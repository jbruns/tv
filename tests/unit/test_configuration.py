"""Reading the Profile and the Room Overlay.

Configuration mistakes must be named locally, before any Device contact.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import ROOM, FakeDevice


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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The committed config/ tree must parse without a Device."""
    from coreelec_reconciler import main

    config_root = Path(__file__).resolve().parents[2] / "config"
    monkeypatch.setenv("PATH", "/nonexistent-for-this-test")

    assert main(["plan", "--room", "theater", "--config-root", str(config_root)]) == 1

    # The shipped Profile and Room Overlay parse; the Run gets as far as the
    # Device, which no CI runner can reach.
    err = capsys.readouterr().err
    assert "ugoos-theater" in err
    assert "ssh" in err
