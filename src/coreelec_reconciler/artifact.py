"""Fetching a pinned add-on Artifact and preparing the tree the Device gets.

Everything here runs on the controller. An Artifact is a ZIP named by the
Artifact Lock and identified by its SHA-256; this module fetches it, proves
it is the pinned bytes, refuses a ZIP that would write outside its own
directory, cross-checks what `addon.xml` declares against the pin, applies
the add-on's Artifact Patches, and hands back a tar stream of the finished
tree (ADR 0017).

The fetch invokes `curl`, and patching invokes `patch`, the way
the Device transport invokes `ssh`: one client, one set of options, and
a boundary a test can stand a stub in front of.
"""

from __future__ import annotations

import calendar
import io
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ElementTree
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

# A pinned Artifact is a few megabytes at most, over a link that is either
# there or is not.
CONNECT_TIMEOUT = 15
TRANSFER_TIMEOUT = 300

# What a ZIP entry gets when the archive carries no Unix mode at all, which
# is what a Windows-built ZIP looks like.
DEFAULT_FILE_MODE = 0o644
DEFAULT_DIRECTORY_MODE = 0o755

# Applying five small diffs to five small files is local work on files that
# are already in memory.
PATCH_TIMEOUT = 30


class ArtifactError(Exception):
    """An Artifact that could not be fetched, proven, read, or patched."""


@dataclass(frozen=True)
class Patch:
    """One Artifact Patch: a unified diff, named by the file it is kept in.

    `diff` opens with a header comment naming the add-on and the version the
    diff was written against. `patch` ignores that leading text; the
    Reconciler reads it and refuses a version the patch was not written for
    before anything is fetched (ADR 0017).
    """

    name: str
    diff: str


@dataclass(frozen=True)
class Member:
    """One entry of the expanded Artifact, addressed inside the add-on's tree."""

    path: str
    mode: int
    modified: int
    data: bytes | None

    @property
    def is_directory(self) -> bool:
        return self.data is None


def download(url: str, digest: str) -> bytes:
    """The pinned bytes, or an error. Different bytes are never installed.

    `curl` writes to a file rather than to a pipe so that a transfer it
    abandons partway cannot be mistaken for a short archive: `--fail` and the
    exit status decide, and the bytes are read only after it succeeded.
    """

    with tempfile.TemporaryDirectory() as workspace:
        target = Path(workspace) / "artifact"
        argv = [
            "curl",
            "--fail",
            "--location",
            "--proto",
            "=https",
            "--tlsv1.2",
            "--retry",
            "3",
            "--retry-all-errors",
            "--connect-timeout",
            str(CONNECT_TIMEOUT),
            "--max-time",
            str(TRANSFER_TIMEOUT),
            "--silent",
            "--show-error",
            "--output",
            str(target),
            url,
        ]
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=TRANSFER_TIMEOUT,
                check=False,
            )
        except FileNotFoundError as error:
            raise ArtifactError(
                f"curl is not installed, so {url} cannot be fetched"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise ArtifactError(
                f"fetching {url} timed out after {TRANSFER_TIMEOUT}s"
            ) from error
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()
            reason = detail[-1] if detail else f"curl exited {completed.returncode}"
            raise ArtifactError(f"{url} could not be fetched: {reason}")
        blob = target.read_bytes()

    observed = sha256(blob).hexdigest()
    if observed != digest:
        raise ArtifactError(
            f"{url} is {observed} and the Artifact Lock pins {digest}: "
            "refusing to install bytes nobody pinned"
        )
    return blob


def _safe_entry(addon_id: str, name: str) -> str:
    """The top-level segment of a ZIP entry, or an error naming the entry.

    A ZIP is an archive of arbitrary names, and the names decide where the
    expansion lands. Anything that could leave the add-on's own directory is
    refused here rather than sanitised, because a pinned Artifact holding one
    is not an Artifact with an awkward name — it is the wrong Artifact.
    """

    if not name:
        raise ArtifactError(f"the {addon_id} Artifact holds an entry with no name")
    if name.startswith("/"):
        raise ArtifactError(
            f"the {addon_id} Artifact holds an absolute path entry: {name}"
        )
    if "\\" in name:
        raise ArtifactError(
            f"the {addon_id} Artifact holds a backslash in an entry: {name}"
        )
    segments = name.split("/")
    if any(segment in (".", "..") for segment in segments):
        raise ArtifactError(f"the {addon_id} Artifact holds a traversal entry: {name}")
    return segments[0]


def _mode(entry: zipfile.ZipInfo) -> int:
    held = (entry.external_attr >> 16) & 0o777
    if held:
        return held
    return DEFAULT_DIRECTORY_MODE if entry.is_dir() else DEFAULT_FILE_MODE


def _modified(entry: zipfile.ZipInfo) -> int:
    """The entry's own timestamp, as seconds, so a tar of one Artifact is one tar.

    A clock reading here would make the stream differ on every Run for bytes
    that never changed.
    """

    year, month, day, hour, minute, second = entry.date_time
    return calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))


