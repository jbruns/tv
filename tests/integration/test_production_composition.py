from pathlib import Path

from coreelec_reconciler.application.commands import InventoryCommand
from coreelec_reconciler.application.outcomes import UnsupportedOutcome
from coreelec_reconciler.application.reconciler import ApplicationReconciler
from coreelec_reconciler.bootstrap import (
    BootstrapSettings,
    ProductionServices,
    bootstrap,
)


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
    assert isinstance(application.production_services, ProductionServices)
    assert not (tmp_path / "state").exists()
    outcome = application.execute(InventoryCommand(str(tmp_path)))
    assert isinstance(outcome, UnsupportedOutcome)
    assert not (tmp_path / "state").exists()
