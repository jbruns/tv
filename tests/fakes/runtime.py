"""Stateful fake managed-file capabilities and deterministic runtime values."""

import hashlib
from dataclasses import dataclass

from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    MutationReceipt,
    NormalizedResourceState,
    Presence,
)
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
        self.before_mutation: object | None = None

    def put(self, path: str, entry: FakeManagedEntry) -> None:
        self._entries[path] = entry

    def entry(self, path: str) -> FakeManagedEntry | None:
        return self._entries.get(path)

    def discard(self, path: str) -> None:
        self._entries.pop(path, None)

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
        self,
        path: str,
        content: bytes,
        mode: int,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        self._before()
        if not _bound_stage(path, binding_digest):
            return self._receipt(
                operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        existing = self._entries.get(path)
        if expected.presence is Presence.ABSENT and existing is not None:
            disposition = (
                MutationDisposition.APPLIED
                if existing.kind is EntryKind.REGULAR
                and existing.mode == mode
                and existing.content == content
                else MutationDisposition.DEFINITELY_NOT_APPLIED
            )
            return self._receipt(operation_id, disposition)
        if not self._matches(path, expected):
            return self._receipt(
                operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        disposition, applied = self._outcome("stage_write")
        if applied:
            self._entries[path] = FakeManagedEntry(mode, content)
        return self._receipt(operation_id, disposition)

    def chmod(
        self,
        path: str,
        mode: int,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        del binding_digest
        self._before()
        if not self._matches(path, expected):
            return self._receipt(
                operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        disposition, applied = self._outcome("chmod")
        entry = self._entries.get(path)
        if applied and entry is not None:
            self._entries[path] = FakeManagedEntry(
                mode, entry.content, entry.kind, entry.readable
            )
        return self._receipt(operation_id, disposition)

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
        self._before()
        if (
            not _bound_stage(staged_path, binding_digest)
            or not self._matches(staged_path, expected_staged)
            or not self._matches(destination, expected_destination)
        ):
            return self._receipt(
                operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        disposition, applied = self._outcome("atomic_replace")
        staged = self._entries.get(staged_path)
        if applied and staged is not None:
            self._entries[destination] = staged
            del self._entries[staged_path]
        return self._receipt(operation_id, disposition)

    def remove(
        self,
        path: str,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        del binding_digest
        self._before()
        if not self._matches(path, expected):
            return self._receipt(
                operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
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
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        del binding_digest
        self._before()
        if not self._matches(path, expected):
            return self._receipt(
                operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        disposition, applied = self._outcome("restore")
        if applied:
            if content is None:
                self._entries.pop(path, None)
            else:
                self._entries[path] = FakeManagedEntry(mode or 0, content)
        return self._receipt(operation_id, disposition)

    def cleanup(
        self,
        path: str,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        del binding_digest
        self._before()
        if not self._matches(path, expected):
            return self._receipt(
                operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
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

    def _matches(self, path: str, expected: NormalizedResourceState) -> bool:
        entry = self._entries.get(path)
        if expected.presence is Presence.ABSENT:
            return entry is None
        if expected.presence is not Presence.PRESENT or entry is None:
            return False
        digest = "sha256:" + hashlib.sha256(entry.content).hexdigest()
        return (
            expected.entry_kind == entry.kind.value
            and expected.content_digest == digest
            and expected.managed_mode == entry.mode
        )

    def _before(self) -> None:
        callback = self.before_mutation
        if callable(callback):
            callback()


__all__ = ["FakeManagedEntry", "FakeManagedFiles", "FiniteRuntimeValues"]


def _bound_stage(path: str, binding_digest: str) -> bool:
    token = binding_digest.removeprefix("sha256:")
    return path.endswith(f".{token}.stage") or f"/runs/{token}/stage/" in path
