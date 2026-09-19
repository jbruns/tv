from dataclasses import replace

from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    EffectDisposition,
    FactState,
    FinalizeMode,
    NormalizedResourceState,
    Presence,
    RecoveryActionCode,
    RecoveryEvidence,
    RecoveryFact,
    RemoteMarkerPhase,
    RunStatus,
    StateRelation,
    WorkspaceId,
    compute_recovery_actions,
)
from coreelec_reconciler.domain.identifiers import RunId


def evidence() -> RecoveryEvidence:
    state = NormalizedResourceState(
        Presence.PRESENT,
        "regular",
        "sha256:" + "a" * 64,
        0o644,
    )
    return RecoveryEvidence(
        run_id=RunId("019950f8-4c00-7000-8000-000000000601"),
        workspace_id=WorkspaceId("workspace:opaque-test-workspace"),
        stable_snapshot=True,
        remote_ownership_presence=Presence.PRESENT,
        remote_generation=3,
        remote_phase=RemoteMarkerPhase.VERIFYING,
        remote_marker_digest="sha256:" + "b" * 64,
        remote_integrity_valid=True,
        remote_quarantine_presence=Presence.ABSENT,
        binding_matches=True,
        chain_valid=True,
        chain_complete=True,
        attachments_valid=True,
        codecs_valid=True,
        preparation_complete=True,
        rollback_declared=True,
        rollback_approved=True,
        live_helper=False,
        forward_work_unperformed=False,
        current_relation=StateRelation.POST,
        before_state=state,
        post_state=state,
        allowed_intermediate_states=(),
        effect_disposition=EffectDisposition.NOT_STARTED,
        effect_readiness_positive=None,
        post_effect_evidence_complete=True,
        rollback_complete_and_verified=False,
        restore_effect_preplanned=False,
        restore_effect_approved=False,
        canonical_status=RunStatus.INTERRUPTED,
        terminal_revision_durable=False,
        cleanup_complete=False,
        ownership_release_or_quarantine_durable=False,
        facts=(
            RecoveryFact(
                "recovery.workspace-present",
                FactState.PRESENT,
                "sha256:" + "c" * 64,
            ),
        ),
    )


def action(
    actions: tuple[AllowedRecoveryAction, ...],
    code: RecoveryActionCode,
    mode: FinalizeMode | None = None,
) -> AllowedRecoveryAction:
    return next(
        item for item in actions if item.code is code and item.finalize_mode is mode
    )


def test_recovery_actions_are_pure_complete_and_conservative() -> None:
    actions = compute_recovery_actions(evidence())
    assert len(actions) == 5
    assert action(actions, RecoveryActionCode.INSPECT).allowed
    assert action(actions, RecoveryActionCode.RESUME_VERIFICATION).allowed
    assert action(actions, RecoveryActionCode.ROLLBACK).allowed
    abandon = action(actions, RecoveryActionCode.FINALIZE, FinalizeMode.ABANDON)
    assert abandon.requires_approval
    assert abandon.requires_reason


def test_corruption_reduces_recovery_authority_to_inspect_and_abandon() -> None:
    actions = compute_recovery_actions(
        replace(evidence(), chain_valid=False, attachments_valid=False)
    )
    assert action(actions, RecoveryActionCode.INSPECT).allowed
    assert not action(actions, RecoveryActionCode.RESUME_VERIFICATION).allowed
    assert not action(actions, RecoveryActionCode.ROLLBACK).allowed
    assert action(actions, RecoveryActionCode.FINALIZE, FinalizeMode.ABANDON).allowed


def test_terminal_flag_cannot_authorize_normal_finalize_on_corrupt_chain() -> None:
    actions = compute_recovery_actions(
        replace(
            evidence(),
            chain_valid=False,
            terminal_revision_durable=True,
        )
    )
    assert not action(
        actions,
        RecoveryActionCode.FINALIZE,
        FinalizeMode.NORMAL,
    ).allowed
    assert action(
        actions,
        RecoveryActionCode.FINALIZE,
        FinalizeMode.ABANDON,
    ).allowed


def test_unstable_or_unknown_state_never_expands_authority() -> None:
    unstable = compute_recovery_actions(replace(evidence(), stable_snapshot=False))
    unknown = compute_recovery_actions(
        replace(evidence(), current_relation=StateRelation.UNKNOWN)
    )
    assert not action(unstable, RecoveryActionCode.RESUME_VERIFICATION).allowed
    assert not action(unknown, RecoveryActionCode.FINALIZE, FinalizeMode.NORMAL).allowed
