"""Reconciling Kodi settings inside guisettings.xml against a fake Device.

guisettings.xml is a shared document: the Reconciler owns the State Addresses
the Profile declares and must leave every other setting alone. Kodi rewrites
the document from memory when it exits, so the restart Effect is part of the
Resource Type rather than a courtesy.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import FakeDevice, shipped_profile

UNMANAGED = """\
<settings version="2">
    <setting id="audiooutput.channels">2</setting>
    <setting id="locale.audiolanguage">original</setting>
    <setting id="videoscreen.resolution" default="true">16</setting>
</settings>
"""


def values(document: Path) -> dict[str, str | None]:
    """Every setting Kodi would read, as id to text."""
    root = ElementTree.parse(document).getroot()
    return {node.get("id") or "": node.text for node in root.findall("setting")}


def write_document(device: FakeDevice, body: str) -> None:
    device.guisettings.parent.mkdir(parents=True, exist_ok=True)
    device.guisettings.write_text(body, encoding="utf-8")


def test_plan_names_the_state_address_and_both_values(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(device, UNMANAGED)

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert f"{device.guisettings}#videolibrary.flattentvshows" in out
    assert "(unset) -> 1" in out


def test_plan_mutates_nothing_including_the_kodi_service(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    write_document(device, UNMANAGED)

    assert reconcile("plan", "--room", "theater") == 0

    assert device.guisettings.read_text(encoding="utf-8") == UNMANAGED
    assert device.effects == []


def test_apply_converges_the_setting_and_preserves_the_others(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(device, UNMANAGED)

    assert reconcile("apply", "--room", "theater") == 0

    assert values(device.guisettings) == {
        "audiooutput.channels": "2",
        "locale.audiolanguage": "original",
        "videoscreen.resolution": "16",
        "videolibrary.flattentvshows": "1",
    }
    assert device.guisettings.stat().st_mode & 0o777 == 0o600
    assert "converged" in capsys.readouterr().out


def test_apply_creates_the_document_when_the_device_has_none(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    assert not device.guisettings.exists()

    assert reconcile("apply", "--room", "theater") == 0

    assert values(device.guisettings) == {"videolibrary.flattentvshows": "1"}


def test_a_second_plan_after_apply_reports_no_changes(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(device, UNMANAGED)
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert reconcile("plan", "--room", "theater") == 0

    assert "no changes" in capsys.readouterr().out


def test_a_case_variant_resolves_to_the_one_node_kodi_reads(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """Kodi resolves a setting ID without regard to case, so the differently
    cased node is the same setting and must not survive alongside the one the
    Reconciler writes."""
    write_document(
        device,
        '<settings version="2">\n'
        '    <setting id="VideoLibrary.FlattenTvShows">0</setting>\n'
        "</settings>\n",
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert values(device.guisettings) == {"videolibrary.flattentvshows": "1"}


def test_a_nested_duplicate_is_removed(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    write_document(
        device,
        '<settings version="2">\n'
        "    <category>\n"
        '        <setting id="videolibrary.flattentvshows">0</setting>\n'
        "    </category>\n"
        "</settings>\n",
    )

    assert reconcile("apply", "--room", "theater") == 0

    root = ElementTree.parse(device.guisettings).getroot()
    nodes = [
        node
        for node in root.iter("setting")
        if (node.get("id") or "").casefold() == "videolibrary.flattentvshows"
    ]
    assert len(nodes) == 1
    assert root.find("setting[@id='videolibrary.flattentvshows']") is nodes[0]
    assert nodes[0].text == "1"


def test_the_default_attribute_is_dropped_so_kodi_keeps_the_value(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    write_document(
        device,
        '<settings version="2">\n'
        '    <setting id="videolibrary.flattentvshows" default="true">0</setting>\n'
        "</settings>\n",
    )

    assert reconcile("apply", "--room", "theater") == 0

    node = ElementTree.parse(device.guisettings).getroot().find("setting")
    assert node is not None
    assert "default" not in node.attrib
    assert node.text == "1"


def test_a_second_setting_needs_no_code_change(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        device.profile_body()
        + '      - setting: videolibrary.showemptytvshows\n        value: "0"\n'
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert values(device.guisettings) == {
        "videolibrary.flattentvshows": "1",
        "videolibrary.showemptytvshows": "0",
    }
    out = capsys.readouterr().out
    assert "videolibrary.showemptytvshows" in out
    assert "applied 3 changes" in out


def test_the_restart_effect_is_taken_once_for_many_settings(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_profile(
        device.profile_body()
        + '      - setting: videolibrary.showemptytvshows\n        value: "0"\n'
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert device.effects == ["stop kodi.service", "start kodi.service"]


def test_a_plan_of_only_playlist_changes_does_not_touch_kodi(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    assert reconcile("apply", "--room", "theater") == 0
    device.systemctl_log.unlink()
    device.playlist.write_text('<smartplaylist type="movies"/>\n', encoding="utf-8")

    assert reconcile("apply", "--room", "theater") == 0

    assert device.effects == []


def test_kodi_is_started_again_when_a_change_fails_partway(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fail Forward: the Run reports what landed and never leaves the
    television dead."""
    write_document(device, UNMANAGED)
    monkeypatch.setenv("FAKE_DEVICE_CHMOD_REFUSES", "guisettings")

    assert reconcile("apply", "--room", "theater") == 1

    assert device.effects == ["stop kodi.service", "start kodi.service"]
    assert device.playlist.exists()
    assert values(device.guisettings) == {
        "audiooutput.channels": "2",
        "locale.audiolanguage": "original",
        "videoscreen.resolution": "16",
    }
    captured = capsys.readouterr()
    assert "applied 1 of 2 changes" in captured.out
    assert f"not applied {device.guisettings}#videolibrary.flattentvshows" in (
        captured.out
    )
    assert "guisettings.xml" in captured.err


