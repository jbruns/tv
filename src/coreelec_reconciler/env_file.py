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

    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        where = f"{path}:{number}"
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assignment = ASSIGNMENT.fullmatch(stripped)
        if assignment is None:
            raise EnvError(f"{where}: expected KEY=value")
        key = assignment.group(1)
        if key in values:
            raise EnvError(f"{where}: duplicate key: {key}")
        values[key] = _value(where, key, assignment.group(2))
    return values
