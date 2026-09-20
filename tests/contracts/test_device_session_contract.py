import base64
import io
from typing import ClassVar

import paramiko
import pytest

from coreelec_reconciler.adapters.managed_mutation_helper import (
    FixedManagedMutationHelper,
)
from coreelec_reconciler.adapters.paramiko_session import (
    CommandFailureCode,
    CommandOutcome,
    ParamikoCommandRunner,
    ParamikoDeviceSession,
    ParamikoSessionFactory,
    SessionError,
    SessionFailureCode,
)
from coreelec_reconciler.adapters.remote_helpers import (
    _NO_FOLLOW_READER,
    FixedNoFollowReader,
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
from tests.adapters.scripted import ScriptedCommands, ScriptedLeastAuthoritySession


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


@pytest.mark.parametrize(
    ("exit_status", "code"),
    [
        (40, "not_found"),
        (41, "unsafe"),
        (42, "too_large"),
        (43, "incomplete"),
        (44, "unreadable"),
        (45, "transport"),
    ],
)
def test_fixed_no_follow_read_failures_are_typed(exit_status: int, code: str) -> None:
    commands = ScriptedCommands([CommandOutcome(b"", b"private", exit_status)])
    result = FixedNoFollowReader(commands).read("/storage/file", 12)
    assert result.failure is not None
    assert result.failure.code.value == code
    assert "private" not in result.failure.safe_message


def test_fixed_no_follow_read_preserves_exact_bytes() -> None:
    commands = ScriptedCommands([CommandOutcome(b"\x00value\xff", b"", 0)])
    result = FixedNoFollowReader(commands).read("/storage/file", 12)
    assert result.value == b"\x00value\xff"


def test_fixed_no_follow_read_rejects_oversize_success_payload() -> None:
    commands = ScriptedCommands([CommandOutcome(b"too-large", b"", 0)])
    result = FixedNoFollowReader(commands).read("/storage/file", 3)
    assert result.failure is not None
    assert result.failure.code.value == "too_large"


def test_fixed_reader_walks_every_absolute_path_component_without_following() -> None:
    script = _NO_FOLLOW_READER.decode()
    assert "dir_fd=" in script
    assert "os.O_DIRECTORY | os.O_NOFOLLOW" in script
    assert "component in ('', '.', '..')" in script
    assert "os.open('/', os.O_RDONLY | os.O_DIRECTORY)" in script
    assert "for descriptor in reversed(descriptors)" in script
    assert "os.close(descriptor)" in script


@pytest.mark.parametrize(
    "scenario",
    [
        "symlinked_intermediate_parent",
        "intermediate_parent_swap",
        "final_symlink",
        "non_directory_parent",
    ],
)
def test_no_follow_path_hazards_fail_closed(scenario: str) -> None:
    commands = ScriptedCommands([CommandOutcome(b"", scenario.encode(), 41)])
    result = FixedNoFollowReader(commands).read("/storage/safe/file", 100)
    assert result.failure is not None
    assert result.failure.code.value == "unsafe"
    assert scenario not in result.failure.safe_message


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
        frozenset({"managed_file.read"}),
    )
    session.close()
    session.close()
    assert sftp.closed
    assert client.closed


def test_managed_file_only_session_exposes_no_command_runner() -> None:
    session = ParamikoDeviceSession(
        Closable(),  # type: ignore[arg-type]
        Closable(),  # type: ignore[arg-type]
        DeviceIdentity(DeviceId("device.test"), "sha256:binding", "boot"),
        DeviceCapabilitySnapshot(None, True),
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        frozenset({"managed_file.read"}),
    )
    assert not hasattr(session, "commands")
    assert not hasattr(session.managed_files, "remove")
    with pytest.raises(SessionError, match="mutation"):
        _ = session.managed_file_mutations


