"""Patching an add-on upstream has broken, and observing what the patch made.

The four fixes this fleet carries are unified diffs applied to the expanded
Artifact on the controller, and a patched add-on is observed by its version
*and* by the hashes of the files its diffs touch — correcting a patch does
not move the version, so nothing else would ever ship the correction
(ADR 0017).

These tests drive the Reconciler only through its public entry point
(ADR 0011). The pinned archive is built here and served by the stub `curl`;
the diffs are applied by the real `patch`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import ADDON_ID, ADDON_VERSION, FakeDevice, addon_lock

# The add-on the fixture publishes holds `lib/six.py`, so the patch this
# slice exercises is a diff against it: one Python file, which is what four
# of the five real patches are.
UNPATCHED = "SIX = True\n"
PATCHED = "SIX = True\nPATCHED = True\n"
PATCHED_SHA256 = hashlib.sha256(PATCHED.encode("utf-8")).hexdigest()

PATCH = f"""\
# {ADDON_ID} {ADDON_VERSION}
#
# Upstream forgot to say so.
--- a/lib/six.py
+++ b/lib/six.py
@@ -1 +1,2 @@
 SIX = True
+PATCHED = True
"""

PATCH_NAME = "0001-say-so.patch"


def patched(
    device: FakeDevice,
    diff: str = PATCH,
    recorded: str | None = PATCHED_SHA256,
    database: bool = True,
    **kwargs: object,
) -> None:
    """Publishes the Artifact and declares it with one Artifact Patch."""

    digest = device.publish_artifact(**kwargs)  # type: ignore[arg-type]
    device.write_patch(PATCH_NAME, diff)
    device.write_addons(
        addon_lock(
            digest=digest,
            patches=(PATCH_NAME,),
            patched_files={"lib/six.py": recorded},
        )
    )
    if database:
        device.create_addon_database()


def installed(device: FakeDevice) -> Path:
    return device.addons / ADDON_ID / "lib" / "six.py"


def test_the_device_receives_the_patched_bytes(
    device: FakeDevice, reconcile: Callable[..., int]
) -> None:
    patched(device)

    assert reconcile("apply", "--room", "theater") == 0

    assert installed(device).read_text(encoding="utf-8") == PATCHED


def test_an_unpatched_addon_at_its_pin_is_repaired(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The drift the slice is accepted on.

    The version matches the pin exactly and the add-on is enabled, so only
    the hash of the file the diff touches can catch this.
    """

    patched(device)
    device.install_addon(files={"lib/six.py": UNPATCHED})

    assert reconcile("plan", "--room", "theater") == 0
    report = capsys.readouterr().out
    assert f"update {device.addons / ADDON_ID}" in report
    assert f"version: {ADDON_VERSION} -> {ADDON_VERSION}" in report
    assert "patched file: lib/six.py is not the bytes" in report

    assert reconcile("apply", "--room", "theater") == 0
    assert installed(device).read_text(encoding="utf-8") == PATCHED
    assert reconcile("plan", "--room", "theater") == 0


