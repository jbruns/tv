from dataclasses import replace

import pytest

from coreelec_reconciler.domain.execution import (
    EffectDisposition,
    FinalizeMode,
    Presence,
    RecoveryActionCode,
    RecoveryEvidence,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RemoteOwnershipSnapshot,
    RunStatus,
    StateRelation,
    StoredRevision,
    WorkspaceId,
    compute_recovery_actions,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.execution.recovery import RecoveryInspection
from coreelec_reconciler.execution.recovery_access import (
    RecoveryAccess,
    RecoveryActionRequest,
    RecoveryHandoff,
    TrustedRecoveryIdentity,
)

RUN_ID = RunId("0199707d-4d00-7000-8000-000000000083")
PLAN_ID = PlanId("0199707d-4d00-7000-8000-000000000081")
ORIGIN_ID = RunId("0199707d-4d00-7000-8000-000000000080")
DEVICE_ID = DeviceId("living-room")
WORKSPACE_ID = WorkspaceId("workspace-83")
PLAN_DIGEST = "sha256:" + "a" * 64
TOKEN_DIGEST = "sha256:" + "b" * 64
MARKER_DIGEST = "sha256:" + "c" * 64
REVISION_DIGEST = "sha256:" + "d" * 64


def _remote_identity() -> RemoteOwnershipIdentity:
    return RemoteOwnershipIdentity(
        DEVICE_ID,
        RUN_ID,
        WORKSPACE_ID,
        PLAN_ID.value,
        PLAN_DIGEST,
        "sha256:" + "e" * 64,
        "boot-1",
    )


def _snapshot() -> RemoteOwnershipSnapshot:
    return RemoteOwnershipSnapshot(
        Presence.PRESENT,
        3,
        MARKER_DIGEST,
        TOKEN_DIGEST,
        _remote_identity(),
        RemoteMarkerPhase.ACQUIRED,
        "sha256:" + "f" * 64,
    )


def _evidence(*, corrupt: bool = False) -> RecoveryEvidence:
    return RecoveryEvidence(
        run_id=RUN_ID,
        workspace_id=WORKSPACE_ID,
        stable_snapshot=True,
        remote_ownership_presence=Presence.PRESENT,
        remote_generation=3,
        remote_phase=RemoteMarkerPhase.ACQUIRED,
        remote_marker_digest=MARKER_DIGEST,
        remote_integrity_valid=True,
        remote_quarantine_presence=Presence.ABSENT,
        binding_matches=True,
        chain_valid=not corrupt,
        chain_complete=not corrupt,
        attachments_valid=not corrupt,
        codecs_valid=not corrupt,
        preparation_complete=True,
        rollback_declared=True,
        rollback_approved=True,
        live_helper=False,
        forward_work_unperformed=False,
        current_relation=StateRelation.POST,
        before_state=None,
        post_state=None,
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
        facts=(),
    )


class _Store:
    def __init__(self) -> None:
        self.revision = 7
        self.digest = REVISION_DIGEST

    def load_identity(self, run_id: RunId) -> dict[str, object]:
        assert run_id == RUN_ID
        return {
            "run_id": RUN_ID.value,
            "device_id": DEVICE_ID.value,
            "workspace_id": WORKSPACE_ID.value,
            "plan_id": PLAN_ID.value,
            "plan_full_digest": PLAN_DIGEST,
            "originating_planning_run_id": ORIGIN_ID.value,
            "ownership_token_digest": TOKEN_DIGEST,
            "binding_digest": "sha256:" + "e" * 64,
            "boot_id": "boot-1",
        }

    def inspect_head(self, run_id: RunId) -> StoredRevision:
        assert run_id == RUN_ID
        return StoredRevision(self.revision, self.digest, b"canonical")


class _Environment:
    def __init__(self) -> None:
        self.snapshot = _snapshot()
        self.reads = 0

    def read_remote_ownership(self, run_id: RunId) -> RemoteOwnershipSnapshot:
        assert run_id == RUN_ID
        self.reads += 1
        return self.snapshot

    def read_remote_quarantine(self, run_id: RunId) -> Presence:
        assert run_id == RUN_ID
        return Presence.ABSENT

    def live_helper(self, run_id: RunId) -> bool | None:
        assert run_id == RUN_ID
        return False


class _Ownership:
    def read_ownership(self, device_id: DeviceId) -> RemoteOwnership:
        assert device_id == DEVICE_ID
        snapshot = _snapshot()
        assert snapshot.identity is not None
        assert snapshot.generation is not None
        assert snapshot.phase is not None
        assert snapshot.marker_digest is not None
        assert snapshot.token_digest is not None
        return RemoteOwnership(
            snapshot.identity,
            snapshot.token_digest,
            snapshot.generation,
            snapshot.phase,
            snapshot.marker_digest,
        )


class _Inspections:
    def __init__(self, evidence: RecoveryEvidence) -> None:
        self.evidence = evidence

    def inspect(self, run_id: RunId) -> RecoveryInspection:
        assert run_id == RUN_ID
        return RecoveryInspection(
            self.evidence,
            compute_recovery_actions(self.evidence),
        )


class _Executor:
    def __init__(self) -> None:
        self.handoffs: list[RecoveryHandoff] = []

    def execute_recovery(self, handoff: RecoveryHandoff) -> str:
        self.handoffs.append(handoff)
        return "executed"


class _ExecutorFactory:
    def __init__(self) -> None:
        self.handoffs: list[RecoveryHandoff] = []
        self.executors: list[_Executor] = []

    def __call__(self, handoff: RecoveryHandoff) -> _Executor:
        self.handoffs.append(handoff)
        executor = _Executor()
        self.executors.append(executor)
        return executor


def _identity() -> TrustedRecoveryIdentity:
    return TrustedRecoveryIdentity(
        RUN_ID,
        DEVICE_ID,
        PLAN_ID,
        PLAN_DIGEST,
        ORIGIN_ID,
    )


def _access(
    evidence: RecoveryEvidence | None = None,
) -> tuple[RecoveryAccess, _Store, _Environment]:
    store = _Store()
    environment = _Environment()
    return (
        RecoveryAccess(
            store,
            environment,
            _Ownership(),
            _Inspections(evidence or _evidence()),
        ),
        store,
        environment,
    )


def test_issues_exact_validated_handoff_before_mutation_execution() -> None:
    access, _, _ = _access()
    inspection = access.inspect(_identity())
    request = RecoveryActionRequest(
        RecoveryActionCode.ROLLBACK,
        approval=None,
        reason=None,
    )
    handoff = access.authorize(inspection, request)
    factory = _ExecutorFactory()

    assert access.execute_mutation(handoff, request, factory) == "executed"
    assert factory.handoffs == [handoff]
    assert factory.executors[0].handoffs == [handoff]
    assert handoff.revision == 7
    assert handoff.revision_digest == REVISION_DIGEST
    assert handoff.evidence_digest == inspection.evidence_digest


def test_rejects_untrusted_plan_identity_before_remote_inspection() -> None:
    access, _, environment = _access()

    with pytest.raises(ValueError, match="identity changed"):
        access.inspect(replace(_identity(), plan_full_digest="sha256:" + "0" * 64))

    assert environment.reads == 0


def test_rejects_revision_change_during_inspection() -> None:
    store = _Store()
    environment = _Environment()

    class _ChangingInspection(_Inspections):
        def inspect(self, run_id: RunId) -> RecoveryInspection:
            inspected = super().inspect(run_id)
            store.revision += 1
            store.digest = "sha256:" + "1" * 64
            return inspected

    access = RecoveryAccess(
        store,
        environment,
        _Ownership(),
        _ChangingInspection(_evidence()),
    )

    with pytest.raises(ValueError, match="changed during"):
        access.inspect(_identity())


def test_rejects_stale_revision_before_opening_mutation_executor() -> None:
    access, store, _ = _access()
    request = RecoveryActionRequest(RecoveryActionCode.ROLLBACK)
    handoff = access.authorize(access.inspect(_identity()), request)
    store.revision += 1
    store.digest = "sha256:" + "1" * 64
    factory = _ExecutorFactory()

    with pytest.raises(ValueError, match="stale"):
        access.execute_mutation(handoff, request, factory)

    assert factory.handoffs == []


def test_rejects_changed_action_and_tampered_handoff() -> None:
    access, _, _ = _access()
    request = RecoveryActionRequest(RecoveryActionCode.ROLLBACK)
    handoff = access.authorize(access.inspect(_identity()), request)
    factory = _ExecutorFactory()

    with pytest.raises(ValueError, match="changed"):
        access.execute_mutation(
            handoff,
            RecoveryActionRequest(
                RecoveryActionCode.FINALIZE,
                FinalizeMode.NORMAL,
            ),
            factory,
        )
    with pytest.raises(ValueError, match="altered"):
        access.execute_mutation(
            replace(handoff, revision_digest="sha256:" + "9" * 64),
            request,
            factory,
        )
    with pytest.raises(ValueError, match="altered"):
        access.execute_mutation(
            replace(
                handoff,
                evidence=replace(handoff.evidence, chain_valid=False),
            ),
            request,
            factory,
        )

    assert factory.handoffs == []


def test_corrupt_evidence_allows_only_separately_approved_abandonment() -> None:
    access, _, _ = _access(_evidence(corrupt=True))
    inspection = access.inspect(_identity())
    assert [
        (action.code, action.finalize_mode)
        for action in inspection.actions
        if action.allowed
    ] == [
        (RecoveryActionCode.INSPECT, None),
        (RecoveryActionCode.FINALIZE, FinalizeMode.ABANDON),
    ]

    with pytest.raises(ValueError, match="not allowed"):
        access.authorize(
            inspection,
            RecoveryActionRequest(RecoveryActionCode.ROLLBACK),
        )
    with pytest.raises(ValueError, match="approval"):
        access.authorize(
            inspection,
            RecoveryActionRequest(
                RecoveryActionCode.FINALIZE,
                FinalizeMode.ABANDON,
                reason="operator accepted quarantine",
            ),
        )

    request = RecoveryActionRequest(
        RecoveryActionCode.FINALIZE,
        FinalizeMode.ABANDON,
        approval="operator@example.test",
        reason="operator accepted quarantine",
    )
    handoff = access.authorize(inspection, request)
    factory = _ExecutorFactory()
    assert access.execute_mutation(handoff, request, factory) == "executed"
    assert factory.handoffs == [handoff]


def test_recomputes_actions_instead_of_trusting_coordinator_action_list() -> None:
    evidence = _evidence(corrupt=True)

    class _UnsafeInspections:
        def inspect(self, run_id: RunId) -> RecoveryInspection:
            assert run_id == RUN_ID
            unsafe = replace(
                compute_recovery_actions(_evidence())[2],
                allowed=True,
            )
            return RecoveryInspection(evidence, (unsafe,))

    access, store, environment = _access(evidence)
    access = RecoveryAccess(store, environment, _Ownership(), _UnsafeInspections())
    inspection = access.inspect(_identity())

    with pytest.raises(ValueError, match="not allowed"):
        access.authorize(
            inspection,
            RecoveryActionRequest(RecoveryActionCode.ROLLBACK),
        )


def test_rejects_changed_remote_evidence_before_mutation_execution() -> None:
    access, _, environment = _access()
    request = RecoveryActionRequest(RecoveryActionCode.ROLLBACK)
    handoff = access.authorize(access.inspect(_identity()), request)
    environment.snapshot = replace(environment.snapshot, generation=4)
    factory = _ExecutorFactory()

    with pytest.raises(ValueError, match="remote evidence is stale"):
        access.execute_mutation(handoff, request, factory)

    assert factory.handoffs == []
