"""Reading the Profile and the Room Overlay.

Configuration mistakes must be named locally, before any Device contact.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import (
    ADMINISTRATOR_KEY,
    LIFECYCLE_KEY,
    PROFILE_FILES,
    ROOM,
    FakeDevice,
)


def test_an_unknown_room_is_named(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert reconcile("apply", "--room", "kitchen") == 1

    err = capsys.readouterr().err
    assert "kitchen" in err
    assert "room.yaml" in err


def test_an_unknown_key_is_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_room(ROOM + "hostnmae: ugoos-theater\n")

    assert reconcile("apply", "--room", "theater") == 1

    assert "hostnmae" in capsys.readouterr().err


def test_a_missing_key_is_named(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_room("room: theater\nprofile: ugoos-am6b-plus/coreelec-21.3\n")

    assert reconcile("apply", "--room", "theater") == 1

    assert "hostname" in capsys.readouterr().err


def test_a_profile_escaping_the_configuration_root_is_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_room("room: theater\nhostname: ugoos-theater\nprofile: ../../etc\n")

    assert reconcile("apply", "--room", "theater") == 1

    assert "profile" in capsys.readouterr().err


def test_a_playlist_file_name_with_a_directory_is_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        device.profile_body().replace("file: NewShows.xsp", "file: ../NewShows.xsp")
    )

    assert reconcile("apply", "--room", "theater") == 1

    assert "../NewShows.xsp" in capsys.readouterr().err


def test_the_room_overlay_names_the_device_and_the_profile(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert "ugoos-theater" in out
    assert "ugoos-am6b-plus/coreelec-21.3" in out


def test_the_shipped_configuration_is_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The committed config/ tree must parse without a Device.

    It must parse without the fleet's secrets too, and without its
    administrator key. The shipped Profile names eight values in `.env`, and
    CI has none of them, so the file this Run reads is a stand-in holding
    exactly the keys the Profile names; the administrator identity is a
    stand-in for the same reason. Which six of those keys are add-on Settings
    Document addresses is asserted in `test_settings_documents.py`.
    """
    from coreelec_reconciler import main

    config_root = Path(__file__).resolve().parents[2] / "config"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "".join(
            f"{key}='a-value'\n"
            for key in (
                "HOME_ASSISTANT_URL",
                "HOME_ASSISTANT_TOKEN",
                "NEXTPVR_HOST",
                "NEXTPVR_PIN",
                "MDBLIST_API_KEY",
                "OMDB_API_KEY",
                "KODI_WEB_PASSWORD",
            )
        )
        + f"COREELEC_LIFECYCLE_PUBLIC_KEY='{LIFECYCLE_KEY}'\n",
        encoding="utf-8",
    )
    # The Profile names the administrator identity under `~`, and the
    # administrator entry is derived from its public half.
    monkeypatch.setenv("HOME", str(tmp_path))
    public = tmp_path / ".ssh" / "coreelec_admin_ed25519.pub"
    public.parent.mkdir(parents=True)
    public.write_text(ADMINISTRATOR_KEY, encoding="utf-8")
    monkeypatch.setenv("PATH", "/nonexistent-for-this-test")

    assert (
        main(
            [
                "plan",
                "--room",
                "theater",
                "--config-root",
                str(config_root),
                "--env-file",
                str(env_file),
            ]
        )
        == 1
    )

    # The shipped Profile and Room Overlay parse; the Run gets as far as the
    # Device, which no CI runner can reach.
    err = capsys.readouterr().err
    assert "ugoos-theater" in err
    assert "ssh" in err


@pytest.mark.parametrize("name", sorted(PROFILE_FILES.values()))
def test_a_profile_missing_one_of_its_files_is_refused_naming_it(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    """A missing file would plan nothing for a whole cohort, and say nothing."""

    (device.profile_directory() / name).unlink()

    assert reconcile("plan", "--room", "theater") == 1

    assert f"no {name} beside the Profile" in capsys.readouterr().err


@pytest.mark.parametrize(("key", "name"), sorted(PROFILE_FILES.items()))
def test_a_block_left_behind_in_profile_yaml_is_rejected(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
    key: str,
    name: str,
) -> None:
    """A bad merge must not leave two places a block could be declared."""

    directory = device.profile_directory()
    block = (directory / name).read_text(encoding="utf-8")
    with (directory / "profile.yaml").open("a", encoding="utf-8") as profile:
        profile.write(block)

    assert reconcile("plan", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "profile.yaml" in err
    assert f"unknown key in the Profile: {key}" in err
