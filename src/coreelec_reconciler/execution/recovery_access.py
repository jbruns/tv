"""Least-authority inspection-to-mutation recovery handoff."""

import dataclasses
import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol, TypeVar

from coreelec_reconciler.domain.canonical_json import canonical_document_bytes
from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    FinalizeMode,
    Presence,
    RecoveryActionCode,
    RecoveryEvidence,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RemoteOwnershipSnapshot,
    StoredRevision,
    WorkspaceId,
    compute_recovery_actions,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.execution.recovery import RecoveryInspection
from coreelec_reconciler.execution.run_adapters import (
    RecoveryEnvironment,
    RemoteOwnershipReader,
)


class RecoveryRunReader(Protocol):
    def load_identity(self, run_id: RunId) -> dict[str, object]: ...

    def inspect_head(self, run_id: RunId) -> StoredRevision: ...


class RecoveryInspectionReader(Protocol):
    """Read-only interface implemented by RecoveryCoordinator."""

    def inspect(self, run_id: RunId) -> RecoveryInspection: ...


@dataclass(frozen=True, slots=True)
class TrustedRecoveryIdentity:
    """Locally trusted Plan identity used before any remote inspection."""

    run_id: RunId
    device_id: DeviceId
    plan_id: PlanId
    plan_full_digest: str
    originating_planning_run_id: RunId


@dataclass(frozen=True, slots=True)
class RecoveryActionRequest:
    action: RecoveryActionCode
    mode: FinalizeMode | None = None
    approval: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryAccessInspection:
    identity: TrustedRecoveryIdentity
    workspace_id: WorkspaceId
    revision: int
    revision_digest: str
    remote_snapshot: RemoteOwnershipSnapshot
    evidence: RecoveryEvidence
    actions: tuple[AllowedRecoveryAction, ...]
    evidence_digest: str
    _authenticator: str = dataclasses.field(repr=False)


@dataclass(frozen=True, slots=True)
class RecoveryHandoff:
    """Immutable authorization for exactly one inspected recovery decision."""

    identity: TrustedRecoveryIdentity
    workspace_id: WorkspaceId
    revision: int
    revision_digest: str
    remote_snapshot: RemoteOwnershipSnapshot
    evidence: RecoveryEvidence
    evidence_digest: str
    action: RecoveryActionCode
    mode: FinalizeMode | None
    approval: str | None
    reason: str | None
    action_reason_code: str
    _authenticator: str = dataclasses.field(repr=False)


T_co = TypeVar("T_co", covariant=True)


class RecoveryMutationExecutor(Protocol[T_co]):
    """Mutation-capable adapter opened only after handoff validation."""

    def execute_recovery(self, handoff: RecoveryHandoff) -> T_co: ...


class RecoveryMutationExecutorFactory(Protocol[T_co]):
    """Open an executor bound to an already validated handoff."""

    def __call__(
        self,
        handoff: RecoveryHandoff,
        /,
    ) -> RecoveryMutationExecutor[T_co]: ...


