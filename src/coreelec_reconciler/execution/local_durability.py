"""Private semantic durability adapters used by the filesystem RunStore."""

import fcntl
import os
import stat
from collections import defaultdict
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class DurabilityOperation(StrEnum):
    WRITE_PRIVATE = "write_private"
    FULL_SYNC_FILE = "full_sync_file"
    ATOMIC_REPLACE = "atomic_replace"
    ATOMIC_CREATE = "atomic_create"
    CREATE_PRIVATE_DIRECTORY = "create_private_directory"
    REMOVE_FILE = "remove_file"
    SYNC_DIRECTORY = "sync_directory"
    ACKNOWLEDGE = "acknowledge"


class DurabilityError(RuntimeError):
    pass


class AcknowledgementLost(DurabilityError):
    pass


class DestinationExists(DurabilityError):
    pass


class LocalDurability(Protocol):
    def write_private(self, object_id: str, payload: bytes) -> None: ...

    def full_sync_file(self, object_id: str) -> None: ...

    def atomic_replace(self, source_id: str, destination_id: str) -> None: ...

    def atomic_create(self, source_id: str, destination_id: str) -> None: ...

    def create_private_directory(self, directory_id: str) -> None: ...

    def remove_file(self, object_id: str) -> None: ...

    def sync_directory(self, directory_id: str) -> None: ...

    def acknowledge(self, operation_id: str) -> None: ...


class PosixLocalDurability:
    def write_private(self, object_id: str, payload: bytes) -> None:
        path = Path(object_id)
        parent_descriptor = _open_directory(path.parent)
        try:
            descriptor = _open_regular_at(
                parent_descriptor,
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(payload)
                    stream.flush()
            finally:
                os.close(descriptor)
        finally:
            os.close(parent_descriptor)

    def full_sync_file(self, object_id: str) -> None:
        path = Path(object_id)
        parent_descriptor = _open_directory(path.parent)
        try:
            descriptor = _open_regular_at(
                parent_descriptor,
                path.name,
                os.O_RDONLY,
            )
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
        finally:
            os.close(parent_descriptor)

    def atomic_replace(self, source_id: str, destination_id: str) -> None:
        source = Path(source_id)
        destination = Path(destination_id)
        if source.parent != destination.parent:
            raise DurabilityError("atomic replacement must stay in one directory")
        parent_descriptor = _open_directory(source.parent)
        try:
            source_stat = os.stat(
                source.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if not stat.S_ISREG(source_stat.st_mode):
                raise DurabilityError("atomic replacement source is unsafe")
            try:
                destination_stat = os.stat(
                    destination.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                if not stat.S_ISREG(destination_stat.st_mode):
                    raise DurabilityError("atomic replacement destination is unsafe")
            os.replace(
                source.name,
                destination.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
        except OSError as error:
            raise DurabilityError("atomic replacement failed safely") from error
        finally:
            os.close(parent_descriptor)

    def atomic_create(self, source_id: str, destination_id: str) -> None:
        source = Path(source_id)
        destination = Path(destination_id)
        if source.parent != destination.parent:
            raise DurabilityError("atomic creation must stay in one directory")
        parent_descriptor = _open_directory(source.parent)
        try:
            source_stat = os.stat(
                source.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if not stat.S_ISREG(source_stat.st_mode):
                raise DurabilityError("atomic creation source is unsafe")
            try:
                os.link(
                    source.name,
                    destination.name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                raise DestinationExists("atomic creation destination exists") from error
        except DestinationExists:
            raise
        except OSError as error:
            raise DurabilityError("atomic creation failed safely") from error
        finally:
            os.close(parent_descriptor)

    def create_private_directory(self, directory_id: str) -> None:
        path = Path(directory_id)
        parent_descriptor = _open_directory(path.parent)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            with suppress(FileExistsError):
                os.mkdir(path.name, 0o700, dir_fd=parent_descriptor)
            descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise DurabilityError("local object is not a directory")
                os.fchmod(descriptor, 0o700)
            finally:
                os.close(descriptor)
        except DurabilityError:
            raise
        except OSError as error:
            raise DurabilityError("private directory creation failed safely") from error
        finally:
            os.close(parent_descriptor)

    def remove_file(self, object_id: str) -> None:
        path = Path(object_id)
        parent_descriptor = _open_directory(path.parent)
        try:
            try:
                metadata = os.stat(
                    path.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return
            if not stat.S_ISREG(metadata.st_mode):
                raise DurabilityError("file removal target is unsafe")
            os.unlink(path.name, dir_fd=parent_descriptor)
        except DurabilityError:
            raise
        except OSError as error:
            raise DurabilityError("file removal failed safely") from error
        finally:
            os.close(parent_descriptor)

    def sync_directory(self, directory_id: str) -> None:
        descriptor = _open_directory(Path(directory_id))
        try:
            os.fsync(descriptor)
        except OSError as error:
            raise DurabilityError("directory sync failed safely") from error
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

    def atomic_create(self, source_id: str, destination_id: str) -> None:
        self._perform(
            DurabilityOperation.ATOMIC_CREATE,
            self._delegate.atomic_create,
            source_id,
            destination_id,
        )

    def create_private_directory(self, directory_id: str) -> None:
        self._perform(
            DurabilityOperation.CREATE_PRIVATE_DIRECTORY,
            self._delegate.create_private_directory,
            directory_id,
        )

    def remove_file(self, object_id: str) -> None:
        self._perform(
            DurabilityOperation.REMOVE_FILE,
            self._delegate.remove_file,
            object_id,
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


def read_regular_file(path: Path) -> bytes:
    """Read a regular file without following any path component symlink."""
    parent_descriptor = _open_directory(path.parent)
    try:
        descriptor = _open_regular_at(parent_descriptor, path.name, os.O_RDONLY)
        try:
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_descriptor)


def _open_directory(path: Path) -> int:
    if not path.is_absolute():
        raise DurabilityError("local durability paths must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            if component in {"", ".", ".."}:
                raise DurabilityError("unsafe local path component")
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except OSError as error:
        os.close(descriptor)
        raise DurabilityError("local path contains an unsafe component") from error
    except Exception:
        os.close(descriptor)
        raise


def _open_regular_at(
    parent_descriptor: int,
    name: str,
    flags: int,
    mode: int = 0o600,
) -> int:
    if not name or name in {".", ".."} or "/" in name:
        raise DurabilityError("unsafe local file name")
    safe_flags = flags | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, safe_flags, mode, dir_fd=parent_descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(descriptor)
            raise DurabilityError("local object is not a regular file")
        return descriptor
    except FileNotFoundError:
        raise
    except OSError as error:
        raise DurabilityError("local file operation failed safely") from error
