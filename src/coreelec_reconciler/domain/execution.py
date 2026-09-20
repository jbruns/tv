"""Closed execution, persistence, and recovery vocabulary."""

import hashlib
import re
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from coreelec_reconciler.domain.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.domain.validation import (
    parse_rfc3339_utc,
    require_logical_id,
    require_rfc3339_utc,
    require_sha256,
    require_uuid7,
)


class RunStatus(StrEnum):
    PLANNING = "planning"
    BLOCKED = "blocked"
    NOOP = "noop"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    EXECUTING = "executing"
    INTERRUPTED = "interrupted"
    CONVERGED = "converged"
    FAILED_ROLLED_BACK = "failed_rolled_back"
    FAILED_PARTIAL = "failed_partial"
    FAILED_RECOVERY_REQUIRED = "failed_recovery_required"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.BLOCKED,
        RunStatus.NOOP,
        RunStatus.CONVERGED,
        RunStatus.FAILED_ROLLED_BACK,
        RunStatus.FAILED_PARTIAL,
        RunStatus.FAILED_RECOVERY_REQUIRED,
    }
)


class AuthorityPhase(StrEnum):
    ACQUISITION_PENDING = "acquisition_pending"
    REMOTE_OWNED = "remote_owned"
    MUTATION_INTENT_DURABLE = "mutation_intent_durable"
    RELEASE_PENDING = "release_pending"


class DeviceIndexIntent(StrEnum):
    ADD_OR_RETAIN_ACTIVE = "add_or_retain_active"
    REMOVE_AFTER_RELEASE_OR_QUARANTINE = "remove_after_release_or_quarantine"
    NO_CHANGE = "no_change"


class MutationDisposition(StrEnum):
    APPLIED = "applied"
    DEFINITELY_NOT_APPLIED = "definitely_not_applied"
    AMBIGUOUS = "ambiguous"


class PrimitiveKind(StrEnum):
    STAGE_WRITE = "stage_write"
    CHMOD = "chmod"
    ATOMIC_REPLACE = "atomic_replace"
    REMOVE = "remove"
    RESTORE = "restore"
    EFFECT = "effect"
    RESTORE_EFFECT = "restore_effect"
    CLEANUP = "cleanup"


class FactState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class Presence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class RecoveryActionCode(StrEnum):
    INSPECT = "inspect"
    RESUME_VERIFICATION = "resume_verification"
    ROLLBACK = "rollback"
    FINALIZE = "finalize"


class FinalizeMode(StrEnum):
    NORMAL = "normal"
    ABANDON = "abandon"


class EffectDisposition(StrEnum):
    NOT_STARTED = "not_started"
    DEFINITELY_SUCCEEDED = "definitely_succeeded"
    DEFINITELY_FAILED = "definitely_failed"
    AMBIGUOUS = "ambiguous"


class SessionCloseDisposition(StrEnum):
    COMPLETE = "complete"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SessionCloseFailureCategory(StrEnum):
    LOCAL_RUNTIME = "local_runtime"
    PROTOCOL = "protocol"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    UNKNOWN = "unknown"


class StateRelation(StrEnum):
    BEFORE = "before"
    POST = "post"
    ALLOWED_INTERMEDIATE = "allowed_intermediate"
    OTHER = "other"
    UNKNOWN = "unknown"


class RemoteMarkerPhase(StrEnum):
    ACQUIRED = "acquired"
    PREPARING = "preparing"
    PREPARED = "prepared"
    MUTATING = "mutating"
    VERIFYING = "verifying"
    EFFECT = "effect"
    ROLLING_BACK = "rolling_back"
    TERMINAL_RELEASE_PENDING = "terminal_release_pending"
    QUARANTINE_PENDING = "quarantine_pending"


class AttemptPhase(StrEnum):
    PRECONDITION_RECHECK = "precondition_recheck"
    MUTATION = "mutation"
    VERIFICATION = "verification"
    EFFECT = "effect"
    POST_EFFECT_VERIFICATION = "post_effect_verification"
    ROLLBACK = "rollback"
    ROLLBACK_VERIFICATION = "rollback_verification"
    RECOVERY = "recovery"
    CLEANUP = "cleanup"


class FailurePhase(StrEnum):
    PLANNING = "planning"
    PRECONDITION = "precondition"
    MUTATION = "mutation"
    VERIFICATION = "verification"
    EFFECT = "effect"
    POST_EFFECT_VERIFICATION = "post_effect_verification"
    ROLLBACK = "rollback"
    RECOVERY = "recovery"


class RetryClassification(StrEnum):
    NEVER = "never"
    REPLAN = "replan"
    SAME_RUN = "same_run"
    OPERATOR_ACTION = "operator_action"


class StopScope(StrEnum):
    RESOURCE = "resource"
    BARRIER = "barrier"
    RUN = "run"


class MutationOutcome(StrEnum):
    NOT_REQUIRED = "not_required"
    BLOCKED = "blocked"
    PENDING = "pending"
    COMPLETED = "completed"
    DEFINITELY_NOT_APPLIED = "definitely_not_applied"
    AMBIGUOUS = "ambiguous"