class RecoveryAccess:
    """Deep module joining read-only inspection to one validated mutation."""

    def __init__(
        self,
        run_store: RecoveryRunReader,
        environment: RecoveryEnvironment,
        ownership: RemoteOwnershipReader,
        inspections: RecoveryInspectionReader,
    ) -> None:
        self._run_store = run_store
        self._environment = environment
        self._ownership = ownership
        self._inspections = inspections
        self._key = secrets.token_bytes(32)

    def inspect(
        self,
        identity: TrustedRecoveryIdentity,
    ) -> RecoveryAccessInspection:
        local, workspace_id = self._load_local_binding(identity)
        first_head = self._run_store.inspect_head(identity.run_id)
        first = self._environment.read_remote_ownership(identity.run_id)
        inspected = self._inspections.inspect(identity.run_id)
        second = self._environment.read_remote_ownership(identity.run_id)
        second_head = self._run_store.inspect_head(identity.run_id)
        if (
            first_head.revision != second_head.revision
            or first_head.digest != second_head.digest
        ):
            raise ValueError("Run revision changed during recovery inspection")
        remote_bound = self._remote_binding_matches(local, first, second)
        evidence_matches_remote = _evidence_matches_snapshot(inspected.evidence, second)
        evidence = replace(
            inspected.evidence,
            stable_snapshot=(
                inspected.evidence.stable_snapshot
                and first == second
                and evidence_matches_remote
            ),
            binding_matches=(
                inspected.evidence.binding_matches is True and remote_bound
            ),
            remote_integrity_valid=(
                inspected.evidence.remote_integrity_valid is not False and remote_bound
            ),
        )
        if evidence.run_id != identity.run_id or evidence.workspace_id != workspace_id:
            raise ValueError(
                "recovery evidence does not bind to trusted local identity"
            )
        actions = compute_recovery_actions(evidence)
        evidence_digest = _digest(evidence)
        unsigned = {
            "kind": "inspection",
            "identity": identity,
            "workspace_id": workspace_id,
            "revision": second_head.revision,
            "revision_digest": second_head.digest,
            "remote_snapshot": second,
            "evidence_digest": evidence_digest,
            "actions": actions,
        }
        return RecoveryAccessInspection(
            identity,
            workspace_id,
            second_head.revision,
            second_head.digest,
            second,
            evidence,
            actions,
            evidence_digest,
            self._authenticate(unsigned),
        )

    def authorize(
        self,
        inspection: RecoveryAccessInspection,
        request: RecoveryActionRequest,
    ) -> RecoveryHandoff:
        self._validate_inspection(inspection)
        action = _find_action(inspection.actions, request)
        if action is None or not action.allowed:
            raise ValueError("recovery action is not allowed by inspected evidence")
        if request.action is RecoveryActionCode.INSPECT:
            raise ValueError("inspect cannot authorize mutation capabilities")
        if action.requires_approval and not _present(request.approval):
            raise ValueError("recovery action requires separate approval")
        if action.requires_reason and not _present(request.reason):
            raise ValueError("recovery action requires a non-empty reason")
        _reject_corrupt_unsafe_action(inspection.evidence, request)
        unsigned = {
            "kind": "handoff",
            "identity": inspection.identity,
            "workspace_id": inspection.workspace_id,
            "revision": inspection.revision,
            "revision_digest": inspection.revision_digest,
            "remote_snapshot": inspection.remote_snapshot,
            "evidence_digest": inspection.evidence_digest,
            "action": request.action,
            "mode": request.mode,
            "approval": request.approval,
            "reason": request.reason,
            "action_reason_code": action.reason_code,
        }
        return RecoveryHandoff(
            inspection.identity,
            inspection.workspace_id,
            inspection.revision,
            inspection.revision_digest,
            inspection.remote_snapshot,
            inspection.evidence,
            inspection.evidence_digest,
            request.action,
            request.mode,
            request.approval,
            request.reason,
            action.reason_code,
            self._authenticate(unsigned),
        )

    def execute_mutation(
        self,
        handoff: RecoveryHandoff,
        request: RecoveryActionRequest,
        executor_factory: RecoveryMutationExecutorFactory[T_co],
    ) -> T_co:
        self._validate_handoff(handoff, request)
        executor = executor_factory(handoff)
        return executor.execute_recovery(handoff)

    def _validate_inspection(self, inspection: RecoveryAccessInspection) -> None:
        unsigned = {
            "kind": "inspection",
            "identity": inspection.identity,
            "workspace_id": inspection.workspace_id,
            "revision": inspection.revision,
            "revision_digest": inspection.revision_digest,
            "remote_snapshot": inspection.remote_snapshot,
            "evidence_digest": inspection.evidence_digest,
            "actions": inspection.actions,
        }
        if not hmac.compare_digest(
            inspection._authenticator, self._authenticate(unsigned)
        ):
            raise ValueError("recovery inspection handoff was altered")
        if inspection.evidence_digest != _digest(inspection.evidence):
            raise ValueError("recovery inspection evidence was altered")
        self._validate_current(
            inspection.identity,
            inspection.workspace_id,
            inspection.revision,
            inspection.revision_digest,
            inspection.remote_snapshot,
        )

    def _validate_handoff(
        self,
        handoff: RecoveryHandoff,
        request: RecoveryActionRequest,
    ) -> None:
        unsigned = {
            "kind": "handoff",
            "identity": handoff.identity,
            "workspace_id": handoff.workspace_id,
            "revision": handoff.revision,
            "revision_digest": handoff.revision_digest,
            "remote_snapshot": handoff.remote_snapshot,
            "evidence_digest": handoff.evidence_digest,
            "action": handoff.action,
            "mode": handoff.mode,
            "approval": handoff.approval,
            "reason": handoff.reason,
            "action_reason_code": handoff.action_reason_code,
        }
        if not hmac.compare_digest(
            handoff._authenticator, self._authenticate(unsigned)
        ):
            raise ValueError("recovery handoff was altered")
        if handoff.evidence_digest != _digest(handoff.evidence):
            raise ValueError("recovery handoff evidence was altered")
        if request != RecoveryActionRequest(
            handoff.action,
            handoff.mode,
            handoff.approval,
            handoff.reason,
        ):
            raise ValueError("recovery action changed after inspection")
        action = _find_action(compute_recovery_actions(handoff.evidence), request)
        if (
            action is None
            or not action.allowed
            or action.reason_code != handoff.action_reason_code
        ):
            raise ValueError("recovery handoff contains an unsafe action")
        _reject_corrupt_unsafe_action(handoff.evidence, request)
        self._validate_current(
            handoff.identity,
            handoff.workspace_id,
            handoff.revision,
            handoff.revision_digest,
            handoff.remote_snapshot,
        )

    def _validate_current(
        self,
        identity: TrustedRecoveryIdentity,
        workspace_id: WorkspaceId,
        revision: int,
        revision_digest: str,
        remote_snapshot: RemoteOwnershipSnapshot,
    ) -> None:
        local, current_workspace = self._load_local_binding(identity)
        head = self._run_store.inspect_head(identity.run_id)
        if (
            current_workspace != workspace_id
            or head.revision != revision
            or head.digest != revision_digest
        ):
            raise ValueError("recovery handoff is stale")
        current_remote = self._environment.read_remote_ownership(identity.run_id)
        if current_remote != remote_snapshot or not self._remote_binding_matches(
            local, current_remote, current_remote
        ):
            raise ValueError("recovery handoff remote evidence is stale")

    def _load_local_binding(
        self,
        trusted: TrustedRecoveryIdentity,
    ) -> tuple[dict[str, object], WorkspaceId]:
        local = self._run_store.load_identity(trusted.run_id)
        expected = {
            "run_id": trusted.run_id.value,
            "device_id": trusted.device_id.value,
            "plan_id": trusted.plan_id.value,
            "plan_full_digest": trusted.plan_full_digest,
            "originating_planning_run_id": trusted.originating_planning_run_id.value,
        }
        if any(local.get(key) != value for key, value in expected.items()):
            raise ValueError("trusted recovery Run/Plan identity changed")
        workspace = local.get("workspace_id")
        if not isinstance(workspace, str) or not workspace:
            raise ValueError("trusted recovery workspace identity is invalid")
        return local, WorkspaceId(workspace)

    def _remote_binding_matches(
        self,
        local: dict[str, object],
        first: RemoteOwnershipSnapshot,
        second: RemoteOwnershipSnapshot,
    ) -> bool:
        if (
            first != second
            or second.presence is not Presence.PRESENT
            or second.identity is None
        ):
            return False
        expected = _remote_identity(local)
        try:
            ownership = self._ownership.read_ownership(expected.device_id)
        except OSError, RuntimeError, TypeError, ValueError:
            return False
        return _ownership_matches_snapshot(ownership, second) and (
            ownership.identity == expected
            and ownership.token_digest == local.get("ownership_token_digest")
        )

    def _authenticate(self, value: object) -> str:
        return hmac.digest(self._key, _canonical_bytes(value), "sha256").hex()


