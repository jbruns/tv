import hashlib

import pytest

from coreelec_reconciler.domain.execution import (
    NormalizedResourceState,
    Presence,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    observe_managed_file,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ManagedPath,
    ResolvedManagedAddress,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    PreparationBinding,
    PreparationError,
    PreparationObject,
    StalePrecondition,
    prepare_managed_file,
    recheck_precondition,
)
from coreelec_reconciler.transports.interfaces import EntryKind
from tests.fakes.device import FakeDevice, FakeEntry
from tests.fakes.run_infrastructure import FakeAttachments

ADDRESS = ResolvedManagedAddress(
    "special://profile/playlists/video/NewShows.xsp",
    ManagedPath("/device/profile/playlists/video/NewShows.xsp"),
)
BINDING = PreparationBinding("device.test", "sha256:binding", "run-1", "r", "c")
DESIRED_DIGEST = "sha256:" + hashlib.sha256(b"new").hexdigest()
STAGED = PreparationObject("object.stage", DESIRED_DIGEST)
CLEANUP = PreparationObject("object.cleanup", DESIRED_DIGEST)


def test_complete_preparation_captures_verified_attachment_and_manifest() -> None:
    device = FakeDevice()
    device.put(ADDRESS.device_path.value, FakeEntry(EntryKind.REGULAR, 0o600, b"old"))
    attachments = FakeAttachments()
    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    desired = NormalizedResourceState(
        Presence.PRESENT, "regular", DESIRED_DIGEST, 0o644
    )
    intermediate = NormalizedResourceState(
        Presence.PRESENT, "regular", DESIRED_DIGEST, 0o600
    )

    prepared = prepare_managed_file(
        reader=device,
        attachments=attachments,
        address=ADDRESS,
        binding=BINDING,
        expected_before=before,
        desired=desired,
        desired_content=b"new",
        allowed_intermediates=(intermediate,),
        staged_object=STAGED,
        cleanup_object=CLEANUP,
        read_limit=100,
    )

    assert prepared.before == before
    assert prepared.desired == desired
    assert prepared.allowed_intermediates == (intermediate,)
    assert b'"content_hex":"6f6c64"' in attachments.read_attachment(
        prepared.rollback_attachment
    )
    assert prepared.desired_attachment is not None
    assert attachments.read_attachment(prepared.desired_attachment) == b"new"
    assert prepared.rollback_capable
    assert prepared.manifest_digest.startswith("sha256:")
    assert b"/device/profile/playlists/video/NewShows.xsp" in prepared.manifest_bytes


def test_attachment_corruption_blocks_preparation() -> None:
    device = FakeDevice()
    device.put(ADDRESS.device_path.value, FakeEntry(EntryKind.REGULAR, 0o644, b"old"))

    class CorruptingAttachments(FakeAttachments):
        def attach(self, kind: str, codec: str, payload: bytes):  # type: ignore[no-untyped-def]
            reference = super().attach(kind, codec, payload)
            self.corrupt(reference)
            return reference

    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    with pytest.raises((PreparationError, ValueError)):
        prepare_managed_file(
            reader=device,
            attachments=CorruptingAttachments(),
            address=ADDRESS,
            binding=BINDING,
            expected_before=before,
            desired=before,
            desired_content=b"old",
            allowed_intermediates=(),
            staged_object=PreparationObject(
                "object.stage", before.content_digest or ""
            ),
            cleanup_object=CLEANUP,
            read_limit=100,
        )


def test_final_recheck_rejects_stale_precondition() -> None:
    device = FakeDevice()
    device.put(ADDRESS.device_path.value, FakeEntry(EntryKind.REGULAR, 0o644, b"old"))
    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    prepared = prepare_managed_file(
        reader=device,
        attachments=FakeAttachments(),
        address=ADDRESS,
        binding=BINDING,
        expected_before=before,
        desired=before,
        desired_content=b"old",
        allowed_intermediates=(),
        staged_object=PreparationObject("object.stage", before.content_digest or ""),
        cleanup_object=CLEANUP,
        read_limit=100,
    )
    device.put(ADDRESS.device_path.value, FakeEntry(EntryKind.REGULAR, 0o644, b"other"))

    with pytest.raises(StalePrecondition):
        recheck_precondition(device, prepared, read_limit=100)


