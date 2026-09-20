from dataclasses import dataclass
from typing import assert_type, cast

import pytest

from coreelec_reconciler.application.commands import (
    ActionCommand,
    ApplyCommand,
    InventoryCommand,
    ObserveCommand,
    PlanCommand,
    ReconcileCommand,
    RecoverCommand,
    ReportCommand,
    ValidateCommand,
    VerifyCommand,
)
from coreelec_reconciler.application.outcomes import (
    ActionResult,
    ApplyOutcome,
    ApplyResult,
    InventoryResult,
    ObservationOutcome,
    ObserveResult,
    PlanOutcome,
    PlanResult,
    ReconcileOutcome,
    ReconcileResult,
    RecoverOutcome,
    RecoverResult,
    RecoveryInspectionOutcome,
    ReportOutcome,
    ReportResult,
    UnsupportedOutcome,
    UnsupportedReason,
    ValidateResult,
    ValidationOutcome,
    VerifyOutcome,
    VerifyResult,
)
from coreelec_reconciler.application.reconciler import (
    ApplicationData,
    ApplicationDependencies,
    ApplicationReconciler,
    ExecutionApplicationWorkflows,
)
from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    FinalizeMode,
    RecoveryActionCode,
    RecoveryEvidence,
    RunStatus,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.domain.planning import (
    CanonicalPlan,
    CanonicalRunReport,
    PlanDisposition,
)
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    ExecutionEngine,
    ExecutionOutcome,
    RecoveryRequest,
)
from coreelec_reconciler.execution.recovery import RecoveryInspection


def _report(
    run_id: str,
    status: RunStatus,
    *,
    revision: int = 3,
) -> CanonicalRunReport:
    content = f'{{"run_id":"{run_id}","status":"{status.value}"}}'.encode()
    return CanonicalRunReport(content, run_id, f"sha256:{run_id}", revision, status)


PLAN = CanonicalPlan(
    b'{"kind":"CoreElecReconcilerPlan"}',
    "plan",
    "sha256:plan-full",
    "sha256:plan-semantic",
    PlanDisposition.ACTIONABLE,
)
OBSERVE_REPORT = _report("observe", RunStatus.NOOP)
PLANNING_REPORT = _report("planning", RunStatus.AWAITING_APPROVAL, revision=2)
EXECUTION_REPORT = _report("execute", RunStatus.CONVERGED, revision=8)
VERIFY_REPORT = _report("verify", RunStatus.CONVERGED, revision=4)
RECOVERY_REPORT = _report("recover", RunStatus.FAILED_ROLLED_BACK, revision=9)


class _Workflows:
    def observe(self, command: ObserveCommand) -> ObservationOutcome:
        return ObservationOutcome(OBSERVE_REPORT)

    def apply(self, command: ApplyCommand) -> ApplyOutcome:
        return ApplyOutcome(EXECUTION_REPORT, True)

    def reconcile(self, command: ReconcileCommand) -> ReconcileOutcome:
        return ReconcileOutcome(PLANNING_REPORT, PLAN, EXECUTION_REPORT, True)

    def verify(self, command: VerifyCommand) -> VerifyOutcome:
        return VerifyOutcome(VERIFY_REPORT)

    def recover(
        self, command: RecoverCommand
    ) -> RecoverOutcome | RecoveryInspectionOutcome:
        return RecoverOutcome(RECOVERY_REPORT, True)

    def report(self, command: ReportCommand) -> ReportOutcome:
        return ReportOutcome(RECOVERY_REPORT)


def _application() -> ApplicationReconciler:
    return ApplicationReconciler(
        dependencies=ApplicationDependencies(
            _Workflows(),
            lambda command: ValidationOutcome(True, (), 0, "", (), ()),
            lambda command: PlanOutcome(
                RunId("planning"),
                PlanId("plan"),
                "actionable",
                PLAN,
                PLANNING_REPORT,
            ),
        )
    )


class _Data:
    def __init__(self, planned: PlanOutcome) -> None:
        self.planned = planned
        self.reports = {
            RunId("execute"): EXECUTION_REPORT,
            RunId("recover"): RECOVERY_REPORT,
        }

    def observe(self, command: ObserveCommand) -> ObservationOutcome:
        return ObservationOutcome(OBSERVE_REPORT)

    def plan(self, command: PlanCommand) -> PlanOutcome:
        return self.planned

    def approved_plan(
        self, plan_id: PlanId, approval_scopes: tuple[str, ...]
    ) -> ApprovedPlan:
        return ApprovedPlan(RunId("execute"), ())

    def verify(self, command: VerifyCommand) -> VerifyOutcome:
        return VerifyOutcome(VERIFY_REPORT)

    def report(self, command: ReportCommand) -> ReportOutcome:
        return ReportOutcome(self.reports[command.run_id])


