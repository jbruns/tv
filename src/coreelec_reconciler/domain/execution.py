"""Closed execution, persistence, and recovery vocabulary."""

from dataclasses import dataclass
from enum import StrEnum

from coreelec_reconciler.domain.identifiers import DeviceId, RunId


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
    normal_finalize = evidence.terminal_revision_durable or (
        stable_and_bound
        and evidence.current_relation is not StateRelation.UNKNOWN
        and not evidence.forward_work_unperformed
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
