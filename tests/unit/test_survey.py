"""`survey`: how the Device differs from the Profile.

It reports what a Run never mentions because no Resource owns it — documents
beside the ones the Profile declares, and settings inside the Settings
Documents it shares — and the declared settings the Device holds differently.
It mutates nothing, and refuses to read under a running Kodi, which rewrites
its documents from memory when it exits.

These tests drive the Reconciler through its public entry point only
(ADR 0011).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import (
    SSHD_CONF,
    FakeDevice,
    document_block,
    write_document,
)


@pytest.fixture
def stopped(device: FakeDevice, monkeypatch: pytest.MonkeyPatch) -> FakeDevice:
    """The fake Device, converged and with Kodi stopped."""

    monkeypatch.setenv("FAKE_DEVICE_KODI_STOPPED", "1")
    return device


def guisettings(*nodes: str) -> str:
    return '<settings version="2">\n' + "".join(nodes) + "</settings>\n"


def findings(out: str) -> list[str]:
    """The survey's block: every line between the header and the summary."""

    lines = out.splitlines()
    assert lines[0].startswith("device ugoos-theater")
    assert lines[-1].startswith("survey: ")
    return lines[1:-1]


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "systemctl.log"
    }


def converge(device: FakeDevice, reconcile: Callable[..., int]) -> None:
    assert reconcile("apply", "--room", "theater") == 0
    device.systemctl_log.unlink(missing_ok=True)


