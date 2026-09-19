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
    ApplyOutcome,
    ObservationOutcome,
    PlanOutcome,
    ReconcileOutcome,
    RecoverOutcome,
    ReportOutcome,
    UnsupportedOutcome,
    UnsupportedReason,
    ValidationOutcome,
    VerifyOutcome,
)
from coreelec_reconciler.application.reconciler import (
    ApplicationDependencies,
    ApplicationReconciler,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId


class _Workflows:
    def observe(self, command: ObserveCommand) -> ObservationOutcome:
        return ObservationOutcome(RunId("observe"), 1)

    def apply(self, command: ApplyCommand) -> ApplyOutcome:
        return ApplyOutcome(RunId("apply"), "converged")

    def reconcile(self, command: ReconcileCommand) -> ReconcileOutcome:
        return ReconcileOutcome(RunId("plan"), RunId("execute"), "converged")

    def verify(self, command: VerifyCommand) -> VerifyOutcome:
        return VerifyOutcome(RunId("verify"), "converged")

    def recover(self, command: RecoverCommand) -> RecoverOutcome:
        return RecoverOutcome(command.run_id, "failed_rolled_back")

    def report(self, command: ReportCommand) -> ReportOutcome:
        return ReportOutcome(command.run_id, 7)


def _application() -> ApplicationReconciler:
    return ApplicationReconciler(
        dependencies=ApplicationDependencies(
            _Workflows(),
            lambda command: ValidationOutcome(True, (), 0, "", (), ()),
            lambda command: PlanOutcome(RunId("plan"), PlanId("id"), "noop"),
        )
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


def test_inventory_and_action_remain_typed_not_implemented() -> None:
    app = _application()
    expected = UnsupportedReason.NOT_IMPLEMENTED

    inventory = app.execute(InventoryCommand("."))
    action = app.execute(ActionCommand(".", "guided"))

    assert isinstance(inventory, UnsupportedOutcome)
    assert inventory.reason is expected
    assert isinstance(action, UnsupportedOutcome)
    assert action.reason is expected
