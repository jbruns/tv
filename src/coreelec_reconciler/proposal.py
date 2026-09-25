"""Proposing Stable Releases, and triaging the Artifact Patches they touch.

`propose-updates` reads every Artifact Lock under the configuration root and
asks each record's own Release Channel for a newer Stable Release. Each one
becomes an Update Proposal: the rewritten Lock, the patch changes, and a body
a reviewer reads. It writes files and talks to nothing else; the workflow
opens the pull requests, and nothing here ever accepts one (ADR 0022).

A proposal moves one record together with every dependency bump its new
`<requires>` floors force. A dependency gets a proposal of its own only if
no other proposal already moves it, so merging one proposal makes the next
run rebuild or close the ones it overlapped.

Each Artifact Patch the moved add-on carries gets a verdict. A patch that
still applies is Carried: its header names the new version and its
post-patch hashes are recorded, as `record-patches` would. A patch that
reverse-applies is Obsolete, because the new version already holds what it
wrote, and it is removed. Anything else is Stale, and the proposal opens as a
draft for a human to rewrite it. Fuzzy application is never tried.
"""

from __future__ import annotations

import difflib
import functools
import gzip
import json
import re
import shutil
import tempfile
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import TextIO

from . import artifact, config, lock

# A version carrying one of these is a prerelease, whatever the channel says
# (ADR 0022). The channel is already scoped to this Kodi version, and this
# is cheap insurance on top.
PRERELEASE = re.compile(r"alpha|beta|rc|~")

# Kodi provides these itself, so a requirement on one is never an add-on the
# Lock could pin.
KODI_OWN = ("xbmc.", "kodi.")

# An upstream diff is context for a reviewer rather than the change under
# review, and a pull request body has a size limit.
DIFF_LINES = 200


class ProposalError(Exception):
    """An Update Proposal that could not be built this run."""


# --- Kodi's own version order ------------------------------------------------
#
# Ported from `CAddonVersion` in xbmc/addons/AddonVersion.cpp (Omega), not
# guessed. A version is lowercased, split at `:` into an epoch and at the
# first `-` into an upstream and a revision, and each part is compared the
# way Debian compares versions: runs of non-digits character by character,
# with `~` below everything including the end, and runs of digits as numbers.

VALID = set("abcdefghijklmnopqrstuvwxyz0123456789.+_@~")
LONG_MAX = 2**63 - 1


def _strtol(text: str, start: int) -> tuple[int, int]:
    """C's `strtol(…, 10)` at `start`: the value and where parsing stopped."""

    index = start
    sign = 1
    if index < len(text) and text[index] in "+-":
        sign = -1 if text[index] == "-" else 1
        index += 1
    digits = index
    while index < len(text) and text[index].isdigit():
        index += 1
    if index == digits:
        return 0, start
    return max(-LONG_MAX - 1, min(LONG_MAX, sign * int(text[digits:index]))), index


def _component(a: str, b: str) -> int:
    """`CAddonVersion::CompareComponent`, statement for statement."""

    i = j = 0
    while i < len(a) and j < len(b):
        while i < len(a) and j < len(b) and not a[i].isdigit() and not b[j].isdigit():
            if a[i] != b[j]:
                if a[i] == "~":
                    return -1
                if b[j] == "~":
                    return 1
                return -1 if a[i] < b[j] else 1
            i += 1
            j += 1
        if i < len(a) and j < len(b) and (not a[i].isdigit() or not b[j].isdigit()):
            if a[i] == "~":
                return -1
            if b[j] == "~":
                return 1
            return -1 if a[i].isdigit() else 1
        number_a, i = _strtol(a, i)
        number_b, j = _strtol(b, j)
        if number_a != number_b:
            return -1 if number_a < number_b else 1
    if i >= len(a) and j >= len(b):
        return 0
    if i < len(a):
        return -1 if a[i] == "~" else 1
    return 1 if b[j] == "~" else -1


