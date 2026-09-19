"""Pure conversion of validated authored playlist Intent."""

from collections.abc import Mapping

from coreelec_reconciler.domain.configuration import (
    DesiredPresence,
    KodiSmartPlaylistIntent,
    PlaylistDefinition,
    PlaylistOrder,
    PlaylistRule,
)
from coreelec_reconciler.resource_types.descriptor import IntentValidationError


def _mapping(value: object, path: tuple[str | int, ...]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise IntentValidationError(path, "Expected a mapping.")
    return value


def _string(value: object, path: tuple[str | int, ...]) -> str:
    if not isinstance(value, str):
        raise IntentValidationError(path, "Expected a string.")
    return value


def _rule_value(value: object, path: tuple[str | int, ...]) -> int | str:
    if type(value) is int or isinstance(value, str):
        return value
    raise IntentValidationError(path, "Expected an integer or string.")


def parse_intent(
    value: Mapping[str, object],
    desired: DesiredPresence,
) -> KodiSmartPlaylistIntent:
    expected_root = (
        {"playlist", "file"} if desired is DesiredPresence.PRESENT else {"playlist"}
    )
    if set(value) != expected_root:
        raise IntentValidationError(
            ("intent",),
            "Playlist Intent has missing or inapplicable fields.",
        )
    playlist = _mapping(value["playlist"], ("intent", "playlist"))
    if desired is DesiredPresence.ABSENT:
        if set(playlist) != {"id", "media_type"}:
            raise IntentValidationError(
                ("intent", "playlist"),
                "Absent playlist Intent accepts identity fields only.",
            )
        return KodiSmartPlaylistIntent(
            playlist=PlaylistDefinition(
                id=_string(playlist["id"], ("intent", "playlist", "id")),
                media_type=_string(
                    playlist["media_type"],
                    ("intent", "playlist", "media_type"),
                ),
                display_name=None,
                match=None,
                limit=None,
                rules=(),
                order=None,
            ),
            file_mode=None,
        )
    required = {
        "id",
        "media_type",
        "display_name",
        "match",
        "limit",
        "rules",
        "order",
    }
    if set(playlist) != required:
        raise IntentValidationError(
            ("intent", "playlist"),
            "Present playlist Intent is incomplete.",
        )
    rules_value = playlist["rules"]
    if not isinstance(rules_value, list):
        raise IntentValidationError(("intent", "playlist", "rules"), "Expected a list.")
    rules = tuple(
        PlaylistRule(
            field=_string(
                _mapping(rule, ("intent", "playlist", "rules", index))["field"],
                ("intent", "playlist", "rules", index, "field"),
            ),
            operator=_string(
                _mapping(rule, ("intent", "playlist", "rules", index))["operator"],
                ("intent", "playlist", "rules", index, "operator"),
            ),
            value=_rule_value(
                _mapping(rule, ("intent", "playlist", "rules", index))["value"],
                ("intent", "playlist", "rules", index, "value"),
            ),
        )
        for index, rule in enumerate(rules_value)
    )
    order = _mapping(playlist["order"], ("intent", "playlist", "order"))
    if set(order) != {"by", "direction"}:
        raise IntentValidationError(
            ("intent", "playlist", "order"),
            "Playlist order is incomplete.",
        )
    limit = playlist["limit"]
    if type(limit) is not int:
        raise IntentValidationError(
            ("intent", "playlist", "limit"),
            "Expected an integer.",
        )
    file_value = _mapping(value["file"], ("intent", "file"))
    if set(file_value) != {"mode"}:
        raise IntentValidationError(
            ("intent", "file"),
            "Playlist file Intent is incomplete.",
        )
    return KodiSmartPlaylistIntent(
        playlist=PlaylistDefinition(
            id=_string(playlist["id"], ("intent", "playlist", "id")),
            media_type=_string(
                playlist["media_type"], ("intent", "playlist", "media_type")
            ),
            display_name=_string(
                playlist["display_name"],
                ("intent", "playlist", "display_name"),
            ),
            match=_string(playlist["match"], ("intent", "playlist", "match")),
            limit=limit,
            rules=rules,
            order=PlaylistOrder(
                by=_string(order["by"], ("intent", "playlist", "order", "by")),
                direction=_string(
                    order["direction"],
                    ("intent", "playlist", "order", "direction"),
                ),
            ),
        ),
        file_mode=_string(file_value["mode"], ("intent", "file", "mode")),
    )
