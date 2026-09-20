"""RunStore-backed execution, recovery, attachment, and reconstruction adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.canonical_json import (
    decode_json_object,
)
from coreelec_reconciler.domain.configuration import ResolvedConfiguration
from coreelec_reconciler.domain.execution import (
    EXECUTION_EVIDENCE_OBSERVERS,
    AppendIntent,
    AttachmentRef,
    AuthorityPhase,
    CleanupMutationIntent,
    DeviceIndexIntent,
    EffectDisposition,
    EvidenceAttachment,
    EvidenceObserver,
    ExecutionEvidenceBindings,
    ExecutionEvidenceKind,
    ExecutionEvidenceRecord,
    MutationDisposition,
    MutationIntent,
    MutationOutcome,
    MutationTrace,
    NormalizedResourceState,
    Presence,
    RecoveryEvidence,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RemoteOwnershipSnapshot,
    ResourceMutationIntent,
    RevisionLease,
    RunStatus,
    SealIntent,
    StateRelation,
    StoredRevision,
    VerificationOutcome,
    VerifiedRunChain,
    build_execution_evidence,
    evidence_proves_terminal_cleanup,
    execution_run_identity,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.domain.planning import CanonicalRunReport, PlanDependencyGraph
from coreelec_reconciler.execution.authority import AcquiredAuthority
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    BoundRecoveryResource,
    ExecutableChange,
    RecoveryResource,
)
from coreelec_reconciler.execution.recovery import RecoveryInspectorPort
from coreelec_reconciler.execution.run_store import RunStore, RunStoreError
from coreelec_reconciler.persistence.document_codecs import (
    CanonicalExecutionDocumentCodec,
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
    PreparationError,
    PreparedManagedFile,
    normalized_state_digest,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry


class RunClock(Protocol):
    def utc_now(self) -> str: ...


class ExecutionDocumentCodec(Protocol):
    def build(
        self,
        value: dict[str, object],
        resource_registry: ResourceRegistry,
    ) -> CanonicalRunReport: ...


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
    change_id: str
    state_addresses: tuple[str, ...]
    manifest_digest: str
    attachment_digest: str
    attachment_kind: str
    attachment_codec: str


class RunStoreAttachmentStore:
    """AttachmentStore bound to one held Run lease."""

    def __init__(
        self,
        store: RunStore,
        lease: RevisionLease,
        allowed_codecs: frozenset[tuple[str, str]],
    ) -> None:
        if not isinstance(lease, RevisionLease):
            raise TypeError("RunStore attachment adapter requires a revision lease")
        self._store = store
        self._lease = lease
        self._allowed_codecs = allowed_codecs

    def attach(self, kind: str, codec: str, payload: bytes) -> AttachmentRef:
        if (kind, codec) not in self._allowed_codecs:
            raise ValueError("attachment codec is not registered for execution")
        return self._store.attach(self._lease, kind, codec, payload)

    def read_attachment(self, reference: AttachmentRef) -> bytes:
        if (reference.kind, reference.codec) not in self._allowed_codecs:
            raise ValueError("attachment codec is not registered for execution")
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
        local_identity = self._store.load_identity(run_id)
        device_id = DeviceId(_text(local_identity, "device_id"))
        device_lease = self._store.acquire_device(device_id)
        try:
            revision_lease = self._revision_lease or self._store.acquire_run(run_id)
        except Exception:
            self._store.release_device(device_lease)
            raise
        ownership = self._remote.read_ownership(device_id)
        expected_identity = RemoteOwnershipIdentity(
            device_id,
            run_id,
            revision_lease.workspace_id,
            _text(local_identity, "plan_id"),
            _text(local_identity, "plan_full_digest"),
            _text(local_identity, "binding_digest"),
            _text(local_identity, "boot_id"),
        )
        expected_token_digest = _text(local_identity, "ownership_token_digest")
        if (
            ownership.identity != expected_identity
            or ownership.token_digest != expected_token_digest
        ):
            if self._owns_revision_lease:
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


@dataclass(frozen=True, slots=True)
class _ResourceMetadata:
    resource_type: str
    change_id: str
    requires: tuple[str, ...]
    disruptive: bool
    state_addresses: tuple[str, ...]


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
        documents: ExecutionDocumentCodec | None = None,
        revision_lease: RevisionLease | None = None,
        dependency_graph: PlanDependencyGraph | None = None,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._lease = revision_lease or store.acquire_run(run_id)
        self._attachments = RunStoreAttachmentStore(
            store,
            self._lease,
            _allowed_attachment_codecs(registry),
        )
        self._registry = registry
        self._resource_types = dict(resource_types)
        self._contexts = contexts
        self._recovery_environment = recovery_environment
        self._clock = clock
        self._documents = documents or CanonicalExecutionDocumentCodec()
        self._dependency_graph = dependency_graph
        self._resource_metadata: dict[str, _ResourceMetadata] = {}
        self._prepared: dict[str, PreparedManagedFile] = {}
        self._last_operation: dict[str, tuple[str, str]] = {}
        self._corrupt_recovery = False
        self._corrupt_abandonment_digest: str | None = None
        self._corrupt_quarantine_digest: str | None = None

    def close(self) -> None:
        self._store.release_run(self._lease)

    @property
    def revision_lease(self) -> RevisionLease:
        return self._lease

    @property
    def attachment_store(self) -> RunStoreAttachmentStore:
        return self._attachments

    def start(self, plan: ApprovedPlan) -> None:
        if plan.run_id != self._run_id:
            raise ValueError("execution Plan does not bind to the Run")
        self._resource_metadata = {
            change.resource_id: _metadata_from_change(
                change,
                self._resource_types[change.resource_id],
            )
            for change in plan.changes
        }
        chain = self.load_chain(plan.run_id)
        if _status(chain.head) is RunStatus.READY:
            self._append_status(RunStatus.EXECUTING)

    def prepared(self, run_id: RunId, resource_id: str, prepared: object) -> None:
        descriptor = self._descriptor(resource_id)
        if descriptor.encode_prepared is None:
            raise ValueError("Resource Type does not support durable preparation")
        managed = _prepared_managed_file(prepared)
        metadata = self._metadata(resource_id)
        local_identity = execution_run_identity(
            decode_json_object(self.load_chain(run_id).head.payload)
        )
        if (
            managed.binding.run_id != run_id.value
            or managed.binding.device_id != _text(local_identity, "device_id")
            or managed.binding.binding_digest != _text(local_identity, "binding_digest")
            or managed.binding.resource_id != resource_id
            or managed.binding.change_id != metadata.change_id
        ):
            raise ValueError("prepared Resource bindings do not match execution")
        metadata = _ResourceMetadata(
            metadata.resource_type,
            metadata.change_id,
            metadata.requires,
            metadata.disruptive,
            (managed.address.logical_address,),
        )
        self._resource_metadata[resource_id] = metadata
        self._prepared[resource_id] = managed
        payload = descriptor.encode_prepared(prepared)
        reference = self._attachments.attach(
            "resource-preparation",
            f"{descriptor.type_code.lower()}-preparation-v1",
            payload,
        )
        manifest_reference = (
            reference
            if reference.digest == managed.manifest_digest
            else self._attachments.attach(
                "managed-file-preparation-manifest",
                "managed-file-preparation-v1",
                managed.manifest_bytes,
            )
        )
        observation_ref = f"evidence.{resource_id}.before"
        records = [
            self._resource_evidence(
                resource_id,
                ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION,
                observation_ref,
                _observation_payload(managed.before, "before"),
                attachments=(managed.rollback_attachment,),
                raw_attachment_digest=managed.rollback_attachment.digest,
            ),
            self._resource_evidence(
                resource_id,
                ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED,
                f"evidence.{resource_id}.preparation",
                {
                    "allowed_intermediate_state_digests": [
                        normalized_state_digest(item)
                        for item in managed.allowed_intermediates
                    ],
                    "before_state_attachment_digest": (
                        managed.rollback_attachment.digest
                    ),
                    "cleanup_object_refs": [managed.cleanup_object.object_id],
                    "desired_state_digest": normalized_state_digest(managed.desired),
                    "manifest_digest": managed.manifest_digest,
                    "preparation_manifest_attachment_digest": (
                        manifest_reference.digest
                    ),
                    "rollback_capable": managed.rollback_capable,
                },
                attachments=(
                    managed.rollback_attachment,
                    reference,
                    manifest_reference,
                    managed.cleanup_metadata_attachment,
                    managed.staged_metadata_attachment,
                    *(
                        ()
                        if managed.desired_attachment is None
                        else (managed.desired_attachment,)
                    ),
                ),
            ),
        ]
        self._append_records(records)

    def result(
        self,
        run_id: RunId,
        resource_id: str,
        result: ManagedFileExecutionResult,
    ) -> None:
        observation = result.verification.observation
        observation_ref = self._observation_evidence(
            resource_id,
            observation,
            "verification",
        )
        intent_ref, outcome_ref = self._last_operation.get(resource_id, (None, None))
        records = [
            observation_ref[0],
            self._resource_evidence(
                resource_id,
                ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT,
                f"evidence.{resource_id}.execution",
                {
                    "intent_evidence_ref": intent_ref,
                    "mutation_outcome": _mutation_outcome(result).value,
                    "outcome_evidence_ref": outcome_ref,
                },
            ),
            self._resource_evidence(
                resource_id,
                ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT,
                f"evidence.{resource_id}.verification",
                {
                    "observation_evidence_ref": observation_ref[1],
                    "outcome": _verification_outcome(result.verification).value,
                    "post_effect": False,
                    "relation": self._relation(resource_id, observation).value,
                },
            ),
        ]
        self._append_records(records, resource_result=_resource_result(result))

    def record_intent(
        self,
        run_id: RunId,
        resource_id: str,
        intent: MutationIntent,
    ) -> StoredRevision:
        payload: dict[str, object]
        if isinstance(intent, ResourceMutationIntent):
            payload = {
                "allowed_intermediate_state_digests": [
                    normalized_state_digest(item)
                    for item in intent.allowed_intermediates
                ],
                "content_attachment_digest": intent.content_attachment_digest,
                "expected_after_digest": normalized_state_digest(intent.expected_after),
                "expected_before_digest": normalized_state_digest(
                    intent.expected_before
                ),
                "manifest_object_ref": None,
                "marker_digest": intent.marker.marker_digest,
                "marker_generation": intent.marker.generation,
                "marker_phase": intent.marker.phase.value,
                "operation_id": intent.operation_id,
                "preparation_manifest_digest": intent.preparation_manifest_digest,
                "primitive": intent.primitive.value,
                "terminal_revision_digest": None,
                "token_digest": intent.marker.token_digest,
            }
            terminal_cleanup = False
        elif isinstance(intent, CleanupMutationIntent):
            payload = {
                "allowed_intermediate_state_digests": [],
                "content_attachment_digest": None,
                "expected_after_digest": None,
                "expected_before_digest": None,
                "manifest_object_ref": intent.manifest_object_ref,
                "marker_digest": intent.marker.marker_digest,
                "marker_generation": intent.marker.generation,
                "marker_phase": intent.marker.phase.value,
                "operation_id": intent.operation_id,
                "preparation_manifest_digest": None,
                "primitive": intent.primitive.value,
                "terminal_revision_digest": intent.terminal_or_seal_evidence_ref,
                "token_digest": intent.marker.token_digest,
            }
            terminal_cleanup = True
        else:
            raise TypeError("managed-file journal received an Effect intent")
        intent_ref = _evidence_id(resource_id, intent.operation_id, "intent")
        marker_ref = _evidence_id(resource_id, intent.operation_id, "marker")
        records = [
            self._resource_evidence(
                resource_id,
                ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
                intent_ref,
                payload,
                attachments=self._intent_attachments(resource_id, intent),
            ),
            self._resource_evidence(
                resource_id,
                ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
                marker_ref,
                {
                    "generation": intent.marker.generation,
                    "manifest_digest": (
                        intent.preparation_manifest_digest
                        if isinstance(intent, ResourceMutationIntent)
                        else None
                    ),
                    "marker_digest": intent.marker.marker_digest,
                    "operation_id": intent.operation_id,
                    "phase": intent.marker.phase.value,
                    "token_digest": intent.marker.token_digest,
                },
            ),
        ]
        self._last_operation[resource_id] = (intent_ref, "")
        return self._append_records(
            records,
            pending_attempt=None
            if terminal_cleanup
            else self._pending_attempt(resource_id, intent, intent_ref),
        )

    def record_primitive_outcome(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace,
        observation: ManagedFileObservation,
    ) -> StoredRevision:
        if not trace.receipts:
            raise ValueError("primitive outcome trace is empty")
        receipt = trace.receipts[-1]
        intent_ref, _ = self._last_operation[resource_id]
        operation_id = receipt.operation_id
        intent_record = self._evidence_by_id(intent_ref)
        intent_payload = dict(intent_record.payload)
        if intent_payload["primitive"] == "cleanup":
            receipt_ref = _evidence_id(resource_id, operation_id, "cleanup")
            record = self._resource_evidence(
                resource_id,
                ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT,
                receipt_ref,
                {
                    "disposition": receipt.disposition.value,
                    "leftover": receipt.disposition is MutationDisposition.AMBIGUOUS,
                    "manifest_object_ref": intent_payload["manifest_object_ref"],
                    "operation_id": operation_id,
                    "terminal_revision_digest": intent_payload[
                        "terminal_revision_digest"
                    ],
                },
            )
            self._last_operation[resource_id] = (intent_ref, receipt_ref)
            return self._append_records([record])
        observation_record, observation_ref = self._observation_evidence(
            resource_id,
            observation,
            f"{operation_id}.outcome",
        )
        outcome_ref = _evidence_id(resource_id, operation_id, "outcome")
        outcome = self._resource_evidence(
            resource_id,
            ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME,
            outcome_ref,
            {
                "disposition": receipt.disposition.value,
                "observation_evidence_ref": observation_ref,
                "observed_state_digest": normalized_state_digest(observation.state),
                "operation_id": operation_id,
                "receipt_sequence": len(trace.receipts),
            },
        )
        self._last_operation[resource_id] = (intent_ref, outcome_ref)
        return self._append_records(
            [observation_record, outcome],
            completed_attempt=(
                f"attempt.{operation_id}",
                receipt.disposition.value,
                outcome_ref,
            ),
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
        self._append_records(
            [
                self._resource_evidence(
                    resource_id,
                    ExecutionEvidenceKind.RESOURCE_SKIP_RESULT,
                    f"evidence.{resource_id}.skip",
                    {
                        "final_convergence": (
                            "skipped_dependency"
                            if dependency_ids
                            else "skipped_run_stopped"
                        ),
                        "reason_code": (
                            "skip.dependency" if dependency_ids else "skip.run-stopped"
                        ),
                        "stop_scope": "resource",
                    },
                )
            ],
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
        records = _preparation_records(
            self._store.load_chain(run_id).head.payload,
            self._registry,
        )
        if self._dependency_graph is not None:
            by_resource = {record.resource_id: record for record in records}
            if set(by_resource) != set(self._dependency_graph.execution_order):
                raise ValueError("prepared Resources do not match saved Plan graph")
            records = tuple(
                by_resource[resource_id]
                for resource_id in self._dependency_graph.execution_order
            )
        resources: list[RecoveryResource] = []
        for record in records:
            descriptor = self._registry.descriptor(record.type_code)
            if (
                descriptor is None
                or descriptor.decode_prepared is None
                or descriptor.execution_factory is None
            ):
                raise ValueError("persisted Resource Type cannot be reconstructed")
            reference = AttachmentRef(
                record.attachment_digest,
                record.attachment_kind,
                record.attachment_codec,
            )
            payload = self._attachments.read_attachment(reference)
            prepared = descriptor.decode_prepared(payload, self._attachments)
            context = self._contexts.context(
                run_id,
                record.resource_id,
                record.type_code,
                self._attachments,
            )
            managed = _prepared_managed_file(prepared)
            if (
                managed.binding != context.binding
                or managed.binding.change_id != record.change_id
                or managed.address != context.address
                or record.state_addresses != (context.address.logical_address,)
                or managed.manifest_digest != record.manifest_digest
            ):
                raise ValueError(
                    "prepared Resource does not match current execution context"
                )
            self._resource_metadata[record.resource_id] = _ResourceMetadata(
                record.type_code,
                record.change_id,
                (
                    self._dependency_graph.requires(record.resource_id)
                    if self._dependency_graph is not None
                    else ()
                ),
                False,
                record.state_addresses,
            )
            self._prepared[record.resource_id] = managed
            runtime = descriptor.execution_factory(context)
            resources.append(
                BoundRecoveryResource(runtime, prepared, record.resource_id)
            )
        return tuple(resources)

    def record_verification(
        self,
        run_id: RunId,
        resource_id: str,
        observation: object,
        assessment: object,
    ) -> StoredRevision:
        if not isinstance(observation, ManagedFileObservation):
            raise TypeError("recovery Verification requires managed-file Observation")
        observation_record, observation_ref = self._observation_evidence(
            resource_id, observation, "recovery"
        )
        verification = _require_verification(assessment, observation)
        return self._append_records(
            [
                observation_record,
                self._resource_evidence(
                    resource_id,
                    ExecutionEvidenceKind.RECOVERY_VERIFICATION_RESULT,
                    f"evidence.{resource_id}.recovery-verification",
                    {
                        "action": "resume_verification",
                        "observation_evidence_ref": observation_ref,
                        "outcome": _verification_outcome(verification).value,
                        "relation": self._relation(resource_id, observation).value,
                    },
                ),
            ]
        )

    def record_rollback(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace | None,
        verification: ManagedFileVerification,
    ) -> StoredRevision:
        observation_record, observation_ref = self._observation_evidence(
            resource_id, verification.observation, "rollback"
        )
        return self._append_records(
            [
                observation_record,
                self._resource_evidence(
                    resource_id,
                    ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT,
                    f"evidence.{resource_id}.rollback",
                    {
                        "observation_evidence_ref": observation_ref,
                        "original_failure_code": "failure.verification",
                        "outcome": _rollback_outcome(trace, verification),
                        "relation": self._relation(
                            resource_id, verification.observation
                        ).value,
                    },
                ),
            ],
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
        if self._corrupt_recovery:
            record = self._trusted_run_evidence(
                ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL,
                "evidence.run.abandonment",
                {
                    "actor": approval,
                    "approved_at": self._clock.utc_now(),
                    "mechanism": "noninteractive-cli",
                    "reason": reason,
                },
            )
            stored = self._store.record_corrupt_recovery_evidence(
                self._lease,
                record,
            )
            self._corrupt_abandonment_digest = stored.digest
            return stored
        self._append_records(
            [
                self._run_evidence(
                    ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL,
                    "evidence.run.abandonment",
                    {
                        "actor": approval,
                        "approved_at": self._clock.utc_now(),
                        "mechanism": "noninteractive-cli",
                        "reason": reason,
                    },
                )
            ]
        )
        return self._append_status(RunStatus.FAILED_RECOVERY_REQUIRED)

    def record_cleanup(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace,
    ) -> str:
        self._require_run(run_id)
        if any(
            receipt.disposition is MutationDisposition.AMBIGUOUS
            for receipt in trace.receipts
        ):
            return self.load_chain(run_id).head.digest
        return self.load_chain(run_id).head.digest

    def seal(self, run_id: RunId, intent: SealIntent) -> None:
        self._require_run(run_id)
        if self._corrupt_recovery:
            if (
                self._corrupt_abandonment_digest is None
                or self._corrupt_quarantine_digest is None
            ):
                raise ValueError("corrupt Run lacks abandonment or quarantine truth")
            self._store.seal_corrupt_quarantine(
                self._lease,
                self._corrupt_abandonment_digest,
                self._corrupt_quarantine_digest,
            )
            return
        self._store.finalize_and_seal(self._lease, intent)

    def record_authority_state(
        self,
        run_id: RunId,
        ownership_state: str,
        *,
        quarantine_receipt_digest: str | None = None,
        generation: int | None = None,
        marker_digest: str | None = None,
        marker_phase: RemoteMarkerPhase | None = None,
        token_digest: str | None = None,
    ) -> StoredRevision:
        self._require_run(run_id)
        if self._corrupt_recovery:
            if ownership_state != "quarantined" or quarantine_receipt_digest is None:
                raise ValueError("corrupt Run may only record quarantine authority")
            identity = self._store.load_identity(run_id)
            record = build_execution_evidence(
                evidence_id="evidence.authority.quarantined.corrupt",
                observed_at=self._clock.utc_now(),
                observer=EvidenceObserver(
                    _observer_code(ExecutionEvidenceKind.AUTHORITY_EVIDENCE), 1
                ),
                subject_kind="device",
                subject_id=_text(identity, "device_id"),
                resource_type=None,
                bindings=self._trusted_evidence_bindings(),
                state_addresses=(),
                attachment_refs=(),
                attempt=None,
                kind=ExecutionEvidenceKind.AUTHORITY_EVIDENCE,
                payload={
                    "generation": generation,
                    "manifest_digest": None,
                    "marker_digest": marker_digest,
                    "ownership_state": "quarantined",
                    "phase": (marker_phase.value if marker_phase is not None else None),
                    "quarantine_receipt_digest": quarantine_receipt_digest,
                    "token_digest": token_digest,
                },
                resource_registry=self._registry,
            )
            stored = self._store.record_corrupt_recovery_evidence(
                self._lease,
                record,
            )
            self._corrupt_quarantine_digest = stored.digest
            return stored
        chain = self.load_chain(run_id)
        value = decode_json_object(chain.head.payload)
        authority = value.get("authority")
        if not isinstance(authority, dict):
            raise ValueError("Run authority summary is malformed")
        if authority.get("ownership_state") == ownership_state:
            return chain.head
        record = self._authority_evidence(
            f"evidence.authority.{ownership_state}.{chain.head.revision + 1}",
            {
                "generation": authority.get("marker_generation"),
                "manifest_digest": None,
                "marker_digest": authority.get("marker_digest"),
                "ownership_state": ownership_state,
                "phase": authority.get("marker_phase"),
                "quarantine_receipt_digest": quarantine_receipt_digest,
                "token_digest": authority.get("ownership_token_digest"),
            },
        )
        authority["ownership_state"] = ownership_state
        authority["device_index_intent"] = "remove_after_release_or_quarantine"
        value["authority"] = authority
        evidence = list(_list(value, "evidence"))
        evidence.append(record)
        value["evidence"] = evidence
        return self._append(value, _status(chain.head), terminal=True)

    def _descriptor(self, resource_id: str) -> ResourceDescriptor:
        type_code = self._resource_types.get(resource_id)
        descriptor = (
            self._registry.descriptor(type_code) if type_code is not None else None
        )
        if descriptor is None:
            raise ValueError("Resource Type is not registered")
        return descriptor

    def _append_records(
        self,
        records: list[dict[str, object]],
        *,
        resource_result: dict[str, object] | None = None,
        pending_attempt: dict[str, object] | None = None,
        completed_attempt: tuple[str, str, str] | None = None,
    ) -> StoredRevision:
        chain = self._store.load_chain(self._run_id)
        value = decode_json_object(chain.head.payload)
        evidence = list(_list(value, "evidence"))
        evidence.extend(records)
        value["evidence"] = evidence
        _update_cleanup_summary(value, records)
        attachments = list(_list(value, "attachments"))
        known_digests = {
            item.get("digest") for item in attachments if isinstance(item, dict)
        }
        for record in records:
            for attachment in _list(record, "attachment_refs"):
                if (
                    isinstance(attachment, dict)
                    and attachment.get("digest") not in known_digests
                ):
                    attachments.append(dict(attachment))
                    known_digests.add(attachment.get("digest"))
        value["attachments"] = attachments
        attempts = list(_list(value, "attempts"))
        if pending_attempt is not None:
            attempts.append(pending_attempt)
        if completed_attempt is not None:
            attempt_id, disposition, outcome_ref = completed_attempt
            for item in attempts:
                if isinstance(item, dict) and item.get("attempt_id") == attempt_id:
                    item["ended_at"] = self._clock.utc_now()
                    item["outcome"] = _attempt_outcome(disposition)
                    item["outcome_evidence_ref"] = outcome_ref
                    break
            else:
                raise ValueError("primitive outcome has no durable intent attempt")
        value["attempts"] = attempts
        if resource_result is not None:
            bindings_value = records[-1].get("bindings")
            if not isinstance(bindings_value, dict):
                raise ValueError("Resource evidence bindings are unavailable")
            resource_id = _text(bindings_value, "resource_id")
            results = list(_list(value, "resource_results"))
            for item in results:
                if isinstance(item, dict) and item.get("resource_id") == resource_id:
                    item.update(resource_result)
                    break
            value["resource_results"] = results
        return self._append(value, _status(chain.head), terminal=chain.terminal)

    def _resource_evidence(
        self,
        resource_id: str,
        kind: ExecutionEvidenceKind,
        evidence_id: str,
        payload: dict[str, object],
        *,
        attachments: tuple[AttachmentRef, ...] = (),
        raw_attachment_digest: str | None = None,
    ) -> dict[str, object]:
        metadata = self._metadata(resource_id)
        return build_execution_evidence(
            evidence_id=evidence_id,
            observed_at=self._clock.utc_now(),
            observer=EvidenceObserver(_observer_code(kind), 1),
            subject_kind="resource",
            subject_id=resource_id,
            resource_type=metadata.resource_type,
            bindings=self._evidence_bindings(resource_id),
            state_addresses=metadata.state_addresses,
            attachment_refs=_evidence_attachments(attachments),
            attempt=1,
            kind=kind,
            payload=payload,
            resource_registry=self._registry,
            raw_attachment_digest=raw_attachment_digest,
        )

    def _run_evidence(
        self,
        kind: ExecutionEvidenceKind,
        evidence_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        bindings = self._evidence_bindings(None)
        return build_execution_evidence(
            evidence_id=evidence_id,
            observed_at=self._clock.utc_now(),
            observer=EvidenceObserver(_observer_code(kind), 1),
            subject_kind="run",
            subject_id=bindings.run_id,
            resource_type=None,
            bindings=bindings,
            state_addresses=(),
            attachment_refs=(),
            attempt=None,
            kind=kind,
            payload=payload,
            resource_registry=self._registry,
        )

    def _trusted_run_evidence(
        self,
        kind: ExecutionEvidenceKind,
        evidence_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        bindings = self._trusted_evidence_bindings()
        return build_execution_evidence(
            evidence_id=evidence_id,
            observed_at=self._clock.utc_now(),
            observer=EvidenceObserver(_observer_code(kind), 1),
            subject_kind="run",
            subject_id=bindings.run_id,
            resource_type=None,
            bindings=bindings,
            state_addresses=(),
            attachment_refs=(),
            attempt=None,
            kind=kind,
            payload=payload,
            resource_registry=self._registry,
        )

    def _authority_evidence(
        self,
        evidence_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        bindings = self._evidence_bindings(None)
        return build_execution_evidence(
            evidence_id=evidence_id,
            observed_at=self._clock.utc_now(),
            observer=EvidenceObserver(
                _observer_code(ExecutionEvidenceKind.AUTHORITY_EVIDENCE), 1
            ),
            subject_kind="device",
            subject_id=bindings.device_id,
            resource_type=None,
            bindings=bindings,
            state_addresses=(),
            attachment_refs=(),
            attempt=None,
            kind=ExecutionEvidenceKind.AUTHORITY_EVIDENCE,
            payload=payload,
            resource_registry=self._registry,
        )

    def _evidence_bindings(self, resource_id: str | None) -> ExecutionEvidenceBindings:
        value = decode_json_object(self.load_chain(self._run_id).head.payload)
        identity = execution_run_identity(value)
        metadata = self._metadata(resource_id) if resource_id is not None else None
        return ExecutionEvidenceBindings(
            _text(identity, "device_id"),
            _text(identity, "run_id"),
            _text(identity, "workspace_id"),
            _text(identity, "plan_id"),
            _text(identity, "plan_full_digest"),
            _text(identity, "binding_digest"),
            resource_id,
            metadata.change_id if metadata is not None else None,
        )

    def _trusted_evidence_bindings(self) -> ExecutionEvidenceBindings:
        identity = self._store.load_identity(self._run_id)
        return ExecutionEvidenceBindings(
            _text(identity, "device_id"),
            _text(identity, "run_id"),
            _text(identity, "workspace_id"),
            _text(identity, "plan_id"),
            _text(identity, "plan_full_digest"),
            _text(identity, "binding_digest"),
            None,
            None,
        )

    def _metadata(self, resource_id: str) -> _ResourceMetadata:
        try:
            return self._resource_metadata[resource_id]
        except KeyError as error:
            raise ValueError("Resource execution metadata is unavailable") from error

    def _observation_evidence(
        self,
        resource_id: str,
        observation: ManagedFileObservation,
        suffix: str,
    ) -> tuple[dict[str, object], str]:
        evidence_id = _evidence_id(resource_id, suffix, "observation")
        return (
            self._resource_evidence(
                resource_id,
                ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION,
                evidence_id,
                _observation_payload(
                    observation.state,
                    self._relation(resource_id, observation).value,
                ),
            ),
            evidence_id,
        )

    def _relation(
        self, resource_id: str, observation: ManagedFileObservation
    ) -> StateRelation:
        prepared = self._prepared.get(resource_id)
        if prepared is None:
            return StateRelation.UNKNOWN
        if observation.state == prepared.before:
            return StateRelation.BEFORE
        if observation.state == prepared.desired:
            return StateRelation.POST
        if observation.state in prepared.allowed_intermediates:
            return StateRelation.ALLOWED_INTERMEDIATE
        if observation.state.presence is Presence.UNKNOWN:
            return StateRelation.UNKNOWN
        return StateRelation.OTHER

    def _intent_attachments(
        self, resource_id: str, intent: MutationIntent
    ) -> tuple[AttachmentRef, ...]:
        if not isinstance(intent, ResourceMutationIntent):
            return ()
        digest = intent.content_attachment_digest
        if digest is None:
            return ()
        prepared = self._prepared[resource_id]
        for reference in (
            prepared.rollback_attachment,
            prepared.desired_attachment,
        ):
            if reference is not None and reference.digest == digest:
                return (reference,)
        raise ValueError("primitive intent attachment is not prepared")

    def _pending_attempt(
        self,
        resource_id: str,
        intent: ResourceMutationIntent | CleanupMutationIntent,
        intent_ref: str,
    ) -> dict[str, object]:
        metadata = self._metadata(resource_id)
        bindings = self._evidence_bindings(resource_id)
        return {
            "attempt": 1,
            "attempt_id": f"attempt.{intent.operation_id}",
            "bindings": _bindings_value(bindings),
            "ended_at": None,
            "intent_evidence_ref": intent_ref,
            "operation_code": intent.primitive.value,
            "outcome": "pending",
            "outcome_evidence_ref": None,
            "phase": "mutation",
            "resource_type": metadata.resource_type,
            "started_at": self._clock.utc_now(),
            "state_addresses": list(metadata.state_addresses),
            "subject": {"id": resource_id, "kind": "resource"},
        }

    def _evidence_by_id(self, evidence_id: str) -> ExecutionEvidenceRecord:
        value = decode_json_object(self.load_chain(self._run_id).head.payload)
        from coreelec_reconciler.domain.execution import decode_execution_evidence

        for item in _list(value, "evidence"):
            if isinstance(item, dict) and item.get("evidence_id") == evidence_id:
                return decode_execution_evidence(item, resource_registry=self._registry)
        raise ValueError("durable evidence reference is missing")

    def _append_status(self, status: RunStatus) -> StoredRevision:
        chain = self._store.load_chain(self._run_id)
        value = decode_json_object(chain.head.payload)
        lifecycle = list(_list(value, "lifecycle_history"))
        if not lifecycle or lifecycle[-1] != status.value:
            lifecycle.append(status.value)
        value["lifecycle_history"] = lifecycle
        value["status"] = status.value
        if status is RunStatus.FAILED_ROLLED_BACK:
            for result in _list(value, "resource_results"):
                if (
                    isinstance(result, dict)
                    and result.get("mutation_outcome") == "not_required"
                    and result.get("final_convergence") == "converged"
                ):
                    result["rollback_outcome"] = "restored_or_unchanged"
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
        report = self._documents.build(value, self._registry)
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
        try:
            return self._validate_complete_evidence(first)
        except RunStoreError, PreparationError, TypeError, ValueError:
            self._persistence._corrupt_recovery = True
            return self._corrupt_evidence(first)

    def _validate_complete_evidence(
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
        local_identity = execution_run_identity(value)
        expected_identity = RemoteOwnershipIdentity(
            DeviceId(_text(local_identity, "device_id")),
            run_id,
            self._persistence._lease.workspace_id,
            _text(local_identity, "plan_id"),
            _text(local_identity, "plan_full_digest"),
            _text(local_identity, "binding_digest"),
            _text(local_identity, "boot_id"),
        )
        expected_token_digest = _text(local_identity, "ownership_token_digest")
        binding_matches = (
            identity == expected_identity
            and first.token_digest == expected_token_digest
        )
        results = _list(value, "resource_results")
        evidence_records = _list(value, "evidence")
        forward_work_unperformed = not any(
            isinstance(item, dict)
            and item.get("payload_kind")
            in {
                ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT.value,
                ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME.value,
                ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT.value,
            }
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
                first.marker_digest is not None and binding_matches
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
            cleanup_complete=evidence_proves_terminal_cleanup(
                value,
                resource_registry=self._persistence._registry,
            ),
            ownership_release_or_quarantine_durable=(
                chain.terminal
                and isinstance(authority, dict)
                and authority.get("ownership_state") in {"released", "quarantined"}
            ),
            facts=(),
        )

    def _corrupt_evidence(
        self,
        first: RemoteOwnershipSnapshot,
    ) -> RecoveryEvidence:
        run_id = self._persistence._run_id
        identity = self._persistence._store.load_identity(run_id)
        expected = RemoteOwnershipIdentity(
            DeviceId(_text(identity, "device_id")),
            run_id,
            self._persistence._lease.workspace_id,
            _text(identity, "plan_id"),
            _text(identity, "plan_full_digest"),
            _text(identity, "binding_digest"),
            _text(identity, "boot_id"),
        )
        binding_matches = first.identity == expected and first.token_digest == _text(
            identity, "ownership_token_digest"
        )
        return RecoveryEvidence(
            run_id=run_id,
            workspace_id=self._persistence._lease.workspace_id,
            stable_snapshot=True,
            remote_ownership_presence=first.presence,
            remote_generation=first.generation,
            remote_phase=first.phase,
            remote_marker_digest=first.marker_digest,
            remote_integrity_valid=(
                first.marker_digest is not None and binding_matches
                if first.presence is Presence.PRESENT
                else None
            ),
            remote_quarantine_presence=self._environment.read_remote_quarantine(run_id),
            binding_matches=binding_matches,
            chain_valid=False,
            chain_complete=False,
            attachments_valid=False,
            codecs_valid=False,
            preparation_complete=False,
            rollback_declared=False,
            rollback_approved=False,
            live_helper=self._environment.live_helper(run_id),
            forward_work_unperformed=False,
            current_relation=StateRelation.UNKNOWN,
            before_state=None,
            post_state=None,
            allowed_intermediate_states=(),
            effect_disposition=EffectDisposition.NOT_STARTED,
            effect_readiness_positive=None,
            post_effect_evidence_complete=False,
            rollback_complete_and_verified=False,
            restore_effect_preplanned=False,
            restore_effect_approved=False,
            canonical_status=RunStatus.FAILED_RECOVERY_REQUIRED,
            terminal_revision_durable=False,
            cleanup_complete=False,
            ownership_release_or_quarantine_durable=False,
            facts=(),
        )


def _preparation_records(
    content: bytes,
    registry: ResourceRegistry,
) -> tuple[PreparedResourceRecord, ...]:
    from coreelec_reconciler.domain.execution import decode_execution_evidence

    value = decode_json_object(content)
    records: list[PreparedResourceRecord] = []
    for evidence in _list(value, "evidence"):
        record = decode_execution_evidence(
            evidence,
            resource_registry=registry,
        )
        if record.kind is not ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED:
            continue
        if (
            record.resource_type is None
            or record.bindings.resource_id is None
            or record.bindings.change_id is None
        ):
            raise ValueError("Resource preparation bindings are incomplete")
        payload = dict(record.payload)
        manifest_attachment_digest = _text(
            payload, "preparation_manifest_attachment_digest"
        )
        manifest_attachment = next(
            (
                item
                for item in record.attachment_refs
                if item.digest == manifest_attachment_digest
            ),
            None,
        )
        attachment = next(
            (
                item
                for item in record.attachment_refs
                if item.kind == "resource-preparation"
            ),
            None,
        )
        if manifest_attachment is None or attachment is None:
            raise ValueError("Resource preparation attachment is missing")
        records.append(
            PreparedResourceRecord(
                record.bindings.resource_id,
                record.resource_type,
                record.bindings.change_id,
                record.state_addresses,
                _text(payload, "manifest_digest"),
                attachment.digest,
                attachment.kind,
                attachment.codec,
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


def _metadata_from_change(
    change: ExecutableChange, resource_type: str
) -> _ResourceMetadata:
    typed_change = getattr(change, "change", None)
    change_id = getattr(typed_change, "change_id", None)
    if not isinstance(change_id, str) or not change_id:
        raise ValueError("executable Change lacks a canonical Change ID")
    return _ResourceMetadata(
        resource_type,
        change_id,
        change.requires,
        change.disruptive,
        (),
    )


def _allowed_attachment_codecs(
    registry: ResourceRegistry,
) -> frozenset[tuple[str, str]]:
    managed_file = {
        ("managed-file-before-state", "managed-file-before-v1"),
        ("managed-file-desired-content", "managed-file-content-v1"),
        ("managed-file-staged-object", "managed-file-object-v1"),
        ("managed-file-cleanup-object", "managed-file-object-v1"),
        ("managed-file-preparation-manifest", "managed-file-preparation-v1"),
    }
    resource_preparation = {
        ("resource-preparation", f"{type_code.lower()}-preparation-v1")
        for type_code in registry.type_codes
    }
    return frozenset(managed_file | resource_preparation)


def _prepared_managed_file(value: object) -> PreparedManagedFile:
    managed = getattr(value, "managed_file", value)
    if not isinstance(managed, PreparedManagedFile):
        raise TypeError("prepared Resource lacks managed-file evidence")
    return managed


def _observer_code(kind: ExecutionEvidenceKind) -> str:
    return EXECUTION_EVIDENCE_OBSERVERS[kind]


def _observation_payload(
    state: NormalizedResourceState, relation: str
) -> dict[str, object]:
    return {
        "content_digest": state.content_digest,
        "entry_kind": state.entry_kind,
        "managed_mode": state.managed_mode,
        "normalized_state_digest": normalized_state_digest(state),
        "presence": state.presence.value,
        "relation": relation,
    }


def _evidence_id(resource_id: str, operation_id: str, suffix: str) -> str:
    safe_operation = operation_id.replace(":", ".")
    return f"evidence.{resource_id}.{safe_operation}.{suffix}"


def _bindings_value(bindings: ExecutionEvidenceBindings) -> dict[str, object]:
    return {
        "binding_digest": bindings.binding_digest,
        "change_id": bindings.change_id,
        "device_id": bindings.device_id,
        "plan_full_digest": bindings.plan_full_digest,
        "plan_id": bindings.plan_id,
        "resource_id": bindings.resource_id,
        "run_id": bindings.run_id,
        "workspace_id": bindings.workspace_id,
    }


def _evidence_attachments(
    references: tuple[AttachmentRef, ...],
) -> tuple[EvidenceAttachment, ...]:
    result: list[EvidenceAttachment] = []
    seen: set[str] = set()
    for reference in references:
        if reference.digest in seen:
            continue
        seen.add(reference.digest)
        result.append(
            EvidenceAttachment(reference.digest, reference.kind, reference.codec)
        )
    return tuple(result)


def _attempt_outcome(disposition: str) -> str:
    if disposition == MutationDisposition.APPLIED.value:
        return "completed"
    return disposition


def _update_cleanup_summary(
    run: dict[str, object],
    added_records: list[dict[str, object]],
) -> None:
    kinds = {item.get("payload_kind") for item in added_records}
    cleanup = run.get("cleanup")
    authority = run.get("authority")
    if not isinstance(cleanup, dict) or not isinstance(authority, dict):
        raise ValueError("Run cleanup or authority summary is malformed")
    cleanup_intent = False
    for item in added_records:
        payload_value = item.get("payload")
        if (
            item.get("payload_kind")
            == ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT.value
            and isinstance(payload_value, dict)
            and payload_value.get("primitive") == "cleanup"
        ):
            cleanup_intent = True
            break
    if cleanup_intent:
        cleanup["state"] = "pending"
        authority["cleanup_state"] = "pending"
    if ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT.value not in kinds:
        return
    required: set[tuple[object, object, object]] = set()
    receipts: dict[tuple[object, object, object], dict[str, object]] = {}
    for record_value in _list(run, "evidence"):
        if not isinstance(record_value, dict):
            continue
        evidence_payload = record_value.get("payload")
        bindings = record_value.get("bindings")
        if not isinstance(evidence_payload, dict) or not isinstance(bindings, dict):
            continue
        if record_value.get("payload_kind") == (
            ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED.value
        ):
            objects = evidence_payload.get("cleanup_object_refs")
            if isinstance(objects, list):
                required.update(
                    (bindings.get("resource_id"), bindings.get("change_id"), obj)
                    for obj in objects
                )
        elif record_value.get("payload_kind") == (
            ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT.value
        ):
            key = (
                bindings.get("resource_id"),
                bindings.get("change_id"),
                evidence_payload.get("manifest_object_ref"),
            )
            receipts[key] = evidence_payload
    leftovers = sum(payload.get("leftover") is True for payload in receipts.values())
    complete = (
        set(receipts) == required
        and all(
            payload.get("disposition")
            in {
                MutationDisposition.APPLIED.value,
                MutationDisposition.DEFINITELY_NOT_APPLIED.value,
            }
            for payload in receipts.values()
        )
        and leftovers == 0
    )
    cleanup["state"] = "complete" if complete else "failed"
    cleanup["leftover_count"] = leftovers
    authority["cleanup_state"] = cleanup["state"]


def _mutation_outcome(result: ManagedFileExecutionResult) -> MutationOutcome:
    if not result.mutation.receipts:
        return MutationOutcome.NOT_REQUIRED
    if any(
        item.disposition is MutationDisposition.AMBIGUOUS
        for item in result.mutation.receipts
    ):
        return MutationOutcome.AMBIGUOUS
    if all(
        item.disposition is MutationDisposition.DEFINITELY_NOT_APPLIED
        for item in result.mutation.receipts
    ):
        return MutationOutcome.DEFINITELY_NOT_APPLIED
    return MutationOutcome.COMPLETED


def _verification_outcome(
    verification: ManagedFileVerification,
) -> VerificationOutcome:
    return {
        ManagedFileVerificationStatus.MATCHED: VerificationOutcome.MATCHED,
        ManagedFileVerificationStatus.MISMATCH: VerificationOutcome.MISMATCH,
        ManagedFileVerificationStatus.UNKNOWN: VerificationOutcome.UNKNOWN,
    }[verification.status]


def _rollback_outcome(
    trace: MutationTrace | None,
    verification: ManagedFileVerification,
) -> str:
    if trace is not None and any(
        item.disposition is MutationDisposition.AMBIGUOUS for item in trace.receipts
    ):
        return "ambiguous"
    if verification.status is ManagedFileVerificationStatus.MATCHED:
        return "restored_and_verified"
    return "failed"


def _require_verification(
    assessment: object, observation: ManagedFileObservation
) -> ManagedFileVerification:
    relation = getattr(assessment, "relation", None)
    status = (
        ManagedFileVerificationStatus.MATCHED
        if getattr(relation, "value", None) == "satisfied"
        else ManagedFileVerificationStatus.UNKNOWN
        if getattr(relation, "value", None) == "unverifiable"
        else ManagedFileVerificationStatus.MISMATCH
    )
    return ManagedFileVerification(status, observation)


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
