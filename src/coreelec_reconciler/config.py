"""Reading the Profile and the Room Overlay into Desired State.

Both files use a strict schema: an unknown or missing key is rejected naming
the key, so a typo can never be read as a silent default.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from . import artifact, env_file, kodi_settings


class ConfigError(Exception):
    """A Profile or Room Overlay that cannot be read as Desired State."""


# What a Settings Document is written with unless it declares otherwise.
DOCUMENT_MODE = "0600"

# What `authorized_keys` is written with. Not declarable: `sshd` refuses a
# file any other user can write, so there is one correct answer and a Profile
# stating it could only ever state it wrongly.
AUTHORIZED_KEYS_MODE = "0600"

# One OpenSSH public key line: a key type, a base64 blob, and an optional
# comment carrying no control characters. This is the shell's grammar
# (`lib/coreelec-ssh.sh`), enforced here for the same reason — the line is
# embedded in a program a Device runs, and a validated line can hold no
# newline and no here-document delimiter.
PUBLIC_KEY = re.compile(
    r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)"
    r"|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)"
    r" ([A-Za-z0-9+/]+={0,3})"
    r"(?: ([^\x00-\x1f\x7f]*))?"
)

# The name of the Artifact Lock, which sits beside `profile.yaml` in the same
# Profile directory rather than inside it: an Action will eventually rewrite
# it, and a bot editing the file humans edit for settings turns every version
# bump into a conflict (ADR 0017).
ADDONS = "addons.yaml"

# The directory holding the Artifact Patches, beside the Lock. One
# subdirectory per add-on, and the Lock record lists the files it applies
# (ADR 0017).
PATCHES = "patches"

# An add-on id is a directory name on the Device and a value inside a SQL
# statement, so the grammar is narrow enough that neither can be anything but
# a name. Kodi's own ids are dotted lowercase words.
ADDON_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

# Kodi's version grammar (`CAddonVersion`): digits, letters, and the
# separators `. _ - + ~`. A leading `-` or `~` is refused because it is never
# a published version and `~` sorts below everything.
ADDON_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]*")

# A digest is compared against `hashlib`'s own rendering, which is lowercase,
# so the Lock states it lowercase rather than folding case at every read.
SHA256 = re.compile(r"[0-9a-f]{64}")

# Why an add-on is in the Profile at all. `chosen` is a decision someone made,
# `dependency` is a consequence of one, and `repository` is the kind whose
# enablement could invite Kodi to go and fetch something (ADR 0017).
ADDON_ROLES = ("chosen", "dependency", "repository")


# A setting a human declares positively that Kodi stores negatively, or as an
# ordinal, needs a transform between the declaration and the Device. Each one
# has a closed domain: a value outside it is a mistake, not a literal to pass
# through, because Kodi would silently ignore what it wrote.
TRANSFORMS: dict[str, dict[str, str]] = {
    "invert": {"true": "false", "false": "true"},
    "dolby_vision_mode": {"tv-led": "0", "player-led": "1"},
    # Kodi's localisation ID for the CEC "Ignore" action. The shell reads it
    # from a variable and then rejects every value but that one, so the domain
    # is declared here instead and the schema carries the validation.
    "cec_tv_off_action": {"ignore": "36028"},
}

# A rule that selects on the calendar cannot state a literal. A Profile saying
# `year greaterthan 2024` is true until 1 January and wrong every day after,
# and the shell renders the same rule from today's date, so the two would
# disagree annually and never converge. Such a rule declares an offset and the
# base the offset is measured from, and the base is resolved on every read.
RELATIVE_BASES: dict[str, Callable[[datetime.date], int]] = {
    "current_year": lambda today: today.year,
}


@dataclass(frozen=True)
class Platform:
    """What the Device is claimed to be, checked before anything is planned.

    A Profile declares the identity, not how to check it: which file holds
    which key is the Reconciler's business, and a Profile naming paths and
    patterns would be the only block declaring mechanism.
    """

    id: str
    version: str
    device: str
    release_contains: str


@dataclass(frozen=True)
class Transport:
    user: str
    port: int
    identity: Path


@dataclass(frozen=True)
class Addresses:
    """The Device addresses the Reconciler knows the meaning of.

    Every other address reaches the Reconciler as the State Address of a
    Resource. These five do not: the Reconciler knows which unit reads the
    timezone cache and which reads `sshd.conf`, where add-ons live, which
    database holds their enabled flags, and where Kodi lists the add-ons it
    ships with — but knowing what an address *means* is not the same as
    knowing where it *is*.

    So the meaning stays in code and the address is declared here. The Kodi
    schema version is in the database's filename, so a Profile branched for a
    future Kodi changes one line rather than forking the Reconciler
    (ADR 0018). No Device address lives in code.
    """

    timezone_cache: str
    sshd_conf: str
    addons: str
    addon_database: str
    addon_manifest: str


@dataclass(frozen=True)
class AddonArtifact:
    """One record of the Artifact Lock: an add-on, pinned to bytes.

    Appearing here *is* the statement that the add-on should be installed at
    this version and enabled. The two facts are never independently
    desirable, so they are one declaration that cannot disagree with itself
    (ADR 0018).

    `notes` carries the deviation rationale a reviewer of a future version
    bump needs — why this version and not the newest — and is the one field
    nothing but a human reads. `role` answers the other question, why the
    add-on is here at all: bumping a `chosen` add-on is a decision someone
    makes, and bumping a `dependency` is a consequence of one (ADR 0017).

    `patches` are the Artifact Patches applied to the expanded Artifact on
    the controller, read from `patches/<id>/` beside the Lock.
    `patched_files` is the post-patch SHA-256 of each file those diffs touch,
    which is how a patched add-on is observed: correcting a patch does not
    move the add-on's version, so the version alone would never ship the
    correction. A hash of None is one nothing has recorded yet, which
    `record-patches` fills in (ADR 0017).
    """

    id: str
    version: str
    url: str
    sha256: str
    role: str
    notes: str | None = None
    patches: tuple[artifact.Patch, ...] = ()
    patched_files: Mapping[str, str | None] = MappingProxyType({})


@dataclass(frozen=True)
class Rule:
    field: str
    operator: str
    value: str


@dataclass(frozen=True)
class SmartPlaylist:
    """One Kodi Smart Playlist. Its State Address is its path on the Device.

    `path` is where the file is written; `kodi_path` is how Kodi addresses the
    same file from inside a skin. They are two names for one document, and a
    Shortcut Node that references this playlist carries the second.
    """

    path: str
    kodi_path: str
    name: str
    media_type: str
    match: str
    limit: int
    order_field: str
    order_direction: str
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class KodiSetting:
    """One Kodi setting. Its State Address is the ID inside the document.

    `value` is what reaches the Device; `declared` is what the file states.
    The two differ only where a transform stands between them, or where the
    file names the value rather than holding it, in which case `named_by` is
    the `.env` key it was read from and `declared` is that key.

    A `value` of None is a Cleared Address: the Device must resolve no value
    at all. It is not the empty string, which Kodi cannot store — an empty
    node reads back as no value — and which would therefore plan a Change on
    every Run and fail its own Verification forever.

    `divergent` is the reason this address deliberately holds a value the
    Recovery Baseline cannot produce, so a shell run after an `apply` leaves
    a Change here by intent rather than by mistake (ADR 0012). It is stated
    per address and never as a blanket flag: an undeclared disagreement must
    still fail, because that is the fault rule 3 was written to catch.
    """

    setting: str
    value: str | None
    declared: str
    transform: str | None = None
    named_by: str | None = None
    divergent: str | None = None


@dataclass(frozen=True)
class SettingsDocument:
    """One Settings Document and the State Addresses owned inside it.

    `dialect` says how the document is serialised. It is declared, never
    sniffed: a corrupt or truncated document must fail naming itself rather
    than read as a plausible other shape.

    `document` is the file's path, or — when `is_glob` — the pattern that
    names it, for a document Kodi names after hardware the Profile cannot
    know. Which of the two it is comes from the key the Profile states, never
    from the string: a literal path holding a `*` is a path.

    `compiles_to` names an artifact an add-on builds from this document. It is
    stale the moment the source changes, and the Run rebuilds it.

    `mode` is the file's mode on the Device. Which service a Change here
    disturbs is not declared: the Resource Type knows it (ADR 0013).
    """

    document: str
    dialect: str
    settings: tuple[KodiSetting, ...]
    is_glob: bool = False
    compiles_to: str | None = None
    mode: str = DOCUMENT_MODE


@dataclass(frozen=True)
class Shortcut:
    """One entry in a Shortcut Node, in `script.skinvariables`' own shape.

    The type is recursive because upstream's is: `submenu` and `widgets` hold
    items of exactly this kind, and the add-on walks them recursively. Nothing
    in the fleet nests anything today, and the self-reference costs a line;
    a flat type would have to be revisited by every Profile written against it
    the first time a submenu appears.

    `guid` is always declared and never generated. The add-on invents
    `guid-{random}` for an item that carries none, which would differ on every
    Run and plan a Change forever.
    """

    guid: str
    label: str
    path: str
    icon: str
    target: str
    submenu: tuple[Shortcut, ...] = ()
    widgets: tuple[Shortcut, ...] = ()


@dataclass(frozen=True)
class ShortcutNode:
    """One node file the Reconciler renders whole.

    Each file is declared by name. The directory holding them is never
    enumerated: the skin ships node files of its own beside these, carrying
    generated guids, and owning the directory would delete them.
    """

    document: str
    shortcuts: tuple[Shortcut, ...]


@dataclass(frozen=True)
class AuthorizedKey:
    """One entry in `authorized_keys`: a key, and what it may do.

    `key_type` and `blob` are the key itself. The comment the key file
    carried is discarded and `comment` is what reaches the Device, so an
    entry is found by a stable name rather than by whoever generated the key.

    `forced_command` is the only program the key may ever run. An entry
    carrying one is written `restrict,command="..."`, which on OpenSSH 7.2
    and later already implies no agent forwarding, no port forwarding, no
    pty, no user rc and no X11 forwarding. The administrator entry carries
    none and may do anything.

    `named_by` is the `.env` key the public key was read from, when Desired
    State named it rather than holding it.
    """

    comment: str
    key_type: str
    blob: str
    forced_command: str | None = None
    named_by: str | None = None


@dataclass(frozen=True)
class AuthorizedKeys:
    """Who may log in to the Device, declared whole.

    The Reconciler owns every byte of this document, so an entry nobody
    declared is removed rather than tolerated. Appending if absent — what the
    shell does — can only ever grow the file, which means a revoked key is
    never actually revoked.

    `entries` begins with the administrator entry, which is derived from the
    public half of the identity the Run authenticates with and is never
    declared: a Profile that can name an administrator key can name the wrong
    one and lock the Reconciler out of its own Device.
    """

    document: str
    entries: tuple[AuthorizedKey, ...]
    mode: str = AUTHORIZED_KEYS_MODE


@dataclass(frozen=True)
class DesiredState:
    room: str
    hostname: str
    profile: str
    platform: Platform
    transport: Transport
    addresses: Addresses
    authorized_keys: AuthorizedKeys
    playlists: tuple[SmartPlaylist, ...]
    documents: tuple[SettingsDocument, ...]
    addons: tuple[AddonArtifact, ...] = ()
    shortcut_nodes: tuple[ShortcutNode, ...] = ()


def _read(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"{path}: {error.strerror or error}") from error
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"{path}: {error}") from error
    if not isinstance(document, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return document


def _fields(
    source: Path,
    where: str,
    mapping: dict[str, Any],
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> dict[str, Any]:
    unknown = sorted(set(mapping) - set(required) - set(optional))
    if unknown:
        raise ConfigError(f"{source}: unknown key in {where}: {unknown[0]}")
    missing = [key for key in required if key not in mapping]
    if missing:
        raise ConfigError(f"{source}: missing key in {where}: {missing[0]}")
    return mapping


def _mapping(source: Path, where: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{source}: expected a mapping for {where}")
    return value


def _text(source: Path, where: str, value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise ConfigError(f"{source}: expected a value for {where}")
    return str(value)


def _integer(source: Path, where: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{source}: expected a whole number for {where}")
    return value


def _relative(source: Path, where: str, value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ConfigError(f"{source}: {where} must stay inside the tree: {value}")
    return value


def _transform(source: Path, name: str | None, value: str) -> str:
    """The value that reaches the Device for a declaration of `value`."""

    if name is None:
        return value
    mapping = TRANSFORMS.get(name)
    if mapping is None:
        known = ", ".join(sorted(TRANSFORMS))
        raise ConfigError(f"{source}: unknown transform: {name} (known: {known})")
    if value not in mapping:
        allowed = ", ".join(sorted(mapping))
        raise ConfigError(
            f"{source}: the transform {name} cannot read the value {value} "
            f"(it reads: {allowed})"
        )
    return mapping[value]


class NamedValues:
    """The shared `.env`, read once and only when Desired State names a value.

    A Run that names nothing never opens the file, so a checkout holding no
    secrets at all still plans and applies everything else.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._values: dict[str, str] | None = None

    def value(self, source: Path, key: str) -> str:
        """What `.env` holds for `key`, or an error naming the key."""

        if self._values is None:
            try:
                self._values = env_file.read(self._path)
            except env_file.EnvError as error:
                raise ConfigError(
                    f"{source} names {key}, and the shared environment file "
                    f"cannot be read: {error}"
                ) from error
        held = self._values.get(key, "")
        if not held:
            raise ConfigError(f"{source} names {key}, which {self._path} does not hold")
        return held


