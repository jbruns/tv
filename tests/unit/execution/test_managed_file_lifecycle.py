import hashlib
import json

import pytest

from coreelec_reconciler.domain.execution import (
    MarkerCheckpoint,
    MutationDisposition,
    MutationReceipt,
    NormalizedResourceState,
    Presence,
    RemoteMarkerPhase,
    RemoteOwnershipIdentity,
    ResourceMutationIntent,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.execution.managed_file import (
    ManagedFileExecutor,
    VerificationStatus,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ManagedPath,
    ResolvedManagedAddress,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    PreparationObject,
    PreparedManagedFile,
)
from coreelec_reconciler.transports.interfaces import EntryKind
from tests.fakes.run_infrastructure import FakeAttachments
from tests.fakes.runtime import FakeManagedEntry, FakeManagedFiles

PATH = "/storage/.kodi/userdata/playlists/video/NewShows.xsp"
ADDRESS = ResolvedManagedAddress(
    "special://profile/playlists/video/NewShows.xsp", ManagedPath(PATH)
)


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _state(content: bytes, mode: int = 0o644) -> NormalizedResourceState:
    return NormalizedResourceState(Presence.PRESENT, "regular", _digest(content), mode)


def _marker(_: object) -> MarkerCheckpoint:
    identity = RemoteOwnershipIdentity(
        DeviceId("living-room.ugoos"),
        RunId("019950f8-4c00-7000-8000-000000000601"),
        WorkspaceId("workspace:019950f8-4c00-7000-8000-000000000601"),
        "019950f8-4c00-7000-8000-000000000101",
        "sha256:" + "b" * 64,
        "sha256:" + "a" * 64,
        "boot.opaque",
    )
    return MarkerCheckpoint(
        identity,
        "sha256:" + "d" * 64,
        3,
        RemoteMarkerPhase.MUTATING,
        "sha256:" + "e" * 64,
    )


def _prepared(
    attachments: FakeAttachments,
    before: NormalizedResourceState,
    desired: NormalizedResourceState,
    before_content: bytes | None,
    desired_content: bytes | None,
) -> PreparedManagedFile:
    before_payload = json.dumps(
        {"content_hex": before_content.hex() if before_content is not None else None}
    ).encode()
    rollback = attachments.attach("managed-file-before-state", "v1", before_payload)
    desired_ref = (
        attachments.attach("managed-file-desired-content", "v1", desired_content)
        if desired_content is not None
        else None
    )
    metadata = attachments.attach("metadata", "v1", b"metadata")
    intermediates: tuple[NormalizedResourceState, ...] = ()
    if (
        before.presence is Presence.PRESENT
        and desired.presence is Presence.PRESENT
        and before.content_digest != desired.content_digest
        and before.managed_mode != desired.managed_mode
    ):
        intermediates = (
            NormalizedResourceState(
                Presence.PRESENT,
                "regular",
                desired.content_digest,
                before.managed_mode,
            ),
        )
    return PreparedManagedFile(
        ADDRESS,
        before,
        desired,
        intermediates,
        rollback,
        desired_ref,
        metadata,
        metadata,
        PreparationObject("stage-change", desired.content_digest or "sha256:absent"),
        PreparationObject("cleanup-change", "sha256:" + "c" * 64),
        b"manifest",
        "sha256:" + "f" * 64,
        True,
    )


@pytest.mark.parametrize(
    ("before_content", "before_mode", "desired_content", "desired_mode", "operations"),
    [
        (None, None, b"new", 0o644, ("stage_write", "atomic_replace")),
        (b"old", 0o644, b"new", 0o644, ("stage_write", "atomic_replace")),
        (b"same", 0o600, b"same", 0o644, ("chmod",)),
        (b"old", 0o644, None, None, ("remove",)),
        (b"same", 0o644, b"same", 0o644, ()),
    ],
)
def test_complete_managed_file_lifecycle(
    before_content: bytes | None,
    before_mode: int | None,
    desired_content: bytes | None,
    desired_mode: int | None,
    operations: tuple[str, ...],
) -> None:
    device = FakeManagedFiles()
    if before_content is not None:
        device.put(
            PATH,
            FakeManagedEntry(
                kind=EntryKind.REGULAR,
                mode=before_mode or 0,
                content=before_content,
            ),
        )
    attachments = FakeAttachments()
    before = (
        _state(before_content, before_mode or 0)
        if before_content is not None
        else NormalizedResourceState(Presence.ABSENT, None, None, None)
    )
    desired = (
        _state(desired_content, desired_mode or 0)
        if desired_content is not None
        else NormalizedResourceState(Presence.ABSENT, None, None, None)
    )
    intents: list[ResourceMutationIntent] = []
    executor = ManagedFileExecutor(device, attachments, intents.append, _marker)
    result = executor.apply(
        _prepared(attachments, before, desired, before_content, desired_content),
        resource_id="skin.playlist.new-shows",
        change_id="change-1",
        rollback_approved=True,
    )

    assert result.verification.status is VerificationStatus.MATCHED
    assert (
        tuple(
            receipt.operation_id.rsplit(".", 1)[-1]
            for receipt in result.mutation.receipts
        )
        == operations
    )
    assert len(intents) == len(result.mutation.receipts)
    assert all(
        receipt.disposition is MutationDisposition.APPLIED
        for receipt in result.mutation.receipts
    )


def test_lost_ack_is_resolved_by_fresh_verification() -> None:
    device = FakeManagedFiles()
    attachments = FakeAttachments()
    before = NormalizedResourceState(Presence.ABSENT, None, None, None)
    desired = _state(b"new")
    device.fault("atomic_replace", MutationDisposition.AMBIGUOUS)
    result = ManagedFileExecutor(
        device, attachments, lambda intent: None, _marker
    ).apply(
        _prepared(attachments, before, desired, None, b"new"),
        resource_id="skin.playlist.new-shows",
        change_id="change-1",
        rollback_approved=True,
    )

    assert result.converged
    assert result.mutation.receipts[-1].disposition is MutationDisposition.AMBIGUOUS
    assert not result.recovery_required


def test_known_mismatch_is_rolled_back_only_from_a_run_produced_state() -> None:
    device = FakeManagedFiles()
    device.put(
        PATH, FakeManagedEntry(kind=EntryKind.REGULAR, mode=0o644, content=b"old")
    )
    attachments = FakeAttachments()
    before = _state(b"old")
    desired = _state(b"new")
    device.fault("atomic_replace", MutationDisposition.DEFINITELY_NOT_APPLIED)
    result = ManagedFileExecutor(
        device, attachments, lambda intent: None, _marker
    ).apply(
        _prepared(attachments, before, desired, b"old", b"new"),
        resource_id="skin.playlist.new-shows",
        change_id="change-1",
        rollback_approved=True,
    )

    assert result.verification.status is VerificationStatus.MISMATCH
    assert result.rollback is not None
    assert result.rollback_verification is not None
    assert result.rollback_verification.status is VerificationStatus.MATCHED


def test_third_party_state_is_not_overwritten_by_rollback() -> None:
    class RacingFiles(FakeManagedFiles):
        def atomic_replace(
            self, staged_path: str, destination: str, operation_id: str
        ) -> MutationReceipt:
            receipt = super().atomic_replace(staged_path, destination, operation_id)
            self.put(destination, FakeManagedEntry(0o644, b"third-party"))
            return receipt

    device = RacingFiles()
    device.put(PATH, FakeManagedEntry(0o644, b"old"))
    attachments = FakeAttachments()
    result = ManagedFileExecutor(
        device, attachments, lambda intent: None, _marker
    ).apply(
        _prepared(attachments, _state(b"old"), _state(b"new"), b"old", b"new"),
        resource_id="skin.playlist.new-shows",
        change_id="change-1",
        rollback_approved=True,
    )

    assert result.verification.status is VerificationStatus.MISMATCH
    assert result.rollback is None
    assert device.entry(PATH) == FakeManagedEntry(0o644, b"third-party")
