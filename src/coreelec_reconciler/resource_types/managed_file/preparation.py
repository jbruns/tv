"""Complete managed-file preparation without managed-address mutation."""

import hashlib
from dataclasses import dataclass

from coreelec_reconciler.domain.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.domain.execution import (
    AttachmentRef,
    NormalizedResourceState,
    Presence,
)
from coreelec_reconciler.resource_types.descriptor import AttachmentStore
from coreelec_reconciler.transports.interfaces import ManagedFileReader

from .observation import ManagedFileObservation, observe_managed_file
from .paths import ManagedPath, ResolvedManagedAddress


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
class PreparationObject:
    object_id: str
    content_digest: str


@dataclass(frozen=True, slots=True)
class PreparedManagedFile:
    binding: PreparationBinding
    address: ResolvedManagedAddress
    before: NormalizedResourceState
    desired: NormalizedResourceState
    allowed_intermediates: tuple[NormalizedResourceState, ...]
    rollback_attachment: AttachmentRef
    desired_attachment: AttachmentRef | None
    staged_metadata_attachment: AttachmentRef
    cleanup_metadata_attachment: AttachmentRef
    staged_object: PreparationObject
    cleanup_object: PreparationObject
    manifest_bytes: bytes
    manifest_digest: str
    rollback_capable: bool


def decode_prepared_managed_file(
    manifest_bytes: bytes,
    attachments: AttachmentStore,
) -> PreparedManagedFile:
    """Reconstruct and verify a prepared managed file from durable evidence."""
    try:
        value = decode_json_object(manifest_bytes)
        if set(value) != {
            "address",
            "allowed_intermediate_states",
            "before_state",
            "before_state_digest",
            "binding_digest",
            "change_id",
            "cleanup_metadata_attachment_digest",
            "cleanup_object",
            "desired_attachment_digest",
            "desired_state",
            "desired_state_digest",
            "device_id",
            "managed_path",
            "resource_id",
            "rollback_attachment_digest",
            "run_id",
            "schema_version",
            "staged_metadata_attachment_digest",
            "staged_object",
        }:
            raise ValueError("unknown or missing preparation manifest fields")
        if value["schema_version"] != 1:
            raise ValueError("unsupported preparation manifest")
        before = _decode_state(value["before_state"])
        desired = _decode_state(value["desired_state"])
        intermediates_value = value["allowed_intermediate_states"]
        if not isinstance(intermediates_value, list):
            raise ValueError("allowed intermediate states must be an array")
        intermediates = tuple(_decode_state(item) for item in intermediates_value)
        if value["before_state_digest"] != _state_digest(before):
            raise ValueError("before state digest mismatch")
        if value["desired_state_digest"] != _state_digest(desired):
            raise ValueError("desired state digest mismatch")
        rollback = AttachmentRef(
            _string(value["rollback_attachment_digest"]),
            "managed-file-before-state",
            "managed-file-before-v1",
        )
        desired_digest = value["desired_attachment_digest"]
        desired_attachment = (
            None
            if desired_digest is None
            else AttachmentRef(
                _string(desired_digest),
                "managed-file-desired-content",
                "managed-file-content-v1",
            )
        )
        staged_metadata = AttachmentRef(
            _string(value["staged_metadata_attachment_digest"]),
            "managed-file-staged-object",
            "managed-file-object-v1",
        )
        cleanup_metadata = AttachmentRef(
            _string(value["cleanup_metadata_attachment_digest"]),
            "managed-file-cleanup-object",
            "managed-file-object-v1",
        )
        staged = _decode_object(value["staged_object"], "staged object")
        cleanup = _decode_object(value["cleanup_object"], "cleanup object")
        binding = PreparationBinding(
            _string(value["device_id"]),
            _string(value["binding_digest"]),
            _string(value["run_id"]),
            _string(value["resource_id"]),
            _string(value["change_id"]),
        )
        address = ResolvedManagedAddress(
            _string(value["address"]),
            ManagedPath(_string(value["managed_path"])),
        )
        _validate_before_attachment(
            attachments.read_attachment(rollback),
            binding,
            address,
            before,
        )
        if desired_attachment is not None:
            _validate_desired_attachment(
                attachments.read_attachment(desired_attachment),
                desired,
            )
        _validate_object_attachment(
            attachments.read_attachment(staged_metadata),
            binding,
            staged,
            "staged object",
        )
        _validate_object_attachment(
            attachments.read_attachment(cleanup_metadata),
            binding,
            cleanup,
            "cleanup object",
        )
        prepared = PreparedManagedFile(
            binding,
            address,
            before,
            desired,
            intermediates,
            rollback,
            desired_attachment,
            staged_metadata,
            cleanup_metadata,
            staged,
            cleanup,
            manifest_bytes,
            "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
            True,
        )
        if intermediates != _required_intermediates(before, desired):
            raise ValueError("preparation intermediate states are incomplete")
        return prepared
    except (KeyError, TypeError, ValueError) as error:
        raise PreparationError("prepared managed-file evidence is invalid") from error


