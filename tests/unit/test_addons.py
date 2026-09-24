"""Installing one add-on end to end.

Declared in the Artifact Lock, downloaded, proven against its pin, expanded on
the controller, shipped, and enabled in Kodi's own database while Kodi is
stopped (ADR 0017, ADR 0018).

These tests drive the Reconciler only through its public entry point
(ADR 0011). The pinned archive is built here and served by the stub `curl`;
the add-on database is the real SQLite engine holding Kodi's real schema.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from .conftest import (
    ADDON_ID,
    ADDON_URL,
    ADDON_VERSION,
    FakeDevice,
    addon_lock,
    addon_manifest,
)


def pinned(device: FakeDevice, **kwargs: object) -> str:
    """Publishes the Artifact and declares it, leaving only the Device to differ."""

    digest = device.publish_artifact(**kwargs)  # type: ignore[arg-type]
    device.write_addons(addon_lock(digest=digest))
    device.create_addon_database()
    return digest


def test_an_absent_addon_is_downloaded_shipped_and_enabled(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pinned(device)

    assert reconcile("apply", "--room", "theater") == 0

    installed = device.addons / ADDON_ID
    assert (installed / "addon.xml").read_text(encoding="utf-8") == addon_manifest()
    assert (installed / "lib" / "six.py").read_text(encoding="utf-8") == "SIX = True\n"
    # Exactly the columns Kodi's own SyncInstalled touches; everything else
    # takes its declared default.
    assert device.addon_row(ADDON_ID) == (1, 0, "")
    report = capsys.readouterr().out
    assert f"create {installed}" in report
    assert f"version: (absent) -> {ADDON_VERSION}" in report
    assert "enabled: (no row) -> 1" in report
    assert "verification: converged" in report


def test_an_addon_at_its_pin_and_enabled_plans_nothing(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pinned(device)
    device.install_addon()

    assert reconcile("plan", "--room", "theater") == 0

    # The Device already holds it, so the first Run is a no-op that proves
    # Observation. Other Resources still have work; this one does not.
    assert str(device.addons) not in capsys.readouterr().out


def test_the_whole_vertical_repairs_a_deleted_addon(
    device: FakeDevice, reconcile: Callable[..., int]
) -> None:
    """The drift the slice is accepted on: Kodi removes the row with the tree."""

    pinned(device)
    device.install_addon()
    assert reconcile("plan", "--room", "theater") == 0

    # Delete the directory and start Kodi, which drops the `installed` row.
    shutil.rmtree(device.addons / ADDON_ID)
    device.forget_addon_row(ADDON_ID)

    assert reconcile("apply", "--room", "theater") == 0
    assert (device.addons / ADDON_ID / "addon.xml").is_file()
    assert device.addon_row(ADDON_ID) == (1, 0, "")
    assert reconcile("plan", "--room", "theater") == 0


def test_an_installed_addon_that_is_disabled_is_enabled_without_shipping(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Installed and enabled are one Resource, and only what differs is done."""

    pinned(device)
    device.install_addon(enabled=False)
    marker = device.addons / ADDON_ID / "untouched"
    marker.write_text("left alone\n", encoding="utf-8")

    assert reconcile("apply", "--room", "theater") == 0

    assert device.addon_row(ADDON_ID) == (1, 0, "")
    # Nothing was fetched or replaced, so the directory is the one that was
    # already there.
    assert marker.is_file()
    report = capsys.readouterr().out
    assert "enabled: 0 -> 1" in report
    assert "shipping" not in report
    assert "fetching" not in report