def _rule_value(source: Path, mapping: dict[str, Any]) -> str:
    """The value a rule puts on the Device, resolving a calendar base."""

    if "relative_to" not in mapping:
        return _text(source, "rule value", mapping["value"])

    name = _text(source, "rule relative_to", mapping["relative_to"])
    resolve = RELATIVE_BASES.get(name)
    if resolve is None:
        known = ", ".join(sorted(RELATIVE_BASES))
        raise ConfigError(f"{source}: unknown relative_to: {name} (known: {known})")
    offset = mapping["value"]
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ConfigError(
            f"{source}: a rule relative to {name} states a whole-number offset, "
            f"not: {offset}"
        )
    return str(resolve(datetime.date.today()) + offset)


def _rule(source: Path, raw: Any) -> Rule:
    mapping = _fields(
        source,
        "a rule",
        _mapping(source, "a rule", raw),
        required=("field", "operator", "value"),
        optional=("relative_to",),
    )
    return Rule(
        field=_text(source, "rule field", mapping["field"]),
        operator=_text(source, "rule operator", mapping["operator"]),
        value=_rule_value(source, mapping),
    )


def _playlist(
    source: Path, directory: str, kodi_directory: str, raw: Any
) -> SmartPlaylist:
    mapping = _fields(
        source,
        "a playlist",
        _mapping(source, "a playlist", raw),
        required=("file", "name", "type", "match", "limit", "order", "rules"),
    )
    file_name = _relative(
        source, "a playlist file", _text(source, "playlist file", mapping["file"])
    )
    if Path(file_name).name != file_name:
        raise ConfigError(f"{source}: a playlist file must be a bare name: {file_name}")
    order = _fields(
        source,
        "a playlist order",
        _mapping(source, "a playlist order", mapping["order"]),
        required=("field", "direction"),
    )
    rules = mapping["rules"]
    if not isinstance(rules, list) or not rules:
        raise ConfigError(f"{source}: {file_name} needs at least one rule")
    return SmartPlaylist(
        path=f"{directory.rstrip('/')}/{file_name}",
        kodi_path=f"{kodi_directory.rstrip('/')}/{file_name}",
        name=_text(source, "playlist name", mapping["name"]),
        media_type=_text(source, "playlist type", mapping["type"]),
        match=_text(source, "playlist match", mapping["match"]),
        limit=_integer(source, "playlist limit", mapping["limit"]),
        order_field=_text(source, "order field", order["field"]),
        order_direction=_text(source, "order direction", order["direction"]),
        rules=tuple(_rule(source, rule) for rule in rules),
    )


