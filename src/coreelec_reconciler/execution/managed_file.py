"""Managed-file mutation, fresh Verification, and conditional restoration."""

import json
import posixpath
from collections.abc import Callable

from coreelec_reconciler.domain.execution import (
    CleanupMutationIntent,
    MarkerCheckpoint,
    MutationDisposition,
    MutationIntent,
    MutationReceipt,
    MutationTrace,
    NormalizedResourceState,
    Presence,
    PrimitiveKind,
    ResourceMutationIntent,
)
from coreelec_reconciler.resource_types.descriptor import (
    AttachmentStore,
    ManagedFileCapabilities,
    ManagedFileExecutionResult,
    ManagedFileVerification,
    ManagedFileVerificationStatus,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
    observe_managed_file,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ManagedPath,
    ResolvedManagedAddress,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    PreparedManagedFile,
)

VerificationStatus = ManagedFileVerificationStatus


IntentCheckpoint = Callable[[MutationIntent], None]
MarkerProvider = Callable[[PrimitiveKind], MarkerCheckpoint]
MarkerVerifier = Callable[[MarkerCheckpoint], None]
PrimitiveOutcomeCheckpoint = Callable[
    [MutationTrace, ManagedFileObservation],
    None,
]
ObservationVerifier = Callable[[ManagedFileObservation], bool | None]


