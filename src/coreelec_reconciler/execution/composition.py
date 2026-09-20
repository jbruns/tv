"""Production-composition-ready execution services without Device access."""

from dataclasses import dataclass
from typing import cast

from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    SealIntent,
    StoredRevision,
)
from coreelec_reconciler.domain.identifiers import PlanId, RunId
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport
from coreelec_reconciler.execution.authority import AuthorityCoordinator
from coreelec_reconciler.execution.engine import (
    BoundAuthorityStore,
    ExecutionEngine,
    M3AuthorityRecovery,
    RecoveryAuthority,
    RecoveryCoordinator,
)
from coreelec_reconciler.execution.plan_store import PlanStore, SavedPlan
from coreelec_reconciler.execution.progress import Progress
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
from coreelec_reconciler.resource_types.descriptor import (
    AttachmentStore,
    ResourceExecutionContext,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry


@dataclass(frozen=True, slots=True)
class BoundExecutionServices:
    engine: ExecutionEngine
    persistence: RunStoreExecutionPersistence
    authorities: RunStoreBoundAuthorityState

    def close(self) -> None:
        self.authorities.close(self.persistence.revision_lease.run_id)
        self.persistence.close()


class RunStoreExecutionFinalizer:
    """Release authority only after terminal truth and all cleanup receipts."""

    def __init__(
        self,
        persistence: RunStoreExecutionPersistence,
        authority: RecoveryAuthority,
    ) -> None:
        self._persistence = persistence
        self._authority = authority

    def finish(
        self,
        run_id: RunId,
        terminal: StoredRevision,
        cleanup_complete: bool,
    ) -> None:
        released = False
        if cleanup_complete:
            receipt = self._authority.release(run_id, terminal.digest)
            released = receipt.disposition is MutationDisposition.APPLIED
        self._persistence.seal(
            run_id,
            SealIntent(terminal.revision, released),
        )


class _DeferredContexts:
    def __init__(self) -> None:
        self._provider: ResourceContextProvider | None = None

    def bind(self, provider: ResourceContextProvider) -> None:
        self._provider = provider

    def context(
        self,
        run_id: RunId,
        resource_id: str,
        type_code: str,
        attachments: AttachmentStore,
    ) -> ResourceExecutionContext:
        if self._provider is None:
            raise RuntimeError("Resource contexts are not bound")
        return self._provider.context(run_id, resource_id, type_code, attachments)


class ProductionExecutionFactory:
    """Bind concrete restart-safe M3.3 services for one existing Run."""

    def __init__(
        self,
        plan_store: PlanStore,
        run_store: RunStore,
        registry: ResourceRegistry,
        resource_types: dict[str, str],
        contexts: ResourceContextProviderFactory,
        recovery_environment: RecoveryEnvironment,
        authority: AuthorityCoordinator,
        ownership: RemoteOwnershipReader,
        clock: RunClock,
        progress: Progress | None = None,
    ) -> None:
        self._plan_store = plan_store
        self._run_store = run_store
        self._registry = registry
        self._resource_types = dict(resource_types)
        self._contexts = contexts
        self._recovery_environment = recovery_environment
        self._authority = authority
        self._ownership = ownership
        self._clock = clock
        self._progress = progress

    def save_plan(
        self,
        plan: CanonicalPlan,
        planning_run: CanonicalRunReport,
    ) -> SavedPlan:
        return self._plan_store.save(plan, planning_run)

    def load_plan(self, plan_id: PlanId) -> SavedPlan:
        return self._plan_store.load(plan_id)

    def bind(self, run_id: RunId) -> BoundExecutionServices:
        contexts = _DeferredContexts()
        persistence = RunStoreExecutionPersistence(
            self._run_store,
            run_id,
            self._registry,
            self._resource_types,
            contexts,
            self._recovery_environment,
            self._clock,
        )
        contexts.bind(self._contexts.bind(persistence))
        authorities = RunStoreBoundAuthorityState(
            self._run_store,
            self._ownership,
            persistence.revision_lease,
        )
        recovery_authority = M3AuthorityRecovery(
            self._authority,
            cast(BoundAuthorityStore, authorities),
            self._clock,
        )
        recovery = RecoveryCoordinator(persistence, recovery_authority)
        finalizer = RunStoreExecutionFinalizer(persistence, recovery_authority)
        engine = ExecutionEngine(
            persistence,
            recovery,
            self._progress,
            finalizer,
        )
        return BoundExecutionServices(engine, persistence, authorities)
