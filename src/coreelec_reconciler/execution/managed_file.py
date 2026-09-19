"""Managed-file mutation, fresh Verification, and conditional restoration."""

import json
import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coreelec_reconciler.domain.execution import (
    MarkerCheckpoint,
    MutationDisposition,
    MutationReceipt,
    MutationTrace,
    NormalizedResourceState,
    Presence,
    PrimitiveKind,
    ResourceMutationIntent,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
    observe_managed_file,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    AttachmentStore,
    PreparedManagedFile,
)
from coreelec_reconciler.transports.interfaces import ManagedFileReader


class ManagedFileCapabilities(ManagedFileReader, Protocol):
    """Least-authority mutation surface required by managed-file execution."""

    def stage_write(
        self, path: str, content: bytes, mode: int, operation_id: str
    ) -> MutationReceipt: ...

    def chmod(self, path: str, mode: int, operation_id: str) -> MutationReceipt: ...

    def atomic_replace(
        self, staged_path: str, destination: str, operation_id: str
    ) -> MutationReceipt: ...

    def remove(self, path: str, operation_id: str) -> MutationReceipt: ...

    def restore(
        self,
        path: str,
        content: bytes | None,
        mode: int | None,
        operation_id: str,
    ) -> MutationReceipt: ...

    def cleanup(self, path: str, operation_id: str) -> MutationReceipt: ...


class VerificationStatus(StrEnum):
    MATCHED = "matched"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ManagedFileVerification:
    status: VerificationStatus
    observation: ManagedFileObservation


@dataclass(frozen=True, slots=True)
class ManagedFileExecutionResult:
    mutation: MutationTrace
    verification: ManagedFileVerification
    rollback: MutationTrace | None = None
    rollback_verification: ManagedFileVerification | None = None
    cleanup: MutationTrace | None = None

    @property
    def converged(self) -> bool:
        return self.verification.status is VerificationStatus.MATCHED

    @property
    def recovery_required(self) -> bool:
        return (
            self.verification.status is VerificationStatus.UNKNOWN
            or any(
                receipt.disposition is MutationDisposition.AMBIGUOUS
                for trace in (self.rollback, self.cleanup)
                if trace is not None
                for receipt in trace.receipts
            )
            or (
                self.rollback_verification is not None
                and self.rollback_verification.status is not VerificationStatus.MATCHED
            )
        )


IntentCheckpoint = Callable[[ResourceMutationIntent], None]
MarkerProvider = Callable[[PrimitiveKind], MarkerCheckpoint]
MarkerVerifier = Callable[[MarkerCheckpoint], None]


