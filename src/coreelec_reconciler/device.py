"""Talking to a Device over ssh.

The transport shells out to the system `ssh` client and reuses the existing
key-only administrator setup. Remote commands are `sh` scripts whose embedded
paths are quoted, so a path is data rather than shell syntax.

There is a second arm, used by First Contact alone: the same client with
public-key authentication turned off, so the operator is prompted for the
Device's password on the terminal. It is not a fallback. An ordinary Run
stays key-only and strict about host keys, because in steady state password
authentication is disabled and a key failure that fell back would turn into
three prompts against a daemon that refuses all of them (ADR 0016).
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from .config import Transport

CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 60

# Shipping an add-on tree is the one program that carries megabytes rather
# than a document, and the skin is the largest of them.
SHIP_TIMEOUT = 600

# First Contact may take as long as the operator takes to type the password.
FIRST_CONTACT_TIMEOUT = 300

# The status `ssh` itself exits with when the connection fails, as opposed to
# any status the remote program could have chosen.
TRANSPORT_FAILURE = 255

# The status the First Contact program exits with when the Device does not
# answer to the name the Room Overlay gives it.
WRONG_DEVICE = 3


class DeviceError(Exception):
    """A Device that could not be reached, read, or written."""


@dataclass(frozen=True)
class Device:
    hostname: str
    transport: Transport

    def _argv(self, script: str, *options: str) -> list[str]:
        return [
            "ssh",
            "-o",
            f"ConnectTimeout={CONNECT_TIMEOUT}",
            "-p",
            str(self.transport.port),
            *options,
            f"{self.transport.user}@{self.hostname}",
            script,
        ]

    def _run(
        self, script: str, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        completed = self._invoke(
            script, b"" if stdin is None else stdin.encode("utf-8")
        )
        return subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            completed.stdout.decode("utf-8", errors="replace"),
            completed.stderr.decode("utf-8", errors="replace"),
        )

    def _invoke(
        self, script: str, stdin: bytes, timeout: int = COMMAND_TIMEOUT
    ) -> subprocess.CompletedProcess[bytes]:
        argv = self._argv(
            script,
            "-o",
            "BatchMode=yes",
            # A changed host key on an ordinary Run means the Device was
            # reimaged or something is wrong, and refusing is the right
            # answer. Trust on first use belongs to First Contact alone.
            "-o",
            "StrictHostKeyChecking=yes",
            "-i",
            str(self.transport.identity),
        )
        try:
            return subprocess.run(
                argv,
                input=stdin,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as error:
            raise DeviceError(
                f"the ssh client is not installed, so {self.hostname} cannot be reached"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise DeviceError(
                f"ssh to {self.hostname} timed out after {timeout}s"
            ) from error

    def _checked(self, what: str, script: str, stdin: str | None = None) -> str:
        result = self._run(script, stdin)
        if result.returncode != 0:
            raise DeviceError(
                f"{what} on {self.hostname} failed: {self._reason(result)}"
            )
        return result.stdout

    @staticmethod
    def _reason(result: subprocess.CompletedProcess[str]) -> str:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return detail[-1] if detail else f"ssh exited {result.returncode}"

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

    def read_link(self, path: str) -> str | None:
        """What the symbolic link names, or None when `path` is not one."""

        quoted = shlex.quote(path)
        answer = self._checked(
            f"reading {path}",
            f"if [ -L {quoted} ]; then printf 'link\\n'; readlink {quoted};"
            f" else printf 'other\\n'; fi",
        )
        kind, _, target = answer.partition("\n")
        if kind != "link":
            return None
        return target.strip()

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

    def replace_directory(self, path: str, archive: bytes) -> None:
        """Replaces the directory with the tree the tar stream carries.

        The stream is expanded into a staging directory beside the
        destination and moved into place, so an expansion that fails partway
        never leaves a half-written add-on where Kodi will read one. The
        directory being replaced is not kept: the Artifact Lock reproduces it
        at any time, so a copy on the Device stores something already stored
        (ADR 0017), and an interrupted Run is repeated (ADR 0009).

        The tar stream rides on stdin, so the program cannot. It is a single
        `sh` command word whose embedded paths are quoted.
        """

        directory, _, name = path.rpartition("/")
        staging = f"{directory}/.{name}.staging"
        quoted, quoted_staging = shlex.quote(path), shlex.quote(staging)
        script = (
            f"set -e; rm -rf {quoted_staging}; mkdir -p {quoted_staging};"
            f" tar -xf - -C {quoted_staging};"
            f" test -d {quoted_staging}/{shlex.quote(name)};"
            f" rm -rf {quoted}; mkdir -p {shlex.quote(directory)};"
            f" mv {quoted_staging}/{shlex.quote(name)} {quoted};"
            f" rm -rf {quoted_staging}"
        )
        completed = self._invoke(script, archive, timeout=SHIP_TIMEOUT)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).decode(
                "utf-8", errors="replace"
            )
            lines = detail.strip().splitlines()
            reason = lines[-1] if lines else f"ssh exited {completed.returncode}"
            raise DeviceError(f"replacing {path} on {self.hostname} failed: {reason}")

    def sqlite(self, database: str, statements: str) -> str:
        """Runs `statements` against the SQLite database, and returns its output.

        The database must already exist: creating it would produce an empty
        file where Kodi expects its own schema, and every later Run would
        then fail somewhere less obvious than here.
        """

        quoted = shlex.quote(database)
        return self._checked(
            f"reading {database}",
            f"if [ ! -f {quoted} ]; then"
            f" echo 'no such database' >&2; exit 1; fi;"
            f" sqlite3 -batch {quoted} {shlex.quote(statements)}",
        )

    def stop_service(self, unit: str) -> None:
        """Takes a service Effect. The Run takes it once, not once per Change."""

        self._checked(f"stopping {unit}", f"systemctl stop {shlex.quote(unit)}")

    def start_service(self, unit: str) -> None:
        self._checked(f"starting {unit}", f"systemctl start {shlex.quote(unit)}")

    def restart_service_expecting_loss(self, unit: str) -> None:
        """Restarts a unit whose restart takes this connection with it.

        A restart that worked kills the connection before `systemctl` can
        report anything, so the transport's own failure status is the
        expected outcome and is not read; the caller reconnects and asks the
        Device instead. A status that is not the transport's is `systemctl`
        answering, which is a real failure and is reported here rather than
        left to look like a Device that never came back.
        """

        completed = self._run(f"systemctl restart {shlex.quote(unit)}")
        if completed.returncode not in (0, TRANSPORT_FAILURE):
            raise DeviceError(
                f"restarting {unit} on {self.hostname} failed: "
                f"{self._reason(completed)}"
            )

    def service_is_active(self, unit: str) -> bool:
        """Whether the unit is running, over a connection made just now."""

        return (
            self._run(f"systemctl is-active --quiet {shlex.quote(unit)}").returncode
            == 0
        )

    def install_administrator_key(self, path: str, entry: str) -> None:
        """First Contact: puts the administrator key on a Device with no key.

        This is the one program that runs over the password session, before
        any key exists, so it gets a single attempt on a Device the operator
        is standing in front of. It appends rather than declaring the
        document whole: the ordinary Run that follows owns every byte of the
        file, and this one has no business removing a key while the only
        thing proving it reached the right Device is the password it was
        just given.

        `ssh` prompts on the terminal, so neither stream is captured. The
        program rides on stdin — an argv word is joined by the client and
        re-parsed by the Device's login shell, which would lose its quoting
        in transit.

        The identity Guard every ordinary Run opens with is the first thing
        the program does, for the same reason and before the same line: a
        wrong Device must be refused before it is written to.
        """

        directory, _, _ = path.rpartition("/")
        blob = entry.split()[1]
        quoted = shlex.quote(path)
        expected = shlex.quote(self.hostname.casefold())
        script = (
            "set -eu\n"
            "umask 077\n"
            f"observed=$(hostname | tr '[:upper:]' '[:lower:]')\n"
            f'if [ "$observed" != {expected} ]; then\n'
            f'  echo "{self.hostname} answers to the hostname $observed:'
            f' refusing to reach a Device that is not {self.hostname}" >&2\n'
            "  exit 3\n"
            "fi\n"
            f"mkdir -p {shlex.quote(directory)}\n"
            f"chmod 700 {shlex.quote(directory)}\n"
            f"touch {quoted}\n"
            f"chmod 600 {quoted}\n"
            # Matching on the blob is what makes a retry idempotent: the
            # comment may differ between attempts, the key material may not.
            f"if ! grep -Fq {shlex.quote(blob)} {quoted}; then\n"
            f"  printf '%s\\n' {shlex.quote(entry)} >> {quoted}\n"
            "fi\n"
            # The install only counts if the Device can find the key it is
            # about to be asked to authenticate with.
            f"grep -Fq {shlex.quote(blob)} {quoted}\n"
        )
        argv = self._argv(
            "sh -s",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "PreferredAuthentications=keyboard-interactive,password",
            "-o",
            "NumberOfPasswordPrompts=3",
            # Trust on first use is correct for the connection that is first
            # use, and belongs to this entry point alone.
            "-o",
            "StrictHostKeyChecking=accept-new",
        )
        try:
            completed = subprocess.run(
                argv,
                input=script,
                text=True,
                timeout=FIRST_CONTACT_TIMEOUT,
                check=False,
            )
        except FileNotFoundError as error:
            raise DeviceError(
                f"the ssh client is not installed, so {self.hostname} cannot be reached"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise DeviceError(
                f"ssh to {self.hostname} timed out after {FIRST_CONTACT_TIMEOUT}s"
            ) from error
        if completed.returncode == WRONG_DEVICE:
            raise DeviceError(
                f"{self.hostname} answers to the hostname named just above: "
                "refusing to install the administrator key on a Device that "
                f"is not {self.hostname}"
            )
        if completed.returncode != 0:
            raise DeviceError(
                f"the administrator key could not be installed on "
                f"{self.hostname}. Confirm SSH is enabled on the Device and "
                "that the password is the one its first-boot wizard set"
            )