def _parts(version: str) -> tuple[int, str, str]:
    upstream = version.lower() if version else "0.0.0"
    epoch = 0
    if ":" in upstream:
        head, _, upstream = upstream.partition(":")
        epoch, _ = _strtol(head, 0)
    revision = ""
    if "-" in upstream:
        upstream, _, revision = upstream.partition("-")
        if not set(revision) <= VALID:
            revision = ""
    if not set(upstream) <= VALID:
        upstream = "0.0.0"
    return epoch, upstream, revision


def compare(a: str, b: str) -> int:
    """-1, 0 or 1 as Kodi orders the add-on versions `a` and `b`."""

    epoch_a, upstream_a, revision_a = _parts(a)
    epoch_b, upstream_b, revision_b = _parts(b)
    if epoch_a != epoch_b:
        return -1 if epoch_a < epoch_b else 1
    return _component(upstream_a, upstream_b) or _component(revision_a, revision_b)


def stable(version: str) -> bool:
    return PRERELEASE.search(version.lower()) is None


def newest(versions: Iterable[str]) -> str | None:
    held = [version for version in versions if stable(version)]
    if not held:
        return None
    return max(held, key=functools.cmp_to_key(compare))


# --- Release Channels --------------------------------------------------------


@dataclass(frozen=True)
class Listing:
    """What one Release Channel offers: every version of every add-on in it."""

    channel: config.Channel
    versions: Mapping[str, tuple[str, ...]]

    def newest(self, addon_id: str) -> str | None:
        return newest(self.versions.get(addon_id, ()))

    def url(self, addon_id: str, version: str) -> str:
        """Where the channel's own convention puts one version's Artifact."""

        if self.channel.github_tags is not None:
            return (
                f"https://codeload.github.com/{self.channel.github_tags}"
                f"/zip/refs/tags/{version}"
            )
        assert self.channel.addons_xml is not None
        datadir = self.channel.addons_xml.rsplit("/", 1)[0]
        return f"{datadir}/{addon_id}/{addon_id}-{version}.zip"


def _listing(
    channel: config.Channel, records: Sequence[config.AddonArtifact]
) -> Listing:
    if channel.github_tags is not None:
        url = f"https://api.github.com/repos/{channel.github_tags}/tags?per_page=100"
        try:
            tags = json.loads(artifact.fetch(url))
            names = tuple(str(tag["name"]) for tag in tags)
        except (ValueError, TypeError, KeyError) as error:
            raise artifact.ArtifactError(f"{url} is not a list of tags") from error
        # Tags are versions of the one add-on the repository publishes, so
        # only the records naming this channel are offered by it.
        return Listing(
            channel,
            {record.id: names for record in records if record.channel == channel.name},
        )
    assert channel.addons_xml is not None
    blob = artifact.fetch(channel.addons_xml)
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    try:
        root = ElementTree.fromstring(blob)
    except ElementTree.ParseError as error:
        raise artifact.ArtifactError(
            f"{channel.addons_xml} does not parse as XML: {error}"
        ) from error
    versions: dict[str, list[str]] = {}
    for entry in root.findall("addon"):
        addon_id, version = entry.get("id"), entry.get("version")
        if addon_id and version:
            versions.setdefault(addon_id, []).append(version)
    return Listing(channel, {key: tuple(value) for key, value in versions.items()})


# --- What an add-on's addon.xml says -----------------------------------------


@dataclass(frozen=True)
class Manifest:
    requires: Mapping[str, str | None]
    news: str | None
    directories: tuple[str, ...]