class VerificationOutcome(StrEnum):
    NOT_STARTED = "not_started"
    FRESH_MATCH = "fresh_match"
    MATCHED = "matched"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class RollbackOutcome(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    RESTORED_AND_VERIFIED = "restored_and_verified"
    RESTORED_OR_UNCHANGED = "restored_or_unchanged"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    BLOCKED = "blocked"


class PostEffectVerification(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    NOT_REACHED = "not_reached"
    PENDING = "pending"
    MATCHED = "matched"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class ExpectedDisconnectPolicy(StrEnum):
    NEVER = "never"
    ALLOWED = "allowed"
    REQUIRED = "required"


class EffectPhase(StrEnum):
    CONTRIBUTOR_PREVERIFICATION = "contributor_preverification"
    INTENT_DURABLE = "intent_durable"
    EXECUTING = "executing"
    READINESS_PENDING = "readiness_pending"
    POST_EFFECT_OBSERVATION = "post_effect_observation"
    COMPLETE = "complete"
    RECOVERY_REQUIRED = "recovery_required"


class ExecutionEvidenceKind(StrEnum):
    MANAGED_FILE_OBSERVATION = "ManagedFileObservation"
    RESOURCE_PREPARATION_COMPLETED = "ResourcePreparationCompleted"
    RESOURCE_PRIMITIVE_INTENT = "ResourcePrimitiveIntent"
    REMOTE_MARKER_CHECKPOINT = "RemoteMarkerCheckpoint"
    RESOURCE_PRIMITIVE_OUTCOME = "ResourcePrimitiveOutcome"
    RESOURCE_EXECUTION_RESULT = "ResourceExecutionResult"
    RESOURCE_VERIFICATION_RESULT = "ResourceVerificationResult"
    RESOURCE_ROLLBACK_RESULT = "ResourceRollbackResult"
    RESOURCE_SKIP_RESULT = "ResourceSkipResult"
    RECOVERY_VERIFICATION_RESULT = "RecoveryVerificationResult"
    RESOURCE_CLEANUP_RECEIPT = "ResourceCleanupReceipt"
    EFFECT_INTENT = "EffectIntent"
    EFFECT_READINESS_OBSERVATION = "EffectReadinessObservation"
    EFFECT_OUTCOME = "EffectOutcome"
    AUTHORITY_EVIDENCE = "AuthorityEvidence"
    RUN_ABANDONMENT_APPROVAL = "RunAbandonmentApproval"


class FinalConvergence(StrEnum):
    PENDING = "pending"
    BLOCKED = "blocked"
    CONVERGED = "converged"
    FAILED_KNOWN = "failed_known"
    ROLLED_BACK_VERIFIED = "rolled_back_verified"
    SKIPPED_DEPENDENCY = "skipped_dependency"
    SKIPPED_RUN_STOPPED = "skipped_run_stopped"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class WorkspaceId:
    value: str


@dataclass(frozen=True, slots=True)
class DeviceLease:
    device_id: DeviceId
    token: str


@dataclass(frozen=True, slots=True)
class RevisionLease:
    run_id: RunId
    workspace_id: WorkspaceId
    token: str


@dataclass(frozen=True, slots=True)
class ActiveDeviceRun:
    run_id: RunId
    workspace_id: WorkspaceId
    revision: int
    revision_digest: str
    status: RunStatus
    authority_phase: AuthorityPhase


@dataclass(frozen=True, slots=True)
class StoredRevision:
    revision: int
    digest: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class SessionCloseIntent:
    record_id: str
    session_id: str
    observed_at: str
    disposition: SessionCloseDisposition
    failure_category: SessionCloseFailureCategory | None = None
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class SessionCloseRecord:
    record_id: str
    session_id: str
    run_id: str
    workspace_id: str
    device_id: str
    terminal_revision: int
    terminal_digest: str
    observed_head_revision: int
    observed_head_digest: str
    authority_state: str
    seal_digest: str | None
    observed_at: str
    disposition: SessionCloseDisposition
    failure_category: SessionCloseFailureCategory | None
    failure_code: str | None
    digest: str
    canonical_bytes: bytes


@dataclass(frozen=True, slots=True)
class SessionCloseInspection:
    disposition: SessionCloseDisposition
    record: SessionCloseRecord | None
    issue_code: str | None


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    digest: str
    kind: str
    codec: str


@dataclass(frozen=True, slots=True)
class LoadedAttachment:
    reference: AttachmentRef
    payload: bytes


@dataclass(frozen=True, slots=True)
class VerifiedRunChain:
    revisions: tuple[StoredRevision, ...]
    head: StoredRevision
    terminal: bool


@dataclass(frozen=True, slots=True)
class AppendIntent:
    next_status: RunStatus
    terminal: bool
    device_index: DeviceIndexIntent
    authority_phase: AuthorityPhase | None = None


@dataclass(frozen=True, slots=True)
class SealIntent:
    terminal_revision: int
    ownership_released_or_quarantined: bool


@dataclass(frozen=True, slots=True)
class NormalizedResourceState:
    presence: Presence
    entry_kind: str | None
    content_digest: str | None
    managed_mode: int | None


@dataclass(frozen=True, slots=True)
class MutationReceipt:
    operation_id: str
    disposition: MutationDisposition


@dataclass(frozen=True, slots=True)
class MutationTrace:
    receipts: tuple[MutationReceipt, ...]


@dataclass(frozen=True, slots=True)
class RemoteOwnershipIdentity:
    device_id: DeviceId
    run_id: RunId
    workspace_id: WorkspaceId
    plan_id: str
    plan_full_digest: str
    binding_digest: str
    boot_id: str


@dataclass(frozen=True, slots=True)
class RemoteOwnershipSnapshot:
    presence: Presence
    generation: int | None
    marker_digest: str | None
    token_digest: str | None
    identity: RemoteOwnershipIdentity | None
    phase: RemoteMarkerPhase | None
    manifest_digest: str | None


@dataclass(frozen=True, slots=True)
class RemoteOwnership:
    identity: RemoteOwnershipIdentity
    token_digest: str
    generation: int
    phase: RemoteMarkerPhase
    marker_digest: str


@dataclass(frozen=True, slots=True)
class RemoteQuarantine:
    identity: RemoteOwnershipIdentity
    incident_receipt_digest: str
    marker_digest: str


@dataclass(frozen=True, slots=True)
class MarkerCheckpoint:
    identity: RemoteOwnershipIdentity
    token_digest: str
    generation: int
    phase: RemoteMarkerPhase
    marker_digest: str


@dataclass(frozen=True, slots=True)
class ResourceMutationIntent:
    operation_id: str
    primitive: PrimitiveKind
    resource_id: str
    change_id: str
    preparation_manifest_digest: str
    expected_before: NormalizedResourceState
    expected_after: NormalizedResourceState
    allowed_intermediates: tuple[NormalizedResourceState, ...]
    content_attachment_digest: str | None
    marker: MarkerCheckpoint
    attempt: int


@dataclass(frozen=True, slots=True)
class EffectMutationIntent:
    operation_id: str
    primitive: PrimitiveKind
    effect_code: str
    descriptor_digest: str
    approval_evidence_ref: str
    readiness_evidence_ref: str
    marker: MarkerCheckpoint
    attempt: int


@dataclass(frozen=True, slots=True)
class CleanupMutationIntent:
    operation_id: str
    primitive: PrimitiveKind
    manifest_object_ref: str
    terminal_or_seal_evidence_ref: str
    marker: MarkerCheckpoint
    attempt: int


MutationIntent = ResourceMutationIntent | EffectMutationIntent | CleanupMutationIntent


@dataclass(frozen=True, slots=True)
class MutationOutcomeRecord:
    intent_operation_id: str
    trace: MutationTrace
    observed_state_digest: str | None


@dataclass(frozen=True, slots=True)
class RecoveryFact:
    code: str
    state: FactState
    evidence_digest: str | None


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    run_id: RunId
    workspace_id: WorkspaceId
    stable_snapshot: bool
    remote_ownership_presence: Presence
    remote_generation: int | None
    remote_phase: RemoteMarkerPhase | None
    remote_marker_digest: str | None
    remote_integrity_valid: bool | None
    remote_quarantine_presence: Presence
    binding_matches: bool | None
    chain_valid: bool
    chain_complete: bool
    attachments_valid: bool
    codecs_valid: bool
    preparation_complete: bool
    rollback_declared: bool
    rollback_approved: bool
    live_helper: bool | None
    forward_work_unperformed: bool
    current_relation: StateRelation
    before_state: NormalizedResourceState | None
    post_state: NormalizedResourceState | None
    allowed_intermediate_states: tuple[NormalizedResourceState, ...]
    effect_disposition: EffectDisposition
    effect_readiness_positive: bool | None
    post_effect_evidence_complete: bool
    rollback_complete_and_verified: bool
    restore_effect_preplanned: bool
    restore_effect_approved: bool
    canonical_status: RunStatus
    terminal_revision_durable: bool
    cleanup_complete: bool
    ownership_release_or_quarantine_durable: bool
    facts: tuple[RecoveryFact, ...]


@dataclass(frozen=True, slots=True)
class AllowedRecoveryAction:
    code: RecoveryActionCode
    finalize_mode: FinalizeMode | None
    allowed: bool
    reason_code: str
    requires_approval: bool
    requires_reason: bool


@dataclass(frozen=True, slots=True)
class EffectCode:
    value: str


@dataclass(frozen=True, slots=True)
class ReadinessCondition:
    code: str
    positive_observation_kind: str


@dataclass(frozen=True, slots=True)
class EffectHandlerDescriptor:
    code: EffectCode
    required_capabilities: frozenset[str]
    expected_disconnect: ExpectedDisconnectPolicy
    readiness: ReadinessCondition
    post_effect_resource_ids: tuple[str, ...]
    restore_effect_code: EffectCode | None


@dataclass(frozen=True, slots=True)
class EvidenceObserver:
    code: str
    version: int


@dataclass(frozen=True, slots=True)
class EvidenceAttachment:
    digest: str
    kind: str
    codec: str


@dataclass(frozen=True, slots=True)
class ExecutionEvidenceBindings:
    device_id: str
    run_id: str
    workspace_id: str
    plan_id: str
    plan_full_digest: str
    binding_digest: str
    resource_id: str | None
    change_id: str | None


@dataclass(frozen=True, slots=True)
class ExecutionEvidenceRecord:
    evidence_id: str
    observed_at: str
    observer: EvidenceObserver
    subject_kind: str
    subject_id: str
    resource_type: str | None
    bindings: ExecutionEvidenceBindings
    state_addresses: tuple[str, ...]
    attachment_refs: tuple[EvidenceAttachment, ...]
    attempt: int | None
    kind: ExecutionEvidenceKind
    schema_version: int
    payload: tuple[tuple[str, object], ...]
    raw_attachment_digest: str | None


class ExecutionResourceRegistry(Protocol):
    @property
    def type_codes(self) -> frozenset[str]: ...


EXECUTION_EVIDENCE_SCHEMA_VERSION = 1
_EVIDENCE_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_RESOURCE_TYPE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_WORKSPACE_ID = re.compile(r"^workspace:[a-zA-Z0-9_-]{8,128}$")
_SESSION_CLOSE_FIELDS = {
    "authority_state",
    "current_digest",
    "device_id",
    "disposition",
    "failure",
    "kind",
    "observed_at",
    "observed_head_digest",
    "observed_head_revision",
    "producer",
    "record_id",
    "run_id",
    "schema_version",
    "seal_digest",
    "session_id",
    "terminal_digest",
    "terminal_revision",
    "workspace_id",
}


def build_session_close_record(value: dict[str, object]) -> SessionCloseRecord:
    candidate = dict(value)
    candidate["current_digest"] = ""
    without_digest = {
        key: item for key, item in candidate.items() if key != "current_digest"
    }
    candidate["current_digest"] = _execution_sha256(
        canonical_document_bytes(without_digest)
    )
    return decode_session_close_record(canonical_document_bytes(candidate))


def decode_session_close_record(content: bytes) -> SessionCloseRecord:
    value = decode_json_object(content)
    if set(value) != _SESSION_CLOSE_FIELDS:
        raise ValueError("unknown or missing session close fields")
    if canonical_document_bytes(value) != content:
        raise ValueError("session close bytes are not canonical")
    if (
        value["kind"] != "CoreElecReconcilerSessionClose"
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["producer"] != {"name": "coreelec-reconciler", "version": "0.1.0"}
    ):
        raise ValueError("unsupported session close record")
    record_id = require_uuid7(value["record_id"], "session close record_id")
    session_id = _session_close_code(value["session_id"], "session_id")
    run_id = require_uuid7(value["run_id"], "session close run_id")
    workspace_id = _evidence_workspace(value["workspace_id"])
    device_id = require_logical_id(value["device_id"], "session close device_id")
    terminal_revision = _session_close_positive_int(
        value["terminal_revision"], "terminal_revision"
    )
    terminal_digest = require_sha256(
        value["terminal_digest"], "session close terminal_digest"
    )
    observed_head_revision = _session_close_positive_int(
        value["observed_head_revision"], "observed_head_revision"
    )
    observed_head_digest = require_sha256(
        value["observed_head_digest"], "session close observed_head_digest"
    )
    if observed_head_revision < terminal_revision:
        raise ValueError("session close head precedes terminal truth")
    authority_state = _session_close_code(value["authority_state"], "authority_state")
    if authority_state not in {
        "acquisition_pending",
        "owned",
        "quarantined",
        "released",
        "unknown",
    }:
        raise ValueError("unknown session close authority state")
    seal_digest_value = value["seal_digest"]
    seal_digest = (
        None
        if seal_digest_value is None
        else require_sha256(seal_digest_value, "session close seal_digest")
    )
    observed_at = require_rfc3339_utc(value["observed_at"], "observed_at")
    try:
        disposition = SessionCloseDisposition(
            _session_close_string(value["disposition"], "disposition")
        )
    except ValueError as error:
        raise ValueError("unknown session close disposition") from error
    failure_value = value["failure"]
    failure_category: SessionCloseFailureCategory | None = None
    failure_code: str | None = None
    if disposition is SessionCloseDisposition.COMPLETE:
        if failure_value is not None:
            raise ValueError("complete session close cannot contain failure")
    else:
        if not isinstance(failure_value, dict) or set(failure_value) != {
            "category",
            "code",
        }:
            raise ValueError("failed or unknown session close requires failure")
        try:
            failure_category = SessionCloseFailureCategory(
                _session_close_string(failure_value["category"], "failure category")
            )
        except ValueError as error:
            raise ValueError("unknown session close failure category") from error
        failure_code = _session_close_code(failure_value["code"], "failure code")
    digest = require_sha256(value["current_digest"], "session close current_digest")
    without_digest = {
        key: item for key, item in value.items() if key != "current_digest"
    }
    if _execution_sha256(canonical_document_bytes(without_digest)) != digest:
        raise ValueError("session close digest mismatch")
    return SessionCloseRecord(
        record_id=record_id,
        session_id=session_id,
        run_id=run_id,
        workspace_id=workspace_id,
        device_id=device_id,
        terminal_revision=terminal_revision,
        terminal_digest=terminal_digest,
        observed_head_revision=observed_head_revision,
        observed_head_digest=observed_head_digest,
        authority_state=authority_state,
        seal_digest=seal_digest,
        observed_at=observed_at,
        disposition=disposition,
        failure_category=failure_category,
        failure_code=failure_code,
        digest=digest,
        canonical_bytes=content,
    )


def _session_close_string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"session close {label} must be a string")
    return value


def _session_close_code(value: object, label: str) -> str:
    code = _session_close_string(value, label)
    if _EVIDENCE_CODE.fullmatch(code) is None:
        raise ValueError(f"invalid session close {label}")
    return code


def _session_close_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"invalid session close {label}")
    return value


