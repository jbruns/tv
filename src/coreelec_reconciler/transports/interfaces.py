"""Typed, least-authority interfaces shared by production and fake adapters."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coreelec_reconciler.config.device import DeviceSessionParameters
from coreelec_reconciler.domain.configuration import ResolvedDevice
from coreelec_reconciler.domain.identifiers import DeviceId


class EntryKind(StrEnum):
    REGULAR = "regular"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


class ReadFailureCode(StrEnum):
    NOT_FOUND = "not_found"
    UNREADABLE = "unreadable"
    TOO_LARGE = "too_large"
    INCOMPLETE = "incomplete"
    TRANSPORT = "transport"
    UNSAFE = "unsafe"


@dataclass(frozen=True, slots=True)
class ReadFailure:
    code: ReadFailureCode
    safe_message: str


@dataclass(frozen=True, slots=True)
class FileMetadata:
    kind: EntryKind
    mode: int
    size: int


@dataclass(frozen=True, slots=True)
class ReadResult:
    value: bytes | FileMetadata | None
    failure: ReadFailure | None = None

    def __post_init__(self) -> None:
        if (self.failure is None) == (self.value is None):
            raise ValueError("ReadResult must contain exactly one result")


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    device_id: DeviceId
    binding_digest: str
    boot_id: str


@dataclass(frozen=True, slots=True)
class DeviceCapabilitySnapshot:
    kodi_profile_root: str | None
    atomic_replace_over_existing: bool


class ManagedFileReader(Protocol):
    def lstat(self, path: str) -> ReadResult: ...

    def read(self, path: str, limit: int) -> ReadResult: ...


class DeviceSession(Protocol):
    @property
    def identity(self) -> DeviceIdentity: ...

    @property
    def capabilities(self) -> DeviceCapabilitySnapshot: ...

    @property
    def managed_files(self) -> ManagedFileReader: ...

    def close(self) -> None: ...


class DeviceSessionFactory(Protocol):
    def open(
        self,
        parameters: DeviceSessionParameters,
        required_capabilities: frozenset[str],
    ) -> DeviceSession: ...


class DeviceConnectionPolicy(Protocol):
    @property
    def device(self) -> ResolvedDevice: ...