def test_a_version_that_differs_replaces_the_tree(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pinned(device)
    device.install_addon(version="1.15.0+matrix.1")
    stale = device.addons / ADDON_ID / "stale.py"
    stale.write_text("old\n", encoding="utf-8")

    assert reconcile("apply", "--room", "theater") == 0

    assert not stale.exists()
    manifest = (device.addons / ADDON_ID / "addon.xml").read_text(encoding="utf-8")
    assert f'version="{ADDON_VERSION}"' in manifest
    assert f"version: 1.15.0+matrix.1 -> {ADDON_VERSION}" in capsys.readouterr().out


def test_the_run_is_taken_with_kodi_stopped(
    device: FakeDevice, reconcile: Callable[..., int]
) -> None:
    pinned(device)

    assert reconcile("apply", "--room", "theater") == 0

    assert device.effects == ["stop kodi.service", "start kodi.service"]


def test_bytes_that_are_not_the_pin_are_never_installed(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pinned(device)
    device.write_addons(addon_lock(digest="0" * 64))

    assert reconcile("apply", "--room", "theater") == 1

    assert not (device.addons / ADDON_ID).exists()
    assert device.addon_row(ADDON_ID) is None
    # The proof happens before the Run takes an Effect, so the television
    # never went down for an Artifact that was never going to be installed.
    assert device.effects == []
    assert "refusing to install bytes nobody pinned" in capsys.readouterr().err


def test_an_artifact_that_cannot_be_fetched_leaves_the_device_alone(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pinned(device)
    monkeypatch.setenv("FAKE_ARTIFACT_REFUSES", "1")

    assert reconcile("apply", "--room", "theater") == 1

    assert not (device.addons / ADDON_ID).exists()
    assert device.effects == []
    assert "could not be fetched" in capsys.readouterr().err


def test_an_artifact_declaring_another_addon_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The pin and the archive must agree, or the archive is the wrong one."""

    pinned(device, manifest=addon_manifest("script.module.kodi-six", ADDON_VERSION))

    assert reconcile("apply", "--room", "theater") == 1

    assert not (device.addons / ADDON_ID).exists()
    assert (
        "the Artifact pinned for script.module.six declares the add-on "
        "script.module.kodi-six" in capsys.readouterr().err
    )


def test_an_artifact_declaring_another_version_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_addons(
        addon_lock(digest=device.publish_artifact(version="1.15.0+matrix.1"))
    )
    device.create_addon_database()

    assert reconcile("apply", "--room", "theater") == 1

    assert "declares version 1.15.0+matrix.1" in capsys.readouterr().err


def test_a_tag_archive_root_is_not_required_to_be_the_addon_id(
    device: FakeDevice, reconcile: Callable[..., int]
) -> None:
    """Two pins in this fleet are GitHub tag archives rooted at `<repo>-<ref>/`."""

    pinned(device, root="kodi_weather_ha-0.0.6.6")

    assert reconcile("apply", "--room", "theater") == 0

    assert (device.addons / ADDON_ID / "addon.xml").is_file()
    assert not (device.addons / "kodi_weather_ha-0.0.6.6").exists()


@pytest.mark.parametrize(
    ("entry", "refusal"),
    [
        ("/etc/passwd", "absolute path entry"),
        ("script.module.six/../../etc/passwd", "traversal entry"),
        ("script.module.six\\lib\\six.py", "backslash"),
    ],
)
def test_an_unsafe_zip_entry_is_refused_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
    entry: str,
    refusal: str,
) -> None:
    pinned(device, entries={entry: "whatever\n"})

    assert reconcile("apply", "--room", "theater") == 1

    assert refusal in capsys.readouterr().err
    assert not (device.addons / ADDON_ID).exists()


def test_an_archive_with_two_top_level_directories_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pinned(device, entries={"script.module.seven/addon.xml": "<addon />\n"})

    assert reconcile("apply", "--room", "theater") == 1

    assert "more than one top-level directory" in capsys.readouterr().err


def test_an_archive_holding_no_manifest_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = device.artifacts / ADDON_URL.rsplit("/", 1)[1]
    device.artifacts.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(f"{ADDON_ID}/lib/six.py", "SIX = True\n")
    device.write_addons(
        addon_lock(digest=hashlib.sha256(archive.read_bytes()).hexdigest())
    )
    device.create_addon_database()

    assert reconcile("apply", "--room", "theater") == 1

    assert "holds no script.module.six/addon.xml" in capsys.readouterr().err


def test_a_manifest_is_parsed_and_never_matched(
    device: FakeDevice, reconcile: Callable[..., int]
) -> None:
    """A manifest whose attributes are spread across lines still reads."""

    pinned(device)
    device.install_addon()
    sprawled = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<addon\n\n"
        f'    id="{ADDON_ID}"\n'
        f'    version="{ADDON_VERSION}"\n'
        '    name="six">\n'
        "</addon>\n"
    )
    (device.addons / ADDON_ID / "addon.xml").write_text(sprawled, encoding="utf-8")

    assert reconcile("plan", "--room", "theater") == 0


def test_a_directory_holding_another_addon_is_refused_rather_than_replaced(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    pinned(device)
    manifest = device.addons / ADDON_ID / "addon.xml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        addon_manifest("script.module.kodi-six", "0.1.3.1"), encoding="utf-8"
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "holds the add-on script.module.kodi-six" in capsys.readouterr().err


def test_an_absent_database_is_refused_rather_than_created(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty file where Kodi expects its schema would fail somewhere worse."""

    device.write_addons(addon_lock(digest=device.publish_artifact()))

    assert reconcile("plan", "--room", "theater") == 1

    assert "no such database" in capsys.readouterr().err
    assert not device.addon_database.exists()


def test_the_database_address_is_declared_rather_than_known(
    device: FakeDevice, reconcile: Callable[..., int]
) -> None:
    """A Profile branched for a future Kodi changes one line (ADR 0018)."""

    branched = device.userdata / "Database" / "Addons34.db"
    device.write_profile(
        device.profile_body().replace(str(device.addon_database), str(branched))
    )
    device.write_addons(addon_lock(digest=device.publish_artifact()))
    branched.parent.mkdir(parents=True, exist_ok=True)
    device.create_addon_database_at(branched)

    assert reconcile("apply", "--room", "theater") == 0

    assert device.addon_row(ADDON_ID, database=branched) == (1, 0, "")
    assert not device.addon_database.exists()


def test_a_lock_that_is_missing_is_refused_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Lock gone missing would report every add-on in the fleet converged."""

    (device.profile_directory() / "addons.yaml").unlink()

    assert reconcile("plan", "--room", "theater") == 1

    assert "no addons.yaml beside the Profile" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("record", "refusal"),
    [
        ({"addon_id": "script module six"}, "not a well-formed add-on id"),
        ({"version": "~1.16"}, "not a well-formed add-on version"),
        ({"url": "http://mirrors.kodi.tv/six.zip"}, "must be https://"),
        ({"digest": "4197F7773F75AB9F"}, "64 lowercase hex characters"),
        ({"role": "transitive"}, "role of script.module.six must be one of"),
    ],
)
def test_a_malformed_pin_is_refused_before_any_device_contact(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
    record: dict[str, str],
    refusal: str,
) -> None:
    fields: dict[str, Any] = {"digest": "4" * 64}
    fields.update(record)
    device.write_addons(addon_lock(**fields))

    assert reconcile("plan", "--room", "theater") == 1

    assert refusal in capsys.readouterr().err


def test_a_pin_stating_no_role_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Why an add-on is here is not derivable from anything else (ADR 0017)."""

    lines = addon_lock(digest="4" * 64).splitlines(keepends=True)
    device.write_addons(
        "".join(line for line in lines if not line.startswith("    role:"))
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "missing key in an add-on: role" in capsys.readouterr().err


@pytest.mark.parametrize("role", ["chosen", "dependency", "repository"])
def test_every_declared_role_is_accepted(
    device: FakeDevice, reconcile: Callable[..., int], role: str
) -> None:
    pinned(device)
    device.write_addons(addon_lock(digest=device.publish_artifact(), role=role))
    device.install_addon()

    assert reconcile("plan", "--room", "theater") == 0


def test_one_addon_pinned_twice_is_refused(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_addons(
        addon_lock(digest="4" * 64)
        + addon_lock(digest="5" * 64).removeprefix("addons:")
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "script.module.six is pinned twice" in capsys.readouterr().err


LOCK = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "shared"
    / "ugoos-am6b-plus"
    / "coreelec-21.3"
    / "addons.yaml"
)


def shipped_lock() -> list[dict[str, str]]:
    records = yaml.safe_load(LOCK.read_text(encoding="utf-8"))["addons"]
    assert isinstance(records, list)
    return records


def test_every_shipped_record_states_why_the_addon_is_there() -> None:
    """`role` records why each add-on is in the Lock (ADR 0017)."""

    for record in shipped_lock():
        # Kodi's own naming, so the one role a reader can check from outside
        # the file is the one the Lock is checked on.
        expected = "repository" if record["id"].startswith("repository.") else None
        if expected is not None:
            assert record["role"] == expected, record["id"]
        else:
            assert record["role"] in ("chosen", "dependency"), record["id"]

    # The operator installed the program and got its dependency with it, which
    # is the distinction `role` exists to keep: bumping the first is a
    # decision, bumping the second is a consequence of one.
    roles = {record["id"]: record["role"] for record in shipped_lock()}
    assert roles["plugin.program.autocompletion"] == "chosen"
    assert roles["script.module.autocompletion"] == "dependency"