def _execution_sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


EXECUTION_RESOURCE_EVIDENCE_KINDS = frozenset(
    {
        ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION,
        ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED,
        ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
        ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME,
        ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT,
        ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT,
        ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT,
        ExecutionEvidenceKind.RESOURCE_SKIP_RESULT,
        ExecutionEvidenceKind.RECOVERY_VERIFICATION_RESULT,
        ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT,
    }
)
EXECUTION_EVIDENCE_OBSERVERS = MappingProxyType(
    {
        ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION: "managed-file-observer",
        ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED: "managed-file-preparer",
        ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT: "managed-file-executor",
        ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT: "remote-run-ownership",
        ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME: "managed-file-executor",
        ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT: "managed-file-executor",
        ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT: "managed-file-verifier",
        ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT: "managed-file-verifier",
        ExecutionEvidenceKind.RESOURCE_SKIP_RESULT: "execution-controller",
        ExecutionEvidenceKind.RECOVERY_VERIFICATION_RESULT: "recovery-controller",
        ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT: "managed-file-executor",
        ExecutionEvidenceKind.EFFECT_INTENT: "effect-executor",
        ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION: "effect-readiness-observer",
        ExecutionEvidenceKind.EFFECT_OUTCOME: "effect-executor",
        ExecutionEvidenceKind.AUTHORITY_EVIDENCE: "remote-run-ownership",
        ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL: "recovery-controller",
    }
)
EXECUTION_EVIDENCE_PAYLOAD_FIELDS = MappingProxyType(
    {
        kind: frozenset(fields)
        for kind, fields in {
            ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION: {
                "content_digest",
                "entry_kind",
                "managed_mode",
                "normalized_state_digest",
                "presence",
                "relation",
            },
            ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED: {
                "allowed_intermediate_state_digests",
                "before_state_attachment_digest",
                "cleanup_object_refs",
                "desired_state_digest",
                "manifest_digest",
                "preparation_manifest_attachment_digest",
                "rollback_capable",
            },
            ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT: {
                "allowed_intermediate_state_digests",
                "content_attachment_digest",
                "expected_after_digest",
                "expected_before_digest",
                "manifest_object_ref",
                "marker_digest",
                "marker_generation",
                "marker_phase",
                "operation_id",
                "preparation_manifest_digest",
                "primitive",
                "terminal_revision_digest",
                "token_digest",
            },
            ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT: {
                "generation",
                "manifest_digest",
                "marker_digest",
                "operation_id",
                "phase",
                "token_digest",
            },
            ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME: {
                "disposition",
                "observation_evidence_ref",
                "observed_state_digest",
                "operation_id",
                "receipt_sequence",
            },
            ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT: {
                "intent_evidence_ref",
                "mutation_outcome",
                "outcome_evidence_ref",
            },
            ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT: {
                "observation_evidence_ref",
                "outcome",
                "post_effect",
                "relation",
            },
            ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT: {
                "observation_evidence_ref",
                "original_failure_code",
                "outcome",
                "relation",
            },
            ExecutionEvidenceKind.RESOURCE_SKIP_RESULT: {
                "final_convergence",
                "reason_code",
                "stop_scope",
            },
            ExecutionEvidenceKind.RECOVERY_VERIFICATION_RESULT: {
                "action",
                "observation_evidence_ref",
                "outcome",
                "relation",
            },
            ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT: {
                "disposition",
                "leftover",
                "manifest_object_ref",
                "operation_id",
                "terminal_revision_digest",
            },
            ExecutionEvidenceKind.EFFECT_INTENT: {
                "affected_resources",
                "approval_evidence_ref",
                "descriptor_digest",
                "effect_code",
                "marker_digest",
                "marker_generation",
                "marker_phase",
                "operation_id",
                "readiness_evidence_ref",
                "token_digest",
            },
            ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION: {
                "effect_code",
                "positive",
                "readiness_code",
            },
            ExecutionEvidenceKind.EFFECT_OUTCOME: {
                "disposition",
                "effect_code",
                "operation_id",
                "post_effect_evidence_refs",
                "readiness_evidence_ref",
            },
            ExecutionEvidenceKind.AUTHORITY_EVIDENCE: {
                "generation",
                "manifest_digest",
                "marker_digest",
                "ownership_state",
                "phase",
                "quarantine_receipt_digest",
                "token_digest",
            },
            ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL: {
                "actor",
                "approved_at",
                "mechanism",
                "reason",
            },
        }.items()
    }
)