class ManagedFileExecutor:
    """Executes one fully prepared managed file without inferring state from ACKs."""

    def __init__(
        self,
        capabilities: ManagedFileCapabilities,
        attachments: AttachmentStore,
        checkpoint: IntentCheckpoint,
        marker: MarkerProvider,
        verify_marker: MarkerVerifier | None = None,
        *,
        read_limit: int = 1_048_576,
    ) -> None:
        self._files = capabilities
        self._attachments = attachments
        self._checkpoint = checkpoint
        self._marker = marker
        self._verify_marker = verify_marker or (lambda checkpoint: None)
        self._read_limit = read_limit

    def apply(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
        rollback_approved: bool,
    ) -> ManagedFileExecutionResult:
        receipts: list[MutationReceipt] = []
        path = prepared.address.device_path.value
        staged_path = _staged_path(path, prepared.staged_object.object_id)
        before = self._observe(prepared)
        if not before.safe or before.state != prepared.before:
            verification = ManagedFileVerification(
                VerificationStatus.UNKNOWN
                if not before.safe
                else VerificationStatus.MISMATCH,
                before,
            )
            return ManagedFileExecutionResult(MutationTrace(()), verification)

        if prepared.desired.presence is Presence.ABSENT:
            receipts.append(
                self._primitive(
                    prepared,
                    resource_id,
                    change_id,
                    PrimitiveKind.REMOVE,
                    lambda operation_id: self._files.remove(path, operation_id),
                )
            )
        elif prepared.before.content_digest != prepared.desired.content_digest:
            desired = self._desired_bytes(prepared)
            receipts.append(
                self._primitive(
                    prepared,
                    resource_id,
                    change_id,
                    PrimitiveKind.STAGE_WRITE,
                    lambda operation_id: self._files.stage_write(
                        staged_path,
                        desired,
                        prepared.desired.managed_mode or 0,
                        operation_id,
                    ),
                )
            )
            if receipts[-1].disposition is MutationDisposition.APPLIED:
                receipts.append(
                    self._primitive(
                        prepared,
                        resource_id,
                        change_id,
                        PrimitiveKind.ATOMIC_REPLACE,
                        lambda operation_id: self._files.atomic_replace(
                            staged_path, path, operation_id
                        ),
                    )
                )
            if (
                receipts[-1].disposition is MutationDisposition.APPLIED
                and prepared.desired.managed_mode is not None
            ):
                current = self._observe(prepared)
                if (
                    current.safe
                    and current.state.presence is Presence.PRESENT
                    and current.state.managed_mode != prepared.desired.managed_mode
                ):
                    receipts.append(
                        self._primitive(
                            prepared,
                            resource_id,
                            change_id,
                            PrimitiveKind.CHMOD,
                            lambda operation_id: self._files.chmod(
                                path,
                                prepared.desired.managed_mode or 0,
                                operation_id,
                            ),
                        )
                    )
        elif prepared.before.managed_mode != prepared.desired.managed_mode:
            receipts.append(
                self._primitive(
                    prepared,
                    resource_id,
                    change_id,
                    PrimitiveKind.CHMOD,
                    lambda operation_id: self._files.chmod(
                        path, prepared.desired.managed_mode or 0, operation_id
                    ),
                )
            )

        verification = self.verify(prepared, prepared.desired)
        rollback: MutationTrace | None = None
        rollback_verification: ManagedFileVerification | None = None
        if verification.status is not VerificationStatus.MATCHED and rollback_approved:
            relation = verification.observation.state
            if verification.observation.safe and relation in {
                prepared.before,
                prepared.desired,
                *prepared.allowed_intermediates,
            }:
                rollback = self._restore(prepared, resource_id, change_id)
                rollback_verification = self.verify(prepared, prepared.before)
        return ManagedFileExecutionResult(
            MutationTrace(tuple(receipts)),
            verification,
            rollback,
            rollback_verification,
        )

    def cleanup(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
    ) -> MutationTrace:
        return self._cleanup(prepared, resource_id, change_id)

    def rollback(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
    ) -> tuple[MutationTrace | None, ManagedFileVerification]:
        observed = self._observe(prepared)
        if not observed.safe or observed.state not in {
            prepared.before,
            prepared.desired,
            *prepared.allowed_intermediates,
        }:
            return None, ManagedFileVerification(
                VerificationStatus.UNKNOWN
                if not observed.safe
                else VerificationStatus.MISMATCH,
                observed,
            )
        trace = self._restore(prepared, resource_id, change_id)
        return trace, self.verify(prepared, prepared.before)

    def verify(
        self,
        prepared: PreparedManagedFile,
        expected: NormalizedResourceState | None = None,
    ) -> ManagedFileVerification:
        observation = self._observe(prepared)
        status = (
            VerificationStatus.UNKNOWN
            if not observation.safe
            else (
                VerificationStatus.MATCHED
                if observation.state == (expected or prepared.desired)
                else VerificationStatus.MISMATCH
            )
        )
        return ManagedFileVerification(status, observation)

    def _restore(
        self,
        prepared: PreparedManagedFile,
        resource_id: str,
        change_id: str,
    ) -> MutationTrace:
        payload = self._attachments.read_attachment(prepared.rollback_attachment)
        value = json.loads(payload)
        content_hex = value.get("content_hex")
        content = bytes.fromhex(content_hex) if isinstance(content_hex, str) else None
        receipt = self._primitive(
            prepared,
            resource_id,
            change_id,
            PrimitiveKind.RESTORE,
            lambda operation_id: self._files.restore(
                prepared.address.device_path.value,
                content,
                prepared.before.managed_mode,
                operation_id,
            ),
        )
        return MutationTrace((receipt,))

    def _cleanup(
        self,
        prepared: PreparedManagedFile,
        resource_id: str,
        change_id: str,
    ) -> MutationTrace:
        path = _staged_path(
            prepared.address.device_path.value, prepared.staged_object.object_id
        )
        receipt = self._primitive(
            prepared,
            resource_id,
            change_id,
            PrimitiveKind.CLEANUP,
            lambda operation_id: self._files.cleanup(path, operation_id),
        )
        return MutationTrace((receipt,))

    def _primitive(
        self,
        prepared: PreparedManagedFile,
        resource_id: str,
        change_id: str,
        primitive: PrimitiveKind,
        operation: Callable[[str], MutationReceipt],
    ) -> MutationReceipt:
        operation_id = f"{change_id}.{primitive.value}"
        intent = ResourceMutationIntent(
            operation_id=operation_id,
            primitive=primitive,
            resource_id=resource_id,
            change_id=change_id,
            preparation_manifest_digest=prepared.manifest_digest,
            expected_before=prepared.before,
            expected_after=prepared.desired,
            allowed_intermediates=prepared.allowed_intermediates,
            content_attachment_digest=(
                prepared.desired_attachment.digest
                if prepared.desired_attachment is not None
                else None
            ),
            marker=self._marker(primitive),
            attempt=1,
        )
        self._checkpoint(intent)
        self._verify_marker(intent.marker)
        return operation(operation_id)

    def _observe(self, prepared: PreparedManagedFile) -> ManagedFileObservation:
        return observe_managed_file(
            self._files, prepared.address, read_limit=self._read_limit
        )

    def _desired_bytes(self, prepared: PreparedManagedFile) -> bytes:
        if prepared.desired_attachment is None:
            raise ValueError("present desired state has no content attachment")
        return self._attachments.read_attachment(prepared.desired_attachment)


def _staged_path(destination: str, object_id: str) -> str:
    directory, name = posixpath.split(destination)
    return posixpath.join(directory, f".{name}.{object_id}")
