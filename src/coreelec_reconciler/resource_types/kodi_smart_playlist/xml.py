"""Strict semantic Kodi Smart Playlist XML parsing and rendering."""

import re
import xml.etree.ElementTree as ET

from coreelec_reconciler.domain.planning import PlaylistSemanticModel

_DECLARATION = re.compile(rb"^\s*<\?xml\s+([^?]+)\?>", re.IGNORECASE)
_ENCODING = re.compile(rb"encoding\s*=\s*(['\"])([^'\"]+)\1", re.IGNORECASE)
_MEDIA_TYPES = {"movies", "tvshows"}
_MATCH_MODES = {"all", "one"}
_RULE_FIELDS = {"playcount"}
_RULE_OPERATORS = {"is"}
_ORDER_FIELDS = {"dateadded"}
_ORDER_DIRECTIONS = {"ascending", "descending"}


class PlaylistXmlError(ValueError):
    """Raised when bytes are not an accepted Kodi Smart Playlist document."""


def _validate_encoding(content: bytes) -> None:
    declaration = _DECLARATION.match(content)
    if declaration is None:
        return
    encoding = _ENCODING.search(declaration.group(1))
    if encoding is not None and encoding.group(2).lower() not in {b"utf-8", b"utf8"}:
        raise PlaylistXmlError("playlist XML encoding is unsupported")


def _text(element: ET.Element, label: str) -> str:
    value = element.text
    if value is None or not value.strip():
        raise PlaylistXmlError(f"playlist {label} is empty")
    return value.strip()


def _closed_text(
    value: str,
    accepted: set[str],
    label: str,
) -> str:
    if value not in accepted:
        raise PlaylistXmlError(f"playlist {label} is unsupported")
    return value


def validate_playlist_model(
    model: PlaylistSemanticModel,
) -> PlaylistSemanticModel:
    _closed_text(model.media_type, _MEDIA_TYPES, "media type")
    if not model.display_name or len(model.display_name) > 256:
        raise PlaylistXmlError("playlist name is invalid")
    if any(ord(character) < 32 for character in model.display_name):
        raise PlaylistXmlError("playlist name is invalid")
    _closed_text(model.match, _MATCH_MODES, "match")
    if type(model.limit) is not int or not 1 <= model.limit <= 10000:
        raise PlaylistXmlError("playlist limit is invalid")
    if len(model.rules) != 1:
        raise PlaylistXmlError("playlist must contain exactly one rule")
    field, operator, value = model.rules[0]
    _closed_text(field, _RULE_FIELDS, "rule field")
    _closed_text(operator, _RULE_OPERATORS, "rule operator")
    if type(value) is not int or value < 0:
        raise PlaylistXmlError("playlist rule value is invalid")
    if len(model.order) != 2:
        raise PlaylistXmlError("playlist order must contain field and direction")
    _closed_text(model.order[0], _ORDER_FIELDS, "order field")
    _closed_text(model.order[1], _ORDER_DIRECTIONS, "order direction")
    return model


def parse_playlist_xml(content: bytes) -> PlaylistSemanticModel:
    _validate_encoding(content)
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise PlaylistXmlError("playlist XML declarations are unsupported")
    try:
        root = ET.fromstring(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ET.ParseError) as error:
        raise PlaylistXmlError("playlist XML is malformed") from error
    if root.tag != "smartplaylist" or set(root.attrib) != {"type"}:
        raise PlaylistXmlError("playlist root is unsupported")
    allowed = {"name", "match", "rule", "limit", "order"}
    if any(child.tag not in allowed for child in root):
        raise PlaylistXmlError("playlist child is unsupported")
    singletons: dict[str, ET.Element] = {}
    rules: list[tuple[str, str, int | str]] = []
    for child in root:
        if child.tag == "rule":
            if set(child.attrib) != {"field", "operator"} or len(child) != 0:
                raise PlaylistXmlError("playlist rule is malformed")
            raw_value = _text(child, "rule")
            value: int | str = int(raw_value) if raw_value.isdecimal() else raw_value
            rules.append((child.attrib["field"], child.attrib["operator"], value))
            continue
        if child.tag in singletons:
            raise PlaylistXmlError(f"playlist {child.tag} is duplicated")
        singletons[child.tag] = child
    if set(singletons) != {"name", "match", "limit", "order"}:
        raise PlaylistXmlError("playlist singleton fields are incomplete")
    for name in ("name", "match", "limit"):
        if singletons[name].attrib or len(singletons[name]) != 0:
            raise PlaylistXmlError(f"playlist {name} is malformed")
    order = singletons["order"]
    if set(order.attrib) != {"direction"} or len(order) != 0:
        raise PlaylistXmlError("playlist order is malformed")
    limit_text = _text(singletons["limit"], "limit")
    if not limit_text.isdecimal() or int(limit_text) < 1:
        raise PlaylistXmlError("playlist limit is malformed")
    if not rules:
        raise PlaylistXmlError("playlist rules are empty")
    return validate_playlist_model(
        PlaylistSemanticModel(
            media_type=root.attrib["type"],
            display_name=_text(singletons["name"], "name"),
            match=_text(singletons["match"], "match"),
            limit=int(limit_text),
            rules=tuple(rules),
            order=(_text(order, "order"), order.attrib["direction"]),
        )
    )


def render_playlist_xml(model: PlaylistSemanticModel) -> bytes:
    model = validate_playlist_model(model)
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>',
        f'<smartplaylist type="{_escape(model.media_type)}">',
        f"    <name>{_escape(model.display_name)}</name>",
        f"    <match>{_escape(model.match)}</match>",
    ]
    lines.extend(
        f'    <rule field="{_escape(field)}" operator="{_escape(operator)}">'
        f"{_escape(str(value))}</rule>"
        for field, operator, value in model.rules
    )
    lines.extend(
        (
            f"    <limit>{model.limit}</limit>",
            f'    <order direction="{_escape(model.order[1])}">'
            f"{_escape(model.order[0])}</order>",
            "</smartplaylist>",
        )
    )
    return ("\n".join(lines) + "\n").encode()


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
