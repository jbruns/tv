"""Many Settings Documents, each in its declared dialect.

`guisettings.xml` is one Settings Document among several. Every remaining
cohort of Kodi state has the same shape — a document holding many State
Addresses, each owned independently — and differs only in how it is
serialised. Two add-on dialects join the Kodi core one here: `addon_v2`
carries a value as element text, `addon_v1` carries it in a `value`
attribute.

The dialect is declared, never sniffed. A document that does not read as its
declared dialect fails naming itself, because reading it in the wrong dialect
would report every declared address as unset and plan every one of them as a
`create`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from .conftest import ROOM_HEADER, FakeDevice, document_block

WEATHER_SETTINGS = """\
      - setting: ha_sun_entity_id
        value: sun.sun
      - setting: ha_weather_forecast_entity_id
        value: weather.openweathermap
"""

NEXTPVR_SETTINGS = """\
      - setting: hostprotocol
        value: https
      - setting: port
        value: "443"
"""

# What Kodi leaves on the Device for an add-on whose settings definition
# carries no version attribute: no version on the root, value as an attribute.
WEATHER_ON_DEVICE = """\
<settings>
    <setting id="ha_key" value="a-token" />
    <setting id="ha_sun_entity_id" value="sun.wrong" />
</settings>
"""

NEXTPVR_ON_DEVICE = """\
<settings version="2">
    <setting id="host">nextpvr.example</setting>
    <setting id="hostprotocol">http</setting>
</settings>
"""

TMDB_ON_DEVICE = """\
<settings version="2">
    <setting id="mdblist_apikey">an-mdblist-key</setting>
    <setting id="omdb_apikey">a-stale-key</setting>
</settings>
"""


def text_values(document: Path) -> dict[str, str | None]:
    """Every setting a text-dialect document holds, as id to element text."""
    root = ElementTree.parse(document).getroot()
    return {node.get("id") or "": node.text for node in root.findall("setting")}


def attribute_values(document: Path) -> dict[str, str | None]:
    """Every setting an `addon_v1` document holds, as id to value attribute."""
    root = ElementTree.parse(document).getroot()
    return {node.get("id") or "": node.get("value") for node in root.findall("setting")}


def write(document: Path, body: str) -> None:
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(body, encoding="utf-8")


def with_addons(device: FakeDevice) -> str:
    """The Profile, declaring guisettings.xml and both add-on documents."""
    return device.profile_body(
        extra=document_block(device.weather, "addon_v1", WEATHER_SETTINGS)
        + document_block(device.nextpvr, "addon_v2", NEXTPVR_SETTINGS)
    )


def test_an_unknown_dialect_is_rejected_naming_the_document(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        device.profile_body(
            extra=document_block(device.weather, "addon_v3", WEATHER_SETTINGS)
        )
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "addon_v3" in err
    assert str(device.weather) in err
    # Rejected before Device contact: nothing was stopped and nothing written.
    assert device.effects == []
    assert not device.guisettings.exists()


def test_the_addon_v1_value_is_written_as_an_attribute(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_profile(with_addons(device))
    write(device.weather, WEATHER_ON_DEVICE)

    assert reconcile("apply", "--room", "theater") == 0

    assert attribute_values(device.weather) == {
        # Unmanaged State, including the credential the shell still owns.
        "ha_key": "a-token",
        "ha_sun_entity_id": "sun.sun",
        "ha_weather_forecast_entity_id": "weather.openweathermap",
    }
    # An attribute-form node carries no element text at all.
    assert set(text_values(device.weather).values()) == {None}


def test_the_addon_v2_value_is_written_as_element_text(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_profile(with_addons(device))
    write(device.nextpvr, NEXTPVR_ON_DEVICE)

    assert reconcile("apply", "--room", "theater") == 0

    assert text_values(device.nextpvr) == {
        "host": "nextpvr.example",
        "hostprotocol": "https",
        "port": "443",
    }


def test_every_document_converges_under_one_kodi_stop(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stop belongs to the Resource Type, not to a document (ADR 0013),
    and the Run takes it once however many documents it writes."""
    device.write_profile(with_addons(device))
    write(device.weather, WEATHER_ON_DEVICE)
    write(device.nextpvr, NEXTPVR_ON_DEVICE)

    assert reconcile("apply", "--room", "theater") == 0

    assert device.effects == ["stop kodi.service", "start kodi.service"]
    capsys.readouterr()

    assert reconcile("plan", "--room", "theater") == 0

    assert "no changes" in capsys.readouterr().out


