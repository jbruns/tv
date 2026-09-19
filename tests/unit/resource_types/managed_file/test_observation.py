import pytest

from coreelec_reconciler.domain.execution import Presence
from coreelec_reconciler.resource_types.managed_file.observation import (
    observe_managed_file,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ManagedPath,
    ResolvedManagedAddress,
)
from coreelec_reconciler.transports.interfaces import EntryKind, ReadFailureCode
from tests.fakes.device import FakeDevice, FakeEntry

ADDRESS = ResolvedManagedAddress(
    "special://profile/playlists/video/NewShows.xsp",
    ManagedPath("/device/profile/playlists/video/NewShows.xsp"),
)


def test_observes_fresh_regular_file_content_mode_size_and_digest() -> None:
    device = FakeDevice()
    device.put(ADDRESS.device_path.value, FakeEntry(EntryKind.REGULAR, 0o10644, b"abc"))

    observation = observe_managed_file(device, ADDRESS, read_limit=10)

    assert observation.safe
    assert observation.content == b"abc"
    assert observation.state.presence is Presence.PRESENT
    assert observation.state.entry_kind == "regular"
    assert observation.state.managed_mode == 0o644
    assert observation.state.content_digest == (
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_absence_is_distinct_from_unknown() -> None:
    observation = observe_managed_file(FakeDevice(), ADDRESS, read_limit=10)
    assert observation.safe
    assert observation.state.presence is Presence.ABSENT


@pytest.mark.parametrize(
    ("entry", "code"),
    [
        (FakeEntry(EntryKind.SYMLINK, 0o777), ReadFailureCode.UNSAFE),
        (FakeEntry(EntryKind.DIRECTORY, 0o755), ReadFailureCode.UNSAFE),
        (FakeEntry(EntryKind.OTHER, 0o600), ReadFailureCode.UNSAFE),
        (FakeEntry(EntryKind.REGULAR, 0o600, b"x", False), ReadFailureCode.UNREADABLE),
        (FakeEntry(EntryKind.REGULAR, 0o600, b"oversized"), ReadFailureCode.TOO_LARGE),
    ],
)
def test_unsafe_unreadable_and_oversized_state_fails_closed(
    entry: FakeEntry, code: ReadFailureCode
) -> None:
    device = FakeDevice()
    device.put(ADDRESS.device_path.value, entry)

    observation = observe_managed_file(device, ADDRESS, read_limit=3)

    assert not observation.safe
    assert observation.state.presence is Presence.UNKNOWN
    assert observation.failure is not None
    assert observation.failure.code is code
    assert observation.content is None