@dataclass(frozen=True)
class _InspectionEvidence:
    run_id: RunId
    cleanup_complete: bool
    canonical_status: RunStatus


class _Engine:
    def __init__(self, inspection: RecoveryInspection) -> None:
        self.inspection = inspection

    def start(self, plan: ApprovedPlan) -> ExecutionOutcome:
        return ExecutionOutcome(
            plan.run_id,
            RunStatus.CONVERGED,
            (),
            cleanup_complete=False,
        )

    def inspect(self, run_id: RunId) -> RecoveryInspection:
        return self.inspection

    def recover(
        self, run_id: RunId, allowed_action: RecoveryRequest
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            RunId("recover"),
            RunStatus.FAILED_ROLLED_BACK,
            (),
            cleanup_complete=False,
        )


def _concrete_workflows(
    planned: PlanOutcome,
    actions: tuple[AllowedRecoveryAction, ...] = (),
) -> ExecutionApplicationWorkflows:
    evidence = cast(
        RecoveryEvidence,
        _InspectionEvidence(
            RunId("recover"),
            cleanup_complete=False,
            canonical_status=RunStatus.FAILED_ROLLED_BACK,
        ),
    )
    inspection = RecoveryInspection(evidence, actions)
    return ExecutionApplicationWorkflows(
        cast(ApplicationData, _Data(planned)),
        cast(ExecutionEngine, _Engine(inspection)),
    )


def test_all_implemented_workflows_use_explicit_dependencies() -> None:
    app = _application()
    device = DeviceId("device")

    assert isinstance(app.execute(ValidateCommand(".")), ValidationOutcome)
    assert isinstance(app.execute(ObserveCommand(".", device)), ObservationOutcome)
    assert isinstance(app.execute(PlanCommand(".", device)), PlanOutcome)
    assert isinstance(app.execute(ApplyCommand(".", PlanId("plan"), ())), ApplyOutcome)
    assert isinstance(app.execute(ReconcileCommand(".", device, ())), ReconcileOutcome)
    assert isinstance(app.execute(VerifyCommand(".", device)), VerifyOutcome)
    assert isinstance(
        app.execute(RecoverCommand(".", RunId("run"), "rollback")), RecoverOutcome
    )
    assert isinstance(app.execute(ReportCommand(".", RunId("run"))), ReportOutcome)


def test_overloads_preserve_precise_public_result_types() -> None:
    app = _application()
    device = DeviceId("device")

    assert_type(app.execute(ValidateCommand(".")), ValidateResult)
    assert_type(app.execute(InventoryCommand(".")), InventoryResult)
    assert_type(app.execute(ObserveCommand(".", device)), ObserveResult)
    assert_type(app.execute(PlanCommand(".", device)), PlanResult)
    assert_type(app.execute(ApplyCommand(".", PlanId("plan"), ())), ApplyResult)
    assert_type(app.execute(ReconcileCommand(".", device, ())), ReconcileResult)
    assert_type(app.execute(VerifyCommand(".", device)), VerifyResult)
    assert_type(
        app.execute(RecoverCommand(".", RunId("run"), "inspect")), RecoverResult
    )
    assert_type(app.execute(ReportCommand(".", RunId("run"))), ReportResult)
    assert_type(app.execute(ActionCommand(".", "guided")), ActionResult)


def test_observe_verify_and_report_preserve_canonical_run_documents() -> None:
    workflows = _concrete_workflows(
        PlanOutcome(
            RunId("planning"),
            PlanId("plan"),
            "actionable",
            PLAN,
            PLANNING_REPORT,
        )
    )

    observed = workflows.observe(ObserveCommand(".", DeviceId("device")))
    verified = workflows.verify(VerifyCommand(".", DeviceId("device")))
    reported = workflows.report(ReportCommand(".", RunId("recover")))

    assert observed.run_report is OBSERVE_REPORT
    assert observed.run_report.canonical_bytes == OBSERVE_REPORT.canonical_bytes
    assert observed.status is RunStatus.NOOP
    assert verified.run_report is VERIFY_REPORT
    assert verified.status is RunStatus.CONVERGED
    assert reported.run_report is RECOVERY_REPORT
    assert reported.revision == 9
    assert reported.status is RunStatus.FAILED_ROLLED_BACK


