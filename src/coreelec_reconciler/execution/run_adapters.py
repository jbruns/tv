"""RunStore-backed execution, recovery, attachment, and reconstruction adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Protocol

from coreelec_reconciler.domain.configuration import ResolvedConfiguration
from coreelec_reconciler.domain.execution import (
    AppendIntent,
    AttachmentRef,
    AuthorityPhase,
    DeviceIndexIntent,
    EffectDisposition,
    MutationDisposition,
    MutationIntent,
    MutationTrace,
    Presence,
    RecoveryEvidence,
    RemoteOwnership,
    RemoteOwnershipSnapshot,
    RevisionLease,
    RunStatus,
    SealIntent,
    StateRelation,
    StoredRevision,
    VerifiedRunChain,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.execution.authority import AcquiredAuthority
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    BoundRecoveryResource,
    RecoveryResource,
)
from coreelec_reconciler.execution.recovery import RecoveryInspectorPort
from coreelec_reconciler.execution.run_store import RunStore
from coreelec_reconciler.reporting.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.reporting.execution_documents import (
    build_execution_run_report,
)
from coreelec_reconciler.resource_types.descriptor import (
    AttachmentStore,
    ManagedFileCapabilities,
    ManagedFileExecutionResult,
    ManagedFileLifecycle,
    ManagedFileVerification,
    ManagedFileVerificationStatus,
    ResourceDescriptor,
    ResourceExecutionContext,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    resolve_special_profile_path,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    PreparationBinding,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry


class RunClock(Protocol):
    def utc_now(self) -> str: ...


class ResourceContextProvider(Protocol):
    def context(
        self,
        run_id: RunId,
        resource_id: str,
        type_code: str,
        attachments: AttachmentStore,
    ) -> ResourceExecutionContext: ...


class PrimitiveCheckpointJournal(Protocol):
    def record_intent(
        self,
        run_id: RunId,
        resource_id: str,
        intent: MutationIntent,
    ) -> StoredRevision: ...

    def record_primitive_outcome(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace,
        observation: ManagedFileObservation,
    ) -> StoredRevision: ...


class ResourceContextProviderFactory(Protocol):
    def bind(self, journal: PrimitiveCheckpointJournal) -> ResourceContextProvider: ...


class ManagedFileLifecycleFactory(Protocol):
    def lifecycle(
        self,
        run_id: RunId,
        resource_id: str,
        attachments: AttachmentStore,
        intent_checkpoint: Callable[[MutationIntent], None],
        outcome_checkpoint: Callable[[MutationTrace, ManagedFileObservation], None],
    ) -> ManagedFileLifecycle: ...


@dataclass(frozen=True, slots=True)
class ConfigurationResourceContexts:
    """Build per-Run Resource execution from resolved configuration capabilities."""

    configuration: ResolvedConfiguration
    files: ManagedFileCapabilities
    lifecycles: ManagedFileLifecycleFactory
    change_ids: Mapping[str, str]
    binding_digest: Callable[[RunId], str]
    observed_at: Callable[[], str]

    def bind(self, journal: PrimitiveCheckpointJournal) -> ResourceContextProvider:
        return _BoundConfigurationResourceContexts(self, journal)


@dataclass(frozen=True, slots=True)
class _BoundConfigurationResourceContexts:
    configuration: ConfigurationResourceContexts
    journal: PrimitiveCheckpointJournal

    def context(
        self,
        run_id: RunId,
        resource_id: str,
        type_code: str,
        attachments: AttachmentStore,
    ) -> ResourceExecutionContext:
        configuration = self.configuration
        resource = next(
            (
                item
                for item in configuration.configuration.resources
                if item.id.value == resource_id and item.type == type_code
            ),
            None,
        )
        if resource is None:
            raise ValueError("persisted Resource is absent from configuration")
        if configuration.configuration.device is None:
            raise ValueError("resolved Device capabilities are unavailable")
        if len(resource.state_addresses) != 1:
            raise ValueError("managed-file Resource requires one State Address")
        change_id = configuration.change_ids.get(resource_id)
        if change_id is None:
            raise ValueError("persisted Resource Change binding is unavailable")
        address = resolve_special_profile_path(
            resource.state_addresses[0],
            configuration.configuration.device.profile_root,
        )
        return ResourceExecutionContext(
            resource,
            configuration.files,
            attachments,
            configuration.lifecycles.lifecycle(
                run_id,
                resource_id,
                attachments,
                lambda intent: self._record_intent(run_id, resource_id, intent),
                lambda trace, observation: self._record_outcome(
                    run_id, resource_id, trace, observation
                ),
            ),
            address,
            PreparationBinding(
                configuration.configuration.device_id.value,
                configuration.binding_digest(run_id),
                run_id.value,
                resource_id,
                change_id,
            ),
            configuration.observed_at,
        )

    def _record_intent(
        self,
        run_id: RunId,
        resource_id: str,
        intent: MutationIntent,
    ) -> None:
        self.journal.record_intent(run_id, resource_id, intent)

    def _record_outcome(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace,
        observation: ManagedFileObservation,
    ) -> None:
        self.journal.record_primitive_outcome(run_id, resource_id, trace, observation)


class RecoveryEnvironment(Protocol):
    def read_remote_ownership(self, run_id: RunId) -> RemoteOwnershipSnapshot: ...

    def read_remote_quarantine(self, run_id: RunId) -> Presence: ...

    def live_helper(self, run_id: RunId) -> bool | None: ...


class RemoteOwnershipReader(Protocol):
    def read_ownership(self, device_id: DeviceId) -> RemoteOwnership: ...


@dataclass(frozen=True, slots=True)
class PreparedResourceRecord:
    resource_id: str
    type_code: str
    requires: tuple[str, ...]
    disruptive: bool
    attachment_digest: str
    attachment_codec: str


class RunStoreAttachmentStore:
    """AttachmentStore bound to one held Run lease."""

    def __init__(self, store: RunStore, lease: RevisionLease) -> None:
        if not isinstance(lease, RevisionLease):
            raise TypeError("RunStore attachment adapter requires a revision lease")
        self._store = store
        self._lease = lease

    def attach(self, kind: str, codec: str, payload: bytes) -> AttachmentRef:
        return self._store.attach(self._lease, kind, codec, payload)

    def read_attachment(self, reference: AttachmentRef) -> bytes:
        return self._store.read_attachment(self._lease, reference).payload


class RunStoreBoundAuthorityState:
    """Rebind durable local leases and verified remote ownership after restart."""

    def __init__(
        self,
        store: RunStore,
        remote: RemoteOwnershipReader,
        revision_lease: RevisionLease | None = None,
    ) -> None:
        self._store = store
        self._remote = remote
        self._revision_lease = revision_lease
        self._bound: dict[RunId, AcquiredAuthority] = {}
        self._owns_revision_lease = revision_lease is None

    def load(self, run_id: RunId) -> AcquiredAuthority:
        existing = self._bound.get(run_id)
        if existing is not None:
            return existing
        chain = self._store.load_chain(run_id)
        identity = decode_json_object(chain.head.payload)
        device_id = DeviceId(_text(identity, "device_id"))
        device_lease = self._store.acquire_device(device_id)
        try:
            revision_lease = self._revision_lease or self._store.acquire_run(run_id)
        except Exception:
            self._store.release_device(device_lease)
            raise
        ownership = self._remote.read_ownership(device_id)
        if (
            ownership.identity.run_id != run_id
            or ownership.identity.workspace_id != revision_lease.workspace_id
            or ownership.identity.device_id != device_id
        ):
            self._store.release_run(revision_lease)
            self._store.release_device(device_lease)
            raise ValueError("remote ownership does not bind to the local Run")
        acquired = AcquiredAuthority(
            device_lease,
            revision_lease,
            revision_lease.workspace_id,
            ownership,
        )
        self._bound[run_id] = acquired
        return acquired

    def save(self, run_id: RunId, authority: AcquiredAuthority) -> None:
        if authority.revision_lease.run_id != run_id:
            raise ValueError("authority does not bind to the Run")
        self._bound[run_id] = authority

    def close(self, run_id: RunId) -> None:
        authority = self._bound.pop(run_id, None)
        if authority is None:
            return
        if self._owns_revision_lease:
            self._store.release_run(authority.revision_lease)
        self._store.release_device(authority.device_lease)


class RunStoreExecutionPersistence:
    """Concrete RunStore adapter for execution evidence and restart recovery."""

    def __init__(
        self,
        store: RunStore,
        run_id: RunId,
        registry: ResourceRegistry,
        resource_types: Mapping[str, str],
        contexts: ResourceContextProvider,
        recovery_environment: RecoveryEnvironment,
        clock: RunClock,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._lease = store.acquire_run(run_id)
        self._attachments = RunStoreAttachmentStore(store, self._lease)
        self._registry = registry
        self._resource_types = dict(resource_types)
        self._contexts = contexts
        self._recovery_environment = recovery_environment
        self._clock = clock
        self._resource_metadata: dict[str, tuple[tuple[str, ...], bool]] = {}

    def close(self) -> None:
        self._store.release_run(self._lease)

    @property
    def revision_lease(self) -> RevisionLease:
        return self._lease

    def start(self, plan: ApprovedPlan) -> None:
        if plan.run_id != self._run_id:
            raise ValueError("execution Plan does not bind to the Run")
        self._resource_metadata = {
            change.resource_id: (change.requires, change.disruptive)
            for change in plan.changes
        }
        chain = self.load_chain(plan.run_id)
        if _status(chain.head) is RunStatus.READY:
            self._append_status(RunStatus.EXECUTING)

    def prepared(self, run_id: RunId, resource_id: str, prepared: object) -> None:
        descriptor = self._descriptor(resource_id)
        if descriptor.encode_prepared is None:
            raise ValueError("Resource Type does not support durable preparation")
        payload = descriptor.encode_prepared(prepared)
        reference = self._attachments.attach(
            "resource-preparation",
            f"{descriptor.type_code.lower()}-preparation-v1",
            payload,
        )
        requires, disruptive = self._resource_metadata.get(resource_id, ((), False))
        record = {
            "attachment_codec": reference.codec,
            "attachment_digest": reference.digest,
            "disruptive": disruptive,
            "requires": list(requires),
            "resource_id": resource_id,
            "type_code": descriptor.type_code,
        }
        self._append_evidence(run_id, resource_id, "ResourcePreparation", record)

    def result(
        self,
        run_id: RunId,
        resource_id: str,
        result: ManagedFileExecutionResult,
    ) -> None:
        self._append_evidence(
            run_id,
            resource_id,
            "ResourceExecutionResult",
            _jsonable(result),
            resource_result=_resource_result(result),
        )

    def record_intent(
        self,
        run_id: RunId,
        resource_id: str,
        intent: MutationIntent,
    ) -> StoredRevision:
        return self._append_evidence(
            run_id,
            resource_id,
            "MutationIntent",
            _jsonable(intent),
        )

    def record_primitive_outcome(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace,
        observation: ManagedFileObservation,
    ) -> StoredRevision:
        return self._append_evidence(
            run_id,
            resource_id,
            "PrimitiveOutcome",
            {
                "observation": _jsonable(observation),
                "trace": _jsonable(trace),
            },
        )

    def terminal(self, run_id: RunId, status: RunStatus) -> StoredRevision:
        return self._append_status(status)

    def cleanup(self, run_id: RunId, resource_id: str, result: object) -> None:
        self.record_cleanup(run_id, resource_id, _require_trace(result))

    def skipped(
        self,
        run_id: RunId,
        resource_id: str,
        dependency_ids: tuple[str, ...],
    ) -> None:
        self._append_evidence(
            run_id,
            resource_id,
            "ResourceSkipped",
            {"dependency_ids": list(dependency_ids)},
            resource_result={
                "final_convergence": (
                    "skipped_dependency" if dependency_ids else "skipped_run_stopped"
                ),
                "mutation_outcome": "blocked",
                "verification_outcome": "not_started",
                "rollback_outcome": "not_attempted",
                "post_effect_verification": "not_reached",
                "latest_observed_relation": "unknown",
            },
        )

    def load_chain(self, run_id: RunId) -> VerifiedRunChain:
        self._require_run(run_id)
        return self._store.load_chain(run_id)

    def inspection_port(self, run_id: RunId) -> RecoveryInspectorPort:
        self._require_run(run_id)
        return _RunStoreInspectionPort(self, self._recovery_environment)

    def resources(self, run_id: RunId) -> tuple[RecoveryResource, ...]:
        self._require_run(run_id)
        records = _preparation_records(self._store.load_chain(run_id).head.payload)
        resources: list[RecoveryResource] = []
        seen: set[str] = set()
        for record in records:
            if not set(record.requires) <= seen:
                raise ValueError("persisted Resource order violates dependencies")
            descriptor = self._registry.descriptor(record.type_code)
            if (
                descriptor is None
                or descriptor.decode_prepared is None
                or descriptor.execution_factory is None
            ):
                raise ValueError("persisted Resource Type cannot be reconstructed")
            reference = AttachmentRef(
                record.attachment_digest,
                "resource-preparation",
                record.attachment_codec,
            )
            payload = self._attachments.read_attachment(reference)
            prepared = descriptor.decode_prepared(payload, self._attachments)
            runtime = descriptor.execution_factory(
                self._contexts.context(
                    run_id,
                    record.resource_id,
                    record.type_code,
                    self._attachments,
                )
            )
            resources.append(
                BoundRecoveryResource(runtime, prepared, record.resource_id)
            )
            seen.add(record.resource_id)
        return tuple(resources)

    def record_verification(
        self,
        run_id: RunId,
        resource_id: str,
        observation: object,
        assessment: object,
    ) -> StoredRevision:
        return self._append_evidence(
            run_id,
            resource_id,
            "RecoveryVerification",
            {
                "assessment": _jsonable(assessment),
                "observation": _jsonable(observation),
            },
        )

    def record_rollback(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace | None,
        verification: ManagedFileVerification,
    ) -> StoredRevision:
        return self._append_evidence(
            run_id,
            resource_id,
            "RollbackResult",
            {"trace": _jsonable(trace), "verification": _jsonable(verification)},
            resource_result=_rollback_result(trace, verification),
        )

    def record_terminal(self, run_id: RunId, status: RunStatus) -> StoredRevision:
        self._require_run(run_id)
        return self._append_status(status)

    def record_abandonment(
        self,
        run_id: RunId,
        *,
        approval: str,
        reason: str,
    ) -> StoredRevision:
        self._append_evidence(
            run_id,
            "run",
            "RecoveryAbandonment",
            {"approval": approval, "reason": reason},
        )
        return self._append_status(RunStatus.FAILED_RECOVERY_REQUIRED)

    def record_cleanup(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace,
    ) -> str:
        self._require_run(run_id)
        return self._store.record_operational_receipt(
            self._lease,
            "cleanup",
            resource_id,
            canonical_document_bytes({"trace": _jsonable(trace)}),
        )

    def seal(self, run_id: RunId, intent: SealIntent) -> None:
        self._require_run(run_id)
        self._store.finalize_and_seal(self._lease, intent)

    def _descriptor(self, resource_id: str) -> ResourceDescriptor:
        type_code = self._resource_types.get(resource_id)
        descriptor = (
            self._registry.descriptor(type_code) if type_code is not None else None
        )
        if descriptor is None:
            raise ValueError("Resource Type is not registered")
        return descriptor

    def _append_evidence(
        self,
        run_id: RunId,
        resource_id: str,
        payload_kind: str,
        payload: object,
        *,
        resource_result: dict[str, object] | None = None,
    ) -> StoredRevision:
        self._require_run(run_id)
        chain = self._store.load_chain(run_id)
        value = decode_json_object(chain.head.payload)
        evidence = list(_list(value, "evidence"))
        evidence.append(
            {
                "evidence_id": f"evidence.{chain.head.revision + 1}.{resource_id}",
                "observed_at": self._clock.utc_now(),
                "payload": payload,
                "payload_kind": payload_kind,
                "payload_schema_version": 1,
                "raw_attachment_digest": (
                    payload.get("attachment_digest")
                    if isinstance(payload, dict)
                    else None
                ),
                "subject": {"id": resource_id, "kind": "resource"},
            }
        )
        value["evidence"] = evidence
        if isinstance(payload, dict) and payload_kind == "ResourcePreparation":
            attachments = list(_list(value, "attachments"))
            attachments.append(
                {
                    "codec": payload["attachment_codec"],
                    "digest": payload["attachment_digest"],
                    "kind": "resource-preparation",
                }
            )
            value["attachments"] = attachments
        if resource_result is not None:
            results = list(_list(value, "resource_results"))
            for item in results:
                if isinstance(item, dict) and item.get("resource_id") == resource_id:
                    item.update(resource_result)
                    break
            value["resource_results"] = results
        return self._append(value, _status(chain.head), terminal=False)

    def _append_status(self, status: RunStatus) -> StoredRevision:
        chain = self._store.load_chain(self._run_id)
        value = decode_json_object(chain.head.payload)
        lifecycle = list(_list(value, "lifecycle_history"))
        if not lifecycle or lifecycle[-1] != status.value:
            lifecycle.append(status.value)
        value["lifecycle_history"] = lifecycle
        value["status"] = status.value
        terminal = status in {
            RunStatus.CONVERGED,
            RunStatus.FAILED_ROLLED_BACK,
            RunStatus.FAILED_PARTIAL,
            RunStatus.FAILED_RECOVERY_REQUIRED,
        }
        value["ended_at"] = self._clock.utc_now() if terminal else None
        return self._append(value, status, terminal=terminal)

    def _append(
        self,
        value: dict[str, object],
        status: RunStatus,
        *,
        terminal: bool,
    ) -> StoredRevision:
        chain = self._store.load_chain(self._run_id)
        value["revision"] = chain.head.revision + 1
        value["previous_revision_digest"] = chain.head.digest
        report = build_execution_run_report(value)
        return self._store.compare_and_append(
            self._lease,
            chain.head.revision,
            chain.head.digest,
            report.canonical_bytes,
            AppendIntent(
                status,
                terminal,
                DeviceIndexIntent.ADD_OR_RETAIN_ACTIVE,
                (
                    AuthorityPhase.RELEASE_PENDING
                    if terminal
                    else AuthorityPhase.REMOTE_OWNED
                ),
            ),
        )

    def _require_run(self, run_id: RunId) -> None:
        if run_id != self._run_id:
            raise ValueError("RunStore adapter is bound to another Run")


class _RunStoreInspectionPort:
    def __init__(
        self,
        persistence: RunStoreExecutionPersistence,
        environment: RecoveryEnvironment,
    ) -> None:
        self._persistence = persistence
        self._environment = environment

    def read_remote_ownership(self) -> RemoteOwnershipSnapshot:
        return self._environment.read_remote_ownership(self._persistence._run_id)

    def validate_local_evidence(
        self,
        first: RemoteOwnershipSnapshot,
    ) -> RecoveryEvidence:
        run_id = self._persistence._run_id
        chain = self._persistence.load_chain(run_id)
        value = decode_json_object(chain.head.payload)
        resources = self._persistence.resources(run_id)
        relations: list[StateRelation] = []
        rollback_declared = True
        rollback_approved = True
        for resource in resources:
            observation = resource.observe()
            if not isinstance(resource, BoundRecoveryResource):
                raise TypeError("reconstructed recovery Resource is not bound")
            prepared = resource.prepared
            managed = getattr(prepared, "managed_file", prepared)
            before = getattr(managed, "before", None)
            desired = getattr(managed, "desired", None)
            intermediates = getattr(managed, "allowed_intermediates", ())
            state = getattr(observation, "state", None)
            if before is not None and state == before:
                relations.append(StateRelation.BEFORE)
            elif desired is not None and state == desired:
                relations.append(StateRelation.POST)
            elif state in intermediates:
                relations.append(StateRelation.ALLOWED_INTERMEDIATE)
            elif state is None or getattr(state, "presence", None) is Presence.UNKNOWN:
                relations.append(StateRelation.UNKNOWN)
            else:
                relations.append(StateRelation.OTHER)
            rollback_declared = rollback_declared and bool(
                getattr(managed, "rollback_capable", False)
            )
            change = getattr(prepared, "change", None)
            rollback_approved = rollback_approved and bool(
                getattr(change, "rollback_approved", False)
            )
        current_relation = _aggregate_relation(relations)
        identity = first.identity
        binding_matches = (
            identity is not None
            and identity.run_id == run_id
            and identity.workspace_id == self._persistence._lease.workspace_id
            and identity.device_id.value == _text(value, "device_id")
        )
        cleanup_receipts = self._persistence._store.load_operational_receipts(
            run_id, "cleanup"
        )
        cleanup_by_resource = {
            receipt.resource_id: _cleanup_receipt_applied(receipt.payload)
            for receipt in cleanup_receipts
        }
        results = _list(value, "resource_results")
        evidence_records = _list(value, "evidence")
        forward_work_unperformed = not any(
            isinstance(item, dict)
            and item.get("payload_kind")
            in {"MutationIntent", "PrimitiveOutcome", "ResourceExecutionResult"}
            for item in evidence_records
        )
        rollback_complete = bool(results) and all(
            isinstance(item, dict)
            and item.get("rollback_outcome") == "restored_and_verified"
            for item in results
        )
        authority = value.get("authority")
        return RecoveryEvidence(
            run_id=run_id,
            workspace_id=self._persistence._lease.workspace_id,
            stable_snapshot=True,
            remote_ownership_presence=first.presence,
            remote_generation=first.generation,
            remote_phase=first.phase,
            remote_marker_digest=first.marker_digest,
            remote_integrity_valid=(
                first.marker_digest is not None and first.identity is not None
                if first.presence is Presence.PRESENT
                else None
            ),
            remote_quarantine_presence=self._environment.read_remote_quarantine(run_id),
            binding_matches=binding_matches,
            chain_valid=True,
            chain_complete=True,
            attachments_valid=True,
            codecs_valid=True,
            preparation_complete=bool(resources),
            rollback_declared=rollback_declared,
            rollback_approved=rollback_approved,
            live_helper=self._environment.live_helper(run_id),
            forward_work_unperformed=forward_work_unperformed,
            current_relation=current_relation,
            before_state=None,
            post_state=None,
            allowed_intermediate_states=(),
            effect_disposition=EffectDisposition.NOT_STARTED,
            effect_readiness_positive=None,
            post_effect_evidence_complete=True,
            rollback_complete_and_verified=rollback_complete,
            restore_effect_preplanned=False,
            restore_effect_approved=False,
            canonical_status=_status(chain.head),
            terminal_revision_durable=chain.terminal,
            cleanup_complete=(
                bool(resources)
                and len(cleanup_by_resource) == len(resources)
                and all(cleanup_by_resource.get(item.resource_id) for item in resources)
            ),
            ownership_release_or_quarantine_durable=(
                chain.terminal
                and isinstance(authority, dict)
                and authority.get("ownership_state") in {"released", "quarantined"}
            ),
            facts=(),
        )


def _preparation_records(content: bytes) -> tuple[PreparedResourceRecord, ...]:
    value = decode_json_object(content)
    records: list[PreparedResourceRecord] = []
    for evidence in _list(value, "evidence"):
        if not isinstance(evidence, dict):
            continue
        if evidence.get("payload_kind") != "ResourcePreparation":
            continue
        payload = evidence.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Resource preparation evidence is malformed")
        requires = payload.get("requires")
        if not isinstance(requires, list) or not all(
            isinstance(item, str) for item in requires
        ):
            raise ValueError("Resource dependency evidence is malformed")
        records.append(
            PreparedResourceRecord(
                _text(payload, "resource_id"),
                _text(payload, "type_code"),
                tuple(requires),
                _boolean(payload, "disruptive"),
                _text(payload, "attachment_digest"),
                _text(payload, "attachment_codec"),
            )
        )
    return tuple(records)


def _aggregate_relation(relations: list[StateRelation]) -> StateRelation:
    if not relations:
        return StateRelation.UNKNOWN
    first = relations[0]
    if all(relation is first for relation in relations):
        return first
    if StateRelation.UNKNOWN in relations:
        return StateRelation.UNKNOWN
    if StateRelation.OTHER in relations:
        return StateRelation.OTHER
    return StateRelation.ALLOWED_INTERMEDIATE


def _cleanup_receipt_applied(content: bytes) -> bool:
    value = decode_json_object(content)
    trace = value.get("trace")
    if not isinstance(trace, dict) or set(trace) != {"receipts"}:
        raise ValueError("cleanup receipt trace is malformed")
    receipts = trace["receipts"]
    return isinstance(receipts, list) and all(
        isinstance(item, dict) and item.get("disposition") == "applied"
        for item in receipts
    )


def _resource_result(result: ManagedFileExecutionResult) -> dict[str, object]:
    dispositions = tuple(receipt.disposition for receipt in result.mutation.receipts)
    mutation = (
        "ambiguous"
        if MutationDisposition.AMBIGUOUS in dispositions
        else "definitely_not_applied"
        if dispositions
        and all(
            item is MutationDisposition.DEFINITELY_NOT_APPLIED for item in dispositions
        )
        else "completed"
    )
    verification = result.verification.status.value
    convergence = (
        "converged"
        if result.converged
        else "recovery_required"
        if result.recovery_required
        else "failed_known"
    )
    return {
        "final_convergence": convergence,
        "latest_observed_relation": (
            "satisfied"
            if result.converged
            else "unknown"
            if result.recovery_required
            else "divergent"
        ),
        "mutation_outcome": mutation,
        "post_effect_verification": "not_applicable",
        "rollback_outcome": (
            "not_attempted"
            if result.rollback_verification is None
            else "restored_and_verified"
            if result.rollback_verification.status
            is ManagedFileVerificationStatus.MATCHED
            else "ambiguous"
        ),
        "verification_outcome": verification,
    }


def _rollback_result(
    trace: MutationTrace | None,
    verification: ManagedFileVerification,
) -> dict[str, object]:
    ambiguous = trace is not None and any(
        item.disposition is MutationDisposition.AMBIGUOUS for item in trace.receipts
    )
    return {
        "final_convergence": (
            "rolled_back_verified"
            if verification.status is ManagedFileVerificationStatus.MATCHED
            else "recovery_required"
        ),
        "latest_observed_relation": (
            "divergent"
            if verification.status is ManagedFileVerificationStatus.MATCHED
            else "unknown"
        ),
        "rollback_outcome": (
            "ambiguous"
            if ambiguous
            else "restored_and_verified"
            if verification.status is ManagedFileVerificationStatus.MATCHED
            else "failed"
        ),
    }


def _require_trace(value: object) -> MutationTrace:
    if not isinstance(value, MutationTrace):
        raise TypeError("cleanup result is not a MutationTrace")
    return value


def _status(revision: StoredRevision) -> RunStatus:
    return RunStatus(_text(decode_json_object(revision.payload), "status"))


def _list(value: Mapping[str, object], key: str) -> list[object]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ValueError(f"{key} is not an array")
    return item


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} is not text")
    return item


def _boolean(value: Mapping[str, object], key: str) -> bool:
    item = value.get(key)
    if type(item) is not bool:
        raise ValueError(f"{key} is not boolean")
    return item


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, bytes):
        return {"hex": value.hex()}
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    raise TypeError(f"unsupported canonical evidence value: {type(value).__name__}")