def test_unrequested_managed_file_capability_is_inaccessible() -> None:
    session = ParamikoDeviceSession(
        Closable(),  # type: ignore[arg-type]
        Closable(),  # type: ignore[arg-type]
        DeviceIdentity(DeviceId("device.test"), "sha256:binding", "boot"),
        DeviceCapabilitySnapshot(None, True),
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        frozenset({"remote_run_ownership"}),
    )
    with pytest.raises(SessionError, match="not requested"):
        _ = session.managed_files


@pytest.mark.parametrize("adapter_kind", ["fake", "paramiko"])
def test_shared_session_least_authority_contract(adapter_kind: str) -> None:
    if adapter_kind == "fake":
        session: object = ScriptedLeastAuthoritySession(
            frozenset({"managed_file.read"})
        )
    else:
        session = ParamikoDeviceSession(
            Closable(),  # type: ignore[arg-type]
            Closable(),  # type: ignore[arg-type]
            DeviceIdentity(DeviceId("device.test"), "sha256:binding", "boot"),
            DeviceCapabilitySnapshot(None, False),
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            frozenset({"managed_file.read"}),
        )
    assert not hasattr(session, "commands")
    read_view = session.managed_files  # type: ignore[attr-defined]
    assert callable(read_view.read)
    assert not hasattr(read_view, "remove")


class ActiveTransport:
    def is_active(self) -> bool:
        return True


class OrderedSFTP:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def close(self) -> None:
        self.events.append("sftp.close")

    def posix_rename(self, source: str, destination: str) -> None:
        del source, destination


class OpenClient(RejectingClient):
    events: ClassVar[list[str]] = []

    def __init__(self) -> None:
        super().__init__()
        self.sftp = OrderedSFTP(self.events)

    def connect(self, **kwargs: object) -> None:
        del kwargs

    def get_transport(self) -> ActiveTransport:
        return ActiveTransport()

    def open_sftp(self) -> OrderedSFTP:
        return self.sftp

    def close(self) -> None:
        self.events.append("client.close")
        super().close()


def _session_parameters() -> tuple[MappingHostKeyResolver, DeviceSessionParameters]:
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
    return resolver, DeviceSessionParameters(
        device, SecretValue(private.getvalue().encode())
    )


@pytest.mark.parametrize("failure", ["capability", "boot_id", "validation"])
def test_construction_failure_closes_sftp_before_client(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import coreelec_reconciler.adapters.paramiko_session as session_module

    OpenClient.events = []
    resolver, parameters = _session_parameters()
    supported = failure != "capability"
    monkeypatch.setattr(
        FixedNoFollowReader,
        "supported",
        lambda self: supported,
    )
    monkeypatch.setattr(
        FixedManagedMutationHelper,
        "supported",
        lambda self: True,
    )
    if failure in {"boot_id", "validation"}:

        def fail_boot_id(commands: object) -> str:
            del commands
            if failure == "validation":
                raise ValueError("private validation detail")
            raise SessionError(
                SessionFailureCode.CAPABILITY, "Device boot identity is invalid"
            )

        monkeypatch.setattr(session_module, "_read_boot_id", fail_boot_id)
    factory = ParamikoSessionFactory(
        resolver,
        client_factory=OpenClient,  # type: ignore[arg-type]
    )
    with pytest.raises(SessionError):
        factory.open(parameters, frozenset({"managed_file.read"}))
    assert OpenClient.events == ["sftp.close", "client.close"]


def test_missing_server_cas_capability_closes_sftp_before_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    OpenClient.events = []
    resolver, parameters = _session_parameters()
    monkeypatch.setattr(FixedNoFollowReader, "supported", lambda self: True)
    monkeypatch.setattr(
        FixedManagedMutationHelper,
        "supported",
        lambda self: False,
    )
    factory = ParamikoSessionFactory(
        resolver,
        client_factory=OpenClient,  # type: ignore[arg-type]
    )

    with pytest.raises(SessionError):
        factory.open(
            parameters,
            frozenset({"managed_file.write", "atomic_replace_over_existing"}),
        )

    assert OpenClient.events == ["sftp.close", "client.close"]