def _shortcut(source: Path, playlists: dict[str, SmartPlaylist], raw: Any) -> Shortcut:
    mapping = _fields(
        source,
        "a shortcut",
        _mapping(source, "a shortcut", raw),
        required=("guid",),
        optional=("playlist", "path", "label", "icon", "target", "submenu", "widgets"),
    )
    guid = _text(source, "a shortcut guid", mapping["guid"])
    # The add-on invents a random guid for an item that states none, and an
    # empty string is stated none. A document carrying one differs on every
    # Run and plans a Change forever.
    if not guid:
        raise ConfigError(f"{source}: a shortcut guid must not be empty")
    # Where the shortcut goes is stated either as a Smart Playlist the Profile
    # already declares or as a literal path — a builtin, or a playlist some
    # other add-on supplies. The reference arm is what makes a shortcut
    # pointing at a retired playlist unrepresentable rather than merely
    # detectable.
    stated = [arm for arm in ("playlist", "path") if arm in mapping]
    if len(stated) != 1:
        raise ConfigError(
            f"{source}: the shortcut {guid} states exactly one of playlist and path"
        )
    if stated == ["playlist"]:
        if "label" in mapping:
            raise ConfigError(
                f"{source}: the shortcut {guid} names a playlist, which "
                "supplies its label"
            )
        file_name = _text(source, f"the playlist of {guid}", mapping["playlist"])
        playlist = playlists.get(file_name)
        if playlist is None:
            raise ConfigError(
                f"{source}: the shortcut {guid} names the playlist "
                f"{file_name}, which this Profile does not declare"
            )
        path, label = playlist.kodi_path, playlist.name
    else:
        path = _text(source, f"the path of {guid}", mapping["path"])
        if "label" not in mapping:
            raise ConfigError(
                f"{source}: the shortcut {guid} states a path, and a shortcut "
                "holding its own path states its own label"
            )
        label = _text(source, f"the label of {guid}", mapping["label"])
    return Shortcut(
        guid=guid,
        label=label,
        path=path,
        # The add-on's default item carries both keys, so an undeclared icon
        # or target is the empty string rather than an absent key.
        icon=_text(source, f"the icon of {guid}", mapping.get("icon", "")),
        target=_text(source, f"the target of {guid}", mapping.get("target", "")),
        submenu=_shortcuts(source, playlists, mapping.get("submenu", [])),
        widgets=_shortcuts(source, playlists, mapping.get("widgets", [])),
    )