def test_duplicate_intermediate_state_is_incomplete_preparation() -> None:
    device = FakeDevice()
    device.put(ADDRESS.device_path.value, FakeEntry(EntryKind.REGULAR, 0o644, b"old"))
    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    with pytest.raises(PreparationError):
        prepare_managed_file(
            reader=device,
            attachments=FakeAttachments(),
            address=ADDRESS,
            binding=BINDING,
            expected_before=before,
            desired=before,
            desired_content=b"old",
            allowed_intermediates=(before, before),
            staged_object=PreparationObject(
                "object.stage", before.content_digest or ""
            ),
            cleanup_object=CLEANUP,
            read_limit=100,
        )


def test_missing_reachable_content_then_mode_state_blocks_preparation() -> None:
    device = FakeDevice()
    device.put(ADDRESS.device_path.value, FakeEntry(EntryKind.REGULAR, 0o600, b"old"))
    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    desired = NormalizedResourceState(
        Presence.PRESENT, "regular", DESIRED_DIGEST, 0o644
    )

    with pytest.raises(PreparationError, match="intermediate states"):
        prepare_managed_file(
            reader=device,
            attachments=FakeAttachments(),
            address=ADDRESS,
            binding=BINDING,
            expected_before=before,
            desired=desired,
            desired_content=b"new",
            allowed_intermediates=(),
            staged_object=STAGED,
            cleanup_object=CLEANUP,
            read_limit=100,
        )


@pytest.mark.parametrize(
    "binding",
    [
        PreparationBinding("", "sha256:binding", "run-1", "r", "c"),
        PreparationBinding("device.test", "", "run-1", "r", "c"),
        PreparationBinding("device.test", "sha256:binding", "", "r", "c"),
    ],
)
def test_missing_preparation_binding_is_rejected(
    binding: PreparationBinding,
) -> None:
    device = FakeDevice()
    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    with pytest.raises(PreparationError):
        prepare_managed_file(
            reader=device,
            attachments=FakeAttachments(),
            address=ADDRESS,
            binding=binding,
            expected_before=before,
            desired=before,
            desired_content=None,
            allowed_intermediates=(),
            staged_object=PreparationObject("object.stage", "sha256:absent"),
            cleanup_object=CLEANUP,
            read_limit=100,
        )


def test_desired_attachment_corruption_blocks_complete_preparation() -> None:
    device = FakeDevice()
    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    desired = NormalizedResourceState(
        Presence.PRESENT, "regular", DESIRED_DIGEST, 0o644
    )

    class CorruptDesiredAttachment(FakeAttachments):
        def attach(self, kind: str, codec: str, payload: bytes):  # type: ignore[no-untyped-def]
            reference = super().attach(kind, codec, payload)
            if kind == "managed-file-desired-content":
                self.corrupt(reference)
            return reference

    with pytest.raises(PreparationError):
        prepare_managed_file(
            reader=device,
            attachments=CorruptDesiredAttachment(),
            address=ADDRESS,
            binding=BINDING,
            expected_before=before,
            desired=desired,
            desired_content=b"new",
            allowed_intermediates=(),
            staged_object=STAGED,
            cleanup_object=CLEANUP,
            read_limit=100,
        )


def test_mismatched_stage_or_cleanup_binding_blocks_preparation() -> None:
    device = FakeDevice()
    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    desired = NormalizedResourceState(
        Presence.PRESENT, "regular", DESIRED_DIGEST, 0o644
    )

    with pytest.raises(PreparationError, match="bindings are inconsistent"):
        prepare_managed_file(
            reader=device,
            attachments=FakeAttachments(),
            address=ADDRESS,
            binding=BINDING,
            expected_before=before,
            desired=desired,
            desired_content=b"new",
            allowed_intermediates=(),
            staged_object=PreparationObject("object.stage", "sha256:wrong"),
            cleanup_object=CLEANUP,
            read_limit=100,
        )
