from __future__ import annotations

import errno
import io
import stat
from dataclasses import dataclass

import paramiko

from coreelec_reconciler.adapters.paramiko_session import (
    CommandFailureCode,
    CommandOutcome,
)
from coreelec_reconciler.transports.interfaces import (
    ReadFailure,
    ReadFailureCode,
    ReadResult,
)


@dataclass
class Entry:
    content: bytes
    mode: int = stat.S_IFREG | 0o644


class Handle:
    def __init__(
        self,
        sftp: ScriptedSFTP,
        path: str,
        mode: str,
        content: bytes = b"",
    ) -> None:
        self._sftp = sftp
        self._path = path
        self._mode = mode
        self._buffer = io.BytesIO(content)
        self.closed = False

    def read(self, size: int) -> bytes:
        value = self._buffer.read(size)
        if self._sftp.incomplete_read and value:
            self._sftp.incomplete_read = False
            self._buffer.seek(0, io.SEEK_END)
            return value[:-1]
        return value

    def write(self, value: bytes) -> int:
        if self._sftp.disconnect_on == "write":
            if self._sftp.disconnect_applied:
                self._buffer.write(value)
            raise paramiko.SSHException("private transport detail")
        return self._buffer.write(value)

    def flush(self) -> None:
        if self._sftp.disconnect_on == "flush":
            raise paramiko.SSHException("private transport detail")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if "x" in self._mode:
            self._sftp.entries[self._path] = Entry(self._buffer.getvalue(), 0o600)
        self._sftp.closed_handles += 1


class Attributes:
    def __init__(self, entry: Entry) -> None:
        self.st_mode = entry.mode
        self.st_size = len(entry.content)


class ScriptedSFTP:
    def __init__(self) -> None:
        self.entries: dict[str, Entry] = {}
        self.closed_handles = 0
        self.closed = False
        self.incomplete_read = False
        self.disconnect_on: str | None = None
        self.disconnect_applied = True
        self.posix_calls: list[tuple[str, str]] = []
        self.rename_calls: list[tuple[str, str]] = []
        self.remove_calls: list[str] = []
        self.unsupported_posix_rename = False

    def lstat(self, path: str) -> Attributes:
        if self.disconnect_on == "lstat":
            raise paramiko.SSHException("private transport detail")
        try:
            return Attributes(self.entries[path])
        except KeyError as error:
            raise FileNotFoundError(errno.ENOENT, "not found") from error

    def open(self, path: str, mode: str) -> Handle:
        if self.disconnect_on == "open":
            raise paramiko.SSHException("private transport detail")
        if "x" in mode:
            if path in self.entries:
                raise FileExistsError(errno.EEXIST, "exists")
            return Handle(self, path, mode)
        try:
            entry = self.entries[path]
        except KeyError as error:
            raise FileNotFoundError(errno.ENOENT, "not found") from error
        return Handle(self, path, mode, entry.content)

    def chmod(self, path: str, mode: int) -> None:
        if self.disconnect_on == "chmod":
            if self.disconnect_applied and path in self.entries:
                entry = self.entries[path]
                self.entries[path] = Entry(entry.content, stat.S_IFREG | mode)
            raise paramiko.SSHException("private transport detail")
        try:
            entry = self.entries[path]
        except KeyError as error:
            raise FileNotFoundError(errno.ENOENT, "not found") from error
        self.entries[path] = Entry(entry.content, stat.S_IFREG | mode)

    def posix_rename(self, source: str, destination: str) -> None:
        self.posix_calls.append((source, destination))
        if self.unsupported_posix_rename:
            raise OSError("Operation unsupported")
        if self.disconnect_on == "posix_rename":
            if self.disconnect_applied:
                self.entries[destination] = self.entries.pop(source)
            raise paramiko.SSHException("private transport detail")
        self.entries[destination] = self.entries.pop(source)

    def rename(self, source: str, destination: str) -> None:
        self.rename_calls.append((source, destination))
        raise AssertionError("ordinary rename is forbidden")

    def remove(self, path: str) -> None:
        self.remove_calls.append(path)
        if self.disconnect_on == "remove":
            if self.disconnect_applied:
                self.entries.pop(path, None)
            raise paramiko.SSHException("private transport detail")
        try:
            del self.entries[path]
        except KeyError as error:
            raise FileNotFoundError(errno.ENOENT, "not found") from error

    def close(self) -> None:
        self.closed = True


class ScriptedCommands:
    def __init__(self, outcomes: list[CommandOutcome]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, bytes, float]] = []

    def execute(
        self, command: str, *, stdin: bytes = b"", timeout: float = 15.0
    ) -> CommandOutcome:
        self.calls.append((command, stdin, timeout))
        if not self.outcomes:
            return CommandOutcome(b"", b"", None, CommandFailureCode.DISCONNECTED)
        return self.outcomes.pop(0)


class ScriptedNoFollowReader:
    def __init__(self, sftp: ScriptedSFTP) -> None:
        self.sftp = sftp
        self.failure: ReadFailureCode | None = None
        self.before_read: object | None = None

    def read(self, path: str, limit: int) -> ReadResult:
        callback = self.before_read
        if callable(callback):
            callback()
        if self.failure is not None:
            return ReadResult(None, ReadFailure(self.failure, "Safe read failed"))
        entry = self.sftp.entries.get(path)
        if entry is None:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.NOT_FOUND, "Entry is absent")
            )
        if stat.S_IFMT(entry.mode) != stat.S_IFREG:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.UNSAFE, "Entry is unsafe")
            )
        if len(entry.content) > limit:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.TOO_LARGE, "Entry exceeds read limit")
            )
        return ReadResult(entry.content)


class ScriptedReadView:
    def lstat(self, path: str) -> ReadResult:
        del path
        return ReadResult(
            None, ReadFailure(ReadFailureCode.NOT_FOUND, "Entry is absent")
        )

    def read(self, path: str, limit: int) -> ReadResult:
        del path, limit
        return ReadResult(b"")


class ScriptedLeastAuthoritySession:
    def __init__(self, requested: frozenset[str]) -> None:
        self._requested = requested
        self._files = ScriptedReadView()

    @property
    def managed_files(self) -> ScriptedReadView:
        if "managed_file.read" not in self._requested:
            raise RuntimeError("managed-file read capability was not requested")
        return self._files
