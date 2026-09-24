"""Rendering `authorized_keys` whole.

The document is the complete set of entries, in declaration order with the
administrator first. Rendering it whole is what lets a revoked key actually
be revoked: an entry nobody declares is not in the rendering, so the Run
removes it.

Only the `restrict` form is rendered. The Device runs OpenSSH 9.9 on the only
platform the Profile names, and `restrict` already implies no agent forwarding,
no port forwarding, no pty, no user rc and no X11 forwarding there
(ADR 0016).
"""

from __future__ import annotations

from .config import AuthorizedKey, AuthorizedKeys

KEY_TYPES = ("ssh-", "ecdsa-sha2-", "sk-ssh-", "sk-ecdsa-")


def _line(entry: AuthorizedKey) -> str:
    key = f"{entry.key_type} {entry.blob}"
    if entry.comment:
        key = f"{key} {entry.comment}"
    if entry.forced_command is None:
        return key
    return f'restrict,command="{entry.forced_command}" {key}'


def render(keys: AuthorizedKeys) -> str:
    """The whole document, one entry per line."""

    return "".join(f"{_line(entry)}\n" for entry in keys.entries)


def administrator_entry(entry: AuthorizedKey) -> str:
    """The administrator's line on its own, for First Contact."""

    return _line(entry)


def summarise(document: str | None) -> list[str]:
    """The entries a document holds, named by comment.

    A key blob is sixty-eight characters of base64 that no one reads, so a
    Change here is reported by the names of the entries rather than as a diff
    of the file. That is also what keeps a key Desired State names rather
    than holds out of the report.
    """

    names = []
    for line in (document or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        words = stripped.split()
        # An entry is `[options] type blob [comment]`, and the comment is
        # everything after the blob — comments hold spaces, so it is not the
        # last word. An entry whose shape is not that at all is named by its
        # first word, so a line nobody recognises is still visibly one of the
        # lines being removed.
        names.append(_comment(words) or words[0])
    return names


def _comment(words: list[str]) -> str:
    for index, word in enumerate(words):
        if word.startswith(KEY_TYPES) and len(words) > index + 2:
            return " ".join(words[index + 2 :])
    return ""
