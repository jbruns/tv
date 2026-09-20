"""Production composition root for the Reconciler."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from coreelec_reconciler.application.commands import (
    ObserveCommand,
    PlanCommand,
    ReportCommand,
    ValidateCommand,
    VerifyCommand,
)
from coreelec_reconciler.application.outcomes import (
    ApprovalResolution,
    ObservationOutcome,
    PlanOutcome,
    ReportOutcome,
    UnsupportedOutcome,
    UnsupportedReason,
    ValidationOutcome,
    VerifyOutcome,
)
from coreelec_reconciler.application.reconciler import (
    ApplicationDependencies,
    ApplicationReconciler,
    CapabilityUnavailableError,
    ExecutionApplicationWorkflows,
    Reconciler,
)
from coreelec_reconciler.domain.execution import (
    FinalizeMode,
    RunStatus,
    StoredRevision,
)
from coreelec_reconciler.domain.identifiers import (
    PlanId,
    RunId,
    SelectorId,
)
from coreelec_reconciler.domain.planning import CanonicalPlan
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    ExecutionEngine,
    ExecutionOutcome,
)
from coreelec_reconciler.inventory.ledger import validate_ledger
from coreelec_reconciler.reporting.canonical_json import decode_json_object

if TYPE_CHECKING:
    from coreelec_reconciler.domain.configuration import ResolvedDevice
    from coreelec_reconciler.execution.recovery import RecoveryInspection
    from coreelec_reconciler.execution.run_store import RunStore
    from coreelec_reconciler.resource_types.descriptor import (
        ManagedFileExecutionResult,
    )
    from coreelec_reconciler.transports.interfaces import DeviceSession


@dataclass(frozen=True, slots=True)
class BootstrapSettings:
    repository_root: str
    state_root: str | None = None
    environment_secret_names: tuple[tuple[str, str], ...] = ()
    pinned_host_keys: tuple[tuple[str, str], ...] = ()


@dataclass(slots=True)
class ProductionServices:
    """Lazy production Adapter access owned exclusively by the composition root."""

    settings: BootstrapSettings
    environment: Mapping[str, str]
    _store: RunStore | None = None

    def open_device_session(
        self,
        device: ResolvedDevice,
        required_capabilities: frozenset[str],
    ) -> DeviceSession:
        from coreelec_reconciler.adapters.paramiko_session import (
            ParamikoSessionFactory,
        )
        from coreelec_reconciler.adapters.secrets import (
            EnvironmentSecretResolver,
            MappingHostKeyResolver,
        )
        from coreelec_reconciler.config.device import (
            resolve_device_session_parameters,
        )

        secrets = EnvironmentSecretResolver(
            dict(self.settings.environment_secret_names), self.environment
        )
        parameters = resolve_device_session_parameters(device, secrets)
        sessions = ParamikoSessionFactory(
            MappingHostKeyResolver(dict(self.settings.pinned_host_keys))
        )
        return sessions.open(parameters, required_capabilities)

    def run_store(self) -> RunStore:
        from coreelec_reconciler.execution.run_store import RunStore

        if self._store is not None:
            return self._store
        configured = self.settings.state_root
        root = (
            Path(configured)
            if configured is not None
            else Path.home() / ".local" / "state" / "coreelec-reconciler"
        )
        self._store = RunStore(root)
        return self._store

    def state_root_exists(self) -> bool:
        configured = self.settings.state_root
        root = (
            Path(configured)
            if configured is not None
            else Path.home() / ".local" / "state" / "coreelec-reconciler"
        )
        return root.is_dir()


class _ProductionApplicationData:
    def __init__(
        self,
        services: ProductionServices,
        plan_repository: Callable[[PlanCommand], PlanOutcome],
    ) -> None:
        self._services = services
        self._plan_repository = plan_repository

    def observe(
        self, command: ObserveCommand
    ) -> ObservationOutcome | UnsupportedOutcome:
        del command
        return _unavailable("observe", "production.device-session-unavailable")

    def plan(self, command: PlanCommand) -> PlanOutcome:
        return self._plan_repository(command)

    def approved_plan(
        self, plan_id: PlanId, approval_scopes: tuple[str, ...]
    ) -> ApprovedPlan | UnsupportedOutcome:
        del plan_id, approval_scopes
        return _unavailable("apply", "production.approved-plan-unavailable")

    def resolve_approval(
        self,
        plan: CanonicalPlan,
        approval_scopes: tuple[str, ...],
    ) -> ApprovalResolution:
        value = decode_json_object(plan.canonical_bytes)
        requirements = value.get("approval_requirements")
        required = (
            tuple(
                str(item["scope"])
                for item in requirements
                if isinstance(item, dict) and isinstance(item.get("scope"), str)
            )
            if isinstance(requirements, list)
            else ()
        )
        granted = tuple(scope for scope in approval_scopes if scope in required)
        return ApprovalResolution(
            required,
            granted,
            tuple(scope for scope in required if scope not in granted),
        )

    def verify(self, command: VerifyCommand) -> VerifyOutcome | UnsupportedOutcome:
        del command
        return _unavailable("verify", "production.device-session-unavailable")

    def report(self, command: ReportCommand) -> ReportOutcome | UnsupportedOutcome:
        if not self._services.state_root_exists():
            return _unavailable("report", "production.run-not-found")
        from coreelec_reconciler.execution.run_store import RunStoreError
        from coreelec_reconciler.reporting.execution_documents import (
            decode_execution_run_report,
        )

        try:
            chain = self._services.run_store().load_chain(command.run_id)
            return ReportOutcome(decode_execution_run_report(chain.head.payload))
        except FileNotFoundError, RunStoreError, ValueError:
            return _unavailable("report", "production.run-unavailable")


class _ProductionExecutionJournal:
    def __init__(self, services: ProductionServices) -> None:
        self._services = services

    def start(self, plan: ApprovedPlan) -> None:
        del plan
        raise CapabilityUnavailableError(
            "apply", "production.execution-journal-unavailable"
        )

    def prepared(self, run_id: RunId, resource_id: str, prepared: object) -> None:
        del run_id, resource_id, prepared
        self._unavailable()

    def result(
        self,
        run_id: RunId,
        resource_id: str,
        result: ManagedFileExecutionResult,
    ) -> None:
        del run_id, resource_id, result
        self._unavailable()

    def terminal(self, run_id: RunId, status: RunStatus) -> StoredRevision:
        del run_id, status
        self._unavailable()

    def cleanup(self, run_id: RunId, resource_id: str, result: object) -> None:
        del run_id, resource_id, result
        self._unavailable()

    def skipped(
        self, run_id: RunId, resource_id: str, dependency_ids: tuple[str, ...]
    ) -> None:
        del run_id, resource_id, dependency_ids
        self._unavailable()

    @staticmethod
    def _unavailable() -> NoReturn:
        raise CapabilityUnavailableError(
            "apply", "production.execution-journal-unavailable"
        )


class _ProductionRecoveryDriver:
    def __init__(self, services: ProductionServices) -> None:
        self._services = services

    def inspect(self, run_id: RunId) -> RecoveryInspection:
        if not self._services.state_root_exists():
            raise CapabilityUnavailableError("recover", "production.run-not-found")
        try:
            self._services.run_store().load_chain(run_id)
        except FileNotFoundError:
            raise CapabilityUnavailableError(
                "recover", "production.run-not-found"
            ) from None
        raise CapabilityUnavailableError(
            "recover", "production.recovery-binding-unavailable"
        )

    def resume_verification(self, run_id: RunId) -> ExecutionOutcome:
        del run_id
        raise CapabilityUnavailableError("recover", "production.run-unavailable")

    def rollback(self, run_id: RunId) -> ExecutionOutcome:
        del run_id
        raise CapabilityUnavailableError("recover", "production.run-unavailable")

    def finalize(
        self,
        run_id: RunId,
        mode: FinalizeMode,
        *,
        approval: str | None,
        reason: str | None,
    ) -> ExecutionOutcome:
        del run_id, mode, approval, reason
        raise CapabilityUnavailableError("recover", "production.run-unavailable")


def _unavailable(command: str, code: str) -> UnsupportedOutcome:
    return UnsupportedOutcome(command, UnsupportedReason.CAPABILITY_UNAVAILABLE, code)


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

    services = ProductionServices(settings, os.environ)
    data = _ProductionApplicationData(services, plan_repository)
    engine = ExecutionEngine(
        _ProductionExecutionJournal(services),
        _ProductionRecoveryDriver(services),
    )
    return ApplicationReconciler(
        dependencies=ApplicationDependencies(
            ExecutionApplicationWorkflows(data, engine),
            validate_repository,
            plan_repository,
        ),
    )
