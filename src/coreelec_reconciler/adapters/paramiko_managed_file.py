"""No-follow, bounded Paramiko SFTP managed-file operations."""

import errno
import hashlib
import stat
from contextlib import suppress

import paramiko

from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    MutationReceipt,
)
from coreelec_reconciler.transports.interfaces import (
    EntryKind,
    FileMetadata,
    ReadFailure,
    ReadFailureCode,
    ReadResult,
)


class ParamikoManagedFiles:
    def __init__(self, sftp: paramiko.SFTPClient) -> None:
        self._sftp = sftp
        self.atomic_replace_supported = callable(getattr(sftp, "posix_rename", None))

    def lstat(self, path: str) -> ReadResult:
        try:
            value = self._sftp.lstat(path)
        except FileNotFoundError:
            return _read_failure(ReadFailureCode.NOT_FOUND, "Entry is absent")
        except PermissionError:
            return _read_failure(ReadFailureCode.UNREADABLE, "Entry is unreadable")
        except EOFError, paramiko.SSHException, OSError:
            return _read_failure(
                ReadFailureCode.TRANSPORT, "Entry metadata unavailable"
            )
        mode = value.st_mode
        if mode is None or value.st_size is None:
            return _read_failure(ReadFailureCode.UNSAFE, "Entry metadata is incomplete")
        return ReadResult(FileMetadata(_kind(mode), stat.S_IMODE(mode), value.st_size))

    def read(self, path: str, limit: int) -> ReadResult:
        metadata = self.lstat(path)
        if metadata.failure is not None:
            return metadata
        assert isinstance(metadata.value, FileMetadata)
        if metadata.value.kind is not EntryKind.REGULAR:
            return _read_failure(ReadFailureCode.UNSAFE, "Entry is not a regular file")
        if metadata.value.size > limit:
            return _read_failure(ReadFailureCode.TOO_LARGE, "Entry exceeds read limit")
        handle: paramiko.SFTPFile | None = None
        payload = bytearray()
        try:
            handle = self._sftp.open(path, "rb")
            remaining = metadata.value.size
            while remaining:
                chunk = handle.read(min(65_536, remaining))
                if not chunk:
                    return _read_failure(
                        ReadFailureCode.INCOMPLETE, "Entry read was incomplete"
                    )
                payload.extend(chunk)
                remaining -= len(chunk)
            if handle.read(1):
                return _read_failure(
                    ReadFailureCode.INCOMPLETE, "Entry changed during read"
                )
            return ReadResult(bytes(payload))
        except FileNotFoundError:
            return _read_failure(ReadFailureCode.NOT_FOUND, "Entry is absent")
        except PermissionError:
            return _read_failure(ReadFailureCode.UNREADABLE, "Entry is unreadable")
        except EOFError, paramiko.SSHException, OSError:
            return _read_failure(ReadFailureCode.TRANSPORT, "Entry read failed")
        finally:
            if handle is not None:
                handle.close()

    def stage_write(
        self, path: str, content: bytes, mode: int, operation_id: str
    ) -> MutationReceipt:
        handle: paramiko.SFTPFile | None = None
        started = False
        try:
            handle = self._sftp.open(path, "x")
            started = True
            handle.write(content)
            handle.flush()
            handle.close()
            handle = None
            self._sftp.chmod(path, mode)
            return _receipt(operation_id, MutationDisposition.APPLIED)
        except Exception as error:
            return _receipt(operation_id, _mutation_failure(error, started))
        finally:
            if handle is not None:
                with suppress(Exception):
                    handle.close()

    def chmod(self, path: str, mode: int, operation_id: str) -> MutationReceipt:
        return self._single_mutation(operation_id, self._sftp.chmod, path, mode)

    def atomic_replace(
        self, staged_path: str, destination: str, operation_id: str
    ) -> MutationReceipt:
        if not self.atomic_replace_supported:
            return _receipt(operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED)
        try:
            self._sftp.posix_rename(staged_path, destination)
            return _receipt(operation_id, MutationDisposition.APPLIED)
        except OSError as error:
            if str(error).casefold() == "operation unsupported":
                self.atomic_replace_supported = False
                return _receipt(
                    operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
                )
            return _receipt(operation_id, _mutation_failure(error, True))
        except Exception as error:
            return _receipt(operation_id, _mutation_failure(error, True))

    def remove(self, path: str, operation_id: str) -> MutationReceipt:
        return self._single_mutation(operation_id, self._sftp.remove, path)

    def restore(
        self,
        path: str,
        content: bytes | None,
        mode: int | None,
        operation_id: str,
    ) -> MutationReceipt:
        if content is None:
            return self.remove(path, operation_id)
        suffix = hashlib.sha256(operation_id.encode()).hexdigest()[:24]
        directory, _, name = path.rpartition("/")
        staged = f"{directory}/.{name}.{suffix}.restore"
        staged_receipt = self.stage_write(staged, content, mode or 0, operation_id)
        if staged_receipt.disposition is not MutationDisposition.APPLIED:
            return staged_receipt
        replaced = self.atomic_replace(staged, path, operation_id)
        if replaced.disposition is not MutationDisposition.APPLIED:
            return replaced
        if mode is None:
            return replaced
        return self.chmod(path, mode, operation_id)

    def cleanup(self, path: str, operation_id: str) -> MutationReceipt:
        return self.remove(path, operation_id)

    def _single_mutation(
        self, operation_id: str, operation: object, *args: object
    ) -> MutationReceipt:
        try:
            assert callable(operation)
            operation(*args)
            return _receipt(operation_id, MutationDisposition.APPLIED)
        except Exception as error:
            return _receipt(operation_id, _mutation_failure(error, True))


def _kind(mode: int) -> EntryKind:
    if stat.S_ISREG(mode):
        return EntryKind.REGULAR
    if stat.S_ISDIR(mode):
        return EntryKind.DIRECTORY
    if stat.S_ISLNK(mode):
        return EntryKind.SYMLINK
    return EntryKind.OTHER


def _read_failure(code: ReadFailureCode, message: str) -> ReadResult:
    return ReadResult(None, ReadFailure(code, message))


def _receipt(operation_id: str, disposition: MutationDisposition) -> MutationReceipt:
    return MutationReceipt(operation_id, disposition)


def _mutation_failure(error: Exception, started: bool) -> MutationDisposition:
    if not started:
        return MutationDisposition.DEFINITELY_NOT_APPLIED
    if isinstance(error, (EOFError, paramiko.SSHException, TimeoutError)):
        return MutationDisposition.AMBIGUOUS
    if isinstance(error, OSError) and error.errno in {
        errno.ENOENT,
        errno.EEXIST,
        errno.EACCES,
        errno.EPERM,
        errno.ENOTDIR,
        errno.EISDIR,
        errno.EOPNOTSUPP,
    }:
        return MutationDisposition.DEFINITELY_NOT_APPLIED
    return MutationDisposition.AMBIGUOUS
