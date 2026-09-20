"""Case-sensitive POSIX fake Device and independent read-only inspector."""

import hashlib
import json
from dataclasses import dataclass

from coreelec_reconciler.domain.execution import MutationDisposition, MutationReceipt
from coreelec_reconciler.transports.interfaces import (
    EntryKind,
    FileMetadata,
    ReadFailure,
    ReadFailureCode,
    ReadResult,
)
from coreelec_reconciler.transports.remote_ownership import (
    AuthorityConflict,
    RemoteAuthorityBackend,
    RemoteObject,
    RemoteObjectKind,
)


@dataclass(frozen=True, slots=True)
class FakeEntry:
    kind: EntryKind
    mode: int
    content: bytes = b""
    readable: bool = True


class _State:
    def __init__(self) -> None:
        self.entries: dict[str, FakeEntry] = {}
        self.ownership = RemoteObject(RemoteObjectKind.ABSENT)
        self.quarantine = RemoteObject(RemoteObjectKind.ABSENT)
        self.fail_durability = False
        self.quarantine_race = False


class FakeDevice(RemoteAuthorityBackend):
    def __init__(self) -> None:
        self._state = _State()

    def inspector(self) -> DeviceInspector:
        return DeviceInspector(self._state)

    def put(self, path: str, entry: FakeEntry) -> None:
        self._state.entries[path] = entry

    def set_remote_ownership(self, value: RemoteObject) -> None:
        self._state.ownership = value

    def set_remote_quarantine(self, value: RemoteObject) -> None:
        self._state.quarantine = value

    def fail_remote_durability(self, enabled: bool = True) -> None:
        self._state.fail_durability = enabled

    def race_quarantine_on_next_acquire(self) -> None:
        self._state.quarantine_race = True

    def lstat(self, path: str) -> ReadResult:
        entry = self._state.entries.get(path)
        if entry is None:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.NOT_FOUND, "Entry is absent")
            )
        return ReadResult(FileMetadata(entry.kind, entry.mode, len(entry.content)))

    def read(self, path: str, limit: int) -> ReadResult:
        entry = self._state.entries.get(path)
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

    def inspect_ownership(self, device_key: str) -> RemoteObject:
        del device_key
        return self._state.ownership

    def inspect_quarantine(self, device_key: str) -> RemoteObject:
        del device_key
        return self._state.quarantine

    def create_ownership_if_unowned_and_not_quarantined(
        self, device_key: str, payload: bytes, expected_digest: str
    ) -> None:
        del device_key
        self._durable(payload, expected_digest)
        if self._state.quarantine_race:
            self._state.quarantine = RemoteObject(
                RemoteObjectKind.REGULAR, b'{"incident":"race"}'
            )
            self._state.quarantine_race = False
        if (
            self._state.ownership.kind is not RemoteObjectKind.ABSENT
            or self._state.quarantine.kind is not RemoteObjectKind.ABSENT
        ):
            raise AuthorityConflict("ownership or quarantine already exists")
        self._state.ownership = RemoteObject(RemoteObjectKind.REGULAR, payload)

    def replace_ownership(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None:
        del device_key
        current = self._state.ownership
        if current.payload is None or _digest(current.payload) != expected_digest:
            raise AuthorityConflict("ownership compare failed")
        self._durable(payload, next_digest)
        self._state.ownership = RemoteObject(RemoteObjectKind.REGULAR, payload)

    def remove_ownership(
        self,
        device_key: str,
        expected_digest: str,
        terminal_receipt_digest: str,
    ) -> MutationReceipt:
        del device_key
        current = self._state.ownership
        if current.payload is None or _digest(current.payload) != expected_digest:
            raise AuthorityConflict("ownership compare failed")
        marker = json.loads(current.payload)
        if marker.get("manifest_digest") != terminal_receipt_digest:
            raise AuthorityConflict("terminal evidence compare failed")
        self._state.ownership = RemoteObject(RemoteObjectKind.ABSENT)
        return MutationReceipt("remote-ownership-release", MutationDisposition.APPLIED)

    def convert_to_quarantine(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None:
        del device_key
        current = self._state.ownership
        if current.payload is None or _digest(current.payload) != expected_digest:
            raise AuthorityConflict("ownership compare failed")
        self._durable(payload, next_digest)
        self._state.quarantine = RemoteObject(RemoteObjectKind.REGULAR, payload)
        self._state.ownership = RemoteObject(RemoteObjectKind.ABSENT)

    def _durable(self, payload: bytes, expected_digest: str) -> None:
        if self._state.fail_durability or _digest(payload) != expected_digest:
            raise OSError("durability unavailable")


class DeviceInspector:
    def __init__(self, state: _State) -> None:
        self._state = state

    def entry(self, path: str) -> FakeEntry | None:
        return self._state.entries.get(path)

    def snapshot(self) -> tuple[tuple[str, FakeEntry], ...]:
        return tuple(sorted(self._state.entries.items()))

    def ownership(self) -> RemoteObject:
        return self._state.ownership

    def quarantine(self) -> RemoteObject:
        return self._state.quarantine


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
