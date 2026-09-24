"""Rendering a Shortcut Node as the JSON document `script.skinvariables` reads.

The item shape is upstream's default item: `label`, `icon`, `path`, `target`,
`submenu` and `widgets`, plus the `guid` the add-on preserves when it finds one
and invents when it does not.

`submenu` and `widgets` are written only when they hold something. The add-on
creates either key lazily, so an absent key and an empty list are the same
thing to it.
"""

from __future__ import annotations

from typing import Any

from .config import Shortcut, ShortcutNode
from .kodi_settings import render_json


def _item(shortcut: Shortcut) -> dict[str, Any]:
    item: dict[str, Any] = {
        "guid": shortcut.guid,
        "icon": shortcut.icon,
        "label": shortcut.label,
        "path": shortcut.path,
        "target": shortcut.target,
    }
    if shortcut.submenu:
        item["submenu"] = [_item(entry) for entry in shortcut.submenu]
    if shortcut.widgets:
        item["widgets"] = [_item(entry) for entry in shortcut.widgets]
    return item


def render(node: ShortcutNode) -> str:
    """The node document, in the add-on's own JSON shape."""

    return render_json([_item(shortcut) for shortcut in node.shortcuts])
