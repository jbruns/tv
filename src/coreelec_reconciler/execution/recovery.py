"""Stable recovery inspection and schema-owned pure action computation."""

from dataclasses import dataclass, replace
from typing import Protocol

from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    RecoveryEvidence,
    RemoteOwnershipSnapshot,
    compute_recovery_actions,
)


class RecoveryInspectorPort(Protocol):
    def read_remote_ownership(self) -> RemoteOwnershipSnapshot: ...

    def validate_local_evidence(
        self,
        first: RemoteOwnershipSnapshot,
    ) -> RecoveryEvidence: ...


@dataclass(frozen=True, slots=True)
class RecoveryInspection:
    evidence: RecoveryEvidence
    actions: tuple[AllowedRecoveryAction, ...]


def inspect_recovery(port: RecoveryInspectorPort) -> RecoveryInspection:
    first = port.read_remote_ownership()
    evidence = port.validate_local_evidence(first)
    second = port.read_remote_ownership()
    stable = (
        first.presence == second.presence
        and first.generation == second.generation
        and first.marker_digest == second.marker_digest
    )
    if stable != evidence.stable_snapshot:
        evidence = replace(evidence, stable_snapshot=stable)
    return RecoveryInspection(evidence, compute_recovery_actions(evidence))
