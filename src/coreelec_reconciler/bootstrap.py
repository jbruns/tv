"""Production composition root for the Reconciler."""

from dataclasses import dataclass

from coreelec_reconciler.application.reconciler import (
    ApplicationReconciler,
    Reconciler,
)


@dataclass(frozen=True, slots=True)
class BootstrapSettings:
    repository_root: str


def bootstrap(settings: BootstrapSettings) -> Reconciler:
    del settings
    return ApplicationReconciler()