def build_execution_evidence(
    *,
    evidence_id: str,
    observed_at: str,
    observer: EvidenceObserver,
    subject_kind: str,
    subject_id: str,
    resource_type: str | None,
    bindings: ExecutionEvidenceBindings,
    state_addresses: tuple[str, ...],
    attachment_refs: tuple[EvidenceAttachment, ...],
    attempt: int | None,
    kind: ExecutionEvidenceKind,
    payload: dict[str, object],
    resource_registry: ExecutionResourceRegistry,
    raw_attachment_digest: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "attachment_refs": [
            {"codec": item.codec, "digest": item.digest, "kind": item.kind}
            for item in attachment_refs
        ],
        "attempt": attempt,
        "bindings": {
            "binding_digest": bindings.binding_digest,
            "change_id": bindings.change_id,
            "device_id": bindings.device_id,
            "plan_full_digest": bindings.plan_full_digest,
            "plan_id": bindings.plan_id,
            "resource_id": bindings.resource_id,
            "run_id": bindings.run_id,
            "workspace_id": bindings.workspace_id,
        },
        "evidence_id": evidence_id,
        "observed_at": observed_at,
        "observer": {"code": observer.code, "version": observer.version},
        "payload": payload,
        "payload_kind": kind.value,
        "payload_schema_version": EXECUTION_EVIDENCE_SCHEMA_VERSION,
        "raw_attachment_digest": raw_attachment_digest,
        "resource_type": resource_type,
        "state_addresses": list(state_addresses),
        "subject": {"id": subject_id, "kind": subject_kind},
    }
    decode_execution_evidence(
        value,
        resource_registry=resource_registry,
    )
    return value


def decode_execution_evidence(
    value: object,
    *,
    resource_registry: ExecutionResourceRegistry,
) -> ExecutionEvidenceRecord:
    if not isinstance(value, dict) or set(value) != {
        "attachment_refs",
        "attempt",
        "bindings",
        "evidence_id",
        "observed_at",
        "observer",
        "payload",
        "payload_kind",
        "payload_schema_version",
        "raw_attachment_digest",
        "resource_type",
        "state_addresses",
        "subject",
    }:
        raise ValueError("unknown or missing execution evidence fields")
    try:
        kind = ExecutionEvidenceKind(_evidence_string(value, "payload_kind"))
    except ValueError as error:
        raise ValueError("unknown execution evidence kind") from error
    if (
        type(value["payload_schema_version"]) is not int
        or value["payload_schema_version"] != EXECUTION_EVIDENCE_SCHEMA_VERSION
    ):
        raise ValueError("unsupported execution evidence schema version")
    payload = value["payload"]
    if (
        not isinstance(payload, dict)
        or set(payload) != EXECUTION_EVIDENCE_PAYLOAD_FIELDS[kind]
    ):
        raise ValueError("unknown or missing execution evidence payload fields")
    observer_value = _evidence_mapping(value, "observer", {"code", "version"})
    observer = EvidenceObserver(
        _evidence_string(observer_value, "code"),
        _evidence_positive_int(observer_value, "version"),
    )
    if observer.code != EXECUTION_EVIDENCE_OBSERVERS[kind] or observer.version != 1:
        raise ValueError("unsupported execution evidence observer")
    subject = _evidence_mapping(value, "subject", {"id", "kind"})
    bindings_value = _evidence_mapping(
        value,
        "bindings",
        {
            "binding_digest",
            "change_id",
            "device_id",
            "plan_full_digest",
            "plan_id",
            "resource_id",
            "run_id",
            "workspace_id",
        },
    )
    bindings = ExecutionEvidenceBindings(
        require_logical_id(bindings_value["device_id"], "evidence Device ID"),
        require_uuid7(bindings_value["run_id"], "evidence Run ID"),
        _evidence_workspace(bindings_value["workspace_id"]),
        require_uuid7(bindings_value["plan_id"], "evidence Plan ID"),
        require_sha256(bindings_value["plan_full_digest"], "evidence Plan digest"),
        require_sha256(bindings_value["binding_digest"], "evidence binding digest"),
        _optional_evidence_code(bindings_value["resource_id"], "resource ID"),
        _optional_evidence_code(bindings_value["change_id"], "change ID"),
    )
    resource_type = value["resource_type"]
    state_addresses = _evidence_string_tuple(value["state_addresses"], "state address")
    attempt = value["attempt"]
    resource_bound = kind in EXECUTION_RESOURCE_EVIDENCE_KINDS or (
        kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT
        and resource_type is not None
    )
    if resource_bound:
        if (
            not isinstance(resource_type, str)
            or resource_type not in resource_registry.type_codes
        ):
            raise ValueError("unknown execution evidence Resource Type")
        if bindings.resource_id is None or bindings.change_id is None:
            raise ValueError("Resource evidence bindings are incomplete")
        if subject != {"id": bindings.resource_id, "kind": "resource"}:
            raise ValueError("Resource evidence subject does not match bindings")
        if (
            not state_addresses
            or tuple(sorted(set(state_addresses))) != state_addresses
        ):
            raise ValueError("Resource evidence State Addresses are invalid")
        if any(
            not item.startswith("special://")
            or any(token in item for token in ("\n", "\r", "\\", ".."))
            for item in state_addresses
        ):
            raise ValueError("Resource evidence State Address is not logical")
        if type(attempt) is not int or attempt != 1:
            raise ValueError("execution evidence attempt must be 1")
    else:
        if resource_type is not None or bindings.resource_id is not None:
            raise ValueError("non-Resource evidence cannot claim a Resource Type")
        if bindings.change_id is not None or state_addresses:
            raise ValueError("non-Resource evidence has Resource-only bindings")
        operation_evidence = kind in {
            ExecutionEvidenceKind.EFFECT_INTENT,
            ExecutionEvidenceKind.EFFECT_OUTCOME,
            ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
        }
        if operation_evidence and (type(attempt) is not int or attempt != 1):
            raise ValueError("Effect operation evidence attempt must be 1")
        if not operation_evidence and attempt is not None:
            raise ValueError("non-operation evidence attempt must be null")
        expected_subject = {
            ExecutionEvidenceKind.EFFECT_INTENT: ("effect", None),
            ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION: ("effect", None),
            ExecutionEvidenceKind.EFFECT_OUTCOME: ("effect", None),
            ExecutionEvidenceKind.AUTHORITY_EVIDENCE: (
                "device",
                bindings.device_id,
            ),
            ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL: (
                "run",
                bindings.run_id,
            ),
            ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT: ("effect", None),
        }[kind]
        if subject.get("kind") != expected_subject[0] or (
            expected_subject[1] is not None and subject.get("id") != expected_subject[1]
        ):
            raise ValueError("execution evidence subject does not match kind")
    attachments: list[EvidenceAttachment] = []
    raw_attachments = value["attachment_refs"]
    if not isinstance(raw_attachments, list):
        raise ValueError("execution evidence attachment_refs must be an array")
    for raw in raw_attachments:
        if not isinstance(raw, dict) or set(raw) != {"codec", "digest", "kind"}:
            raise ValueError("execution evidence attachment reference is invalid")
        attachments.append(
            EvidenceAttachment(
                require_sha256(raw["digest"], "attachment digest"),
                _evidence_code(raw["kind"], "attachment kind"),
                _evidence_code(raw["codec"], "attachment codec"),
            )
        )
    if len({item.digest for item in attachments}) != len(attachments):
        raise ValueError("execution evidence attachment references are duplicated")
    referenced_attachments = {item.digest for item in attachments}
    for key, item in payload.items():
        if (
            key.endswith("_attachment_digest")
            and item is not None
            and item not in referenced_attachments
        ):
            raise ValueError("payload attachment digest is not declared")
    raw_attachment = value["raw_attachment_digest"]
    if raw_attachment is not None:
        require_sha256(raw_attachment, "raw attachment digest")
    parse_rfc3339_utc(value["observed_at"], "evidence observed_at")
    _validate_evidence_payload(kind, payload, resource_registry.type_codes)
    if (
        kind
        in {
            ExecutionEvidenceKind.EFFECT_INTENT,
            ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION,
            ExecutionEvidenceKind.EFFECT_OUTCOME,
        }
        and subject["id"] != payload["effect_code"]
    ):
        raise ValueError("Effect evidence subject does not match payload")
    _reject_unsafe_evidence_content(payload)
    return ExecutionEvidenceRecord(
        _evidence_code(value["evidence_id"], "evidence ID"),
        _evidence_string(value, "observed_at"),
        observer,
        _evidence_code(subject["kind"], "subject kind"),
        _evidence_code(subject["id"], "subject ID"),
        resource_type if isinstance(resource_type, str) else None,
        bindings,
        state_addresses,
        tuple(attachments),
        attempt if isinstance(attempt, int) else None,
        kind,
        EXECUTION_EVIDENCE_SCHEMA_VERSION,
        tuple(sorted(payload.items())),
        raw_attachment if isinstance(raw_attachment, str) else None,
    )


