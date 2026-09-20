"""Durable remote Device ownership over a least-authority backend."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.domain.execution import (
    ActiveDeviceRun,
    DeviceLease,
    MutationReceipt,
    Presence,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RemoteOwnershipSnapshot,
    RemoteQuarantine,
    RevisionLease,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.execution.run_store import CorruptRunStore
from coreelec_reconciler.transports import remote_ownership as remote_port


class OwnershipTokenSource(Protocol):
    def new_ownership_token(self) -> bytes: ...


class AuthorityRunStore(Protocol):
    def acquire_device(self, device_id: DeviceId) -> DeviceLease: ...

    def release_device(self, lease: DeviceLease) -> None: ...

    def find_active_by_device(
        self, device_id: DeviceId
    ) -> tuple[ActiveDeviceRun, ...]: ...

    def rebuild_active_device_index(self) -> tuple[ActiveDeviceRun, ...]: ...

    def create_run(
        self,
        device_lease: DeviceLease,
        run_id: RunId,
        device_id: DeviceId,
        ownership_token: bytes,
        ownership_token_digest: str,
        initial_payload: bytes,
    ) -> tuple[RevisionLease, WorkspaceId]: ...

    def release_run(self, lease: RevisionLease) -> None: ...

    def load_ownership_token(self, lease: RevisionLease) -> bytes: ...


@dataclass(frozen=True, slots=True)
class AuthorityAcquisitionRequest:
    device_id: DeviceId
    run_id: RunId
    initial_revision: Callable[[str], bytes]
    identity: Callable[[WorkspaceId], RemoteOwnershipIdentity]
    updated_at: str


@dataclass(frozen=True, slots=True)
class AcquiredAuthority:
    device_lease: DeviceLease
    revision_lease: RevisionLease
    workspace_id: WorkspaceId
    ownership: RemoteOwnership


class AuthorityCoordinator:
    """Enforce local exclusion and durable token/index state before remote create."""

    def __init__(
        self,
        run_store: AuthorityRunStore,
        runtime: OwnershipTokenSource,
        backend: remote_port.RemoteAuthorityBackend,
    ) -> None:
        self._run_store = run_store
        self._runtime = runtime
        self._remote = _RemoteAuthority(backend)

    def acquire(self, request: AuthorityAcquisitionRequest) -> AcquiredAuthority:
        device_lease = self._run_store.acquire_device(request.device_id)
        revision_lease: RevisionLease | None = None
        try:
            active = self._find_active_fail_closed(request.device_id)
            if active:
                raise remote_port.AuthorityBlocked(
                    "another local authority Run is active"
                )
            token = self._runtime.new_ownership_token()
            token_digest = _digest(token)
            initial_payload = request.initial_revision(token_digest)
            revision_lease, workspace_id = self._run_store.create_run(
                device_lease,
                request.run_id,
                request.device_id,
                token,
                token_digest,
                initial_payload,
            )
            identity = request.identity(workspace_id)
            if (
                identity.device_id != request.device_id
                or identity.run_id != request.run_id
                or identity.workspace_id != workspace_id
            ):
                raise remote_port.AuthorityConflict(
                    "remote identity does not match local Run"
                )
            ownership = self._remote.acquire_exclusive(
                identity, token, updated_at=request.updated_at
            )
            return AcquiredAuthority(
                device_lease,
                revision_lease,
                workspace_id,
                ownership,
            )
        except Exception:
            if revision_lease is not None:
                self._run_store.release_run(revision_lease)
            self._run_store.release_device(device_lease)
            raise

    def _find_active_fail_closed(
        self, device_id: DeviceId
    ) -> tuple[ActiveDeviceRun, ...]:
        try:
            return self._run_store.find_active_by_device(device_id)
        except CorruptRunStore:
            self._run_store.rebuild_active_device_index()
            return self._run_store.find_active_by_device(device_id)

    def checkpoint(
        self,
        authority: AcquiredAuthority,
        expected_phase: RemoteMarkerPhase,
        next_phase: RemoteMarkerPhase,
        evidence_digest: str | None,
        *,
        updated_at: str,
    ) -> AcquiredAuthority:
        token = self._run_store.load_ownership_token(authority.revision_lease)
        ownership = self._remote.compare_and_update(
            authority.ownership,
            token,
            expected_phase,
            next_phase,
            evidence_digest,
            updated_at=updated_at,
        )
        return AcquiredAuthority(
            authority.device_lease,
            authority.revision_lease,
            authority.workspace_id,
            ownership,
        )

    def release(
        self,
        authority: AcquiredAuthority,
        terminal_receipt_digest: str,
    ) -> MutationReceipt:
        token = self._run_store.load_ownership_token(authority.revision_lease)
        return self._remote.release(authority.ownership, token, terminal_receipt_digest)

    def quarantine(
        self,
        authority: AcquiredAuthority,
        incident_receipt_digest: str,
        *,
        updated_at: str,
    ) -> RemoteQuarantine:
        token = self._run_store.load_ownership_token(authority.revision_lease)
        return self._remote.quarantine(
            authority.ownership,
            token,
            incident_receipt_digest,
            updated_at=updated_at,
        )


_LEGAL_PHASE_TRANSITIONS: dict[RemoteMarkerPhase, frozenset[RemoteMarkerPhase]] = {
    RemoteMarkerPhase.ACQUIRED: frozenset(
        {
            RemoteMarkerPhase.PREPARING,
            RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            RemoteMarkerPhase.QUARANTINE_PENDING,
        }
    ),
    RemoteMarkerPhase.PREPARING: frozenset(
        {
            RemoteMarkerPhase.PREPARED,
            RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            RemoteMarkerPhase.QUARANTINE_PENDING,
        }
    ),
    RemoteMarkerPhase.PREPARED: frozenset(
        {
            RemoteMarkerPhase.MUTATING,
            RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            RemoteMarkerPhase.QUARANTINE_PENDING,
        }
    ),
    RemoteMarkerPhase.MUTATING: frozenset(
        {
            RemoteMarkerPhase.VERIFYING,
            RemoteMarkerPhase.EFFECT,
            RemoteMarkerPhase.ROLLING_BACK,
            RemoteMarkerPhase.QUARANTINE_PENDING,
        }
    ),
    RemoteMarkerPhase.VERIFYING: frozenset(
        {
            RemoteMarkerPhase.EFFECT,
            RemoteMarkerPhase.ROLLING_BACK,
            RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            RemoteMarkerPhase.QUARANTINE_PENDING,
        }
    ),
    RemoteMarkerPhase.EFFECT: frozenset(
        {
            RemoteMarkerPhase.VERIFYING,
            RemoteMarkerPhase.ROLLING_BACK,
            RemoteMarkerPhase.QUARANTINE_PENDING,
        }
    ),
    RemoteMarkerPhase.ROLLING_BACK: frozenset(
        {
            RemoteMarkerPhase.VERIFYING,
            RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            RemoteMarkerPhase.QUARANTINE_PENDING,
        }
    ),
    RemoteMarkerPhase.TERMINAL_RELEASE_PENDING: frozenset(),
    RemoteMarkerPhase.QUARANTINE_PENDING: frozenset(),
}


class _RemoteAuthority:
    def __init__(self, backend: remote_port.RemoteAuthorityBackend) -> None:
        self._backend = backend

    def inspect(self, device_id: str) -> RemoteOwnershipSnapshot:
        device_key = _device_key(device_id)
        quarantine = self._backend.inspect_quarantine(device_key)
        if quarantine.kind is remote_port.RemoteObjectKind.UNKNOWN:
            return _unknown_snapshot()
        if quarantine.kind is not remote_port.RemoteObjectKind.ABSENT:
            return _unknown_snapshot()
        record = self._backend.inspect_ownership(device_key)
        if record.kind is remote_port.RemoteObjectKind.ABSENT:
            return RemoteOwnershipSnapshot(
                Presence.ABSENT, None, None, None, None, None, None
            )
        if record.kind is remote_port.RemoteObjectKind.UNKNOWN:
            return _unknown_snapshot()
        if (
            record.kind is not remote_port.RemoteObjectKind.REGULAR
            or record.payload is None
        ):
            return _unknown_snapshot()
        try:
            return _decode_marker(record.payload)
        except ValueError:
            return _unknown_snapshot()

    def inspect_quarantine(self, device_id: str) -> Presence:
        record = self._backend.inspect_quarantine(_device_key(device_id))
        if record.kind is remote_port.RemoteObjectKind.ABSENT:
            return Presence.ABSENT
        if (
            record.kind is remote_port.RemoteObjectKind.REGULAR
            and record.payload is not None
        ):
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
            is not remote_port.RemoteObjectKind.ABSENT
        ):
            raise remote_port.AuthorityBlocked("remote quarantine blocks acquisition")
        marker = _marker_value(
            identity, token_digest, 1, RemoteMarkerPhase.ACQUIRED, None, updated_at
        )
        payload = canonical_document_bytes(marker)
        digest = _digest(payload)
        try:
            self._backend.create_ownership_if_unowned_and_not_quarantined(
                _device_key(identity.device_id.value), payload, digest
            )
        except remote_port.AuthorityConflict:
            raise
        except Exception as error:
            raise remote_port.AuthorityBlocked(
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
            raise remote_port.AuthorityConflict("ownership token does not match")
        if next_phase not in _LEGAL_PHASE_TRANSITIONS[expected_phase]:
            raise remote_port.AuthorityConflict(
                "remote marker phase transition is illegal"
            )
        if (
            next_phase is RemoteMarkerPhase.TERMINAL_RELEASE_PENDING
            and not _is_evidence_digest(manifest_digest)
        ):
            raise remote_port.AuthorityConflict(
                "release requires durable terminal evidence"
            )
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
            if isinstance(error, remote_port.AuthorityConflict):
                raise
            raise remote_port.AuthorityBlocked(
                "remote marker durability was not proven"
            ) from error
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
            raise remote_port.AuthorityConflict(
                "expected marker phase does not match handle"
            )
        snapshot = self.inspect(ownership.identity.device_id.value)
        _require_snapshot(snapshot, ownership)
        return snapshot

    def release(
        self,
        ownership: RemoteOwnership,
        ownership_token: bytes,
        terminal_receipt_digest: str,
    ) -> MutationReceipt:
        snapshot = self.verify_checkpoint(
            ownership, RemoteMarkerPhase.TERMINAL_RELEASE_PENDING
        )
        if _digest(ownership_token) != ownership.token_digest:
            raise remote_port.AuthorityConflict("ownership token does not match")
        if (
            not _is_evidence_digest(terminal_receipt_digest)
            or snapshot.manifest_digest != terminal_receipt_digest
        ):
            raise remote_port.AuthorityConflict(
                "terminal release evidence does not match"
            )
        return self._backend.remove_ownership(
            _device_key(ownership.identity.device_id.value),
            ownership.marker_digest,
            terminal_receipt_digest,
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
            raise remote_port.AuthorityConflict("ownership token does not match")
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
        raise remote_port.AuthorityConflict("remote marker checkpoint does not match")


def _unknown_snapshot() -> RemoteOwnershipSnapshot:
    return RemoteOwnershipSnapshot(Presence.UNKNOWN, None, None, None, None, None, None)


def _device_key(device_id: str) -> str:
    return hashlib.sha256(device_id.encode()).hexdigest()


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _is_evidence_digest(value: str | None) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) > 7
