"""A Divergent Address: the Profile wanting what the Baseline cannot produce.

Rule 3 of [ADR 0012] is the value-parity invariant — run the shell after an
`apply`, re-plan, expect no changes — and it exists because one mismatched
literal is otherwise invisible. `general.addonupdates` is the first address in
about eighty where the Profile deliberately wants something *better* than the
Recovery Baseline: the shell writes `0` or `1` from `ADDON_UPDATE_MODE` and
cannot emit `2`.

So the exception is declared per address and carries its reason, never as a
blanket flag. A blanket flag would hide exactly the faults rule 3 was written
to catch.

These tests drive the Reconciler through its public entry point only
(ADR 0011).

[ADR 0012]: ../../docs/adr/0012-shadow-the-shell-and-retire-it-wholesale.md
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import FakeDevice, document_block, shipped_profile, write_document

REASON = "the shell writes 0 or 1 and cannot emit 2"

DIVERGENT = f"""\
      - setting: general.addonupdates
        value: "2"
        divergent: {REASON}
"""


def with_setting(device: FakeDevice, block: str) -> str:
    """The Profile, declaring the skin document and nothing else new."""

    return device.profile_body(extra=document_block(device.skin, "addon_v2", block))


def test_a_declared_divergence_is_reported_with_the_change_it_explains(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The moment it is needed is rule 3: the one Change that came back."""

    device.write_profile(with_setting(device, DIVERGENT))
    write_document(
        device.skin,
        '<settings version="2">'
        '<setting id="general.addonupdates">1</setting></settings>',
    )

    assert reconcile("plan", "--room", "theater") == 0

    report = capsys.readouterr().out
    assert f"update {device.skin}#general.addonupdates: 1 -> 2" in report
    assert f"divergent: {REASON}" in report


def test_an_address_that_agrees_says_nothing_about_diverging(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A declaration is not a warning. It explains a Change or stays quiet."""

    device.write_profile(with_setting(device, DIVERGENT))
    write_document(
        device.skin,
        '<settings version="2">'
        '<setting id="general.addonupdates">2</setting></settings>',
    )

    assert reconcile("plan", "--room", "theater") == 0

    assert "divergent" not in capsys.readouterr().out


def test_a_divergence_stating_no_reason_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty reason is a blanket flag spelled per address."""

    device.write_profile(
        with_setting(
            device,
            "      - setting: general.addonupdates\n"
            '        value: "2"\n'
            '        divergent: "  "\n',
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "general.addonupdates" in err
    assert "divergent" in err


def test_a_divergence_is_declared_per_address_and_not_on_the_document(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The safeguard is that one address diverging says nothing about the next."""

    device.write_profile(
        device.profile_body(
            extra=document_block(device.skin, "addon_v2", DIVERGENT)
            + f"    divergent: {REASON}\n"
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "divergent" in capsys.readouterr().err


ADDON_UPDATES = "general.addonupdates"
REPOSITORY = Path(__file__).resolve().parents[2]
BASELINE = (
    REPOSITORY
    / "config"
    / "shared"
    / "ugoos-am6b-plus"
    / "coreelec-21.3"
    / "provision.conf"
)


def shipped_addon_updates() -> dict[str, str]:
    """What the Profile declares for `general.addonupdates`, read from the file."""

    for document in shipped_profile()["settings_documents"]:
        for setting in document["settings"]:
            if setting["setting"] == ADDON_UPDATES:
                held: dict[str, str] = setting
                return held
    raise AssertionError(f"the shipped Profile declares no {ADDON_UPDATES}")


def test_the_shipped_profile_stops_kodi_polling_and_says_why_it_may() -> None:
    """`2` is AUTO_UPDATES_NEVER, the only mode that stops the timer."""

    setting = shipped_addon_updates()
    assert setting["value"] == "2"
    assert setting["divergent"].strip()


def test_the_recovery_baseline_cannot_reach_the_value_the_profile_holds() -> None:
    """The divergence is derived from the shell, not asserted about it.

    `ADDON_UPDATE_MODE` takes two values and the shell maps them to `0` and
    `1`. If it ever learned to emit `2`, this address would stop being
    divergent and the declaration would have to go.
    """

    baseline = BASELINE.read_text(encoding="utf-8")
    declared = [
        line.removeprefix("ADDON_UPDATE_MODE=").strip()
        for line in baseline.splitlines()
        if line.startswith("ADDON_UPDATE_MODE=")
    ]
    assert declared and set(declared) <= {"auto", "notify"}

    shell = (REPOSITORY / "provision-coreelec.sh").read_text(encoding="utf-8")
    lines = shell.splitlines()
    held = [
        lines[index + 1]
        for index, line in enumerate(lines)
        if line.strip() == f'"{ADDON_UPDATES}":'
    ]
    assert len(held) == 1
    assert '"0"' in held[0] and '"1"' in held[0]
    assert '"2"' not in held[0]
