"""Private execution module owning start, inspection, and recovery scheduling."""

from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    FinalizeMode,
    MutationDisposition,
    MutationReceipt,
    MutationTrace,
    RecoveryActionCode,
    RecoveryEvidence,
    RemoteMarkerPhase,
    RunStatus,
    SealIntent,
    StateRelation,
    StoredRevision,
    VerifiedRunChain,
)
from coreelec_reconciler.domain.identifiers import RunId
from coreelec_reconciler.domain.planning import DesiredRelation
from coreelec_reconciler.execution.authority import (
    AcquiredAuthority,
    AuthorityCoordinator,
)
from coreelec_reconciler.execution.progress import PresentationDiagnostic, Progress
from coreelec_reconciler.execution.recovery import (
    RecoveryInspection,
    RecoveryInspectorPort,
    inspect_recovery,
)
from coreelec_reconciler.resource_types.descriptor import (
    ErasedResourceExecution,
    ManagedFileExecutionResult,
    ManagedFileVerification,
    ManagedFileVerificationStatus,
)


class ExecutableChange(Protocol):
    @property
    def resource_id(self) -> str: ...

    @property
    def requires(self) -> tuple[str, ...]: ...

    @property
    def disruptive(self) -> bool: ...

    def prepare(self) -> object: ...

    def apply(self, prepared: object) -> ManagedFileExecutionResult: ...

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object: ...


@dataclass(frozen=True, slots=True)
class BoundExecutableChange:
    """Private adapter that erases one typed Resource only at engine entry."""

    resource_id: str
    requires: tuple[str, ...]
    disruptive: bool
    runtime: ErasedResourceExecution
    change: object

    def prepare(self) -> object:
        return self.runtime.prepare(self.change)

    def apply(self, prepared: object) -> ManagedFileExecutionResult:
        result = self.runtime.apply(prepared)
        if not isinstance(result, ManagedFileExecutionResult):
            raise TypeError("Resource execution returned an invalid result")
        return result

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object:
        return self.runtime.cleanup(prepared, terminal_evidence_ref)


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

    def terminal(self, run_id: RunId, status: RunStatus) -> StoredRevision: ...

    def cleanup(self, run_id: RunId, resource_id: str, result: object) -> None: ...

    def skipped(
        self, run_id: RunId, resource_id: str, dependency_ids: tuple[str, ...]
    ) -> None: ...


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


class ExecutionFinalizer(Protocol):
    def finish(
        self,
        run_id: RunId,
        terminal: StoredRevision,
        cleanup_complete: bool,
    ) -> None: ...


class RecoveryResource(Protocol):
    """Erased recovery view: fresh observe plus the Resource's pure assessment."""

    @property
    def resource_id(self) -> str: ...

    def observe(self) -> object: ...

    def assess(self, observation: object) -> object: ...

    def rollback(
        self,
    ) -> tuple[MutationTrace | None, ManagedFileVerification]: ...

    def cleanup(self, terminal_evidence_ref: str) -> MutationTrace: ...


@dataclass(frozen=True, slots=True)
class BoundRecoveryResource:
    """Recovery adapter over a decoded typed prepared Resource value."""

    runtime: ErasedResourceExecution
    prepared: object
    resource_id: str

    def observe(self) -> object:
        return self.runtime.observe()

    def assess(self, observation: object) -> object:
        return self.runtime.assess(observation)

    def rollback(
        self,
    ) -> tuple[MutationTrace | None, ManagedFileVerification]:
        value = self.runtime.rollback(self.prepared)
        if not isinstance(value, tuple) or len(value) != 2:
            raise TypeError("Resource rollback returned an invalid result")
        trace, verification = value
        if trace is not None and not isinstance(trace, MutationTrace):
            raise TypeError("Resource rollback trace is invalid")
        if not isinstance(verification, ManagedFileVerification):
            raise TypeError("Resource rollback Verification is invalid")
        return trace, verification

    def cleanup(self, terminal_evidence_ref: str) -> MutationTrace:
        value = self.runtime.cleanup(self.prepared, terminal_evidence_ref)
        if not isinstance(value, MutationTrace):
            raise TypeError("Resource cleanup trace is invalid")
        return value


