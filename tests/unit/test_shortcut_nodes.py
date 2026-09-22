"""Arctic Fuse's Shortcut Nodes.

A Shortcut Node is a whole JSON document the Reconciler renders: the widget
rows under the home and hub screens, and the power menu. Every byte is
declared, so the Observation is the rendering and nothing inside the file is
Unmanaged State.

The files sit in a directory the skin also writes into. It is never
enumerated: each of the four is declared by name, and the skin's own two are
left exactly as found.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from .conftest import FakeDevice, shipped_profile

NEW_SHOWS = """\
      - guid: coreelec-home-new-shows
        playlist: NewShows.xsp
        target: videos
"""

POWER_OFF = """\
      - guid: coreelec-power-poweroff
        path: Powerdown()
        label: "$LOCALIZE[13016]"
        icon: special://skin/extras/icons/power.png
"""

# The bytes the Recovery Baseline writes: sorted keys, four-space indent, one
# trailing newline. Value parity is what keeps the two engines from reverting
# each other, so it is stated here in full rather than recomputed.
EXPECTED_HOME_WIDGETS = """\
[
    {
        "guid": "coreelec-home-new-shows",
        "icon": "",
        "label": "New Shows",
        "path": "special://profile/playlists/video/NewShows.xsp",
        "target": "videos"
    }
]
"""


def node_block(document: Path, shortcuts: str) -> str:
    """One entry in a Profile's `shortcut_nodes` list."""

    return f"\n  - document: {document}\n    shortcuts:\n{shortcuts}"


def declare(device: FakeDevice, shortcuts: str, document: Path | None = None) -> None:
    """Writes a Profile declaring one Shortcut Node holding `shortcuts`."""

    where = document if document is not None else device.nodes / "homewidgets.json"
    device.write_profile(device.profile_body(nodes=node_block(where, shortcuts)))


def test_a_node_lands_in_the_add_ons_own_shape_and_a_second_plan_is_empty(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device, NEW_SHOWS)

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    node = device.nodes / "homewidgets.json"
    assert node.read_text(encoding="utf-8") == EXPECTED_HOME_WIDGETS

    assert reconcile("plan", "--room", "theater") == 0
    assert "no changes" in capsys.readouterr().out


