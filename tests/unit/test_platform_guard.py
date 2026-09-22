"""The Guard that asks the Device what it is before anything is planned.

The shell concatenates `/etc/os-release` and `/etc/release` and greps the
blob case-insensitively for `coreelec`. That passes on any Device whose
`HOME_URL` merely mentions the project, which is every CoreELEC fork and
anything that copied the file. `/etc/os-release` is a defined `KEY=value`
document, so the Guard parses it and asserts on keys instead; `/etc/release`
is genuinely one line of free text and stays a substring match.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from .conftest import OS_RELEASE, FakeDevice, shipped_profile


def platform_block(
    id: str = "coreelec",
    version: str = "21.3",
    device: str = "Amlogic-ng",
    release_contains: str = "Amlogic-ng.arm-21.3-Omega",
) -> str:
    return (
        "platform:\n"
        f"  id: {id}\n"
        f'  version: "{version}"\n'
        f"  device: {device}\n"
        f"  release_contains: {release_contains}\n"
    )


def declare_platform(device: FakeDevice, block: str) -> None:
    """The Profile with its `platform:` block replaced by `block`."""

    body = device.profile_body()
    assert platform_block() in body
    device.write_profile(body.replace(platform_block(), block))


def test_the_guard_passes_on_a_device_that_says_what_the_profile_claims(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert reconcile("apply", "--room", "theater") == 0
    assert "no changes" not in capsys.readouterr().out


def test_a_device_naming_coreelec_only_in_a_url_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole reason the Guard parses rather than greps.

    This Device carries `coreelec` in two keys, and the shell's
    case-insensitive grep over the concatenated files passes on it.
    """

    device.os_release.write_text(
        OS_RELEASE.replace('ID="coreelec"', 'ID="libreelec"'), encoding="utf-8"
    )
    assert 'HOME_URL="https://coreelec.org"' in device.os_release.read_text()

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "/etc/os-release" in err
    assert "ID=libreelec" in err
    assert "coreelec" in err
    # Refused before anything was planned: no service was touched and no
    # document written.
    assert device.effects == []
    assert not device.guisettings.exists()


def test_a_wrong_version_is_refused_naming_the_key_and_both_values(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.os_release.write_text(
        OS_RELEASE.replace('VERSION_ID="21.3"', 'VERSION_ID="22.0"'), encoding="utf-8"
    )

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "VERSION_ID=22.0" in err
    assert "21.3" in err
    assert device.effects == []


def test_a_wrong_soc_family_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.os_release.write_text(
        OS_RELEASE.replace('COREELEC_DEVICE="Amlogic-ng"', 'COREELEC_DEVICE="Amlogic"'),
        encoding="utf-8",
    )

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "COREELEC_DEVICE=Amlogic" in err
    assert "Amlogic-ng" in err


def test_a_key_the_device_does_not_hold_is_refused_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.os_release.write_text(
        "\n".join(
            line
            for line in OS_RELEASE.splitlines()
            if not line.startswith("COREELEC_DEVICE=")
        ),
        encoding="utf-8",
    )

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "COREELEC_DEVICE=(unset)" in err


def test_a_device_with_no_os_release_at_all_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.os_release.unlink()

    assert reconcile("plan", "--room", "theater") == 1

    assert "/etc/os-release" in capsys.readouterr().err


def test_the_release_line_is_matched_by_substring(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One line of free text, so the whole line need not be declared."""

    device.release.write_text(
        "CoreELEC Amlogic-ng.arm-21.3-Omega (official)\n", encoding="utf-8"
    )
    assert reconcile("plan", "--room", "theater") == 0
    capsys.readouterr()

    device.release.write_text("Amlogic-ng.arm-20.5-Nexus\n", encoding="utf-8")
    assert reconcile("plan", "--room", "theater") == 1
    err = capsys.readouterr().err
    assert "/etc/release" in err
    # The refusal names what was expected and what was there.
    assert "Amlogic-ng.arm-21.3-Omega" in err
    assert "Amlogic-ng.arm-20.5-Nexus" in err


def test_a_quoted_value_and_an_unquoted_one_read_the_same(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.os_release.write_text(
        "ID=coreelec\nVERSION_ID=21.3\nCOREELEC_DEVICE=Amlogic-ng\n", encoding="utf-8"
    )

    assert reconcile("plan", "--room", "theater") == 0


def test_a_profile_with_no_platform_block_is_an_error_before_device_contact(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare_platform(device, "")

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "missing key in the Profile: platform" in err
    # Nothing was dialled at all: the hostname is never asked for.
    assert device.effects == []


def test_a_platform_block_missing_a_key_is_an_error_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    declare_platform(
        device,
        'platform:\n  id: coreelec\n  version: "21.3"\n  device: Amlogic-ng\n',
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "missing key in platform: release_contains" in capsys.readouterr().err


def test_the_shipped_profile_declares_the_theater_ugoos_identity() -> None:
    """What the Device actually holds, so the two cannot drift apart."""

    assert shipped_profile()["platform"] == {
        "id": "coreelec",
        "version": "21.3",
        "device": "Amlogic-ng",
        "release_contains": "Amlogic-ng.arm-21.3-Omega",
    }
