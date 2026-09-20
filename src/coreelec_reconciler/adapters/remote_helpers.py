"""Fixed, repository-owned remote Run Infrastructure helper operations."""

import hashlib
import posixpath
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coreelec_reconciler.transports.interfaces import (
    ReadFailure,
    ReadFailureCode,
    ReadResult,
)

REMOTE_ROOT = "/storage/.coreelec-reconciler"


class RemoteHelperCode(StrEnum):
    APPLIED = "applied"
    CONFLICT = "conflict"
    UNSAFE = "unsafe"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class RemoteHelperResult:
    code: RemoteHelperCode


class CommandRunner(Protocol):
    def execute(
        self, command: str, *, stdin: bytes = b"", timeout: float = 15.0
    ) -> object: ...


class RemoteHelper(Protocol):
    def run(
        self,
        operation: str,
        object_path: str,
        expected_digest: str,
        staged_path: str,
    ) -> RemoteHelperResult: ...


_HELPER = b"""set -eu
op=$1; object=$2; expected=$3; staged=$4
case "$object:$staged" in
  /storage/.coreelec-reconciler/*:/storage/.coreelec-reconciler/*) ;;
  *) exit 65 ;;
esac
ensure_dir() {
  [ ! -L "$1" ] || exit 66
  if [ -e "$1" ]; then [ -d "$1" ] || exit 66; else mkdir "$1" || exit 68; fi
  chmod 700 "$1" || exit 68
}
ensure_dir /storage/.coreelec-reconciler
lock="${object}.operation-lock"
case "$op" in
prepare)
  parent=${staged%/*}
  run_dir=${parent%/stage}
  runs_dir=${run_dir%/*}
  [ "$runs_dir" = /storage/.coreelec-reconciler/runs ] || exit 65
  ensure_dir "$runs_dir"
  ensure_dir "$run_dir"
  ensure_dir "$parent"
  ;;
create)
  parent=${object%/ownership}
  devices=${parent%/*}
  ensure_dir "$devices"
  ensure_dir "$parent"
  authority_lock="$parent/.authority-operation-lock"
  mkdir "$authority_lock" 2>/dev/null || exit 67
  trap 'rmdir "$authority_lock" 2>/dev/null || true' EXIT
  [ ! -e "$parent/quarantine" ] && [ ! -L "$parent/quarantine" ] || exit 67
  [ ! -L "$object" ] || exit 66
  mkdir "$object" 2>/dev/null || exit 67
  chmod 700 "$object" || exit 68
  mv "$staged" "$object/marker.json" || exit 68
  chmod 600 "$object/marker.json" || exit 68
  sync || exit 69
  ;;
replace)
  mkdir "$lock" 2>/dev/null || exit 67
  trap 'rmdir "$lock" 2>/dev/null || true' EXIT
  [ ! -L "$object/marker.json" ] && [ -f "$object/marker.json" ] || exit 66
  actual=$(sha256sum "$object/marker.json" | cut -d' ' -f1)
  [ "sha256:$actual" = "$expected" ] || exit 67
  mv "$staged" "$object/marker.json" || exit 68
  chmod 600 "$object/marker.json" || exit 68
  sync || exit 69
  ;;
remove)
  mkdir "$lock" 2>/dev/null || exit 67
  trap 'rmdir "$lock" 2>/dev/null || true' EXIT
  [ ! -L "$object/marker.json" ] && [ -f "$object/marker.json" ] || exit 66
  actual=$(sha256sum "$object/marker.json" | cut -d' ' -f1)
  [ "sha256:$actual" = "$expected" ] || exit 67
  rm "$object/marker.json" && rmdir "$object" || exit 68
  sync || exit 69
  ;;
quarantine)
  mkdir "$lock" 2>/dev/null || exit 67
  trap 'rmdir "$lock" 2>/dev/null || true' EXIT
  [ ! -L "$object/marker.json" ] && [ -f "$object/marker.json" ] || exit 66
  actual=$(sha256sum "$object/marker.json" | cut -d' ' -f1)
  [ "sha256:$actual" = "$expected" ] || exit 67
  destination="${object%/ownership}/quarantine"
  mkdir "$destination" 2>/dev/null || exit 67
  chmod 700 "$destination" || exit 68
  mv "$staged" "$destination/receipt.json" || exit 68
  chmod 600 "$destination/receipt.json" || exit 68
  rm "$object/marker.json" && rmdir "$object" || exit 68
  sync || exit 69
  ;;
cleanup)
  parent=${object%/*}
  run_dir=${parent%/*}
  runs_dir=${run_dir%/*}
  [ "$runs_dir" = /storage/.coreelec-reconciler/runs ] || exit 65
  for directory in "$runs_dir" "$run_dir" "$parent"; do
    [ ! -L "$directory" ] && [ -d "$directory" ] || exit 66
  done
  [ ! -L "$object" ] || exit 66
  if [ -e "$object" ]; then rm "$object" || exit 68; fi
  sync || exit 69
  ;;
inspect_cleanup)
  parent=${object%/*}
  run_dir=${parent%/*}
  runs_dir=${run_dir%/*}
  [ "$runs_dir" = /storage/.coreelec-reconciler/runs ] || exit 65
  for directory in "$runs_dir" "$run_dir" "$parent"; do
    [ ! -L "$directory" ] && [ -d "$directory" ] || exit 66
  done
  [ ! -L "$object" ] || exit 66
  [ -e "$object" ] && exit 67
  exit 0
  ;;
*) exit 64 ;;
esac
"""