def test_a_patched_addon_at_its_pin_plans_nothing(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    patched(device)
    device.install_addon(files={"lib/six.py": PATCHED})

    assert reconcile("plan", "--room", "theater") == 0

    assert str(device.addons) not in capsys.readouterr().out


def test_a_corrected_patch_ships_although_the_version_did_not_move(
    device: FakeDevice, reconcile: Callable[..., int]
) -> None:
    patched(device)
    assert reconcile("apply", "--room", "theater") == 0

    corrected = PATCH.replace("+PATCHED = True", "+PATCHED = 2")
    body = "SIX = True\nPATCHED = 2\n"
    patched(
        device,
        diff=corrected,
        recorded=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        database=False,
    )

    assert reconcile("apply", "--room", "theater") == 0
    assert installed(device).read_text(encoding="utf-8") == body


def test_a_patch_that_does_not_apply_fails_the_run(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The context lines are the assertion, and a Device is left untouched."""

    patched(device, diff=PATCH.replace(" SIX = True", " SIX = False"))

    assert reconcile("apply", "--room", "theater") == 1

    assert not (device.addons / ADDON_ID).exists()
    assert (
        f"{PATCH_NAME} does not apply to the pinned {ADDON_ID}"
        in capsys.readouterr().err
    )


def test_a_patched_file_that_does_not_compile_fails_the_run(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A clean application proves the context matched, not that Kodi can import it."""

    patched(device, diff=PATCH.replace("+PATCHED = True", "+PATCHED = ("))

    assert reconcile("apply", "--room", "theater") == 1

    assert not (device.addons / ADDON_ID).exists()
    assert "the patched lib/six.py does not compile" in capsys.readouterr().err


def test_a_patch_written_against_another_version_fails_before_any_fetch(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bump that outruns its patches fails at once, not after 8 MB."""

    device.write_patch(PATCH_NAME, PATCH.replace(ADDON_VERSION, "1.15.0+matrix.1"))
    device.write_addons(
        addon_lock(
            digest="0" * 64,
            patches=(PATCH_NAME,),
            patched_files={"lib/six.py": PATCHED_SHA256},
        )
    )
    device.create_addon_database()

    assert reconcile("plan", "--room", "theater") == 1

    error = capsys.readouterr().err
    assert f"written against {ADDON_ID} 1.15.0+matrix.1" in error
    assert "re-review the patch before moving the pin" in error


def test_a_patch_that_is_not_there_is_named(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_addons(
        addon_lock(
            digest="0" * 64,
            patches=("0002-absent.patch",),
            patched_files={},
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "names a patch that is not there" in capsys.readouterr().err


def test_recorded_files_must_be_the_files_the_diffs_touch(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nothing declares the file list twice, so the two cannot drift apart."""

    patched(device)
    device.write_patch(PATCH_NAME, PATCH)
    device.write_addons(
        addon_lock(
            digest="0" * 64,
            patches=(PATCH_NAME,),
            patched_files={"lib/elsewhere.py": PATCHED_SHA256},
        )
    )

    assert reconcile("plan", "--room", "theater") == 1

    assert "must be exactly the files its patches touch: lib/six.py" in (
        capsys.readouterr().err
    )


def test_an_unrecorded_hash_fails_the_run_rather_than_guessing(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    patched(device, recorded=None)
    device.install_addon(files={"lib/six.py": PATCHED})

    assert reconcile("plan", "--room", "theater") == 1

    assert "run record-patches" in capsys.readouterr().err


def test_record_patches_writes_what_the_pipeline_produces(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The hashes are generated by running the real pipeline, not by hand."""

    patched(device, recorded=None)

    assert reconcile("record-patches", "--room", "theater") == 0

    held = device.read_addons()
    assert f'lib/six.py: "{PATCHED_SHA256}"' in held
    assert f"recorded {ADDON_ID} lib/six.py" in capsys.readouterr().out
    # Nothing was contacted: recording is the artifact pipeline, not a Run.
    assert device.effects == []
    # And the Device the command never touched now plans nothing.
    assert reconcile("apply", "--room", "theater") == 0


def test_record_patches_leaves_a_recorded_lock_alone(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """What the CI job compares: a second run moves nothing."""

    patched(device)
    held = device.read_addons()

    assert reconcile("record-patches", "--room", "theater") == 0

    assert device.read_addons() == held
    assert "already records every patched file" in capsys.readouterr().out


def test_the_shipped_lock_records_every_patch_it_names() -> None:
    """The committed Lock, read as the fleet actually declares it."""

    import yaml

    lock = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "shared"
        / "ugoos-am6b-plus"
        / "coreelec-21.3"
        / "addons.yaml"
    )
    document = yaml.safe_load(lock.read_text(encoding="utf-8"))
    patched_addons = {
        record["id"]: record for record in document["addons"] if record.get("patches")
    }
    assert set(patched_addons) == {
        "weather.ha",
        "script.plexmod",
        "plugin.video.themoviedb.helper",
    }
    for addon_id, record in patched_addons.items():
        for name in record["patches"]:
            assert (lock.parent / "patches" / addon_id / name).is_file()
        assert record["patched_files"]
        for digest in record["patched_files"].values():
            assert isinstance(digest, str) and len(digest) == 64