def _shortcuts(
    source: Path, playlists: dict[str, SmartPlaylist], raw: Any
) -> tuple[Shortcut, ...]:
    if not isinstance(raw, list):
        raise ConfigError(f"{source}: a list of shortcuts is expected here")
    return tuple(_shortcut(source, playlists, entry) for entry in raw)


def _shortcut_node(
    source: Path, playlists: dict[str, SmartPlaylist], raw: Any
) -> ShortcutNode:
    mapping = _fields(
        source,
        "a Shortcut Node",
        _mapping(source, "a Shortcut Node", raw),
        required=("document", "shortcuts"),
    )
    document = _text(source, "a Shortcut Node document", mapping["document"])
    if not document.startswith("/"):
        raise ConfigError(
            f"{source}: a Shortcut Node path must be absolute: {document}"
        )
    declared = mapping["shortcuts"]
    if not isinstance(declared, list) or not declared:
        raise ConfigError(f"{source}: {document} declares no shortcuts")
    shortcuts = _shortcuts(source, playlists, declared)
    # The add-on finds an item by walking the whole tree for its guid, so a
    # guid repeated at any depth is one shortcut shadowing another.
    seen: set[str] = set()
    for shortcut in _walk(shortcuts):
        if shortcut.guid in seen:
            raise ConfigError(
                f"{source}: {document} declares the shortcut {shortcut.guid} twice"
            )
        seen.add(shortcut.guid)
    return ShortcutNode(document=document, shortcuts=shortcuts)


def _walk(shortcuts: Iterable[Shortcut]) -> Iterator[Shortcut]:
    for shortcut in shortcuts:
        yield shortcut
        yield from _walk(shortcut.submenu)
        yield from _walk(shortcut.widgets)


def _kodi_setting(
    source: Path, named: NamedValues, constants: Mapping[str, str], raw: Any
) -> KodiSetting:
    mapping = _fields(
        source,
        "a Kodi setting",
        _mapping(source, "a Kodi setting", raw),
        required=("setting",),
        optional=(
            "value",
            "from_env",
            "from_profile",
            "unset",
            "transform",
            "divergent",
        ),
    )
    setting = _text(source, "a Kodi setting id", mapping["setting"])
    # Why the Recovery Baseline cannot produce this value. A key stating an
    # empty reason is a declaration that says nothing, and a reviewer reading
    # rule 3's one expected Change would learn nothing from it.
    divergent: str | None = None
    if "divergent" in mapping:
        divergent = _text(
            source, f"the divergent of {setting}", mapping["divergent"]
        ).strip()
        if not divergent:
            raise ConfigError(
                f"{source}: the divergent of {setting} states why the Recovery "
                "Baseline cannot produce this value"
            )
    # The four arms are mutually exclusive and one is mandatory. A setting
    # stating none of them is the shape a truncated line produces, and one
    # stating two says two different things about the same address.
    arms = ("value", "from_env", "from_profile", "unset")
    stated = [arm for arm in arms if arm in mapping]
    if len(stated) != 1:
        listed = ", ".join(arms[:-1]) + f" and {arms[-1]}"
        raise ConfigError(f"{source}: {setting} states exactly one of {listed}")
    if stated == ["from_env"]:
        if "transform" in mapping:
            raise ConfigError(
                f"{source}: {setting} names its value in .env, and a named "
                "value takes no transform"
            )
        key = _text(source, f"the from_env of {setting}", mapping["from_env"])
        return KodiSetting(
            setting=setting,
            value=named.value(source, key),
            declared=key,
            named_by=key,
            divergent=divergent,
        )
    if stated == ["unset"]:
        # Only `true`. `unset: false` would be a setting saying nothing about
        # its own value, and a Profile that meant to hold one says `value`.
        if mapping["unset"] is not True:
            raise ConfigError(
                f"{source}: the unset of {setting} states true, and a setting "
                "that holds a value states value"
            )
        if "transform" in mapping:
            raise ConfigError(
                f"{source}: {setting} is cleared, and a cleared setting takes "
                "no transform"
            )
        return KodiSetting(
            setting=setting, value=None, declared="unset", divergent=divergent
        )
    if stated == ["from_profile"]:
        # A Profile Constant is committed and printable, so it resolves to an
        # ordinary declared value and is reported like one. `from_env` stays
        # a separate arm because what it names may never be printed.
        name = _text(source, f"the from_profile of {setting}", mapping["from_profile"])
        if name not in constants:
            raise ConfigError(
                f"{source}: {setting} takes the Profile constant {name}, "
                "which the Profile does not declare"
            )
        declared = constants[name]
    else:
        declared = _text(source, "a Kodi setting value", mapping["value"])
    transform = (
        _text(source, "a Kodi setting transform", mapping["transform"])
        if "transform" in mapping
        else None
    )
    return KodiSetting(
        setting=setting,
        value=_transform(source, transform, declared),
        declared=declared,
        transform=transform,
        divergent=divergent,
    )


