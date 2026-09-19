"""Private semantic durability adapters used by the filesystem RunStore."""

import fcntl
import os
import stat
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class DurabilityOperation(StrEnum):
    WRITE_PRIVATE = "write_private"
    FULL_SYNC_FILE = "full_sync_file"
    ATOMIC_REPLACE = "atomic_replace"
    SYNC_DIRECTORY = "sync_directory"
    ACKNOWLEDGE = "acknowledge"


class DurabilityError(RuntimeError):
    pass


class AcknowledgementLost(DurabilityError):
    pass


class LocalDurability(Protocol):
    def write_private(self, object_id: str, payload: bytes) -> None: ...

    def full_sync_file(self, object_id: str) -> None: ...

    def atomic_replace(self, source_id: str, destination_id: str) -> None: ...

    def sync_directory(self, directory_id: str) -> None: ...

    def acknowledge(self, operation_id: str) -> None: ...


class PosixLocalDurability:
    def write_private(self, object_id: str, payload: bytes) -> None:
        path = Path(object_id)
        _require_safe_parent(path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
        finally:
            os.close(descriptor)

    def full_sync_file(self, object_id: str) -> None:
        descriptor = os.open(object_id, os.O_RDONLY)
        try:
            full_sync = getattr(fcntl, "F_FULLFSYNC", None)
            if full_sync is not None:
                try:
                    fcntl.fcntl(descriptor, full_sync)
                    return
                except OSError:
                    pass
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def atomic_replace(self, source_id: str, destination_id: str) -> None:
        os.replace(source_id, destination_id)

    def sync_directory(self, directory_id: str) -> None:
        descriptor = os.open(directory_id, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def acknowledge(self, operation_id: str) -> None:
        del operation_id


@dataclass(frozen=True, slots=True)
class ScriptedFault:
    operation: DurabilityOperation
    occurrence: int = 1
    acknowledgement_lost: bool = False


class ScriptedLocalDurability:
    """Fault-injecting adapter with a real durable delegate."""

    def __init__(
        self,
        faults: Iterable[ScriptedFault] = (),
        delegate: LocalDurability | None = None,
    ) -> None:
        self._delegate = delegate or PosixLocalDurability()
        self._faults = tuple(faults)
        self._counts: dict[DurabilityOperation, int] = defaultdict(int)

    def _before(self, operation: DurabilityOperation) -> ScriptedFault | None:
        self._counts[operation] += 1
        return next(
            (
                fault
                for fault in self._faults
                if fault.operation is operation
                and fault.occurrence == self._counts[operation]
            ),
            None,
        )

    def _perform(
        self,
        operation: DurabilityOperation,
        callback: object,
        *arguments: str | bytes,
    ) -> None:
        fault = self._before(operation)
        if fault is not None and not fault.acknowledgement_lost:
            raise DurabilityError(f"injected {operation.value} failure")
        callback(*arguments)  # type: ignore[operator]
        if fault is not None:
            raise AcknowledgementLost(f"lost {operation.value} acknowledgement")

    def write_private(self, object_id: str, payload: bytes) -> None:
        self._perform(
            DurabilityOperation.WRITE_PRIVATE,
            self._delegate.write_private,
            object_id,
            payload,
        )

    def full_sync_file(self, object_id: str) -> None:
        self._perform(
            DurabilityOperation.FULL_SYNC_FILE,
            self._delegate.full_sync_file,
            object_id,
        )

    def atomic_replace(self, source_id: str, destination_id: str) -> None:
        self._perform(
            DurabilityOperation.ATOMIC_REPLACE,
            self._delegate.atomic_replace,
            source_id,
            destination_id,
        )

    def sync_directory(self, directory_id: str) -> None:
        self._perform(
            DurabilityOperation.SYNC_DIRECTORY,
            self._delegate.sync_directory,
            directory_id,
        )

    def acknowledge(self, operation_id: str) -> None:
        self._perform(
            DurabilityOperation.ACKNOWLEDGE,
            self._delegate.acknowledge,
            operation_id,
        )


def _require_safe_parent(path: Path) -> None:
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise DurabilityError("durability destination parent is unsafe")
    if path.exists() and (path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode)):
        raise DurabilityError("durability destination is unsafe")