def validate_execution_evidence_sequence(
    values: tuple[object, ...],
    *,
    status: RunStatus,
    resource_registry: ExecutionResourceRegistry,
) -> tuple[ExecutionEvidenceRecord, ...]:
    records = tuple(
        decode_execution_evidence(
            value,
            resource_registry=resource_registry,
        )
        for value in values
    )
    identifiers: set[str] = set()
    records_by_id: dict[str, ExecutionEvidenceRecord] = {}
    last_observed_at: str | None = None
    resource_kinds: dict[tuple[str | None, str | None], set[ExecutionEvidenceKind]] = {}
    operations: dict[
        str,
        tuple[
            tuple[object, ...],
            dict[ExecutionEvidenceKind, ExecutionEvidenceRecord],
        ],
    ] = {}
    result_signatures: set[tuple[object, ...]] = set()
    previous_record: ExecutionEvidenceRecord | None = None
    for record in records:
        if record.evidence_id in identifiers:
            raise ValueError("execution evidence IDs are duplicated")
        key = (record.bindings.resource_id, record.bindings.change_id)
        if last_observed_at is not None and record.observed_at < last_observed_at:
            raise ValueError("execution evidence records are out of order")
        last_observed_at = record.observed_at
        seen_resource_kinds = resource_kinds.setdefault(key, set())
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED
            and ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION
            not in seen_resource_kinds
        ):
            raise ValueError("Resource preparation precedes fresh Observation")
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT
            and ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED
            not in seen_resource_kinds
        ):
            raise ValueError("primitive intent precedes Resource preparation")
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT
            and ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT
            not in seen_resource_kinds
        ):
            raise ValueError("Resource Verification precedes execution result")
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT
            and ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT
            not in seen_resource_kinds
        ):
            raise ValueError("Resource rollback precedes execution result")
        mutation_kinds = {
            ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
            ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
            ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME,
            ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT,
            ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT,
            ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT,
        }
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_SKIP_RESULT
            and seen_resource_kinds & mutation_kinds
        ) or (
            record.kind in mutation_kinds
            and ExecutionEvidenceKind.RESOURCE_SKIP_RESULT in seen_resource_kinds
        ):
            raise ValueError("Resource skip conflicts with execution evidence")
        payload = dict(record.payload)
        operation_id = payload.get("operation_id")
        if isinstance(operation_id, str):
            operation_binding = (
                record.subject_kind,
                record.subject_id,
                record.bindings,
            )
            operation = operations.setdefault(operation_id, (operation_binding, {}))
            if operation[0] != operation_binding:
                raise ValueError("execution operation bindings changed")
            seen = operation[1]
            if record.kind in seen:
                raise ValueError("execution operation evidence is duplicated")
            if record.kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT and not {
                ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
                ExecutionEvidenceKind.EFFECT_INTENT,
            } & set(seen):
                raise ValueError("marker checkpoint precedes operation intent")
            if record.kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT and (
                previous_record is None
                or previous_record.kind
                not in {
                    ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
                    ExecutionEvidenceKind.EFFECT_INTENT,
                }
                or dict(previous_record.payload).get("operation_id") != operation_id
            ):
                raise ValueError("marker checkpoint is not immediate")
            if record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME and not {
                ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
                ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
            } <= set(seen):
                raise ValueError("primitive outcome lacks intent/checkpoint")
            if record.kind is ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT and (
                ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT not in seen
                or ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT not in seen
                or dict(seen[ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT].payload)[
                    "primitive"
                ]
                != PrimitiveKind.CLEANUP.value
            ):
                raise ValueError("cleanup receipt lacks intent/checkpoint")
            if record.kind is ExecutionEvidenceKind.EFFECT_OUTCOME and not {
                ExecutionEvidenceKind.EFFECT_INTENT,
                ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
            } <= set(seen):
                raise ValueError("Effect outcome lacks intent/checkpoint")
            if record.kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT:
                intent_record = seen.get(
                    ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT
                ) or seen.get(ExecutionEvidenceKind.EFFECT_INTENT)
                assert intent_record is not None
                intent = dict(intent_record.payload)
                if (
                    payload["marker_digest"] != intent["marker_digest"]
                    or payload["generation"] != intent["marker_generation"]
                    or payload["phase"] != intent["marker_phase"]
                    or payload["token_digest"] != intent["token_digest"]
                ):
                    raise ValueError("marker checkpoint does not match intent")
            seen[record.kind] = record
        signature = _evidence_result_signature(record)
        if signature is not None:
            if signature in result_signatures:
                raise ValueError("execution result evidence is duplicated")
            result_signatures.add(signature)
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT
            and status not in TERMINAL_RUN_STATUSES
        ):
            raise ValueError("cleanup receipt precedes terminal Run truth")
        if (
            record.kind is ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL
            and status
            not in {RunStatus.INTERRUPTED, RunStatus.FAILED_RECOVERY_REQUIRED}
        ):
            raise ValueError("abandonment approval is invalid for Run status")
        _validate_evidence_references(
            record,
            records_by_id,
            resource_registry.type_codes,
        )
        identifiers.add(record.evidence_id)
        records_by_id[record.evidence_id] = record
        seen_resource_kinds.add(record.kind)
        previous_record = record
    return records


def execution_run_identity(value: dict[str, object]) -> dict[str, object]:
    """Return the immutable identity projection shared by codecs and storage."""
    reference = value.get("plan_reference")
    authority = value.get("authority")
    recovery = value.get("recovery")
    if (
        not isinstance(reference, dict)
        or not isinstance(authority, dict)
        or not isinstance(recovery, dict)
    ):
        raise ValueError("Run immutable identity bindings are malformed")
    return {
        "binding_digest": authority.get("binding_digest"),
        "boot_id": authority.get("boot_id"),
        "created_at": value.get("started_at"),
        "device_id": value.get("device_id"),
        "kind": value.get("kind"),
        "originating_planning_run_id": value.get("originating_planning_run_id"),
        "ownership_token_digest": authority.get("ownership_token_digest"),
        "plan_full_digest": reference.get("plan_full_digest"),
        "plan_id": reference.get("plan_id"),
        "producer": value.get("producer"),
        "run_id": value.get("run_id"),
        "schema_version": value.get("schema_version"),
        "workspace_id": recovery.get("workspace_id"),
    }


def evidence_proves_terminal_cleanup(
    value: dict[str, object],
    *,
    resource_registry: ExecutionResourceRegistry,
) -> bool:
    """Return whether canonical evidence proves cleanup and authority summaries."""
    try:
        status = RunStatus(_evidence_string(value, "status"))
        evidence = value.get("evidence")
        cleanup = value.get("cleanup")
        authority = value.get("authority")
        if (
            status not in TERMINAL_RUN_STATUSES
            or not isinstance(evidence, list)
            or not isinstance(cleanup, dict)
            or not isinstance(authority, dict)
        ):
            return False
        records = validate_execution_evidence_sequence(
            tuple(evidence),
            status=status,
            resource_registry=resource_registry,
        )
        required: set[tuple[str, str, str]] = set()
        intents: dict[str, ExecutionEvidenceRecord] = {}
        checkpoints: set[str] = set()
        receipts: dict[tuple[str, str, str], ExecutionEvidenceRecord] = {}
        latest_authority: ExecutionEvidenceRecord | None = None
        for record in records:
            payload = dict(record.payload)
            if record.kind is ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED:
                assert record.bindings.resource_id is not None
                assert record.bindings.change_id is not None
                for object_ref in _evidence_string_tuple(
                    payload["cleanup_object_refs"],
                    "cleanup object reference",
                ):
                    required.add(
                        (
                            record.bindings.resource_id,
                            record.bindings.change_id,
                            object_ref,
                        )
                    )
            elif (
                record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT
                and payload["primitive"] == PrimitiveKind.CLEANUP.value
            ):
                intents[str(payload["operation_id"])] = record
            elif record.kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT:
                checkpoints.add(str(payload["operation_id"]))
            elif record.kind is ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT:
                operation_id = str(payload["operation_id"])
                intent = intents.get(operation_id)
                if (
                    intent is None
                    or operation_id not in checkpoints
                    or intent.bindings.resource_id != record.bindings.resource_id
                    or intent.bindings.change_id != record.bindings.change_id
                    or dict(intent.payload)["manifest_object_ref"]
                    != payload["manifest_object_ref"]
                    or payload["disposition"]
                    not in {
                        MutationDisposition.APPLIED.value,
                        MutationDisposition.DEFINITELY_NOT_APPLIED.value,
                    }
                ):
                    return False
                assert record.bindings.resource_id is not None
                assert record.bindings.change_id is not None
                receipt_key = (
                    record.bindings.resource_id,
                    record.bindings.change_id,
                    str(payload["manifest_object_ref"]),
                )
                if receipt_key in receipts:
                    return False
                receipts[receipt_key] = record
            elif record.kind is ExecutionEvidenceKind.AUTHORITY_EVIDENCE:
                latest_authority = record
        leftovers = sum(
            dict(record.payload)["leftover"] is True for record in receipts.values()
        )
        if cleanup.get("leftover_count") != leftovers:
            return False
        if cleanup.get("state") == "complete" and (
            set(receipts) != required or leftovers != 0
        ):
            return False
        ownership = authority.get("ownership_state")
        if ownership == "released" and cleanup.get("state") != "complete":
            return False
        if latest_authority is not None:
            authority_payload = dict(latest_authority.payload)
            if (
                authority_payload["ownership_state"] != ownership
                or authority_payload["token_digest"]
                != authority.get("ownership_token_digest")
                or authority_payload["generation"] != authority.get("marker_generation")
                or authority_payload["marker_digest"] != authority.get("marker_digest")
                or authority_payload["phase"] != authority.get("marker_phase")
                or (
                    ownership == "quarantined"
                    and authority_payload["quarantine_receipt_digest"] is None
                )
            ):
                return False
        elif ownership in {"released", "quarantined"}:
            return False
        if ownership in {"released", "quarantined"}:
            assert latest_authority is not None
            if receipts and records.index(latest_authority) < max(
                records.index(receipt) for receipt in receipts.values()
            ):
                return False
        return True
    except AssertionError, KeyError, TypeError, ValueError:
        return False