def _manifest(members: tuple[artifact.Member, ...]) -> Manifest:
    document = next(
        member.data for member in members if member.path == "addon.xml" and member.data
    )
    root = ElementTree.fromstring(document)
    requires: dict[str, str | None] = {}
    for entry in root.findall("requires/import"):
        name = entry.get("addon")
        if name and entry.get("optional", "false").lower() != "true":
            requires[name] = entry.get("version")
    news = None
    for extension in root.findall("extension"):
        if extension.get("point") == "xbmc.addon.metadata":
            held = extension.findtext("news")
            news = held.strip() if held and held.strip() else None
    directories = tuple(
        (info.text or "").strip()
        for extension in root.findall("extension")
        if extension.get("point") == "xbmc.addon.repository"
        for info in extension.iter("info")
    )
    return Manifest(requires, news, directories)


# --- One Update Proposal -----------------------------------------------------


@dataclass
class Verdict:
    patch: artifact.Patch
    verdict: str
    said: str = ""


@dataclass
class Move:
    """One record the proposal moves, or adds."""

    id: str
    record: config.AddonArtifact | None
    channel: str
    version: str
    url: str
    why: str
    sha256: str = ""
    new: tuple[artifact.Member, ...] = ()
    old: tuple[artifact.Member, ...] | None = None
    manifest: Manifest | None = None
    old_manifest: Manifest | None = None
    verdicts: list[Verdict] = field(default_factory=list)
    patched_files: dict[str, str] = field(default_factory=dict)

    @property
    def was(self) -> str:
        return self.record.version if self.record else "(new)"


@dataclass
class Proposal:
    profile: str
    primary: Move
    moves: dict[str, Move]
    channels: Mapping[str, config.Channel]
    drafts: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.profile}/{self.primary.id}@{self.primary.version}"

    @property
    def branch(self) -> str:
        return f"update/{self.profile}/{self.primary.id}"

    @property
    def title(self) -> str:
        return f"Update {self.primary.id} to {self.primary.version} in {self.profile}"


class Run:
    """One pass over every Artifact Lock. Fetches are shared between Locks."""

    def __init__(self, err: TextIO) -> None:
        self.err = err
        self.failed = False
        self.listings: dict[config.Channel, Listing | None] = {}
        self.blobs: dict[str, bytes] = {}

    def fail(self, message: str) -> None:
        self.failed = True
        print(f"error: {message}", file=self.err)

    def listing(
        self, channel: config.Channel, records: Sequence[config.AddonArtifact]
    ) -> Listing | None:
        key = channel
        if channel.github_tags is not None:
            # Which records a tag listing is offered to depends on the Lock.
            return self._fetch_listing(channel, records)
        if key not in self.listings:
            self.listings[key] = self._fetch_listing(channel, records)
        return self.listings[key]

    def _fetch_listing(
        self, channel: config.Channel, records: Sequence[config.AddonArtifact]
    ) -> Listing | None:
        try:
            return _listing(channel, records)
        except artifact.ArtifactError as error:
            self.fail(f"the Release Channel {channel.name} was skipped: {error}")
            return None

    def fetch(self, url: str) -> bytes:
        if url not in self.blobs:
            self.blobs[url] = artifact.fetch(url)
        return self.blobs[url]


