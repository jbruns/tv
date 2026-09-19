"""Production composition root for the Reconciler."""

from dataclasses import dataclass
from pathlib import Path

from coreelec_reconciler.application.outcomes import ValidationOutcome
from coreelec_reconciler.application.reconciler import (
    ApplicationReconciler,
    Reconciler,
)
from coreelec_reconciler.inventory.ledger import validate_ledger


@dataclass(frozen=True, slots=True)
class BootstrapSettings:
    repository_root: str


def bootstrap(settings: BootstrapSettings) -> Reconciler:
    def validate_repository(repository_root: str) -> ValidationOutcome:
        root = repository_root or settings.repository_root
        validation = validate_ledger(Path(root) / "inventory" / "ownership-ledger.json")
        diagnostics = tuple(
            " ".join(
                part
                for part in (
                    diagnostic.code,
                    diagnostic.inventory_id,
                    diagnostic.field,
                    diagnostic.message,
                )
                if part
            )
            for diagnostic in validation.diagnostics
        )
        return ValidationOutcome(
            valid=validation.valid,
            diagnostics=diagnostics,
            row_count=validation.row_count,
            sha256=validation.sha256,
            role_totals=tuple(validation.role_totals.items()),
            disposition_totals=tuple(validation.disposition_totals.items()),
        )

    return ApplicationReconciler(validate_repository)
