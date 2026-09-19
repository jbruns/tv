from typing import cast

import pytest

from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    FinalizeMode,
    MutationTrace,
    RecoveryActionCode,
    RecoveryEvidence,
    RunStatus,
)
from coreelec_reconciler.domain.identifiers import RunId
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    ExecutionEngine,
    ExecutionOutcome,
    RecoveryRequest,
)
from coreelec_reconciler.execution.managed_file import ManagedFileExecutionResult
from coreelec_reconciler.execution.recovery import RecoveryInspection


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

    def terminal(self, run_id: RunId, status: RunStatus) -> None:
        self.events.append("terminal")

    def cleanup(self, run_id: RunId, resource_id: str, result: object) -> None:
        self.events.append("cleanup")


class _SuccessfulResult:
    converged = True
    recovery_required = False
    rollback_verification = None


class _Change:
    resource_id = "resource"

    def prepare(self) -> object:
        return object()

    def apply(self, prepared: object) -> ManagedFileExecutionResult:
        return cast(ManagedFileExecutionResult, _SuccessfulResult())

    def cleanup(self, prepared: object) -> MutationTrace:
        return MutationTrace(())


class _CleanupFailure(_Change):
    def cleanup(self, prepared: object) -> MutationTrace:
        raise OSError("scripted cleanup failure")


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
