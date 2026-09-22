"""Reading the Profile and the Room Overlay into Desired State.

Both files use a strict schema: an unknown or missing key is rejected naming
the key, so a typo can never be read as a silent default.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from . import env_file, kodi_settings


class ConfigError(Exception):
    """A Profile or Room Overlay that cannot be read as Desired State."""


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
class Transport:
    user: str
    port: int
    identity: Path


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
    """

    setting: str
    value: str | None
    declared: str
    transform: str | None = None
    named_by: str | None = None


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
    """

    document: str
    dialect: str
    settings: tuple[KodiSetting, ...]
    is_glob: bool = False
    compiles_to: str | None = None


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
class DesiredState:
    room: str
    hostname: str
    profile: str
    transport: Transport
    playlists: tuple[SmartPlaylist, ...]
    documents: tuple[SettingsDocument, ...]
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
    seen: set[str] = set()
    for shortcut in shortcuts:
        if shortcut.guid in seen:
            raise ConfigError(
                f"{source}: {document} declares the shortcut {shortcut.guid} twice"
            )
        seen.add(shortcut.guid)
    return ShortcutNode(document=document, shortcuts=shortcuts)


def _kodi_setting(source: Path, named: NamedValues, raw: Any) -> KodiSetting:
    mapping = _fields(
        source,
        "a Kodi setting",
        _mapping(source, "a Kodi setting", raw),
        required=("setting",),
        optional=("value", "from_env", "unset", "transform"),
    )
    setting = _text(source, "a Kodi setting id", mapping["setting"])
    # The three arms are mutually exclusive and one is mandatory. A setting
    # stating none of them is the shape a truncated line produces, and one
    # stating two says two different things about the same address.
    stated = [arm for arm in ("value", "from_env", "unset") if arm in mapping]
    if len(stated) != 1:
        raise ConfigError(
            f"{source}: {setting} states exactly one of value, from_env and unset"
        )
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
        return KodiSetting(setting=setting, value=None, declared="unset")
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
    )


def _document(source: Path, named: NamedValues, raw: Any) -> SettingsDocument:
    mapping = _fields(
        source,
        "a Settings Document",
        _mapping(source, "a Settings Document", raw),
        required=("dialect", "settings"),
        optional=("document", "document_glob", "compiles_to"),
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
        settings=tuple(_kodi_setting(source, named, entry) for entry in declared),
        is_glob=is_glob,
        compiles_to=compiles_to,
    )


def _documents(
    source: Path, named: NamedValues, where: str, raw: Any
) -> tuple[SettingsDocument, ...]:
    if not isinstance(raw, list):
        raise ConfigError(
            f"{source}: {where} must be a list of Settings Documents, and an "
            "empty list when there are none"
        )
    return tuple(_document(source, named, entry) for entry in raw)


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


def load(config_root: Path, room: str, env_path: Path) -> DesiredState:
    """Resolves the Room Overlay for `room` against the Profile it names.

    `env_path` is the shared `.env`. It is read only if the resolved
    configuration names a value in it, and always before any Device contact.
    """

    named = NamedValues(env_path)
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
    hostname = _text(room_file, "hostname", overlay["hostname"])
    declared_profile = _relative(
        room_file, "profile", _text(room_file, "profile", overlay["profile"])
    )
    room_documents = _documents(
        room_file, named, "settings_documents", overlay["settings_documents"]
    )

    profile_file = config_root / "shared" / declared_profile / "profile.yaml"
    if not profile_file.is_file():
        raise ConfigError(f"no profile.yaml for {declared_profile}: {profile_file}")
    profile = _fields(
        profile_file,
        "the Profile",
        _read(profile_file),
        required=(
            "profile",
            "transport",
            "smart_playlists",
            "settings_documents",
            "shortcut_nodes",
        ),
    )
    if _text(profile_file, "profile", profile["profile"]) != declared_profile:
        raise ConfigError(
            f"{profile_file}: declares a different profile than {declared_profile}"
        )

    transport = _fields(
        profile_file,
        "transport",
        _mapping(profile_file, "transport", profile["transport"]),
        required=("user", "port", "identity"),
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
    rendered = tuple(
        _playlist(profile_file, directory, kodi_directory, raw) for raw in declared
    )
    by_file = {Path(playlist.path).name: playlist for playlist in rendered}

    kodi = _documents(
        profile_file, named, "settings_documents", profile["settings_documents"]
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
        transport=Transport(
            user=_text(profile_file, "transport user", transport["user"]),
            port=_integer(profile_file, "transport port", transport["port"]),
            identity=Path(
                _text(profile_file, "transport identity", transport["identity"])
            ).expanduser(),
        ),
        playlists=rendered,
        documents=_merge(((profile_file, kodi), (room_file, room_documents))),
        shortcut_nodes=tuple(
            _shortcut_node(profile_file, by_file, entry) for entry in nodes
        ),
    )