def propose(
    config_root: Path,
    out: Path,
    declined: Iterable[str],
    *,
    stdout: TextIO,
    err: TextIO,
) -> bool:
    """Writes every Update Proposal. False if anything had to be skipped."""

    run = Run(err)
    held = set(declined)
    if out.exists() and any(out.iterdir()):
        raise config.ConfigError(f"the proposal directory is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for document in sorted(config_root.rglob(config.ADDONS)):
        shared = config_root / "shared"
        profile = (
            document.parent.relative_to(shared)
            if document.is_relative_to(shared)
            else document.parent.relative_to(config_root)
        ).as_posix()
        for proposal in _proposals(run, document, profile, held):
            destination = out / profile / proposal.primary.id
            try:
                _write(proposal, document, config_root, destination)
            except ProposalError as error:
                run.fail(f"no Update Proposal for {proposal.key}: {error}")
                shutil.rmtree(destination, ignore_errors=True)
                continue
            written += 1
            state = " (draft)" if proposal.drafts else ""
            print(f"proposed {proposal.key}{state}", file=stdout)
    if not written:
        print("no Update Proposals", file=stdout)
    return not run.failed


def _proposals(
    run: Run, document: Path, profile: str, declined: set[str]
) -> list[Proposal]:
    channels, records = config.artifact_lock(document)
    listings = {
        name: run.listing(channel, records) for name, channel in channels.items()
    }
    pinned = {record.id: record for record in records}
    candidates: list[Proposal] = []
    for record in records:
        listing = listings.get(record.channel) if record.channel else None
        if listing is None:
            continue
        offered = listing.newest(record.id)
        if offered is None or compare(offered, record.version) <= 0:
            continue
        if f"{profile}/{record.id}@{offered}" in declined:
            continue
        primary = Move(
            id=record.id,
            record=record,
            channel=listing.channel.name,
            version=offered,
            url=listing.url(record.id, offered),
            why="a newer Stable Release",
        )
        try:
            candidates.append(
                _compose(run, profile, primary, pinned, channels, listings)
            )
        except (artifact.ArtifactError, ProposalError) as error:
            run.fail(f"no Update Proposal for {record.id} {offered}: {error}")
    # A record another proposal already moves gets no proposal of its own.
    carried = {
        moved
        for proposal in candidates
        for moved in proposal.moves
        if moved != proposal.primary.id
    }
    return [proposal for proposal in candidates if proposal.primary.id not in carried]


def _compose(
    run: Run,
    profile: str,
    primary: Move,
    pinned: Mapping[str, config.AddonArtifact],
    channels: Mapping[str, config.Channel],
    listings: Mapping[str, Listing | None],
) -> Proposal:
    proposal = Proposal(profile, primary, {primary.id: primary}, channels)
    queue = [primary]
    while queue:
        move = queue.pop(0)
        _fetch(run, proposal, move)
        assert move.manifest is not None
        before = move.old_manifest.requires if move.old_manifest else None
        for name, floor in move.manifest.requires.items():
            if name.startswith(KODI_OWN):
                continue
            if name in proposal.moves:
                moved = proposal.moves[name]
                if floor and compare(moved.version, floor) < 0:
                    proposal.drafts.append(
                        f"{move.id} {move.version} requires {name} {floor}, "
                        f"and this proposal moves it only to {moved.version}"
                    )
                continue
            record = pinned.get(name)
            if record is not None:
                if not floor or compare(record.version, floor) >= 0:
                    continue
                forced = _forced(proposal, move, record, floor, listings)
                if forced is not None:
                    proposal.moves[name] = forced
                    queue.append(forced)
                continue
            if before is not None and name in before:
                continue
            added = _required(proposal, move, name, floor, listings)
            if added is not None:
                proposal.moves[name] = added
                queue.append(added)
        if before is not None:
            for name, floor in move.manifest.requires.items():
                if name not in before:
                    proposal.requirements.append(
                        f"{move.id} {move.version} newly requires "
                        f"`{name}` {floor or '(any version)'}"
                    )
                elif before[name] != floor:
                    proposal.requirements.append(
                        f"{move.id} {move.version} raises its floor on `{name}` "
                        f"from {before[name] or '(any version)'} to "
                        f"{floor or '(any version)'}"
                    )
            for name in before:
                if name not in move.manifest.requires:
                    proposal.requirements.append(
                        f"{move.id} {move.version} no longer requires `{name}`. "
                        "Nothing is removed from the Lock."
                    )
    for move in proposal.moves.values():
        _triage(proposal, move)
    return proposal


def _forced(
    proposal: Proposal,
    move: Move,
    record: config.AddonArtifact,
    floor: str,
    listings: Mapping[str, Listing | None],
) -> Move | None:
    listing = listings.get(record.channel) if record.channel else None
    offered = listing.newest(record.id) if listing else None
    if listing is None or offered is None or compare(offered, floor) < 0:
        where = (
            f"its channel {record.channel} offers {offered or 'nothing'}"
            if record.channel
            else "it names no Release Channel"
        )
        proposal.drafts.append(
            f"{move.id} {move.version} requires {record.id} {floor}, the Lock "
            f"pins {record.version}, and {where}"
        )
        return None
    return Move(
        id=record.id,
        record=record,
        channel=listing.channel.name,
        version=offered,
        url=listing.url(record.id, offered),
        why=f"{move.id} {move.version} requires {floor}",
    )


def _required(
    proposal: Proposal,
    move: Move,
    name: str,
    floor: str | None,
    listings: Mapping[str, Listing | None],
) -> Move | None:
    """A requirement new to the Lock, added only if one channel offers it."""

    offering = [
        (listing, offered)
        for listing in listings.values()
        if listing is not None
        and (offered := listing.newest(name)) is not None
        and (not floor or compare(offered, floor) >= 0)
    ]
    if len(offering) != 1:
        where = (
            ", ".join(
                f"{listing.channel.name} ({offered})" for listing, offered in offering
            )
            or "no channel the Lock names"
        )
        proposal.drafts.append(
            f"{move.id} {move.version} newly requires `{name}` "
            f"{floor or '(any version)'}, and it is offered by {where}. "
            "Add it to the Lock by hand"
        )
        return None
    listing, offered = offering[0]
    return Move(
        id=name,
        record=None,
        channel=listing.channel.name,
        version=offered,
        url=listing.url(name, offered),
        why=f"{move.id} {move.version} newly requires it",
    )


def _fetch(run: Run, proposal: Proposal, move: Move) -> None:
    """The proposed Artifact, and the pinned one it is compared against."""

    blob = run.fetch(move.url)
    move.sha256 = sha256(blob).hexdigest()
    move.new = artifact.expand(blob, move.id, move.version)
    move.manifest = _manifest(move.new)
    if move.record is None:
        return
    try:
        pinned = artifact.download(move.record.url, move.record.sha256)
        move.old = artifact.expand(pinned, move.id, move.record.version)
    except artifact.ArtifactError as error:
        proposal.drafts.append(
            f"the pinned {move.id} {move.record.version} could not be fetched to "
            f"compare against ({error}), so no upstream diff or requirement "
            "change is shown for it"
        )
        return
    move.old_manifest = _manifest(move.old)


def _triage(proposal: Proposal, move: Move) -> None:
    """A verdict on each of the moved record's Artifact Patches."""

    if move.record is None or not move.record.patches:
        return
    tree = move.new
    carried: list[artifact.Patch] = []
    for patch in move.record.patches:
        applies, said = artifact.attempt(tree, patch)
        if applies:
            _, _, rest = patch.diff.partition("\n")
            rewritten = artifact.Patch(
                name=patch.name, diff=f"# {move.id} {move.version}\n{rest}"
            )
            try:
                tree = artifact.patched(tree, move.id, [rewritten])
            except artifact.ArtifactError as error:
                proposal.drafts.append(str(error))
                move.verdicts.append(Verdict(patch, "Stale", str(error)))
                continue
            carried.append(rewritten)
            move.verdicts.append(Verdict(rewritten, "Carried"))
            continue
        reversed_, _ = artifact.attempt(tree, patch, reverse=True)
        if reversed_:
            move.verdicts.append(Verdict(patch, "Obsolete"))
            continue
        move.verdicts.append(Verdict(patch, "Stale", said))
        proposal.drafts.append(
            f"{patch.name} neither applies to {move.id} {move.version} nor is "
            "already contained in it, so it must be rewritten"
        )
    touched = sorted({path for patch in carried for path in artifact.touched(patch)})
    move.patched_files = artifact.digests(tree, touched)


# --- Writing a proposal out --------------------------------------------------


def _write(
    proposal: Proposal, document: Path, config_root: Path, destination: Path
) -> None:
    """The proposal as files: what changes, what is deleted, and the body.

    Every path is relative to the configuration root, so the workflow copies
    `files/` over it and removes what `deleted` names.
    """

    directory = document.parent
    files: dict[Path, str] = {}
    removed: list[Path] = []
    pins: list[lock.Pin] = []
    for move in proposal.moves.values():
        kept = [
            verdict.patch.name
            for verdict in move.verdicts
            if verdict.verdict in ("Carried", "Stale")
        ]
        for verdict in move.verdicts:
            path = directory / config.PATCHES / move.id / verdict.patch.name
            if verdict.verdict == "Carried":
                files[path] = verdict.patch.diff
            elif verdict.verdict == "Obsolete":
                removed.append(path)
        stale = any(verdict.verdict == "Stale" for verdict in move.verdicts)
        recorded = dict(move.patched_files)
        if stale and move.record is not None:
            # The Lock keeps what it recorded, because nothing produced a new
            # answer, and still fails loudly on the Stale patch's header.
            recorded.update(
                {
                    path: digest
                    for path, digest in move.record.patched_files.items()
                    if digest is not None and path not in recorded
                }
            )
        pins.append(
            lock.Pin(
                id=move.id,
                version=move.version,
                url=move.url,
                sha256=move.sha256,
                channel=move.channel,
                patches=tuple(kept),
                patched_files=recorded,
            )
        )
    files[document] = lock.repin(document.read_text(encoding="utf-8"), pins)
    if not any(
        verdict.verdict == "Stale"
        for move in proposal.moves.values()
        for verdict in move.verdicts
    ):
        _check(document, files, removed)

    destination.mkdir(parents=True)
    for path, text in files.items():
        target = destination / "files" / path.relative_to(config_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (destination / "deleted").write_text(
        "".join(f"{path.relative_to(config_root).as_posix()}\n" for path in removed),
        encoding="utf-8",
    )
    (destination / "body.md").write_text(_body(proposal), encoding="utf-8")
    (destination / "proposal.json").write_text(
        json.dumps(
            {
                "branch": proposal.branch,
                "title": proposal.title,
                "draft": bool(proposal.drafts),
                "key": proposal.key,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _check(document: Path, files: Mapping[Path, str], removed: Sequence[Path]) -> None:
    """The proposed Lock, read back the way `plan` and `apply` will read it."""

    directory = document.parent
    with tempfile.TemporaryDirectory() as workspace:
        copy = Path(workspace) / "profile"
        shutil.copytree(directory, copy)
        for path, text in files.items():
            (copy / path.relative_to(directory)).write_text(text, encoding="utf-8")
        for path in removed:
            (copy / path.relative_to(directory)).unlink()
        try:
            config.artifact_lock(copy / document.name)
        except config.ConfigError as error:
            raise ProposalError(f"the proposed Lock does not read: {error}") from error


def _fenced(text: str, language: str = "text") -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}{language}\n{text.rstrip()}\n{fence}\n"


def _diff(move: Move, path: str) -> str:
    def text(members: tuple[artifact.Member, ...] | None) -> list[str]:
        for member in members or ():
            if member.path == path and member.data is not None:
                return member.data.decode("utf-8", errors="replace").splitlines(
                    keepends=True
                )
        return []

    lines = list(
        difflib.unified_diff(
            text(move.old),
            text(move.new),
            fromfile=f"a/{path} ({move.was})",
            tofile=f"b/{path} ({move.version})",
        )
    )
    if not lines:
        return "Upstream did not change this file.\n"
    shown = "".join(
        line if line.endswith("\n") else line + "\n" for line in lines[:DIFF_LINES]
    )
    if len(lines) > DIFF_LINES:
        shown += f"… {len(lines) - DIFF_LINES} more lines\n"
    return _fenced(shown, "diff")


def _body(proposal: Proposal) -> str:
    primary = proposal.primary
    parts = [
        f"<!-- update-proposal: {proposal.key} -->\n",
        f"Moves `{primary.id}` from {primary.was} to {primary.version} in the "
        f"`{proposal.profile}` Artifact Lock, from its Release Channel "
        f"`{primary.channel}`. Nothing merges this but a human.\n",
    ]
    if proposal.drafts:
        parts.append("\n**This proposal is a draft.**\n\n")
        parts.extend(f"- {reason}.\n" for reason in proposal.drafts)
    parts.append(
        "\n## Versions\n\n"
        "| add-on | role | from | to | channel | why |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
    )
    for move in proposal.moves.values():
        role = move.record.role if move.record else "dependency"
        parts.append(
            f"| `{move.id}` | {role} | {move.was} | {move.version} | "
            f"{move.channel} | {move.why} |\n"
        )
    noted = [
        move for move in proposal.moves.values() if move.record and move.record.notes
    ]
    if noted:
        parts.append("\n## Notes\n\nRead these before accepting the move.\n")
        for move in noted:
            assert move.record is not None and move.record.notes is not None
            parts.append(f"\n`{move.id}`:\n\n")
            parts.extend(f"> {line}\n" for line in move.record.notes.splitlines())
    parts.append("\n## News\n")
    for move in proposal.moves.values():
        news = move.manifest.news if move.manifest else None
        parts.append(f"\n### `{move.id}` {move.version}\n\n")
        parts.append(_fenced(news) if news else "Upstream gives no `<news>`.\n")
    if proposal.requirements:
        parts.append("\n## Requirements\n\n")
        parts.extend(f"- {line}\n" for line in proposal.requirements)
    for move in proposal.moves.values():
        if move.record is None or move.record.role != "repository":
            continue
        if move.old_manifest is None or move.manifest is None:
            continue
        gone = [
            d
            for d in move.old_manifest.directories
            if d not in move.manifest.directories
        ]
        arrived = [
            d
            for d in move.manifest.directories
            if d not in move.old_manifest.directories
        ]
        if gone or arrived:
            moved = sorted(
                channel.name
                for channel in proposal.channels.values()
                if channel.addons_xml in gone
            )
            parts.append(
                f"\n## Repository directories\n\n`{move.id}` {move.version} "
                "changes the directories it publishes.\n\n"
            )
            parts.extend(f"- It no longer publishes {d}\n" for d in gone)
            parts.extend(f"- It now publishes {d}\n" for d in arrived)
            parts.append(
                "\n"
                + (
                    f"Release Channels the Lock names that moved: "
                    f"{', '.join(moved)}. Edit the `channels:` map by hand "
                    "before accepting this.\n"
                    if moved
                    else "No Release Channel the Lock names has moved.\n"
                )
            )
    verdicts = [move for move in proposal.moves.values() if move.verdicts]
    if verdicts:
        parts.append("\n## Artifact Patches\n")
        for move in verdicts:
            for verdict in move.verdicts:
                parts.append(f"\n### `{verdict.patch.name}`: {verdict.verdict}\n\n")
                parts.append(
                    {
                        "Carried": (
                            "It still applies. Its header now names "
                            f"{move.version}, and its post-patch hashes are "
                            "recorded.\n"
                        ),
                        "Obsolete": (
                            "It reverse-applies, so the new version already holds "
                            "what it wrote, and it is removed. That is evidence "
                            "upstream fixed the fault, not proof: confirm it.\n"
                        ),
                        "Stale": (
                            "It neither applies nor reverse-applies. Rewrite it "
                            f"against {move.version}. What `patch` said:\n\n"
                        ),
                    }[verdict.verdict]
                )
                if verdict.verdict == "Stale" and verdict.said:
                    parts.append(_fenced(verdict.said))
                for path in artifact.touched(verdict.patch):
                    parts.append(f"\nUpstream diff of `{path}`:\n\n")
                    parts.append(_diff(move, path))
    parts.append(
        "\n## Acceptance\n\n"
        "- [ ] A Device running this Profile was reconciled from this branch\n"
    )
    return "".join(parts)