def is_post_terminal_cleanup_successor(
    previous: dict[str, object],
    current: dict[str, object],
    *,
    resource_registry: ExecutionResourceRegistry,
) -> bool:
    """Return whether current only advances cleanup after immutable terminal truth."""
    try:
        status = RunStatus(_evidence_string(previous, "status"))
        if status not in TERMINAL_RUN_STATUSES or current.get("status") != status.value:
            return False
        if execution_run_identity(previous) != execution_run_identity(current):
            return False
        ignored = {
            "authority",
            "cleanup",
            "current_digest",
            "evidence",
            "previous_revision_digest",
            "revision",
        }
        if {key: value for key, value in previous.items() if key not in ignored} != {
            key: value for key, value in current.items() if key not in ignored
        }:
            return False
        previous_evidence = previous.get("evidence")
        current_evidence = current.get("evidence")
        if not isinstance(previous_evidence, list) or not isinstance(
            current_evidence, list
        ):
            return False
        if current_evidence[: len(previous_evidence)] != previous_evidence:
            return False
        additions = current_evidence[len(previous_evidence) :]
        if not additions:
            return False
        current_records = tuple(
            decode_execution_evidence(
                item,
                resource_registry=resource_registry,
            )
            for item in current_evidence
        )
        records = current_records[len(previous_evidence) :]
        cleanup_operations = {
            dict(item.payload)["operation_id"]
            for item in current_records
            if item.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT
            and dict(item.payload)["primitive"] == PrimitiveKind.CLEANUP.value
        }
        if any(
            not _is_cleanup_progress_record(item, cleanup_operations)
            for item in records
        ):
            return False
        terminal_digest = _terminal_evidence_digest(
            previous_evidence,
            _evidence_string(previous, "current_digest"),
            resource_registry,
        )
        if any(
            item.kind
            in {
                ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
                ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT,
            }
            and dict(item.payload)["terminal_revision_digest"] != terminal_digest
            for item in records
        ):
            return False
        return _cleanup_transition_valid(
            previous.get("authority"),
            current.get("authority"),
            previous.get("cleanup"),
            current.get("cleanup"),
        ) and evidence_proves_terminal_cleanup(
            current,
            resource_registry=resource_registry,
        )
    except KeyError, TypeError, ValueError:
        return False


def _terminal_evidence_digest(
    evidence: list[object],
    fallback: str,
    resource_registry: ExecutionResourceRegistry,
) -> str:
    for item in evidence:
        try:
            record = decode_execution_evidence(
                item,
                resource_registry=resource_registry,
            )
        except ValueError:
            continue
        if record.kind is ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT or (
            record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT
            and dict(record.payload).get("primitive") == PrimitiveKind.CLEANUP.value
        ):
            digest = dict(record.payload).get("terminal_revision_digest")
            if isinstance(digest, str):
                return digest
    return fallback


def _is_cleanup_progress_record(
    record: ExecutionEvidenceRecord,
    cleanup_operations: set[object],
) -> bool:
    payload = dict(record.payload)
    if record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT:
        return payload["primitive"] == PrimitiveKind.CLEANUP.value
    if record.kind in {
        ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
        ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT,
    }:
        return payload["operation_id"] in cleanup_operations
    if record.kind is ExecutionEvidenceKind.AUTHORITY_EVIDENCE:
        return payload["ownership_state"] in {"released", "quarantined"}
    return False


def _cleanup_transition_valid(
    previous_authority: object,
    current_authority: object,
    previous_cleanup: object,
    current_cleanup: object,
) -> bool:
    if not all(
        isinstance(item, dict)
        for item in (
            previous_authority,
            current_authority,
            previous_cleanup,
            current_cleanup,
        )
    ):
        return False
    assert isinstance(previous_authority, dict)
    assert isinstance(current_authority, dict)
    assert isinstance(previous_cleanup, dict)
    assert isinstance(current_cleanup, dict)
    mutable_authority = {
        "cleanup_state",
        "device_index_intent",
        "marker_digest",
        "marker_generation",
        "marker_phase",
        "ownership_state",
    }
    if {
        key: value
        for key, value in previous_authority.items()
        if key not in mutable_authority
    } != {
        key: value
        for key, value in current_authority.items()
        if key not in mutable_authority
    }:
        return False
    cleanup_order = {
        "not_started": 0,
        "pending": 1,
        "failed": 2,
        "unknown": 2,
        "complete": 3,
    }
    previous_state = previous_cleanup.get("state")
    current_state = current_cleanup.get("state")
    if (
        previous_state not in cleanup_order
        or current_state not in cleanup_order
        or cleanup_order[current_state] < cleanup_order[previous_state]
        or current_authority.get("cleanup_state") != current_state
    ):
        return False
    ownership = current_authority.get("ownership_state")
    index_intent = current_authority.get("device_index_intent")
    return not (
        index_intent == "remove_after_release_or_quarantine"
        and ownership not in {"released", "quarantined"}
    )