def test_a_device_that_will_not_start_kodi_again_is_reported(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FAKE_DEVICE_SYSTEMCTL_REFUSES", "start")

    assert reconcile("apply", "--room", "theater") == 1

    assert device.effects == ["stop kodi.service", "start kodi.service"]
    assert "starting kodi.service" in capsys.readouterr().err


def test_an_unreadable_document_is_named_before_kodi_is_stopped(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(device, '<settings version="2">\n')

    assert reconcile("apply", "--room", "theater") == 1

    assert device.effects == []
    assert "guisettings.xml" in capsys.readouterr().err


def test_a_setting_kodi_reverts_as_it_exits_still_converges(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A setting can look converged while Kodi is running and be reverted by
    Kodi's own exit write. The Observation that counts, and the set of
    settings written, are both taken after the service stopped."""
    device.write_profile(
        device.profile_body()
        + '      - setting: videolibrary.showemptytvshows\n        value: "0"\n'
    )
    write_document(
        device,
        '<settings version="2">\n'
        '    <setting id="videolibrary.flattentvshows">1</setting>\n'
        "</settings>\n",
    )
    memory = tmp_path / "kodi-memory.xml"
    memory.write_text(
        '<settings version="2">\n'
        '    <setting id="videolibrary.flattentvshows">0</setting>\n'
        "</settings>\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_DEVICE_KODI_MEMORY", str(memory))

    assert reconcile("apply", "--room", "theater") == 0

    assert values(device.guisettings) == {
        "videolibrary.flattentvshows": "1",
        "videolibrary.showemptytvshows": "0",
    }


def test_the_document_survives_an_interrupted_write(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_document(device, UNMANAGED)
    assert reconcile("apply", "--room", "theater") == 0
    converged = device.guisettings.read_text(encoding="utf-8")
    device.guisettings.write_text(UNMANAGED, encoding="utf-8")

    monkeypatch.setenv("FAKE_DEVICE_KILL_BEFORE_RENAME", "1")
    assert reconcile("apply", "--room", "theater") == 1

    assert device.guisettings.read_text(encoding="utf-8") == UNMANAGED
    assert device.effects[-2:] == ["stop kodi.service", "start kodi.service"]

    monkeypatch.delenv("FAKE_DEVICE_KILL_BEFORE_RENAME")
    assert reconcile("apply", "--room", "theater") == 0

    assert device.guisettings.read_text(encoding="utf-8") == converged


def shipped_settings() -> dict[str, str]:
    """The guisettings settings the committed Profile declares, in file order."""
    document = shipped_profile()
    constants = document["constants"]
    documents = document["settings_documents"]
    guisettings = [
        document for document in documents if document["dialect"] == "guisettings"
    ]
    assert len(guisettings) == 1, "the Profile declares guisettings.xml once"
    declared = guisettings[0]["settings"]
    assert isinstance(declared, list)
    # A setting takes a Profile Constant rather than repeating a literal the
    # Device records in two places, and what reaches Kodi is the same either
    # way. A Named Value has no committed value, so it is stood in for by
    # the key that names it.
    settings = {
        entry["setting"]: (
            constants[entry["from_profile"]]
            if "from_profile" in entry
            else entry["from_env"]
            if "from_env" in entry
            else entry["value"]
        )
        for entry in declared
    }
    assert len(settings) == len(declared), "a setting is declared twice"
    return settings


def test_the_shipped_settings_converge_in_one_write_and_one_restart(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declared = shipped_settings()
    device.write_profile(device.profile_body(declared))
    write_document(device, UNMANAGED)

    assert reconcile("apply", "--room", "theater") == 0

    assert values(device.guisettings) == {
        "audiooutput.channels": "2",
        "locale.audiolanguage": "original",
        "videoscreen.resolution": "16",
        **declared,
    }
    assert device.effects == ["stop kodi.service", "start kodi.service"]
    capsys.readouterr()

    assert reconcile("plan", "--room", "theater") == 0

    assert "no changes" in capsys.readouterr().out


def test_every_declared_setting_plans_as_an_update_on_a_provisioned_device(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """On a provisioned Device, no declared address may plan as a `create`.

    A create is a misread setting id, which would write a node Kodi ignores
    and still verify as converged.
    """
    declared = shipped_settings()
    device.write_profile(device.profile_body(declared))
    write_document(
        device,
        '<settings version="2">\n'
        + "".join(
            f'    <setting id="{setting}">stale</setting>\n' for setting in declared
        )
        + "</settings>\n",
    )

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    reported = [line for line in out.splitlines() if "guisettings.xml#" in line]
    assert len(reported) == len(declared)
    assert all(line.startswith("update ") for line in reported)
    for setting, value in declared.items():
        assert f"#{setting}: stale -> {value}" in out