def test_the_plan_names_the_document_of_every_change(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(with_addons(device))
    write(device.weather, WEATHER_ON_DEVICE)
    write(device.nextpvr, NEXTPVR_ON_DEVICE)

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert f"update {device.weather}#ha_sun_entity_id: sun.wrong -> sun.sun" in out
    assert (
        f"create {device.weather}#ha_weather_forecast_entity_id: (unset) -> "
        "weather.openweathermap"
    ) in out
    assert f"update {device.nextpvr}#hostprotocol: http -> https" in out
    assert f"create {device.nextpvr}#port: (unset) -> 443" in out
    assert device.effects == []


def test_a_document_read_in_the_wrong_dialect_is_an_error_not_an_empty_parse(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Declaring `addon_v2` for a document Kodi writes in the flat form would
    otherwise read every declared address as unset, plan each as a `create`,
    and write a node Kodi never reads."""
    device.write_profile(
        device.profile_body(
            extra=document_block(device.weather, "addon_v2", WEATHER_SETTINGS)
        )
    )
    write(device.weather, WEATHER_ON_DEVICE)

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert str(device.weather) in err
    assert "addon_v1" in err
    assert device.effects == []
    assert device.weather.read_text(encoding="utf-8") == WEATHER_ON_DEVICE


def test_the_other_way_round_is_an_error_too(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        device.profile_body(
            extra=document_block(device.nextpvr, "addon_v1", NEXTPVR_SETTINGS)
        )
    )
    write(device.nextpvr, NEXTPVR_ON_DEVICE)

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert str(device.nextpvr) in err
    assert "addon_v2" in err
    assert device.effects == []


def test_a_document_the_device_lacks_is_created_in_its_declared_dialect(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_profile(with_addons(device))

    assert reconcile("apply", "--room", "theater") == 0

    weather = ElementTree.parse(device.weather).getroot()
    assert weather.get("version") is None
    assert attribute_values(device.weather)["ha_sun_entity_id"] == "sun.sun"
    nextpvr = ElementTree.parse(device.nextpvr).getroot()
    assert nextpvr.get("version") == "2"
    assert text_values(device.nextpvr)["port"] == "443"


def test_every_document_is_re_read_after_the_stop(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An add-on document can look converged while Kodi runs and be reverted
    by Kodi's own exit write, exactly as guisettings.xml can."""
    device.write_profile(with_addons(device))
    write(
        device.weather,
        '<settings>\n    <setting id="ha_sun_entity_id" value="sun.sun" />\n'
        "</settings>\n",
    )
    write(device.nextpvr, NEXTPVR_ON_DEVICE)
    memory = tmp_path / "kodi-memory.xml"
    memory.write_text(
        '<settings>\n    <setting id="ha_sun_entity_id" value="sun.wrong" />\n'
        "</settings>\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_DEVICE_KODI_MEMORY", str(memory))
    monkeypatch.setenv("FAKE_DEVICE_KODI_DOCUMENT", str(device.weather))

    assert reconcile("apply", "--room", "theater") == 0

    assert attribute_values(device.weather) == {
        "ha_sun_entity_id": "sun.sun",
        "ha_weather_forecast_entity_id": "weather.openweathermap",
    }


def test_kodi_comes_back_when_one_document_cannot_be_written(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fail Forward across documents: the Run reports the document it could
    not write and still starts Kodi again."""
    device.write_profile(with_addons(device))
    monkeypatch.setenv("FAKE_DEVICE_CHMOD_REFUSES", "weather.ha")

    assert reconcile("apply", "--room", "theater") == 1

    assert device.effects == ["stop kodi.service", "start kodi.service"]
    # The document declared before the failing one still landed.
    assert device.guisettings.exists()
    out = capsys.readouterr().out
    assert f"not applied {device.weather}#ha_sun_entity_id" in out


def test_a_room_overlay_adds_a_setting_to_a_document_the_profile_declares(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_profile(with_addons(device))
    device.write_room(
        ROOM_HEADER
        + "settings_documents:\n"
        + document_block(
            device.nextpvr,
            "addon_v2",
            "      - setting: kodi_addon_instance_name\n        value: Theater\n",
        )
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert text_values(device.nextpvr) == {
        "hostprotocol": "https",
        "port": "443",
        "kodi_addon_instance_name": "Theater",
    }


def test_a_collision_inside_one_document_names_the_document_and_the_setting(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(with_addons(device))
    device.write_room(
        ROOM_HEADER
        + "settings_documents:\n"
        + document_block(
            device.nextpvr,
            "addon_v2",
            "      - setting: hostprotocol\n        value: http\n",
        )
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "hostprotocol" in err
    assert str(device.nextpvr) in err
    assert device.effects == []


def test_the_same_setting_in_two_documents_is_not_a_collision(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """A State Address is the document plus the setting, so `port` in two
    documents is two addresses."""
    device.write_profile(
        device.profile_body(
            extra=document_block(
                device.weather, "addon_v1", "      - setting: port\n        value: 1\n"
            )
            + document_block(
                device.nextpvr, "addon_v2", "      - setting: port\n        value: 2\n"
            )
        )
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert attribute_values(device.weather)["port"] == "1"
    assert text_values(device.nextpvr)["port"] == "2"


def test_two_sides_disagreeing_on_a_dialect_are_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One path is one file, so the two sides cannot describe it differently."""
    device.write_profile(with_addons(device))
    device.write_room(
        ROOM_HEADER
        + "settings_documents:\n"
        + document_block(
            device.nextpvr,
            "addon_v1",
            "      - setting: kodi_addon_instance_name\n        value: Theater\n",
        )
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert str(device.nextpvr) in err
    assert "addon_v1" in err
    assert "addon_v2" in err


WEATHER_PATH = "/storage/.kodi/userdata/addon_data/weather.ha/settings.xml"
NEXTPVR_PATH = "/storage/.kodi/userdata/addon_data/pvr.nextpvr/instance-settings-1.xml"
TMDB_PATH = (
    "/storage/.kodi/userdata/addon_data/plugin.video.themoviedb.helper/settings.xml"
)

# What `.env` holds for every key the committed Profile names. The values are
# this test's, not the fleet's; what matters is that the Profile carries none
# of them.
SHIPPED_ENV = """\
HOME_ASSISTANT_URL='https://home-assistant.example'
HOME_ASSISTANT_TOKEN='a-long-lived-token'
NEXTPVR_HOST='nextpvr.example'
NEXTPVR_PIN='0000'
MDBLIST_API_KEY='an-mdblist-key'
OMDB_API_KEY='an-omdb-key'
"""


def shipped_addon_documents() -> dict[str, dict[str, Any]]:
    """The add-on Settings Documents the committed Profile declares."""
    profile = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "shared"
        / "ugoos-am6b-plus"
        / "coreelec-21.3"
        / "profile.yaml"
    )
    documents = yaml.safe_load(profile.read_text(encoding="utf-8"))[
        "settings_documents"
    ]
    return {
        document["document"]: document
        for document in documents
        if document["dialect"] != "guisettings"
    }


def profile_extra(device: FakeDevice, documents: dict[str, dict[str, Any]]) -> str:
    """The committed add-on documents, re-pointed at the fake Device."""
    local = {
        WEATHER_PATH: device.weather,
        NEXTPVR_PATH: device.nextpvr,
        TMDB_PATH: device.tmdb,
    }
    return "".join(
        document_block(
            local[path],
            str(document["dialect"]),
            "".join(
                f"      - setting: {entry['setting']}\n" + declaration(entry)
                for entry in document["settings"]
            ),
        )
        for path, document in documents.items()
    )


def declaration(entry: dict[str, Any]) -> str:
    """How the committed Profile states one setting's value."""
    if "from_env" in entry:
        return f"        from_env: {entry['from_env']}\n"
    return f'        value: "{entry["value"]}"\n'


def test_the_shipped_profile_declares_the_three_addon_documents() -> None:
    """Every `SVC` address in the three add-on documents. Six of them name a
    value in `.env` rather than holding one: four credentials and the two
    endpoints those credentials authenticate to (ADR 0014)."""
    documents = shipped_addon_documents()
    declared = {
        path: (
            document["dialect"],
            [entry["setting"] for entry in document["settings"]],
        )
        for path, document in documents.items()
    }
    assert declared == {
        WEATHER_PATH: (
            "addon_v1",
            [
                "ha_server",
                "ha_key",
                "ha_weather_forecast_entity_id",
                "ha_sun_entity_id",
            ],
        ),
        NEXTPVR_PATH: (
            "addon_v2",
            [
                "host",
                "hostprotocol",
                "port",
                "pin",
                "kodi_addon_instance_enabled",
                "kodi_addon_instance_name",
            ],
        ),
        TMDB_PATH: ("addon_v2", ["mdblist_apikey", "omdb_apikey"]),
    }
    named = {
        entry["setting"]: entry.get("from_env")
        for document in documents.values()
        for entry in document["settings"]
        if "from_env" in entry
    }
    assert named == {
        "ha_server": "HOME_ASSISTANT_URL",
        "ha_key": "HOME_ASSISTANT_TOKEN",
        "host": "NEXTPVR_HOST",
        "pin": "NEXTPVR_PIN",
        "mdblist_apikey": "MDBLIST_API_KEY",
        "omdb_apikey": "OMDB_API_KEY",
    }
    # A named setting carries the key and nothing else.
    assert all(
        "value" not in entry
        for document in documents.values()
        for entry in document["settings"]
        if "from_env" in entry
    )


def test_no_declared_addon_setting_plans_as_a_create(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The shell writes all of them, so on a provisioned Device none may plan
    as a `create`: a create is a misread setting id or a document read in the
    wrong dialect, either of which writes a node Kodi ignores and still
    verifies as converged (ADR 0012)."""
    documents = shipped_addon_documents()
    device.write_env(SHIPPED_ENV)
    device.write_profile(device.profile_body(extra=profile_extra(device, documents)))
    write(
        device.weather,
        "<settings>\n"
        + "".join(
            f'    <setting id="{entry["setting"]}" value="stale" />\n'
            for entry in documents[WEATHER_PATH]["settings"]
        )
        + "</settings>\n",
    )
    write(
        device.nextpvr,
        '<settings version="2">\n'
        + "".join(
            f'    <setting id="{entry["setting"]}">stale</setting>\n'
            for entry in documents[NEXTPVR_PATH]["settings"]
        )
        + "</settings>\n",
    )
    write(
        device.tmdb,
        '<settings version="2">\n'
        + "".join(
            f'    <setting id="{entry["setting"]}">stale</setting>\n'
            for entry in documents[TMDB_PATH]["settings"]
        )
        + "</settings>\n",
    )

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    reported = [
        line
        for line in out.splitlines()
        if str(device.weather) in line
        or str(device.nextpvr) in line
        or str(device.tmdb) in line
    ]
    assert len(reported) == sum(
        len(document["settings"]) for document in documents.values()
    )
    assert all(line.startswith("update ") for line in reported)


def test_the_shipped_addon_settings_converge_and_then_plan_clean(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    documents = shipped_addon_documents()
    device.write_env(SHIPPED_ENV)
    device.write_profile(device.profile_body(extra=profile_extra(device, documents)))
    write(device.weather, WEATHER_ON_DEVICE)
    write(device.nextpvr, NEXTPVR_ON_DEVICE)
    write(device.tmdb, TMDB_ON_DEVICE)

    assert reconcile("apply", "--room", "theater") == 0

    assert attribute_values(device.weather)["ha_sun_entity_id"] == "sun.sun"
    assert text_values(device.nextpvr)["kodi_addon_instance_enabled"] == "true"
    # A named value reaches the Device and nowhere else.
    assert text_values(device.tmdb)["omdb_apikey"] == "an-omdb-key"
    assert device.effects == ["stop kodi.service", "start kodi.service"]
    printed = capsys.readouterr()
    assert "an-omdb-key" not in printed.out
    assert "a-long-lived-token" not in printed.out

    assert reconcile("plan", "--room", "theater") == 0

    assert "no changes" in capsys.readouterr().out