def test_apply_returns_canonical_terminal_report_and_separate_cleanup_truth() -> None:
    workflows = _concrete_workflows(
        PlanOutcome(
            RunId("planning"),
            PlanId("plan"),
            "actionable",
            PLAN,
            PLANNING_REPORT,
        )
    )

    outcome = workflows.apply(ApplyCommand(".", PlanId("plan"), ()))

    assert outcome.run_report is EXECUTION_REPORT
    assert outcome.run_report.canonical_bytes == EXECUTION_REPORT.canonical_bytes
    assert outcome.status is RunStatus.CONVERGED
    assert outcome.cleanup_complete is False


def test_reconcile_preserves_awaiting_approval_plan_and_run_documents() -> None:
    planned = PlanOutcome(
        RunId("planning"),
        PlanId("plan"),
        "actionable",
        PLAN,
        PLANNING_REPORT,
    )
    workflows = _concrete_workflows(planned)

    outcome = workflows.reconcile(ReconcileCommand(".", DeviceId("device"), ()))

    assert outcome.plan is PLAN
    assert outcome.planning_run_report is PLANNING_REPORT
    assert outcome.execution_run_report is EXECUTION_REPORT
    assert outcome.run_report is EXECUTION_REPORT
    assert outcome.cleanup_complete is False


def test_reconcile_without_execution_returns_the_planning_run_document() -> None:
    noop_report = _report("planning", RunStatus.NOOP, revision=2)
    workflows = _concrete_workflows(
        PlanOutcome(RunId("planning"), PlanId("plan"), "noop", PLAN, noop_report)
    )

    outcome = workflows.reconcile(ReconcileCommand(".", DeviceId("device"), ()))

    assert outcome.run_report is noop_report
    assert outcome.execution_run_report is None
    assert outcome.cleanup_complete is None


def test_reconcile_rejects_a_missing_canonical_planning_run_document() -> None:
    workflows = _concrete_workflows(
        PlanOutcome(RunId("planning"), None, "blocked", None, None)
    )

    with pytest.raises(
        RuntimeError,
        match="planning workflow omitted its canonical Run Report",
    ):
        workflows.reconcile(ReconcileCommand(".", DeviceId("device"), ()))


def test_recovery_inspect_preserves_exact_computed_actions_and_current_report() -> None:
    actions = (
        AllowedRecoveryAction(
            RecoveryActionCode.INSPECT,
            None,
            True,
            "recovery.inspect",
            False,
            False,
        ),
        AllowedRecoveryAction(
            RecoveryActionCode.FINALIZE,
            FinalizeMode.ABANDON,
            True,
            "recovery.abandon",
            True,
            True,
        ),
    )
    workflows = _concrete_workflows(
        PlanOutcome(
            RunId("planning"),
            PlanId("plan"),
            "actionable",
            PLAN,
            PLANNING_REPORT,
        ),
        actions,
    )

    outcome = workflows.recover(
        RecoverCommand(".", RunId("recover"), RecoveryActionCode.INSPECT.value)
    )

    assert isinstance(outcome, RecoveryInspectionOutcome)
    assert outcome.run_report is RECOVERY_REPORT
    assert outcome.actions is actions
    assert outcome.cleanup_complete is False
    assert outcome.status is RunStatus.FAILED_ROLLED_BACK


def test_non_inspect_recovery_returns_current_report_and_cleanup_truth() -> None:
    workflows = _concrete_workflows(
        PlanOutcome(
            RunId("planning"),
            PlanId("plan"),
            "actionable",
            PLAN,
            PLANNING_REPORT,
        )
    )

    outcome = workflows.recover(
        RecoverCommand(".", RunId("recover"), RecoveryActionCode.ROLLBACK.value)
    )

    assert isinstance(outcome, RecoverOutcome)
    assert outcome.run_report is RECOVERY_REPORT
    assert outcome.status is RunStatus.FAILED_ROLLED_BACK
    assert outcome.cleanup_complete is False


def test_inventory_and_action_remain_typed_not_implemented() -> None:
    app = _application()
    expected = UnsupportedReason.NOT_IMPLEMENTED

    inventory = app.execute(InventoryCommand("."))
    action = app.execute(ActionCommand(".", "guided"))

    assert isinstance(inventory, UnsupportedOutcome)
    assert inventory.reason is expected
    assert isinstance(action, UnsupportedOutcome)
    assert action.reason is expected