def _document(
    source: Path, named: NamedValues, constants: Mapping[str, str], raw: Any
) -> SettingsDocument:
    mapping = _fields(
        source,
        "a Settings Document",
        _mapping(source, "a Settings Document", raw),
        required=("dialect", "settings"),
        optional=("document", "document_glob", "compiles_to", "mode"),
    )
    # A document is named either literally or by a pattern, and the shape is
    # declared rather than sniffed: a `*` inside a `document` is a character
    # in a filename, never a wildcard, because a path that quietly became a
    # pattern would resolve to a file nobody declared.
    stated = [arm for arm in ("document", "document_glob") if arm in mapping]
    if len(stated) != 1:
        held = ", ".join(str(mapping[arm]) for arm in stated) or "neither"
        raise ConfigError(
            f"{source}: a Settings Document states exactly one of document "
            f"and document_glob, and this one states {held}"
        )
    is_glob = stated == ["document_glob"]
    document = _text(source, f"a Settings Document {stated[0]}", mapping[stated[0]])
    if not document.startswith("/"):
        raise ConfigError(
            f"{source}: a Settings Document path must be absolute: {document}"
        )
    dialect = _text(source, f"the dialect of {document}", mapping["dialect"])
    if dialect not in kodi_settings.DIALECTS:
        known = ", ".join(kodi_settings.DIALECTS)
        raise ConfigError(
            f"{source}: unknown dialect for {document}: {dialect} (known: {known})"
        )
    declared = mapping["settings"]
    if not isinstance(declared, list) or not declared:
        raise ConfigError(f"{source}: {document} declares no settings")
    compiles_to = None
    if "compiles_to" in mapping:
        compiles_to = _text(
            source, f"the compiles_to of {document}", mapping["compiles_to"]
        )
        if not compiles_to.startswith("/"):
            raise ConfigError(
                f"{source}: the artifact {document} compiles to must be "
                f"absolute: {compiles_to}"
            )
    return SettingsDocument(
        document=document,
        dialect=dialect,
        settings=tuple(
            _kodi_setting(source, named, constants, entry) for entry in declared
        ),
        is_glob=is_glob,
        compiles_to=compiles_to,
        mode=_text(
            source, f"the mode of {document}", mapping.get("mode", DOCUMENT_MODE)
        ),
    )


def _documents(
    source: Path,
    named: NamedValues,
    constants: Mapping[str, str],
    where: str,
    raw: Any,
) -> tuple[SettingsDocument, ...]:
    if not isinstance(raw, list):
        raise ConfigError(
            f"{source}: {where} must be a list of Settings Documents, and an "
            "empty list when there are none"
        )
    return tuple(_document(source, named, constants, entry) for entry in raw)


def _platform(source: Path, raw: Any) -> Platform:
    """What the Profile claims the Device is.

    Nothing here is derived from the Profile's directory name. That name is
    for humans — `ugoos-am6b-plus` against a Device whose own model string is
    `UGOOS AM6` — so reading an identity out of it would assert something no
    Device ever said about itself.
    """

    mapping = _fields(
        source,
        "platform",
        _mapping(source, "platform", raw),
        required=("id", "version", "device", "release_contains"),
    )
    return Platform(
        id=_text(source, "platform id", mapping["id"]),
        version=_text(source, "platform version", mapping["version"]),
        device=_text(source, "platform device", mapping["device"]),
        release_contains=_text(
            source, "platform release_contains", mapping["release_contains"]
        ),
    )


ADDRESS_KEYS = (
    "timezone_cache",
    "sshd_conf",
    "addons",
    "addon_database",
    "addon_manifest",
)


def _addresses(source: Path, raw: Any) -> Addresses:
    """The Device addresses the Reconciler knows the meaning of.

    Every one is required and every one is absolute. A Profile that could
    omit one would leave the Reconciler holding a path of its own, which is
    the thing this block exists to stop.
    """

    mapping = _fields(
        source,
        "addresses",
        _mapping(source, "addresses", raw),
        required=ADDRESS_KEYS,
    )
    held = {}
    for key in ADDRESS_KEYS:
        address = _text(source, f"the {key} address", mapping[key])
        if not address.startswith("/"):
            raise ConfigError(
                f"{source}: the {key} address must be absolute: {address}"
            )
        held[key] = address.rstrip("/") if key == "addons" else address
    return Addresses(**held)