def _validate_evidence_payload(
    kind: ExecutionEvidenceKind,
    payload: dict[str, object],
    registered_resource_types: Collection[str],
) -> None:
    digest_fields = {
        key for key in payload if key.endswith("_digest") and payload[key] is not None
    }
    for key in digest_fields:
        require_sha256(payload[key], key)
    for key, item in payload.items():
        if key.endswith("_digests"):
            values = _evidence_string_tuple(item, key)
            if len(set(values)) != len(values):
                raise ValueError(f"{key} values are duplicated")
            for digest in values:
                require_sha256(digest, key)
    if kind is ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION:
        presence = payload["presence"]
        if presence not in {"present", "absent", "unknown"}:
            raise ValueError("unknown Observation presence")
        if payload["relation"] not in {
            "before",
            "post",
            "allowed_intermediate",
            "other",
            "unknown",
        }:
            raise ValueError("unknown Observation relation")
        mode = payload["managed_mode"]
        if mode is not None and (type(mode) is not int or not 0 <= mode <= 0o777):
            raise ValueError("invalid managed mode")
        entry_kind = payload["entry_kind"]
        content_digest = payload["content_digest"]
        if presence == "present" and (
            entry_kind != "regular" or content_digest is None or mode is None
        ):
            raise ValueError("present Observation is incomplete")
        if presence != "present" and any(
            item is not None for item in (entry_kind, content_digest, mode)
        ):
            raise ValueError("non-present Observation claims file state")
    elif kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT:
        try:
            primitive = PrimitiveKind(_evidence_string(payload, "primitive"))
        except ValueError as error:
            raise ValueError("unknown primitive kind") from error
        _evidence_code(payload["operation_id"], "operation ID")
        _evidence_positive_int(payload, "marker_generation")
        RemoteMarkerPhase(_evidence_string(payload, "marker_phase"))
        state_primitive = primitive in {
            PrimitiveKind.STAGE_WRITE,
            PrimitiveKind.CHMOD,
            PrimitiveKind.ATOMIC_REPLACE,
            PrimitiveKind.REMOVE,
            PrimitiveKind.RESTORE,
        }
        if state_primitive and (
            payload["expected_before_digest"] is None
            or payload["expected_after_digest"] is None
            or payload["terminal_revision_digest"] is not None
            or payload["manifest_object_ref"] is not None
        ):
            raise ValueError("state primitive intent bindings are incomplete")
        if primitive is PrimitiveKind.CLEANUP and (
            payload["terminal_revision_digest"] is None
            or payload["manifest_object_ref"] is None
            or payload["expected_before_digest"] is not None
            or payload["expected_after_digest"] is not None
            or payload["allowed_intermediate_state_digests"] != []
        ):
            raise ValueError("cleanup primitive intent bindings are incomplete")
        content_required = primitive in {
            PrimitiveKind.STAGE_WRITE,
            PrimitiveKind.ATOMIC_REPLACE,
            PrimitiveKind.RESTORE,
        }
        if content_required != (payload["content_attachment_digest"] is not None):
            raise ValueError("primitive content attachment is invalid")
        if primitive in {PrimitiveKind.EFFECT, PrimitiveKind.RESTORE_EFFECT}:
            raise ValueError("Effect primitives require typed Effect intent")
    elif kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT:
        _evidence_positive_int(payload, "generation")
        try:
            RemoteMarkerPhase(_evidence_string(payload, "phase"))
        except ValueError as error:
            raise ValueError("unknown remote marker phase") from error
        _evidence_code(payload["operation_id"], "operation ID")
    elif kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME:
        try:
            MutationDisposition(_evidence_string(payload, "disposition"))
        except ValueError as error:
            raise ValueError("unknown primitive disposition") from error
        _evidence_code(payload["operation_id"], "operation ID")
        sequence = payload["receipt_sequence"]
        if type(sequence) is not int or sequence < 1:
            raise ValueError("receipt sequence must be positive")
    elif kind is ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT:
        MutationOutcome(_evidence_string(payload, "mutation_outcome"))
    elif kind is ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT:
        VerificationOutcome(_evidence_string(payload, "outcome"))
        StateRelation(_evidence_string(payload, "relation"))
        if type(payload["post_effect"]) is not bool:
            raise ValueError("post_effect must be boolean")
    elif kind is ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT:
        RollbackOutcome(_evidence_string(payload, "outcome"))
        StateRelation(_evidence_string(payload, "relation"))
        _evidence_code(payload["original_failure_code"], "failure code")
    elif kind is ExecutionEvidenceKind.RESOURCE_SKIP_RESULT:
        FinalConvergence(_evidence_string(payload, "final_convergence"))
        StopScope(_evidence_string(payload, "stop_scope"))
        _evidence_code(payload["reason_code"], "skip reason")
    elif kind is ExecutionEvidenceKind.RECOVERY_VERIFICATION_RESULT:
        if payload["action"] not in {"resume_verification", "rollback"}:
            raise ValueError("unknown recovery Verification action")
        VerificationOutcome(_evidence_string(payload, "outcome"))
        StateRelation(_evidence_string(payload, "relation"))
    elif kind is ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT:
        MutationDisposition(_evidence_string(payload, "disposition"))
        _evidence_code(payload["operation_id"], "operation ID")
        _evidence_code(payload["manifest_object_ref"], "manifest object reference")
        if type(payload["leftover"]) is not bool:
            raise ValueError("cleanup leftover must be boolean")
    elif kind is ExecutionEvidenceKind.EFFECT_INTENT:
        _evidence_code(payload["effect_code"], "Effect code")
        _evidence_code(payload["operation_id"], "operation ID")
        _evidence_code(payload["approval_evidence_ref"], "approval evidence reference")
        _evidence_positive_int(payload, "marker_generation")
        marker_phase = RemoteMarkerPhase(_evidence_string(payload, "marker_phase"))
        if marker_phase is not RemoteMarkerPhase.EFFECT:
            raise ValueError("Effect intent marker phase must be effect")
        _effect_affected_resources(
            payload["affected_resources"],
            registered_resource_types,
        )
    elif kind is ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION:
        _evidence_code(payload["effect_code"], "Effect code")
        _evidence_code(payload["readiness_code"], "readiness code")
        if type(payload["positive"]) is not bool:
            raise ValueError("Effect readiness positive must be boolean")
    elif kind is ExecutionEvidenceKind.EFFECT_OUTCOME:
        _evidence_code(payload["effect_code"], "Effect code")
        _evidence_code(payload["operation_id"], "operation ID")
        disposition = EffectDisposition(_evidence_string(payload, "disposition"))
        if disposition is EffectDisposition.NOT_STARTED:
            raise ValueError("Effect outcome disposition is invalid")
        references = _evidence_string_tuple(
            payload["post_effect_evidence_refs"],
            "post-Effect evidence reference",
        )
        if not references or len(set(references)) != len(references):
            raise ValueError("post-Effect evidence references are incomplete")
    elif kind is ExecutionEvidenceKind.AUTHORITY_EVIDENCE:
        if payload["ownership_state"] not in {
            "acquisition_pending",
            "owned",
            "released",
            "quarantined",
            "unknown",
        }:
            raise ValueError("unknown authority evidence state")
        generation = payload["generation"]
        if generation is not None and (type(generation) is not int or generation < 1):
            raise ValueError("authority generation is invalid")
        phase = payload["phase"]
        if phase is not None:
            RemoteMarkerPhase(_evidence_string(payload, "phase"))
    elif kind is ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL:
        _evidence_code(payload["actor"], "abandonment actor")
        _evidence_code(payload["mechanism"], "abandonment mechanism")
        parse_rfc3339_utc(payload["approved_at"], "abandonment approval time")
        reason = payload["reason"]
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
            raise ValueError("abandonment reason must be non-empty and safe")
    elif kind is ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED:
        if type(payload["rollback_capable"]) is not bool:
            raise ValueError("rollback_capable must be boolean")
        cleanup_objects = _evidence_string_tuple(
            payload["cleanup_object_refs"],
            "cleanup object reference",
        )
        if not cleanup_objects or len(set(cleanup_objects)) != len(cleanup_objects):
            raise ValueError("cleanup object references are incomplete")
        for item in cleanup_objects:
            _evidence_code(item, "cleanup object reference")


def _validate_evidence_references(
    record: ExecutionEvidenceRecord,
    records_by_id: dict[str, ExecutionEvidenceRecord],
    registered_resource_types: Collection[str],
) -> None:
    payload = dict(record.payload)
    for key, item in payload.items():
        if (
            key.endswith("_evidence_ref")
            and key != "approval_evidence_ref"
            and item is not None
            and (not isinstance(item, str) or item not in records_by_id)
        ):
            raise ValueError("execution evidence reference is unresolved or forward")
        if key.endswith("_evidence_refs"):
            references = _evidence_string_tuple(item, key)
            if any(reference not in records_by_id for reference in references):
                raise ValueError(
                    "execution evidence reference is unresolved or forward"
                )
    readiness_kind = (
        ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION
        if record.kind is ExecutionEvidenceKind.EFFECT_OUTCOME
        else ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION
    )
    expected_kinds = {
        "intent_evidence_ref": {ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT},
        "observation_evidence_ref": {ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION},
        "outcome_evidence_ref": {ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME},
        "readiness_evidence_ref": {readiness_kind},
    }
    for key, kinds in expected_kinds.items():
        reference = payload.get(key)
        if reference is None:
            continue
        target = records_by_id.get(str(reference))
        if target is None or target.kind not in kinds:
            raise ValueError("execution evidence reference has the wrong kind")
        if key != "readiness_evidence_ref" and (
            target.bindings.resource_id != record.bindings.resource_id
            or target.bindings.change_id != record.bindings.change_id
        ):
            raise ValueError("execution evidence reference bindings do not match")
    if record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME:
        observation = records_by_id[str(payload["observation_evidence_ref"])]
        if (
            dict(observation.payload)["normalized_state_digest"]
            != payload["observed_state_digest"]
        ):
            raise ValueError("primitive outcome does not match fresh Observation")
    if record.kind is ExecutionEvidenceKind.EFFECT_OUTCOME:
        _validate_post_effect_observations(
            record,
            records_by_id,
            registered_resource_types,
        )


def _effect_affected_resources(
    value: object,
    registered_resource_types: Collection[str],
) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("Effect affected Resources must be a non-empty array")
    result: list[tuple[str, str, str, tuple[str, ...]]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "change_id",
            "resource_id",
            "resource_type",
            "state_addresses",
        }:
            raise ValueError("Effect affected Resource fields are invalid")
        resource_type = item["resource_type"]
        if (
            not isinstance(resource_type, str)
            or _RESOURCE_TYPE_CODE.fullmatch(resource_type) is None
            or resource_type not in registered_resource_types
        ):
            raise ValueError("unknown execution evidence Resource Type")
        resource_id = _evidence_code(item["resource_id"], "Resource ID")
        change_id = _evidence_code(item["change_id"], "Change ID")
        state_addresses = _evidence_string_tuple(
            item["state_addresses"],
            "affected Resource State Address",
        )
        if (
            not state_addresses
            or tuple(sorted(set(state_addresses))) != state_addresses
            or any(
                not address.startswith("special://")
                or any(token in address for token in ("\n", "\r", "\\", ".."))
                for address in state_addresses
            )
        ):
            raise ValueError("Effect affected Resource State Addresses are invalid")
        result.append((resource_type, resource_id, change_id, state_addresses))
    if len(set(result)) != len(result):
        raise ValueError("Effect affected Resources are duplicated")
    return tuple(result)