class RecoveryPersistence(Protocol):
    """Existing M3.1 evidence operations consumed by recovery."""

    def load_chain(self, run_id: RunId) -> VerifiedRunChain: ...

    def inspection_port(self, run_id: RunId) -> RecoveryInspectorPort: ...

    def resources(self, run_id: RunId) -> tuple[RecoveryResource, ...]: ...

    def record_verification(
        self,
        run_id: RunId,
        resource_id: str,
        observation: object,
        assessment: object,
    ) -> StoredRevision: ...

    def record_rollback(
        self,
        run_id: RunId,
        resource_id: str,
        trace: MutationTrace | None,
        verification: ManagedFileVerification,
    ) -> StoredRevision: ...

    def record_terminal(self, run_id: RunId, status: RunStatus) -> StoredRevision: ...

    def record_abandonment(
        self, run_id: RunId, *, approval: str, reason: str
    ) -> StoredRevision: ...

    def record_cleanup(
        self, run_id: RunId, resource_id: str, trace: MutationTrace
    ) -> str: ...

    def seal(self, run_id: RunId, intent: SealIntent) -> None: ...


class RecoveryAuthority(Protocol):
    """Bound M3.2 authority operations; no takeover or arbitrary marker access."""

    def release(self, run_id: RunId, terminal_digest: str) -> MutationReceipt: ...

    def quarantine(
        self,
        run_id: RunId,
        incident_digest: str,
        *,
        approval: str,
        reason: str,
    ) -> None: ...


class BoundAuthorityStore(Protocol):
    def load(self, run_id: RunId) -> AcquiredAuthority: ...

    def save(self, run_id: RunId, authority: AcquiredAuthority) -> None: ...


class RecoveryClock(Protocol):
    def utc_now(self) -> str: ...


class AuthorityEvidenceJournal(Protocol):
    def record_authority_state(
        self,
        run_id: RunId,
        ownership_state: str,
        *,
        quarantine_receipt_digest: str | None = None,
    ) -> StoredRevision: ...