def test_a_converged_device_holding_nothing_else_reports_nothing(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    converge(stopped, reconcile)
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert findings(out) == []
    assert out.splitlines()[-1] == "survey: no findings"


def test_it_refuses_while_kodi_is_running_and_says_why(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    converge(device, reconcile)
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 1

    printed = capsys.readouterr()
    assert "kodi.service is active" in printed.err
    assert "rewrites" in printed.err
    assert "systemctl stop kodi" in printed.err
    assert "undeclared" not in printed.out


def test_it_names_the_documents_and_directories_beside_declared_ones(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    converge(stopped, reconcile)
    write_document(stopped.playlists_dir / "Stale.xsp", "<smartplaylist/>\n")
    write_document(stopped.userdata / "sources.xml", "<sources/>\n")
    write_document(stopped.userdata / "Thumbnails" / "0" / "a.jpg", "jpeg")
    write_document(stopped.userdata / "Thumbnails" / "1" / "b.jpg", "jpeg")
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    # `playlists/` holds a declared document, so it is walked rather than
    # named; `Thumbnails/` holds none, so it is one line however deep it is.
    assert findings(capsys.readouterr().out) == [
        f"undeclared directory: {stopped.userdata}/Thumbnails",
        f"undeclared document: {stopped.playlists_dir}/Stale.xsp",
        f"undeclared document: {stopped.userdata}/sources.xml",
    ]


def test_it_reports_an_undeclared_setting_and_not_one_at_kodis_default(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(
        stopped.guisettings,
        guisettings(
            '    <setting id="videolibrary.flattentvshows">1</setting>\n',
            '    <setting id="audiooutput.volumesteps">90</setting>\n',
            '    <setting id="audiooutput.passthrough" default="true">false'
            "</setting>\n",
            '    <setting id="lookandfeel.skin" default="true">skin.estuary'
            "</setting>\n",
        ),
    )
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    assert findings(capsys.readouterr().out) == [
        f"undeclared setting: {stopped.guisettings}#audiooutput.volumesteps = 90",
    ]


def test_a_declared_setting_is_matched_the_way_kodi_matches_it(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Kodi resolves a setting id without regard to case, and so does this."""

    write_document(
        stopped.guisettings,
        guisettings('    <setting id="VideoLibrary.FlattenTVShows">1</setting>\n'),
    )
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    assert findings(capsys.readouterr().out) == []


def test_a_declared_setting_the_device_holds_differently_states_both_sides(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(
        stopped.guisettings,
        guisettings('    <setting id="videolibrary.flattentvshows">2</setting>\n'),
    )
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    assert findings(capsys.readouterr().out) == [
        f"declared setting differs: {stopped.guisettings}#videolibrary.flattentvshows"
        ": Profile says 1, Device holds 2",
    ]


def test_a_declared_setting_the_device_does_not_hold_says_so(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(stopped.guisettings, guisettings())
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    assert findings(capsys.readouterr().out) == [
        f"declared setting differs: {stopped.guisettings}#videolibrary.flattentvshows"
        ": Profile says 1, Device holds (unset)",
    ]


def test_an_addon_v1_setting_is_read_from_its_value_attribute(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    converge(stopped, reconcile)
    stopped.write_profile(
        stopped.profile_body(
            extra=document_block(
                stopped.weather,
                "addon_v1",
                '      - setting: interval\n        value: "30"\n',
            )
        )
    )
    write_document(
        stopped.weather,
        "<settings>\n"
        '    <setting id="interval" value="30" />\n'
        '    <setting id="units" value="metric" />\n'
        '    <setting id="theme" value="dark" default="true" />\n'
        "</settings>\n",
    )
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    assert findings(capsys.readouterr().out) == [
        f"undeclared setting: {stopped.weather}#units = metric",
    ]


def test_a_json_document_reports_every_undeclared_value(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """JSON has no notion of a default, so nothing is filtered out."""

    converge(stopped, reconcile)
    stopped.write_profile(
        stopped.profile_body(
            extra=document_block(
                stopped.viewtypes,
                "json",
                '      - setting: library.movies\n        value: "500"\n',
            )
        )
    )
    write_document(
        stopped.viewtypes,
        '{"library": {"movies": "500", "tvshows": "502"}, "prefix": 1}\n',
    )
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    assert findings(capsys.readouterr().out) == [
        f"undeclared setting: {stopped.viewtypes}#library.tvshows = 502",
        f"undeclared setting: {stopped.viewtypes}#prefix = 1",
    ]


def test_a_shell_vars_document_reports_every_undeclared_key(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    stopped.write_profile(
        stopped.profile_body(
            extra=(
                f"  - document: {SSHD_CONF}\n"
                "    dialect: shell_vars\n"
                "    settings:\n"
                '      - setting: SSHD_DISABLE_PW_AUTH\n        value: "true"\n'
            )
        )
    )
    write_document(
        stopped.sshd_conf,
        'SSHD_DISABLE_PW_AUTH="true"\nSSH_ARGS=""\n',
    )
    converge(stopped, reconcile)
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    assert findings(capsys.readouterr().out) == [
        f"undeclared setting: {SSHD_CONF}#SSH_ARGS = ",
    ]


def test_a_named_value_that_differs_is_never_printed(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret, held = "s3cr3t-never-printed", "0ld-s3cr3t-never-printed"
    stopped.write_env(f"NEXTPVR_PIN='{secret}'\n")
    stopped.write_profile(
        stopped.profile_body(
            extra=document_block(
                stopped.nextpvr,
                "addon_v2",
                "      - setting: pin\n        from_env: NEXTPVR_PIN\n",
            )
        )
    )
    converge(stopped, reconcile)
    write_document(
        stopped.nextpvr,
        guisettings(f'    <setting id="pin">{held}</setting>\n'),
    )
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    printed = capsys.readouterr()
    assert findings(printed.out) == [
        f"declared setting differs: {stopped.nextpvr}#pin: named by NEXTPVR_PIN",
    ]
    assert secret not in printed.out
    assert held not in printed.out


def test_it_keeps_the_undeclared_addon_report(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    converge(stopped, reconcile)
    stopped.install_addon("script.example", enabled=None)
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0

    assert findings(capsys.readouterr().out) == [
        f"undeclared add-on: {stopped.addons}/script.example",
    ]


def test_it_writes_nothing_and_two_runs_read_identically(
    stopped: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    converge(stopped, reconcile)
    write_document(stopped.userdata / "sources.xml", "<sources/>\n")
    write_document(stopped.userdata / "Thumbnails" / "a.jpg", "jpeg")
    write_document(
        stopped.guisettings,
        guisettings(
            '    <setting id="videolibrary.flattentvshows">2</setting>\n',
            '    <setting id="b.second">2</setting>\n',
            '    <setting id="a.first">1</setting>\n',
        ),
    )
    stopped.install_addon("script.example", enabled=None)
    before = snapshot(stopped.root)
    capsys.readouterr()

    assert reconcile("survey", "--room", "theater") == 0
    first = capsys.readouterr().out
    assert reconcile("survey", "--room", "theater") == 0
    second = capsys.readouterr().out

    assert first == second
    assert findings(first) == sorted(findings(first))
    assert len(findings(first)) == 6
    assert first.splitlines()[-1] == "survey: 6 findings"
    assert snapshot(stopped.root) == before
    assert all(effect.startswith("is-active") for effect in stopped.effects)
