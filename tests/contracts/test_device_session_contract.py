import base64
import io

import paramiko
import pytest

from coreelec_reconciler.adapters.paramiko_session import (
    CommandFailureCode,
    ParamikoCommandRunner,
    ParamikoDeviceSession,
    ParamikoSessionFactory,
    SessionError,
    SessionFailureCode,
)
from coreelec_reconciler.adapters.secrets import (
    EnvironmentSecretResolver,
    MappingHostKeyResolver,
    SecretResolutionError,
)
from coreelec_reconciler.config.device import DeviceSessionParameters, SecretValue
from coreelec_reconciler.domain.configuration import (
    DeviceEndpoint,
    ProfileRootCapability,
    ResolvedDevice,
    SecretReference,
)
from coreelec_reconciler.domain.identifiers import DeviceId
from coreelec_reconciler.transports.interfaces import (
    DeviceCapabilitySnapshot,
    DeviceIdentity,
)


class Channel:
    def __init__(self) -> None:
        self.closed = False
        self.sent = b""
        self.stdout = [b"\\x00out\\xff"]
        self.stderr = [b"\\x80err\\n"]

    def settimeout(self, timeout: float) -> None:
        del timeout

    def exec_command(self, command: str) -> None:
        del command

    def sendall(self, value: bytes) -> None:
        self.sent += value

    def shutdown_write(self) -> None:
        pass

    def recv_ready(self) -> bool:
        return bool(self.stdout)

    def recv(self, size: int) -> bytes:
        del size
        return self.stdout.pop(0)

    def recv_stderr_ready(self) -> bool:
        return bool(self.stderr)

    def recv_stderr(self, size: int) -> bytes:
        del size
        return self.stderr.pop(0)

    def exit_status_ready(self) -> bool:
        return not self.stdout and not self.stderr

    def recv_exit_status(self) -> int:
        return 7

    def close(self) -> None:
        self.closed = True


class Transport:
    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    def open_session(self, timeout: float) -> Channel:
        del timeout
        return self.channel


def test_command_bytes_and_channel_close_are_exact() -> None:
    channel = Channel()
    outcome = ParamikoCommandRunner(Transport(channel)).execute(  # type: ignore[arg-type]
        "fixed-command", stdin=b"\\x00input"
    )
    assert outcome.stdout == b"\\x00out\\xff"
    assert outcome.stderr == b"\\x80err\\n"
    assert outcome.exit_status == 7
    assert outcome.failure is None
    assert channel.sent == b"\\x00input"
    assert channel.closed


class DisconnectTransport:
    def open_session(self, timeout: float) -> Channel:
        del timeout
        raise paramiko.SSHException("private endpoint and credential detail")


def test_command_disconnect_is_typed_and_redacted() -> None:
    outcome = ParamikoCommandRunner(DisconnectTransport()).execute("fixed")  # type: ignore[arg-type]
    assert outcome.failure is CommandFailureCode.DISCONNECTED
    assert outcome.stdout == outcome.stderr == b""


class WaitingChannel(Channel):
    def recv_ready(self) -> bool:
        return False

    def recv_stderr_ready(self) -> bool:
        return False

    def exit_status_ready(self) -> bool:
        return False


def test_command_timeout_is_typed_and_closes_channel() -> None:
    channel = WaitingChannel()
    outcome = ParamikoCommandRunner(Transport(channel)).execute(  # type: ignore[arg-type]
        "fixed", timeout=0
    )
    assert outcome.failure is CommandFailureCode.TIMEOUT
    assert channel.closed


def test_typed_secret_resolution_and_redaction() -> None:
    resolver = EnvironmentSecretResolver(
        {"private-key": "TV_TEST_KEY"}, {"TV_TEST_KEY": "super-secret"}
    )
    value = resolver.resolve(SecretReference("controller.environment", "private-key"))
    assert value.value == b"super-secret"
    assert "super-secret" not in repr(value)
    with pytest.raises(SecretResolutionError, match="provider"):
        resolver.resolve(SecretReference("unsupported", "private-key"))


def test_pinned_host_key_parsing_and_redaction() -> None:
    key = paramiko.RSAKey.generate(1024)
    line = f"{key.get_name()} {key.get_base64()}"
    pinned = MappingHostKeyResolver({"device-key": line}).resolve_host_key("device-key")
    assert pinned.key == key
    assert base64.b64decode(key.get_base64()) not in repr(pinned).encode()


def test_host_key_rejection_is_a_closed_typed_failure() -> None:
    error = SessionError(
        SessionFailureCode.HOST_KEY_REJECTED, "pinned SSH host key was rejected"
    )
    assert error.code is SessionFailureCode.HOST_KEY_REJECTED
    assert "endpoint" not in str(error)


class RejectingClient:
    last: RejectingClient | None = None

    def __init__(self) -> None:
        self.host_keys = paramiko.HostKeys()
        self.closed = False
        RejectingClient.last = self

    def set_missing_host_key_policy(self, policy: object) -> None:
        del policy

    def get_host_keys(self) -> paramiko.HostKeys:
        return self.host_keys

    def connect(self, **kwargs: object) -> None:
        del kwargs
        got = paramiko.RSAKey.generate(1024)
        expected = paramiko.RSAKey.generate(1024)
        raise paramiko.BadHostKeyException("device.example", got, expected)

    def close(self) -> None:
        self.closed = True


def test_factory_rejects_changed_host_key_and_closes_client() -> None:
    host_key = paramiko.RSAKey.generate(1024)
    private_key = paramiko.RSAKey.generate(1024)
    private = io.StringIO()
    private_key.write_private_key(private)
    resolver = MappingHostKeyResolver(
        {"host-key": f"{host_key.get_name()} {host_key.get_base64()}"}
    )
    device = ResolvedDevice(
        DeviceId("device.test"),
        DeviceEndpoint("device.example", 22),
        "root",
        "host-key",
        SecretReference("controller.environment", "private-key"),
        ProfileRootCapability("/storage/.kodi/userdata"),
    )
    factory = ParamikoSessionFactory(
        resolver,
        client_factory=RejectingClient,  # type: ignore[arg-type]
    )
    with pytest.raises(SessionError) as raised:
        factory.open(
            DeviceSessionParameters(device, SecretValue(private.getvalue().encode())),
            frozenset(),
        )
    assert raised.value.code is SessionFailureCode.HOST_KEY_REJECTED
    assert RejectingClient.last is not None
    assert RejectingClient.last.closed


class Closable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_session_closes_sftp_before_client_and_is_idempotent() -> None:
    client = Closable()
    sftp = Closable()
    session = ParamikoDeviceSession(
        client,  # type: ignore[arg-type]
        sftp,  # type: ignore[arg-type]
        DeviceIdentity(DeviceId("device.test"), "sha256:binding", "boot"),
        DeviceCapabilitySnapshot(None, True),
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
    )
    session.close()
    session.close()
    assert sftp.closed
    assert client.closed
