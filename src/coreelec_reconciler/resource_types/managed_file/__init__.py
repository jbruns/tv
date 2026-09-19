"""Managed-file resolution, observation, and preparation."""

from .observation import ManagedFileObservation, observe_managed_file
from .paths import KodiProfileRootCapability, ManagedPath, ResolvedManagedAddress
from .preparation import PreparedManagedFile, prepare_managed_file

__all__ = [
    "KodiProfileRootCapability",
    "ManagedFileObservation",
    "ManagedPath",
    "PreparedManagedFile",
    "ResolvedManagedAddress",
    "observe_managed_file",
    "prepare_managed_file",
]