class FixedRemoteHelper:
    def __init__(self, commands: CommandRunner) -> None:
        self._commands = commands

    def run(
        self,
        operation: str,
        object_path: str,
        expected_digest: str,
        staged_path: str,
    ) -> RemoteHelperResult:
        _validate_infrastructure_path(object_path)
        _validate_infrastructure_path(staged_path)
        command = " ".join(
            (
                "/bin/sh -s --",
                _shell_word(operation),
                _shell_word(object_path),
                _shell_word(expected_digest),
                _shell_word(staged_path),
            )
        )
        outcome = self._commands.execute(command, stdin=_HELPER, timeout=15.0)
        failure = getattr(outcome, "failure", None)
        if failure is not None:
            return RemoteHelperResult(RemoteHelperCode.AMBIGUOUS)
        exit_status = getattr(outcome, "exit_status", None)
        if exit_status == 0:
            code = RemoteHelperCode.APPLIED
        elif exit_status == 67:
            code = RemoteHelperCode.CONFLICT
        elif exit_status == 66:
            code = RemoteHelperCode.UNSAFE
        elif exit_status == 69:
            code = RemoteHelperCode.UNSUPPORTED
        elif exit_status == 68:
            code = RemoteHelperCode.AMBIGUOUS
        else:
            code = RemoteHelperCode.FAILED
        return RemoteHelperResult(code)


_NO_FOLLOW_READER = b"""import errno, os, stat, sys
if sys.argv[1] == "--probe":
    supported = (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
    )
    raise SystemExit(0 if supported else 46)
path = sys.argv[1]
limit = int(sys.argv[2])
descriptors = []
payload = b""
status = 0
try:
    if not path.startswith("/"):
        raise ValueError
    components = path.split("/")[1:]
    if not components or any(component in ('', '.', '..') for component in components):
        raise ValueError
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    descriptors.append(parent)
    for component in components[:-1]:
        parent = os.open(
            component,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent,
        )
        descriptors.append(parent)
        if not stat.S_ISDIR(os.fstat(parent).st_mode):
            raise ValueError
    descriptor = os.open(
        components[-1],
        os.O_RDONLY | os.O_NOFOLLOW,
        dir_fd=parent,
    )
    descriptors.append(descriptor)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError
    if metadata.st_size > limit:
        status = 42
    else:
        chunks = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                status = 43
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if status == 0 and os.read(descriptor, 1):
            status = 43
        if status == 0:
            payload = b"".join(chunks)
except FileNotFoundError:
    status = 40
except PermissionError:
    status = 44
except (NotADirectoryError, ValueError):
    status = 41
except OSError as error:
    status = 41 if error.errno in (errno.ELOOP, errno.ENOTDIR) else 45
finally:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            if status == 0:
                status = 45
if status == 0:
    os.write(1, payload)
raise SystemExit(status)
"""