def _patches(
    source: Path, addon_id: str, version: str, raw: Any
) -> tuple[artifact.Patch, ...]:
    """The Artifact Patches a record lists, read from `patches/<id>/`.

    The version each diff was written against is asserted here, before a Run
    has fetched anything: a bump that outruns its patches fails at once
    rather than after an 8 MB download (ADR 0017).
    """

    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{source}: the patches of {addon_id} must be a list")
    directory = source.parent / PATCHES / addon_id
    held: list[artifact.Patch] = []
    for entry in raw:
        name = _text(source, f"a patch of {addon_id}", entry)
        _relative(source, f"the patch {name} of {addon_id}", name)
        document = directory / name
        if not document.is_file():
            raise ConfigError(
                f"{source}: {addon_id} names a patch that is not there: {document}"
            )
        patch = artifact.Patch(name=name, diff=document.read_text(encoding="utf-8"))
        try:
            patched_id, patched_version = artifact.asserted(patch)
            artifact.touched(patch)
        except artifact.ArtifactError as error:
            raise ConfigError(f"{document}: {error}") from error
        if patched_id != addon_id:
            raise ConfigError(
                f"{document}: written against {patched_id} and listed under {addon_id}"
            )
        if patched_version != version:
            raise ConfigError(
                f"{document}: written against {addon_id} {patched_version} and "
                f"the Artifact Lock pins {version}: re-review the patch before "
                "moving the pin"
            )
        held.append(patch)
    return tuple(held)


def _patched_files(
    source: Path,
    addon_id: str,
    patches: tuple[artifact.Patch, ...],
    raw: Any,
) -> Mapping[str, str | None]:
    """The recorded post-patch hash of every file the diffs touch.

    The file list is the diffs' own, so the Lock states the same names and
    nothing declares them twice. A record naming a file no patch touches, or
    missing one a patch does, is rejected here: the Observation would
    silently stop covering it.
    """

    expected = sorted({path for patch in patches for path in artifact.touched(patch)})
    mapping = (
        {} if raw is None else _mapping(source, f"the patched files of {addon_id}", raw)
    )
    held: dict[str, str | None] = {}
    for path, value in mapping.items():
        name = _text(source, f"a patched file of {addon_id}", path)
        if value is None:
            held[name] = None
            continue
        digest = _text(source, f"the hash of {name} in {addon_id}", value)
        if not SHA256.fullmatch(digest):
            raise ConfigError(
                f"{source}: the hash of {name} in {addon_id} must be 64 "
                f"lowercase hex characters: {digest}"
            )
        held[name] = digest
    if sorted(held) != expected:
        raise ConfigError(
            f"{source}: the patched files of {addon_id} must be exactly the "
            f"files its patches touch: {', '.join(expected) or 'none'}"
        )
    return MappingProxyType(held)


def _addon(source: Path, raw: Any) -> AddonArtifact:
    """One record of the Artifact Lock, rejected here rather than mid-Run."""

    mapping = _fields(
        source,
        "an add-on",
        _mapping(source, "an add-on", raw),
        required=("id", "version", "url", "sha256", "role", "notes"),
        optional=("patches", "patched_files"),
    )
    addon_id = _text(source, "an add-on id", mapping["id"])
    if not ADDON_ID.fullmatch(addon_id):
        raise ConfigError(f"{source}: not a well-formed add-on id: {addon_id}")
    version = _text(source, f"the version of {addon_id}", mapping["version"])
    if not ADDON_VERSION.fullmatch(version):
        raise ConfigError(
            f"{source}: not a well-formed add-on version for {addon_id}: {version}"
        )
    url = _text(source, f"the url of {addon_id}", mapping["url"])
    # The Artifact travels over the open internet, so the pin states how it
    # is fetched as well as what it is.
    if not url.startswith("https://") or len(url) <= len("https://"):
        raise ConfigError(f"{source}: the url of {addon_id} must be https://: {url}")
    digest = _text(source, f"the sha256 of {addon_id}", mapping["sha256"])
    if not SHA256.fullmatch(digest):
        raise ConfigError(
            f"{source}: the sha256 of {addon_id} must be 64 lowercase hex "
            f"characters: {digest}"
        )
    notes = mapping["notes"]
    role = _text(source, f"the role of {addon_id}", mapping["role"])
    if role not in ADDON_ROLES:
        raise ConfigError(
            f"{source}: the role of {addon_id} must be one of "
            f"{', '.join(ADDON_ROLES)}: {role}"
        )
    patches = _patches(source, addon_id, version, mapping.get("patches"))
    return AddonArtifact(
        id=addon_id,
        version=version,
        url=url,
        sha256=digest,
        role=role,
        notes=(
            None if notes is None else _text(source, f"the notes of {addon_id}", notes)
        ),
        patches=patches,
        patched_files=_patched_files(
            source, addon_id, patches, mapping.get("patched_files")
        ),
    )


def _addons(source: Path) -> tuple[AddonArtifact, ...]:
    """The Artifact Lock, which every Profile has and which may be empty.

    It is a separate file from the Profile, and a required one: a Profile
    whose Lock had gone missing would plan nothing for every add-on in the
    fleet and report a converged Device.
    """

    if not source.is_file():
        raise ConfigError(f"no {ADDONS} beside the Profile: {source}")
    declared = _fields(
        source, "the Artifact Lock", _read(source), required=("addons",)
    )["addons"]
    if not isinstance(declared, list):
        raise ConfigError(
            f"{source}: addons must be a list of records, and an empty list "
            "when the Profile installs none"
        )
    records = tuple(_addon(source, entry) for entry in declared)
    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            raise ConfigError(f"{source}: {record.id} is pinned twice")
        seen.add(record.id)
    return records


def _constants(source: Path, raw: Any) -> dict[str, str]:
    """The facts the Profile states once and more than one address takes.

    A Profile with nothing to share states an empty mapping, the same as
    every other block that is required and may be empty.
    """

    mapping = _mapping(source, "constants", raw)
    return {
        _text(source, "a constant name", name): _text(
            source, f"the constant {name}", value
        )
        for name, value in mapping.items()
    }


