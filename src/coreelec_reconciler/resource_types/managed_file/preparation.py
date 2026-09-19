"""Complete managed-file preparation without managed-address mutation."""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.execution import AttachmentRef, NormalizedResourceState
from coreelec_reconciler.reporting.canonical_json import canonical_document_bytes
from coreelec_reconciler.transports.interfaces import ManagedFileReader

from .observation import ManagedFileObservation, observe_managed_file
from .paths import ResolvedManagedAddress


class AttachmentStore(Protocol):
    def attach(self, kind: str, codec: str, payload: bytes) -> AttachmentRef: ...

    def read_attachment(self, reference: AttachmentRef) -> bytes: ...


class StalePrecondition(RuntimeError):
    pass


class PreparationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreparationBinding:
    device_id: str
    binding_digest: str
    run_id: str
    resource_id: str
    change_id: str


@dataclass(frozen=True, slots=True)
class PreparedManagedFile:
    address: ResolvedManagedAddress
    before: NormalizedResourceState
    desired: NormalizedResourceState
    allowed_intermediates: tuple[NormalizedResourceState, ...]
    rollback_attachment: AttachmentRef
    manifest_bytes: bytes
    manifest_digest: str


def prepare_managed_file(
    *,
    reader: ManagedFileReader,
    attachments: AttachmentStore,
    address: ResolvedManagedAddress,
    binding: PreparationBinding,
    expected_before: NormalizedResourceState,
    desired: NormalizedResourceState,
    allowed_intermediates: tuple[NormalizedResourceState, ...],
    read_limit: int,
) -> PreparedManagedFile:
    before = observe_managed_file(reader, address, read_limit=read_limit)
    if not before.safe:
        raise PreparationError("before-state observation is unsafe or unreadable")
    if before.state != expected_before:
        raise StalePrecondition("managed-file precondition changed before preparation")
    attachment_payload = _before_attachment(before, binding)
    reference = attachments.attach(
        "managed-file-before-state",
        "managed-file-before-v1",
        attachment_payload,
    )
    try:
        loaded_attachment = attachments.read_attachment(reference)
    except Exception as error:
        raise PreparationError("rollback attachment verification failed") from error
    if loaded_attachment != attachment_payload:
        raise PreparationError("rollback attachment verification failed")
    rechecked = observe_managed_file(reader, address, read_limit=read_limit)
    if not rechecked.safe or rechecked.state != expected_before:
        raise StalePrecondition("managed-file precondition changed during preparation")
    if len(set(allowed_intermediates)) != len(allowed_intermediates):
        raise PreparationError(
            "allowed intermediate states must be complete and unique"
        )
    required_intermediates = _required_intermediates(expected_before, desired)
    if not set(required_intermediates).issubset(allowed_intermediates):
        raise PreparationError("preparation omits a reachable intermediate state")
    manifest = canonical_document_bytes(
        {
            "address": address.logical_address,
            "allowed_intermediate_digests": [
                _state_digest(state) for state in allowed_intermediates
            ],
            "before_state_digest": _state_digest(expected_before),
            "binding_digest": binding.binding_digest,
            "change_id": binding.change_id,
            "desired_state_digest": _state_digest(desired),
            "device_id": binding.device_id,
            "managed_path": address.device_path.value,
            "resource_id": binding.resource_id,
            "rollback_attachment_digest": reference.digest,
            "run_id": binding.run_id,
            "schema_version": 1,
        }
    )
    return PreparedManagedFile(
        address,
        expected_before,
        desired,
        allowed_intermediates,
        reference,
        manifest,
        "sha256:" + hashlib.sha256(manifest).hexdigest(),
    )


def recheck_precondition(
    reader: ManagedFileReader,
    prepared: PreparedManagedFile,
    *,
    read_limit: int,
) -> ManagedFileObservation:
    observation = observe_managed_file(reader, prepared.address, read_limit=read_limit)
    if not observation.safe or observation.state != prepared.before:
        raise StalePrecondition("managed-file precondition is stale")
    return observation


def _before_attachment(
    observation: ManagedFileObservation,
    binding: PreparationBinding,
) -> bytes:
    return canonical_document_bytes(
        {
            "binding_digest": binding.binding_digest,
            "change_id": binding.change_id,
            "codec": "managed-file-before-v1",
            "content_hex": (
                observation.content.hex() if observation.content is not None else None
            ),
            "content_digest": observation.state.content_digest,
            "device_id": binding.device_id,
            "entry_kind": observation.state.entry_kind,
            "logical_address": observation.address.logical_address,
            "managed_mode": observation.state.managed_mode,
            "managed_path": observation.address.device_path.value,
            "presence": observation.state.presence.value,
            "resource_id": binding.resource_id,
            "run_id": binding.run_id,
            "schema_version": 1,
            "size": len(observation.content or b""),
        }
    )


def _state_digest(state: NormalizedResourceState) -> str:
    payload = canonical_document_bytes(
        {
            "content_digest": state.content_digest,
            "entry_kind": state.entry_kind,
            "managed_mode": state.managed_mode,
            "presence": state.presence.value,
        }
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _required_intermediates(
    before: NormalizedResourceState,
    desired: NormalizedResourceState,
) -> tuple[NormalizedResourceState, ...]:
    if (
        before.presence is desired.presence
        and before.presence.value == "present"
        and before.content_digest != desired.content_digest
        and before.managed_mode != desired.managed_mode
    ):
        return (
            NormalizedResourceState(
                desired.presence,
                desired.entry_kind,
                desired.content_digest,
                before.managed_mode,
            ),
        )
    return ()
