import pytest

from coreelec_reconciler.resource_types.managed_file.paths import (
    KodiProfileRootCapability,
    ManagedPath,
    PathResolutionError,
    resolve_special_profile_path,
)


def test_resolves_profile_address_while_preserving_logical_identity() -> None:
    result = resolve_special_profile_path(
        "special://profile/playlists/video/NewShows.xsp",
        KodiProfileRootCapability("/storage/.kodi/userdata"),
    )

    assert result.logical_address == ("special://profile/playlists/video/NewShows.xsp")
    assert result.device_path == ManagedPath(
        "/storage/.kodi/userdata/playlists/video/NewShows.xsp"
    )


@pytest.mark.parametrize(
    ("address", "capability"),
    [
        ("file:///storage/example", KodiProfileRootCapability("/storage")),
        ("special://profile/../secrets", KodiProfileRootCapability("/x")),
        ("special://profile/a//b", KodiProfileRootCapability("/x")),
        ("special://profile/a", None),
    ],
)
def test_rejects_unknown_missing_and_traversing_paths(
    address: str,
    capability: KodiProfileRootCapability | None,
) -> None:
    with pytest.raises(PathResolutionError):
        resolve_special_profile_path(address, capability)


@pytest.mark.parametrize("value", ["relative/path", "/a/../b", "/a/./b"])
def test_managed_path_requires_normalized_absolute_value(value: str) -> None:
    with pytest.raises(ValueError):
        ManagedPath(value)