def declared(document: str) -> tuple[str, str]:
    """The `id` and `version` an `addon.xml` declares.

    Parsed, never matched: the `<addon>` element's attributes are spread
    across lines in several of the add-ons this fleet installs, so a pattern
    over the text would read the wrong thing or nothing at all.
    """

    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise ArtifactError(f"addon.xml does not parse as XML: {error}") from error
    if root.tag != "addon":
        raise ArtifactError(
            f"addon.xml holds a <{root.tag}> element where <addon> is expected"
        )
    held_id = root.get("id")
    held_version = root.get("version")
    if not held_id or not held_version:
        raise ArtifactError("addon.xml declares no id or no version")
    return held_id, held_version


def expand(blob: bytes, addon_id: str, version: str) -> tuple[Member, ...]:
    """The Artifact's single top-level directory, as the tree that is shipped.

    The directory is *not* always the add-on id — two pins in this fleet are
    GitHub tag archives rooted at `<repo>-<ref>/` — so the root is whatever
    the archive holds and the identity comes from `addon.xml`.
    """

    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as error:
        raise ArtifactError(
            f"the {addon_id} Artifact does not read as a ZIP: {error}"
        ) from error

    root = ""
    for entry in archive.infolist():
        top = _safe_entry(addon_id, entry.filename)
        if not root:
            root = top
        elif top != root:
            raise ArtifactError(
                f"the {addon_id} Artifact holds more than one top-level "
                f"directory: {root}, {top}"
            )
    if not root:
        raise ArtifactError(f"the {addon_id} Artifact is empty")

    members: list[Member] = []
    manifest: str | None = None
    for entry in archive.infolist():
        relative = entry.filename[len(root) :].strip("/")
        if not relative:
            continue
        if entry.is_dir():
            members.append(
                Member(
                    path=relative,
                    mode=_mode(entry),
                    modified=_modified(entry),
                    data=None,
                )
            )
            continue
        data = archive.read(entry)
        if relative == "addon.xml":
            manifest = data.decode("utf-8", errors="replace")
        members.append(
            Member(
                path=relative,
                mode=_mode(entry),
                modified=_modified(entry),
                data=data,
            )
        )

    if manifest is None:
        raise ArtifactError(f"the {addon_id} Artifact holds no {root}/addon.xml")
    held_id, held_version = declared(manifest)
    if held_id != addon_id:
        raise ArtifactError(
            f"the Artifact pinned for {addon_id} declares the add-on {held_id}"
        )
    if held_version != version:
        raise ArtifactError(
            f"the {addon_id} Artifact declares version {held_version} and the "
            f"Artifact Lock pins {version}"
        )
    return tuple(sorted(members, key=lambda member: member.path))


def tar(members: tuple[Member, ...], name: str) -> bytes:
    """The tree as one `ustar` stream rooted at `name`.

    `ustar` because the Device's `tar` is BusyBox's, which rejects the
    extended headers a modern default emits. Ownership is flattened to root,
    which is the only user CoreELEC has.
    """

    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        root = tarfile.TarInfo(name)
        root.type = tarfile.DIRTYPE
        root.mode = DEFAULT_DIRECTORY_MODE
        root.mtime = max((member.modified for member in members), default=0)
        _own(root)
        archive.addfile(root)
        for member in members:
            info = tarfile.TarInfo(f"{name}/{member.path}")
            info.mode = member.mode
            info.mtime = member.modified
            _own(info)
            if member.data is None:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
                continue
            info.size = len(member.data)
            archive.addfile(info, io.BytesIO(member.data))
    return stream.getvalue()


def _own(info: tarfile.TarInfo) -> None:
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"


def asserted(patch: Patch) -> tuple[str, str]:
    """The add-on and version a patch's header comment was written against.

    The header is the first line: `# <add-on id> <version>`. `patch` skips
    leading text, so the assertion costs the diff nothing and keeps the patch
    a file `patch` can read and a reviewer can read as a diff.
    """

    header = patch.diff.split("\n", 1)[0].strip()
    words = header.lstrip("#").split()
    if not header.startswith("#") or len(words) != 2:
        raise ArtifactError(
            f"{patch.name} does not open with a header naming the add-on and "
            "the version it was written against"
        )
    return words[0], words[1]


