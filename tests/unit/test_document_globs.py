"""A Settings Document the Profile cannot name, and the CEC power policy.

Kodi names a peripheral's settings document after the hardware's own
identity, so the theater Ugoos holds `cec_CEC_Adapter.xml`: a bus prefix Kodi
controls and an adapter name the adapter reports. A Profile can state the
pattern but not the path.

A Settings Document therefore states exactly one of `document` and
`document_glob`. The shape is declared, never sniffed: a `*` inside a
`document` is a character in a filename. A pattern is resolved against the
names the Device holds, in Python — an unmatched glob handed to the remote
`sh` expands to itself and arrives as a path that merely does not exist — and
exactly one match is required, because two CEC documents mean the second is
for hardware that is no longer there and writing either is a coin toss whose
symptom is a television that stops answering its own remote.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from typing import Any

import pytest

from .conftest import (
    FakeDevice,
    attribute_values,
    document_block,
    shipped_profile,
    write_document,
)

CEC_GLOB_PATH = "/storage/.kodi/userdata/peripheral_data/cec_*.xml"

CEC_SETTINGS = """\
      - setting: standby_pc_on_tv_standby
        value: ignore
        transform: cec_tv_off_action
      - setting: activate_source
        value: "0"
"""

# What Kodi leaves behind for a CEC adapter: the flat `addon_v1` form, with a
# bare root and the value in an attribute.
CEC_ON_DEVICE = """\
<settings>
    <setting id="activate_source" value="1" />
    <setting id="device_name" value="Kodi" />
</settings>
"""


def cec_glob(device: FakeDevice) -> str:
    """The Profile's pattern for the CEC document, on the fake Device."""

    return f"{device.peripheral_data}/cec_*.xml"


def with_cec(device: FakeDevice, settings: str = CEC_SETTINGS) -> str:
    """The Profile, naming the CEC document by pattern."""

    return device.profile_body(
        extra=document_block(cec_glob(device), "addon_v1", settings, "document_glob")
    )


def test_a_document_stating_both_a_path_and_a_glob_is_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        device.profile_body(
            extra=(
                f"  - document: {device.cec}\n"
                f"    document_glob: {cec_glob(device)}\n"
                "    dialect: addon_v1\n"
                "    settings:\n" + CEC_SETTINGS
            )
        )
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "document_glob" in err
    assert str(device.cec) in err
    # Rejected before Device contact: nothing stopped and nothing written.
    assert device.effects == []
    assert not device.guisettings.exists()


def test_a_document_stating_neither_is_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        device.profile_body(
            extra="  - dialect: addon_v1\n    settings:\n" + CEC_SETTINGS
        )
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "exactly one of document and document_glob" in err
    assert device.effects == []
    assert not device.guisettings.exists()


