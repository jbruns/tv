import hashlib
from copy import deepcopy
from pathlib import Path
from typing import cast

from coreelec_reconciler.application.commands import ApplyCommand, ReportCommand
from coreelec_reconciler.application.outcomes import ApplyOutcome, ReportOutcome
from coreelec_reconciler.application.reconciler import (
    ApplicationData,
    ExecutionApplicationWorkflows,
)
from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    MutationReceipt,
    MutationTrace,
    NormalizedResourceState,
    Presence,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RemoteOwnershipSnapshot,
    RunStatus,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.execution.authority import AuthorityCoordinator
from coreelec_reconciler.execution.composition import (
    ProductionExecutionFactory,
    RunStoreExecutionFinalizer,
)
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    ExecutableChange,
    ExecutionEngine,
    RecoveryAuthority,
    RecoveryDriver,
)
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
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.reporting.execution_documents import (
    build_execution_run_report,
    decode_execution_run_report,
)
from coreelec_reconciler.resource_types.descriptor import (
    ErasedResourceExecution,
    ManagedFileExecutionResult,
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
from coreelec_reconciler.resource_types.registry import ResourceRegistry
from tests.unit.execution.test_execution_documents import RUN_ID, run_value


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


class _Change:
    def __init__(
        self,
        resource_id: str = "skin.playlist.new-shows",
        requires: tuple[str, ...] = (),
    ) -> None:
        self.resource_id = resource_id
        self.requires = requires
        self.disruptive = False

    def prepare(self) -> object:
        return {"prepared": "exact"}

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
        return MutationTrace(())


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
    def bind(self, journal: object) -> ResourceContextProvider:
        return cast(ResourceContextProvider, self)

    def context(
        self,
        run_id: RunId,
        resource_id: str,
        type_code: str,
        attachments: object,
    ) -> ResourceExecutionContext:
        return cast(ResourceExecutionContext, object())


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
            self._store.load_chain(command.run_id).head.payload
        )
        return ReportOutcome(report)


def _registry() -> ResourceRegistry:
    return ResourceRegistry.create(
        (
            ResourceDescriptor(
                "TestResource",
                parse_intent,
                state_addresses,
                encode_intent,
                decode_intent,
                execution_factory=lambda context: cast(
                    ErasedResourceExecution, _Runtime()
                ),
                encode_prepared=lambda value: canonical_document_bytes(
                    cast(dict[str, object], value)
                ),
                decode_prepared=lambda content, attachments: decode_json_object(
                    content
                ),
            ),
        )
    )


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


def _adapter(store: RunStore) -> RunStoreExecutionPersistence:
    return RunStoreExecutionPersistence(
        store,
        RunId(RUN_ID),
        _registry(),
        {"skin.playlist.new-shows": "TestResource"},
        cast(ResourceContextProvider, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(RunClock, _Clock()),
    )


def test_journal_persists_preparation_and_reconstructs_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    first_store = RunStore(root)
    _create(first_store)
    first = _adapter(first_store)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, _Change()),)))
    first.prepared(RunId(RUN_ID), "skin.playlist.new-shows", {"prepared": "exact"})
    first.close()

    restarted = _adapter(RunStore(root))
    resources = restarted.resources(RunId(RUN_ID))

    assert len(resources) == 1
    assert resources[0].resource_id == "skin.playlist.new-shows"
    assert restarted.load_chain(RunId(RUN_ID)).head.revision == 3
    restarted.close()


def test_runstore_recovery_inspection_is_rebuilt_from_durable_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root)
    _create(store)
    first = _adapter(store)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, _Change()),)))
    first.prepared(RunId(RUN_ID), "skin.playlist.new-shows", {"prepared": "exact"})
    first.close()
    restarted = _adapter(RunStore(root))

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


def test_ambiguous_cleanup_receipt_is_not_classified_complete_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root)
    _create(store)
    first = _adapter(store)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, _Change()),)))
    first.prepared(RunId(RUN_ID), "skin.playlist.new-shows", {"prepared": "exact"})
    first.record_cleanup(
        RunId(RUN_ID),
        "skin.playlist.new-shows",
        MutationTrace((MutationReceipt("cleanup", MutationDisposition.AMBIGUOUS),)),
    )
    first.close()

    restarted = _adapter(RunStore(root))
    inspection = inspect_recovery(restarted.inspection_port(RunId(RUN_ID)))

    assert not inspection.evidence.cleanup_complete
    restarted.close()


def test_persisted_resources_reconstruct_in_dependency_order_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    first_store = RunStore(root)
    _create(first_store, ("first", "second"))
    first = RunStoreExecutionPersistence(
        first_store,
        RunId(RUN_ID),
        _registry(),
        {"first": "TestResource", "second": "TestResource"},
        cast(ResourceContextProvider, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(RunClock, _Clock()),
    )
    changes = (
        cast(ExecutableChange, _Change("first")),
        cast(ExecutableChange, _Change("second", ("first",))),
    )
    first.start(ApprovedPlan(RunId(RUN_ID), changes))
    first.prepared(RunId(RUN_ID), "first", {"prepared": "first"})
    first.prepared(RunId(RUN_ID), "second", {"prepared": "second"})
    first.close()

    restarted = RunStoreExecutionPersistence(
        RunStore(root),
        RunId(RUN_ID),
        _registry(),
        {"first": "TestResource", "second": "TestResource"},
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
    store = RunStore(tmp_path / "runs")
    _create(store)
    factory = ProductionExecutionFactory(
        PlanStore(tmp_path / "plans"),
        store,
        _registry(),
        {"skin.playlist.new-shows": "TestResource"},
        cast(ResourceContextProviderFactory, _Contexts()),
        cast(RecoveryEnvironment, _Inspections()),
        cast(AuthorityCoordinator, object()),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
        Progress(),
    )

    services = factory.bind(RunId(RUN_ID))

    assert services.persistence.load_chain(RunId(RUN_ID)).head.revision == 1
    services.close()


def test_normal_finalizer_releases_with_exact_terminal_digest_after_cleanup(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs")
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

    result = engine.start(
        ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, _Change()),))
    )
    terminal = persistence.load_chain(RunId(RUN_ID)).head

    assert authority.releases == [(RunId(RUN_ID), terminal.digest)]
    assert result.cleanup_complete is True
    persistence.close()


def test_normal_finalizer_does_not_release_when_cleanup_is_incomplete(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs")
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

    result = engine.start(
        ApprovedPlan(
            RunId(RUN_ID),
            (cast(ExecutableChange, _CleanupFailureChange()),),
        )
    )

    assert authority.releases == []
    assert result.cleanup_complete is False
    persistence.close()


def test_bound_authority_reconstructs_local_leases_and_remote_identity(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs")
    _create(store)
    state = RunStoreBoundAuthorityState(store, _Remote())

    authority = state.load(RunId(RUN_ID))

    assert authority.revision_lease.workspace_id == WorkspaceId(f"workspace:{RUN_ID}")
    assert authority.ownership.identity.run_id == RunId(RUN_ID)
    state.close(RunId(RUN_ID))


def test_public_apply_uses_concrete_runstore_journal_across_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root)
    _create(store)
    persistence = _adapter(store)
    plan = ApprovedPlan(
        RunId(RUN_ID),
        (cast(ExecutableChange, _Change()),),
    )
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
    restarted = RunStore(root)
    assert restarted.load_chain(RunId(RUN_ID)).terminal
    assert len(restarted.load_operational_receipts(RunId(RUN_ID), "cleanup")) == 1
