from coreelec_reconciler.domain.execution import (
    EffectDisposition,
    FinalizeMode,
    Presence,
    RecoveryActionCode,
    RecoveryEvidence,
    RemoteMarkerPhase,
    RemoteOwnershipSnapshot,
    RunStatus,
    StateRelation,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import RunId
from coreelec_reconciler.execution.recovery import inspect_recovery


def evidence(
    *,
    attachments_valid: bool = True,
    canonical_status: RunStatus = RunStatus.INTERRUPTED,
    terminal_revision_durable: bool = False,
    forward_work_unperformed: bool = False,
    live_helper: bool | None = False,
    binding_matches: bool | None = True,
    effect_disposition: EffectDisposition = EffectDisposition.NOT_STARTED,
    current_relation: StateRelation = StateRelation.POST,
) -> RecoveryEvidence:
    return RecoveryEvidence(
        run_id=RunId("run.test"),
        workspace_id=WorkspaceId("workspace:test"),
        stable_snapshot=True,
        remote_ownership_presence=Presence.PRESENT,
        remote_generation=1,
        remote_phase=RemoteMarkerPhase.PREPARED,
        remote_marker_digest="sha256:marker",
        remote_integrity_valid=True,
        remote_quarantine_presence=Presence.ABSENT,
        binding_matches=binding_matches,
        chain_valid=True,
        chain_complete=True,
        attachments_valid=attachments_valid,
        codecs_valid=True,
        preparation_complete=True,
        rollback_declared=True,
        rollback_approved=True,
        live_helper=live_helper,
        forward_work_unperformed=forward_work_unperformed,
        current_relation=current_relation,
        before_state=None,
        post_state=None,
        allowed_intermediate_states=(),
        effect_disposition=effect_disposition,
        effect_readiness_positive=None,
        post_effect_evidence_complete=True,
        rollback_complete_and_verified=False,
        restore_effect_preplanned=False,
        restore_effect_approved=False,
        canonical_status=canonical_status,
        terminal_revision_durable=terminal_revision_durable,
        cleanup_complete=False,
        ownership_release_or_quarantine_durable=False,
        facts=(),
    )


class Inspector:
    def __init__(
        self,
        first: RemoteOwnershipSnapshot,
        second: RemoteOwnershipSnapshot,
        value: RecoveryEvidence,
    ) -> None:
        self._reads = [first, second]
        self._evidence = value

    def read_remote_ownership(self) -> RemoteOwnershipSnapshot:
        return self._reads.pop(0)

    def validate_local_evidence(
        self, first: RemoteOwnershipSnapshot
    ) -> RecoveryEvidence:
        del first
        return self._evidence


def snapshot(generation: int = 1) -> RemoteOwnershipSnapshot:
    return RemoteOwnershipSnapshot(
        Presence.PRESENT,
        generation,
        f"sha256:marker-{generation}",
        "sha256:token",
        None,
        RemoteMarkerPhase.PREPARED,
        "sha256:manifest",
    )


def action_map(
    value: RecoveryEvidence,
) -> dict[tuple[RecoveryActionCode, FinalizeMode | None], bool]:
    result = inspect_recovery(Inspector(snapshot(), snapshot(), value))
    return {(item.code, item.finalize_mode): item.allowed for item in result.actions}


def test_complete_stable_evidence_allows_verification_rollback_and_abandon() -> None:
    actions = action_map(evidence())
    assert actions[(RecoveryActionCode.INSPECT, None)]
    assert actions[(RecoveryActionCode.RESUME_VERIFICATION, None)]
    assert actions[(RecoveryActionCode.ROLLBACK, None)]
    assert actions[(RecoveryActionCode.FINALIZE, FinalizeMode.NORMAL)]
    assert actions[(RecoveryActionCode.FINALIZE, FinalizeMode.ABANDON)]


def test_terminal_known_state_allows_normal_finalize() -> None:
    actions = action_map(
        evidence(
            canonical_status=RunStatus.FAILED_PARTIAL,
            terminal_revision_durable=True,
        )
    )
    assert actions[(RecoveryActionCode.FINALIZE, FinalizeMode.NORMAL)]


def test_corruption_allows_only_inspect_and_approved_reasoned_abandon() -> None:
    result = inspect_recovery(
        Inspector(snapshot(), snapshot(), evidence(attachments_valid=False))
    )
    allowed = [item for item in result.actions if item.allowed]
    assert [(item.code, item.finalize_mode) for item in allowed] == [
        (RecoveryActionCode.INSPECT, None),
        (RecoveryActionCode.FINALIZE, FinalizeMode.ABANDON),
    ]
    abandon = allowed[-1]
    assert abandon.requires_approval and abandon.requires_reason


def test_unsafe_recovery_facts_reduce_authority() -> None:
    for value in (
        evidence(forward_work_unperformed=True),
        evidence(live_helper=True),
        evidence(binding_matches=False),
        evidence(effect_disposition=EffectDisposition.AMBIGUOUS),
        evidence(current_relation=StateRelation.OTHER),
    ):
        actions = action_map(value)
        assert not (
            actions[(RecoveryActionCode.RESUME_VERIFICATION, None)]
            and actions[(RecoveryActionCode.ROLLBACK, None)]
        )


def test_marker_change_during_inspection_is_unstable_and_inspect_only() -> None:
    result = inspect_recovery(Inspector(snapshot(), snapshot(2), evidence()))
    assert not result.evidence.stable_snapshot
    allowed = [item for item in result.actions if item.allowed]
    assert [(item.code, item.finalize_mode) for item in allowed] == [
        (RecoveryActionCode.INSPECT, None),
        (RecoveryActionCode.FINALIZE, FinalizeMode.ABANDON),
    ]
