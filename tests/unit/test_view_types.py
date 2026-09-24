"""Arctic Fuse's view types, and the rebuild that makes them take effect.

`script.skinvariables` keeps the view types as JSON and compiles them into an
XML include inside the skin. Two addresses are declared inside that JSON and
the rest of it is Unmanaged State, exactly as for the XML Settings Documents —
the difference is the parser, which is what the `json` dialect names.

Getting the compile to happen needs no conversation with Kodi. The Run writes
the skin's own trigger stub over the compiled include and restarts Kodi, which
it was taking anyway for the Settings Documents (ADR 0015).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from .conftest import FakeDevice, shipped_profile

COMPILED = (
    "/storage/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml"
)

# What the skin's compiled include holds once the add-on has built it.
REBUILT = '<includes>\n    <include name="View_509" />\n</includes>\n'

# The stub the Run authors. The skin ships the compiled include untracked, so
# there is no pristine copy to restore; `Includes_Fallbacks.xml` defines
# `Action_BuildViews` as an empty include, and this is what overrides it.
# Emptying the file would resolve to the fallback and rebuild nothing.
STUB = """\
<?xml version="1.0" encoding="UTF-8"?>
<includes>
    <include name="Action_BuildViews">
        <onload>RunScript(script.skinvariables,action=buildviews)</onload>
    </include>
</includes>
"""


def viewtypes_block(document: Path, compiles_to: Path | None = None) -> str:
    """The view types document, declared as `json` and addressed by path."""

    artifact = f"    compiles_to: {compiles_to}\n" if compiles_to is not None else ""
    return (
        f"  - document: {document}\n"
        "    dialect: json\n"
        f"{artifact}"
        "    settings:\n"
        '      - setting: library.seasons\n        value: "509"\n'
        '      - setting: library.episodes\n        value: "549"\n'
    )


def declare(device: FakeDevice, *, rebuild: bool = False) -> None:
    device.write_profile(
        device.profile_body(
            extra=viewtypes_block(
                device.viewtypes, device.compiled if rebuild else None
            )
        )
    )


def arm_the_skin(device: FakeDevice, monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes starting Kodi compile the include, the way the skin does."""

    monkeypatch.setenv("FAKE_DEVICE_COMPILED", str(device.compiled))
    monkeypatch.setenv("FAKE_DEVICE_COMPILED_BODY", REBUILT)


def held(device: FakeDevice) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(device.viewtypes.read_text(encoding="utf-8"))
    return document


def test_a_dotted_address_lands_and_a_second_plan_is_empty(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device)

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert held(device)["library"] == {"seasons": "509", "episodes": "549"}

    assert reconcile("plan", "--room", "theater") == 0
    assert "no changes" in capsys.readouterr().out


