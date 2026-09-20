import hashlib
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pytest

from coreelec_reconciler.application.commands import ApplyCommand, ReportCommand
from coreelec_reconciler.application.outcomes import ApplyOutcome, ReportOutcome
from coreelec_reconciler.application.reconciler import (
    ApplicationData,
    ExecutionApplicationWorkflows,
)
from coreelec_reconciler.domain.configuration import Resource
from coreelec_reconciler.domain.execution import (
    CleanupMutationIntent,
    MarkerCheckpoint,
    MutationDisposition,
    MutationReceipt,
    MutationTrace,
    NormalizedResourceState,
    Presence,
    PrimitiveKind,
    RecoveryActionCode,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RemoteOwnershipSnapshot,
    RunStatus,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport
from coreelec_reconciler.execution.authority import (
    AcquiredAuthority,
    AuthorityCoordinator,
)
from coreelec_reconciler.execution.composition import (
    ApprovalGrant,
    ProductionExecutionFactory,
    RunStoreExecutionFinalizer,
    SavedPlanExecutionRequest,
)
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    ExecutableChange,
    ExecutionEngine,
    RecoveryAuthority,
    RecoveryDriver,
)
from coreelec_reconciler.execution.local_durability import DurabilityError
from coreelec_reconciler.execution.plan_store import PlanStore
from coreelec_reconciler.execution.progress import Progress
from coreelec_reconciler.execution.recovery import inspect_recovery
from coreelec_reconciler.execution.run_adapters import (
    RecoveryEnvironment,
    RemoteOwnershipReader,
    ResourceContextProvider,
    ResourceContextProviderFactory,
    RunClock,
    RunStoreBoundAuthorityState,
    RunStoreExecutionPersistence,
)
from coreelec_reconciler.execution.run_store import RunStore
from coreelec_reconciler.reporting.canonical_json import (
    decode_json_object,
)
from coreelec_reconciler.reporting.execution_documents import (
    build_execution_run_report,
    decode_execution_run_report,
)
from coreelec_reconciler.reporting.planning_documents import (
    decode_plan,
    decode_run_report,
)
from coreelec_reconciler.resource_types.descriptor import (
    AttachmentStore,
    ErasedResourceExecution,
    ManagedFileCapabilities,
    ManagedFileExecutionResult,
    ManagedFileLifecycle,
    ManagedFileVerification,
    ManagedFileVerificationStatus,
    ResourceDescriptor,
    ResourceExecutionContext,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.codecs import (
    decode_intent,
    encode_intent,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.intent import (
    parse_intent,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning_codecs import (
    decode_plan_evidence,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.resource_type import (
    state_addresses,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ManagedPath,
    ResolvedManagedAddress,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    PreparationBinding,
    PreparationObject,
    PreparedManagedFile,
    decode_prepared_managed_file,
    prepare_managed_file,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry
from tests.fakes.runtime import FakeManagedFiles
from tests.unit.execution.test_execution_documents import RUN_ID, run_value

FIXTURES = Path(__file__).parents[2] / "fixtures" / "canonical"


class _Clock:
    def utc_now(self) -> str:
        return "2026-09-19T08:02:00Z"


class _FinalizerAuthority:
    def __init__(self) -> None:
        self.releases: list[tuple[RunId, str]] = []

    def release(self, run_id: RunId, terminal_digest: str) -> MutationReceipt:
        self.releases.append((run_id, terminal_digest))
        return MutationReceipt("release", MutationDisposition.APPLIED)

    def quarantine(self, run_id: RunId) -> MutationReceipt:
        raise AssertionError("normal completion must not quarantine")


class _AcquiringAuthority:
    def __init__(self, store: RunStore) -> None:
        self.store = store
        self.calls = 0

    def acquire(self, request: object) -> AcquiredAuthority:
        from coreelec_reconciler.execution.authority import AuthorityAcquisitionRequest

        assert isinstance(request, AuthorityAcquisitionRequest)
        self.calls += 1
        device_lease = self.store.acquire_device(request.device_id)
        token = b"production-token"
        token_digest = "sha256:" + hashlib.sha256(token).hexdigest()
        revision_lease, workspace_id = self.store.create_run(
            device_lease,
            request.run_id,
            request.device_id,
            token,
            token_digest,
            request.initial_revision(token_digest),
        )
        identity = request.identity(workspace_id)
        return AcquiredAuthority(
            device_lease,
            revision_lease,
            workspace_id,
            RemoteOwnership(
                identity,
                token_digest,
                1,
                RemoteMarkerPhase.ACQUIRED,
                "sha256:" + "6" * 64,
            ),
        )


@dataclass(frozen=True)
class _TypedChange:
    change_id: str


class _Change:
    def __init__(
        self,
        resource_id: str = "skin.playlist.new-shows",
        requires: tuple[str, ...] = (),
    ) -> None:
        self.resource_id = resource_id
        self.requires = requires
        self.disruptive = False
        self.change = _TypedChange(f"change.{resource_id}")
        self.prepared: PreparedManagedFile | None = None
        self.journal: RunStoreExecutionPersistence | None = None

    def prepare(self) -> object:
        if self.prepared is None:
            raise AssertionError("test Change preparation was not configured")
        return self.prepared

    def apply(self, prepared: object) -> ManagedFileExecutionResult:
        observation = ManagedFileObservation(
            ResolvedManagedAddress(
                "special://profile/playlists/video/NewShows.xsp",
                ManagedPath("/storage/.kodi/userdata/playlists/video/NewShows.xsp"),
            ),
            NormalizedResourceState(
                Presence.PRESENT,
                "regular",
                "sha256:" + "d" * 64,
                0o644,
            ),
            b"desired",
        )
        return ManagedFileExecutionResult(
            MutationTrace(()),
            ManagedFileVerification(
                ManagedFileVerificationStatus.MATCHED,
                observation,
            ),
        )

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object:
        if self.journal is None:
            return MutationTrace(())
        operation_id = f"operation.{self.resource_id}.cleanup"
        intent = CleanupMutationIntent(
            operation_id,
            PrimitiveKind.CLEANUP,
            "cleanup.new-shows",
            terminal_evidence_ref,
            MarkerCheckpoint(
                _Remote()
                .read_ownership(DeviceId("living-room.ugoos-am6b-plus"))
                .identity,
                "sha256:"
                + "202b6cddfe21dac0427445df8c1756ec0a9bbc10f3b74cd4c693ebef3e63ae48",
                1,
                RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
                "sha256:" + "6" * 64,
            ),
            1,
        )
        self.journal.record_intent(RunId(RUN_ID), self.resource_id, intent)
        trace = MutationTrace(
            (MutationReceipt(operation_id, MutationDisposition.APPLIED),)
        )
        managed = cast(PreparedManagedFile, prepared)
        self.journal.record_primitive_outcome(
            RunId(RUN_ID),
            self.resource_id,
            trace,
            ManagedFileObservation(managed.address, managed.before, None),
        )
        return trace


class _CleanupFailureChange(_Change):
    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object:
        raise OSError("cleanup failed")


class _Runtime:
    def observe(self) -> object:
        return object()

    def assess(self, observation: object) -> object:
        return object()

    def prepare(self, change: object) -> object:
        return change

    def apply(self, prepared: object) -> object:
        return object()

    def rollback(self, prepared: object) -> object:
        return object()

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object:
        return object()


class _Contexts:
    def __init__(
        self,
        *,
        device_id: str = "living-room.ugoos-am6b-plus",
        run_id: str = RUN_ID,
        resource_id: str | None = None,
        change_id: str | None = None,
        binding_digest: str = "sha256:" + "a" * 64,
        logical_address: str = "special://profile/playlists/video/NewShows.xsp",
        device_path: str = "/storage/.kodi/userdata/playlists/video/NewShows.xsp",
    ) -> None:
        self.device_id = device_id
        self.run_id = run_id
        self.resource_id = resource_id
        self.change_id = change_id
        self.binding_digest = binding_digest
        self.logical_address = logical_address
        self.device_path = device_path

    def bind(self, journal: object) -> ResourceContextProvider:
        return cast(ResourceContextProvider, self)

    def context(
        self,
        run_id: RunId,
        resource_id: str,
        type_code: str,
        attachments: AttachmentStore,
    ) -> ResourceExecutionContext:
        return ResourceExecutionContext(
            cast(Resource, object()),
            cast(ManagedFileCapabilities, object()),
            attachments,
            cast(ManagedFileLifecycle, object()),
            ResolvedManagedAddress(
                self.logical_address,
                ManagedPath(self.device_path),
            ),
            PreparationBinding(
                self.device_id,
                self.binding_digest,
                self.run_id,
                self.resource_id or resource_id,
                self.change_id or f"change.{resource_id}",
            ),
            _Clock().utc_now,
        )


class _Inspections:
    def read_remote_ownership(self, run_id: RunId) -> RemoteOwnershipSnapshot:
        return RemoteOwnershipSnapshot(
            Presence.ABSENT,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    def read_remote_quarantine(self, run_id: RunId) -> Presence:
        return Presence.ABSENT

    def live_helper(self, run_id: RunId) -> bool | None:
        return False


class _OwnershipInspections(_Inspections):
    def __init__(self, field: str | None = None) -> None:
        reader = _Remote() if field is None else _MismatchedRemote(field)
        self.ownership = reader.read_ownership(DeviceId("living-room.ugoos-am6b-plus"))

    def read_remote_ownership(self, run_id: RunId) -> RemoteOwnershipSnapshot:
        return RemoteOwnershipSnapshot(
            Presence.PRESENT,
            self.ownership.generation,
            self.ownership.marker_digest,
            self.ownership.token_digest,
            self.ownership.identity,
            self.ownership.phase,
            None,
        )


class _Remote:
    def read_ownership(self, device_id: DeviceId) -> RemoteOwnership:
        return RemoteOwnership(
            RemoteOwnershipIdentity(
                device_id,
                RunId(RUN_ID),
                WorkspaceId(f"workspace:{RUN_ID}"),
                "019950f8-4c00-7000-8000-000000000101",
                "sha256:" + "b" * 64,
                "sha256:" + "a" * 64,
                "boot.opaque",
            ),
            "sha256:"
            + "202b6cddfe21dac0427445df8c1756ec0a9bbc10f3b74cd4c693ebef3e63ae48",
            1,
            RemoteMarkerPhase.VERIFYING,
            "sha256:" + "c" * 64,
        )


class _MismatchedRemote:
    def __init__(self, field: str) -> None:
        self.field = field

    def read_ownership(self, device_id: DeviceId) -> RemoteOwnership:
        ownership = _Remote().read_ownership(device_id)
        if self.field == "token_digest":
            return replace(ownership, token_digest="sha256:" + "f" * 64)
        if self.field == "device_id":
            identity = replace(ownership.identity, device_id=DeviceId("other-device"))
        elif self.field == "run_id":
            identity = replace(
                ownership.identity,
                run_id=RunId("019950f8-4c00-7000-8000-000000000699"),
            )
        elif self.field == "workspace_id":
            identity = replace(
                ownership.identity,
                workspace_id=WorkspaceId(
                    "workspace:019950f8-4c00-7000-8000-000000000699"
                ),
            )
        elif self.field == "plan_full_digest":
            identity = replace(
                ownership.identity, plan_full_digest="sha256:" + "f" * 64
            )
        elif self.field == "binding_digest":
            identity = replace(ownership.identity, binding_digest="sha256:" + "f" * 64)
        elif self.field == "plan_id":
            identity = replace(ownership.identity, plan_id="wrong-plan")
        elif self.field == "boot_id":
            identity = replace(ownership.identity, boot_id="wrong-boot")
        else:
            raise AssertionError(f"unsupported field {self.field}")
        return replace(ownership, identity=identity)


class _ApplicationData:
    def __init__(self, plan: ApprovedPlan, store: RunStore) -> None:
        self._plan = plan
        self._store = store

    def approved_plan(
        self, plan_id: PlanId, approval_scopes: tuple[str, ...]
    ) -> ApprovedPlan:
        return self._plan

    def report(self, command: ReportCommand) -> ReportOutcome:
        report = decode_execution_run_report(
            self._store.load_chain(command.run_id).head.payload,
            resource_registry=_registry(),
        )
        return ReportOutcome(report)


def _registry() -> ResourceRegistry:
    return ResourceRegistry.create(
        (
            ResourceDescriptor(
                "KodiSmartPlaylist",
                parse_intent,
                state_addresses,
                encode_intent,
                decode_intent,
                decode_plan_evidence,
                execution_factory=lambda context: cast(
                    ErasedResourceExecution, _Runtime()
                ),
                encode_prepared=lambda value: (
                    cast(PreparedManagedFile, value).manifest_bytes
                ),
                decode_prepared=lambda content, attachments: (
                    decode_prepared_managed_file(content, attachments)
                ),
                decode_planned_change=lambda value, context, rollback: _TypedChange(
                    str(value["change_id"])
                ),
            ),
        )
    )


def _reject_planned_change(
    value: object,
    context: object,
    rollback_approved: bool,
) -> object:
    raise ValueError("resolved configuration differs from approved Plan")


def _create(
    store: RunStore,
    resource_ids: tuple[str, ...] = ("skin.playlist.new-shows",),
) -> None:
    device = DeviceId("living-room.ugoos-am6b-plus")
    lease = store.acquire_device(device)
    value = run_value()
    results = value["resource_results"]
    assert isinstance(results, list)
    first_result = results[0]
    assert isinstance(first_result, dict)
    value["resource_results"] = [
        {**deepcopy(first_result), "resource_id": resource_id}
        for resource_id in resource_ids
    ]
    report = build_execution_run_report(value)
    run_lease, _ = store.create_run(
        lease,
        RunId(RUN_ID),
        device,
        b"ownership-token",
        "sha256:" + hashlib.sha256(b"ownership-token").hexdigest(),
        report.canonical_bytes,
    )
    store.release_run(run_lease)
    store.release_device(lease)


def _adapter(
    store: RunStore,
    contexts: ResourceContextProvider | None = None,
) -> RunStoreExecutionPersistence:
    return RunStoreExecutionPersistence(
        store,
        RunId(RUN_ID),
        _registry(),
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        contexts or cast(ResourceContextProvider, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(RunClock, _Clock()),
    )


def _prepared(
    persistence: RunStoreExecutionPersistence,
    resource_id: str = "skin.playlist.new-shows",
) -> PreparedManagedFile:
    files = FakeManagedFiles()
    desired = NormalizedResourceState(
        Presence.PRESENT,
        "regular",
        "sha256:" + hashlib.sha256(b"desired").hexdigest(),
        0o644,
    )
    return prepare_managed_file(
        reader=files,
        attachments=persistence.attachment_store,
        address=ResolvedManagedAddress(
            "special://profile/playlists/video/NewShows.xsp",
            ManagedPath("/storage/.kodi/userdata/playlists/video/NewShows.xsp"),
        ),
        binding=PreparationBinding(
            "living-room.ugoos-am6b-plus",
            "sha256:" + "a" * 64,
            RUN_ID,
            resource_id,
            f"change.{resource_id}",
        ),
        expected_before=NormalizedResourceState(Presence.ABSENT, None, None, None),
        desired=desired,
        desired_content=b"desired",
        allowed_intermediates=(),
        staged_object=PreparationObject(
            "stage.new-shows",
            desired.content_digest or "",
        ),
        cleanup_object=PreparationObject("cleanup.new-shows", "sha256:" + "c" * 64),
        read_limit=1024,
    )


def test_journal_persists_preparation_and_reconstructs_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    first_store = RunStore(root, resource_registry=_registry())
    _create(first_store)
    first = _adapter(first_store)
    change = _Change()
    change.prepared = _prepared(first)
    change.journal = first
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),)))
    first.prepared(RunId(RUN_ID), "skin.playlist.new-shows", change.prepared)
    first.close()

    restarted = _adapter(RunStore(root, resource_registry=_registry()))
    resources = restarted.resources(RunId(RUN_ID))

    assert len(resources) == 1
    assert resources[0].resource_id == "skin.playlist.new-shows"
    assert restarted.load_chain(RunId(RUN_ID)).head.revision == 3
    restarted.close()


def test_execution_attachment_store_rejects_unregistered_codec(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    persistence = _adapter(store)

    with pytest.raises(ValueError, match="not registered"):
        persistence.attachment_store.attach("private-evidence", "private-v1", b"{}")

    persistence.close()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "019950f8-4c00-7000-8000-000000000699"),
        ("device_id", "other-device"),
        ("binding_digest", "sha256:" + "f" * 64),
        ("logical_address", "special://profile/playlists/video/Other.xsp"),
        ("device_path", "/storage/.kodi/userdata/playlists/video/Other.xsp"),
        ("change_id", "change.skin.playlist.other"),
    ),
)
def test_restart_rejects_preparation_from_another_context(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    first = _adapter(store)
    change = _Change()
    change.prepared = _prepared(first)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),)))
    first.prepared(RunId(RUN_ID), change.resource_id, change.prepared)
    first.close()
    contexts = _Contexts(**{field: value})
    restarted = _adapter(
        RunStore(root, resource_registry=_registry()),
        cast(ResourceContextProvider, contexts),
    )

    with pytest.raises(ValueError, match="current execution context"):
        restarted.resources(RunId(RUN_ID))
    restarted.close()


