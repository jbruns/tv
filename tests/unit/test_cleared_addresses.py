"""A Cleared Address: Desired State that the Device resolves no value.

Half the Arctic Fuse skin cohort is cleared rather than set. A setting
therefore states exactly one of `value`, `from_env` and `unset`, and the third
arm cannot be spelled as either of the first two:

- `value: ""` would compare an empty string against an Observation of None,
  because an empty node reads back as no value. It would plan a Change on
  every Run and fail its own Verification forever.
- `value: null` is what a truncated `value:` line reads as, so accepting it
  would make a typo silently mean "clear this".

These tests drive the Reconciler through its public entry point only
(ADR 0011).
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from typing import Any

import pytest

from .conftest import (
    EXPECTED_XSP,
    FakeDevice,
    document_block,
    shipped_profile,
    text_values,
    write_document,
)

# What the shell leaves behind, and what Kodi leaves behind on top of it. The
# skin document carries no version attribute because the shell provisioner
# created it, which is the `skin` shape: a value is element text.
#
# `Hub.1107.DisableSearch` is a node the shell wrote and someone since set;
# the other three cleared ids are the three states that all read as no value.
SKIN_ON_DEVICE = """\
<settings>
    <setting id="HomeSwitcher.1101.Name" type="string">TV Shows</setting>
    <setting id="Hub.1107.DisableSearch" type="string">true</setting>
    <setting id="HomeSwitcher.1104.Toggle" />
    <setting id="HomeSwitcher.1104.Icon"></setting>
</settings>
"""

# The four cleared ids above, plus the one valued address that anchors them.
# `HomeSwitcher.1104.Mode` is absent from the document entirely.
CLEARED_SETTINGS = """\
      - setting: HomeSwitcher.1101.Name
        value: TV Shows
      - setting: Hub.1107.DisableSearch
        unset: true
      - setting: HomeSwitcher.1104.Toggle
        unset: true
      - setting: HomeSwitcher.1104.Icon
        unset: true
      - setting: HomeSwitcher.1104.Mode
        unset: true
"""


def converge_baseline(device: FakeDevice) -> None:
    """Writes what the Profile's other two Resources already declare.

    The fixture Profile also holds a Smart Playlist and one `guisettings.xml`
    address. Putting both on the Device leaves the skin document as the only
    thing a Plan can be about.
    """

    device.playlists_dir.mkdir(parents=True, exist_ok=True)
    device.playlist.write_text(EXPECTED_XSP, encoding="utf-8")
    write_document(
        device.guisettings,
        '<settings version="2">'
        '<setting id="videolibrary.flattentvshows">1</setting></settings>',
    )


def with_skin(device: FakeDevice, settings: str = CLEARED_SETTINGS) -> str:
    """The Profile, declaring guisettings.xml and the skin document."""
    return device.profile_body(extra=document_block(device.skin, "skin", settings))


def one_setting(body: str) -> str:
    """A skin document declaring a single setting, from a YAML fragment."""
    return "".join(f"      {line}\n" for line in body.splitlines())


def test_a_setting_stating_two_arms_is_rejected_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        with_skin(
            device,
            one_setting(
                "- setting: HomeSwitcher.1104.Toggle\n  value: 'true'\n  unset: true"
            ),
        )
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "HomeSwitcher.1104.Toggle" in err
    assert "exactly one of value, from_env, from_profile and unset" in err
    # Rejected before Device contact: nothing was stopped and nothing written.
    assert device.effects == []
    assert not device.guisettings.exists()


def test_a_setting_stating_no_arm_is_rejected_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        with_skin(device, one_setting("- setting: HomeSwitcher.1104.Toggle"))
    )

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "HomeSwitcher.1104.Toggle" in err
    assert "exactly one of value, from_env, from_profile and unset" in err


def test_a_truncated_value_line_is_still_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`value:` with nothing after it is a typo, never a request to clear."""

    device.write_profile(
        with_skin(device, one_setting("- setting: HomeSwitcher.1104.Toggle\n  value:"))
    )

    assert reconcile("plan", "--room", "theater") == 1
    assert "expected a value" in capsys.readouterr().err


