"""Durable remote Device ownership over a least-authority backend."""

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coreelec_reconciler.domain.execution import (
    MutationReceipt,
    Presence,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RemoteOwnershipSnapshot,
    RemoteQuarantine,
)
from coreelec_reconciler.reporting.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)


class RemoteObjectKind(StrEnum):
    ABSENT = "absent"
    REGULAR = "regular"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RemoteObject:
    kind: RemoteObjectKind
    payload: bytes | None = None


class RemoteAuthorityBackend(Protocol):
    def inspect_ownership(self, device_key: str) -> RemoteObject: ...

    def inspect_quarantine(self, device_key: str) -> RemoteObject: ...

    def create_ownership(
        self,
        device_key: str,
        payload: bytes,
        expected_digest: str,
    ) -> None: ...

    def replace_ownership(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None: ...

    def remove_ownership(
        self,
        device_key: str,
        expected_digest: str,
    ) -> MutationReceipt: ...

    def convert_to_quarantine(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None: ...


class AuthorityError(RuntimeError):
    pass


class AuthorityBlocked(AuthorityError):
    pass


class AuthorityConflict(AuthorityError):
    pass


class RemoteAuthority:
    def __init__(self, backend: RemoteAuthorityBackend) -> None:
        self._backend = backend

    def inspect(self, device_id: str) -> RemoteOwnershipSnapshot:
        device_key = _device_key(device_id)
        quarantine = self._backend.inspect_quarantine(device_key)
        if quarantine.kind is RemoteObjectKind.UNKNOWN:
            return _unknown_snapshot()
        if quarantine.kind is not RemoteObjectKind.ABSENT:
            return _unknown_snapshot()
        record = self._backend.inspect_ownership(device_key)
        if record.kind is RemoteObjectKind.ABSENT:
            return RemoteOwnershipSnapshot(
                Presence.ABSENT, None, None, None, None, None, None
            )
        if record.kind is RemoteObjectKind.UNKNOWN:
            return _unknown_snapshot()
        if record.kind is not RemoteObjectKind.REGULAR or record.payload is None:
            return _unknown_snapshot()
        try:
            return _decode_marker(record.payload)
        except ValueError:
            return _unknown_snapshot()

    def inspect_quarantine(self, device_id: str) -> Presence:
        record = self._backend.inspect_quarantine(_device_key(device_id))
        if record.kind is RemoteObjectKind.ABSENT:
            return Presence.ABSENT
        if record.kind is RemoteObjectKind.REGULAR and record.payload is not None:
            return Presence.PRESENT
        return Presence.UNKNOWN

    def acquire_exclusive(
        self,
        identity: RemoteOwnershipIdentity,
        ownership_token: bytes,
        *,
        updated_at: str,
    ) -> RemoteOwnership:
        token_digest = _digest(ownership_token)
        if (
            self._backend.inspect_quarantine(_device_key(identity.device_id.value)).kind
            is not RemoteObjectKind.ABSENT
        ):
            raise AuthorityBlocked("remote quarantine blocks acquisition")
        marker = _marker_value(
            identity, token_digest, 1, RemoteMarkerPhase.ACQUIRED, None, updated_at
        )
        payload = canonical_document_bytes(marker)
        digest = _digest(payload)
        try:
            self._backend.create_ownership(
                _device_key(identity.device_id.value), payload, digest
            )
        except AuthorityConflict:
            raise
        except Exception as error:
            raise AuthorityBlocked(
                "remote ownership durability was not proven"
            ) from error
        snapshot = self.inspect(identity.device_id.value)
        ownership = RemoteOwnership(
            identity, token_digest, 1, RemoteMarkerPhase.ACQUIRED, digest
        )
        _require_snapshot(snapshot, ownership)
        return ownership

    def compare_and_update(
        self,
        ownership: RemoteOwnership,
        ownership_token: bytes,
        expected_phase: RemoteMarkerPhase,
        next_phase: RemoteMarkerPhase,
        manifest_digest: str | None,
        *,
        updated_at: str,
    ) -> RemoteOwnership:
        self.verify_checkpoint(ownership, expected_phase)
        if _digest(ownership_token) != ownership.token_digest:
            raise AuthorityConflict("ownership token does not match")
        next_ownership = RemoteOwnership(
            ownership.identity,
            ownership.token_digest,
            ownership.generation + 1,
            next_phase,
            "",
        )
        marker = _marker_value(
            ownership.identity,
            ownership.token_digest,
            next_ownership.generation,
            next_phase,
            manifest_digest,
            updated_at,
        )
        payload = canonical_document_bytes(marker)
        next_ownership = RemoteOwnership(
            next_ownership.identity,
            next_ownership.token_digest,
            next_ownership.generation,
            next_ownership.phase,
            _digest(payload),
        )
        try:
            self._backend.replace_ownership(
                _device_key(ownership.identity.device_id.value),
                ownership.marker_digest,
                payload,
                next_ownership.marker_digest,
            )
        except Exception as error:
            if isinstance(error, AuthorityConflict):
                raise
            raise AuthorityBlocked("remote marker durability was not proven") from error
        _require_snapshot(
            self.inspect(ownership.identity.device_id.value), next_ownership
        )
        return next_ownership

    def verify_checkpoint(
        self,
        ownership: RemoteOwnership,
        expected_phase: RemoteMarkerPhase,
    ) -> RemoteOwnershipSnapshot:
        if ownership.phase is not expected_phase:
            raise AuthorityConflict("expected marker phase does not match handle")
        snapshot = self.inspect(ownership.identity.device_id.value)
        _require_snapshot(snapshot, ownership)
        return snapshot

    def release(
        self,
        ownership: RemoteOwnership,
        ownership_token: bytes,
        terminal_receipt_digest: str,
    ) -> MutationReceipt:
        del terminal_receipt_digest
        self.verify_checkpoint(ownership, RemoteMarkerPhase.TERMINAL_RELEASE_PENDING)
        if _digest(ownership_token) != ownership.token_digest:
            raise AuthorityConflict("ownership token does not match")
        return self._backend.remove_ownership(
            _device_key(ownership.identity.device_id.value), ownership.marker_digest
        )

    def quarantine(
        self,
        ownership: RemoteOwnership,
        ownership_token: bytes,
        incident_receipt_digest: str,
        *,
        updated_at: str,
    ) -> RemoteQuarantine:
        self.verify_checkpoint(ownership, RemoteMarkerPhase.QUARANTINE_PENDING)
        if _digest(ownership_token) != ownership.token_digest:
            raise AuthorityConflict("ownership token does not match")
        value = {
            "binding_digest": ownership.identity.binding_digest,
            "boot_id": ownership.identity.boot_id,
            "device_id": ownership.identity.device_id.value,
            "incident_receipt_digest": incident_receipt_digest,
            "plan_full_digest": ownership.identity.plan_full_digest,
            "plan_id": ownership.identity.plan_id,
            "run_id": ownership.identity.run_id.value,
            "schema_version": 1,
            "updated_at": updated_at,
            "workspace_id": ownership.identity.workspace_id.value,
        }
        payload = canonical_document_bytes(value)
        digest = _digest(payload)
        self._backend.convert_to_quarantine(
            _device_key(ownership.identity.device_id.value),
            ownership.marker_digest,
            payload,
            digest,
        )
        return RemoteQuarantine(ownership.identity, incident_receipt_digest, digest)


def _marker_value(
    identity: RemoteOwnershipIdentity,
    token_digest: str,
    generation: int,
    phase: RemoteMarkerPhase,
    manifest_digest: str | None,
    updated_at: str,
) -> dict[str, object]:
    return {
        "binding_digest": identity.binding_digest,
        "boot_id": identity.boot_id,
        "device_id": identity.device_id.value,
        "generation": generation,
        "manifest_digest": manifest_digest,
        "phase": phase.value,
        "plan_full_digest": identity.plan_full_digest,
        "plan_id": identity.plan_id,
        "run_id": identity.run_id.value,
        "schema_version": 1,
        "token_digest": token_digest,
        "updated_at": updated_at,
        "workspace_id": identity.workspace_id.value,
    }


def _decode_marker(payload: bytes) -> RemoteOwnershipSnapshot:
    value = decode_json_object(payload)
    required = {
        "binding_digest",
        "boot_id",
        "device_id",
        "generation",
        "manifest_digest",
        "phase",
        "plan_full_digest",
        "plan_id",
        "run_id",
        "schema_version",
        "token_digest",
        "updated_at",
        "workspace_id",
    }
    if set(value) != required or value["schema_version"] != 1:
        raise ValueError("marker shape is invalid")
    strings = {
        key: value[key]
        for key in required - {"generation", "manifest_digest", "schema_version"}
    }
    if not all(isinstance(item, str) and item for item in strings.values()):
        raise ValueError("marker values are invalid")
    generation = value["generation"]
    manifest = value["manifest_digest"]
    if type(generation) is not int or generation < 1:
        raise ValueError("marker generation is invalid")
    if manifest is not None and not isinstance(manifest, str):
        raise ValueError("marker manifest is invalid")
    from coreelec_reconciler.domain.execution import WorkspaceId
    from coreelec_reconciler.domain.identifiers import DeviceId, RunId

    identity = RemoteOwnershipIdentity(
        DeviceId(str(value["device_id"])),
        RunId(str(value["run_id"])),
        WorkspaceId(str(value["workspace_id"])),
        str(value["plan_id"]),
        str(value["plan_full_digest"]),
        str(value["binding_digest"]),
        str(value["boot_id"]),
    )
    return RemoteOwnershipSnapshot(
        Presence.PRESENT,
        generation,
        _digest(payload),
        str(value["token_digest"]),
        identity,
        RemoteMarkerPhase(str(value["phase"])),
        manifest,
    )


def _require_snapshot(
    snapshot: RemoteOwnershipSnapshot,
    ownership: RemoteOwnership,
) -> None:
    if (
        snapshot.presence is not Presence.PRESENT
        or snapshot.identity != ownership.identity
        or snapshot.token_digest != ownership.token_digest
        or snapshot.generation != ownership.generation
        or snapshot.phase is not ownership.phase
        or snapshot.marker_digest != ownership.marker_digest
    ):
        raise AuthorityConflict("remote marker checkpoint does not match")


def _unknown_snapshot() -> RemoteOwnershipSnapshot:
    return RemoteOwnershipSnapshot(Presence.UNKNOWN, None, None, None, None, None, None)


def _device_key(device_id: str) -> str:
    return hashlib.sha256(device_id.encode()).hexdigest()


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
