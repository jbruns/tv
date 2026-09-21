"""A value Desired State names rather than holds.

Six State Addresses on the theater Ugoos resolve from the shared `.env` file:
four credentials and the two endpoints those credentials authenticate to. A
Profile is committed, so it may not carry any of them. It names the `.env` key
instead, and the value is read at load time, before any Device contact.

The rule these tests hold to is that the value never leaves the Device write:
it is not in a committed file, not in `plan` or `apply` output, and not in an
error message. What is named is the key, which is documented in
`config/README.md` and `.env.example` and is not itself a secret.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import FakeDevice, document_block

# A value no other fixture could produce, so a test that asserts it is absent
# from output is asserting something.
SECRET = "s3cr3t-never-printed"

NAMED_HOST = """\
      - setting: host
        from_env: NEXTPVR_HOST
"""


def named(device: FakeDevice, settings: str = NAMED_HOST) -> str:
    """The Profile, declaring the NextPVR document with `settings`."""
    return device.profile_body(
        extra=document_block(device.nextpvr, "addon_v2", settings)
    )


def text_value(document: Path, setting: str) -> str:
    """What an `addon_v2` document holds for `setting`, read back raw."""
    body = document.read_text(encoding="utf-8")
    opening = f'<setting id="{setting}">'
    return body.split(opening)[1].split("</setting>")[0]


def test_a_named_value_reaches_the_device_without_being_declared(
    device: FakeDevice,
    reconcile: Callable[..., int],
) -> None:
    device.write_env(f"NEXTPVR_HOST='{SECRET}'\n")
    device.write_profile(named(device))

    assert reconcile("apply", "--room", "theater") == 0

    assert text_value(device.nextpvr, "host") == SECRET
    profile = device.config_root.rglob("*.yaml")
    for committed in profile:
        assert SECRET not in committed.read_text(encoding="utf-8")


def test_plan_names_the_key_and_never_the_value(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_env(f"NEXTPVR_HOST='{SECRET}'\n")
    device.write_profile(named(device))

    assert reconcile("plan", "--room", "theater") == 0

    printed = capsys.readouterr()
    assert "NEXTPVR_HOST" in printed.out
    assert f"create {device.nextpvr}#host" in printed.out
    assert SECRET not in printed.out
    assert SECRET not in printed.err


def test_apply_never_prints_the_value(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_env(f"NEXTPVR_HOST='{SECRET}'\n")
    device.write_profile(named(device))

    assert reconcile("apply", "--room", "theater") == 0

    printed = capsys.readouterr()
    assert SECRET not in printed.out
    assert SECRET not in printed.err


def test_a_named_value_converges_and_re_planning_finds_nothing(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_env(f"NEXTPVR_HOST='{SECRET}'\n")
    device.write_profile(named(device))
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert reconcile("plan", "--room", "theater") == 0

    assert "plan: no changes" in capsys.readouterr().out


def test_a_key_the_env_file_does_not_hold_is_an_error_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_env("KODI_WEB_PASSWORD='unrelated'\n")
    device.write_profile(named(device))

    assert reconcile("plan", "--room", "theater") == 1

    printed = capsys.readouterr()
    assert "NEXTPVR_HOST" in printed.err
    # Before Device contact: nothing was read, nothing was planned.
    assert printed.out == ""
    assert device.effects == []


def test_a_key_the_env_file_holds_empty_is_the_same_error(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_env("NEXTPVR_HOST=''\n")
    device.write_profile(named(device))

    assert reconcile("plan", "--room", "theater") == 1

    assert "NEXTPVR_HOST" in capsys.readouterr().err


def test_a_missing_env_file_is_an_error_naming_the_file(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(named(device))

    assert reconcile("plan", "--room", "theater") == 1

    printed = capsys.readouterr()
    assert str(device.env_file) in printed.err
    assert "NEXTPVR_HOST" in printed.err


def test_a_run_that_names_nothing_never_reads_the_env_file(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert not device.env_file.exists()

    assert reconcile("plan", "--room", "theater") == 0

    assert "plan:" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("NEXTPVR_HOST=bare-value\n", "bare-value"),
        ('NEXTPVR_HOST="double quoted"\n', "double quoted"),
        ("NEXTPVR_HOST='has a # and spaces'\n", "has a # and spaces"),
        ("# a comment\n\n   \nNEXTPVR_HOST='after-noise'\n", "after-noise"),
        ("UNRELATED='x'\nNEXTPVR_HOST='last'\n", "last"),
    ],
)
def test_the_env_grammar_reads_what_the_shell_reads(
    device: FakeDevice,
    reconcile: Callable[..., int],
    line: str,
    expected: str,
) -> None:
    device.write_env(line)
    device.write_profile(named(device))

    assert reconcile("apply", "--room", "theater") == 0

    assert text_value(device.nextpvr, "host") == expected


@pytest.mark.parametrize(
    "line",
    [
        "NEXTPVR_HOST\n",
        "export NEXTPVR_HOST='x'\n",
        "NEXTPVR_HOST=$(hostname)\n",
        'NEXTPVR_HOST="${OTHER}"\n',
        "NEXTPVR_HOST='x'\nNEXTPVR_HOST='y'\n",
    ],
)
def test_a_line_the_grammar_cannot_read_is_rejected_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
    line: str,
) -> None:
    device.write_env(line)
    device.write_profile(named(device))

    assert reconcile("plan", "--room", "theater") == 1

    printed = capsys.readouterr()
    assert str(device.env_file) in printed.err
    assert printed.out == ""


def test_a_setting_declares_a_value_or_names_one_but_not_both(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_env(f"NEXTPVR_HOST='{SECRET}'\n")
    device.write_profile(
        named(
            device,
            "      - setting: host\n"
            "        value: literal\n"
            "        from_env: NEXTPVR_HOST\n",
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "host" in capsys.readouterr().err


def test_a_setting_that_neither_holds_nor_names_a_value_is_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(named(device, "      - setting: host\n"))

    assert reconcile("plan", "--room", "theater") == 1

    assert "host" in capsys.readouterr().err


def test_a_named_value_takes_no_transform(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_env(f"NEXTPVR_HOST='{SECRET}'\n")
    device.write_profile(
        named(
            device,
            "      - setting: host\n"
            "        from_env: NEXTPVR_HOST\n"
            "        transform: invert\n",
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    printed = capsys.readouterr()
    assert "transform" in printed.err
    assert SECRET not in printed.err


def test_an_unreadable_value_on_the_device_is_still_not_printed(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Drift on a named address reports the address and the key, nothing else."""
    device.write_env(f"NEXTPVR_HOST='{SECRET}'\n")
    device.write_profile(named(device))
    device.nextpvr.parent.mkdir(parents=True, exist_ok=True)
    device.nextpvr.write_text(
        '<settings version="2">\n'
        '    <setting id="host">stale-backend</setting>\n'
        "</settings>\n",
        encoding="utf-8",
    )

    assert reconcile("plan", "--room", "theater") == 0

    printed = capsys.readouterr()
    assert f"update {device.nextpvr}#host" in printed.out
    assert "stale-backend" not in printed.out
    assert SECRET not in printed.out
