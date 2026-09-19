"""Fixed, repository-owned remote Run Infrastructure helper operations."""

import hashlib
import posixpath
from dataclasses import dataclass
from enum import StrEnum

from .paramiko_session import CommandRunner

REMOTE_ROOT = "/storage/.coreelec-reconciler"


class RemoteHelperCode(StrEnum):
    APPLIED = "applied"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class RemoteHelperResult:
    code: RemoteHelperCode


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
  [ -f "$object/marker.json" ] && [ ! -L "$object/marker.json" ] || exit 66
  actual=$(sha256sum "$object/marker.json" | cut -d' ' -f1)
  [ "sha256:$actual" = "$expected" ] || exit 67
  mv "$staged" "$object/marker.json" || exit 68
  chmod 600 "$object/marker.json" || exit 68
  sync || exit 69
  ;;
remove)
  mkdir "$lock" 2>/dev/null || exit 67
  trap 'rmdir "$lock" 2>/dev/null || true' EXIT
  actual=$(sha256sum "$object/marker.json" | cut -d' ' -f1)
  [ "sha256:$actual" = "$expected" ] || exit 67
  rm "$object/marker.json" && rmdir "$object" || exit 68
  sync || exit 69
  ;;
quarantine)
  mkdir "$lock" 2>/dev/null || exit 67
  trap 'rmdir "$lock" 2>/dev/null || true' EXIT
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
        if outcome.failure is not None:
            return RemoteHelperResult(RemoteHelperCode.AMBIGUOUS)
        if outcome.exit_status == 0:
            code = RemoteHelperCode.APPLIED
        elif outcome.exit_status == 67:
            code = RemoteHelperCode.CONFLICT
        elif outcome.exit_status == 69:
            code = RemoteHelperCode.UNSUPPORTED
        else:
            code = RemoteHelperCode.FAILED
        return RemoteHelperResult(code)


def staged_infrastructure_path(object_path: str, payload: bytes) -> str:
    _validate_infrastructure_path(object_path)
    digest = hashlib.sha256(payload).hexdigest()
    return posixpath.join(REMOTE_ROOT, "stage", digest)


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
