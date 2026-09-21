"""Reading and writing Kodi settings inside a Settings Document.

A Settings Document is not a document the Reconciler renders. It holds many
State Addresses, almost all of them Unmanaged State, so this module changes
only the State Addresses it is given and leaves every other setting's identity
and value exactly as it found them.

Kodi serialises these documents in more than one shape, and which shape a
document uses is not something the Reconciler may guess. `guisettings.xml` and
an add-on whose settings definition declares a version carry a value as
element text; an add-on whose definition carries no version attribute, such as
`weather.ha`, carries it in a `value` attribute instead. The dialect is
therefore declared in the Profile and checked against the Device: a document
that does not read as its declared dialect is an error naming the document,
never a plausible empty parse that would report every declared address as
unset.

Kodi resolves a setting ID without regard to case and reads only the direct
`<setting>` children of the root, while a recursive reader sees nested copies
too. The canonical node is therefore the one Kodi reads: every other match at
any depth is removed, matching the Recovery Baseline's behaviour.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping

GUISETTINGS = "guisettings"
ADDON_V1 = "addon_v1"
ADDON_V2 = "addon_v2"

# Every dialect this module can read and write. `guisettings` and `addon_v2`
# are the same shape on the wire and are named apart because they are
# different documents: one is Kodi core's and one is an add-on's, and what
# Kodi does to one it need not do to the other.
DIALECTS = (GUISETTINGS, ADDON_V1, ADDON_V2)

# The dialects that carry a setting's value as element text. `addon_v1` is the
# one that carries it in a `value` attribute.
_TEXT_DIALECTS = (GUISETTINGS, ADDON_V2)


class SettingsError(Exception):
    """A settings document that cannot be read in its declared dialect."""


def _empty(dialect: str) -> ElementTree.Element:
    """The root of a document the Device does not have yet.

    The shell provisioner writes a version attribute for the text dialects and
    none for `addon_v1`, so a document the Reconciler creates is the document
    the shell would have created.
    """

    attributes = {} if dialect == ADDON_V1 else {"version": "2"}
    return ElementTree.Element("settings", attributes)


def _mismatch(root: ElementTree.Element, dialect: str) -> str | None:
    """Why `root` is not a document in `dialect`, or None when it is.

    The check is on the shape of the document as a whole rather than on any
    one node. A stray legacy node inside an otherwise well-formed document is
    rewritten, as it always has been; a document that is wholly the other
    dialect is the mistake worth naming, because reading it in the declared
    dialect would report every declared address as unset and then plan every
    one of them as a `create`.
    """

    version = root.get("version")
    children = [node for node in root if node.tag == "setting"]
    if dialect == ADDON_V1:
        if version is not None:
            return (
                f'its root declares version="{version}", which is the {ADDON_V2} form'
            )
        for node in children:
            if node.get("value") is None and (node.text or "").strip():
                return (
                    f"{node.get('id') or ''} carries its value as element "
                    f"text, which is the {ADDON_V2} form"
                )
        return None
    if version is None:
        for node in children:
            if node.get("value") is not None:
                return (
                    f"{node.get('id') or ''} carries its value in a value "
                    "attribute and the root declares no version, which is "
                    f"the {ADDON_V1} form"
                )
    return None


def _root(document: str | None, dialect: str) -> ElementTree.Element:
    if dialect not in DIALECTS:
        raise SettingsError(f"unknown dialect: {dialect}")
    if document is None or not document.strip():
        return _empty(dialect)
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise SettingsError(str(error)) from error
    if root.tag != "settings":
        raise SettingsError(f"unexpected root element: {root.tag}")
    reason = _mismatch(root, dialect)
    if reason is not None:
        raise SettingsError(f"it is declared as {dialect} but {reason}")
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


def validate(document: str | None, dialect: str) -> None:
    """Raises SettingsError unless `document` reads as `dialect`."""

    _root(document, dialect)


def observe(document: str | None, dialect: str, setting: str) -> str | None:
    """The value Kodi resolves for `setting`, or None when it is unset.

    A node that carries its value in the other dialect's place reads as unset,
    which is what Kodi does with it.
    """

    root = _root(document, dialect)
    for parent, node in _matches(root, setting):
        if parent is root:
            return node.get("value") if dialect == ADDON_V1 else node.text
    return None


def rewrite(document: str | None, dialect: str, settings: Mapping[str, str]) -> str:
    """`document` with `settings` set, serialised the way the shell writes it."""

    root = _root(document, dialect)
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
        if dialect in _TEXT_DIALECTS:
            node.attrib.pop("value", None)
            node.text = value
        else:
            node.text = None
            node.set("value", value)

    tree = ElementTree.ElementTree(root)
    ElementTree.indent(tree, space="    ")
    raw: bytes = ElementTree.tostring(root, encoding="UTF-8", xml_declaration=True)
    body = raw.decode("utf-8")
    return body if body.endswith("\n") else body + "\n"
