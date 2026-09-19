"""Strict persisted codec for Kodi Smart Playlist Intent."""

from collections.abc import Mapping

from coreelec_reconciler.domain.configuration import (
    KodiSmartPlaylistIntent,
    PlaylistDefinition,
    PlaylistOrder,
    PlaylistRule,
)


def encode_intent(intent: KodiSmartPlaylistIntent) -> Mapping[str, object]:
    playlist = intent.playlist
    return {
        "file_mode": intent.file_mode,
        "playlist": {
            "display_name": playlist.display_name,
            "id": playlist.id,
            "limit": playlist.limit,
            "match": playlist.match,
            "media_type": playlist.media_type,
            "order": (
                None
                if playlist.order is None
                else {
                    "by": playlist.order.by,
                    "direction": playlist.order.direction,
                }
            ),
            "rules": [
                {
                    "field": rule.field,
                    "operator": rule.operator,
                    "value": rule.value,
                }
                for rule in playlist.rules
            ],
        },
    }


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError("playlist codec value must be an object")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("playlist codec value must be a string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise ValueError("playlist codec value must be an integer")
    return value


def _rule_value(value: object) -> int | str:
    if type(value) is int or isinstance(value, str):
        return value
    raise ValueError("playlist rule value must be an integer or string")


def decode_intent(value: Mapping[str, object]) -> KodiSmartPlaylistIntent:
    if set(value) != {"file_mode", "playlist"}:
        raise ValueError("unknown or missing playlist Intent fields")
    playlist = _mapping(value["playlist"])
    if set(playlist) != {
        "display_name",
        "id",
        "limit",
        "match",
        "media_type",
        "order",
        "rules",
    }:
        raise ValueError("unknown or missing playlist fields")
    order_value = playlist["order"]
    order = None
    if order_value is not None:
        order_mapping = _mapping(order_value)
        if set(order_mapping) != {"by", "direction"}:
            raise ValueError("unknown or missing playlist order fields")
        order = PlaylistOrder(
            by=_string(order_mapping["by"]),
            direction=_string(order_mapping["direction"]),
        )
    rules_value = playlist["rules"]
    if not isinstance(rules_value, list):
        raise ValueError("playlist rules must be an array")
    rules: list[PlaylistRule] = []
    for value_item in rules_value:
        rule = _mapping(value_item)
        if set(rule) != {"field", "operator", "value"}:
            raise ValueError("unknown or missing playlist rule fields")
        rules.append(
            PlaylistRule(
                field=_string(rule["field"]),
                operator=_string(rule["operator"]),
                value=_rule_value(rule["value"]),
            )
        )
    return KodiSmartPlaylistIntent(
        playlist=PlaylistDefinition(
            id=_string(playlist["id"]),
            media_type=_string(playlist["media_type"]),
            display_name=_optional_string(playlist["display_name"]),
            match=_optional_string(playlist["match"]),
            limit=_optional_int(playlist["limit"]),
            rules=tuple(rules),
            order=order,
        ),
        file_mode=_optional_string(value["file_mode"]),
    )
