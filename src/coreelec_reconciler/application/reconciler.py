"""Single typed application execution boundary."""

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
                name = "validate"
            case InventoryCommand():
                name = "inventory"
            case ObserveCommand():
                name = "observe"
            case PlanCommand():
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
