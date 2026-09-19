"""Stateful fake managed-file capabilities and deterministic runtime values."""

from dataclasses import dataclass

from coreelec_reconciler.domain.execution import MutationDisposition, MutationReceipt
from coreelec_reconciler.execution.runtime import FiniteRuntimeValues
from coreelec_reconciler.transports.interfaces import (
    EntryKind,
    FileMetadata,
    ReadFailure,
    ReadFailureCode,
    ReadResult,
)


@dataclass(frozen=True, slots=True)
class FakeManagedEntry:
    mode: int
    content: bytes
    kind: EntryKind = EntryKind.REGULAR
    readable: bool = True


class FakeManagedFiles:
    """Case-sensitive POSIX fake with both lost-ack outcomes per primitive."""

    def __init__(self) -> None:
        self._entries: dict[str, FakeManagedEntry] = {}
        self._faults: dict[str, list[tuple[MutationDisposition, bool]]] = {}
        self._operations: list[MutationReceipt] = []

    def put(self, path: str, entry: FakeManagedEntry) -> None:
        self._entries[path] = entry

    def entry(self, path: str) -> FakeManagedEntry | None:
        return self._entries.get(path)

    @property
    def operations(self) -> tuple[MutationReceipt, ...]:
        return tuple(self._operations)

    def fault(self, primitive: str, disposition: MutationDisposition) -> None:
        self._faults.setdefault(primitive, []).append(
            (
                disposition,
                disposition is not MutationDisposition.DEFINITELY_NOT_APPLIED,
            )
        )

    def lost_ack(self, primitive: str, *, applied: bool) -> None:
        self._faults.setdefault(primitive, []).append(
            (MutationDisposition.AMBIGUOUS, applied)
        )

    def lstat(self, path: str) -> ReadResult:
        entry = self._entries.get(path)
        if entry is None:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.NOT_FOUND, "Entry is absent")
            )
        return ReadResult(FileMetadata(entry.kind, entry.mode, len(entry.content)))

    def read(self, path: str, limit: int) -> ReadResult:
        entry = self._entries.get(path)
        if entry is None:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.NOT_FOUND, "Entry is absent")
            )
        if not entry.readable:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.UNREADABLE, "Entry is unreadable")
            )
        if len(entry.content) > limit:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.TOO_LARGE, "Entry exceeds limit")
            )
        return ReadResult(entry.content)

    def stage_write(
        self, path: str, content: bytes, mode: int, operation_id: str
    ) -> MutationReceipt:
        disposition, applied = self._outcome("stage_write")
        if applied:
            self._entries[path] = FakeManagedEntry(mode, content)
        return self._receipt(operation_id, disposition)

    def chmod(self, path: str, mode: int, operation_id: str) -> MutationReceipt:
        disposition, applied = self._outcome("chmod")
        entry = self._entries.get(path)
        if applied and entry is not None:
            self._entries[path] = FakeManagedEntry(
                mode, entry.content, entry.kind, entry.readable
            )
        return self._receipt(operation_id, disposition)

    def atomic_replace(
        self, staged_path: str, destination: str, operation_id: str
    ) -> MutationReceipt:
        disposition, applied = self._outcome("atomic_replace")
        staged = self._entries.get(staged_path)
        if applied and staged is not None:
            self._entries[destination] = staged
            del self._entries[staged_path]
        return self._receipt(operation_id, disposition)

    def remove(self, path: str, operation_id: str) -> MutationReceipt:
        disposition, applied = self._outcome("remove")
        if applied:
            self._entries.pop(path, None)
        return self._receipt(operation_id, disposition)

    def restore(
        self,
        path: str,
        content: bytes | None,
        mode: int | None,
        operation_id: str,
    ) -> MutationReceipt:
        disposition, applied = self._outcome("restore")
        if applied:
            if content is None:
                self._entries.pop(path, None)
            else:
                self._entries[path] = FakeManagedEntry(mode or 0, content)
        return self._receipt(operation_id, disposition)

    def cleanup(self, path: str, operation_id: str) -> MutationReceipt:
        disposition, applied = self._outcome("cleanup")
        if applied:
            self._entries.pop(path, None)
        return self._receipt(operation_id, disposition)

    def scripted_outcome(self, primitive: str) -> tuple[MutationDisposition, bool]:
        return self._outcome(primitive)

    def _outcome(self, primitive: str) -> tuple[MutationDisposition, bool]:
        queue = self._faults.get(primitive)
        return queue.pop(0) if queue else (MutationDisposition.APPLIED, True)

    def _receipt(
        self, operation_id: str, disposition: MutationDisposition
    ) -> MutationReceipt:
        receipt = MutationReceipt(operation_id, disposition)
        self._operations.append(receipt)
        return receipt


__all__ = ["FakeManagedEntry", "FakeManagedFiles", "FiniteRuntimeValues"]