def touched(patch: Patch) -> tuple[str, ...]:
    """The files a patch changes, taken from its own `+++` headers.

    Nothing declares this list a second time: the diff already says which
    files it rewrites, and the Lock records the hash of each one under the
    same names (ADR 0017).
    """

    held: list[str] = []
    for line in patch.diff.splitlines():
        if not line.startswith("+++ "):
            continue
        name = line[4:].split("\t", 1)[0].strip()
        _, _, relative = name.partition("/")
        candidate = Path(relative)
        if not relative or candidate.is_absolute() or ".." in candidate.parts:
            raise ArtifactError(f"{patch.name} names a file outside the add-on: {name}")
        if relative not in held:
            held.append(relative)
    if not held:
        raise ArtifactError(f"{patch.name} holds no diff")
    return tuple(held)


def _compiles(path: str, data: bytes) -> None:
    """A patched Python file that Kodi could not import fails the Run instead.

    A clean application proves the context matched; it does not prove the
    result parses, and most patched files are imported at boot (ADR 0017).
    """

    if not path.endswith(".py"):
        return
    try:
        compile(data.decode("utf-8"), path, "exec")
    except (SyntaxError, ValueError, UnicodeDecodeError) as error:
        raise ArtifactError(f"the patched {path} does not compile: {error}") from error


def patched(
    members: tuple[Member, ...], addon_id: str, patches: Sequence[Patch]
) -> tuple[Member, ...]:
    """The expanded Artifact with its Artifact Patches applied, or an error.

    Only the files the diffs name are written out and read back, so mode and
    timestamp come from the Artifact for every member and the tar of one
    Artifact stays one tar. An already-patched tree cannot arise here: this
    tree was expanded from bytes a SHA-256 pins.
    """

    if not patches:
        return members
    held = {member.path: member for member in members}
    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace) / "tree"
        for patch in patches:
            for path in touched(patch):
                member = held.get(path)
                if member is None or member.data is None:
                    raise ArtifactError(
                        f"{patch.name} patches {path}, which the {addon_id} "
                        "Artifact does not hold"
                    )
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(member.data)
            diff = Path(workspace) / patch.name
            diff.write_text(patch.diff, encoding="utf-8")
            _patch(root, diff, patch, addon_id)
        for patch in patches:
            for path in touched(patch):
                data = (root / path).read_bytes()
                _compiles(path, data)
                held[path] = Member(
                    path=path,
                    mode=held[path].mode,
                    modified=held[path].modified,
                    data=data,
                )
    return tuple(sorted(held.values(), key=lambda member: member.path))


def _patch(root: Path, diff: Path, patch: Patch, addon_id: str) -> None:
    """One diff applied by `patch`, whose context lines are the assertion."""

    argv = [
        "patch",
        # The context lines are the assertion, so an application that had to
        # ignore some of them to succeed has not asserted anything (ADR 0017).
        "--fuzz=0",
        "--strip=1",
        "--directory",
        str(root),
        "--input",
        str(diff),
    ]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            # A patch that cannot find what it is told to change asks a human
            # which file to patch. There is no human here, so it reads EOF
            # and gives up.
            stdin=subprocess.DEVNULL,
            timeout=PATCH_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as error:
        raise ArtifactError(
            f"patch is not installed, so {patch.name} cannot be applied"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise ArtifactError(f"applying {patch.name} timed out") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"patch exited {completed.returncode}"
        raise ArtifactError(
            f"{patch.name} does not apply to the pinned {addon_id}: {reason}"
        )


def digests(members: tuple[Member, ...], paths: Sequence[str]) -> dict[str, str]:
    """The SHA-256 of each named file of a prepared tree."""

    held = {member.path: member for member in members}
    recorded = {}
    for path in paths:
        member = held.get(path)
        if member is None or member.data is None:
            raise ArtifactError(f"the prepared tree holds no {path}")
        recorded[path] = sha256(member.data).hexdigest()
    return recorded


def build(
    url: str,
    digest: str,
    addon_id: str,
    version: str,
    patches: Sequence[Patch] = (),
) -> tuple[Member, ...]:
    """Fetch, prove, expand and patch one Artifact, in that order."""

    members = expand(download(url, digest), addon_id, version)
    return patched(members, addon_id, patches)


def prepare(
    url: str,
    digest: str,
    addon_id: str,
    version: str,
    patches: Sequence[Patch] = (),
) -> bytes:
    """The finished tree the Device receives, as one tar stream."""

    return tar(build(url, digest, addon_id, version, patches), addon_id)