def prepare_managed_file(
    *,
    reader: ManagedFileReader,
    attachments: AttachmentStore,
    address: ResolvedManagedAddress,
    binding: PreparationBinding,
    expected_before: NormalizedResourceState,
    desired: NormalizedResourceState,
    desired_content: bytes | None,
    allowed_intermediates: tuple[NormalizedResourceState, ...],
    staged_object: PreparationObject,
    cleanup_object: PreparationObject,
    read_limit: int,
) -> PreparedManagedFile:
    _validate_binding(binding)
    _validate_object(staged_object, "staged object")
    _validate_object(cleanup_object, "cleanup object")
    expected_staged_digest = (
        desired.content_digest
        if desired.presence.value == "present"
        else "sha256:absent"
    )
    if (
        staged_object.content_digest != expected_staged_digest
        or cleanup_object.object_id == staged_object.object_id
    ):
        raise PreparationError("staged and cleanup object bindings are inconsistent")
    before = observe_managed_file(reader, address, read_limit=read_limit)
    if not before.safe:
        raise PreparationError("before-state observation is unsafe or unreadable")
    if before.state != expected_before:
        raise StalePrecondition("managed-file precondition changed before preparation")
    desired_attachment = _publish_desired_attachment(
        attachments, desired, desired_content
    )
    attachment_payload = _before_attachment(before, binding)
    reference = _publish_verified(
        attachments,
        "managed-file-before-state",
        "managed-file-before-v1",
        attachment_payload,
    )
    staged_metadata = canonical_document_bytes(
        {
            "binding_digest": binding.binding_digest,
            "change_id": binding.change_id,
            "content_digest": staged_object.content_digest,
            "device_id": binding.device_id,
            "object_id": staged_object.object_id,
            "resource_id": binding.resource_id,
            "run_id": binding.run_id,
            "schema_version": 1,
        }
    )
    staged_metadata_attachment = _publish_verified(
        attachments,
        "managed-file-staged-object",
        "managed-file-object-v1",
        staged_metadata,
    )
    cleanup_metadata = canonical_document_bytes(
        {
            "binding_digest": binding.binding_digest,
            "change_id": binding.change_id,
            "content_digest": cleanup_object.content_digest,
            "device_id": binding.device_id,
            "object_id": cleanup_object.object_id,
            "resource_id": binding.resource_id,
            "run_id": binding.run_id,
            "schema_version": 1,
        }
    )
    cleanup_metadata_attachment = _publish_verified(
        attachments,
        "managed-file-cleanup-object",
        "managed-file-object-v1",
        cleanup_metadata,
    )
    rechecked = observe_managed_file(reader, address, read_limit=read_limit)
    if not rechecked.safe or rechecked.state != expected_before:
        raise StalePrecondition("managed-file precondition changed during preparation")
    if len(set(allowed_intermediates)) != len(allowed_intermediates):
        raise PreparationError(
            "allowed intermediate states must be complete and unique"
        )
    required_intermediates = _required_intermediates(expected_before, desired)
    if allowed_intermediates != required_intermediates:
        raise PreparationError("preparation intermediate states are incomplete")
    manifest = canonical_document_bytes(
        {
            "address": address.logical_address,
            "allowed_intermediate_states": [
                _state_value(state) for state in allowed_intermediates
            ],
            "before_state": _state_value(expected_before),
            "before_state_digest": _state_digest(expected_before),
            "binding_digest": binding.binding_digest,
            "change_id": binding.change_id,
            "cleanup_metadata_attachment_digest": (cleanup_metadata_attachment.digest),
            "cleanup_object": {
                "content_digest": cleanup_object.content_digest,
                "object_id": cleanup_object.object_id,
            },
            "desired_attachment_digest": (
                desired_attachment.digest if desired_attachment is not None else None
            ),
            "desired_state": _state_value(desired),
            "desired_state_digest": _state_digest(desired),
            "device_id": binding.device_id,
            "managed_path": address.device_path.value,
            "resource_id": binding.resource_id,
            "rollback_attachment_digest": reference.digest,
            "run_id": binding.run_id,
            "schema_version": 1,
            "staged_metadata_attachment_digest": staged_metadata_attachment.digest,
            "staged_object": {
                "content_digest": staged_object.content_digest,
                "object_id": staged_object.object_id,
            },
        }
    )
    return PreparedManagedFile(
        binding,
        address,
        expected_before,
        desired,
        allowed_intermediates,
        reference,
        desired_attachment,
        staged_metadata_attachment,
        cleanup_metadata_attachment,
        staged_object,
        cleanup_object,
        manifest,
        "sha256:" + hashlib.sha256(manifest).hexdigest(),
        True,
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


def normalized_state_digest(state: NormalizedResourceState) -> str:
    payload = canonical_document_bytes(_state_value(state))
    return "sha256:" + hashlib.sha256(payload).hexdigest()


_state_digest = normalized_state_digest


def _state_value(state: NormalizedResourceState) -> dict[str, object]:
    return {
        "content_digest": state.content_digest,
        "entry_kind": state.entry_kind,
        "managed_mode": state.managed_mode,
        "presence": state.presence.value,
    }


def _decode_state(value: object) -> NormalizedResourceState:
    if not isinstance(value, dict) or set(value) != {
        "content_digest",
        "entry_kind",
        "managed_mode",
        "presence",
    }:
        raise ValueError("normalized Resource state is malformed")
    content_digest = value["content_digest"]
    entry_kind = value["entry_kind"]
    managed_mode = value["managed_mode"]
    if content_digest is not None and not isinstance(content_digest, str):
        raise ValueError("state content digest is invalid")
    if entry_kind is not None and not isinstance(entry_kind, str):
        raise ValueError("state entry kind is invalid")
    if managed_mode is not None and type(managed_mode) is not int:
        raise ValueError("state mode is invalid")
    return NormalizedResourceState(
        Presence(_string(value["presence"])),
        entry_kind,
        content_digest,
        managed_mode,
    )


def _decode_object(value: object, label: str) -> PreparationObject:
    if not isinstance(value, dict) or set(value) != {"content_digest", "object_id"}:
        raise ValueError(f"{label} is malformed")
    result = PreparationObject(
        _string(value["object_id"]),
        _string(value["content_digest"]),
    )
    _validate_object(result, label)
    return result


def _validate_before_attachment(
    payload: bytes,
    binding: PreparationBinding,
    address: ResolvedManagedAddress,
    before: NormalizedResourceState,
) -> None:
    value = decode_json_object(payload)
    expected_fields = {
        "binding_digest",
        "change_id",
        "codec",
        "content_hex",
        "content_digest",
        "device_id",
        "entry_kind",
        "logical_address",
        "managed_mode",
        "managed_path",
        "presence",
        "resource_id",
        "run_id",
        "schema_version",
        "size",
    }
    if set(value) != expected_fields:
        raise ValueError("before-state attachment fields are invalid")
    content_hex = value["content_hex"]
    if content_hex is not None and not isinstance(content_hex, str):
        raise ValueError("before-state content is invalid")
    content = bytes.fromhex(content_hex) if isinstance(content_hex, str) else None
    if (
        value["schema_version"] != 1
        or value["codec"] != "managed-file-before-v1"
        or value["device_id"] != binding.device_id
        or value["binding_digest"] != binding.binding_digest
        or value["run_id"] != binding.run_id
        or value["resource_id"] != binding.resource_id
        or value["change_id"] != binding.change_id
        or value["logical_address"] != address.logical_address
        or value["managed_path"] != address.device_path.value
        or value["presence"] != before.presence.value
        or value["entry_kind"] != before.entry_kind
        or value["content_digest"] != before.content_digest
        or value["managed_mode"] != before.managed_mode
        or value["size"] != len(content or b"")
        or (
            content is not None
            and "sha256:" + hashlib.sha256(content).hexdigest() != before.content_digest
        )
    ):
        raise ValueError("before-state attachment binding is invalid")


def _validate_desired_attachment(
    payload: bytes,
    desired: NormalizedResourceState,
) -> None:
    if (
        desired.presence is not Presence.PRESENT
        or desired.content_digest != "sha256:" + hashlib.sha256(payload).hexdigest()
    ):
        raise ValueError("desired-content attachment is invalid")


def _validate_object_attachment(
    payload: bytes,
    binding: PreparationBinding,
    expected: PreparationObject,
    label: str,
) -> None:
    value = decode_json_object(payload)
    if set(value) != {
        "binding_digest",
        "change_id",
        "content_digest",
        "device_id",
        "object_id",
        "resource_id",
        "run_id",
        "schema_version",
    } or value != {
        "binding_digest": binding.binding_digest,
        "change_id": binding.change_id,
        "content_digest": expected.content_digest,
        "device_id": binding.device_id,
        "object_id": expected.object_id,
        "resource_id": binding.resource_id,
        "run_id": binding.run_id,
        "schema_version": 1,
    }:
        raise ValueError(f"{label} attachment binding is invalid")


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("expected non-empty string")
    return value


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


def _publish_desired_attachment(
    attachments: AttachmentStore,
    desired: NormalizedResourceState,
    desired_content: bytes | None,
) -> AttachmentRef | None:
    if desired.presence.value == "absent":
        if desired_content is not None or desired.content_digest is not None:
            raise PreparationError("absent desired state cannot carry content")
        return None
    if desired_content is None:
        raise PreparationError("present desired state requires exact content")
    digest = "sha256:" + hashlib.sha256(desired_content).hexdigest()
    if digest != desired.content_digest:
        raise PreparationError("desired content digest does not match")
    return _publish_verified(
        attachments,
        "managed-file-desired-content",
        "managed-file-content-v1",
        desired_content,
    )


def _publish_verified(
    attachments: AttachmentStore,
    kind: str,
    codec: str,
    payload: bytes,
) -> AttachmentRef:
    try:
        reference = attachments.attach(kind, codec, payload)
        loaded = attachments.read_attachment(reference)
    except Exception as error:
        raise PreparationError(f"{kind} verification failed") from error
    if loaded != payload:
        raise PreparationError(f"{kind} verification failed")
    return reference


def _validate_binding(binding: PreparationBinding) -> None:
    if not all(
        (
            binding.device_id,
            binding.binding_digest,
            binding.run_id,
            binding.resource_id,
            binding.change_id,
        )
    ):
        raise PreparationError("preparation binding is incomplete")


def _validate_object(value: PreparationObject, label: str) -> None:
    if (
        not value.object_id
        or "/" in value.object_id
        or not _is_digest(value.content_digest)
    ):
        raise PreparationError(f"{label} binding is invalid")


def _is_digest(value: str) -> bool:
    return value.startswith("sha256:") and len(value) > 7
