"""Pinned-host-key Paramiko sessions with typed command outcomes."""

import hashlib
import io
import time
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import paramiko

from coreelec_reconciler.config.device import DeviceSessionParameters
from coreelec_reconciler.transports.interfaces import (
    DeviceCapabilitySnapshot,
    DeviceIdentity,
    ReadResult,
)

from .managed_mutation_helper import FixedManagedMutationHelper
from .paramiko_managed_file import ParamikoManagedFiles
from .remote_helpers import FixedNoFollowReader, FixedRemoteHelper
from .remote_run_ownership import ParamikoRemoteAuthorityBackend
from .secrets import HostKeyResolver


class SessionFailureCode(StrEnum):
    HOST_KEY_REJECTED = "host_key_rejected"
    AUTHENTICATION = "authentication"
    TIMEOUT = "timeout"
    DISCONNECTED = "disconnected"
    TRANSPORT = "transport"
    CAPABILITY = "capability"


class SessionError(RuntimeError):
    def __init__(self, code: SessionFailureCode, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class CommandFailureCode(StrEnum):
    TIMEOUT = "timeout"
    DISCONNECTED = "disconnected"
    TRANSPORT = "transport"


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    stdout: bytes
    stderr: bytes
    exit_status: int | None
    failure: CommandFailureCode | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure is None and self.exit_status == 0


class CommandRunner(Protocol):
    def execute(
        self, command: str, *, stdin: bytes = b"", timeout: float = 15.0
    ) -> CommandOutcome: ...


class ParamikoCommandRunner:
    def __init__(self, transport: paramiko.Transport) -> None:
        self._transport = transport

    def execute(
        self, command: str, *, stdin: bytes = b"", timeout: float = 15.0
    ) -> CommandOutcome:
        channel: paramiko.Channel | None = None
        stdout = bytearray()
        stderr = bytearray()
        deadline = time.monotonic() + timeout
        try:
            channel = self._transport.open_session(timeout=timeout)
            channel.settimeout(min(timeout, 0.25))
            channel.exec_command(command)
            if stdin:
                channel.sendall(stdin)
            channel.shutdown_write()
            while True:
                while channel.recv_ready():
                    stdout.extend(channel.recv(65_536))
                while channel.recv_stderr_ready():
                    stderr.extend(channel.recv_stderr(65_536))
                if channel.exit_status_ready():
                    while channel.recv_ready():
                        stdout.extend(channel.recv(65_536))
                    while channel.recv_stderr_ready():
                        stderr.extend(channel.recv_stderr(65_536))
                    return CommandOutcome(
                        bytes(stdout), bytes(stderr), channel.recv_exit_status()
                    )
                if time.monotonic() >= deadline:
                    return CommandOutcome(
                        bytes(stdout),
                        bytes(stderr),
                        None,
                        CommandFailureCode.TIMEOUT,
                    )
                time.sleep(0.005)
        except EOFError, paramiko.SSHException:
            return CommandOutcome(
                bytes(stdout),
                bytes(stderr),
                None,
                CommandFailureCode.DISCONNECTED,
            )
        except TimeoutError:
            return CommandOutcome(
                bytes(stdout),
                bytes(stderr),
                None,
                CommandFailureCode.TIMEOUT,
            )
        except OSError:
            code = (
                CommandFailureCode.TIMEOUT
                if time.monotonic() >= deadline
                else CommandFailureCode.TRANSPORT
            )
            return CommandOutcome(bytes(stdout), bytes(stderr), None, code)
        finally:
            if channel is not None:
                channel.close()


@dataclass(frozen=True, slots=True)
class ManagedFileReadView:
    _files: ParamikoManagedFiles

    def lstat(self, path: str) -> ReadResult:
        return self._files.lstat(path)

    def read(self, path: str, limit: int) -> ReadResult:
        return self._files.read(path, limit)


@dataclass(slots=True, repr=False)
class ParamikoDeviceSession:
    _client: paramiko.SSHClient
    _sftp: paramiko.SFTPClient
    _identity: DeviceIdentity
    _capabilities: DeviceCapabilitySnapshot
    _managed_files: ParamikoManagedFiles
    _commands: ParamikoCommandRunner
    _requested_capabilities: frozenset[str]
    _closed: bool = False

    def __repr__(self) -> str:
        return (
            "ParamikoDeviceSession("
            f"device_id={self._identity.device_id.value!r}, "
            f"capabilities={sorted(self._requested_capabilities)!r}, "
            f"closed={self._closed})"
        )

    @property
    def identity(self) -> DeviceIdentity:
        return self._identity

    @property
    def capabilities(self) -> DeviceCapabilitySnapshot:
        return self._capabilities

    @property
    def managed_files(self) -> ManagedFileReadView:
        if "managed_file.read" not in self._requested_capabilities:
            raise SessionError(
                SessionFailureCode.CAPABILITY,
                "managed-file read capability was not requested",
            )
        return ManagedFileReadView(self._managed_files)

    @property
    def managed_file_mutations(self) -> ParamikoManagedFiles:
        required = {"managed_file.write", "atomic_replace_over_existing"}
        if not required.issubset(self._requested_capabilities):
            raise SessionError(
                SessionFailureCode.CAPABILITY,
                "managed-file mutation capability was not requested",
            )
        return self._managed_files

    def remote_ownership(self, workspace_key: str) -> ParamikoRemoteAuthorityBackend:
        if "remote_run_ownership" not in self._requested_capabilities:
            raise SessionError(
                SessionFailureCode.CAPABILITY,
                "remote ownership capability was not requested",
            )
        return ParamikoRemoteAuthorityBackend(
            self._managed_files,
            FixedRemoteHelper(self._commands),
            workspace_key=workspace_key,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failed = False
        try:
            self._sftp.close()
        except Exception:
            failed = True
        try:
            self._client.close()
        except Exception:
            failed = True
        if failed:
            raise SessionError(
                SessionFailureCode.TRANSPORT,
                "SSH session closure could not be confirmed",
            )

    def __enter__(self) -> ParamikoDeviceSession:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class ParamikoSessionFactory:
    def __init__(
        self,
        host_keys: HostKeyResolver,
        *,
        connect_timeout: float = 15.0,
        client_factory: type[paramiko.SSHClient] = paramiko.SSHClient,
    ) -> None:
        self._host_keys = host_keys
        self._connect_timeout = connect_timeout
        self._client_factory = client_factory

    def open(
        self,
        parameters: DeviceSessionParameters,
        required_capabilities: frozenset[str],
    ) -> ParamikoDeviceSession:
        device = parameters.device
        pinned = self._host_keys.resolve_host_key(device.host_key_reference)
        client = self._client_factory()
        sftp: paramiko.SFTPClient | None = None
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        hostname = device.endpoint.host
        host_key_name = (
            hostname
            if device.endpoint.port == 22
            else f"[{hostname}]:{device.endpoint.port}"
        )
        client.get_host_keys().add(host_key_name, pinned.algorithm, pinned.key)
        try:
            private_key = _load_private_key(parameters.credential.value)
            client.connect(
                hostname=hostname,
                port=device.endpoint.port,
                username=device.ssh_username,
                pkey=private_key,
                allow_agent=False,
                look_for_keys=False,
                timeout=self._connect_timeout,
                banner_timeout=self._connect_timeout,
                auth_timeout=self._connect_timeout,
            )
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise SessionError(
                    SessionFailureCode.DISCONNECTED,
                    "SSH transport did not become active",
                )
            sftp = client.open_sftp()
            commands = ParamikoCommandRunner(transport)
            reader = FixedNoFollowReader(commands)
            no_follow_read = reader.supported()
            mutation_helper = FixedManagedMutationHelper(commands)
            cas_mutations = mutation_helper.supported()
            managed = ParamikoManagedFiles(
                sftp,
                reader if no_follow_read else None,
                mutation_helper if cas_mutations else None,
            )
            available_capabilities = DeviceCapabilitySnapshot(
                device.profile_root, cas_mutations
            )
            _require_capabilities(
                available_capabilities,
                required_capabilities,
                no_follow_read=no_follow_read,
            )
            capabilities = DeviceCapabilitySnapshot(
                device.profile_root
                if required_capabilities.intersection(
                    {"managed_file.read", "managed_file.write"}
                )
                else None,
                available_capabilities.atomic_replace_over_existing
                and "atomic_replace_over_existing" in required_capabilities,
            )
            boot_id = _read_boot_id(commands)
            binding = b"\0".join(
                (
                    device.id.value.encode(),
                    hostname.encode(),
                    str(device.endpoint.port).encode(),
                    device.ssh_username.encode(),
                    pinned.key.asbytes(),
                    device.profile_root.path.encode(),
                )
            )
            identity = DeviceIdentity(
                device.id,
                "sha256:" + hashlib.sha256(binding).hexdigest(),
                boot_id,
            )
            return ParamikoDeviceSession(
                client,
                sftp,
                identity,
                capabilities,
                managed,
                commands,
                required_capabilities,
            )
        except SessionError:
            _close_failed_session(sftp, client)
            raise
        except paramiko.BadHostKeyException:
            _close_failed_session(sftp, client)
            raise SessionError(
                SessionFailureCode.HOST_KEY_REJECTED,
                "pinned SSH host key was rejected",
            ) from None
        except paramiko.AuthenticationException:
            _close_failed_session(sftp, client)
            raise SessionError(
                SessionFailureCode.AUTHENTICATION, "SSH authentication failed"
            ) from None
        except TimeoutError:
            _close_failed_session(sftp, client)
            raise SessionError(
                SessionFailureCode.TIMEOUT, "SSH connection timed out"
            ) from None
        except EOFError, paramiko.SSHException, OSError:
            _close_failed_session(sftp, client)
            raise SessionError(
                SessionFailureCode.TRANSPORT, "SSH session could not be established"
            ) from None
        except Exception:
            _close_failed_session(sftp, client)
            raise SessionError(
                SessionFailureCode.TRANSPORT, "SSH session validation failed"
            ) from None


def _load_private_key(value: bytes) -> paramiko.PKey:
    try:
        text = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SessionError(
            SessionFailureCode.AUTHENTICATION, "SSH credential format is unsupported"
        ) from None
    for key_type in (
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
        paramiko.RSAKey,
    ):
        try:
            return key_type.from_private_key(io.StringIO(text))
        except paramiko.SSHException, ValueError:
            continue
    raise SessionError(
        SessionFailureCode.AUTHENTICATION, "SSH credential format is unsupported"
    )


def _require_capabilities(
    capabilities: DeviceCapabilitySnapshot,
    required: frozenset[str],
    *,
    no_follow_read: bool,
) -> None:
    available = {
        "managed_file.write",
        "atomic_replace_over_existing",
        "remote_run_ownership",
    }
    if no_follow_read:
        available.add("managed_file.read")
    if not capabilities.atomic_replace_over_existing:
        available.discard("atomic_replace_over_existing")
    missing = required - available
    if missing:
        raise SessionError(
            SessionFailureCode.CAPABILITY,
            "required Device session capability is unavailable",
        )


def _close_failed_session(
    sftp: paramiko.SFTPClient | None, client: paramiko.SSHClient
) -> None:
    if sftp is not None:
        with suppress(Exception):
            sftp.close()
    with suppress(Exception):
        client.close()


def _read_boot_id(commands: CommandRunner) -> str:
    outcome = commands.execute("cat /proc/sys/kernel/random/boot_id", timeout=5.0)
    if outcome.failure is not None or outcome.exit_status != 0:
        raise SessionError(
            SessionFailureCode.CAPABILITY, "Device boot identity is unavailable"
        )
    try:
        value = outcome.stdout.decode("ascii").strip()
    except UnicodeDecodeError:
        value = ""
    if (
        not value
        or len(value) > 128
        or any(character not in "0123456789abcdefABCDEF-" for character in value)
    ):
        raise SessionError(
            SessionFailureCode.CAPABILITY, "Device boot identity is invalid"
        )
    return value
