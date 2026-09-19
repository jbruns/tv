"""Typed outcomes returned by the Reconciler."""

from dataclasses import dataclass
from enum import StrEnum

from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId


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
    run_id: RunId
    report_revision: int


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    run_id: RunId
    plan_id: PlanId | None
    disposition: str


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    run_id: RunId
    status: str


@dataclass(frozen=True, slots=True)
class ReconcileOutcome:
    planning_run_id: RunId
    execution_run_id: RunId | None
    status: str


@dataclass(frozen=True, slots=True)
class VerifyOutcome:
    run_id: RunId
    status: str


@dataclass(frozen=True, slots=True)
class RecoverOutcome:
    run_id: RunId
    status: str


@dataclass(frozen=True, slots=True)
class ReportOutcome:
    run_id: RunId
    revision: int


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    action_code: str
    status: str


type ValidateResult = ValidationOutcome | UnsupportedOutcome
type InventoryResult = InventoryOutcome | UnsupportedOutcome
type ObserveResult = ObservationOutcome | UnsupportedOutcome
type PlanResult = PlanOutcome | UnsupportedOutcome
type ApplyResult = ApplyOutcome | UnsupportedOutcome
type ReconcileResult = ReconcileOutcome | UnsupportedOutcome
type VerifyResult = VerifyOutcome | UnsupportedOutcome
type RecoverResult = RecoverOutcome | UnsupportedOutcome
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