def test_runstore_recovery_inspection_is_rebuilt_from_durable_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    first = _adapter(store)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, _Change()),)))
    first.prepared(
        RunId(RUN_ID),
        "skin.playlist.new-shows",
        _prepared(first),
    )
    first.close()
    restarted = _adapter(RunStore(root, resource_registry=_registry()))

    inspection = inspect_recovery(restarted.inspection_port(RunId(RUN_ID)))

    assert inspection.evidence.chain_valid
    assert inspection.evidence.preparation_complete
    assert inspection.evidence.forward_work_unperformed
    assert not inspection.evidence.cleanup_complete
    assert tuple(action.code.value for action in inspection.actions) == (
        "inspect",
        "resume_verification",
        "rollback",
        "finalize",
        "finalize",
    )
    restarted.close()


@pytest.mark.parametrize(
    "field",
    (
        "device_id",
        "run_id",
        "workspace_id",
        "plan_id",
        "plan_full_digest",
        "binding_digest",
        "boot_id",
        "token_digest",
    ),
)
def test_recovery_inspection_rejects_every_remote_identity_mismatch(
    tmp_path: Path,
    field: str,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    persistence = RunStoreExecutionPersistence(
        store,
        RunId(RUN_ID),
        _registry(),
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(ResourceContextProvider, _Contexts()),
        cast(RecoveryEnvironment, _OwnershipInspections(field)),
        cast(RunClock, _Clock()),
    )
    change = _Change()
    change.prepared = _prepared(persistence)
    persistence.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),)))
    persistence.prepared(RunId(RUN_ID), change.resource_id, change.prepared)

    inspection = inspect_recovery(persistence.inspection_port(RunId(RUN_ID)))

    assert not inspection.evidence.binding_matches
    assert inspection.evidence.remote_integrity_valid is False
    assert all(
        not action.allowed or action.code is RecoveryActionCode.INSPECT
        for action in inspection.actions
    )
    persistence.close()


