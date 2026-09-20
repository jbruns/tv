"""No-follow reads and server-side CAS managed-file mutations."""

import stat
from typing import Protocol

import paramiko

from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    MutationReceipt,
    NormalizedResourceState,
)
from coreelec_reconciler.transports.interfaces import (
    EntryKind,
    FileMetadata,
    ReadFailure,
    ReadFailureCode,
    ReadResult,
)

from .managed_mutation_helper import ManagedMutationCode, ManagedMutationHelper


class NoFollowReader(Protocol):
    def read(self, path: str, limit: int) -> ReadResult: ...


class ParamikoManagedFiles:
    def __init__(
        self,
        sftp: paramiko.SFTPClient,
        no_follow_reader: NoFollowReader | None = None,
        mutation_helper: ManagedMutationHelper | None = None,
    ) -> None:
        self._sftp = sftp
        self._no_follow_reader = no_follow_reader
        self._mutation_helper = mutation_helper
        self.atomic_replace_supported = mutation_helper is not None

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
        if self._no_follow_reader is None:
            return _read_failure(
                ReadFailureCode.UNSAFE,
                "No-follow regular-file reads are unavailable",
            )
        return self._no_follow_reader.read(path, limit)

    def stage_write(
        self,
        path: str,
        content: bytes,
        mode: int,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        return self._mutate(
            operation_id,
            "stage",
            path,
            binding_digest,
            expected,
            content=content,
            mode=mode,
        )

    def chmod(
        self,
        path: str,
        mode: int,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        return self._mutate(
            operation_id,
            "chmod",
            path,
            binding_digest,
            expected,
            mode=mode,
        )

    def atomic_replace(
        self,
        staged_path: str,
        destination: str,
        operation_id: str,
        *,
        expected_staged: NormalizedResourceState,
        expected_destination: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        return self._mutate(
            operation_id,
            "replace",
            destination,
            binding_digest,
            expected_destination,
            staged_path=staged_path,
            expected_staged=expected_staged,
        )

    def remove(
        self,
        path: str,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        return self._mutate(operation_id, "remove", path, binding_digest, expected)

    def restore(
        self,
        path: str,
        content: bytes | None,
        mode: int | None,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        return self._mutate(
            operation_id,
            "restore",
            path,
            binding_digest,
            expected,
            content=content,
            mode=mode,
        )

    def cleanup(
        self,
        path: str,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        return self._mutate(operation_id, "cleanup", path, binding_digest, expected)

    def _mutate(
        self,
        operation_id: str,
        operation: str,
        path: str,
        binding_digest: str,
        expected: NormalizedResourceState,
        *,
        content: bytes | None = None,
        mode: int | None = None,
        staged_path: str | None = None,
        expected_staged: NormalizedResourceState | None = None,
    ) -> MutationReceipt:
        if self._mutation_helper is None:
            return _receipt(operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED)
        result = self._mutation_helper.mutate(
            operation,
            path,
            operation_id,
            binding_digest,
            expected,
            content=content,
            mode=mode,
            staged_path=staged_path,
            expected_staged=expected_staged,
        )
        disposition = (
            MutationDisposition.APPLIED
            if result.code is ManagedMutationCode.APPLIED
            else (
                MutationDisposition.AMBIGUOUS
                if result.code is ManagedMutationCode.AMBIGUOUS
                else MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        )
        return _receipt(operation_id, disposition)


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