def _public_key(where: str, text: str) -> tuple[str, str, str]:
    """One public key line, as its type, blob and comment.

    `where` is what carried the line — a file, or the `.env` key naming it.
    Nothing here puts the line into an error message: a public key is not a
    secret, but a named value is never printed, and one rule is easier to
    trust than an exception to it.
    """

    lines = [line.strip() for line in text.splitlines()]
    held = [line for line in lines if line]
    if len(held) != 1:
        raise ConfigError(
            f"{where} holds {len(held)} public key lines, and a public key is "
            "exactly one line"
        )
    matched = PUBLIC_KEY.fullmatch(held[0])
    if matched is None:
        raise ConfigError(f"{where} does not hold a well-formed OpenSSH public key")
    return matched.group(1), matched.group(2), matched.group(3) or ""


def _administrator_key(identity: Path) -> AuthorizedKey:
    """The entry for the identity the Run authenticates with.

    This is derived rather than declared, so the one key that must never be
    absent from the document cannot be got wrong by a Profile. The comment
    is the key file's own, which is what the shell installs, so a Device the
    shell last wrote and a Device this wrote hold the same line.
    """

    public = identity.with_name(f"{identity.name}.pub")
    try:
        text = public.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(
            f"the administrator public key {public} cannot be read: "
            f"{error.strerror or error}. It is the half of the transport "
            "identity that goes on the Device, and every Run declares it"
        ) from error
    key_type, blob, comment = _public_key(str(public), text)
    return AuthorizedKey(comment=comment, key_type=key_type, blob=blob)


def _authorized_key(source: Path, named: NamedValues, raw: Any) -> AuthorizedKey:
    mapping = _fields(
        source,
        "an authorized key",
        _mapping(source, "an authorized key", raw),
        required=("comment", "from_env", "forced_command"),
    )
    comment = _text(source, "an authorized key comment", mapping["comment"])
    # The comment is how an entry is found and read, by a human and by the
    # shell's own installer, which replaces the line carrying this marker.
    # A comment holding whitespace would split into two words, and the second
    # would not be part of the comment at all.
    if not comment or comment.split() != [comment]:
        raise ConfigError(
            f"{source}: an authorized key comment is one word carrying no "
            f"whitespace: {comment!r}"
        )
    command = _text(
        source, f"the forced_command of {comment}", mapping["forced_command"]
    )
    if not command.startswith("/"):
        raise ConfigError(
            f"{source}: the forced_command of {comment} must be absolute: {command}"
        )
    # A forced command is written inside a double-quoted `command="..."`
    # option, and OpenSSH reads a backslash there as an escape. A path
    # holding either character would not be the path the entry names.
    if '"' in command or "\\" in command:
        raise ConfigError(
            f"{source}: the forced_command of {comment} must hold neither a "
            f"double quote nor a backslash: {command}"
        )
    key = _text(source, f"the from_env of {comment}", mapping["from_env"])
    key_type, blob, _ = _public_key(
        f"{source}, which names {key}", named.value(source, key)
    )
    return AuthorizedKey(
        comment=comment,
        key_type=key_type,
        blob=blob,
        forced_command=command,
        named_by=key,
    )


def _authorized_keys(
    source: Path, named: NamedValues, identity: Path, raw: Any
) -> AuthorizedKeys:
    """Who may log in, with the administrator entry first and always.

    Every entry beside it carries a forced command. A second unrestricted
    key is not something the fleet has ever wanted, and the arm to declare
    one would be the arm that quietly grants a Device to anybody a Profile
    names.
    """

    mapping = _fields(
        source,
        "authorized_keys",
        _mapping(source, "authorized_keys", raw),
        required=("document", "entries"),
    )
    document = _text(source, "the authorized_keys document", mapping["document"])
    if not document.startswith("/"):
        raise ConfigError(
            f"{source}: the authorized_keys document must be absolute: {document}"
        )
    declared = mapping["entries"]
    if not isinstance(declared, list):
        raise ConfigError(
            f"{source}: authorized_keys entries must be a list, and an empty "
            "list when the administrator is the only key that may log in"
        )
    entries = (
        _administrator_key(identity),
        *(_authorized_key(source, named, entry) for entry in declared),
    )
    seen: dict[str, str] = {}
    for entry in entries:
        if entry.blob in seen:
            raise ConfigError(
                f"{source}: {document} declares one key twice, as "
                f"{seen[entry.blob] or 'the administrator'} and as {entry.comment}"
            )
        seen[entry.blob] = entry.comment
    comments = [entry.comment for entry in entries if entry.comment]
    if len(set(comments)) != len(comments):
        raise ConfigError(f"{source}: {document} declares one comment twice")
    return AuthorizedKeys(document=document, entries=entries)


def _merge(
    sides: tuple[tuple[Path, tuple[SettingsDocument, ...]], ...],
) -> tuple[SettingsDocument, ...]:
    """Every side's Settings Documents, merged by document path.

    A document declared on more than one side contributes the settings of
    each, in the order the sides are given, so a Room Overlay may add a State
    Address to a document the Profile names. The two sides must agree on the
    document's dialect, because they describe one file.

    The language says a Room Overlay wins on collision, but nothing needs that
    yet, so a `(document, setting)` collision is an error naming both instead.
    Merging per document keeps each side's contribution separable, so the
    winning rule can be added here later without reshaping anything.
    """

    merged: dict[str, SettingsDocument] = {}
    origins: dict[tuple[str, str], Path] = {}
    for source, documents in sides:
        for document in documents:
            path = document.document
            existing = merged.get(path)
            if existing is not None and existing.dialect != document.dialect:
                raise ConfigError(
                    f"{source}: {path} is declared as {document.dialect} here "
                    f"and as {existing.dialect} elsewhere"
                )
            for setting in document.settings:
                key = (path, setting.setting.casefold())
                origin = origins.get(key)
                if origin == source:
                    raise ConfigError(
                        f"{source}: {path} declares {setting.setting} twice"
                    )
                if origin is not None:
                    raise ConfigError(
                        f"{source}: {setting.setting} in {path} is declared by "
                        f"both {origin} and {source}"
                    )
                origins[key] = source
            merged[path] = (
                document
                if existing is None
                else replace(existing, settings=existing.settings + document.settings)
            )
    return tuple(merged.values())