def test_a_reference_supplies_the_playlists_path_and_its_label(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The shortcut states neither, and both come from one declaration."""

    declare(device, NEW_SHOWS)

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    item = json.loads((device.nodes / "homewidgets.json").read_text(encoding="utf-8"))
    assert item[0]["path"] == "special://profile/playlists/video/NewShows.xsp"
    assert item[0]["label"] == "New Shows"


def test_a_literal_path_carries_a_builtin_and_its_own_label(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device, POWER_OFF, device.nodes / "powermenu.json")

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    item = json.loads((device.nodes / "powermenu.json").read_text(encoding="utf-8"))
    assert item == [
        {
            "guid": "coreelec-power-poweroff",
            "icon": "special://skin/extras/icons/power.png",
            "label": "$LOCALIZE[13016]",
            "path": "Powerdown()",
            "target": "",
        }
    ]


def test_a_shortcut_stating_both_arms_is_refused_before_device_contact(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(
        device,
        "      - guid: coreelec-home-new-shows\n"
        "        playlist: NewShows.xsp\n"
        "        path: Powerdown()\n",
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "coreelec-home-new-shows" in err
    assert "exactly one of playlist and path" in err
    assert device.effects == []
    assert not (device.nodes / "homewidgets.json").exists()


def test_a_shortcut_stating_neither_arm_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device, "      - guid: coreelec-home-new-shows\n")

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "coreelec-home-new-shows" in err
    assert "exactly one of playlist and path" in err


def test_a_label_beside_a_playlist_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(
        device,
        "      - guid: coreelec-home-new-shows\n"
        "        playlist: NewShows.xsp\n"
        "        label: Newest Shows\n",
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "coreelec-home-new-shows" in err
    assert "supplies its label" in err


def test_a_playlist_the_profile_does_not_declare_names_both(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The failure mode `RecentlyReleasedMovies90Days.xsp` once had."""

    declare(
        device,
        "      - guid: coreelec-home-retired\n"
        "        playlist: RecentlyReleasedMovies90Days.xsp\n",
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "coreelec-home-retired" in err
    assert "RecentlyReleasedMovies90Days.xsp" in err
    assert device.effects == []


def test_a_literal_path_without_a_label_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(
        device,
        "      - guid: coreelec-power-poweroff\n        path: Powerdown()\n",
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "coreelec-power-poweroff" in err
    assert "states its own label" in err


def test_one_guid_declared_twice_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device, NEW_SHOWS + NEW_SHOWS)

    assert reconcile("apply", "--room", "theater") == 1

    assert "coreelec-home-new-shows" in capsys.readouterr().err


def test_a_guid_repeated_inside_a_submenu_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The add-on finds an item by walking the tree, so depth does not hide one."""

    declare(
        device,
        NEW_SHOWS
        + "        submenu:\n"
        + "          - guid: coreelec-home-new-shows\n"
        + "            playlist: NewShows.xsp\n"
        + "            target: videos\n",
    )

    assert reconcile("apply", "--room", "theater") == 1

    assert "coreelec-home-new-shows" in capsys.readouterr().err
    assert device.effects == []


def test_an_empty_guid_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An item stating no guid gets a random one, which never converges."""

    declare(
        device,
        '      - guid: ""\n        playlist: NewShows.xsp\n        target: videos\n',
    )

    assert reconcile("apply", "--room", "theater") == 1

    assert "guid must not be empty" in capsys.readouterr().err
    assert device.effects == []


def test_a_shortcut_nests_shortcuts_of_the_same_kind(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`submenu` and `widgets` hold items of exactly the outer type."""

    declare(
        device,
        "      - guid: coreelec-home-tv\n"
        "        path: videodb://tvshows/titles/\n"
        "        label: TV Shows\n"
        "        target: videos\n"
        "        widgets:\n"
        "          - guid: coreelec-home-new-shows\n"
        "            playlist: NewShows.xsp\n"
        "            target: videos\n"
        "        submenu:\n"
        "          - guid: coreelec-home-settings\n"
        "            path: ActivateWindow(settings)\n"
        "            label: Settings\n",
    )

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    item = json.loads((device.nodes / "homewidgets.json").read_text(encoding="utf-8"))
    assert item[0]["widgets"][0]["label"] == "New Shows"
    assert item[0]["widgets"][0]["path"].endswith("NewShows.xsp")
    assert item[0]["submenu"][0]["label"] == "Settings"


def test_a_node_that_nests_nothing_writes_neither_key(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The add-on creates either key lazily, so absent and empty are one."""

    declare(device, NEW_SHOWS)

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    item = json.loads((device.nodes / "homewidgets.json").read_text(encoding="utf-8"))
    assert "submenu" not in item[0]
    assert "widgets" not in item[0]


def test_applying_a_node_takes_the_kodi_stop(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The skin reads a node file when it loads, and holds what it read."""

    declare(device, NEW_SHOWS)

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert device.effects == ["stop kodi.service", "start kodi.service"]


def test_the_skins_own_node_files_are_left_alone(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The directory is never enumerated, so nothing undeclared is touched."""

    device.nodes.mkdir(parents=True)
    theirs = device.nodes / "skinvariables-shortcut-searchwidgets.json"
    theirs.write_text('[{"guid": "guid-1a2b3c4d"}]\n', encoding="utf-8")
    declare(device, NEW_SHOWS)

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert theirs.read_text(encoding="utf-8") == '[{"guid": "guid-1a2b3c4d"}]\n'
    assert sorted(entry.name for entry in device.nodes.iterdir()) == [
        "homewidgets.json",
        "skinvariables-shortcut-searchwidgets.json",
    ]


def test_the_shipped_profile_declares_four_node_files_and_every_guid() -> None:
    profile = shipped_profile()
    nodes: list[dict[str, Any]] = profile["shortcut_nodes"]

    assert [Path(node["document"]).name for node in nodes] == [
        "skinvariables-shortcut-homewidgets.json",
        "skinvariables-shortcut-1101widgets.json",
        "skinvariables-shortcut-1102widgets.json",
        "skinvariables-shortcut-powermenu.json",
    ]

    declared = {
        playlist["file"] for playlist in profile["smart_playlists"]["playlists"]
    }
    for node in nodes:
        for shortcut in node["shortcuts"]:
            assert shortcut["guid"]
            if "playlist" in shortcut:
                assert shortcut["playlist"] in declared