def test_every_undeclared_key_is_left_exactly_as_found(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.viewtypes.parent.mkdir(parents=True)
    device.viewtypes.write_text(
        json.dumps(
            {
                "library": {"seasons": "500", "movies": "52", "tvshows": "54"},
                "plugin": {"default": "50"},
            },
            indent=4,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    declare(device)

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    document = held(device)
    assert document["library"]["seasons"] == "509"
    assert document["library"]["episodes"] == "549"
    assert document["library"]["movies"] == "52"
    assert document["library"]["tvshows"] == "54"
    assert document["plugin"] == {"default": "50"}


def test_both_addresses_survive_a_rebuilds_defaults_merge(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`update_xml` merges the skin's defaults *under* what it finds.

    The add-on rewrites this whole document on every build, adding a default
    for every content type it knows. Our two keys win that merge by design, so
    a Run after a rebuild has nothing to do.
    """

    declare(device)
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    rebuilt = held(device)
    rebuilt["library"].update({"movies": "50", "tvshows": "50", "musicvideos": "50"})
    rebuilt["videos"] = {"default": "50"}
    device.viewtypes.write_text(
        json.dumps(rebuilt, indent=4, sort_keys=True) + "\n", encoding="utf-8"
    )

    assert reconcile("plan", "--room", "theater") == 0
    assert "no changes" in capsys.readouterr().out


def test_a_document_that_is_not_json_fails_naming_itself(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Never a plausible empty parse that plans every address as a create."""

    device.viewtypes.parent.mkdir(parents=True)
    device.viewtypes.write_text('{"library": {"seasons": "50', encoding="utf-8")
    declare(device)

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert str(device.viewtypes) in err
    assert "create" not in capsys.readouterr().out
    assert device.effects == []


def test_a_document_whose_top_level_is_not_an_object_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.viewtypes.parent.mkdir(parents=True)
    device.viewtypes.write_text('["seasons"]', encoding="utf-8")
    declare(device)

    assert reconcile("apply", "--room", "theater") == 1

    assert "list" in capsys.readouterr().err


def test_an_address_landing_on_a_branch_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Overwriting it would discard whatever the add-on put there."""

    device.viewtypes.parent.mkdir(parents=True)
    device.viewtypes.write_text(
        '{"library": {"seasons": {"id": "509"}}}', encoding="utf-8"
    )
    declare(device)

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "library.seasons" in err
    assert device.effects == []


def test_clearing_a_json_address_removes_the_key(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """JSON has no empty node, and `null` is a value rather than the lack of one."""

    device.viewtypes.parent.mkdir(parents=True)
    device.viewtypes.write_text(
        '{"library": {"seasons": "500", "movies": "52"}}', encoding="utf-8"
    )
    device.write_profile(
        device.profile_body(
            extra=(
                f"  - document: {device.viewtypes}\n"
                "    dialect: json\n"
                "    settings:\n"
                "      - setting: library.seasons\n        unset: true\n"
            )
        )
    )

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert held(device)["library"] == {"movies": "52"}


def test_clearing_an_absent_branch_adds_nothing(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Cleared Address whose branch is absent is already clear.

    Building the branch to pop nothing out of it would write keys the
    document did not have, which is the one thing the dialect promises not
    to do.
    """

    device.viewtypes.parent.mkdir(parents=True)
    device.viewtypes.write_text('{"tvshows": {"seasons": "500"}}', encoding="utf-8")
    device.write_profile(
        device.profile_body(
            extra=(
                f"  - document: {device.viewtypes}\n"
                "    dialect: json\n"
                "    settings:\n"
                "      - setting: library.seasons\n        unset: true\n"
                "      - setting: tvshows.seasons\n        value: '509'\n"
            )
        )
    )

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert held(device) == {"tvshows": {"seasons": "509"}}


def test_a_change_arms_the_stub_and_the_restart_fires_the_rebuild(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device, rebuild=True)
    arm_the_skin(device, monkeypatch)

    assert reconcile("apply", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert f"arming {device.compiled}" in out
    assert f"rebuilt {device.compiled}" in out
    # The stub is written while Kodi is down and the restart is what fires it:
    # no JSON-RPC and no EventServer.
    assert device.effects == ["stop kodi.service", "start kodi.service"]
    assert device.compiled.read_text(encoding="utf-8") == REBUILT


def test_the_stub_is_the_skins_own_trigger_and_a_partial_compile_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Three scripted reads: the stub, a file caught mid-write, the result.

    The Run wrote the stub, so "changed from what we wrote" is an edge rather
    than a guess, and the parse is what catches the partial write. Neither of
    the first two satisfies the wait.
    """

    scripted = tmp_path / "compiled"
    scripted.mkdir()
    (scripted / "1").write_text(STUB, encoding="utf-8")
    (scripted / "2").write_text("<includes>\n    <include name=", encoding="utf-8")
    (scripted / "last").write_text(REBUILT, encoding="utf-8")
    monkeypatch.setenv("FAKE_DEVICE_SCRIPTED_PATH", str(device.compiled))
    monkeypatch.setenv("FAKE_DEVICE_SCRIPTED_DIR", str(scripted))
    monkeypatch.setenv("FAKE_DEVICE_SCRIPTED_READS", str(tmp_path / "reads"))
    declare(device, rebuild=True)

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    # Nothing overwrote the compiled include here, so what stayed on the
    # Device is exactly what the Run authored.
    assert device.compiled.read_text(encoding="utf-8") == STUB
    assert "Action_BuildViews" in STUB
    assert int((tmp_path / "reads").read_text(encoding="utf-8")) >= 3


def test_nothing_is_armed_when_the_source_already_agrees(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The compiled artifact is stale only when its source changed."""

    declare(device, rebuild=True)
    arm_the_skin(device, monkeypatch)
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    device.guisettings.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<settings version="2" />\n',
        encoding="utf-8",
    )

    assert reconcile("apply", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert "videolibrary.flattentvshows" in out
    assert "arming" not in out


def test_the_shipped_profile_declares_both_view_types_and_the_artifact() -> None:
    documents = shipped_profile()["settings_documents"]
    viewtypes = [
        document
        for document in documents
        if document.get("dialect") == "json"
        and document["document"].endswith("skin.arctic.fuse.3-viewtypes.json")
    ]
    assert len(viewtypes) == 1
    assert viewtypes[0]["compiles_to"] == COMPILED
    assert {
        setting["setting"]: setting["value"] for setting in viewtypes[0]["settings"]
    } == {"library.seasons": "509", "library.episodes": "549"}
