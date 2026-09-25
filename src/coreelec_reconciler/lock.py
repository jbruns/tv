"""Recording what an Artifact Patch produces, back into the Artifact Lock.

A patched add-on is observed by its version *and* by the hashes of the files
its patches touch, because correcting a patch does not move the version
(ADR 0017). Those hashes are recorded rather than recomputed on every Run, so
`plan` stays offline and instant, and this is what records them: it runs the
real pipeline — fetch, prove the digest, expand, patch — and writes the
result into the record that named the patches.

It lives on the Reconciler rather than in `scripts/` because it *is* the
artifact pipeline. A tool beside it would either duplicate the pipeline or
reach past the package boundary ADR 0011 protects.

Only the recorded values are rewritten. Everything else in the file — the
comments explaining why each add-on is pinned where it is — is left exactly
as the human who wrote it left it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from . import artifact
from .config import AddonArtifact, ConfigError

# The shape of an Artifact Lock, read closely enough to find the values this
# command owns and no more closely than that.
RECORD = re.compile(r"^(\s*)-\s+id:\s*(\S+)\s*$")
ENTRY = re.compile(r"^(\s*)([^\s:]+):\s*(\S.*?)\s*$")


def record(document: Path, addons: Sequence[AddonArtifact], *, out: TextIO) -> None:
    """Rewrites every recorded post-patch hash the Artifact Lock holds."""

    recorded: dict[str, dict[str, str]] = {}
    for addon in addons:
        if not addon.patches:
            continue
        print(f"fetching {addon.id} {addon.version}", file=out)
        members = artifact.build(
            addon.url, addon.sha256, addon.id, addon.version, addon.patches
        )
        recorded[addon.id] = artifact.digests(members, sorted(addon.patched_files))

    held = document.read_text(encoding="utf-8")
    rewritten, moved = rewrite(held, recorded)
    for addon_id, path in moved:
        print(f"recorded {addon_id} {path}", file=out)
    if rewritten == held:
        print("the Artifact Lock already records every patched file", file=out)
        return
    document.write_text(rewritten, encoding="utf-8")


def rewrite(
    document: str, recorded: dict[str, dict[str, str]]
) -> tuple[str, list[tuple[str, str]]]:
    """The Lock with each patched file's hash replaced by the one computed.

    The file is rewritten line by line rather than round-tripped through a
    YAML writer, which would drop every comment in it.
    """

    lines = document.splitlines(keepends=True)
    current: str | None = None
    moved: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        held = RECORD.match(line)
        if held is not None:
            current = held.group(2)
            continue
        if current is None or current not in recorded:
            continue
        entry = ENTRY.match(line)
        if entry is None:
            continue
        path = entry.group(2)
        if path not in recorded[current]:
            continue
        digest = recorded[current][path]
        replacement = f'{entry.group(1)}{path}: "{digest}"\n'
        if lines[index] != replacement:
            lines[index] = replacement
            moved.append((current, path))
    rewritten = "".join(lines)
    unwritten = [
        (addon_id, path)
        for addon_id, files in recorded.items()
        for path, digest in files.items()
        if f'{path}: "{digest}"' not in rewritten
    ]
    if unwritten:
        addon_id, path = unwritten[0]
        raise ConfigError(
            f"the Artifact Lock has nowhere to record {path} of {addon_id}"
        )
    return rewritten, moved


@dataclass(frozen=True)
class Pin:
    """What an Update Proposal moves one record of the Lock to.

    `role` and `channel` are read only for a record new to the Lock; an
    existing record keeps its own, and its `notes`, exactly as written.
    """

    id: str
    version: str
    url: str
    sha256: str
    role: str = "dependency"
    channel: str | None = None
    patches: tuple[str, ...] = ()
    patched_files: Mapping[str, str] = field(default_factory=dict)


def repin(document: str, pins: Sequence[Pin]) -> str:
    """The Lock with each pin's record moved, and any new record appended.

    Like `rewrite`, this edits lines rather than round-tripping YAML, so the
    comments explaining each pin survive the proposal that moves it. A record
    is its `- id:` line and every line after it indented past that line.
    """

    lines = document.splitlines(keepends=True)
    wanted = {pin.id: pin for pin in pins}
    output: list[str] = []
    index = 0
    while index < len(lines):
        held = RECORD.match(lines[index])
        if held is None or held.group(2) not in wanted:
            output.append(lines[index])
            index += 1
            continue
        indent = len(held.group(1))
        end = index + 1
        while end < len(lines) and lines[end].startswith(" " * (indent + 2)):
            end += 1
        output.extend(_repinned(lines[index:end], indent, wanted.pop(held.group(2))))
        index = end
    text = "".join(output)
    for pin in pins:
        if pin.id not in wanted:
            continue
        if not text.endswith("\n"):
            text += "\n"
        text += "".join(
            [
                f"  - id: {pin.id}\n",
                *_entries(pin, 4, ("version", "url", "sha256")),
                f"    role: {pin.role}\n",
                f"    channel: {pin.channel or '~'}\n",
                "    notes: ~\n",
                *_entries(pin, 4, ("patches", "patched_files")),
            ]
        )
    return text


def _entries(pin: Pin, indent: int, keys: Sequence[str]) -> list[str]:
    pad = " " * indent
    held: list[str] = []
    for key in keys:
        if key == "version":
            held.append(f'{pad}version: "{pin.version}"\n')
        elif key == "url":
            held.append(f"{pad}url: {pin.url}\n")
        elif key == "sha256":
            held.append(f'{pad}sha256: "{pin.sha256}"\n')
        elif key == "patches" and pin.patches:
            held.append(f"{pad}patches:\n")
            held.extend(f"{pad}  - {name}\n" for name in pin.patches)
        elif key == "patched_files" and pin.patched_files:
            held.append(f"{pad}patched_files:\n")
            held.extend(
                f'{pad}  {path}: "{digest}"\n'
                for path, digest in sorted(pin.patched_files.items())
            )
    return held


def _repinned(block: list[str], indent: int, pin: Pin) -> list[str]:
    """One record's lines, with the entries a proposal owns replaced."""

    pad = " " * (indent + 2)
    owned = ("version", "url", "sha256", "patches", "patched_files")
    entries: list[tuple[str | None, list[str]]] = [(None, [block[0]])]
    for line in block[1:]:
        entry = ENTRY.match(line) or re.match(r"^(\s*)([^\s:]+):\s*$", line)
        if entry is not None and entry.group(1) == pad:
            entries.append((entry.group(2), [line]))
        else:
            entries[-1][1].append(line)
    output: list[str] = []
    for key, held in entries:
        if key in owned:
            output.extend(_entries(pin, indent + 2, (key,)))
        else:
            output.extend(held)
    present = {key for key, _ in entries}
    output.extend(
        _entries(pin, indent + 2, [key for key in owned if key not in present])
    )
    return output