def _remote_identity(local: dict[str, object]) -> RemoteOwnershipIdentity:
    return RemoteOwnershipIdentity(
        DeviceId(_text(local, "device_id")),
        RunId(_text(local, "run_id")),
        WorkspaceId(_text(local, "workspace_id")),
        _text(local, "plan_id"),
        _text(local, "plan_full_digest"),
        _text(local, "binding_digest"),
        _text(local, "boot_id"),
    )


def _ownership_matches_snapshot(
    ownership: RemoteOwnership,
    snapshot: RemoteOwnershipSnapshot,
) -> bool:
    return (
        snapshot.identity == ownership.identity
        and snapshot.token_digest == ownership.token_digest
        and snapshot.generation == ownership.generation
        and snapshot.phase is ownership.phase
        and snapshot.marker_digest == ownership.marker_digest
    )


def _evidence_matches_snapshot(
    evidence: RecoveryEvidence,
    snapshot: RemoteOwnershipSnapshot,
) -> bool:
    return (
        evidence.remote_ownership_presence is snapshot.presence
        and evidence.remote_generation == snapshot.generation
        and evidence.remote_phase is snapshot.phase
        and evidence.remote_marker_digest == snapshot.marker_digest
    )


def _find_action(
    actions: tuple[AllowedRecoveryAction, ...],
    request: RecoveryActionRequest,
) -> AllowedRecoveryAction | None:
    return next(
        (
            action
            for action in actions
            if action.code is request.action and action.finalize_mode is request.mode
        ),
        None,
    )


def _reject_corrupt_unsafe_action(
    evidence: RecoveryEvidence,
    request: RecoveryActionRequest,
) -> None:
    corrupt = not all(
        (
            evidence.chain_valid,
            evidence.chain_complete,
            evidence.attachments_valid,
            evidence.codecs_valid,
        )
    )
    if corrupt and not (
        request.action is RecoveryActionCode.FINALIZE
        and request.mode is FinalizeMode.ABANDON
        and _present(request.approval)
        and _present(request.reason)
    ):
        raise ValueError("corrupt evidence permits only approved abandonment")


def _present(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"trusted recovery {key} is invalid")
    return item


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return canonical_document_bytes({"value": _canonical_value(value)})


def _canonical_value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if not field.name.startswith("_")
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if value is None or isinstance(value, bool | int | str):
        return value
    raise TypeError(f"unsupported recovery handoff value: {type(value).__name__}")
