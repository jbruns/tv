"""Fetching a pinned add-on Artifact and preparing the tree the Device gets.

Everything here runs on the controller. An Artifact is a ZIP named by the
Artifact Lock and identified by its SHA-256; this module fetches it, proves
it is the pinned bytes, refuses a ZIP that would write outside its own
directory, cross-checks what `addon.xml` declares against the pin, and hands
back a tar stream of the finished tree (ADR 0017).

The fetch shells out to `curl`, the way the Device transport shells out to
`ssh`: one client, one set of TLS options, and a boundary a test can stand a
stub in front of.
"""

from __future__ import annotations

import calendar
import io
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ElementTree
import zipfile
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


class ArtifactError(Exception):
    """An Artifact that could not be fetched, proven, or read."""


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


def prepare(url: str, digest: str, addon_id: str, version: str) -> bytes:
    """Fetch, prove, expand and pack one Artifact, in that order."""

    members = expand(download(url, digest), addon_id, version)
    return tar(members, addon_id)