def _resolved(config_root: Path, room: str) -> tuple[Path, Mapping[str, Any], Path]:
    """The Room Overlay for `room`, and the Profile document it names."""

    room_path = config_root / "rooms" / _relative(config_root, "a room", room)
    room_file = room_path / "room.yaml"
    if not room_file.is_file():
        raise ConfigError(f"no room.yaml for room {room}: {room_file}")
    overlay = _fields(
        room_file,
        "the Room Overlay",
        _read(room_file),
        required=("room", "hostname", "profile", "settings_documents"),
    )
    declared_profile = _relative(
        room_file, "profile", _text(room_file, "profile", overlay["profile"])
    )
    profile_file = config_root / "shared" / declared_profile / "profile.yaml"
    if not profile_file.is_file():
        raise ConfigError(f"no profile.yaml for {declared_profile}: {profile_file}")
    return room_file, overlay, profile_file


def lock(config_root: Path, room: str) -> tuple[Path, tuple[AddonArtifact, ...]]:
    """The Artifact Lock a room resolves to, and the records it holds.

    `record-patches` runs the artifact pipeline and touches nothing else, so
    it resolves only as far as the Lock. Demanding a transport identity of a
    command that never contacts a Device would make it unrunnable anywhere
    the Device is not, which includes CI (ADR 0011).
    """

    _, _, profile_file = _resolved(config_root, room)
    document = profile_file.with_name(ADDONS)
    return document, _addons(document)


def load(config_root: Path, room: str, env_path: Path) -> DesiredState:
    """Resolves the Room Overlay for `room` against the Profile it names.

    `env_path` is the shared `.env`. It is read only if the resolved
    configuration names a value in it, and always before any Device contact.
    """

    named = NamedValues(env_path)
    room_file, overlay, profile_file = _resolved(config_root, room)
    hostname = _text(room_file, "hostname", overlay["hostname"])
    declared_profile = _relative(
        room_file, "profile", _text(room_file, "profile", overlay["profile"])
    )
    profile = _fields(
        profile_file,
        "the Profile",
        _read(profile_file),
        required=(
            "profile",
            "platform",
            "constants",
            "addresses",
            "transport",
            "authorized_keys",
            "smart_playlists",
            "settings_documents",
            "shortcut_nodes",
        ),
    )
    if _text(profile_file, "profile", profile["profile"]) != declared_profile:
        raise ConfigError(
            f"{profile_file}: declares a different profile than {declared_profile}"
        )

    platform = _platform(profile_file, profile["platform"])
    constants = _constants(profile_file, profile["constants"])
    addresses = _addresses(profile_file, profile["addresses"])
    document = profile_file.with_name(ADDONS)
    addons = _addons(document)
    room_documents = _documents(
        room_file, named, constants, "settings_documents", overlay["settings_documents"]
    )

    transport = _fields(
        profile_file,
        "transport",
        _mapping(profile_file, "transport", profile["transport"]),
        required=("user", "port", "identity"),
    )
    identity = Path(
        _text(profile_file, "transport identity", transport["identity"])
    ).expanduser()
    # Read before any Device contact, like every other declaration: the
    # administrator entry is derived from this identity, so a missing public
    # half is an error before a Run has written anything.
    authorized = _authorized_keys(
        profile_file, named, identity, profile["authorized_keys"]
    )

    playlists = _fields(
        profile_file,
        "smart_playlists",
        _mapping(profile_file, "smart_playlists", profile["smart_playlists"]),
        required=("directory", "kodi_directory", "playlists"),
    )
    directory = _text(profile_file, "playlist directory", playlists["directory"])
    if not directory.startswith("/"):
        raise ConfigError(
            f"{profile_file}: the playlist directory must be absolute: {directory}"
        )
    kodi_directory = _text(
        profile_file, "playlist kodi_directory", playlists["kodi_directory"]
    )
    declared = playlists["playlists"]
    if not isinstance(declared, list) or not declared:
        raise ConfigError(f"{profile_file}: smart_playlists declares no playlists")
    parsed = tuple(
        _playlist(profile_file, directory, kodi_directory, raw) for raw in declared
    )
    by_file = {Path(playlist.path).name: playlist for playlist in parsed}

    kodi = _documents(
        profile_file,
        named,
        constants,
        "settings_documents",
        profile["settings_documents"],
    )
    if not kodi:
        raise ConfigError(f"{profile_file}: settings_documents declares no documents")

    nodes = profile["shortcut_nodes"]
    if not isinstance(nodes, list):
        raise ConfigError(
            f"{profile_file}: shortcut_nodes must be a list of Shortcut Nodes, "
            "and an empty list when there are none"
        )

    return DesiredState(
        room=_text(room_file, "room", overlay["room"]),
        hostname=hostname,
        profile=declared_profile,
        platform=platform,
        transport=Transport(
            user=_text(profile_file, "transport user", transport["user"]),
            port=_integer(profile_file, "transport port", transport["port"]),
            identity=identity,
        ),
        addresses=addresses,
        authorized_keys=authorized,
        playlists=parsed,
        documents=_merge(((profile_file, kodi), (room_file, room_documents))),
        addons=addons,
        shortcut_nodes=tuple(
            _shortcut_node(profile_file, by_file, entry) for entry in nodes
        ),
    )
