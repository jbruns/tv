import json
from dataclasses import replace
from pathlib import Path

import pytest

from coreelec_reconciler.domain.configuration import ProfileRootCapability
from coreelec_reconciler.domain.execution import (
    DeviceLease,
    RevisionLease,
    SessionCloseDisposition,
    StoredRevision,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.domain.observation import (
    ObservationRunStatus,
)
from coreelec_reconciler.execution.document_family import DocumentAppendIntent
from coreelec_reconciler.execution.observation import (
    CanonicalObservationRuns,
    ObservationInputDigests,
    ObservationResource,
    ObservationResourceContext,
    ObservationRunRequest,
)
from coreelec_reconciler.execution.run_store import CorruptRunStore, RunStore
from coreelec_reconciler.execution.runtime import FiniteRuntimeValues
from coreelec_reconciler.execution.session_close import (
    DurableSessionClose,
    SessionCloseRequest,
)
from coreelec_reconciler.persistence.observation_documents import (
    observation_run_document_family,
)
from coreelec_reconciler.resource_types.builtins import (
    built_in_resource_registry,
)
from coreelec_reconciler.resource_types.descriptor import (
    ErasedResourceObserverAdapter,
    ResourceObservationContext,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
    observe_managed_file,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    resolve_special_profile_path,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry
from coreelec_reconciler.transports.interfaces import (
    EntryKind,
    FileMetadata,
    ReadFailure,
    ReadFailureCode,
    ReadResult,
)

RUN_ID = RunId("019950f8-4c00-7000-8000-000000000901")
DEVICE_ID = DeviceId("device.test")
SHA = "sha256:" + "a" * 64


class _HostileReadContext:
    def __init__(
        self,
        resource_id: str,
        calls: list[str],
        *,
        failure: ReadFailure | None = None,
    ) -> None:
        self._resource_id = resource_id
        self._calls = calls
        self._failure = failure
        self.write_attempts: list[str] = []

    def lstat(self, path: str) -> ReadResult:
        self._calls.append(self._resource_id)
        if self._failure is not None:
            return ReadResult(None, self._failure)
        content = self._resource_id.encode()
        return ReadResult(
            FileMetadata(EntryKind.REGULAR, 0o644, len(content)),
        )

    def read(self, path: str, limit: int) -> ReadResult:
        return ReadResult(self._resource_id.encode())

    def stage_write(self, *args: object) -> object:
        self.write_attempts.append("stage_write")
        raise AssertionError("observation attempted a write")

    def remove(self, *args: object) -> object:
        self.write_attempts.append("remove")
        raise AssertionError("observation attempted a write")


class _InterruptingStore(RunStore):
    def __init__(self, root: Path, boundary: int) -> None:
        registry = built_in_resource_registry()
        super().__init__(
            root,
            resource_registry=registry,
            document_families=(observation_run_document_family(registry),),
        )
        self._boundary = boundary
        self._appends = 0

    def compare_and_append_observation(
        self,
        lease: RevisionLease,
        expected_revision: int,
        expected_digest: str,
        payload: bytes,
        intent: DocumentAppendIntent,
    ) -> StoredRevision:
        stored = super().compare_and_append_observation(
            lease,
            expected_revision,
            expected_digest,
            payload,
            intent,
        )
        self._appends += 1
        if self._appends == self._boundary:
            raise RuntimeError("interrupted after durable boundary")
        return stored


class _InterruptAfterCreateStore(RunStore):
    def create_observation_run(
        self,
        device_lease: DeviceLease,
        run_id: RunId,
        device_id: DeviceId,
        initial_payload: bytes,
    ) -> tuple[RevisionLease, WorkspaceId]:
        result = super().create_observation_run(
            device_lease,
            run_id,
            device_id,
            initial_payload,
        )
        self.release_run(result[0])
        raise RuntimeError("interrupted after durable creation")


def _runtime() -> FiniteRuntimeValues:
    return FiniteRuntimeValues(
        utc_instants=tuple(f"2026-09-20T06:00:{second:02d}Z" for second in range(12))
    )


def _store(root: Path, registry: ResourceRegistry | None = None) -> RunStore:
    selected = registry or built_in_resource_registry()
    return RunStore(
        root,
        resource_registry=selected,
        document_families=(observation_run_document_family(selected),),
    )


def _request(
    calls: list[str],
    *,
    second_failure: ReadFailure | None = None,
    inputs: ObservationInputDigests | None = None,
    resources: tuple[ObservationResource, ...] | None = None,
) -> ObservationRunRequest:
    selected = resources or (
        ObservationResource(
            "resource.base",
            "KodiSmartPlaylist",
            ("special://profile/playlists/video/resource.base.xsp",),
            (),
            ObservationResourceContext(
                DEVICE_ID,
                "resource.base",
                "KodiSmartPlaylist",
                ("special://profile/playlists/video/resource.base.xsp",),
                ProfileRootCapability("/storage"),
                _HostileReadContext("resource.base", calls),
            ),
        ),
        ObservationResource(
            "resource.dependent",
            "KodiSmartPlaylist",
            ("special://profile/playlists/video/resource.dependent.xsp",),
            ("resource.base",),
            ObservationResourceContext(
                DEVICE_ID,
                "resource.dependent",
                "KodiSmartPlaylist",
                ("special://profile/playlists/video/resource.dependent.xsp",),
                ProfileRootCapability("/storage"),
                _HostileReadContext(
                    "resource.dependent", calls, failure=second_failure
                ),
            ),
        ),
    )
    return ObservationRunRequest(
        RUN_ID,
        DEVICE_ID,
        inputs or ObservationInputDigests(SHA, SHA, SHA, SHA, SHA),
        selected,
    )


def test_multi_resource_observation_is_canonical_read_only_and_reportable(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    registry = built_in_resource_registry()
    store = _store(tmp_path / "runs", registry)
    service = CanonicalObservationRuns(store, registry, _runtime())

    result = service.start(
        _request(
            calls,
            second_failure=ReadFailure(
                ReadFailureCode.TRANSPORT,
                "secret transport detail",
            ),
        )
    )

    assert result.status is ObservationRunStatus.OBSERVED_PARTIAL
    assert result.revision == 4
    assert calls == ["resource.base", "resource.dependent"]
    assert tuple(item.resource_id for item in result.checkpoints) == (
        "resource.base",
        "resource.dependent",
    )
    assert (
        result.checkpoints[0].raw_attachments[0].digest
        == (result.checkpoints[0].payload["content_digest"])
    )
    assert result.checkpoints[1].payload["failure_code"] == "transport.transport"
    assert "secret transport detail" not in result.canonical_bytes.decode()
    forbidden = {
        "approvals",
        "authority",
        "changes",
        "desired",
        "mutation",
        "plan",
        "verification",
    }
    assert forbidden.isdisjoint(json.loads(result.canonical_bytes))
    assert store.find_active_by_device(DEVICE_ID) == ()
    assert service.report(RUN_ID) == result
    inspection = service.inspect(RUN_ID)
    assert inspection.run == result
    assert inspection.completed_resource_ids == ("resource.base", "resource.dependent")
    assert inspection.remaining_resource_ids == ()
    assert inspection.terminal


@pytest.mark.parametrize(
    ("boundary", "calls_before_restart"),
    (
        (1, []),
        (2, ["resource.base"]),
        (3, ["resource.base", "resource.dependent"]),
    ),
)
def test_restart_never_reobserves_durable_prefix(
    tmp_path: Path,
    boundary: int,
    calls_before_restart: list[str],
) -> None:
    calls: list[str] = []
    registry = built_in_resource_registry()
    store = _InterruptingStore(tmp_path / "runs", boundary)
    service = CanonicalObservationRuns(store, registry, _runtime())
    request = _request(calls)

    with pytest.raises(RuntimeError, match="durable boundary"):
        service.start(request)

    assert calls == calls_before_restart
    result = service.restart(request)
    assert result.status is ObservationRunStatus.OBSERVED
    assert calls == ["resource.base", "resource.dependent"]
    assert service.restart(request) == result
    assert calls == ["resource.base", "resource.dependent"]


def test_restart_after_initial_creation_observes_every_resource_once(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    registry = built_in_resource_registry()
    root = tmp_path / "runs"
    store = _InterruptAfterCreateStore(
        root,
        resource_registry=registry,
        document_families=(observation_run_document_family(registry),),
    )
    service = CanonicalObservationRuns(store, registry, _runtime())
    request = _request(calls)

    with pytest.raises(RuntimeError, match="durable creation"):
        service.start(request)

    assert calls == []
    result = service.restart(request)
    assert result.status is ObservationRunStatus.OBSERVED
    assert calls == ["resource.base", "resource.dependent"]


def test_restart_rejects_scope_codec_and_selection_changes(tmp_path: Path) -> None:
    calls: list[str] = []
    registry = built_in_resource_registry()
    store = _InterruptingStore(tmp_path / "runs", 1)
    request = _request(calls)
    service = CanonicalObservationRuns(store, registry, _runtime())
    with pytest.raises(RuntimeError):
        service.start(request)

    changed_inputs = replace(
        request,
        inputs=replace(request.inputs, configuration="sha256:" + "b" * 64),
    )
    with pytest.raises(ValueError, match="scope binding changed"):
        service.restart(changed_inputs)
    with pytest.raises(ValueError, match="dependency ordered"):
        service.restart(replace(request, resources=tuple(reversed(request.resources))))
    with pytest.raises(ValueError, match="scope binding changed"):
        service.restart(replace(request, resources=request.resources[:1]))

    descriptor = registry.descriptor("KodiSmartPlaylist")
    assert descriptor is not None
    changed_registry = ResourceRegistry.create(
        (replace(descriptor, observation_policy_digest="sha256:" + "c" * 64),)
    )
    changed_service = CanonicalObservationRuns(store, changed_registry, _runtime())
    with pytest.raises(ValueError, match="scope binding changed"):
        changed_service.restart(request)


@pytest.mark.parametrize("damage", ["tamper", "gap"])
def test_report_rejects_tampered_or_gapped_chain(
    tmp_path: Path,
    damage: str,
) -> None:
    registry = built_in_resource_registry()
    root = tmp_path / "runs"
    service = CanonicalObservationRuns(_store(root, registry), registry, _runtime())
    service.start(_request([]))
    workspace = next((root / "runs").iterdir())
    revisions = workspace / "revisions"
    if damage == "gap":
        (revisions / "00000002.json").unlink()
    else:
        path = revisions / "00000003.json"
        value = json.loads(path.read_bytes())
        value["scope"]["configuration_digest"] = "sha256:" + "b" * 64
        path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(CorruptRunStore):
        service.report(RUN_ID)


def test_rejects_missing_codec_and_invalid_selection(tmp_path: Path) -> None:
    calls: list[str] = []
    registry = built_in_resource_registry()
    descriptor = registry.descriptor("KodiSmartPlaylist")
    assert descriptor is not None
    incomplete = ResourceRegistry.create(
        (replace(descriptor, encode_observation_evidence=None),)
    )
    service = CanonicalObservationRuns(
        _store(tmp_path / "missing", incomplete),
        incomplete,
        _runtime(),
    )
    with pytest.raises(ValueError, match="complete observation codec"):
        service.start(_request(calls))

    duplicate = _request(calls)
    with pytest.raises(ValueError, match="unique"):
        CanonicalObservationRuns(
            _store(tmp_path / "duplicate", registry),
            registry,
            _runtime(),
        ).start(replace(duplicate, resources=(duplicate.resources[0],) * 2))

    wrong_address = replace(
        duplicate.resources[0],
        state_addresses=("special://profile/../wrong.xsp",),
        context=replace(
            duplicate.resources[0].context,
            state_addresses=("special://profile/../wrong.xsp",),
        ),
    )
    with pytest.raises(ValueError, match="State Address"):
        CanonicalObservationRuns(
            _store(tmp_path / "address", registry),
            registry,
            _runtime(),
        ).start(replace(duplicate, resources=(wrong_address,)))
    assert calls == []


def test_resource_type_mismatch_fails_before_observation(tmp_path: Path) -> None:
    calls: list[str] = []
    request = _request(calls)
    selected = request.resources[0]
    wrong_type = replace(
        selected,
        resource_type="WrongType",
        context=replace(selected.context, resource_type="WrongType"),
    )
    registry = built_in_resource_registry()

    with pytest.raises(ValueError, match="complete observation codec"):
        CanonicalObservationRuns(
            _store(tmp_path / "wrong-type", registry),
            registry,
            _runtime(),
        ).start(replace(request, resources=(wrong_type,)))

    assert calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resource_type", "WrongType"),
        ("state_addresses", ("special://profile/playlists/video/wrong.xsp",)),
        ("device_id", DeviceId("other-device")),
    ],
)
def test_context_binding_mismatch_fails_before_observation(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    calls: list[str] = []
    request = _request(calls)
    selected = request.resources[0]
    if field == "resource_type":
        assert isinstance(value, str)
        mismatched = replace(selected.context, resource_type=value)
    elif field == "state_addresses":
        mismatched = replace(
            selected.context,
            state_addresses=("special://profile/playlists/video/wrong.xsp",),
        )
    else:
        assert isinstance(value, DeviceId)
        mismatched = replace(selected.context, device_id=value)
    registry = built_in_resource_registry()

    with pytest.raises(ValueError, match="context binding"):
        CanonicalObservationRuns(
            _store(tmp_path / "mismatch", registry),
            registry,
            _runtime(),
        ).start(replace(request, resources=(replace(selected, context=mismatched),)))

    assert calls == []


def test_observation_factory_receives_no_write_capabilities(tmp_path: Path) -> None:
    calls: list[str] = []
    request = _request(calls)
    hostile = request.resources[0].context.reader
    registry = built_in_resource_registry()
    descriptor = registry.descriptor("KodiSmartPlaylist")
    assert descriptor is not None
    received_capabilities: list[tuple[bool, bool]] = []

    def factory(
        context: ResourceObservationContext,
    ) -> ErasedResourceObserverAdapter[ManagedFileObservation]:
        received_capabilities.append(
            (hasattr(context, "stage_write"), hasattr(context, "reader"))
        )
        address = resolve_special_profile_path(
            context.state_addresses[0], context.profile_root
        )
        return ErasedResourceObserverAdapter(
            ManagedFileObservation,
            lambda: observe_managed_file(context, address, read_limit=1_048_576),
        )

    registry = ResourceRegistry.create(
        (replace(descriptor, _observation_factory=factory),)
    )

    result = CanonicalObservationRuns(
        _store(tmp_path / "readonly", registry),
        registry,
        _runtime(),
    ).start(replace(request, resources=request.resources[:1]))

    assert result.status is ObservationRunStatus.OBSERVED
    assert not hasattr(result, "plan")
    assert not hasattr(request.resources[0].context, "stage_write")
    assert isinstance(hostile, _HostileReadContext)
    assert received_capabilities == [(False, False)]
    assert hostile.write_attempts == []


def test_session_close_failure_preserves_terminal_observation(
    tmp_path: Path,
) -> None:
    registry = built_in_resource_registry()
    store = _store(tmp_path / "runs", registry)
    runs = CanonicalObservationRuns(store, registry, _runtime())
    session_close = DurableSessionClose(
        store,
        FiniteRuntimeValues(utc_instants=("2026-09-20T06:01:00Z",)),
    )
    result = runs.start(_request([]))
    request = SessionCloseRequest(
        "019950f8-4c00-7000-8000-000000000902",
        "session.019950f8-4c00-7000-8000-000000000903",
    )

    closed = session_close.close(
        request,
        result,
        (),
        lambda: (_ for _ in ()).throw(TimeoutError("secret")),
    )

    assert closed.run_report is result
    assert closed.run_id == RUN_ID
    assert closed.close.disposition is SessionCloseDisposition.FAILED
    assert closed.close.issue_code == "session_close.timeout"
    assert session_close.inspect(request, result, ()) == closed
