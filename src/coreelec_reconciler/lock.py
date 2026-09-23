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
from collections.abc import Sequence
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
