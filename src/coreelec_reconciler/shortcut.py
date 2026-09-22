"""Rendering a Shortcut Node as the JSON document `script.skinvariables` reads.

The item shape is upstream's default item: `label`, `icon`, `path`, `target`,
`submenu` and `widgets`, plus the `guid` the add-on preserves when it finds one
and invents when it does not. The bytes match what the shell provisioner
writes, so a Device restored from the Recovery Baseline converges with no
Change.

`submenu` and `widgets` are written only when they hold something. The add-on
creates either key lazily, so an absent key and an empty list are the same
thing to it, and the Recovery Baseline writes neither.
"""

from __future__ import annotations

import json
from typing import Any

from .config import Shortcut, ShortcutNode


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
    """Sorted, four-space JSON: the add-on's convention and the shell's."""

    body = [_item(shortcut) for shortcut in node.shortcuts]
    return json.dumps(body, ensure_ascii=False, indent=4, sort_keys=True) + "\n"