def test_ambiguous_cleanup_receipt_is_not_classified_complete_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    first = _adapter(store)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, _Change()),)))
    first.prepared(
        RunId(RUN_ID),
        "skin.playlist.new-shows",
        _prepared(first),
    )
    first.record_cleanup(
        RunId(RUN_ID),
        "skin.playlist.new-shows",
        MutationTrace((MutationReceipt("cleanup", MutationDisposition.AMBIGUOUS),)),
    )
    first.close()

    restarted = _adapter(RunStore(root, resource_registry=_registry()))
    inspection = inspect_recovery(restarted.inspection_port(RunId(RUN_ID)))

    assert not inspection.evidence.cleanup_complete
    restarted.close()


def test_persisted_resources_reconstruct_in_dependency_order_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    first_store = RunStore(root, resource_registry=_registry())
    _create(first_store, ("first", "second"))
    first = RunStoreExecutionPersistence(
        first_store,
        RunId(RUN_ID),
        _registry(),
        {"first": "KodiSmartPlaylist", "second": "KodiSmartPlaylist"},
        cast(ResourceContextProvider, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(RunClock, _Clock()),
    )
    changes = (
        cast(ExecutableChange, _Change("first")),
        cast(ExecutableChange, _Change("second", ("first",))),
    )
    first.start(ApprovedPlan(RunId(RUN_ID), changes))
    first.prepared(RunId(RUN_ID), "first", _prepared(first, "first"))
    first.prepared(RunId(RUN_ID), "second", _prepared(first, "second"))
    first.close()

    restarted = RunStoreExecutionPersistence(
        RunStore(root, resource_registry=_registry()),
        RunId(RUN_ID),
        _registry(),
        {"first": "KodiSmartPlaylist", "second": "KodiSmartPlaylist"},
        cast(ResourceContextProvider, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(RunClock, _Clock()),
    )

    assert [item.resource_id for item in restarted.resources(RunId(RUN_ID))] == [
        "first",
        "second",
    ]
    restarted.close()


def test_production_factory_binds_concrete_services_without_device_access(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    factory = ProductionExecutionFactory(
        PlanStore(tmp_path / "plans"),
        store,
        _registry(),
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(ResourceContextProviderFactory, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(AuthorityCoordinator, object()),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
        progress=Progress(),
    )

    services = factory.bind(RunId(RUN_ID))

    assert services.persistence.load_chain(RunId(RUN_ID)).head.revision == 1
    services.close()


def _saved_plan_request() -> tuple[
    SavedPlanExecutionRequest, CanonicalPlan, CanonicalRunReport
]:
    plan = decode_plan((FIXTURES / "plan-actionable.json").read_bytes())
    planning_run = decode_run_report(
        (FIXTURES / "run-awaiting-approval.json").read_bytes(),
        plan,
    )
    value = decode_json_object(plan.canonical_bytes)
    device = value["device"]
    digests = value["input_digests"]
    assert isinstance(device, dict)
    assert isinstance(digests, dict)
    request = SavedPlanExecutionRequest(
        PlanId(plan.plan_id),
        RunId(RUN_ID),
        DeviceId("living-room.ugoos-am6b-plus"),
        RunId(planning_run.run_id),
        device,
        cast(dict[str, str], digests),
        (
            ApprovalGrant(
                "apply",
                "actor.local-admin",
                "noninteractive_cli",
                "2026-09-19T08:01:00Z",
            ),
        ),
        "2026-09-19T08:01:00Z",
        "boot.opaque",
        "sha256:" + "a" * 64,
    )
    return request, plan, planning_run


def test_saved_plan_approval_creates_bound_run_and_only_encoded_changes(
    tmp_path: Path,
) -> None:
    request, plan, planning_run = _saved_plan_request()
    registry = _registry()
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    plans = PlanStore(tmp_path / "plans")
    plans.save(plan, planning_run)
    authority = _AcquiringAuthority(store)
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(ResourceContextProviderFactory, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    approved = factory.approve_saved_plan(request)

    assert authority.calls == 1
    assert approved.approved_plan.run_id == request.execution_run_id
    assert tuple(change.resource_id for change in approved.approved_plan.changes) == (
        "skin.playlist.new-shows",
    )
    assert (
        decode_json_object(store.load_chain(request.execution_run_id).head.payload)[
            "status"
        ]
        == RunStatus.READY.value
    )
    approved.services.close()


@pytest.mark.parametrize(
    "mismatch",
    (
        "device_id",
        "device_host",
        "device_port",
        "device_platform",
        "device_host_key",
        "input_authored",
        "input_profile",
        "input_artifact",
        "input_capabilities",
        "input_observation",
        "input_aggregate",
        "origin",
        "not_yet_valid",
        "expiry",
        "approval_missing",
        "approval_extra",
        "approval_duplicate",
        "approval_actor",
        "approval_mechanism",
        "approval_before_plan",
        "approval_after_request",
    ),
)
def test_saved_plan_approval_fails_before_run_creation_on_mismatch(
    tmp_path: Path,
    mismatch: str,
) -> None:
    request, plan, planning_run = _saved_plan_request()
    if mismatch.startswith("device_"):
        device = deepcopy(dict(request.expected_device))
        endpoint = cast(dict[str, object], device["endpoint"])
        if mismatch == "device_id":
            device["logical_id"] = "other-device"
        elif mismatch == "device_host":
            endpoint["host"] = "other.example.test"
        elif mismatch == "device_port":
            endpoint["port"] = 2200
        elif mismatch == "device_platform":
            device["observed_platform_identity_fingerprint"] = "sha256:" + "f" * 64
        else:
            device["ssh_host_key_fingerprint"] = "SHA256:other"
        request = replace(request, expected_device=device)
    elif mismatch.startswith("input_"):
        key = {
            "input_authored": "authored_configuration",
            "input_profile": "resolved_profile",
            "input_artifact": "artifact_resolution",
            "input_capabilities": "controller_capabilities",
            "input_observation": "observation_snapshot",
            "input_aggregate": "aggregate_semantic",
        }[mismatch]
        digests = dict(request.input_digests)
        digests[key] = "sha256:" + "f" * 64
        request = replace(
            request,
            input_digests=digests,
        )
    elif mismatch == "origin":
        request = replace(
            request,
            originating_run_id=RunId("019950f8-4c00-7000-8000-000000000699"),
        )
    elif mismatch == "expiry":
        request = replace(request, now="2030-01-01T00:00:00Z")
    elif mismatch == "not_yet_valid":
        request = replace(request, now="2026-09-19T08:00:59Z")
    elif mismatch == "approval_missing":
        request = replace(request, approval_grants=())
    elif mismatch == "approval_extra":
        request = replace(
            request,
            approval_grants=(
                *request.approval_grants,
                ApprovalGrant(
                    "rollback",
                    "actor.local-admin",
                    "noninteractive_cli",
                    request.now,
                ),
            ),
        )
    elif mismatch == "approval_duplicate":
        request = replace(
            request,
            approval_grants=(
                *request.approval_grants,
                request.approval_grants[0],
            ),
        )
    else:
        grant = request.approval_grants[0]
        replacements = {
            "approval_actor": replace(grant, actor=""),
            "approval_mechanism": replace(grant, mechanism=""),
            "approval_before_plan": replace(grant, granted_at="2026-09-19T08:00:59Z"),
            "approval_after_request": replace(grant, granted_at="2026-09-19T08:01:01Z"),
        }
        request = replace(request, approval_grants=(replacements[mismatch],))
    registry = _registry()
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    plans = PlanStore(tmp_path / "plans")
    plans.save(plan, planning_run)
    authority = _AcquiringAuthority(store)
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(ResourceContextProviderFactory, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    with pytest.raises(ValueError):
        factory.approve_saved_plan(request)

    assert authority.calls == 0


def test_saved_plan_approval_rejects_unknown_plan_before_authority(
    tmp_path: Path,
) -> None:
    request, _, _ = _saved_plan_request()
    registry = _registry()
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    authority = _AcquiringAuthority(store)
    factory = ProductionExecutionFactory(
        PlanStore(tmp_path / "plans"),
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(ResourceContextProviderFactory, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    with pytest.raises(DurabilityError):
        factory.approve_saved_plan(request)

    assert authority.calls == 0


def test_saved_plan_decoding_failure_precedes_authority_acquisition(
    tmp_path: Path,
) -> None:
    request, plan, planning_run = _saved_plan_request()
    base = _registry().descriptor("KodiSmartPlaylist")
    assert base is not None
    registry = ResourceRegistry.create(
        (replace(base, decode_planned_change=_reject_planned_change),)
    )
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    plans = PlanStore(tmp_path / "plans")
    plans.save(plan, planning_run)
    authority = _AcquiringAuthority(store)
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(ResourceContextProviderFactory, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    with pytest.raises(ValueError, match="differs from approved Plan"):
        factory.approve_saved_plan(request)

    assert authority.calls == 0


def test_normal_finalizer_releases_with_exact_terminal_digest_after_cleanup(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    persistence = _adapter(store)
    authority = _FinalizerAuthority()
    engine = ExecutionEngine(
        persistence,
        cast(RecoveryDriver, object()),
        finalizer=RunStoreExecutionFinalizer(
            persistence, cast(RecoveryAuthority, authority)
        ),
    )

    change = _Change()
    change.prepared = _prepared(persistence)
    change.journal = persistence
    result = engine.start(
        ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),))
    )
    chain = persistence.load_chain(RunId(RUN_ID))
    terminal = next(
        revision
        for revision in chain.revisions
        if decode_json_object(revision.payload)["status"] == "converged"
    )

    assert authority.releases == [(RunId(RUN_ID), terminal.digest)]
    assert result.cleanup_complete is True
    persistence.close()


def test_normal_finalizer_does_not_release_when_cleanup_is_incomplete(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    persistence = _adapter(store)
    authority = _FinalizerAuthority()
    engine = ExecutionEngine(
        persistence,
        cast(RecoveryDriver, object()),
        finalizer=RunStoreExecutionFinalizer(
            persistence, cast(RecoveryAuthority, authority)
        ),
    )

    change = _CleanupFailureChange()
    change.prepared = _prepared(persistence)
    change.journal = persistence
    result = engine.start(
        ApprovedPlan(
            RunId(RUN_ID),
            (cast(ExecutableChange, change),),
        )
    )

    assert authority.releases == []
    assert result.cleanup_complete is False
    persistence.close()


def test_bound_authority_reconstructs_local_leases_and_remote_identity(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    state = RunStoreBoundAuthorityState(store, _Remote())

    authority = state.load(RunId(RUN_ID))

    assert authority.revision_lease.workspace_id == WorkspaceId(f"workspace:{RUN_ID}")
    assert authority.ownership.identity.run_id == RunId(RUN_ID)
    state.close(RunId(RUN_ID))


@pytest.mark.parametrize(
    "field",
    (
        "device_id",
        "run_id",
        "workspace_id",
        "plan_id",
        "plan_full_digest",
        "binding_digest",
        "boot_id",
        "token_digest",
    ),
)
def test_bound_authority_rejects_every_remote_identity_mismatch(
    tmp_path: Path,
    field: str,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    state = RunStoreBoundAuthorityState(store, _MismatchedRemote(field))

    with pytest.raises(ValueError, match="does not bind"):
        state.load(RunId(RUN_ID))


def test_public_apply_uses_concrete_runstore_journal_across_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    persistence = _adapter(store)
    change = _Change()
    change.prepared = _prepared(persistence)
    change.journal = persistence
    plan = ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),))
    engine = ExecutionEngine(persistence, cast(RecoveryDriver, object()))
    workflows = ExecutionApplicationWorkflows(
        cast(ApplicationData, _ApplicationData(plan, store)),
        engine,
    )

    outcome = workflows.apply(
        ApplyCommand(
            ".",
            PlanId("019950f8-4c00-7000-8000-000000000101"),
            ("apply",),
        )
    )
    persistence.close()

    assert isinstance(outcome, ApplyOutcome)
    assert outcome.status is RunStatus.CONVERGED
    assert outcome.cleanup_complete
    restarted = RunStore(root, resource_registry=_registry())
    assert restarted.load_chain(RunId(RUN_ID)).terminal
    assert restarted.load_chain(RunId(RUN_ID)).head.revision > 1
