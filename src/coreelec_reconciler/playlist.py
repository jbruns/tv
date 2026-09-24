"""Rendering a Smart Playlist as the .xsp document Kodi reads."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

from .config import SmartPlaylist


def render(playlist: SmartPlaylist) -> str:
    root = ElementTree.Element("smartplaylist", {"type": playlist.media_type})
    ElementTree.SubElement(root, "name").text = playlist.name
    ElementTree.SubElement(root, "match").text = playlist.match
    for rule in playlist.rules:
        node = ElementTree.SubElement(
            root, "rule", {"field": rule.field, "operator": rule.operator}
        )
        if rule.value:
            ElementTree.SubElement(node, "value").text = rule.value
    ElementTree.SubElement(root, "limit").text = str(playlist.limit)
    order = ElementTree.SubElement(
        root, "order", {"direction": playlist.order_direction}
    )
    order.text = playlist.order_field

    tree = ElementTree.ElementTree(root)
    ElementTree.indent(tree, space="    ")
    raw: bytes = ElementTree.tostring(root, encoding="UTF-8", xml_declaration=True)
    body = raw.decode("utf-8")
    return body if body.endswith("\n") else body + "\n"
