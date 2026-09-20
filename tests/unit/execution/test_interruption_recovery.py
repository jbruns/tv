from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from coreelec_reconciler.application.commands import RecoverCommand
from coreelec_reconciler.application.outcomes import (
    PlanOutcome,
    RecoverOutcome,
    ReportOutcome,
    ValidationOutcome,
)
from coreelec_reconciler.application.reconciler import (
    ApplicationData,
    ApplicationDependencies,
    ApplicationReconciler,
    ExecutionApplicationWorkflows,
)
from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    DeviceLease,
    FinalizeMode,
    MutationDisposition,
    MutationReceipt,
    MutationTrace,
    NormalizedResourceState,
    Presence,
    RecoveryActionCode,
    RecoveryEvidence,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RevisionLease,
    RunStatus,
    SealIntent,
    StoredRevision,
    VerifiedRunChain,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.domain.planning import CanonicalRunReport, DesiredRelation
from coreelec_reconciler.execution.authority import (
    AcquiredAuthority,
    AuthorityCoordinator,
)
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    ExecutionEngine,
    ExecutionOutcome,
    M3AuthorityRecovery,
    RecoveryCoordinator,
    RecoveryRequest,
)
from coreelec_reconciler.execution.managed_file import ManagedFileExecutor
from coreelec_reconciler.execution.recovery import RecoveryInspection
from coreelec_reconciler.resource_types.descriptor import (
    ManagedFileExecutionResult,
    ManagedFileVerification,
    ManagedFileVerificationStatus,
)
from tests.fakes.run_infrastructure import FakeAttachments
from tests.fakes.runtime import FakeManagedFiles
from tests.unit.execution.test_managed_file_lifecycle import (
    _marker,
    _prepared,
    _state,
)
from tests.unit.execution.test_recovery_actions import Inspector, evidence, snapshot


class _Journal:
    def __init__(self) -> None:
        self.events: list[str] = []

    def start(self, plan: object) -> None:
        self.events.append("start")

    def prepared(self, run_id: RunId, resource_id: str, prepared: object) -> None:
        self.events.append("prepared")

    def result(
        self,
        run_id: RunId,
        resource_id: str,
        result: ManagedFileExecutionResult,
    ) -> None:
        self.events.append("result")

    def terminal(self, run_id: RunId, status: RunStatus) -> StoredRevision:
        self.events.append("terminal")
        return StoredRevision(2, "sha256:terminal", b"{}")

    def cleanup(self, run_id: RunId, resource_id: str, result: object) -> None:
        self.events.append("cleanup")

    def skipped(
        self, run_id: RunId, resource_id: str, dependency_ids: tuple[str, ...]
    ) -> None:
        self.events.append("skipped")


class _SuccessfulResult:
    converged = True
    recovery_required = False
    rollback_verification = None


class _Change:
    resource_id = "resource"
    requires: tuple[str, ...] = ()
    disruptive = False

    def prepare(self) -> object:
        return object()

    def apply(self, prepared: object) -> ManagedFileExecutionResult:
        return cast(ManagedFileExecutionResult, _SuccessfulResult())

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> MutationTrace:
        return MutationTrace(())


class _CleanupFailure(_Change):
    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> MutationTrace:
        raise OSError("scripted cleanup failure")


