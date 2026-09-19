"""Fresh, bounded, lstat-based managed-file observation."""

import hashlib
from dataclasses import dataclass

from coreelec_reconciler.domain.execution import NormalizedResourceState, Presence
from coreelec_reconciler.transports.interfaces import (
    EntryKind,
    FileMetadata,
    ManagedFileReader,
    ReadFailure,
    ReadFailureCode,
)

from .paths import ResolvedManagedAddress


@dataclass(frozen=True, slots=True)
class ManagedFileObservation:
    address: ResolvedManagedAddress
    state: NormalizedResourceState
    content: bytes | None
    failure: ReadFailure | None = None

    @property
    def safe(self) -> bool:
        return self.failure is None


def observe_managed_file(
    reader: ManagedFileReader,
    address: ResolvedManagedAddress,
    *,
    read_limit: int,
) -> ManagedFileObservation:
    metadata_result = reader.lstat(address.device_path.value)
    if metadata_result.failure is not None:
        if metadata_result.failure.code is ReadFailureCode.NOT_FOUND:
            return ManagedFileObservation(
                address,
                NormalizedResourceState(Presence.ABSENT, None, None, None),
                None,
            )
        return _failed(address, metadata_result.failure)
    metadata = metadata_result.value
    if not isinstance(metadata, FileMetadata):
        return _failed(
            address, ReadFailure(ReadFailureCode.TRANSPORT, "Invalid metadata")
        )
    if metadata.kind is not EntryKind.REGULAR:
        return _failed(
            address,
            ReadFailure(ReadFailureCode.UNSAFE, "Managed entry is not a regular file"),
            metadata.kind.value,
        )
    if metadata.size > read_limit:
        return _failed(
            address,
            ReadFailure(
                ReadFailureCode.TOO_LARGE, "Managed file exceeds the read limit"
            ),
            metadata.kind.value,
        )
    content_result = reader.read(address.device_path.value, read_limit)
    if content_result.failure is not None:
        return _failed(address, content_result.failure, metadata.kind.value)
    content = content_result.value
    if not isinstance(content, bytes) or len(content) != metadata.size:
        return _failed(
            address,
            ReadFailure(ReadFailureCode.INCOMPLETE, "Managed file read was incomplete"),
            metadata.kind.value,
        )
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    return ManagedFileObservation(
        address,
        NormalizedResourceState(
            Presence.PRESENT,
            metadata.kind.value,
            digest,
            metadata.mode & 0o7777,
        ),
        content,
    )


def _failed(
    address: ResolvedManagedAddress,
    failure: ReadFailure,
    entry_kind: str | None = None,
) -> ManagedFileObservation:
    return ManagedFileObservation(
        address,
        NormalizedResourceState(Presence.UNKNOWN, entry_kind, None, None),
        None,
        failure,
    )
