"""Production composition root for the Reconciler."""

from dataclasses import dataclass
from pathlib import Path

from coreelec_reconciler.application.commands import PlanCommand, ValidateCommand
from coreelec_reconciler.application.outcomes import PlanOutcome, ValidationOutcome
from coreelec_reconciler.application.reconciler import (
    ApplicationReconciler,
    Reconciler,
)
from coreelec_reconciler.domain.identifiers import PlanId, RunId, SelectorId
from coreelec_reconciler.inventory.ledger import validate_ledger


@dataclass(frozen=True, slots=True)
class BootstrapSettings:
    repository_root: str


def bootstrap(settings: BootstrapSettings) -> Reconciler:
    from coreelec_reconciler.application.supplied_observations import (
        load_supplied_planning_input,
    )
    from coreelec_reconciler.config.load import load_configuration
    from coreelec_reconciler.reporting.planning_documents import build_plan_and_run
    from coreelec_reconciler.resource_types.kodi_smart_playlist.planning import (
        assess_playlist,
    )

    def validate_repository(command: ValidateCommand) -> ValidationOutcome:
        root = command.repository_root or settings.repository_root
        validation = validate_ledger(Path(root) / "inventory" / "ownership-ledger.json")
        diagnostics = [
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
        ]
        if command.device_id is not None:
            loaded = load_configuration(
                root,
                command.device_id,
                (SelectorId("selector.skin"),),
            )
            diagnostics.extend(
                f"{item.code} {item.source} {item.message}"
                for item in loaded.diagnostics
            )
            if command.observations_file is None:
                diagnostics.append(
                    "observation.missing supplied observations are required"
                )
            else:
                try:
                    supplied = load_supplied_planning_input(command.observations_file)
                except ValueError as error:
                    diagnostics.append(f"observation.invalid {error}")
                else:
                    if loaded.configuration is not None:
                        resource = loaded.configuration.resources[0]
                        if supplied.observation.resource_id != resource.id.value:
                            diagnostics.append(
                                "observation.resource-mismatch supplied Resource ID "
                                "does not match selection"
                            )
                        if (
                            supplied.observation.state_address
                            not in resource.state_addresses
                        ):
                            diagnostics.append(
                                "observation.address-mismatch supplied State Address "
                                "does not match selection"
                            )
        return ValidationOutcome(
            valid=validation.valid and not diagnostics,
            diagnostics=tuple(diagnostics),
            row_count=validation.row_count,
            sha256=validation.sha256,
            role_totals=tuple(validation.role_totals.items()),
            disposition_totals=tuple(validation.disposition_totals.items()),
        )

    def plan_repository(command: PlanCommand) -> PlanOutcome:
        if command.observations_file is None:
            return PlanOutcome(
                run_id=RunId("unavailable"),
                plan_id=None,
                disposition="blocked",
                diagnostics=("observation.missing supplied observations are required",),
            )
        loaded = load_configuration(
            command.repository_root or settings.repository_root,
            command.device_id,
            (SelectorId("selector.skin"),),
        )
        if loaded.configuration is None:
            return PlanOutcome(
                run_id=RunId("unavailable"),
                plan_id=None,
                disposition="blocked",
                diagnostics=tuple(
                    f"{item.code} {item.source} {item.message}"
                    for item in loaded.diagnostics
                ),
            )
        try:
            supplied = load_supplied_planning_input(command.observations_file)
        except ValueError as error:
            return PlanOutcome(
                run_id=RunId("unavailable"),
                plan_id=None,
                disposition="blocked",
                diagnostics=(f"observation.invalid {error}",),
            )
        if len(loaded.configuration.resources) != 1:
            return PlanOutcome(
                run_id=RunId(supplied.runtime.planning_run_id),
                plan_id=None,
                disposition="blocked",
                diagnostics=("selection.invalid expected exactly one Resource",),
            )
        resource = loaded.configuration.resources[0]
        if (
            supplied.observation.resource_id != resource.id.value
            or supplied.observation.state_address not in resource.state_addresses
        ):
            return PlanOutcome(
                run_id=RunId(supplied.runtime.planning_run_id),
                plan_id=None,
                disposition="blocked",
                diagnostics=("observation.binding-mismatch",),
            )
        assessment = assess_playlist(
            resource.intent,
            resource.desired,
            resource.management,
            supplied.observation,
        )
        plan, run = build_plan_and_run(
            loaded.configuration,
            resource,
            supplied,
            assessment,
        )
        return PlanOutcome(
            run_id=RunId(run.run_id),
            plan_id=PlanId(plan.plan_id),
            disposition=plan.disposition.value,
            plan=plan,
            run_report=run,
        )

    return ApplicationReconciler(validate_repository, plan_repository)
