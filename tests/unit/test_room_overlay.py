"""Room-scoped Kodi settings and the transforms that come with them.

Nine State Addresses inside `guisettings.xml` describe the room's hardware
rather than the Profile's class of Devices. The Room Overlay declares them
with the Profile's schema, the Reconciler concatenates the two lists, and two
of them are not written as declared: one is inverted and one is mapped.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from .conftest import ROOM_HEADER, FakeDevice

DOLBY_VISION = """\
  - setting: coreelec.amlogic.disabledolbyvision
    value: "true"
    transform: invert
  - setting: coreelec.amlogic.dolbyvisionled
    value: tv-led
    transform: dolby_vision_mode
"""


def values(document: Path) -> dict[str, str | None]:
    """Every setting Kodi would read, as id to text."""
    root = ElementTree.parse(document).getroot()
    return {node.get("id") or "": node.text for node in root.findall("setting")}


def shipped_room_settings() -> list[dict[str, str]]:
    """The Kodi settings the committed Room Overlay declares, in file order."""
    room = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "rooms"
        / "theater"
        / "room.yaml"
    )
    declared = yaml.safe_load(room.read_text(encoding="utf-8"))["kodi_settings"]
    assert isinstance(declared, list)
    return declared


def test_a_room_overlay_without_the_block_is_rejected_naming_the_key(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_room(ROOM_HEADER)

    assert reconcile("apply", "--room", "theater") == 1

    assert "kodi_settings" in capsys.readouterr().err


def test_a_room_setting_the_profile_does_not_declare_is_added(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_room_settings(
        '  - setting: audiooutput.passthrough\n    value: "true"\n'
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert values(device.guisettings) == {
        "videolibrary.flattentvshows": "1",
        "audiooutput.passthrough": "true",
    }
    out = capsys.readouterr().out
    assert f"{device.guisettings}#audiooutput.passthrough: (unset) -> true" in out


def test_an_address_declared_twice_is_rejected_before_device_contact(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Room Overlay wins on collision in the language, but nothing needs
    that yet, so a collision is an error naming the address instead."""
    device.write_room_settings(
        '  - setting: videolibrary.flattentvshows\n    value: "0"\n'
    )

    assert reconcile("apply", "--room", "theater") == 1

    assert device.effects == []
    assert not device.guisettings.exists()
    err = capsys.readouterr().err
    assert "videolibrary.flattentvshows" in err


def test_a_collision_is_found_however_the_two_sides_are_cased(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Kodi resolves a setting ID without regard to case, so two differently
    cased declarations are the same State Address declared twice."""
    device.write_room_settings(
        '  - setting: VideoLibrary.FlattenTvShows\n    value: "0"\n'
    )

    assert reconcile("apply", "--room", "theater") == 1

    assert "VideoLibrary.FlattenTvShows" in capsys.readouterr().err


def test_dolby_vision_is_written_inverted_and_the_mode_is_mapped(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_room_settings(DOLBY_VISION)

    assert reconcile("apply", "--room", "theater") == 0

    assert values(device.guisettings) == {
        "videolibrary.flattentvshows": "1",
        # Dolby Vision is on, so the setting that disables it is false.
        "coreelec.amlogic.disabledolbyvision": "false",
        # Display-led is Kodi's ordinal 0.
        "coreelec.amlogic.dolbyvisionled": "0",
    }


def test_dolby_vision_off_and_player_led_take_the_other_branch(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_room_settings(
        DOLBY_VISION.replace('"true"', '"false"').replace("tv-led", "player-led")
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert values(device.guisettings)["coreelec.amlogic.disabledolbyvision"] == "true"
    assert values(device.guisettings)["coreelec.amlogic.dolbyvisionled"] == "1"


def test_a_transformed_setting_plans_the_value_that_reaches_the_device(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The Plan is read against the Device, so it names the value Kodi will
    hold, and names the declaration it came from so the Room Overlay still
    reads as the source."""
    device.write_room_settings(DOLBY_VISION)

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert (
        f"{device.guisettings}#coreelec.amlogic.disabledolbyvision: (unset) -> "
        "false (invert of true)"
    ) in out
    assert (
        f"{device.guisettings}#coreelec.amlogic.dolbyvisionled: (unset) -> "
        "0 (dolby_vision_mode of tv-led)"
    ) in out


def test_a_transformed_setting_converges_on_a_second_plan(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_room_settings(DOLBY_VISION)
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert reconcile("plan", "--room", "theater") == 0

    assert "no changes" in capsys.readouterr().out


def test_an_unknown_transform_is_rejected_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_room_settings(
        "  - setting: audiooutput.passthrough\n"
        '    value: "true"\n'
        "    transform: negate\n"
    )

    assert reconcile("apply", "--room", "theater") == 1

    assert "negate" in capsys.readouterr().err


def test_a_value_the_transform_cannot_map_is_rejected_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transform's domain is closed: `yes` is not a Dolby Vision mode, and
    writing it through would put a value Kodi ignores on the Device."""
    device.write_room_settings(
        "  - setting: coreelec.amlogic.dolbyvisionled\n"
        "    value: yes-please\n"
        "    transform: dolby_vision_mode\n"
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "yes-please" in err
    assert "dolby_vision_mode" in err


def test_the_shipped_room_overlay_declares_the_nine_room_scoped_addresses(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The committed Room Overlay, merged with the fake Device's Profile,
    converges in one write and one restart and then plans clean."""
    declared = shipped_room_settings()
    assert [entry["setting"] for entry in declared] == [
        "videoscreen.whitelist",
        "coreelec.amlogic.disabledolbyvision",
        "coreelec.amlogic.dolbyvisionled",
        "audiooutput.passthrough",
        "audiooutput.ac3passthrough",
        "audiooutput.eac3passthrough",
        "audiooutput.dtspassthrough",
        "audiooutput.truehdpassthrough",
        "audiooutput.dtshdpassthrough",
    ]
    device.write_room_settings(
        "".join(
            f"  - setting: {entry['setting']}\n"
            f'    value: "{entry["value"]}"\n'
            + (f"    transform: {entry['transform']}\n" if "transform" in entry else "")
            for entry in declared
        )
    )

    assert reconcile("apply", "--room", "theater") == 0

    written = values(device.guisettings)
    assert written["coreelec.amlogic.disabledolbyvision"] == "false"
    assert written["coreelec.amlogic.dolbyvisionled"] == "0"
    for setting in (
        "audiooutput.passthrough",
        "audiooutput.ac3passthrough",
        "audiooutput.eac3passthrough",
        "audiooutput.dtspassthrough",
        "audiooutput.truehdpassthrough",
        "audiooutput.dtshdpassthrough",
    ):
        assert written[setting] == "true"
    assert device.effects == ["stop kodi.service", "start kodi.service"]
    capsys.readouterr()

    assert reconcile("plan", "--room", "theater") == 0

    assert "no changes" in capsys.readouterr().out
