from pathlib import Path

from coreelec_reconciler.application.commands import (
    ApplyCommand,
    ObserveCommand,
    ReconcileCommand,
    RecoverCommand,
    ReportCommand,
    VerifyCommand,
)
from coreelec_reconciler.application.outcomes import (
    PlanningFailureOutcome,
    UnsupportedOutcome,
    UnsupportedReason,
)
from coreelec_reconciler.application.reconciler import (
    ApplicationReconciler,
    ExecutionApplicationWorkflows,
)
from coreelec_reconciler.bootstrap import (
    BootstrapSettings,
    bootstrap,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId


def test_bootstrap_wires_lazy_production_services_without_device_access(
    tmp_path: Path,
) -> None:
    application = bootstrap(
        BootstrapSettings(
            str(tmp_path),
            state_root=str(tmp_path / "state"),
            environment_secret_names=(("ssh-key", "SYNTHETIC_SECRET"),),
            pinned_host_keys=(("host-key", "ssh-ed25519 synthetic"),),
        )
    )

    assert isinstance(application, ApplicationReconciler)
    assert application._dependencies is not None
    assert isinstance(
        application._dependencies.workflows, ExecutionApplicationWorkflows
    )
    assert not (tmp_path / "state").exists()
    outcomes = (
        application.execute(ObserveCommand(str(tmp_path), DeviceId("device.test"))),
        application.execute(ApplyCommand(str(tmp_path), PlanId("plan.test"), ())),
        application.execute(VerifyCommand(str(tmp_path), DeviceId("device.test"))),
        application.execute(
            RecoverCommand(str(tmp_path), RunId("run.test"), "inspect")
        ),
        application.execute(ReportCommand(str(tmp_path), RunId("run.test"))),
    )
    assert all(isinstance(outcome, UnsupportedOutcome) for outcome in outcomes)
    assert all(
        outcome.reason is UnsupportedReason.CAPABILITY_UNAVAILABLE
        for outcome in outcomes
        if isinstance(outcome, UnsupportedOutcome)
    )
    assert all(
        outcome.diagnostic_code != "application.command-not-implemented"
        for outcome in outcomes
        if isinstance(outcome, UnsupportedOutcome)
    )
    reconciled = application.execute(
        ReconcileCommand(str(tmp_path), DeviceId("device.test"), ())
    )
    assert isinstance(reconciled, PlanningFailureOutcome)
    assert not (tmp_path / "state").exists()