def test_unset_false_is_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        with_skin(
            device, one_setting("- setting: HomeSwitcher.1104.Toggle\n  unset: false")
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "HomeSwitcher.1104.Toggle" in err
    assert "states true" in err


def test_a_cleared_setting_takes_no_transform(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        with_skin(
            device,
            one_setting(
                "- setting: HomeSwitcher.1104.Toggle\n"
                "  unset: true\n"
                "  transform: invert"
            ),
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "HomeSwitcher.1104.Toggle" in err
    assert "takes no transform" in err


def test_an_absent_a_self_closing_and_an_empty_node_observe_identically(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The three shapes of no value are one Observation, not three.

    Kodi materialises a node for every skin string the skin merely references,
    writing it self-closing or empty. If either read as anything but None, a
    Cleared Address would plan a Change at every Kodi restart and never
    converge. This looks like an accident of ElementTree; it is load-bearing.
    """

    write_document(
        device.skin,
        """\
<settings>
    <setting id="HomeSwitcher.1101.Name" type="string">TV Shows</setting>
    <setting id="HomeSwitcher.1104.Toggle" />
    <setting id="HomeSwitcher.1104.Icon"></setting>
</settings>
""",
    )
    converge_baseline(device)
    device.write_profile(with_skin(device))

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    # Absent, self-closing and empty: none of the three is a Change, and no
    # Kodi stop is planned for a document with nothing to do.
    assert "plan: no changes" in out
    assert device.effects == []


def test_applying_a_clear_writes_an_empty_node_rather_than_removing_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    write_document(device.skin, SKIN_ON_DEVICE)
    device.write_profile(with_skin(device))

    assert reconcile("apply", "--room", "theater") == 0

    held = text_values(device.skin)
    # The node the shell wrote a value into is still there, holding none.
    assert "Hub.1107.DisableSearch" in held
    assert held["Hub.1107.DisableSearch"] is None
    # The shell removes such a node instead. Both leave the Device resolving
    # no value, so the two engines do not revert each other over it.
    assert '<setting id="Hub.1107.DisableSearch"' in device.skin.read_text(
        encoding="utf-8"
    )


def test_an_already_cleared_address_creates_no_node(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """Nothing is written for an address the Device already resolves nothing
    from, even when another address in the same document is being converged.
    """

    write_document(device.skin, SKIN_ON_DEVICE)
    device.write_profile(with_skin(device))

    assert reconcile("apply", "--room", "theater") == 0

    assert "HomeSwitcher.1104.Mode" not in text_values(device.skin)


def test_a_clear_plans_as_an_update_and_prints_no_desired_value(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(device.skin, SKIN_ON_DEVICE)
    converge_baseline(device)
    device.write_profile(with_skin(device))

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert f"update {device.skin}#Hub.1107.DisableSearch: true -> (cleared)" in out
    # A Cleared Address is never a `create`: there is nothing to create.
    assert "create " not in out
    assert "plan: 1 change" in out


def test_a_cleared_address_converges_and_stays_converged(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(device.skin, SKIN_ON_DEVICE)
    device.write_profile(with_skin(device))

    assert reconcile("apply", "--room", "theater") == 0
    assert "verification: converged" in capsys.readouterr().out

    # The second Run is the one that would fail if an empty node read back as
    # anything but no value.
    assert reconcile("plan", "--room", "theater") == 0
    assert "plan: no changes" in capsys.readouterr().out


def test_every_skin_node_written_is_typed(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """Kodi's skin loader drops an untyped node, so every write is typed."""

    write_document(device.skin, SKIN_ON_DEVICE)
    device.write_profile(
        with_skin(
            device,
            CLEARED_SETTINGS
            + '      - setting: HomeSwitcher.1108.Toggle\n        value: "true"\n',
        )
    )

    assert reconcile("apply", "--room", "theater") == 0

    root = ElementTree.parse(device.skin).getroot()
    types = {node.get("id"): node.get("type") for node in root.findall("setting")}
    assert types["HomeSwitcher.1101.Name"] == "string"
    # Emptied by the clear, and still typed.
    assert types["Hub.1107.DisableSearch"] == "string"
    # Created by the Reconciler.
    assert types["HomeSwitcher.1108.Toggle"] == "string"
    # Already clear, and typed when the document is rewritten around it.
    assert types["HomeSwitcher.1104.Toggle"] == "string"


def test_a_room_overlay_may_clear_an_address(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """The third arm is the setting schema's, so both sides read it."""

    device.write_room_settings("- setting: videolibrary.showallitems\n  unset: true\n")
    write_document(
        device.guisettings,
        '<settings version="2">'
        '<setting id="videolibrary.showallitems">true</setting></settings>',
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert text_values(device.guisettings)["videolibrary.showallitems"] is None


# --- The committed Profile's Arctic Fuse document ---------------------------

SKIN_PATH = "/storage/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"

# The sixteen ids the home screen must resolve nothing from. Restated here
# rather than derived, because this is the list a typo would quietly shorten
# and nothing on the Device can catch: a wrong id resolves no value, matches
# `unset`, and reports converged forever
# (ADR 0012, "Rule 2 does not reach a Cleared Address").
CLEARED_IDS = (
    "HomeSwitcher.1103.Shortcut.Target",
    "HomeSwitcher.1103.Spotlight.Label",
    "HomeSwitcher.1103.Spotlight.Path",
    "HomeSwitcher.1103.Spotlight.Target",
    "HomeSwitcher.1104.Toggle",
    "HomeSwitcher.1104.Shortcut.Path",
    "HomeSwitcher.1104.Shortcut.Target",
    "HomeSwitcher.1104.Spotlight.Label",
    "HomeSwitcher.1104.Spotlight.Path",
    "HomeSwitcher.1104.Spotlight.Target",
    "Hub.1107.DisableSearch",
    "Hub.1107.DisableChannels",
    "Hub.1107.DisableGroups",
    "Hub.1107.DisableRecordings",
    "optionstiles.03.path",
    "optionstiles.03.target",
)

# The three the shell clears and the Reconciler deliberately does not declare.
# Arctic Fuse rewrites them on every skin load — the theater Ugoos holds
# `Custom` and `Standard` for the first two — so declaring them would give two
# engines that revert each other at every restart. They are inert while
# `HomeSwitcher.1104.Toggle` is empty, which is the field that decides whether
# the hub renders at all.
ARCTIC_FUSE_OWNS = (
    "HomeSwitcher.1104.Name",
    "HomeSwitcher.1104.Mode",
    "HomeSwitcher.1104.Icon",
)


def shipped_skin() -> dict[str, Any]:
    """The Arctic Fuse Settings Document the committed Profile declares."""
    documents = shipped_profile()["settings_documents"]
    return next(
        document for document in documents if document.get("document") == SKIN_PATH
    )


def skin_extra(device: FakeDevice) -> str:
    """The committed skin document, re-pointed at the fake Device."""
    document = shipped_skin()
    return document_block(
        device.skin,
        str(document["dialect"]),
        "".join(
            f"      - setting: {entry['setting']}\n"
            + (
                "        unset: true\n"
                if entry.get("unset")
                else f'        value: "{entry["value"]}"\n'
            )
            for entry in document["settings"]
        ),
    )


def test_the_shipped_profile_declares_the_arctic_fuse_document() -> None:
    document = shipped_skin()
    settings = document["settings"]
    cleared = tuple(entry["setting"] for entry in settings if entry.get("unset"))
    valued = [entry for entry in settings if not entry.get("unset")]

    # Kodi core reads the skin document and drops an untyped node, so it is
    # declared in the dialect that writes every node typed.
    assert document["dialect"] == "skin"
    assert cleared == CLEARED_IDS
    assert len(settings) == 44
    assert len(valued) == 28
    # Nothing in this document names a value, and nothing clears with a value.
    assert all("from_env" not in entry for entry in settings)
    assert all("value" not in entry for entry in settings if entry.get("unset"))
    # The three Arctic Fuse writes for itself are declared neither way.
    declared = {entry["setting"] for entry in settings}
    assert declared.isdisjoint(ARCTIC_FUSE_OWNS)


def test_no_valued_arctic_fuse_setting_plans_as_a_create(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The shell writes every valued address, so none may plan as a `create`.

    The cleared ones are absent from the Device here, which is the state the
    shell leaves them in, and they must plan as nothing at all.
    """

    converge_baseline(device)
    document = shipped_skin()
    device.write_profile(device.profile_body(extra=skin_extra(device)))
    write_document(
        device.skin,
        "<settings>\n"
        + "".join(
            f'    <setting id="{entry["setting"]}" type="string">stale</setting>\n'
            for entry in document["settings"]
            if not entry.get("unset")
        )
        + "</settings>\n",
    )

    assert reconcile("plan", "--room", "theater") == 0

    reported = [
        line
        for line in capsys.readouterr().out.splitlines()
        if str(device.skin) in line
    ]
    assert len(reported) == 28
    assert all(line.startswith("update ") for line in reported)


def test_the_shipped_arctic_fuse_document_survives_a_kodi_restart(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Convergence holds across the moment Kodi materialises the empty nodes.

    Kodi writes a node for every skin string the skin merely references, with
    a lowercased id and no text. That is when a Cleared Address would re-plan
    if an empty node read as anything but no value, and it is the half of the
    check a single Run cannot see.
    """

    converge_baseline(device)
    document = shipped_skin()
    device.write_profile(device.profile_body(extra=skin_extra(device)))
    write_document(
        device.skin,
        "<settings>\n"
        + "".join(
            f'    <setting id="{entry["setting"]}" type="string">stale</setting>\n'
            for entry in document["settings"]
        )
        + "</settings>\n",
    )

    assert reconcile("apply", "--room", "theater") == 0
    assert "verification: converged" in capsys.readouterr().out

    held = text_values(device.skin)
    assert held["optionstiles.03.include"] == "Weather"
    assert all(held[setting] is None for setting in CLEARED_IDS)

    # Kodi, on the next start: every cleared id re-materialised, lowercased
    # and empty, and the nodes it did not write left alone.
    root = ElementTree.parse(device.skin).getroot()
    for setting in CLEARED_IDS:
        for node in [n for n in root if (n.get("id") or "") == setting]:
            root.remove(node)
        ElementTree.SubElement(root, "setting", {"id": setting.casefold()})
    device.skin.write_text(
        ElementTree.tostring(root, encoding="unicode"), encoding="utf-8"
    )

    assert reconcile("plan", "--room", "theater") == 0
    assert "plan: no changes" in capsys.readouterr().out