class ManagedFileExecutor:
    """Executes one fully prepared managed file without inferring state from ACKs."""

    def __init__(
        self,
        capabilities: ManagedFileCapabilities,
        attachments: AttachmentStore,
        checkpoint: IntentCheckpoint,
        marker: MarkerProvider,
        verify_marker: MarkerVerifier | None = None,
        outcome_checkpoint: PrimitiveOutcomeCheckpoint | None = None,
        *,
        read_limit: int = 1_048_576,
    ) -> None:
        self._files = capabilities
        self._attachments = attachments
        self._checkpoint = checkpoint
        self._marker = marker
        self._verify_marker = verify_marker or (lambda checkpoint: None)
        self._outcome_checkpoint = outcome_checkpoint or (
            lambda trace, observation: None
        )
        self._read_limit = read_limit

    def apply(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
        rollback_approved: bool,
        verify: ObservationVerifier | None = None,
    ) -> ManagedFileExecutionResult:
        receipts: list[MutationReceipt] = []
        path = prepared.address.device_path.value
        staged_path = _staged_path(
            path,
            prepared.staged_object.object_id,
            prepared.binding.binding_digest,
        )
        before = self._observe(prepared)
        if not before.safe or before.state != prepared.before:
            verification = ManagedFileVerification(
                ManagedFileVerificationStatus.UNKNOWN
                if not before.safe
                else ManagedFileVerificationStatus.MISMATCH,
                before,
            )
            return ManagedFileExecutionResult(MutationTrace(()), verification)

        if prepared.desired.presence is Presence.ABSENT:
            receipt = self._primitive(
                prepared,
                resource_id,
                change_id,
                PrimitiveKind.REMOVE,
                lambda operation_id: self._files.remove(
                    path,
                    operation_id,
                    expected=prepared.before,
                    binding_digest=prepared.binding.binding_digest,
                ),
            )
            receipts.append(receipt)
            self._persist_primitive(receipts, prepared.address)
        elif prepared.before.content_digest != prepared.desired.content_digest:
            desired = self._desired_bytes(prepared)
            receipt = self._primitive(
                prepared,
                resource_id,
                change_id,
                PrimitiveKind.STAGE_WRITE,
                lambda operation_id: self._files.stage_write(
                    staged_path,
                    desired,
                    prepared.desired.managed_mode or 0,
                    operation_id,
                    expected=_absent_state(),
                    binding_digest=prepared.binding.binding_digest,
                ),
            )
            receipts.append(receipt)
            staged_observation = self._persist_primitive(
                receipts,
                ResolvedManagedAddress(
                    prepared.address.logical_address, ManagedPath(staged_path)
                ),
            )
            staged_ready = (
                receipt.disposition is not MutationDisposition.DEFINITELY_NOT_APPLIED
                and staged_observation.safe
                and staged_observation.state.presence is Presence.PRESENT
                and staged_observation.state.content_digest
                == prepared.desired.content_digest
            )
            if staged_ready:
                receipt = self._primitive(
                    prepared,
                    resource_id,
                    change_id,
                    PrimitiveKind.ATOMIC_REPLACE,
                    lambda operation_id: self._files.atomic_replace(
                        staged_path,
                        path,
                        operation_id,
                        expected_staged=staged_observation.state,
                        expected_destination=prepared.before,
                        binding_digest=prepared.binding.binding_digest,
                    ),
                )
                receipts.append(receipt)
                current = self._persist_primitive(receipts, prepared.address)
            else:
                current = staged_observation
            if (
                receipt.disposition is not MutationDisposition.DEFINITELY_NOT_APPLIED
                and current.safe
                and current.address == prepared.address
                and current.state.content_digest == prepared.desired.content_digest
                and prepared.desired.managed_mode is not None
                and current.state.presence is Presence.PRESENT
                and current.state.managed_mode != prepared.desired.managed_mode
            ):
                receipt = self._primitive(
                    prepared,
                    resource_id,
                    change_id,
                    PrimitiveKind.CHMOD,
                    lambda operation_id: self._files.chmod(
                        path,
                        prepared.desired.managed_mode or 0,
                        operation_id,
                        expected=current.state,
                        binding_digest=prepared.binding.binding_digest,
                    ),
                )
                receipts.append(receipt)
                self._persist_primitive(receipts, prepared.address)
        elif prepared.before.managed_mode != prepared.desired.managed_mode:
            receipt = self._primitive(
                prepared,
                resource_id,
                change_id,
                PrimitiveKind.CHMOD,
                lambda operation_id: self._files.chmod(
                    path,
                    prepared.desired.managed_mode or 0,
                    operation_id,
                    expected=prepared.before,
                    binding_digest=prepared.binding.binding_digest,
                ),
            )
            receipts.append(receipt)
            self._persist_primitive(receipts, prepared.address)

        verification = self._verify(prepared, prepared.desired, verify)
        rollback: MutationTrace | None = None
        rollback_verification: ManagedFileVerification | None = None
        if (
            verification.status is not ManagedFileVerificationStatus.MATCHED
            and rollback_approved
        ):
            relation = verification.observation.state
            if verification.observation.safe and relation in {
                prepared.before,
                prepared.desired,
                *prepared.allowed_intermediates,
            }:
                rollback = self._restore(
                    prepared, resource_id, change_id, verification.observation.state
                )
                rollback_verification = self._verify(prepared, prepared.before)
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
        terminal_evidence_ref: str,
    ) -> MutationTrace:
        return self._cleanup(prepared, resource_id, change_id, terminal_evidence_ref)

    def rollback(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
    ) -> tuple[MutationTrace | None, ManagedFileVerification]:
        observed = self._observe(prepared)
        if observed.safe and observed.state == prepared.before:
            return MutationTrace(()), self._verify(prepared, prepared.before)
        if not observed.safe or observed.state not in {
            prepared.before,
            prepared.desired,
            *prepared.allowed_intermediates,
        }:
            return None, ManagedFileVerification(
                ManagedFileVerificationStatus.UNKNOWN
                if not observed.safe
                else ManagedFileVerificationStatus.MISMATCH,
                observed,
            )
        trace = self._restore(prepared, resource_id, change_id, observed.state)
        return trace, self._verify(prepared, prepared.before)

    def _verify(
        self,
        prepared: PreparedManagedFile,
        expected: NormalizedResourceState | None = None,
        verify: ObservationVerifier | None = None,
    ) -> ManagedFileVerification:
        observation = self._observe(prepared)
        assessed = verify(observation) if verify is not None else None
        status = (
            ManagedFileVerificationStatus.UNKNOWN
            if not observation.safe
            else (
                ManagedFileVerificationStatus.MATCHED
                if (
                    assessed is True
                    or (
                        verify is None
                        and observation.state == (expected or prepared.desired)
                    )
                )
                else (
                    ManagedFileVerificationStatus.UNKNOWN
                    if assessed is None and verify is not None
                    else ManagedFileVerificationStatus.MISMATCH
                )
            )
        )
        return ManagedFileVerification(status, observation)

    def _restore(
        self,
        prepared: PreparedManagedFile,
        resource_id: str,
        change_id: str,
        expected: NormalizedResourceState,
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
                expected=expected,
                binding_digest=prepared.binding.binding_digest,
            ),
        )
        trace = MutationTrace((receipt,))
        self._persist_primitive(list(trace.receipts), prepared.address)
        return trace

    def _cleanup(
        self,
        prepared: PreparedManagedFile,
        resource_id: str,
        change_id: str,
        terminal_evidence_ref: str,
    ) -> MutationTrace:
        path = _staged_path(
            prepared.address.device_path.value,
            prepared.staged_object.object_id,
            prepared.binding.binding_digest,
        )
        operation_id = f"{change_id}.{PrimitiveKind.CLEANUP.value}"
        staged_address = ResolvedManagedAddress(
            prepared.address.logical_address, ManagedPath(path)
        )
        expected = observe_managed_file(
            self._files, staged_address, read_limit=self._read_limit
        )
        marker = self._marker(PrimitiveKind.CLEANUP)
        self._checkpoint(
            CleanupMutationIntent(
                operation_id,
                PrimitiveKind.CLEANUP,
                prepared.cleanup_object.object_id,
                terminal_evidence_ref,
                marker,
                1,
            )
        )
        self._verify_marker(marker)
        receipt = self._files.cleanup(
            path,
            operation_id,
            expected=expected.state,
            binding_digest=prepared.binding.binding_digest,
        )
        trace = MutationTrace((receipt,))
        self._persist_primitive(
            list(trace.receipts),
            staged_address,
        )
        return trace

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
                if primitive
                in {
                    PrimitiveKind.STAGE_WRITE,
                    PrimitiveKind.ATOMIC_REPLACE,
                    PrimitiveKind.RESTORE,
                }
                and prepared.desired_attachment is not None
                else None
            ),
            marker=self._marker(primitive),
            attempt=1,
        )
        self._checkpoint(intent)
        self._verify_marker(intent.marker)
        return operation(operation_id)

    def _persist_primitive(
        self,
        receipts: list[MutationReceipt],
        address: ResolvedManagedAddress,
    ) -> ManagedFileObservation:
        observation = observe_managed_file(
            self._files, address, read_limit=self._read_limit
        )
        self._outcome_checkpoint(MutationTrace(tuple(receipts)), observation)
        return observation

    def _observe(self, prepared: PreparedManagedFile) -> ManagedFileObservation:
        return observe_managed_file(
            self._files, prepared.address, read_limit=self._read_limit
        )

    def _desired_bytes(self, prepared: PreparedManagedFile) -> bytes:
        if prepared.desired_attachment is None:
            raise ValueError("present desired state has no content attachment")
        return self._attachments.read_attachment(prepared.desired_attachment)


def _staged_path(destination: str, object_id: str, binding_digest: str) -> str:
    directory, name = posixpath.split(destination)
    binding_key = binding_digest.removeprefix("sha256:")
    return posixpath.join(directory, f".{name}.{object_id}.{binding_key}.stage")


def _absent_state() -> NormalizedResourceState:
    return NormalizedResourceState(Presence.ABSENT, None, None, None)
