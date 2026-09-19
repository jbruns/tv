from coreelec_reconciler.application.commands import ValidateCommand
from coreelec_reconciler.application.outcomes import (
    UnsupportedOutcome,
    UnsupportedReason,
)
from coreelec_reconciler.application.reconciler import ApplicationReconciler


def test_unimplemented_command_returns_typed_outcome() -> None:
    outcome = ApplicationReconciler().execute(
        ValidateCommand(repository_root="/repository")
    )

    assert outcome == UnsupportedOutcome(
        command="validate",
        reason=UnsupportedReason.NOT_IMPLEMENTED,
        diagnostic_code="application.command-not-implemented",
    )