def test_a_wildcard_inside_a_document_path_is_a_filename(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """A `document` is always literal. Treating this one as a pattern would
    match the adapter's real document and write the wrong file."""
    literal = device.peripheral_data / "cec_*.xml"
    write_document(literal, CEC_ON_DEVICE)
    write_document(device.cec, CEC_ON_DEVICE)
    device.write_profile(
        device.profile_body(extra=document_block(literal, "addon_v1", CEC_SETTINGS))
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert attribute_values(literal)["activate_source"] == "0"
    assert device.cec.read_text(encoding="utf-8") == CEC_ON_DEVICE


def test_a_glob_matching_one_document_resolves_to_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(with_cec(device))
    write_document(device.cec, CEC_ON_DEVICE)
    # A neighbour the pattern does not match, so the match is the pattern's
    # and not merely the only file in the directory.
    write_document(device.peripheral_data / "joystick_Gamepad.xml", CEC_ON_DEVICE)

    assert reconcile("plan", "--room", "theater") == 0

    # The Plan names the document it resolved to, never the pattern.
    out = capsys.readouterr().out
    assert f"update {device.cec}#activate_source: 1 -> 0" in out
    assert (
        f"create {device.cec}#standby_pc_on_tv_standby: (unset) -> 36028 "
        "(cec_tv_off_action of ignore)"
    ) in out

    assert reconcile("apply", "--room", "theater") == 0

    assert attribute_values(device.cec) == {
        "activate_source": "0",
        "device_name": "Kodi",
        "standby_pc_on_tv_standby": "36028",
    }
    assert device.effects == ["stop kodi.service", "start kodi.service"]


def test_a_glob_matching_nothing_is_an_error_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Device Kodi has never run on has no peripheral document at all. The
    Run refuses rather than creating one for an adapter it never saw."""
    device.write_profile(with_cec(device))

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert cec_glob(device) in err
    assert "nothing" in err
    # Raised while resolving, before any write and before the Kodi stop.
    assert device.effects == []
    assert not device.guisettings.exists()
    assert not device.peripheral_data.exists()


def test_a_glob_matching_more_than_one_document_names_every_match(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A changed television or HDMI path leaves the old document beside the
    new one. Picking either writes a power policy for absent hardware."""
    device.write_profile(with_cec(device))
    write_document(device.cec, CEC_ON_DEVICE)
    stale = device.peripheral_data / "cec_Pulse_Eight.xml"
    write_document(stale, CEC_ON_DEVICE)

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert cec_glob(device) in err
    assert "cec_CEC_Adapter.xml" in err
    assert "cec_Pulse_Eight.xml" in err
    assert device.effects == []
    assert device.cec.read_text(encoding="utf-8") == CEC_ON_DEVICE
    assert stale.read_text(encoding="utf-8") == CEC_ON_DEVICE
    # The refusal comes before the whole Run's first write, not just this
    # document's: guisettings.xml is declared ahead of it and is untouched.
    assert not device.guisettings.exists()


def test_a_value_outside_the_cec_transform_domain_names_the_domain(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`ignore` is the whole domain: the shell validates the same rule as a
    check, and passing anything else through writes a value Kodi discards."""
    device.write_profile(
        with_cec(
            device,
            "      - setting: standby_pc_on_tv_standby\n"
            "        value: shutdown\n"
            "        transform: cec_tv_off_action\n",
        )
    )
    write_document(device.cec, CEC_ON_DEVICE)

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "cec_tv_off_action" in err
    assert "shutdown" in err
    assert "ignore" in err
    assert device.effects == []


def shipped_cec_document() -> dict[str, Any]:
    """The CEC Settings Document the committed Profile declares."""

    documents = shipped_profile()["settings_documents"]
    matching = [
        document
        for document in documents
        if document.get("document_glob") == CEC_GLOB_PATH
    ]
    assert len(matching) == 1
    single: dict[str, Any] = matching[0]
    return single


def test_the_shipped_profile_declares_the_five_cec_addresses() -> None:
    """The pattern is the bus prefix Kodi writes, deliberately narrower than
    the shell's `*CEC*.xml`, which matches on the adapter's name and so finds
    nothing for an adapter that calls itself anything else (ADR 0012)."""
    document = shipped_cec_document()

    assert "document" not in document
    assert document["dialect"] == "addon_v1"
    assert [
        (entry["setting"], entry["value"], entry.get("transform"))
        for entry in document["settings"]
    ] == [
        ("standby_pc_on_tv_standby", "ignore", "cec_tv_off_action"),
        ("activate_source", "0", None),
        ("wake_devices", "231", None),
        ("standby_devices", "231", None),
        ("standby_tv_on_pc_standby", "0", None),
    ]


def shipped_cec_block(device: FakeDevice) -> str:
    """The committed CEC document, re-pointed at the fake Device."""

    document = shipped_cec_document()
    return document_block(
        cec_glob(device),
        str(document["dialect"]),
        "".join(
            f"      - setting: {entry['setting']}\n"
            f'        value: "{entry["value"]}"\n'
            + (
                f"        transform: {entry['transform']}\n"
                if "transform" in entry
                else ""
            )
            for entry in document["settings"]
        ),
        "document_glob",
    )


def test_no_declared_cec_setting_plans_as_a_create(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The shell writes all five, so on a provisioned Device none may plan as
    a `create`: a create is a misread setting id, which writes a node Kodi
    ignores and still verifies as converged (ADR 0012)."""
    document = shipped_cec_document()
    device.write_profile(device.profile_body(extra=shipped_cec_block(device)))
    write_document(
        device.cec,
        "<settings>\n"
        + "".join(
            f'    <setting id="{entry["setting"]}" value="stale" />\n'
            for entry in document["settings"]
        )
        + "</settings>\n",
    )

    assert reconcile("plan", "--room", "theater") == 0

    reported = [
        line for line in capsys.readouterr().out.splitlines() if str(device.cec) in line
    ]
    assert len(reported) == len(document["settings"])
    assert all(line.startswith("update ") for line in reported)


def test_the_shipped_cec_policy_converges_and_then_plans_clean(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(device.profile_body(extra=shipped_cec_block(device)))
    write_document(device.cec, CEC_ON_DEVICE)

    assert reconcile("apply", "--room", "theater") == 0

    assert attribute_values(device.cec) == {
        "device_name": "Kodi",
        "standby_pc_on_tv_standby": "36028",
        "activate_source": "0",
        "wake_devices": "231",
        "standby_devices": "231",
        "standby_tv_on_pc_standby": "0",
    }
    capsys.readouterr()

    assert reconcile("plan", "--room", "theater") == 0

    assert "no changes" in capsys.readouterr().out


def test_a_nested_copy_does_not_survive_beside_the_canonical_node(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """`Peripheral::LoadPersistedSettings` reads only the direct children of
    the root, so a nested copy is a value Kodi never resolves. The shell hunts
    them down before writing and the Reconciler must leave the document in the
    same state."""
    device.write_profile(with_cec(device))
    write_document(
        device.cec,
        "<settings>\n"
        '    <setting id="activate_source" value="1" />\n'
        "    <category>\n"
        '        <setting id="activate_source" value="1" />\n'
        '        <setting id="standby_pc_on_tv_standby" value="13011" />\n'
        "    </category>\n"
        "</settings>\n",
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert attribute_values(device.cec) == {
        "activate_source": "0",
        "standby_pc_on_tv_standby": "36028",
    }
    # The nested copies are gone; the element that held them is Unmanaged
    # State and stays, emptied, exactly as the shell leaves it.
    root = ElementTree.parse(device.cec).getroot()
    assert [node.tag for node in root.iter("setting")] == ["setting", "setting"]
