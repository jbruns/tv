"""Least-authority Device transport contracts."""

from .interfaces import (
    DeviceCapabilitySnapshot,
    DeviceIdentity,
    DeviceSession,
    DeviceSessionFactory,
    EntryKind,
    FileMetadata,
    ManagedFileReader,
    ReadFailure,
    ReadResult,
)
from .remote_ownership import (
    AuthorityBlocked,
    AuthorityConflict,
    AuthorityError,
    RemoteAuthorityBackend,
    RemoteObject,
    RemoteObjectKind,
)

__all__ = [
    "AuthorityBlocked",
    "AuthorityConflict",
    "AuthorityError",
    "DeviceCapabilitySnapshot",
    "DeviceIdentity",
    "DeviceSession",
    "DeviceSessionFactory",
    "EntryKind",
    "FileMetadata",
    "ManagedFileReader",
    "ReadFailure",
    "ReadResult",
    "RemoteAuthorityBackend",
    "RemoteObject",
    "RemoteObjectKind",
]