def _validate_post_effect_observations(
    outcome: ExecutionEvidenceRecord,
    records_by_id: dict[str, ExecutionEvidenceRecord],
    registered_resource_types: Collection[str],
) -> None:
    payload = dict(outcome.payload)
    operation = payload["operation_id"]
    intent = next(
        (
            record
            for record in records_by_id.values()
            if record.kind is ExecutionEvidenceKind.EFFECT_INTENT
            and dict(record.payload)["operation_id"] == operation
        ),
        None,
    )
    checkpoint = next(
        (
            record
            for record in records_by_id.values()
            if record.kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT
            and dict(record.payload)["operation_id"] == operation
        ),
        None,
    )
    if intent is None or checkpoint is None:
        raise ValueError("Effect outcome lacks intent/checkpoint")
    readiness = records_by_id.get(str(payload["readiness_evidence_ref"]))
    if (
        readiness is None
        or readiness.kind is not ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION
        or readiness.observed_at <= checkpoint.observed_at
        or dict(readiness.payload)["positive"] is not True
        or readiness.bindings != outcome.bindings
        or readiness.subject_id != outcome.subject_id
    ):
        raise ValueError("Effect outcome lacks fresh positive readiness")
    expected = set(
        _effect_affected_resources(
            dict(intent.payload)["affected_resources"],
            registered_resource_types,
        )
    )
    references = _evidence_string_tuple(
        payload["post_effect_evidence_refs"],
        "post-Effect evidence reference",
    )
    actual: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for reference in references:
        observation = records_by_id.get(reference)
        if (
            observation is None
            or observation.kind is not ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION
            or observation.observed_at <= checkpoint.observed_at
            or observation.observed_at <= readiness.observed_at
            or observation.bindings.run_id != outcome.bindings.run_id
            or observation.bindings.workspace_id != outcome.bindings.workspace_id
            or observation.bindings.device_id != outcome.bindings.device_id
            or observation.bindings.plan_id != outcome.bindings.plan_id
            or observation.bindings.plan_full_digest
            != outcome.bindings.plan_full_digest
            or observation.bindings.binding_digest != outcome.bindings.binding_digest
            or observation.resource_type is None
            or observation.bindings.resource_id is None
            or observation.bindings.change_id is None
        ):
            raise ValueError(
                "post-Effect evidence reference is not a fresh Observation"
            )
        actual.add(
            (
                observation.resource_type,
                observation.bindings.resource_id,
                observation.bindings.change_id,
                observation.state_addresses,
            )
        )
    if actual != expected or len(actual) != len(references):
        raise ValueError("post-Effect observations do not cover affected Resources")


def _evidence_result_signature(
    record: ExecutionEvidenceRecord,
) -> tuple[object, ...] | None:
    payload = dict(record.payload)
    key = (record.bindings.resource_id, record.bindings.change_id)
    if record.kind is ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED:
        return (*key, record.kind)
    if record.kind is ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT:
        return (*key, record.kind)
    if record.kind is ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT:
        return (*key, record.kind, payload["post_effect"])
    if record.kind in {
        ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT,
        ExecutionEvidenceKind.RESOURCE_SKIP_RESULT,
        ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL,
    }:
        return (*key, record.kind)
    if record.kind in {
        ExecutionEvidenceKind.EFFECT_INTENT,
        ExecutionEvidenceKind.EFFECT_OUTCOME,
    }:
        return (record.kind, payload["effect_code"])
    return None


def _reject_unsafe_evidence_content(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if any(token in key.lower() for token in ("secret", "password", "private")):
                raise ValueError("unsafe execution evidence field")
            _reject_unsafe_evidence_content(item)
    elif isinstance(value, list):
        for item in value:
            _reject_unsafe_evidence_content(item)
    elif isinstance(value, str) and (
        "\n" in value
        or "\r" in value
        or value.startswith(("/", "file://"))
        or "/.coreelec-reconciler/" in value
    ):
        raise ValueError("unsafe execution evidence content")


def _evidence_mapping(
    value: dict[str, object],
    key: str,
    fields: set[str],
) -> dict[str, object]:
    item = value.get(key)
    if not isinstance(item, dict) or set(item) != fields:
        raise ValueError(f"unknown or missing execution evidence {key} fields")
    return item


def _evidence_string(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError(f"execution evidence {key} must be a string")
    return item


def _evidence_code(value: object, label: str) -> str:
    if not isinstance(value, str) or not _EVIDENCE_CODE.fullmatch(value):
        raise ValueError(f"invalid execution evidence {label}")
    return value


def _optional_evidence_code(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _evidence_code(value, label)


def _evidence_positive_int(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if type(item) is not int or item < 1:
        raise ValueError(f"execution evidence {key} must be positive")
    return item


def _evidence_string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"execution evidence {label} must be a string array")
    return tuple(value)


def _evidence_workspace(value: object) -> str:
    if not isinstance(value, str) or not _WORKSPACE_ID.fullmatch(value):
        raise ValueError("invalid execution evidence workspace ID")
    return value


def compute_recovery_actions(
    evidence: RecoveryEvidence,
) -> tuple[AllowedRecoveryAction, ...]:
    """Compute conservative recovery authority without I/O or elapsed time."""
    corrupt = not all(
        (
            evidence.chain_valid,
            evidence.chain_complete,
            evidence.attachments_valid,
            evidence.codecs_valid,
        )
    )
    stable_and_bound = (
        evidence.stable_snapshot
        and evidence.binding_matches is True
        and evidence.remote_integrity_valid is not False
        and evidence.live_helper is False
        and not corrupt
    )
    inspect_allowed = bool(evidence.run_id.value and evidence.workspace_id.value)
    resume_allowed = (
        stable_and_bound
        and not evidence.forward_work_unperformed
        and evidence.canonical_status in {RunStatus.EXECUTING, RunStatus.INTERRUPTED}
        and evidence.effect_disposition is not EffectDisposition.AMBIGUOUS
    )
    rollback_allowed = (
        stable_and_bound
        and evidence.preparation_complete
        and evidence.rollback_declared
        and evidence.rollback_approved
        and evidence.current_relation
        in {
            StateRelation.BEFORE,
            StateRelation.POST,
            StateRelation.ALLOWED_INTERMEDIATE,
        }
        and evidence.effect_disposition is not EffectDisposition.AMBIGUOUS
    )
    normal_finalize = not corrupt and (
        evidence.terminal_revision_durable
        or (
            stable_and_bound
            and evidence.current_relation is not StateRelation.UNKNOWN
            and not evidence.forward_work_unperformed
        )
    )
    abandon = (
        evidence.binding_matches is not False
        and evidence.remote_ownership_presence is not Presence.ABSENT
    )
    return (
        AllowedRecoveryAction(
            RecoveryActionCode.INSPECT,
            None,
            inspect_allowed,
            (
                "recovery.workspace-present"
                if inspect_allowed
                else "recovery.identity-insufficient"
            ),
            False,
            False,
        ),
        AllowedRecoveryAction(
            RecoveryActionCode.RESUME_VERIFICATION,
            None,
            resume_allowed,
            (
                "recovery.verification-only-work-available"
                if resume_allowed
                else "recovery.resume-not-safe"
            ),
            False,
            False,
        ),
        AllowedRecoveryAction(
            RecoveryActionCode.ROLLBACK,
            None,
            rollback_allowed,
            (
                "recovery.rollback-capable-before-evidence-present"
                if rollback_allowed
                else "recovery.rollback-not-authorized"
            ),
            False,
            False,
        ),
        AllowedRecoveryAction(
            RecoveryActionCode.FINALIZE,
            FinalizeMode.NORMAL,
            normal_finalize,
            (
                "recovery.normal-finalization-available"
                if normal_finalize
                else "recovery.final-state-not-known"
            ),
            False,
            False,
        ),
        AllowedRecoveryAction(
            RecoveryActionCode.FINALIZE,
            FinalizeMode.ABANDON,
            abandon,
            (
                "recovery.abandonment-available"
                if abandon
                else "recovery.ownership-not-identifiable"
            ),
            True,
            True,
        ),
    )
