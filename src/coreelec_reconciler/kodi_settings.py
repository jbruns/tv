"""Reading and writing Kodi settings inside a shared settings document.

`guisettings.xml` is not a document the Reconciler renders. It holds hundreds
of settings, almost all of them Unmanaged State, so this module changes only
the State Addresses it is given and leaves every other setting's identity and
value exactly as it found them.

Kodi resolves a setting ID without regard to case and reads only the direct
`<setting>` children of the root, while a recursive reader sees nested copies
too. The canonical node is therefore the one Kodi reads: every other match at
any depth is removed, matching the Recovery Baseline's behaviour.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping


class SettingsError(Exception):
    """A settings document that cannot be read as XML."""


def _root(document: str | None) -> ElementTree.Element:
    if document is None or not document.strip():
        return ElementTree.Element("settings", {"version": "2"})
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise SettingsError(str(error)) from error
    if root.tag != "settings":
        raise SettingsError(f"unexpected root element: {root.tag}")
    return root


def _matches(
    root: ElementTree.Element, setting: str
) -> list[tuple[ElementTree.Element, ElementTree.Element]]:
    """Every case-insensitively matching node at any depth, with its parent."""

    wanted = setting.casefold()
    found = []
    stack = [root]
    while stack:
        parent = stack.pop()
        for node in list(parent):
            if node.tag == "setting" and (node.get("id") or "").casefold() == wanted:
                found.append((parent, node))
            stack.append(node)
    return found


def validate(document: str | None) -> None:
    """Raises SettingsError unless `document` is a Kodi settings document."""

    _root(document)


def observe(document: str | None, setting: str) -> str | None:
    """The value Kodi resolves for `setting`, or None when it is unset.

    A node carrying its value in a `value` attribute rather than as text reads
    as unset, which is what Kodi does with a version 2 document.
    """

    root = _root(document)
    for parent, node in _matches(root, setting):
        if parent is root:
            return node.text
    return None


def rewrite(document: str | None, settings: Mapping[str, str]) -> str:
    """`document` with `settings` set, serialised the way the shell writes it."""

    root = _root(document)
    for setting, value in settings.items():
        node = None
        for parent, candidate in _matches(root, setting):
            if parent is root and node is None:
                node = candidate
                continue
            parent.remove(candidate)
        if node is None:
            node = ElementTree.SubElement(root, "setting")
        node.set("id", setting)
        # A node marked `default` is one Kodi feels free to overwrite.
        node.attrib.pop("default", None)
        node.attrib.pop("value", None)
        node.text = value

    tree = ElementTree.ElementTree(root)
    ElementTree.indent(tree, space="    ")
    raw: bytes = ElementTree.tostring(root, encoding="UTF-8", xml_declaration=True)
    body = raw.decode("utf-8")
    return body if body.endswith("\n") else body + "\n"
