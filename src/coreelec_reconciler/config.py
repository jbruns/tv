"""Reading the Profile and the Room Overlay into Desired State.

Both files use a strict schema: an unknown or missing key is rejected naming
the key, so a typo can never be read as a silent default.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """A Profile or Room Overlay that cannot be read as Desired State."""


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
    """One Kodi Smart Playlist. Its State Address is its path on the Device."""

    path: str
    name: str
    media_type: str
    match: str
    limit: int
    order_field: str
    order_direction: str
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class KodiSetting:
    """One Kodi setting. Its State Address is the ID inside the document."""

    setting: str
    value: str


@dataclass(frozen=True)
class KodiSettings:
    """A shared settings document and the State Addresses owned inside it."""

    document: str
    settings: tuple[KodiSetting, ...]


@dataclass(frozen=True)
class DesiredState:
    room: str
    hostname: str
    profile: str
    transport: Transport
    playlists: tuple[SmartPlaylist, ...]
    kodi_settings: KodiSettings


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
    source: Path, where: str, mapping: dict[str, Any], *, required: tuple[str, ...]
) -> dict[str, Any]:
    unknown = sorted(set(mapping) - set(required))
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


def _rule(source: Path, raw: Any) -> Rule:
    mapping = _fields(
        source,
        "a rule",
        _mapping(source, "a rule", raw),
        required=("field", "operator", "value"),
    )
    return Rule(
        field=_text(source, "rule field", mapping["field"]),
        operator=_text(source, "rule operator", mapping["operator"]),
        value=_text(source, "rule value", mapping["value"]),
    )


def _playlist(source: Path, directory: str, raw: Any) -> SmartPlaylist:
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
        name=_text(source, "playlist name", mapping["name"]),
        media_type=_text(source, "playlist type", mapping["type"]),
        match=_text(source, "playlist match", mapping["match"]),
        limit=_integer(source, "playlist limit", mapping["limit"]),
        order_field=_text(source, "order field", order["field"]),
        order_direction=_text(source, "order direction", order["direction"]),
        rules=tuple(_rule(source, rule) for rule in rules),
    )


def _kodi_setting(source: Path, raw: Any) -> KodiSetting:
    mapping = _fields(
        source,
        "a Kodi setting",
        _mapping(source, "a Kodi setting", raw),
        required=("setting", "value"),
    )
    return KodiSetting(
        setting=_text(source, "a Kodi setting id", mapping["setting"]),
        value=_text(source, "a Kodi setting value", mapping["value"]),
    )


def load(config_root: Path, room: str) -> DesiredState:
    """Resolves the Room Overlay for `room` against the Profile it names."""

    room_path = config_root / "rooms" / _relative(config_root, "a room", room)
    room_file = room_path / "room.yaml"
    if not room_file.is_file():
        raise ConfigError(f"no room.yaml for room {room}: {room_file}")
    overlay = _fields(
        room_file,
        "the Room Overlay",
        _read(room_file),
        required=("room", "hostname", "profile"),
    )
    hostname = _text(room_file, "hostname", overlay["hostname"])
    declared_profile = _relative(
        room_file, "profile", _text(room_file, "profile", overlay["profile"])
    )

    profile_file = config_root / "shared" / declared_profile / "profile.yaml"
    if not profile_file.is_file():
        raise ConfigError(f"no profile.yaml for {declared_profile}: {profile_file}")
    profile = _fields(
        profile_file,
        "the Profile",
        _read(profile_file),
        required=("profile", "transport", "smart_playlists", "kodi_settings"),
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
        required=("directory", "playlists"),
    )
    directory = _text(profile_file, "playlist directory", playlists["directory"])
    if not directory.startswith("/"):
        raise ConfigError(
            f"{profile_file}: the playlist directory must be absolute: {directory}"
        )
    declared = playlists["playlists"]
    if not isinstance(declared, list) or not declared:
        raise ConfigError(f"{profile_file}: smart_playlists declares no playlists")

    kodi = _fields(
        profile_file,
        "kodi_settings",
        _mapping(profile_file, "kodi_settings", profile["kodi_settings"]),
        required=("document", "settings"),
    )
    document = _text(profile_file, "the Kodi settings document", kodi["document"])
    if not document.startswith("/"):
        raise ConfigError(
            f"{profile_file}: the Kodi settings document must be absolute: {document}"
        )
    declared_settings = kodi["settings"]
    if not isinstance(declared_settings, list) or not declared_settings:
        raise ConfigError(f"{profile_file}: kodi_settings declares no settings")

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
        playlists=tuple(_playlist(profile_file, directory, raw) for raw in declared),
        kodi_settings=KodiSettings(
            document=document,
            settings=tuple(
                _kodi_setting(profile_file, raw) for raw in declared_settings
            ),
        ),
    )
