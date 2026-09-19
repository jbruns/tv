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


def test_complete_preparation_captures_verified_attachment_and_manifest() -> None:
    device = FakeDevice()
    device.put(ADDRESS.device_path.value, FakeEntry(EntryKind.REGULAR, 0o644, b"old"))
    attachments = FakeAttachments()
    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    desired = NormalizedResourceState(
        Presence.PRESENT, "regular", "sha256:desired", 0o644
    )
    intermediate = NormalizedResourceState(
        Presence.PRESENT, "regular", "sha256:desired", 0o600
    )

    prepared = prepare_managed_file(
        reader=device,
        attachments=attachments,
        address=ADDRESS,
        binding=BINDING,
        expected_before=before,
        desired=desired,
        allowed_intermediates=(intermediate,),
        read_limit=100,
    )

    assert prepared.before == before
    assert prepared.desired == desired
    assert prepared.allowed_intermediates == (intermediate,)
    assert b'"content_hex":"6f6c64"' in attachments.read_attachment(
        prepared.rollback_attachment
    )
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
            allowed_intermediates=(),
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
        allowed_intermediates=(),
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
            allowed_intermediates=(before, before),
            read_limit=100,
        )


def test_missing_reachable_content_then_mode_state_blocks_preparation() -> None:
    device = FakeDevice()
    device.put(ADDRESS.device_path.value, FakeEntry(EntryKind.REGULAR, 0o600, b"old"))
    before = observe_managed_file(device, ADDRESS, read_limit=100).state
    desired = NormalizedResourceState(
        Presence.PRESENT, "regular", "sha256:desired", 0o644
    )

    with pytest.raises(PreparationError, match="reachable intermediate"):
        prepare_managed_file(
            reader=device,
            attachments=FakeAttachments(),
            address=ADDRESS,
            binding=BINDING,
            expected_before=before,
            desired=desired,
            allowed_intermediates=(),
            read_limit=100,
        )
