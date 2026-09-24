"""A skin's settings document, in the `skin` dialect.

Kodi core reads a skin's `settings.xml` itself (`CSkinInfo`), and its loader
keeps only a `<setting>` typed `string` or `bool`. An untyped node is dropped
without a word, so the skin starts from its own defaults and later rewrites
the file from memory. The `skin` dialect therefore writes every node typed,
and reads an untyped node as holding no value: that is what Kodi resolves
from it, and reading it any other way would let Verification pass while the
skin showed its defaults.

These tests drive the Reconciler through its public entry point only
(ADR 0011).
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Callable

import pytest

from .conftest import FakeDevice, document_block, write_document

SKIN_SETTINGS = """\
      - setting: HomeSwitcher.1101.Name
        value: TV Shows
      - setting: HomeSwitcher.1101.Toggle
        value: "true"
      - setting: Hub.1107.DisableSearch
        unset: true
"""


def with_skin(device: FakeDevice) -> str:
    return device.profile_body(extra=document_block(device.skin, "skin", SKIN_SETTINGS))


def nodes(device: FakeDevice) -> dict[str, tuple[str | None, str | None]]:
    """Every setting the skin document holds, as id to (type, text)."""

    root = ElementTree.parse(device.skin).getroot()
    return {
        node.get("id") or "": (node.get("type"), node.text)
        for node in root.findall("setting")
    }


def test_a_fresh_skin_document_is_written_with_typed_nodes(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_profile(with_skin(device))

    assert reconcile("apply", "--room", "theater") == 0

    root = ElementTree.parse(device.skin).getroot()
    # Kodi writes a skin document's root without a version, and so does the
    # shell.
    assert root.attrib == {}
    assert nodes(device) == {
        "HomeSwitcher.1101.Name": ("string", "TV Shows"),
        "HomeSwitcher.1101.Toggle": ("string", "true"),
    }


def test_an_untyped_node_observes_as_unset_and_is_typed_when_applied(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The node Kodi drops must not look converged."""

    device.write_profile(with_skin(device))
    write_document(
        device.skin,
        "<settings>"
        '<setting id="HomeSwitcher.1101.Name">TV Shows</setting>'
        '<setting id="HomeSwitcher.1101.Toggle" type="string">true</setting>'
        "</settings>",
    )

    assert reconcile("plan", "--room", "theater") == 0
    report = capsys.readouterr().out
    assert "HomeSwitcher.1101.Name" in report
    assert "HomeSwitcher.1101.Toggle" not in report

    assert reconcile("apply", "--room", "theater") == 0
    assert nodes(device)["HomeSwitcher.1101.Name"] == ("string", "TV Shows")

    capsys.readouterr()
    assert reconcile("plan", "--room", "theater") == 0
    assert "HomeSwitcher.1101" not in capsys.readouterr().out


def test_a_cleared_skin_address_is_emptied_and_stays_typed(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_profile(with_skin(device))
    write_document(
        device.skin,
        "<settings>"
        '<setting id="Hub.1107.DisableSearch" type="string">true</setting>'
        "</settings>",
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert nodes(device)["Hub.1107.DisableSearch"] == ("string", None)
