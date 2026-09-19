"""Safe resolution from logical Kodi VFS addresses to Device paths."""

import posixpath
from dataclasses import dataclass

from coreelec_reconciler.domain.configuration import ProfileRootCapability


@dataclass(frozen=True, slots=True)
class ManagedPath:
    value: str

    def __post_init__(self) -> None:
        if (
            not self.value.startswith("/")
            or posixpath.normpath(self.value) != self.value
        ):
            raise ValueError("managed path must be normalized and absolute")


@dataclass(frozen=True, slots=True)
class ResolvedManagedAddress:
    logical_address: str
    device_path: ManagedPath


class PathResolutionError(ValueError):
    pass


KodiProfileRootCapability = ProfileRootCapability


def resolve_special_profile_path(
    logical_address: str,
    capability: ProfileRootCapability | None,
) -> ResolvedManagedAddress:
    prefix = "special://profile/"
    if not logical_address.startswith(prefix):
        raise PathResolutionError("unsupported State Address scheme")
    if capability is None:
        raise PathResolutionError("Kodi profile-root capability is unavailable")
    suffix = logical_address[len(prefix) :]
    if not suffix or suffix.startswith("/"):
        raise PathResolutionError("State Address suffix is invalid")
    components = suffix.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise PathResolutionError("State Address traversal is forbidden")
    try:
        root = ManagedPath(capability.path).value
    except ValueError as error:
        raise PathResolutionError("profile root is not a safe absolute path") from error
    candidate = posixpath.normpath(posixpath.join(root, *components))
    if candidate == root or not candidate.startswith(root.rstrip("/") + "/"):
        raise PathResolutionError("resolved path escapes the profile root")
    return ResolvedManagedAddress(logical_address, ManagedPath(candidate))
