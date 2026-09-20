import json
from collections.abc import Callable
from pathlib import Path

import pytest

from coreelec_reconciler.domain.execution import (
    ActiveDeviceRun,
    AuthorityPhase,
    DeviceLease,
    MutationDisposition,
    Presence,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RevisionLease,
    RunStatus,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.execution.authority import (
    AuthorityAcquisitionRequest,
    AuthorityCoordinator,
    _RemoteAuthority,
)
from coreelec_reconciler.execution.run_store import (
    CorruptRunStore,
    RunStore,
    RunStoreError,
)
from coreelec_reconciler.reporting.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.reporting.execution_documents import (
    build_execution_run_report,
)
from coreelec_reconciler.transports.remote_ownership import (
    AuthorityBlocked,
    AuthorityConflict,
    RemoteObject,
    RemoteObjectKind,
)
from tests.fakes.device import FakeDevice


def identity(**changes: str) -> RemoteOwnershipIdentity:
    values = {
        "device_id": "device.test",
        "run_id": "run.test",
        "workspace_id": "workspace:test",
        "plan_id": "plan.test",
        "plan_full_digest": "sha256:plan",
        "binding_digest": "sha256:binding",
        "boot_id": "boot.test",
    }
    values.update(changes)
    return RemoteOwnershipIdentity(
        DeviceId(values["device_id"]),
        RunId(values["run_id"]),
        WorkspaceId(values["workspace_id"]),
        values["plan_id"],
        values["plan_full_digest"],
        values["binding_digest"],
        values["boot_id"],
    )


def acquire() -> tuple[FakeDevice, _RemoteAuthority, RemoteOwnership]:
    device = FakeDevice()
    authority = _RemoteAuthority(device)
    owned = authority.acquire_exclusive(
        identity(), b"secret-token", updated_at="2026-09-19T00:00:00Z"
    )
    return device, authority, owned


def test_exclusive_acquisition_has_one_winner_and_no_token_in_marker() -> None:
    device, authority, owned = acquire()

    assert authority.inspect("device.test").presence is Presence.PRESENT
    assert b"secret-token" not in (device.inspector().ownership().payload or b"")
    with pytest.raises(AuthorityConflict):
        authority.acquire_exclusive(
            identity(run_id="run.other"),
            b"other-token",
            updated_at="2026-09-19T00:00:01Z",
        )
    assert owned.generation == 1


@pytest.mark.parametrize(
    "kind",
    [
        RemoteObjectKind.SYMLINK,
        RemoteObjectKind.DIRECTORY,
        RemoteObjectKind.OTHER,
        RemoteObjectKind.UNKNOWN,
    ],
)
def test_foreign_nonregular_or_unknown_marker_fails_closed(
    kind: RemoteObjectKind,
) -> None:
    device = FakeDevice()
    device.set_remote_ownership(RemoteObject(kind, b"foreign"))
    authority = _RemoteAuthority(device)

    assert authority.inspect("device.test").presence is Presence.UNKNOWN
    with pytest.raises(AuthorityConflict):
        authority.acquire_exclusive(
            identity(), b"token", updated_at="2026-09-19T00:00:00Z"
        )


def test_malformed_marker_is_unknown_and_blocks() -> None:
    device = FakeDevice()
    device.set_remote_ownership(RemoteObject(RemoteObjectKind.REGULAR, b"{}"))
    authority = _RemoteAuthority(device)
    assert authority.inspect("device.test").presence is Presence.UNKNOWN


def test_remote_durability_failure_never_grants_authority() -> None:
    device = FakeDevice()
    device.fail_remote_durability()
    with pytest.raises(AuthorityBlocked):
        _RemoteAuthority(device).acquire_exclusive(
            identity(), b"token", updated_at="2026-09-19T00:00:00Z"
        )
    assert device.inspector().ownership().kind is RemoteObjectKind.ABSENT


def test_checkpoint_durability_failure_retains_prior_marker() -> None:
    device, authority, owned = acquire()
    original = device.inspector().ownership()
    device.fail_remote_durability()

    with pytest.raises(AuthorityBlocked):
        authority.compare_and_update(
            owned,
            b"secret-token",
            RemoteMarkerPhase.ACQUIRED,
            RemoteMarkerPhase.PREPARING,
            None,
            updated_at="2026-09-19T00:00:01Z",
        )

    assert device.inspector().ownership() == original


def test_checkpoint_update_release_and_quarantine_are_durable() -> None:
    device, authority, owned = acquire()
    preparing = authority.compare_and_update(
        owned,
        b"secret-token",
        RemoteMarkerPhase.ACQUIRED,
        RemoteMarkerPhase.PREPARING,
        None,
        updated_at="2026-09-19T00:00:01Z",
    )
    prepared = authority.compare_and_update(
        preparing,
        b"secret-token",
        RemoteMarkerPhase.PREPARING,
        RemoteMarkerPhase.PREPARED,
        "sha256:manifest",
        updated_at="2026-09-19T00:00:02Z",
    )
    releasing = authority.compare_and_update(
        prepared,
        b"secret-token",
        RemoteMarkerPhase.PREPARED,
        RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
        "sha256:terminal",
        updated_at="2026-09-19T00:00:03Z",
    )
    receipt = authority.release(releasing, b"secret-token", "sha256:terminal")
    assert receipt.disposition is MutationDisposition.APPLIED
    assert device.inspector().ownership().kind is RemoteObjectKind.ABSENT

    owned = authority.acquire_exclusive(
        identity(run_id="run.second"),
        b"second-token",
        updated_at="2026-09-19T00:00:04Z",
    )
    pending = authority.compare_and_update(
        owned,
        b"second-token",
        RemoteMarkerPhase.ACQUIRED,
        RemoteMarkerPhase.QUARANTINE_PENDING,
        None,
        updated_at="2026-09-19T00:00:05Z",
    )
    quarantine = authority.quarantine(
        pending,
        b"second-token",
        "sha256:incident",
        updated_at="2026-09-19T00:00:06Z",
    )
    assert quarantine.incident_receipt_digest == "sha256:incident"
    assert device.inspector().quarantine().kind is RemoteObjectKind.REGULAR
    assert authority.inspect_quarantine("device.test") is Presence.PRESENT
    assert authority.inspect("device.test").presence is Presence.UNKNOWN
    with pytest.raises(AuthorityBlocked):
        authority.acquire_exclusive(
            identity(run_id="run.third"),
            b"third-token",
            updated_at="2026-09-19T00:00:07Z",
        )


def test_quarantine_race_is_part_of_atomic_exclusive_create() -> None:
    device = FakeDevice()
    device.race_quarantine_on_next_acquire()

    with pytest.raises(AuthorityConflict):
        _RemoteAuthority(device).acquire_exclusive(
            identity(), b"token", updated_at="2026-09-19T00:00:00Z"
        )

    assert device.inspector().ownership().kind is RemoteObjectKind.ABSENT
    assert device.inspector().quarantine().kind is RemoteObjectKind.REGULAR


def test_release_requires_matching_terminal_evidence_and_release_phase() -> None:
    device, authority, owned = acquire()
    with pytest.raises(AuthorityConflict):
        authority.release(owned, b"secret-token", "sha256:terminal")
    preparing = authority.compare_and_update(
        owned,
        b"secret-token",
        RemoteMarkerPhase.ACQUIRED,
        RemoteMarkerPhase.PREPARING,
        None,
        updated_at="2026-09-19T00:00:01Z",
    )
    releasing = authority.compare_and_update(
        preparing,
        b"secret-token",
        RemoteMarkerPhase.PREPARING,
        RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
        "sha256:terminal",
        updated_at="2026-09-19T00:00:02Z",
    )
    with pytest.raises(AuthorityConflict):
        authority.release(releasing, b"secret-token", "sha256:other")
    assert device.inspector().ownership().kind is RemoteObjectKind.REGULAR


@pytest.mark.parametrize(
    ("current", "next_phase"),
    [
        (RemoteMarkerPhase.ACQUIRED, RemoteMarkerPhase.PREPARED),
        (RemoteMarkerPhase.PREPARING, RemoteMarkerPhase.MUTATING),
        (RemoteMarkerPhase.PREPARED, RemoteMarkerPhase.VERIFYING),
        (RemoteMarkerPhase.TERMINAL_RELEASE_PENDING, RemoteMarkerPhase.MUTATING),
    ],
)
def test_illegal_phase_jumps_are_rejected(
    current: RemoteMarkerPhase, next_phase: RemoteMarkerPhase
) -> None:
    _, authority, owned = acquire()
    handle = owned
    if current in {
        RemoteMarkerPhase.PREPARING,
        RemoteMarkerPhase.PREPARED,
    }:
        handle = authority.compare_and_update(
            handle,
            b"secret-token",
            RemoteMarkerPhase.ACQUIRED,
            RemoteMarkerPhase.PREPARING,
            None,
            updated_at="2026-09-19T00:00:01Z",
        )
    if current is RemoteMarkerPhase.PREPARED:
        handle = authority.compare_and_update(
            handle,
            b"secret-token",
            RemoteMarkerPhase.PREPARING,
            RemoteMarkerPhase.PREPARED,
            "sha256:manifest",
            updated_at="2026-09-19T00:00:02Z",
        )
    if current is RemoteMarkerPhase.TERMINAL_RELEASE_PENDING:
        handle = authority.compare_and_update(
            handle,
            b"secret-token",
            RemoteMarkerPhase.ACQUIRED,
            RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            "sha256:terminal",
            updated_at="2026-09-19T00:00:01Z",
        )
    with pytest.raises(AuthorityConflict):
        authority.compare_and_update(
            handle,
            b"secret-token",
            current,
            next_phase,
            None,
            updated_at="2026-09-19T00:00:01Z",
        )


class _Runtime:
    def __init__(self, events: list[str], fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    def new_ownership_token(self) -> bytes:
        self.events.append("runtime.token")
        if self.fail:
            raise RuntimeError("token unavailable")
        return b"coordinator-token"


class _Store:
    def __init__(
        self,
        events: list[str],
        *,
        active: bool = False,
        fail: str | None = None,
    ) -> None:
        self.events = events
        self.active = active
        self.fail = fail
        self.find_count = 0

    def acquire_device(self, device_id: DeviceId) -> DeviceLease:
        self.events.append("local.acquire-device")
        if self.fail == "lease":
            raise RunStoreError("lease failed")
        return DeviceLease(device_id, "device-lease")

    def find_active_by_device(self, device_id: DeviceId) -> tuple[ActiveDeviceRun, ...]:
        self.events.append("local.find-active")
        self.find_count += 1
        if self.fail == "index":
            raise RunStoreError("index failed")
        if self.fail in {"corrupt-once", "rebuild"} and self.find_count == 1:
            raise CorruptRunStore("index corrupt")
        if not self.active:
            return ()
        return (
            ActiveDeviceRun(
                RunId("run.active"),
                WorkspaceId("workspace:active"),
                1,
                "sha256:active",
                RunStatus.EXECUTING,
                AuthorityPhase.REMOTE_OWNED,
            ),
        )

    def rebuild_active_device_index(self) -> tuple[ActiveDeviceRun, ...]:
        self.events.append("local.rebuild-index")
        if self.fail == "rebuild":
            raise RunStoreError("rebuild failed")
        return ()

    def create_run(
        self,
        device_lease: DeviceLease,
        run_id: RunId,
        device_id: DeviceId,
        ownership_token: bytes,
        ownership_token_digest: str,
        initial_payload: bytes,
    ) -> tuple[RevisionLease, WorkspaceId]:
        del device_lease, device_id, ownership_token, ownership_token_digest
        self.events.append("local.create-run-token-index")
        if self.fail == "create":
            raise RunStoreError("create failed")
        assert initial_payload == b"initial"
        workspace = WorkspaceId("workspace:test")
        return RevisionLease(run_id, workspace, "revision-lease"), workspace

    def release_device(self, lease: DeviceLease) -> None:
        del lease
        self.events.append("local.release-device")

    def release_run(self, lease: RevisionLease) -> None:
        del lease
        self.events.append("local.release-run")

    def load_ownership_token(self, lease: RevisionLease) -> bytes:
        del lease
        self.events.append("local.load-token")
        return b"coordinator-token"


class _RecordingDevice(FakeDevice):
    def __init__(
        self,
        events: list[str],
        before_create: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.events = events
        self.before_create = before_create

    def create_ownership_if_unowned_and_not_quarantined(
        self, device_key: str, payload: bytes, expected_digest: str
    ) -> None:
        self.events.append("remote.create")
        if self.before_create is not None:
            self.before_create()
        super().create_ownership_if_unowned_and_not_quarantined(
            device_key, payload, expected_digest
        )


def _request() -> AuthorityAcquisitionRequest:
    return AuthorityAcquisitionRequest(
        device_id=DeviceId("device.test"),
        run_id=RunId("run.test"),
        initial_revision=lambda digest: b"initial",
        identity=lambda workspace: identity(workspace_id=workspace.value),
        updated_at="2026-09-19T00:00:00Z",
    )


@pytest.mark.parametrize("failure", ["lease", "index", "rebuild", "create"])
def test_coordinator_never_creates_remote_ownership_after_local_failure(
    failure: str,
) -> None:
    events: list[str] = []
    coordinator = AuthorityCoordinator(
        _Store(events, fail=failure), _Runtime(events), _RecordingDevice(events)
    )
    with pytest.raises(RunStoreError):
        coordinator.acquire(_request())
    assert "remote.create" not in events


def test_coordinator_blocks_an_existing_active_local_run() -> None:
    events: list[str] = []
    coordinator = AuthorityCoordinator(
        _Store(events, active=True), _Runtime(events), _RecordingDevice(events)
    )
    with pytest.raises(AuthorityBlocked):
        coordinator.acquire(_request())
    assert "runtime.token" not in events
    assert "remote.create" not in events


def test_coordinator_never_creates_remote_ownership_after_token_failure() -> None:
    events: list[str] = []
    coordinator = AuthorityCoordinator(
        _Store(events), _Runtime(events, fail=True), _RecordingDevice(events)
    )
    with pytest.raises(RuntimeError):
        coordinator.acquire(_request())
    assert "remote.create" not in events


def test_coordinator_rebuilds_corrupt_index_before_remote_acquisition() -> None:
    events: list[str] = []
    coordinator = AuthorityCoordinator(
        _Store(events, fail="corrupt-once"),
        _Runtime(events),
        _RecordingDevice(events),
    )
    coordinator.acquire(_request())
    assert events == [
        "local.acquire-device",
        "local.find-active",
        "local.rebuild-index",
        "local.find-active",
        "runtime.token",
        "local.create-run-token-index",
        "remote.create",
    ]


def test_coordinator_enforces_local_token_index_before_remote_create() -> None:
    events: list[str] = []
    coordinator = AuthorityCoordinator(
        _Store(events), _Runtime(events), _RecordingDevice(events)
    )
    result = coordinator.acquire(_request())
    assert result.ownership.phase is RemoteMarkerPhase.ACQUIRED
    assert events == [
        "local.acquire-device",
        "local.find-active",
        "runtime.token",
        "local.create-run-token-index",
        "remote.create",
    ]


class _ObservedRunStore(RunStore):
    created_lease: RevisionLease | None = None

    def create_run(
        self,
        device_lease: DeviceLease,
        run_id: RunId,
        device_id: DeviceId,
        ownership_token: bytes,
        ownership_token_digest: str,
        initial_payload: bytes,
    ) -> tuple[RevisionLease, WorkspaceId]:
        result = super().create_run(
            device_lease,
            run_id,
            device_id,
            ownership_token,
            ownership_token_digest,
            initial_payload,
        )
        self.created_lease = result[0]
        return result


def test_coordinator_uses_durable_run_store_before_remote_create(
    tmp_path: Path,
) -> None:
    fixture = (
        Path(__file__).parents[2] / "fixtures" / "canonical" / "execution-ready.json"
    )
    value = decode_json_object(fixture.read_bytes())
    device_id = DeviceId(str(value["device_id"]))
    run_id = RunId(str(value["run_id"]))
    store = _ObservedRunStore(tmp_path / "store")
    events: list[str] = []

    def initial_revision(token_digest: str) -> bytes:
        authority = value["authority"]
        assert isinstance(authority, dict)
        authority["ownership_token_digest"] = token_digest
        return build_execution_run_report(value).canonical_bytes

    def prove_local_durability() -> None:
        assert store.created_lease is not None
        assert store.load_ownership_token(store.created_lease) == b"coordinator-token"
        active = store.find_active_by_device(device_id)
        assert tuple(item.run_id for item in active) == (run_id,)

    coordinator = AuthorityCoordinator(
        store,
        _Runtime(events),
        _RecordingDevice(events, prove_local_durability),
    )
    acquired = coordinator.acquire(
        AuthorityAcquisitionRequest(
            device_id=device_id,
            run_id=run_id,
            initial_revision=initial_revision,
            identity=lambda workspace: RemoteOwnershipIdentity(
                device_id,
                run_id,
                workspace,
                str(value["plan_reference"]["plan_id"]),  # type: ignore[index]
                str(value["plan_reference"]["plan_full_digest"]),  # type: ignore[index]
                str(value["authority"]["binding_digest"]),  # type: ignore[index]
                str(value["authority"]["boot_id"]),  # type: ignore[index]
            ),
            updated_at="2026-09-19T00:00:00Z",
        )
    )
    assert acquired.ownership.phase is RemoteMarkerPhase.ACQUIRED
    store.release_run(acquired.revision_lease)
    store.release_device(acquired.device_lease)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("device_id", "device.other"),
        ("run_id", "run.other"),
        ("workspace_id", "workspace:other"),
        ("plan_id", "plan.other"),
        ("plan_full_digest", "sha256:other-plan"),
        ("binding_digest", "sha256:other-binding"),
        ("boot_id", "boot.other"),
        ("token_digest", "sha256:other-token"),
        ("generation", 99),
        ("phase", "preparing"),
    ],
)
def test_checkpoint_rejects_every_identity_phase_generation_mismatch(
    field: str, replacement: str | int
) -> None:
    device, authority, owned = acquire()
    payload = device.inspector().ownership().payload
    assert payload is not None
    value = json.loads(payload)
    value[field] = replacement
    device.set_remote_ownership(
        RemoteObject(RemoteObjectKind.REGULAR, canonical_document_bytes(value))
    )

    with pytest.raises(AuthorityConflict):
        authority.verify_checkpoint(owned, RemoteMarkerPhase.ACQUIRED)


def test_checkpoint_rejects_wrong_handle_marker_digest_and_token_credential() -> None:
    _, authority, owned = acquire()
    with pytest.raises(AuthorityConflict):
        authority.verify_checkpoint(
            RemoteOwnership(
                owned.identity,
                owned.token_digest,
                owned.generation,
                owned.phase,
                "sha256:wrong",
            ),
            RemoteMarkerPhase.ACQUIRED,
        )
    with pytest.raises(AuthorityConflict):
        authority.compare_and_update(
            owned,
            b"wrong-token",
            RemoteMarkerPhase.ACQUIRED,
            RemoteMarkerPhase.PREPARING,
            None,
            updated_at="2026-09-19T00:00:01Z",
        )
