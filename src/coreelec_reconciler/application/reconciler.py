"""Single typed application execution boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, assert_never, final, overload

from coreelec_reconciler.application.commands import (
    ActionCommand,
    ApplyCommand,
    Command,
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
    ApprovalResolution,
    CanonicalPlanOutcome,
    InventoryResult,
    ObservationOutcome,
    ObserveResult,
    Outcome,
    PlanningFailureOutcome,
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
from coreelec_reconciler.domain.execution import (
    FinalizeMode,
    RecoveryActionCode,
    RunStatus,
)
from coreelec_reconciler.domain.identifiers import PlanId, RunId
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport

if TYPE_CHECKING:
    from coreelec_reconciler.execution.engine import (
        ApprovedPlan,
        ExecutionEngine,
        RecoveryRequest,
    )


class ApplicationWorkflows(Protocol):
    def apply(self, command: ApplyCommand) -> ApplyOutcome | UnsupportedOutcome: ...

    def reconcile(
        self, command: ReconcileCommand
    ) -> ReconcileOutcome | PlanningFailureOutcome | UnsupportedOutcome: ...

    def verify(self, command: VerifyCommand) -> VerifyOutcome | UnsupportedOutcome: ...

    def recover(
        self, command: RecoverCommand
    ) -> RecoverOutcome | RecoveryInspectionOutcome | UnsupportedOutcome: ...

    def report(self, command: ReportCommand) -> ReportOutcome | UnsupportedOutcome: ...


class ApplicationData(Protocol):
    """Typed non-execution services used by the concrete workflows."""

    def plan(self, command: PlanCommand) -> PlanOutcome | UnsupportedOutcome: ...

    def approved_plan(
        self, plan_id: PlanId, approval_scopes: tuple[str, ...]
    ) -> ApprovedPlan | UnsupportedOutcome: ...

    def resolve_approval(
        self,
        plan: CanonicalPlan,
        approval_scopes: tuple[str, ...],
    ) -> ApprovalResolution: ...

    def verify(self, command: VerifyCommand) -> VerifyOutcome | UnsupportedOutcome: ...

    def report(self, command: ReportCommand) -> ReportOutcome | UnsupportedOutcome: ...


class CapabilityUnavailableError(RuntimeError):
    def __init__(self, command: str, diagnostic_code: str) -> None:
        super().__init__(diagnostic_code)
        self.command = command
        self.diagnostic_code = diagnostic_code


@final
class ExecutionApplicationWorkflows:
    """Concrete command workflows over the private execution module."""

    def __init__(self, data: ApplicationData, engine: ExecutionEngine) -> None:
        self._data = data
        self._engine = engine

    def apply(self, command: ApplyCommand) -> ApplyOutcome | UnsupportedOutcome:
        plan = self._data.approved_plan(command.plan_id, command.approval_scopes)
        if isinstance(plan, UnsupportedOutcome):
            return plan
        try:
            result = self._engine.start(plan)
        except CapabilityUnavailableError as error:
            return _capability_unavailable(error)
        report = self._run_report(command.repository_root, result.run_id)
        if isinstance(report, UnsupportedOutcome):
            return report
        _require_execution_result_binding(result.run_id, result.status, report)
        return ApplyOutcome(report, result.cleanup_complete)

    def reconcile(
        self, command: ReconcileCommand
    ) -> ReconcileOutcome | PlanningFailureOutcome | UnsupportedOutcome:
        plan_outcome = self._data.plan(
            PlanCommand(command.repository_root, command.device_id)
        )
        if isinstance(plan_outcome, UnsupportedOutcome):
            return plan_outcome
        planned = _classify_plan_outcome(plan_outcome)
        if isinstance(planned, PlanningFailureOutcome):
            return planned
        canonical_plan, planning_report = _canonical_planning_documents(planned)
        if planned.disposition != "actionable":
            return ReconcileOutcome(planning_report, canonical_plan, None, None)
        approval = self._data.resolve_approval(canonical_plan, command.approval_scopes)
        if not approval.sufficient:
            return ReconcileOutcome(
                planning_report,
                canonical_plan,
                None,
                None,
                approval,
            )
        approved_plan = self._data.approved_plan(
            planned.plan_id, command.approval_scopes
        )
        if isinstance(approved_plan, UnsupportedOutcome):
            return approved_plan
        try:
            result = self._engine.start(approved_plan)
        except CapabilityUnavailableError as error:
            return _capability_unavailable(error)
        report = self._run_report(command.repository_root, result.run_id)
        if isinstance(report, UnsupportedOutcome):
            return report
        _require_execution_result_binding(result.run_id, result.status, report)
        return ReconcileOutcome(
            planning_report,
            canonical_plan,
            report,
            result.cleanup_complete,
            approval,
        )

    def verify(self, command: VerifyCommand) -> VerifyOutcome | UnsupportedOutcome:
        return self._data.verify(command)

    def recover(
        self, command: RecoverCommand
    ) -> RecoverOutcome | RecoveryInspectionOutcome | UnsupportedOutcome:
        request = _recovery_request(command)
        try:
            if request.action is RecoveryActionCode.INSPECT:
                inspection = self._engine.inspect(command.run_id)
            else:
                result = self._engine.recover(command.run_id, request)
        except CapabilityUnavailableError as error:
            return _capability_unavailable(error)
        if request.action is RecoveryActionCode.INSPECT:
            report = self._run_report(command.repository_root, command.run_id)
            if isinstance(report, UnsupportedOutcome):
                return report
            if inspection.evidence.run_id != command.run_id:
                raise ValueError("recovery inspection does not bind to the Run")
            if report.status is not inspection.evidence.canonical_status:
                raise ValueError(
                    "canonical Run Report does not bind to recovery inspection truth"
                )
            return RecoveryInspectionOutcome(
                report,
                inspection.actions,
                inspection.evidence.cleanup_complete,
            )
        report = self._run_report(command.repository_root, result.run_id)
        if isinstance(report, UnsupportedOutcome):
            return report
        _require_execution_result_binding(result.run_id, result.status, report)
        return RecoverOutcome(report, result.cleanup_complete)

    def report(self, command: ReportCommand) -> ReportOutcome | UnsupportedOutcome:
        outcome = self._data.report(command)
        if isinstance(outcome, UnsupportedOutcome):
            return outcome
        if outcome.run_id != command.run_id:
            raise ValueError("canonical Run Report does not bind to the requested Run")
        return outcome

    def _run_report(
        self, repository_root: str, run_id: RunId
    ) -> CanonicalRunReport | UnsupportedOutcome:
        outcome = self._data.report(ReportCommand(repository_root, run_id))
        if isinstance(outcome, UnsupportedOutcome):
            return outcome
        if outcome.run_id != run_id:
            raise ValueError("canonical Run Report does not bind to the requested Run")
        return outcome.run_report


def _capability_unavailable(error: CapabilityUnavailableError) -> UnsupportedOutcome:
    return UnsupportedOutcome(
        error.command,
        UnsupportedReason.CAPABILITY_UNAVAILABLE,
        error.diagnostic_code,
    )


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    """Explicit application wiring; presentation code receives one dependency set."""

    workflows: ApplicationWorkflows
    validate_repository: Callable[[ValidateCommand], ValidationOutcome]
    plan_repository: Callable[[PlanCommand], PlanOutcome | UnsupportedOutcome]


class Reconciler(Protocol):
    @overload
    def execute(self, command: ValidateCommand) -> ValidateResult: ...

    @overload
    def execute(self, command: InventoryCommand) -> InventoryResult: ...

    @overload
    def execute(self, command: ObserveCommand) -> ObserveResult: ...

    @overload
    def execute(self, command: PlanCommand) -> PlanResult: ...

    @overload
    def execute(self, command: ApplyCommand) -> ApplyResult: ...

    @overload
    def execute(self, command: ReconcileCommand) -> ReconcileResult: ...

    @overload
    def execute(self, command: VerifyCommand) -> VerifyResult: ...

    @overload
    def execute(self, command: RecoverCommand) -> RecoverResult: ...

    @overload
    def execute(self, command: ReportCommand) -> ReportResult: ...

    @overload
    def execute(self, command: ActionCommand) -> ActionResult: ...

    def execute(self, command: Command) -> Outcome: ...


@final
class ApplicationReconciler:
    def __init__(
        self,
        validate_repository: Callable[[ValidateCommand], ValidationOutcome]
        | None = None,
        plan_repository: Callable[[PlanCommand], PlanOutcome | UnsupportedOutcome]
        | None = None,
        *,
        dependencies: ApplicationDependencies | None = None,
        observe_repository: (
            Callable[[ObserveCommand], ObservationOutcome] | None
        ) = None,
    ) -> None:
        self._dependencies = dependencies
        self._observe_repository = observe_repository
        self._validate_repository = (
            dependencies.validate_repository
            if dependencies is not None
            else validate_repository
        )
        self._plan_repository = (
            dependencies.plan_repository
            if dependencies is not None
            else plan_repository
        )

    @overload
    def execute(self, command: ValidateCommand) -> ValidateResult: ...

    @overload
    def execute(self, command: InventoryCommand) -> InventoryResult: ...

    @overload
    def execute(self, command: ObserveCommand) -> ObserveResult: ...

    @overload
    def execute(self, command: PlanCommand) -> PlanResult: ...

    @overload
    def execute(self, command: ApplyCommand) -> ApplyResult: ...

    @overload
    def execute(self, command: ReconcileCommand) -> ReconcileResult: ...

    @overload
    def execute(self, command: VerifyCommand) -> VerifyResult: ...

    @overload
    def execute(self, command: RecoverCommand) -> RecoverResult: ...

    @overload
    def execute(self, command: ReportCommand) -> ReportResult: ...

    @overload
    def execute(self, command: ActionCommand) -> ActionResult: ...

    def execute(self, command: Command) -> Outcome:
        match command:
            case ValidateCommand():
                if self._validate_repository is not None:
                    return self._validate_repository(command)
                name = "validate"
            case InventoryCommand():
                name = "inventory"
            case ObserveCommand():
                if self._observe_repository is not None:
                    return self._observe_repository(command)
                name = "observe"
            case PlanCommand():
                if self._plan_repository is not None:
                    planned = self._plan_repository(command)
                    if isinstance(planned, UnsupportedOutcome):
                        return planned
                    return _classify_plan_outcome(planned)
                name = "plan"
            case ApplyCommand():
                if self._dependencies is not None:
                    return self._dependencies.workflows.apply(command)
                name = "apply"
            case ReconcileCommand():
                if self._dependencies is not None:
                    return self._dependencies.workflows.reconcile(command)
                name = "reconcile"
            case VerifyCommand():
                if self._dependencies is not None:
                    return self._dependencies.workflows.verify(command)
                name = "verify"
            case RecoverCommand():
                if self._dependencies is not None:
                    return self._dependencies.workflows.recover(command)
                name = "recover"
            case ReportCommand():
                if self._dependencies is not None:
                    return self._dependencies.workflows.report(command)
                name = "report"
            case ActionCommand():
                name = "action"
            case _ as unreachable:
                assert_never(unreachable)

        return UnsupportedOutcome(
            command=name,
            reason=UnsupportedReason.NOT_IMPLEMENTED,
            diagnostic_code="application.command-not-implemented",
        )


def _recovery_request(command: RecoverCommand) -> RecoveryRequest:
    from coreelec_reconciler.execution.engine import RecoveryRequest

    parts = command.action.split(":", 1)
    try:
        code = RecoveryActionCode(parts[0])
        mode = FinalizeMode(parts[1]) if len(parts) == 2 else None
    except ValueError as error:
        raise ValueError("unknown recovery action") from error
    if code is RecoveryActionCode.FINALIZE and mode is None:
        raise ValueError("finalize recovery action requires normal or abandon mode")
    if code is not RecoveryActionCode.FINALIZE and mode is not None:
        raise ValueError("only finalize accepts a recovery mode")
    return RecoveryRequest(code, mode, command.approval, command.reason)


def _classify_plan_outcome(
    outcome: PlanOutcome,
) -> CanonicalPlanOutcome | PlanningFailureOutcome:
    if (
        outcome.plan_id is not None
        and outcome.plan is not None
        and outcome.run_report is not None
    ):
        return CanonicalPlanOutcome(
            outcome.run_id,
            outcome.plan_id,
            outcome.disposition,
            outcome.plan,
            outcome.run_report,
            outcome.diagnostics,
        )
    if outcome.plan is None and outcome.run_report is None and outcome.plan_id is None:
        return PlanningFailureOutcome(
            outcome.run_id,
            None,
            outcome.disposition,
            None,
            None,
            outcome.diagnostics,
        )
    raise ValueError("planning outcome has inconsistent canonical documents")


def _canonical_planning_documents(
    outcome: CanonicalPlanOutcome,
) -> tuple[CanonicalPlan, CanonicalRunReport]:
    plan = outcome.plan
    report = outcome.run_report
    if report.run_id != outcome.run_id.value:
        raise ValueError("planning Run Report does not bind to the planning outcome")
    return plan, report


def _require_execution_result_binding(
    run_id: RunId,
    status: RunStatus,
    report: CanonicalRunReport,
) -> None:
    if report.run_id != run_id.value or report.status is not status:
        raise ValueError("canonical Run Report does not bind to execution truth")
