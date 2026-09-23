"""Add-ons nobody declared.

Every directory under the add-on address is in the Artifact Lock, is in
Kodi's own `addon-manifest.xml`, or is not an add-on at all. The remainder is
reported on every Run, including one that changes nothing — which is exactly
when a stray is the only thing worth noticing.

The Run does not fail on one. An add-on appearing from nowhere is interesting
and we want to know, but nothing has decided what a Run should *do* about one,
and refusing to work for a reason nobody chose is worse than the stray
(ADR 0007).

These tests drive the Reconciler through its public entry point only
(ADR 0011).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from .conftest import (
    ADDON_ID,
    SHIPPED_WITH_KODI,
    SHIPPED_WITH_KODI_OPTIONAL,
    FakeDevice,
    addon_lock,
    write_document,
)

STRAY = "plugin.video.nobody.declared"


def report_of(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def test_an_addon_nobody_declared_is_reported_and_the_run_still_succeeds(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.install_addon(STRAY, enabled=None)

    assert reconcile("plan", "--room", "theater") == 0

    assert f"undeclared add-on: {device.addons}/{STRAY}" in report_of(capsys)


def test_a_stray_is_reported_on_a_run_that_changes_nothing(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The quiet Run is the one where the stray is the whole news."""

    device.create_addon_database()
    device.write_addons(addon_lock(digest=device.publish_artifact()))
    device.install_addon()
    device.install_addon(STRAY, enabled=None)

    assert reconcile("apply", "--room", "theater") == 0

    report = report_of(capsys)
    assert f"undeclared add-on: {device.addons}/{STRAY}" in report
    assert str(device.addons / ADDON_ID) not in report
    assert "verification: converged" in report


def test_a_declared_addon_is_not_a_stray(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.create_addon_database()
    device.write_addons(addon_lock(digest=device.publish_artifact()))
    device.install_addon()

    assert reconcile("plan", "--room", "theater") == 0

    assert "undeclared" not in report_of(capsys)


@pytest.mark.parametrize("addon_id", [SHIPPED_WITH_KODI, SHIPPED_WITH_KODI_OPTIONAL])
def test_an_addon_kodi_ships_with_is_not_a_stray(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
    addon_id: str,
) -> None:
    """Kodi's manifest is read, attributes and all, rather than a list here."""

    device.install_addon(addon_id, enabled=None)

    assert reconcile("plan", "--room", "theater") == 0

    assert "undeclared" not in report_of(capsys)


def test_a_directory_without_a_descriptor_is_not_an_addon(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Kodi's `packages` and `temp` are excluded by observation, not by name.

    Naming them would re-introduce the hand-maintained list the Artifact Lock
    replaced, and would still miss the next scratch directory Kodi invents.
    """

    for scratch in ("packages", "temp", "a-directory-nobody-named"):
        (device.addons / scratch).mkdir(parents=True, exist_ok=True)
    write_document(device.addons / "packages" / "some.addon-1.0.0.zip", "")

    assert reconcile("plan", "--room", "theater") == 0

    assert "undeclared" not in report_of(capsys)


def test_a_staging_directory_a_killed_run_left_behind_is_not_a_find(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(
        device.addons / f".{ADDON_ID}.staging" / ADDON_ID / "addon.xml", "<addon/>"
    )

    assert reconcile("plan", "--room", "theater") == 0

    assert "undeclared" not in report_of(capsys)


def test_the_report_is_made_once_even_though_apply_plans_twice(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verification is the Plan run again, and a stray is news only once."""

    device.install_addon(STRAY, enabled=None)

    assert reconcile("apply", "--room", "theater") == 0

    assert report_of(capsys).count("undeclared add-on:") == 1


def test_a_device_without_kodis_manifest_fails_naming_the_address(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Not a stray, so not tolerated: without it every scraper reads as one."""

    device.addon_manifest.unlink()

    assert reconcile("plan", "--room", "theater") == 1

    assert str(device.addon_manifest) in capsys.readouterr().err


def test_a_manifest_that_is_not_xml_fails_naming_itself(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_document(device.addon_manifest, "<addons>\n  <addon>truncated")

    assert reconcile("plan", "--room", "theater") == 1

    assert str(device.addon_manifest) in capsys.readouterr().err


def test_the_manifest_address_is_declared_rather_than_held_in_code(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Device path reaches the Reconciler from the Profile (ADR 0018)."""

    device.write_profile(
        device.profile_body().replace(
            f"addon_manifest: {device.addon_manifest}", "addon_manifest: "
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "addon_manifest" in capsys.readouterr().err


def test_the_shipped_profile_names_kodis_manifest_where_kodi_keeps_it() -> None:
    """Derived from the Profile, so a moved address cannot drift from this."""

    from .conftest import shipped_profile

    addresses = shipped_profile()["addresses"]
    assert addresses["addon_manifest"] == "/usr/share/kodi/system/addon-manifest.xml"
    # The manifest is Kodi's own installation, not the add-on tree, so a
    # Profile that pointed it inside the add-on address would be accounting
    # for strays with a file a stray could write.
    assert not addresses["addon_manifest"].startswith(addresses["addons"])
