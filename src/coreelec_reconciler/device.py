"""Talking to a Device over ssh.

The transport shells out to the system `ssh` client and reuses the existing
key-only administrator setup. Remote commands are `sh` scripts whose embedded
paths are quoted, so a path is data rather than shell syntax.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from .config import Transport

CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 60


class DeviceError(Exception):
    """A Device that could not be reached, read, or written."""


@dataclass(frozen=True)
class Device:
    hostname: str
    transport: Transport

    def _run(
        self, script: str, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        argv = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={CONNECT_TIMEOUT}",
            "-i",
            str(self.transport.identity),
            "-p",
            str(self.transport.port),
            f"{self.transport.user}@{self.hostname}",
            script,
        ]
        try:
            return subprocess.run(
                argv,
                input=stdin if stdin is not None else "",
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
                check=False,
            )
        except FileNotFoundError as error:
            raise DeviceError(
                f"the ssh client is not installed, so {self.hostname} cannot be reached"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise DeviceError(
                f"ssh to {self.hostname} timed out after {COMMAND_TIMEOUT}s"
            ) from error

    def _checked(self, what: str, script: str, stdin: str | None = None) -> str:
        result = self._run(script, stdin)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            reason = detail[-1] if detail else f"ssh exited {result.returncode}"
            raise DeviceError(f"{what} on {self.hostname} failed: {reason}")
        return result.stdout

    def observed_hostname(self) -> str:
        """The name the Device calls itself, used to confirm its identity."""

        return self._checked("reading the hostname", "hostname").strip()

    def read(self, path: str) -> str | None:
        """The file's content, or None when the Device does not have it."""

        quoted = shlex.quote(path)
        marker = self._checked(
            f"reading {path}",
            f"if [ -f {quoted} ]; then printf 'file\\n'; cat {quoted};"
            f" elif [ -e {quoted} ]; then printf 'other\\n';"
            f" else printf 'absent\\n'; fi",
        )
        kind, _, content = marker.partition("\n")
        if kind == "absent":
            return None
        if kind != "file":
            raise DeviceError(f"{path} on {self.hostname} is not a regular file")
        return content

    def list_directory(self, path: str) -> list[str]:
        """The names the directory holds, empty when it holds none or is absent.

        The transport stays dumb on purpose: it returns names, and matching a
        pattern against them happens in Python. A glob handed to the remote
        `sh` would be the one thing this module does not do — an unmatched
        shell glob expands to itself, so a pattern matching nothing would
        arrive as a path that merely does not exist.
        """

        quoted = shlex.quote(path)
        listing = self._checked(
            f"listing {path}",
            f"if [ -d {quoted} ]; then ls -A {quoted}; fi",
        )
        return sorted(name for name in listing.splitlines() if name)

    def write(self, path: str, content: str, mode: str = "0644") -> None:
        """Stages the content beside the destination and renames it into place.

        The rename is atomic, so a Run killed mid-write leaves the previous
        file untouched rather than truncated. The staged name is fixed, so a
        killed Run leaves one stale file that the next Run overwrites.
        """

        directory, _, name = path.rpartition("/")
        staged = f"{directory}/.{name}.tmp"
        self._checked(
            f"writing {path}",
            f"set -e; mkdir -p {shlex.quote(directory)}; cat > {shlex.quote(staged)};"
            f" chmod {mode} {shlex.quote(staged)};"
            f" mv {shlex.quote(staged)} {shlex.quote(path)}",
            stdin=content,
        )

    def stop_service(self, unit: str) -> None:
        """Takes a service Effect. The Run takes it once, not once per Change."""

        self._checked(f"stopping {unit}", f"systemctl stop {shlex.quote(unit)}")

    def start_service(self, unit: str) -> None:
        self._checked(f"starting {unit}", f"systemctl start {shlex.quote(unit)}")
