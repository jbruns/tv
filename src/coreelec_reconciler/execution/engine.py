"""Private execution module owning start, inspection, and recovery scheduling."""

from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    FinalizeMode,
    MutationDisposition,
    MutationTrace,
    RecoveryActionCode,
    RunStatus,
)
from coreelec_reconciler.domain.identifiers import RunId
from coreelec_reconciler.execution.managed_file import ManagedFileExecutionResult
from coreelec_reconciler.execution.progress import PresentationDiagnostic, Progress
from coreelec_reconciler.execution.recovery import RecoveryInspection


class ExecutableChange(Protocol):
    @property
    def resource_id(self) -> str: ...

    def prepare(self) -> object: ...

    def apply(self, prepared: object) -> ManagedFileExecutionResult: ...

    def cleanup(self, prepared: object) -> object: ...


@dataclass(frozen=True, slots=True)
class ApprovedPlan:
    run_id: RunId
    changes: tuple[ExecutableChange, ...]


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    action: RecoveryActionCode
    finalize_mode: FinalizeMode | None = None
    approval: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    run_id: RunId
    status: RunStatus
    resource_results: tuple[ManagedFileExecutionResult, ...]
    cleanup_complete: bool
    diagnostics: tuple[PresentationDiagnostic, ...] = ()


class ExecutionJournal(Protocol):
    """Durable canonical evidence writer; all methods complete before returning."""

    def start(self, plan: ApprovedPlan) -> None: ...

    def prepared(self, run_id: RunId, resource_id: str, prepared: object) -> None: ...

    def result(
        self,
        run_id: RunId,
        resource_id: str,
        result: ManagedFileExecutionResult,
    ) -> None: ...

    def terminal(self, run_id: RunId, status: RunStatus) -> None: ...

    def cleanup(self, run_id: RunId, resource_id: str, result: object) -> None: ...


class RecoveryDriver(Protocol):
    def inspect(self, run_id: RunId) -> RecoveryInspection: ...

    def resume_verification(self, run_id: RunId) -> ExecutionOutcome: ...

    def rollback(self, run_id: RunId) -> ExecutionOutcome: ...

    def finalize(
        self,
        run_id: RunId,
        mode: FinalizeMode,
        *,
        approval: str | None,
        reason: str | None,
    ) -> ExecutionOutcome: ...


class ExecutionEngine:
    """The only scheduler for mutating execution and recovery."""

    def __init__(
        self,
        journal: ExecutionJournal,
        recovery: RecoveryDriver,
        progress: Progress | None = None,
    ) -> None:
        self._journal = journal
        self._recovery = recovery
        self._progress = progress or Progress()

    def start(self, approved_plan: ApprovedPlan) -> ExecutionOutcome:
        self._journal.start(approved_plan)
        self._progress.emit("execution.started", approved_plan.run_id.value)
        results: list[ManagedFileExecutionResult] = []
        prepared_changes: list[tuple[ExecutableChange, object]] = []
        status = RunStatus.CONVERGED
        for change in approved_plan.changes:
            prepared = change.prepare()
            self._journal.prepared(approved_plan.run_id, change.resource_id, prepared)
            prepared_changes.append((change, prepared))
            result = change.apply(prepared)
            self._journal.result(approved_plan.run_id, change.resource_id, result)
            results.append(result)
            self._progress.emit(
                "resource.verified",
                approved_plan.run_id.value,
                resource_id=change.resource_id,
            )
            if result.recovery_required:
                status = RunStatus.FAILED_RECOVERY_REQUIRED
                break
            if not result.converged:
                status = (
                    RunStatus.FAILED_ROLLED_BACK
                    if result.rollback_verification is not None
                    and result.rollback_verification.status.value == "matched"
                    else RunStatus.FAILED_PARTIAL
                )
                break

        self._journal.terminal(approved_plan.run_id, status)
        self._progress.emit("execution.terminal", approved_plan.run_id.value)
        cleanup_complete = True
        for change, prepared in prepared_changes:
            try:
                cleanup = change.cleanup(prepared)
                self._journal.cleanup(approved_plan.run_id, change.resource_id, cleanup)
                if isinstance(cleanup, MutationTrace) and any(
                    receipt.disposition is not MutationDisposition.APPLIED
                    for receipt in cleanup.receipts
                ):
                    cleanup_complete = False
            except Exception:
                cleanup_complete = False
        return ExecutionOutcome(
            approved_plan.run_id,
            status,
            tuple(results),
            cleanup_complete,
            self._progress.diagnostics,
        )

    def inspect(self, run_id: RunId) -> RecoveryInspection:
        return self._recovery.inspect(run_id)

    def recover(
        self, run_id: RunId, allowed_action: RecoveryRequest
    ) -> ExecutionOutcome:
        inspection = self.inspect(run_id)
        action = _find_allowed(inspection.actions, allowed_action)
        if action is None or not action.allowed:
            raise ValueError("recovery action is not allowed by the stable inspection")
        if action.requires_approval and not allowed_action.approval:
            raise ValueError("recovery action requires separate approval")
        if action.requires_reason and not allowed_action.reason:
            raise ValueError("recovery action requires a non-empty reason")
        match allowed_action.action:
            case RecoveryActionCode.RESUME_VERIFICATION:
                return self._recovery.resume_verification(run_id)
            case RecoveryActionCode.ROLLBACK:
                return self._recovery.rollback(run_id)
            case RecoveryActionCode.FINALIZE:
                if allowed_action.finalize_mode is None:
                    raise ValueError("finalize requires a mode")
                return self._recovery.finalize(
                    run_id,
                    allowed_action.finalize_mode,
                    approval=allowed_action.approval,
                    reason=allowed_action.reason,
                )
            case RecoveryActionCode.INSPECT:
                raise ValueError("inspect is read-only and is not a recovery mutation")


def _find_allowed(
    actions: tuple[AllowedRecoveryAction, ...], request: RecoveryRequest
) -> AllowedRecoveryAction | None:
    return next(
        (
            action
            for action in actions
            if action.code is request.action
            and action.finalize_mode is request.finalize_mode
        ),
        None,
    )
