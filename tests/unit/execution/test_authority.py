import json

import pytest

from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    Presence,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.execution.authority import (
    AuthorityBlocked,
    AuthorityConflict,
    RemoteAuthority,
    RemoteObject,
    RemoteObjectKind,
)
from coreelec_reconciler.reporting.canonical_json import canonical_document_bytes
from tests.fakes.device import FakeDevice


def identity(**changes: str) -> RemoteOwnershipIdentity:
    values = {
        "device_id": "device.test",
        "run_id": "run.test",
        "workspace_id": "workspace:test",
        "plan_id": "plan.test",
        "plan_full_digest": "sha256:plan",
        "binding_digest": "sha256:binding",
        "boot_id": "boot.test",
    }
    values.update(changes)
    return RemoteOwnershipIdentity(
        DeviceId(values["device_id"]),
        RunId(values["run_id"]),
        WorkspaceId(values["workspace_id"]),
        values["plan_id"],
        values["plan_full_digest"],
        values["binding_digest"],
        values["boot_id"],
    )


def acquire() -> tuple[FakeDevice, RemoteAuthority, RemoteOwnership]:
    device = FakeDevice()
    authority = RemoteAuthority(device)
    owned = authority.acquire_exclusive(
        identity(), b"secret-token", updated_at="2026-09-19T00:00:00Z"
    )
    return device, authority, owned


def test_exclusive_acquisition_has_one_winner_and_no_token_in_marker() -> None:
    device, authority, owned = acquire()

    assert authority.inspect("device.test").presence is Presence.PRESENT
    assert b"secret-token" not in (device.inspector().ownership().payload or b"")
    with pytest.raises(AuthorityConflict):
        authority.acquire_exclusive(
            identity(run_id="run.other"),
            b"other-token",
            updated_at="2026-09-19T00:00:01Z",
        )
    assert owned.generation == 1


@pytest.mark.parametrize(
    "kind",
    [
        RemoteObjectKind.SYMLINK,
        RemoteObjectKind.DIRECTORY,
        RemoteObjectKind.OTHER,
        RemoteObjectKind.UNKNOWN,
    ],
)
def test_foreign_nonregular_or_unknown_marker_fails_closed(
    kind: RemoteObjectKind,
) -> None:
    device = FakeDevice()
    device.set_remote_ownership(RemoteObject(kind, b"foreign"))
    authority = RemoteAuthority(device)

    assert authority.inspect("device.test").presence is Presence.UNKNOWN
    with pytest.raises(AuthorityConflict):
        authority.acquire_exclusive(
            identity(), b"token", updated_at="2026-09-19T00:00:00Z"
        )


def test_malformed_marker_is_unknown_and_blocks() -> None:
    device = FakeDevice()
    device.set_remote_ownership(RemoteObject(RemoteObjectKind.REGULAR, b"{}"))
    authority = RemoteAuthority(device)
    assert authority.inspect("device.test").presence is Presence.UNKNOWN


def test_remote_durability_failure_never_grants_authority() -> None:
    device = FakeDevice()
    device.fail_remote_durability()
    with pytest.raises(AuthorityBlocked):
        RemoteAuthority(device).acquire_exclusive(
            identity(), b"token", updated_at="2026-09-19T00:00:00Z"
        )
    assert device.inspector().ownership().kind is RemoteObjectKind.ABSENT


def test_checkpoint_durability_failure_retains_prior_marker() -> None:
    device, authority, owned = acquire()
    original = device.inspector().ownership()
    device.fail_remote_durability()

    with pytest.raises(AuthorityBlocked):
        authority.compare_and_update(
            owned,
            b"secret-token",
            RemoteMarkerPhase.ACQUIRED,
            RemoteMarkerPhase.PREPARING,
            None,
            updated_at="2026-09-19T00:00:01Z",
        )

    assert device.inspector().ownership() == original


def test_checkpoint_update_release_and_quarantine_are_durable() -> None:
    device, authority, owned = acquire()
    prepared = authority.compare_and_update(
        owned,
        b"secret-token",
        RemoteMarkerPhase.ACQUIRED,
        RemoteMarkerPhase.PREPARED,
        "sha256:manifest",
        updated_at="2026-09-19T00:00:01Z",
    )
    releasing = authority.compare_and_update(
        prepared,
        b"secret-token",
        RemoteMarkerPhase.PREPARED,
        RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
        "sha256:manifest",
        updated_at="2026-09-19T00:00:02Z",
    )
    receipt = authority.release(releasing, b"secret-token", "sha256:terminal")
    assert receipt.disposition is MutationDisposition.APPLIED
    assert device.inspector().ownership().kind is RemoteObjectKind.ABSENT

    owned = authority.acquire_exclusive(
        identity(run_id="run.second"),
        b"second-token",
        updated_at="2026-09-19T00:00:03Z",
    )
    pending = authority.compare_and_update(
        owned,
        b"second-token",
        RemoteMarkerPhase.ACQUIRED,
        RemoteMarkerPhase.QUARANTINE_PENDING,
        None,
        updated_at="2026-09-19T00:00:04Z",
    )
    quarantine = authority.quarantine(
        pending,
        b"second-token",
        "sha256:incident",
        updated_at="2026-09-19T00:00:05Z",
    )
    assert quarantine.incident_receipt_digest == "sha256:incident"
    assert device.inspector().quarantine().kind is RemoteObjectKind.REGULAR
    assert authority.inspect_quarantine("device.test") is Presence.PRESENT
    assert authority.inspect("device.test").presence is Presence.UNKNOWN
    with pytest.raises(AuthorityBlocked):
        authority.acquire_exclusive(
            identity(run_id="run.third"),
            b"third-token",
            updated_at="2026-09-19T00:00:06Z",
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("device_id", "device.other"),
        ("run_id", "run.other"),
        ("workspace_id", "workspace:other"),
        ("plan_id", "plan.other"),
        ("plan_full_digest", "sha256:other-plan"),
        ("binding_digest", "sha256:other-binding"),
        ("boot_id", "boot.other"),
        ("token_digest", "sha256:other-token"),
        ("generation", 99),
        ("phase", "preparing"),
    ],
)
def test_checkpoint_rejects_every_identity_phase_generation_mismatch(
    field: str, replacement: str | int
) -> None:
    device, authority, owned = acquire()
    payload = device.inspector().ownership().payload
    assert payload is not None
    value = json.loads(payload)
    value[field] = replacement
    device.set_remote_ownership(
        RemoteObject(RemoteObjectKind.REGULAR, canonical_document_bytes(value))
    )

    with pytest.raises(AuthorityConflict):
        authority.verify_checkpoint(owned, RemoteMarkerPhase.ACQUIRED)


def test_checkpoint_rejects_wrong_handle_marker_digest_and_token_credential() -> None:
    _, authority, owned = acquire()
    with pytest.raises(AuthorityConflict):
        authority.verify_checkpoint(
            RemoteOwnership(
                owned.identity,
                owned.token_digest,
                owned.generation,
                owned.phase,
                "sha256:wrong",
            ),
            RemoteMarkerPhase.ACQUIRED,
        )
    with pytest.raises(AuthorityConflict):
        authority.compare_and_update(
            owned,
            b"wrong-token",
            RemoteMarkerPhase.ACQUIRED,
            RemoteMarkerPhase.PREPARING,
            None,
            updated_at="2026-09-19T00:00:01Z",
        )
