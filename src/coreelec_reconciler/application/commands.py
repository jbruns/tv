"""Typed commands accepted by the Reconciler."""

from dataclasses import dataclass

from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId

__all__ = [
    "ActionCommand",
    "ApplyCommand",
    "Command",
    "DeviceId",
    "InventoryCommand",
    "ObserveCommand",
    "PlanCommand",
    "PlanId",
    "ReconcileCommand",
    "RecoverCommand",
    "ReportCommand",
    "RunId",
    "ValidateCommand",
    "VerifyCommand",
]


@dataclass(frozen=True, slots=True)
class ValidateCommand:
    repository_root: str
    device_id: DeviceId | None = None
    observations_file: str | None = None


@dataclass(frozen=True, slots=True)
class InventoryCommand:
    repository_root: str


@dataclass(frozen=True, slots=True)
class ObserveCommand:
    repository_root: str
    device_id: DeviceId


@dataclass(frozen=True, slots=True)
class PlanCommand:
    repository_root: str
    device_id: DeviceId
    observations_file: str | None = None


@dataclass(frozen=True, slots=True)
class ApplyCommand:
    repository_root: str
    plan_id: PlanId
    approval_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconcileCommand:
    repository_root: str
    device_id: DeviceId
    approval_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerifyCommand:
    repository_root: str
    device_id: DeviceId


@dataclass(frozen=True, slots=True)
class RecoverCommand:
    repository_root: str
    run_id: RunId
    action: str


@dataclass(frozen=True, slots=True)
class ReportCommand:
    repository_root: str
    run_id: RunId


@dataclass(frozen=True, slots=True)
class ActionCommand:
    repository_root: str
    action_code: str


type Command = (
    ValidateCommand
    | InventoryCommand
    | ObserveCommand
    | PlanCommand
    | ApplyCommand
    | ReconcileCommand
    | VerifyCommand
    | RecoverCommand
    | ReportCommand
    | ActionCommand
)
