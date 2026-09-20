"""Typed outcomes returned by the Reconciler."""

from dataclasses import dataclass
from enum import StrEnum

from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    RunStatus,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.domain.observation import (
    CanonicalObservationRun,
    ObservationRunStatus,
)
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport


class UnsupportedReason(StrEnum):
    NOT_IMPLEMENTED = "not_implemented"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"


@dataclass(frozen=True, slots=True)
class UnsupportedOutcome:
    command: str
    reason: UnsupportedReason
    diagnostic_code: str


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    valid: bool
    diagnostics: tuple[str, ...]
    row_count: int
    sha256: str
    role_totals: tuple[tuple[str, int], ...]
    disposition_totals: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class InventoryOutcome:
    device_ids: tuple[DeviceId, ...]


@dataclass(frozen=True, slots=True)
class ObservationOutcome:
    run_report: CanonicalObservationRun

    @property
    def run_id(self) -> RunId:
        return RunId(self.run_report.run_id)

    @property
    def report_revision(self) -> int:
        return self.run_report.revision

    @property
    def status(self) -> ObservationRunStatus:
        return self.run_report.status


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    run_id: RunId
    plan_id: PlanId | None
    disposition: str
    plan: CanonicalPlan | None = None
    run_report: CanonicalRunReport | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalPlanOutcome(PlanOutcome):
    """A modeled planning result with canonical Plan and Run documents."""

    plan_id: PlanId
    plan: CanonicalPlan
    run_report: CanonicalRunReport


@dataclass(frozen=True, slots=True)
class PlanningFailureOutcome(PlanOutcome):
    """A failure that occurs before a canonical planning Run exists."""

    plan_id: None
    plan: None
    run_report: None


@dataclass(frozen=True, slots=True)
class ApprovalResolution:
    required_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...]
    missing_scopes: tuple[str, ...]

    @property
    def sufficient(self) -> bool:
        return not self.missing_scopes


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    run_report: CanonicalRunReport
    cleanup_complete: bool

    @property
    def run_id(self) -> RunId:
        return RunId(self.run_report.run_id)

    @property
    def status(self) -> RunStatus:
        return self.run_report.status


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    planning_run_report: CanonicalRunReport
    plan: CanonicalPlan | None
    execution_run_report: CanonicalRunReport | None
    cleanup_complete: bool | None
    approval: ApprovalResolution | None = None

    @property
    def planning_run_id(self) -> RunId:
        return RunId(self.planning_run_report.run_id)

    @property
    def execution_run_id(self) -> RunId | None:
        if self.execution_run_report is None:
            return None
        return RunId(self.execution_run_report.run_id)

    @property
    def run_report(self) -> CanonicalRunReport:
        return self.execution_run_report or self.planning_run_report

    @property
    def status(self) -> RunStatus:
        return self.run_report.status


@dataclass(frozen=True, slots=True)
class VerifyOutcome:
    run_report: CanonicalRunReport

    @property
    def run_id(self) -> RunId:
        return RunId(self.run_report.run_id)

    @property
    def status(self) -> RunStatus:
        return self.run_report.status


@dataclass(frozen=True, slots=True)
class RecoverOutcome:
    run_report: CanonicalRunReport
    cleanup_complete: bool

    @property
    def run_id(self) -> RunId:
        return RunId(self.run_report.run_id)

    @property
    def status(self) -> RunStatus:
        return self.run_report.status


@dataclass(frozen=True, slots=True)
class RecoveryInspectionOutcome:
    run_report: CanonicalRunReport
    actions: tuple[AllowedRecoveryAction, ...]
    cleanup_complete: bool

    @property
    def run_id(self) -> RunId:
        return RunId(self.run_report.run_id)

    @property
    def status(self) -> RunStatus:
        return self.run_report.status


@dataclass(frozen=True, slots=True)
class ReportOutcome:
    run_report: CanonicalRunReport | CanonicalObservationRun

    @property
    def run_id(self) -> RunId:
        return RunId(self.run_report.run_id)

    @property
    def revision(self) -> int:
        return self.run_report.revision

    @property
    def status(self) -> RunStatus | ObservationRunStatus:
        return self.run_report.status


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action_code: str
    status: str


type ValidateResult = ValidationOutcome | UnsupportedOutcome
type InventoryResult = InventoryOutcome | UnsupportedOutcome
type ObserveResult = ObservationOutcome | UnsupportedOutcome
type PlanResult = CanonicalPlanOutcome | PlanningFailureOutcome | UnsupportedOutcome
type ApplyResult = ApplyOutcome | UnsupportedOutcome
type ReconcileResult = ReconcileOutcome | PlanningFailureOutcome | UnsupportedOutcome
type VerifyResult = VerifyOutcome | UnsupportedOutcome
type RecoverResult = RecoverOutcome | RecoveryInspectionOutcome | UnsupportedOutcome
type ReportResult = ReportOutcome | UnsupportedOutcome
type ActionResult = ActionOutcome | UnsupportedOutcome
type Outcome = (
    ValidateResult
    | InventoryResult
    | ObserveResult
    | PlanResult
    | ApplyResult
    | ReconcileResult
    | VerifyResult
    | RecoverResult
    | ReportResult
    | ActionResult
)
