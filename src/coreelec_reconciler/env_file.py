"""Reading the shared `.env`, which holds what no committed file may.

Desired State names a value here rather than holding it: the Profile carries
the key, and the value is read from this file. The shell entry points source
it as bash; the Reconciler does not. It reads it with the strict grammar
below, the posture `provision.conf` already takes (`config/README.md`), so a
line is data and never shell syntax.

The grammar is narrower than bash's on purpose. Every line this repository's
`.env.example` produces is a quoted scalar, and a line outside the grammar is
rejected naming the file and the line rather than read as something bash would
have read differently — a value misread here is a credential written to a
Device.

Nothing in this module puts a value into an error message.

The same grammar reads the `shell_vars` Settings Documents the Device holds
(`/storage/.cache/timezone`, say), which are the same shape read for the same
reason. Those are not secrets, but the strictness costs nothing and one
grammar is easier to trust than two.
"""

from __future__ import annotations

import re
from pathlib import Path

ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)")

# What a bare, unquoted value may hold. Anything else — whitespace, a quote, a
# shell metacharacter — is a value bash would have read differently, so it
# must be quoted.
BARE = re.compile(r"[A-Za-z0-9_./:@%+,=-]*")

# What double quotes do not protect from bash: expansion, command
# substitution, and escapes.
EXPANDS = ("$", "`", "\\")


class EnvError(Exception):
    """A shared `.env` that cannot be read as key-value pairs."""


def _value(where: str, key: str, raw: str) -> str:
    if raw.startswith("'"):
        if not raw.endswith("'") or len(raw) < 2 or "'" in raw[1:-1]:
            raise EnvError(f"{where}: {key} is not closed by a single quote")
        return raw[1:-1]
    if raw.startswith('"'):
        if not raw.endswith('"') or len(raw) < 2 or '"' in raw[1:-1]:
            raise EnvError(f"{where}: {key} is not closed by a double quote")
        inner = raw[1:-1]
        if any(character in inner for character in EXPANDS):
            raise EnvError(
                f"{where}: {key} is double-quoted around a character the shell "
                "would expand; single-quote it instead"
            )
        return inner
    if BARE.fullmatch(raw) is None:
        raise EnvError(f"{where}: {key} holds a character that must be quoted")
    return raw


def read(path: Path) -> dict[str, str]:
    """Every key the file holds. Raises EnvError naming the file and line."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise EnvError(f"{path}: {error.strerror or error}") from error
    return parse(text, str(path))


def parse(text: str, where: str | None = None) -> dict[str, str]:
    """Every key `text` holds. Raises EnvError naming the line.

    `where` is what the lines belong to, when the caller has a name for it;
    a caller that names the document itself passes nothing and decorates the
    message.

    The grammar is shared with the `shell_vars` dialect, because both read
    the same shape for the same reason: a line is data and never shell
    syntax, whatever the file is called.
    """

    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        location = f"line {number}" if where is None else f"{where}:{number}"
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assignment = ASSIGNMENT.fullmatch(stripped)
        if assignment is None:
            raise EnvError(f"{location}: expected KEY=value")
        key = assignment.group(1)
        if key in values:
            raise EnvError(f"{location}: duplicate key: {key}")
        values[key] = _value(location, key, assignment.group(2))
    return values


def serialise(value: str) -> str:
    """`value` as a line's right-hand side, quoted only when it must be.

    The shell provisioner writes these values bare, so anything the bare
    grammar accepts is written bare and the two engines produce the same
    bytes.
    """

    if BARE.fullmatch(value) is not None:
        return value
    if "'" in value:
        raise EnvError("a value holding a single quote cannot be written")
    return f"'{value}'"