class FixedNoFollowReader:
    def __init__(self, commands: CommandRunner) -> None:
        self._commands = commands

    def supported(self) -> bool:
        outcome = self._commands.execute(
            "/usr/bin/python3 - --probe 0",
            stdin=_NO_FOLLOW_READER,
            timeout=5.0,
        )
        return (
            getattr(outcome, "failure", None) is None
            and getattr(outcome, "exit_status", None) == 0
        )

    def read(self, path: str, limit: int) -> ReadResult:
        command = " ".join(
            (
                "/usr/bin/python3 -",
                _shell_word(path),
                str(limit),
            )
        )
        outcome = self._commands.execute(command, stdin=_NO_FOLLOW_READER, timeout=15.0)
        if getattr(outcome, "failure", None) is not None:
            return _read_failure(ReadFailureCode.TRANSPORT, "Entry read failed")
        exit_status = getattr(outcome, "exit_status", None)
        if exit_status == 0:
            stdout = getattr(outcome, "stdout", None)
            if isinstance(stdout, bytes):
                if len(stdout) > limit:
                    return _read_failure(
                        ReadFailureCode.TOO_LARGE, "Entry exceeds read limit"
                    )
                return ReadResult(stdout)
            return _read_failure(
                ReadFailureCode.INCOMPLETE, "Entry read was incomplete"
            )
        if not isinstance(exit_status, int):
            return _read_failure(ReadFailureCode.TRANSPORT, "Entry read failed")
        code = {
            40: ReadFailureCode.NOT_FOUND,
            41: ReadFailureCode.UNSAFE,
            42: ReadFailureCode.TOO_LARGE,
            43: ReadFailureCode.INCOMPLETE,
            44: ReadFailureCode.UNREADABLE,
        }.get(exit_status, ReadFailureCode.TRANSPORT)
        return _read_failure(code, _READ_MESSAGES[code])


def staged_infrastructure_path(workspace_key: str, payload: bytes) -> str:
    _validate_opaque_key(workspace_key)
    digest = hashlib.sha256(payload).hexdigest()
    return posixpath.join(REMOTE_ROOT, "runs", workspace_key, "stage", digest)


def _validate_infrastructure_path(path: str) -> None:
    normalized = posixpath.normpath(path)
    if (
        path != normalized
        or not path.startswith(REMOTE_ROOT + "/")
        or "/../" in path
        or path.endswith("/..")
    ):
        raise ValueError("remote Run Infrastructure path is invalid")


def _shell_word(value: str) -> str:
    if not value or any(character not in _SAFE_SHELL for character in value):
        raise ValueError("remote helper argument is invalid")
    return value


_SAFE_SHELL = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./:-"
)


_READ_MESSAGES = {
    ReadFailureCode.NOT_FOUND: "Entry is absent",
    ReadFailureCode.UNSAFE: "Entry is not a safe regular file",
    ReadFailureCode.TOO_LARGE: "Entry exceeds read limit",
    ReadFailureCode.INCOMPLETE: "Entry read was incomplete",
    ReadFailureCode.UNREADABLE: "Entry is unreadable",
    ReadFailureCode.TRANSPORT: "Entry read failed",
}


def _read_failure(code: ReadFailureCode, message: str) -> ReadResult:
    return ReadResult(None, ReadFailure(code, message))


def _validate_opaque_key(value: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("opaque Run key is invalid")
