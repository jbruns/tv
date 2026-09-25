"""CoreELEC's own settings: `oe_settings.xml`, in the `coreelec` dialect.

`service.coreelec.settings` reads a value by module and tag name from
`<coreelec><settings><module><Setting>`, so the Profile addresses one as
`module.Setting`. The add-on reads them once as its service starts inside
Kodi, so a Change takes the Kodi stop like every other Settings Document.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from .conftest import FakeDevice, shipped_profile, write_document

OE_SETTINGS = (
    "/storage/.kodi/userdata/addon_data/service.coreelec.settings/oe_settings.xml"
)

# What a Device fresh from the first-boot wizard holds: no `updates` module.
FIRST_BOOT = """\
<?xml version="1.0" ?>
<coreelec>
\t<addon_config/>
\t<settings>
\t\t<system>
\t\t\t<wizard_completed>True</wizard_completed>
\t\t\t<hostname>ugoos-theater</hostname>
\t\t</system>
\t</settings>
</coreelec>
"""


def oe_settings(device: FakeDevice) -> Path:
    return (
        device.userdata / "addon_data" / "service.coreelec.settings" / "oe_settings.xml"
    )


def shipped_document() -> dict[str, Any]:
    return next(
        document
        for document in shipped_profile()["settings_documents"]
        if document.get("document") == OE_SETTINGS
    )


def declare_shipped(device: FakeDevice) -> dict[str, str]:
    document = shipped_document()
    declared = {entry["setting"]: entry["value"] for entry in document["settings"]}
    device.write_profile(
        device.profile_body(
            extra=f"  - document: {oe_settings(device)}\n"
            f"    dialect: {document['dialect']}\n"
            f'    mode: "{document["mode"]}"\n'
            "    settings:\n"
            + "".join(
                f'      - setting: {setting}\n        value: "{value}"\n'
                for setting, value in declared.items()
            )
        )
    )
    return declared


def held(document: Path) -> dict[str, str | None]:
    """Every `module.Setting` the add-on would read, as address to text."""
    settings = ElementTree.parse(document).getroot().find("settings")
    assert settings is not None
    return {
        f"{module.tag}.{node.tag}": node.text for module in settings for node in module
    }


def test_the_shipped_profile_turns_off_coreelec_updates_notices_and_stats() -> None:
    document = shipped_document()

    assert document["dialect"] == "coreelec"
    assert document["mode"] == "0644"
    assert {entry["setting"]: entry["value"] for entry in document["settings"]} == {
        "updates.AutoUpdate": "manual",
        "updates.UpdateNotify": "0",
        "updates.SubmitStats": "0",
    }


def test_the_settings_converge_under_the_kodi_stop_and_keep_the_rest(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare_shipped(device)
    write_document(oe_settings(device), FIRST_BOOT)

    assert reconcile("apply", "--room", "theater") == 0

    assert held(oe_settings(device)) == {
        "system.wizard_completed": "True",
        "system.hostname": "ugoos-theater",
        "updates.AutoUpdate": "manual",
        "updates.UpdateNotify": "0",
        "updates.SubmitStats": "0",
    }
    assert (
        ElementTree.parse(oe_settings(device)).getroot().find("addon_config")
        is not None
    )
    assert oe_settings(device).stat().st_mode & 0o777 == 0o644
    assert device.effects == ["stop kodi.service", "start kodi.service"]
    capsys.readouterr()

    assert reconcile("plan", "--room", "theater") == 0

    assert "no changes" in capsys.readouterr().out


def test_a_device_holding_other_values_plans_each_as_an_update(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declared = declare_shipped(device)
    write_document(
        oe_settings(device),
        "<coreelec>\n  <settings>\n    <updates>\n"
        "      <AutoUpdate>auto</AutoUpdate>\n"
        "      <UpdateNotify>1</UpdateNotify>\n"
        "      <SubmitStats>1</SubmitStats>\n"
        "    </updates>\n  </settings>\n</coreelec>\n",
    )

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    reported = [line for line in out.splitlines() if "oe_settings.xml#" in line]
    assert len(reported) == len(declared)
    assert all(line.startswith("update ") for line in reported)
    assert "#updates.AutoUpdate: auto -> manual" in out


def test_a_document_that_is_not_coreelecs_is_named_before_kodi_is_stopped(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare_shipped(device)
    write_document(oe_settings(device), '<settings version="2" />\n')

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert str(oe_settings(device)) in err
    assert "coreelec" in err
    assert device.effects == []