class M3AuthorityRecovery:
    """Recovery-only adapter over the M3.2 bound authority coordinator."""

    def __init__(
        self,
        coordinator: AuthorityCoordinator,
        authorities: BoundAuthorityStore,
        clock: RecoveryClock,
        evidence: AuthorityEvidenceJournal | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._authorities = authorities
        self._clock = clock
        self._evidence = evidence

    def release(self, run_id: RunId, terminal_digest: str) -> MutationReceipt:
        authority = self._authorities.load(run_id)
        if authority.ownership.phase is not RemoteMarkerPhase.TERMINAL_RELEASE_PENDING:
            authority = self._coordinator.checkpoint(
                authority,
                authority.ownership.phase,
                RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
                terminal_digest,
                updated_at=self._clock.utc_now(),
            )
            self._authorities.save(run_id, authority)
        receipt = self._coordinator.release(authority, terminal_digest)
        if (
            self._evidence is not None
            and receipt.disposition is MutationDisposition.APPLIED
        ):
            self._evidence.record_authority_state(run_id, "released")
        return receipt

    def quarantine(
        self,
        run_id: RunId,
        incident_digest: str,
        *,
        approval: str,
        reason: str,
    ) -> None:
        del approval, reason
        authority = self._authorities.load(run_id)
        if authority.ownership.phase is not RemoteMarkerPhase.QUARANTINE_PENDING:
            authority = self._coordinator.checkpoint(
                authority,
                authority.ownership.phase,
                RemoteMarkerPhase.QUARANTINE_PENDING,
                incident_digest,
                updated_at=self._clock.utc_now(),
            )
            self._authorities.save(run_id, authority)
        quarantine = self._coordinator.quarantine(
            authority,
            incident_digest,
            updated_at=self._clock.utc_now(),
        )
        if self._evidence is not None:
            self._evidence.record_authority_state(
                run_id,
                "quarantined",
                quarantine_receipt_digest=quarantine.incident_receipt_digest,
            )


class RecoveryCoordinator:
    """Concrete recovery lifecycle over persisted evidence and bound authority."""

    def __init__(
        self,
        persistence: RecoveryPersistence,
        authority: RecoveryAuthority,
    ) -> None:
        self._persistence = persistence
        self._authority = authority

    def inspect(self, run_id: RunId) -> RecoveryInspection:
        inspection = inspect_recovery(self._persistence.inspection_port(run_id))
        evidence = inspection.evidence
        if evidence.run_id != run_id:
            raise ValueError("persisted recovery evidence does not bind to the Run")
        if evidence.chain_valid and evidence.chain_complete:
            chain = self._persistence.load_chain(run_id)
            if (
                not chain.revisions
                or chain.head.revision != chain.revisions[-1].revision
            ):
                raise ValueError("persisted recovery chain is incomplete")
        return inspection

    def resume_verification(self, run_id: RunId) -> ExecutionOutcome:
        self.inspect(run_id)
        resources = self._persistence.resources(run_id)
        relations: list[DesiredRelation] = []
        for resource in resources:
            observation = resource.observe()
            assessment = resource.assess(observation)
            self._persistence.record_verification(
                run_id, resource.resource_id, observation, assessment
            )
            relations.append(_assessment_relation(assessment))
        if relations and all(
            relation is DesiredRelation.SATISFIED for relation in relations
        ):
            return self._finish(run_id, RunStatus.CONVERGED, resources)
        refreshed = self.inspect(run_id)
        if _action_allowed(refreshed, RecoveryActionCode.ROLLBACK, None):
            return self.rollback(run_id)
        status = (
            RunStatus.FAILED_RECOVERY_REQUIRED
            if any(relation is DesiredRelation.UNVERIFIABLE for relation in relations)
            else RunStatus.FAILED_PARTIAL
        )
        return self._finish(run_id, status, resources)

    def rollback(self, run_id: RunId) -> ExecutionOutcome:
        self.inspect(run_id)
        resources = self._persistence.resources(run_id)
        rollback_results: list[
            tuple[MutationTrace | None, ManagedFileVerification]
        ] = []
        for resource in reversed(resources):
            trace, verification = resource.rollback()
            self._persistence.record_rollback(
                run_id, resource.resource_id, trace, verification
            )
            rollback_results.append((trace, verification))
        status = (
            RunStatus.FAILED_ROLLED_BACK
            if rollback_results
            and all(
                verification.status is ManagedFileVerificationStatus.MATCHED
                for _, verification in rollback_results
            )
            else RunStatus.FAILED_RECOVERY_REQUIRED
        )
        return self._finish(run_id, status, resources)

    def finalize(
        self,
        run_id: RunId,
        mode: FinalizeMode,
        *,
        approval: str | None,
        reason: str | None,
    ) -> ExecutionOutcome:
        inspection = self.inspect(run_id)
        if mode is FinalizeMode.ABANDON:
            if not approval or not reason:
                raise ValueError("abandonment requires separate approval and reason")
            terminal = self._persistence.record_abandonment(
                run_id, approval=approval, reason=reason
            )
            cleanup_complete = True
            for resource in self._persistence.resources(run_id):
                cleanup = resource.cleanup(terminal.digest)
                self._persistence.record_cleanup(run_id, resource.resource_id, cleanup)
                cleanup_complete = cleanup_complete and all(
                    receipt.disposition
                    in {
                        MutationDisposition.APPLIED,
                        MutationDisposition.DEFINITELY_NOT_APPLIED,
                    }
                    for receipt in cleanup.receipts
                )
            self._authority.quarantine(
                run_id,
                terminal.digest,
                approval=approval,
                reason=reason,
            )
            seal_revision = self._persistence.load_chain(run_id).head.revision
            self._persistence.seal(run_id, SealIntent(seal_revision, True))
            return ExecutionOutcome(
                run_id,
                RunStatus.FAILED_RECOVERY_REQUIRED,
                (),
                cleanup_complete,
            )
        status = _normal_final_status(inspection.evidence)
        return self._finish(
            run_id,
            status,
            self._persistence.resources(run_id),
            terminal_already_durable=inspection.evidence.terminal_revision_durable,
            cleanup_already_complete=inspection.evidence.cleanup_complete,
        )

    def _finish(
        self,
        run_id: RunId,
        status: RunStatus,
        resources: tuple[RecoveryResource, ...],
        *,
        terminal_already_durable: bool = False,
        cleanup_already_complete: bool = False,
    ) -> ExecutionOutcome:
        terminal = (
            self._persistence.load_chain(run_id).head
            if terminal_already_durable
            else self._persistence.record_terminal(run_id, status)
        )
        if status is RunStatus.FAILED_RECOVERY_REQUIRED:
            self._persistence.seal(run_id, SealIntent(terminal.revision, False))
            return ExecutionOutcome(run_id, status, (), False)
        if cleanup_already_complete:
            cleanup_complete = True
        else:
            cleanup_complete = True
            for resource in resources:
                cleanup = resource.cleanup(terminal.digest)
                self._persistence.record_cleanup(run_id, resource.resource_id, cleanup)
                cleanup_complete = cleanup_complete and all(
                    receipt.disposition is MutationDisposition.APPLIED
                    for receipt in cleanup.receipts
                )
        release = (
            self._authority.release(run_id, terminal.digest)
            if cleanup_complete
            else None
        )
        released = (
            release is not None and release.disposition is MutationDisposition.APPLIED
        )
        seal_revision = self._persistence.load_chain(run_id).head.revision
        self._persistence.seal(run_id, SealIntent(seal_revision, released))
        return ExecutionOutcome(run_id, status, (), cleanup_complete)


class ExecutionEngine:
    """The only scheduler for mutating execution and recovery."""

    def __init__(
        self,
        journal: ExecutionJournal,
        recovery: RecoveryDriver,
        progress: Progress | None = None,
        finalizer: ExecutionFinalizer | None = None,
    ) -> None:
        self._journal = journal
        self._recovery = recovery
        self._progress = progress or Progress()
        self._finalizer = finalizer

    def start(self, approved_plan: ApprovedPlan) -> ExecutionOutcome:
        self._journal.start(approved_plan)
        self._progress.emit("execution.started", approved_plan.run_id.value)
        results: list[ManagedFileExecutionResult] = []
        prepared_changes: list[tuple[ExecutableChange, object]] = []
        status = RunStatus.CONVERGED
        unavailable: set[str] = set()
        stop_all = False
        for change in approved_plan.changes:
            if stop_all:
                unavailable.add(change.resource_id)
                self._journal.skipped(approved_plan.run_id, change.resource_id, ())
                continue
            blocked_by = tuple(
                dependency
                for dependency in change.requires
                if dependency in unavailable
            )
            if blocked_by:
                unavailable.add(change.resource_id)
                status = RunStatus.FAILED_PARTIAL
                self._journal.skipped(
                    approved_plan.run_id, change.resource_id, blocked_by
                )
                continue
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
                stop_all = True
                continue
            if not result.converged:
                unavailable.add(change.resource_id)
                status = (
                    RunStatus.FAILED_ROLLED_BACK
                    if result.rollback_verification is not None
                    and result.rollback_verification.status.value == "matched"
                    else RunStatus.FAILED_PARTIAL
                )
                if change.disruptive:
                    stop_all = True

        terminal = self._journal.terminal(approved_plan.run_id, status)
        self._progress.emit("execution.terminal", approved_plan.run_id.value)
        cleanup_complete = True
        for change, prepared in prepared_changes:
            try:
                cleanup = change.cleanup(prepared, terminal.digest)
                self._journal.cleanup(approved_plan.run_id, change.resource_id, cleanup)
                if isinstance(cleanup, MutationTrace) and any(
                    receipt.disposition is not MutationDisposition.APPLIED
                    for receipt in cleanup.receipts
                ):
                    cleanup_complete = False
            except Exception:
                cleanup_complete = False
        if self._finalizer is not None:
            self._finalizer.finish(
                approved_plan.run_id,
                terminal,
                cleanup_complete,
            )
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


def _action_allowed(
    inspection: RecoveryInspection,
    code: RecoveryActionCode,
    mode: FinalizeMode | None,
) -> bool:
    action = next(
        (
            item
            for item in inspection.actions
            if item.code is code and item.finalize_mode is mode
        ),
        None,
    )
    return action is not None and action.allowed


def _assessment_relation(assessment: object) -> DesiredRelation:
    relation = getattr(assessment, "relation", None)
    if not isinstance(relation, DesiredRelation):
        raise ValueError("Resource assessment does not contain a typed relation")
    return relation


def _normal_final_status(evidence: RecoveryEvidence) -> RunStatus:
    if evidence.terminal_revision_durable:
        return evidence.canonical_status
    if evidence.rollback_complete_and_verified:
        return RunStatus.FAILED_ROLLED_BACK
    if evidence.current_relation is StateRelation.POST:
        return RunStatus.CONVERGED
    if evidence.current_relation in {
        StateRelation.BEFORE,
        StateRelation.ALLOWED_INTERMEDIATE,
        StateRelation.OTHER,
    }:
        return RunStatus.FAILED_PARTIAL
    return RunStatus.FAILED_RECOVERY_REQUIRED
