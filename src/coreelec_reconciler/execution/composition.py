"""Production-composition-ready execution services without Device access."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from coreelec_reconciler.domain.canonical_json import decode_json_object
from coreelec_reconciler.domain.execution import (
    AttachmentRef,
    MutationDisposition,
    MutationIntent,
    MutationTrace,
    RemoteOwnershipIdentity,
    SealIntent,
    StoredRevision,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport
from coreelec_reconciler.execution.authority import (
    AcquiredAuthority,
    AuthorityAcquisitionRequest,
    AuthorityCoordinator,
)
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    BoundAuthorityStore,
    BoundExecutableChange,
    ExecutableChange,
    ExecutionEngine,
    M3AuthorityRecovery,
    RecoveryAuthority,
    RecoveryCoordinator,
)
from coreelec_reconciler.execution.plan_store import PlanStore, SavedPlan
from coreelec_reconciler.execution.progress import Progress
from coreelec_reconciler.execution.run_adapters import (
    ExecutionDocumentCodec,
    PrimitiveCheckpointJournal,
    RecoveryEnvironment,
    RemoteOwnershipReader,
    ResourceContextProvider,
    ResourceContextProviderFactory,
    RunClock,
    RunStoreBoundAuthorityState,
    RunStoreExecutionPersistence,
)
from coreelec_reconciler.execution.run_store import RunStore
from coreelec_reconciler.persistence.document_codecs import (
    CanonicalExecutionDocumentCodec,
)
from coreelec_reconciler.resource_types.descriptor import (
    AttachmentStore,
    ResourceExecutionContext,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry


@dataclass(frozen=True, slots=True)
class BoundExecutionServices:
    engine: ExecutionEngine
    persistence: RunStoreExecutionPersistence
    authorities: RunStoreBoundAuthorityState
    contexts: ResourceContextProvider

    def close(self) -> None:
        self.authorities.close(self.persistence.revision_lease.run_id)
        self.persistence.close()


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    scope: str
    actor: str
    mechanism: str
    granted_at: str


@dataclass(frozen=True, slots=True)
class SavedPlanExecutionRequest:
    plan_id: PlanId
    execution_run_id: RunId
    device_id: DeviceId
    originating_run_id: RunId
    expected_device: Mapping[str, object]
    input_digests: Mapping[str, str]
    approval_grants: tuple[ApprovalGrant, ...]
    now: str
    boot_id: str
    binding_digest: str


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    approved_plan: ApprovedPlan
    services: BoundExecutionServices


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
        if not released:
            return
        released_revision = self._persistence.record_authority_state(run_id, "released")
        self._persistence.seal(
            run_id,
            SealIntent(released_revision.revision, True),
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


class _DeferredJournal:
    def __init__(self) -> None:
        self._journal: PrimitiveCheckpointJournal | None = None

    def bind(self, journal: PrimitiveCheckpointJournal) -> None:
        self._journal = journal

    def record_intent(
        self,
        run_id: RunId,
        resource_id: str,
        intent: MutationIntent,
    ) -> StoredRevision:
        if self._journal is None:
            raise RuntimeError("execution journal is not bound")
        return self._journal.record_intent(run_id, resource_id, intent)

    def record_primitive_outcome(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace,
        observation: ManagedFileObservation,
    ) -> StoredRevision:
        if self._journal is None:
            raise RuntimeError("execution journal is not bound")
        return self._journal.record_primitive_outcome(
            run_id,
            resource_id,
            trace,
            observation,
        )


class _DeferredAttachmentStore:
    def __init__(self) -> None:
        self._store: AttachmentStore | None = None

    def bind(self, store: AttachmentStore) -> None:
        self._store = store

    def attach(self, kind: str, codec: str, payload: bytes) -> AttachmentRef:
        if self._store is None:
            raise RuntimeError("attachment store is not bound")
        return self._store.attach(kind, codec, payload)

    def read_attachment(self, reference: AttachmentRef) -> bytes:
        if self._store is None:
            raise RuntimeError("attachment store is not bound")
        return self._store.read_attachment(reference)


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
        documents: ExecutionDocumentCodec | None = None,
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
        self._documents = documents or CanonicalExecutionDocumentCodec()
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
        return self._bind(run_id)

    def approve_saved_plan(
        self,
        request: SavedPlanExecutionRequest,
    ) -> PreparedExecution:
        saved = self.load_plan(request.plan_id)
        value = decode_json_object(saved.plan.canonical_bytes)
        if saved.device_id != request.device_id:
            raise ValueError("saved Plan Device binding changed")
        if saved.originating_run_id != request.originating_run_id:
            raise ValueError("saved Plan origin binding changed")
        if dict(saved.input_digests) != dict(request.input_digests):
            raise ValueError("saved Plan input bindings changed")
        device = value.get("device")
        if not isinstance(device, dict) or device != dict(request.expected_device):
            raise ValueError("saved Plan Device identity changed")
        expires_at = value.get("expires_at")
        if not isinstance(expires_at, str) or _timestamp(request.now) > _timestamp(
            expires_at
        ):
            raise ValueError("saved Plan expired")
        valid_from = value.get("valid_from")
        if not isinstance(valid_from, str):
            raise ValueError("saved Plan validity boundary is invalid")
        if _timestamp(request.now) < _timestamp(valid_from):
            raise ValueError("saved Plan is not yet valid")
        if len({grant.scope for grant in request.approval_grants}) != len(
            request.approval_grants
        ):
            raise ValueError("approval grant scopes must be unique")
        for grant in request.approval_grants:
            if not grant.scope or not grant.actor or not grant.mechanism:
                raise ValueError("approval grant identity is incomplete")
            granted_at = _timestamp(grant.granted_at)
            if granted_at < _timestamp(valid_from) or granted_at > _timestamp(
                request.now
            ):
                raise ValueError("approval grant time is outside Plan validity")
        grants = {grant.scope: grant for grant in request.approval_grants}
        missing = set(saved.approval_scopes) - set(grants)
        if missing:
            raise ValueError("saved Plan approval scopes are insufficient")
        if any(
            grant.scope not in saved.approval_scopes
            for grant in request.approval_grants
        ):
            raise ValueError("approval grant is not required by saved Plan")
        resources = _objects(value, "resources")
        deferred_journal = _DeferredJournal()
        deferred_attachments = _DeferredAttachmentStore()
        execution_contexts = self._contexts.bind(deferred_journal)
        changes: list[ExecutableChange] = []
        for resource in resources:
            resource_id = _required_text(resource, "resource_id")
            type_code = _required_text(resource, "resource_type")
            descriptor = self._registry.descriptor(type_code)
            if (
                descriptor is None
                or descriptor.execution_factory is None
                or descriptor.decode_planned_change is None
            ):
                raise ValueError("saved Plan Resource Type is not executable")
            context = execution_contexts.context(
                request.execution_run_id,
                resource_id,
                type_code,
                deferred_attachments,
            )
            runtime = descriptor.execution_factory(context)
            for change in _objects(resource, "changes"):
                changes.append(
                    BoundExecutableChange(
                        resource_id,
                        (),
                        "service_disruption" in _strings(change, "impact_codes"),
                        runtime,
                        descriptor.decode_planned_change(
                            change,
                            context,
                            "apply" in grants,
                        ),
                    )
                )

        def initial_revision(token_digest: str) -> bytes:
            report = self._documents.build(
                _initial_execution_run(
                    saved,
                    request,
                    token_digest,
                    resources,
                ),
                self._registry,
            )
            return report.canonical_bytes

        acquired = self._authority.acquire(
            AuthorityAcquisitionRequest(
                request.device_id,
                request.execution_run_id,
                initial_revision,
                lambda workspace_id: RemoteOwnershipIdentity(
                    request.device_id,
                    request.execution_run_id,
                    workspace_id,
                    saved.plan.plan_id,
                    saved.plan.full_digest,
                    request.binding_digest,
                    request.boot_id,
                ),
                request.now,
            )
        )
        services = self._bind(
            request.execution_run_id,
            acquired,
            execution_contexts,
            deferred_journal,
            deferred_attachments,
        )
        return PreparedExecution(
            ApprovedPlan(request.execution_run_id, tuple(changes)),
            services,
        )

    def _bind(
        self,
        run_id: RunId,
        acquired: AcquiredAuthority | None = None,
        execution_contexts: ResourceContextProvider | None = None,
        deferred_journal: _DeferredJournal | None = None,
        deferred_attachments: _DeferredAttachmentStore | None = None,
    ) -> BoundExecutionServices:
        contexts = _DeferredContexts()
        persistence = RunStoreExecutionPersistence(
            self._run_store,
            run_id,
            self._registry,
            self._resource_types,
            contexts,
            self._recovery_environment,
            self._clock,
            self._documents,
            acquired.revision_lease if acquired is not None else None,
        )
        provider = execution_contexts or self._contexts.bind(persistence)
        contexts.bind(provider)
        if deferred_journal is not None:
            deferred_journal.bind(persistence)
        if deferred_attachments is not None:
            deferred_attachments.bind(persistence.attachment_store)
        authorities = RunStoreBoundAuthorityState(
            self._run_store,
            self._ownership,
            persistence.revision_lease,
        )
        if acquired is not None:
            authorities.save(run_id, acquired)
        recovery_authority = M3AuthorityRecovery(
            self._authority,
            cast(BoundAuthorityStore, authorities),
            self._clock,
            persistence,
        )
        recovery = RecoveryCoordinator(persistence, recovery_authority)
        finalizer = RunStoreExecutionFinalizer(persistence, recovery_authority)
        engine = ExecutionEngine(
            persistence,
            recovery,
            self._progress,
            finalizer,
        )
        return BoundExecutionServices(
            engine,
            persistence,
            authorities,
            contexts,
        )


def _initial_execution_run(
    saved: SavedPlan,
    request: SavedPlanExecutionRequest,
    token_digest: str,
    resources: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "approvals": [
            {
                "actor": grant.actor,
                "granted_at": grant.granted_at,
                "mechanism": grant.mechanism,
                "plan_full_digest": saved.plan.full_digest,
                "plan_id": saved.plan.plan_id,
                "scope": grant.scope,
            }
            for grant in request.approval_grants
        ],
        "attachments": [],
        "attempts": [],
        "authority": {
            "binding_digest": request.binding_digest,
            "boot_id": request.boot_id,
            "cleanup_state": "not_started",
            "device_index_intent": "add_or_retain_active",
            "marker_digest": None,
            "marker_generation": None,
            "marker_phase": None,
            "ownership_state": "acquisition_pending",
            "ownership_token_digest": token_digest,
        },
        "cleanup": {"leftover_count": 0, "state": "not_started"},
        "current_digest": "",
        "device_id": request.device_id.value,
        "ended_at": None,
        "evidence": [],
        "failures": [],
        "kind": "CoreElecReconcilerRunReport",
        "lifecycle_history": ["ready"],
        "originating_planning_run_id": saved.originating_run_id.value,
        "plan_reference": {
            "originating_planning_run_id": saved.originating_run_id.value,
            "plan_full_digest": saved.plan.full_digest,
            "plan_id": saved.plan.plan_id,
        },
        "previous_revision_digest": None,
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "recovery": {
            "actions": [
                {
                    "allowed": True,
                    "code": "inspect",
                    "mode": None,
                    "reason_code": "recovery.workspace-present",
                    "requires_approval": False,
                    "requires_reason": False,
                },
                {
                    "allowed": False,
                    "code": "finalize",
                    "mode": "abandon",
                    "reason_code": "recovery.abandonment-available",
                    "requires_approval": True,
                    "requires_reason": True,
                },
            ],
            "required": False,
            "workspace_id": f"workspace:{request.execution_run_id.value}",
        },
        "resource_results": [
            {
                "decisive_attempt_id": None,
                "desired_disposition": _desired_disposition(resource),
                "final_convergence": "pending",
                "latest_observed_relation": _required_text(
                    resource, "desired_relation"
                ),
                "mutation_outcome": "pending",
                "post_effect_verification": "not_applicable",
                "resource_id": _required_text(resource, "resource_id"),
                "rollback_outcome": "not_attempted",
                "verification_outcome": "not_started",
            }
            for resource in resources
        ],
        "revision": 1,
        "run_id": request.execution_run_id.value,
        "schema_version": 1,
        "started_at": request.now,
        "status": "ready",
    }


def _objects(value: Mapping[str, object], key: str) -> list[dict[str, object]]:
    raw = value.get(key)
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError(f"saved Plan {key} is malformed")
    return [cast(dict[str, object], item) for item in raw]


def _strings(value: Mapping[str, object], key: str) -> tuple[str, ...]:
    raw = value.get(key)
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"saved Plan {key} is malformed")
    return tuple(raw)


def _required_text(value: Mapping[str, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"saved Plan {key} is malformed")
    return raw


def _desired_disposition(resource: Mapping[str, object]) -> str:
    changes = _objects(resource, "changes")
    if not changes:
        return "observe_only"
    desired = changes[0].get("desired")
    summary = desired.get("summary") if isinstance(desired, dict) else None
    if not isinstance(summary, dict) or summary.get("presence") not in {
        "present",
        "absent",
    }:
        raise ValueError("saved Plan desired disposition is malformed")
    return cast(str, summary["presence"])


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("execution timestamp is invalid") from error