class _RecoveryResource:
    def __init__(
        self,
        *,
        resource_id: str = "resource",
        ambiguous_rollback: bool = False,
        timeline: list[str] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.ambiguous_rollback = ambiguous_rollback
        self.resource_id = resource_id
        self.timeline = timeline

    def observe(self) -> object:
        self.calls.append("observe")
        return object()

    def assess(self, observation: object) -> object:
        self.calls.append("assess")
        return SimpleNamespace(relation=DesiredRelation.SATISFIED)

    def rollback(
        self,
    ) -> tuple[MutationTrace | None, ManagedFileVerification]:
        self.calls.append("rollback")
        if self.timeline is not None:
            self.timeline.append(f"rollback:{self.resource_id}")
        if self.ambiguous_rollback:
            return (
                MutationTrace(
                    (MutationReceipt("restore", MutationDisposition.AMBIGUOUS),)
                ),
                cast(ManagedFileVerification, _UnknownVerification()),
            )
        return MutationTrace(()), cast(ManagedFileVerification, _MatchedVerification())

    def cleanup(self, terminal_evidence_ref: str) -> MutationTrace:
        self.calls.append("cleanup")
        if self.timeline is not None:
            self.timeline.append(f"cleanup:{self.resource_id}")
        return MutationTrace(())


class _MatchedVerification:
    status = ManagedFileVerificationStatus.MATCHED


class _UnknownVerification:
    status = ManagedFileVerificationStatus.UNKNOWN


class _Persistence:
    def __init__(
        self,
        resource: _RecoveryResource,
        evidence_value: RecoveryEvidence | None = None,
        events: list[str] | None = None,
        resources: tuple[_RecoveryResource, ...] | None = None,
    ) -> None:
        self.resource_value = resource
        self.resource_values = resources or (resource,)
        self.evidence_value = evidence_value or evidence()
        self.events = events if events is not None else []
        head = StoredRevision(1, "sha256:head", b"{}")
        self.chain = VerifiedRunChain((head,), head, False)

    def load_chain(self, run_id: RunId) -> VerifiedRunChain:
        self.events.append("load")
        return self.chain

    def inspection_port(self, run_id: RunId) -> Inspector:
        return Inspector(snapshot(), snapshot(), self.evidence_value)

    def resources(self, run_id: RunId) -> tuple[_RecoveryResource, ...]:
        return self.resource_values

    def record_verification(
        self,
        run_id: RunId,
        resource_id: str,
        observation: object,
        assessment: object,
    ) -> StoredRevision:
        self.events.append("verification")
        return self.chain.head

    def record_rollback(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace | None,
        verification: ManagedFileVerification,
    ) -> StoredRevision:
        self.events.append("rollback")
        return self.chain.head

    def record_terminal(self, run_id: RunId, status: RunStatus) -> StoredRevision:
        self.events.append(f"terminal:{status.value}")
        return StoredRevision(2, "sha256:terminal", b"{}")

    def record_abandonment(
        self, run_id: RunId, *, approval: str, reason: str
    ) -> StoredRevision:
        self.events.append(f"abandon:{approval}:{reason}")
        return StoredRevision(2, "sha256:terminal", b"{}")

    def record_cleanup(
        self, run_id: RunId, resource_id: str, trace: MutationTrace
    ) -> str:
        self.events.append("cleanup:sha256:cleanup")
        return "sha256:cleanup"

    def seal(self, run_id: RunId, intent: SealIntent) -> None:
        self.events.append(f"seal:{intent.ownership_released_or_quarantined}")


class _Authority:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []

    def release(self, run_id: RunId, terminal_digest: str) -> MutationReceipt:
        self.events.append(f"release:{terminal_digest}")
        return MutationReceipt("release", MutationDisposition.APPLIED)

    def quarantine(
        self,
        run_id: RunId,
        incident_digest: str,
        *,
        approval: str,
        reason: str,
    ) -> None:
        self.events.append(f"quarantine:{approval}:{reason}")


class _BoundAuthorities:
    def __init__(self, authority: AcquiredAuthority) -> None:
        self.authority = authority

    def load(self, run_id: RunId) -> AcquiredAuthority:
        return self.authority

    def save(self, run_id: RunId, authority: AcquiredAuthority) -> None:
        self.authority = authority


class _Clock:
    def utc_now(self) -> str:
        return "2026-09-19T08:00:00Z"


def _acquired_authority() -> AcquiredAuthority:
    identity = RemoteOwnershipIdentity(
        DeviceId("device"),
        RunId("run.test"),
        WorkspaceId("workspace:test"),
        "plan",
        "sha256:plan",
        "sha256:binding",
        "boot",
    )
    return AcquiredAuthority(
        DeviceLease(DeviceId("device"), "device-lease"),
        RevisionLease(RunId("run.test"), WorkspaceId("workspace:test"), "run-lease"),
        WorkspaceId("workspace:test"),
        RemoteOwnership(
            identity,
            "sha256:token",
            1,
            RemoteMarkerPhase.VERIFYING,
            "sha256:marker",
        ),
    )


class _M3Coordinator:
    def __init__(self, calls: list[str] | None = None) -> None:
        self.calls = calls if calls is not None else []

    def checkpoint(
        self,
        authority: AcquiredAuthority,
        expected_phase: RemoteMarkerPhase,
        next_phase: RemoteMarkerPhase,
        evidence_digest: str | None,
        *,
        updated_at: str,
    ) -> AcquiredAuthority:
        self.calls.append(f"checkpoint:{next_phase.value}:{evidence_digest}")
        return replace(
            authority,
            ownership=replace(
                authority.ownership,
                phase=next_phase,
                generation=authority.ownership.generation + 1,
                marker_digest="sha256:next",
            ),
        )

    def release(
        self, authority: AcquiredAuthority, terminal_receipt_digest: str
    ) -> MutationReceipt:
        self.calls.append(f"release:{terminal_receipt_digest}")
        return MutationReceipt("release", MutationDisposition.APPLIED)

    def quarantine(
        self,
        authority: AcquiredAuthority,
        incident_receipt_digest: str,
        *,
        updated_at: str,
    ) -> object:
        self.calls.append(f"quarantine:{incident_receipt_digest}")
        return object()


class _FailedChange(_Change):
    resource_id = "failed"

    def apply(self, prepared: object) -> ManagedFileExecutionResult:
        result = _SuccessfulResult()
        result.converged = False
        return cast(ManagedFileExecutionResult, result)


class _DependentChange(_Change):
    resource_id = "dependent"
    requires = ("failed",)


class _IndependentChange(_Change):
    resource_id = "independent"


class _DisruptiveFailedChange(_FailedChange):
    disruptive = True


class _Recovery:
    def __init__(self, action: AllowedRecoveryAction) -> None:
        self.action = action
        self.calls: list[str] = []

    def inspect(self, run_id: RunId) -> RecoveryInspection:
        self.calls.append("inspect")
        return RecoveryInspection(cast(RecoveryEvidence, object()), (self.action,))

    def resume_verification(self, run_id: RunId) -> ExecutionOutcome:
        self.calls.append("resume_verification")
        return ExecutionOutcome(run_id, RunStatus.CONVERGED, (), True)

    def rollback(self, run_id: RunId) -> ExecutionOutcome:
        self.calls.append("rollback")
        return ExecutionOutcome(run_id, RunStatus.FAILED_ROLLED_BACK, (), True)

    def finalize(
        self,
        run_id: RunId,
        mode: FinalizeMode,
        *,
        approval: str | None,
        reason: str | None,
    ) -> ExecutionOutcome:
        self.calls.append(f"finalize:{mode.value}")
        return ExecutionOutcome(run_id, RunStatus.FAILED_RECOVERY_REQUIRED, (), True)


@pytest.mark.parametrize(
    ("recovery_request", "expected"),
    [
        (
            RecoveryRequest(RecoveryActionCode.RESUME_VERIFICATION),
            "resume_verification",
        ),
        (RecoveryRequest(RecoveryActionCode.ROLLBACK), "rollback"),
        (
            RecoveryRequest(RecoveryActionCode.FINALIZE, FinalizeMode.NORMAL),
            "finalize:normal",
        ),
        (
            RecoveryRequest(
                RecoveryActionCode.FINALIZE,
                FinalizeMode.ABANDON,
                approval="approval",
                reason="operator accepted unknown state",
            ),
            "finalize:abandon",
        ),
    ],
)
def test_recovery_dispatches_only_the_inspected_allowed_action(
    recovery_request: RecoveryRequest, expected: str
) -> None:
    action = AllowedRecoveryAction(
        recovery_request.action,
        recovery_request.finalize_mode,
        True,
        "allowed",
        recovery_request.finalize_mode is FinalizeMode.ABANDON,
        recovery_request.finalize_mode is FinalizeMode.ABANDON,
    )
    recovery = _Recovery(action)
    engine = ExecutionEngine(_Journal(), recovery)

    engine.recover(RunId("run"), recovery_request)

    assert recovery.calls == ["inspect", expected]


def test_disallowed_recovery_performs_no_work() -> None:
    action = AllowedRecoveryAction(
        RecoveryActionCode.ROLLBACK, None, False, "blocked", False, False
    )
    recovery = _Recovery(action)

    with pytest.raises(ValueError, match="not allowed"):
        ExecutionEngine(_Journal(), recovery).recover(
            RunId("run"), RecoveryRequest(RecoveryActionCode.ROLLBACK)
        )

    assert recovery.calls == ["inspect"]


def test_terminal_truth_is_durable_before_cleanup() -> None:
    journal = _Journal()
    recovery = _Recovery(
        AllowedRecoveryAction(
            RecoveryActionCode.INSPECT, None, True, "inspect", False, False
        )
    )

    outcome = ExecutionEngine(journal, recovery).start(
        ApprovedPlan(RunId("run"), (_Change(),))
    )

    assert outcome.status is RunStatus.CONVERGED
    assert journal.events == ["start", "prepared", "result", "terminal", "cleanup"]


def test_cleanup_failure_does_not_rewrite_terminal_truth() -> None:
    journal = _Journal()
    recovery = _Recovery(
        AllowedRecoveryAction(
            RecoveryActionCode.INSPECT, None, True, "inspect", False, False
        )
    )

    outcome = ExecutionEngine(journal, recovery).start(
        ApprovedPlan(RunId("run"), (_CleanupFailure(),))
    )

    assert outcome.status is RunStatus.CONVERGED
    assert not outcome.cleanup_complete
    assert journal.events[-1] == "terminal"


def test_concrete_recovery_uses_persisted_evidence_and_verified_rollback() -> None:
    resource = _RecoveryResource()
    timeline: list[str] = []
    persistence = _Persistence(resource, events=timeline)
    authority = _Authority(timeline)
    coordinator = RecoveryCoordinator(persistence, authority)
    engine = ExecutionEngine(_Journal(), coordinator)

    outcome = engine.recover(
        RunId("run.test"), RecoveryRequest(RecoveryActionCode.ROLLBACK)
    )

    assert outcome.status is RunStatus.FAILED_ROLLED_BACK
    assert resource.calls == ["rollback", "cleanup"]
    assert timeline == [
        "load",
        "load",
        "rollback",
        "terminal:failed_rolled_back",
        "cleanup:sha256:cleanup",
        "release:sha256:terminal",
        "seal:True",
    ]


def test_multi_resource_recovery_rolls_back_reverse_and_cleans_plan_order() -> None:
    resource_events: list[str] = []
    first = _RecoveryResource(resource_id="first", timeline=resource_events)
    second = _RecoveryResource(resource_id="second", timeline=resource_events)
    persistence = _Persistence(first, resources=(first, second))
    engine = ExecutionEngine(
        _Journal(),
        RecoveryCoordinator(persistence, _Authority()),
    )

    outcome = engine.recover(
        RunId("run.test"),
        RecoveryRequest(RecoveryActionCode.ROLLBACK),
    )

    assert outcome.status is RunStatus.FAILED_ROLLED_BACK
    assert resource_events == [
        "rollback:second",
        "rollback:first",
        "cleanup:first",
        "cleanup:second",
    ]


def test_approved_reasoned_abandonment_terminalizes_then_quarantines() -> None:
    resource = _RecoveryResource()
    persistence = _Persistence(resource, evidence(attachments_valid=False))
    authority = _Authority()
    engine = ExecutionEngine(_Journal(), RecoveryCoordinator(persistence, authority))

    outcome = engine.recover(
        RunId("run.test"),
        RecoveryRequest(
            RecoveryActionCode.FINALIZE,
            FinalizeMode.ABANDON,
            approval="approval.operator",
            reason="evidence is corrupt",
        ),
    )

    assert outcome.status is RunStatus.FAILED_RECOVERY_REQUIRED
    assert persistence.events[-2:] == [
        "abandon:approval.operator:evidence is corrupt",
        "seal:True",
    ]
    assert authority.events == ["quarantine:approval.operator:evidence is corrupt"]


def test_resume_recovery_only_observes_assesses_and_finalizes() -> None:
    resource = _RecoveryResource()
    persistence = _Persistence(resource)
    authority = _Authority()
    engine = ExecutionEngine(_Journal(), RecoveryCoordinator(persistence, authority))

    outcome = engine.recover(
        RunId("run.test"),
        RecoveryRequest(RecoveryActionCode.RESUME_VERIFICATION),
    )

    assert outcome.status is RunStatus.CONVERGED
    assert resource.calls == ["observe", "assess", "cleanup"]
    assert "verification" in persistence.events


def test_ambiguous_rollback_retains_authority_and_requires_recovery() -> None:
    resource = _RecoveryResource(ambiguous_rollback=True)
    persistence = _Persistence(resource)
    authority = _Authority()
    engine = ExecutionEngine(_Journal(), RecoveryCoordinator(persistence, authority))

    outcome = engine.recover(
        RunId("run.test"), RecoveryRequest(RecoveryActionCode.ROLLBACK)
    )

    assert outcome.status is RunStatus.FAILED_RECOVERY_REQUIRED
    assert not outcome.cleanup_complete
    assert authority.events == []
    assert persistence.events[-2:] == [
        "terminal:failed_recovery_required",
        "seal:False",
    ]


def test_normal_finalize_preserves_existing_terminal_truth() -> None:
    resource = _RecoveryResource()
    timeline: list[str] = []
    persistence = _Persistence(
        resource,
        evidence(
            canonical_status=RunStatus.FAILED_PARTIAL,
            terminal_revision_durable=True,
        ),
        timeline,
    )
    authority = _Authority(timeline)
    engine = ExecutionEngine(_Journal(), RecoveryCoordinator(persistence, authority))

    outcome = engine.recover(
        RunId("run.test"),
        RecoveryRequest(RecoveryActionCode.FINALIZE, FinalizeMode.NORMAL),
    )

    assert outcome.status is RunStatus.FAILED_PARTIAL
    assert not any(event.startswith("terminal:") for event in timeline)
    assert timeline[-3:] == [
        "cleanup:sha256:cleanup",
        "release:sha256:head",
        "seal:True",
    ]


def test_recovery_authority_checkpoints_m3_marker_before_release() -> None:
    coordinator = _M3Coordinator()
    recovery = M3AuthorityRecovery(
        cast(AuthorityCoordinator, coordinator),
        _BoundAuthorities(_acquired_authority()),
        _Clock(),
    )

    receipt = recovery.release(RunId("run.test"), "sha256:terminal")

    assert receipt.disposition is MutationDisposition.APPLIED
    assert coordinator.calls == [
        "checkpoint:terminal_release_pending:sha256:terminal",
        "release:sha256:terminal",
    ]


def test_cleanup_receipt_precedes_terminal_authorized_m3_release() -> None:
    timeline: list[str] = []
    persistence = _Persistence(_RecoveryResource(), events=timeline)
    authority = M3AuthorityRecovery(
        cast(AuthorityCoordinator, _M3Coordinator(timeline)),
        _BoundAuthorities(_acquired_authority()),
        _Clock(),
    )
    engine = ExecutionEngine(_Journal(), RecoveryCoordinator(persistence, authority))

    engine.recover(RunId("run.test"), RecoveryRequest(RecoveryActionCode.ROLLBACK))

    assert timeline == [
        "load",
        "load",
        "rollback",
        "terminal:failed_rolled_back",
        "cleanup:sha256:cleanup",
        "checkpoint:terminal_release_pending:sha256:terminal",
        "release:sha256:terminal",
        "seal:True",
    ]


def test_public_recover_seam_uses_concrete_recovery_coordinator() -> None:
    persistence = _Persistence(_RecoveryResource())
    authority = _Authority()
    engine = ExecutionEngine(_Journal(), RecoveryCoordinator(persistence, authority))
    report = CanonicalRunReport(
        b'{"run_id":"run.test","status":"failed_rolled_back"}',
        "run.test",
        "sha256:terminal",
        2,
        RunStatus.FAILED_ROLLED_BACK,
    )
    data = SimpleNamespace(report=lambda command: ReportOutcome(report))
    workflows = ExecutionApplicationWorkflows(cast(ApplicationData, data), engine)
    application = ApplicationReconciler(
        dependencies=ApplicationDependencies(
            workflows,
            lambda command: ValidationOutcome(True, (), 0, "", (), ()),
            lambda command: PlanOutcome(RunId("plan"), None, "blocked"),
        )
    )

    outcome = application.execute(RecoverCommand(".", RunId("run.test"), "rollback"))

    assert outcome == RecoverOutcome(report, True)


@pytest.mark.parametrize("boundary", range(1, 7))
def test_interruption_at_each_create_primitive_durable_boundary(
    boundary: int,
) -> None:
    events: list[str] = []
    device = FakeManagedFiles()
    attachments = FakeAttachments()
    prepared = _prepared(
        attachments,
        _absent_state(),
        _state(b"desired"),
        None,
        b"desired",
    )

    def stop(label: str) -> None:
        events.append(label)
        if len(events) == boundary:
            raise InterruptedError(label)

    executor = ManagedFileExecutor(
        device,
        attachments,
        lambda intent: stop(f"intent:{intent.primitive.value}"),
        _marker,
        lambda marker: stop(f"marker:{marker.phase.value}"),
        lambda trace, observation: stop(f"outcome:{trace.receipts[-1].operation_id}"),
    )

    with pytest.raises(InterruptedError):
        executor.apply(
            prepared,
            resource_id="skin.playlist.new-shows",
            change_id="change-1",
            rollback_approved=False,
        )

    assert len(events) == boundary
    if boundary <= 2:
        assert device.operations == ()
    elif boundary <= 5:
        assert len(device.operations) == 1
    else:
        assert len(device.operations) == 2


def _absent_state() -> NormalizedResourceState:
    return NormalizedResourceState(Presence.ABSENT, None, None, None)


def test_known_resource_failure_skips_dependents_and_continues_independent_work() -> (
    None
):
    journal = _Journal()
    recovery = _Recovery(
        AllowedRecoveryAction(
            RecoveryActionCode.INSPECT, None, True, "inspect", False, False
        )
    )

    outcome = ExecutionEngine(journal, recovery).start(
        ApprovedPlan(
            RunId("run"),
            (_FailedChange(), _DependentChange(), _IndependentChange()),
        )
    )

    assert outcome.status is RunStatus.FAILED_PARTIAL
    assert journal.events.count("result") == 2
    assert journal.events.count("skipped") == 1


def test_disruptive_failure_stops_all_later_mutation() -> None:
    journal = _Journal()
    recovery = _Recovery(
        AllowedRecoveryAction(
            RecoveryActionCode.INSPECT, None, True, "inspect", False, False
        )
    )

    outcome = ExecutionEngine(journal, recovery).start(
        ApprovedPlan(RunId("run"), (_DisruptiveFailedChange(), _IndependentChange()))
    )

    assert outcome.status is RunStatus.FAILED_PARTIAL
    assert journal.events.count("result") == 1
    assert journal.events.count("skipped") == 1
