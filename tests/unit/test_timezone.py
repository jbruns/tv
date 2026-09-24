"""The timezone: one Profile Constant, two State Addresses, one Effect.

`/storage/.cache/timezone` is a `KEY=value` document the operating system
reads, so it is a Settings Document in a dialect that is not Kodi's. Writing
it leaves `/var/run/localtime` stale, and `tz-data.service` is the oneshot
that relinks it — an Effect taken only when the document changes, and
verified by reading the link it wrote.

`locale.timezone` in `guisettings.xml` records the same fact for Kodi. Both
take the `timezone` Profile Constant, so the Device cannot end up showing one
zone in Kodi and another in the operating system.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from .conftest import TIMEZONE_CACHE, FakeDevice, shipped_profile

ZONE = "America/Los_Angeles"


def timezone_block(mode: str = "0644") -> str:
    return (
        f"  - document: {TIMEZONE_CACHE}\n"
        "    dialect: shell_vars\n"
        f'    mode: "{mode}"\n'
        "    settings:\n"
        "      - setting: TIMEZONE\n"
        "        from_profile: timezone\n"
    )


def declare(device: FakeDevice, mode: str = "0644") -> None:
    device.write_profile(device.profile_body(extra=timezone_block(mode)))


def arm_tz_data(device: FakeDevice, monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes starting `tz-data.service` relink, the way the unit does."""

    monkeypatch.setenv("FAKE_DEVICE_LOCALTIME", str(device.localtime))
    monkeypatch.setenv("FAKE_DEVICE_TIMEZONE_DOCUMENT", str(device.timezone))


def test_the_zone_lands_and_the_link_is_verified(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device)
    arm_tz_data(device, monkeypatch)

    assert reconcile("apply", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert device.timezone.read_text(encoding="utf-8") == f"TIMEZONE={ZONE}\n"
    assert device.localtime.readlink().as_posix() == f"/usr/share/zoneinfo/{ZONE}"
    assert f"/var/run/localtime names {ZONE}" in out
    assert "verification: converged" in out


def test_the_effect_is_taken_only_when_the_document_changes(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device)
    arm_tz_data(device, monkeypatch)

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()
    assert "stop tz-data.service" in device.effects
    device.systemctl_log.unlink()

    # Nothing left to change here, and the Kodi document converged too.
    assert reconcile("apply", "--room", "theater") == 0
    assert "no changes" in capsys.readouterr().out
    assert device.effects == []


def test_a_run_that_changes_only_kodi_leaves_tz_data_alone(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device)
    arm_tz_data(device, monkeypatch)
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()
    device.systemctl_log.unlink()

    device.guisettings.write_text(
        '<settings version="2">\n'
        '    <setting id="videolibrary.flattentvshows">0</setting>\n'
        "</settings>\n",
        encoding="utf-8",
    )

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()
    assert device.effects == ["stop kodi.service", "start kodi.service"]


def test_the_declared_mode_is_what_the_document_is_written_with(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The declared mode is applied to the written document."""

    declare(device)
    arm_tz_data(device, monkeypatch)

    assert reconcile("apply", "--room", "theater") == 0

    assert device.timezone.stat().st_mode & 0o777 == 0o644
    # A Kodi document keeps the mode it has always been written with.
    assert device.guisettings.stat().st_mode & 0o777 == 0o600


def test_every_undeclared_key_line_and_comment_survives(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declare(device)
    arm_tz_data(device, monkeypatch)
    device.timezone.parent.mkdir(parents=True, exist_ok=True)
    device.timezone.write_text(
        "# written by something else\nTIMEZONE=Europe/Berlin\nOTHER=kept\n",
        encoding="utf-8",
    )

    assert reconcile("apply", "--room", "theater") == 0

    assert device.timezone.read_text(encoding="utf-8") == (
        f"# written by something else\nTIMEZONE={ZONE}\nOTHER=kept\n"
    )


def test_a_document_that_is_not_key_value_is_refused_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device)
    device.timezone.parent.mkdir(parents=True, exist_ok=True)
    device.timezone.write_text('<settings version="2" />\n', encoding="utf-8")

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert TIMEZONE_CACHE in err
    assert "shell_vars" in err
    assert device.effects == []


def test_the_run_fails_when_the_link_does_not_name_the_declared_zone(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare(device)
    arm_tz_data(device, monkeypatch)
    monkeypatch.setenv("FAKE_DEVICE_TZ_DATA_WRONG", "1")

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "/var/run/localtime" in err
    assert ZONE in err


def test_both_addresses_resolve_from_one_constant(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One statement of the zone, two records of it on the Device."""

    device.write_profile(
        device.profile_body(extra=timezone_block()).replace(
            "  timezone: America/Los_Angeles\n", "  timezone: Europe/Berlin\n"
        )
    )
    # The Room Overlay takes the constant too: it is the Profile's statement,
    # not the Profile file's scope.
    device.write_room_settings("- setting: locale.timezone\n  from_profile: timezone\n")
    arm_tz_data(device, monkeypatch)

    assert reconcile("apply", "--room", "theater") == 0

    from .conftest import text_values

    assert text_values(device.guisettings)["locale.timezone"] == "Europe/Berlin"
    assert device.timezone.read_text(encoding="utf-8") == "TIMEZONE=Europe/Berlin\n"


def test_a_from_profile_naming_an_undeclared_constant_names_both(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        device.profile_body(
            extra=timezone_block().replace(
                "from_profile: timezone", "from_profile: timezome"
            )
        )
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "TIMEZONE" in err
    assert "timezome" in err
    # Rejected while the configuration is read, before the Device is dialled.
    assert device.effects == []


def test_a_setting_stating_a_value_and_a_constant_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        device.profile_body(
            extra=timezone_block().replace(
                "        from_profile: timezone\n",
                "        from_profile: timezone\n        value: UTC\n",
            )
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "exactly one of value, from_env, from_profile and unset" in err


def test_no_document_may_declare_its_effect(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ADR 0013: which unit a document disturbs belongs to the Resource Type.

    A document that could state its unit could omit it, and an omitted unit
    is the one mistake nothing catches.
    """

    device.write_profile(
        device.profile_body(
            extra=timezone_block().replace(
                "    dialect: shell_vars\n",
                "    dialect: shell_vars\n    effect: tz-data.service\n",
            )
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "effect" in err


def test_a_value_is_never_scanned_for_interpolation(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    """Kodi values routinely carry sigils, and a sigil is a character.

    A Profile Constant is a fourth arm rather than `${...}` inside `value`
    for exactly this: scanning a literal would change the meaning of one that
    legitimately holds it.
    """

    from .conftest import text_values

    literal = "$LOCALIZE[31000] ${timezone} $INFO[System.Time]"
    device.write_profile(device.profile_body(settings={"skin.label": literal}))

    assert reconcile("apply", "--room", "theater") == 0

    assert text_values(device.guisettings)["skin.label"] == literal


def test_the_shipped_profile_states_the_zone_once() -> None:
    profile = shipped_profile()
    assert profile["constants"]["timezone"] == ZONE

    taken = [
        setting
        for document in profile["settings_documents"]
        for setting in document["settings"]
        if setting.get("from_profile") == "timezone"
    ]
    assert [setting["setting"] for setting in taken] == ["locale.timezone", "TIMEZONE"]
    # Neither repeats the literal.
    assert not any(setting.get("value") == ZONE for setting in taken)
