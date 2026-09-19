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
    InventoryResult,
    ObservationOutcome,
    ObserveResult,
    Outcome,
    PlanOutcome,
    PlanResult,
    ReconcileOutcome,
    ReconcileResult,
    RecoverOutcome,
    RecoverResult,
    ReportOutcome,
    ReportResult,
    UnsupportedOutcome,
    UnsupportedReason,
    ValidateResult,
    ValidationOutcome,
    VerifyOutcome,
    VerifyResult,
)
from coreelec_reconciler.domain.execution import FinalizeMode, RecoveryActionCode
from coreelec_reconciler.domain.identifiers import PlanId

if TYPE_CHECKING:
    from coreelec_reconciler.execution.engine import (
        ApprovedPlan,
        ExecutionEngine,
        RecoveryRequest,
    )


class ApplicationWorkflows(Protocol):
    def observe(self, command: ObserveCommand) -> ObservationOutcome: ...

    def apply(self, command: ApplyCommand) -> ApplyOutcome: ...

    def reconcile(self, command: ReconcileCommand) -> ReconcileOutcome: ...

    def verify(self, command: VerifyCommand) -> VerifyOutcome: ...

    def recover(self, command: RecoverCommand) -> RecoverOutcome: ...

    def report(self, command: ReportCommand) -> ReportOutcome: ...


class ApplicationData(Protocol):
    """Typed non-execution services used by the concrete workflows."""

    def observe(self, command: ObserveCommand) -> ObservationOutcome: ...

    def plan(self, command: PlanCommand) -> PlanOutcome: ...

    def approved_plan(
        self, plan_id: PlanId, approval_scopes: tuple[str, ...]
    ) -> ApprovedPlan: ...

    def verify(self, command: VerifyCommand) -> VerifyOutcome: ...

    def report(self, command: ReportCommand) -> ReportOutcome: ...


@final
class ExecutionApplicationWorkflows:
    """Concrete command workflows over the private execution module."""

    def __init__(self, data: ApplicationData, engine: ExecutionEngine) -> None:
        self._data = data
        self._engine = engine

    def observe(self, command: ObserveCommand) -> ObservationOutcome:
        return self._data.observe(command)

    def apply(self, command: ApplyCommand) -> ApplyOutcome:
        plan = self._data.approved_plan(command.plan_id, command.approval_scopes)
        result = self._engine.start(plan)
        return ApplyOutcome(result.run_id, result.status.value)

    def reconcile(self, command: ReconcileCommand) -> ReconcileOutcome:
        planned = self._data.plan(
            PlanCommand(command.repository_root, command.device_id)
        )
        if planned.plan_id is None or planned.disposition != "actionable":
            return ReconcileOutcome(planned.run_id, None, planned.disposition)
        plan = self._data.approved_plan(planned.plan_id, command.approval_scopes)
        result = self._engine.start(plan)
        return ReconcileOutcome(planned.run_id, result.run_id, result.status.value)

    def verify(self, command: VerifyCommand) -> VerifyOutcome:
        return self._data.verify(command)

    def recover(self, command: RecoverCommand) -> RecoverOutcome:
        request = _recovery_request(command)
        if request.action is RecoveryActionCode.INSPECT:
            self._engine.inspect(command.run_id)
            return RecoverOutcome(command.run_id, "inspected")
        result = self._engine.recover(command.run_id, request)
        return RecoverOutcome(result.run_id, result.status.value)

    def report(self, command: ReportCommand) -> ReportOutcome:
        return self._data.report(command)


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    """Explicit application wiring; presentation code receives one dependency set."""

    workflows: ApplicationWorkflows
    validate_repository: Callable[[ValidateCommand], ValidationOutcome]
    plan_repository: Callable[[PlanCommand], PlanResult]


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
        plan_repository: Callable[[PlanCommand], PlanResult] | None = None,
        *,
        dependencies: ApplicationDependencies | None = None,
    ) -> None:
        self._dependencies = dependencies
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
                if self._dependencies is not None:
                    return self._dependencies.workflows.observe(command)
                name = "observe"
            case PlanCommand():
                if self._plan_repository is not None:
                    return self._plan_repository(command)
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
