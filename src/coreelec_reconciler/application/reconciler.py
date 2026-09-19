"""Single typed application execution boundary."""

from collections.abc import Callable
from typing import Protocol, assert_never, final, overload

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
    ApplyResult,
    InventoryResult,
    ObserveResult,
    Outcome,
    PlanResult,
    ReconcileResult,
    RecoverResult,
    ReportResult,
    UnsupportedOutcome,
    UnsupportedReason,
    ValidateResult,
    ValidationOutcome,
    VerifyResult,
)


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
    ) -> None:
        self._validate_repository = validate_repository
        self._plan_repository = plan_repository

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
                name = "observe"
            case PlanCommand():
                if self._plan_repository is not None:
                    return self._plan_repository(command)
                name = "plan"
            case ApplyCommand():
                name = "apply"
            case ReconcileCommand():
                name = "reconcile"
            case VerifyCommand():
                name = "verify"
            case RecoverCommand():
                name = "recover"
            case ReportCommand():
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
