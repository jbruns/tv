"""Reconciling NewShows.xsp against a fake Device.

Each scenario here is the offline analogue of one acceptance case in the
slice: fresh convergence, no-op, drift repair, interruption, and a wrong
Device rejected before any mutation.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from .conftest import EXPECTED_XSP, FakeDevice


def test_apply_creates_the_playlist_on_a_fresh_device(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert not device.playlist.exists()

    assert reconcile("apply", "--room", "theater") == 0

    assert device.playlist.read_text(encoding="utf-8") == EXPECTED_XSP
    assert device.playlist.stat().st_mode & 0o777 == 0o644
    out = capsys.readouterr().out
    assert "create" in out
    assert "applied 2 changes" in out
    assert "converged" in out


def test_apply_on_a_converged_device_changes_nothing(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert reconcile("apply", "--room", "theater") == 0
    before = device.playlist.stat().st_mtime_ns
    capsys.readouterr()

    assert reconcile("apply", "--room", "theater") == 0

    assert device.playlist.stat().st_mtime_ns == before
    out = capsys.readouterr().out
    assert "no changes" in out
    assert "converged" in out


def test_apply_repairs_drift(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert reconcile("apply", "--room", "theater") == 0
    device.playlist.write_text('<smartplaylist type="movies"/>\n', encoding="utf-8")
    capsys.readouterr()

    assert reconcile("apply", "--room", "theater") == 0

    assert device.playlist.read_text(encoding="utf-8") == EXPECTED_XSP
    out = capsys.readouterr().out
    assert "update" in out
    assert "converged" in out


def test_plan_reports_the_diff_and_changes_nothing(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert reconcile("plan", "--room", "theater") == 0

    assert not device.playlist.exists()
    out = capsys.readouterr().out
    assert "create" in out
    assert "+    <name>New Shows</name>" in out
    assert "plan: 2 changes" in out


def test_plan_on_a_converged_device_reports_no_changes(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert "no changes" in out


def test_a_wrong_device_is_rejected_before_any_mutation(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FAKE_DEVICE_HOSTNAME", "ugoos-living")

    assert reconcile("apply", "--room", "theater") == 1

    assert not device.playlists_dir.exists()
    captured = capsys.readouterr()
    assert "ugoos-living" in captured.err
    assert "ugoos-theater" in captured.err


def test_an_unreachable_device_fails_without_mutating(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PATH", "/nonexistent-for-this-test")

    assert reconcile("apply", "--room", "theater") == 1

    assert not device.playlists_dir.exists()
    assert "ssh" in capsys.readouterr().err


def test_an_interrupted_apply_leaves_the_file_intact_and_converges_on_re_run(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.playlists_dir.mkdir(parents=True)
    intact = '<smartplaylist type="tvshows"/>\n'
    device.playlist.write_text(intact, encoding="utf-8")

    monkeypatch.setenv("FAKE_DEVICE_KILL_BEFORE_RENAME", "1")
    assert reconcile("apply", "--room", "theater") == 1

    assert device.playlist.read_text(encoding="utf-8") == intact
    assert device.staged.read_text(encoding="utf-8") == EXPECTED_XSP
    assert "not converge" in capsys.readouterr().err

    monkeypatch.delenv("FAKE_DEVICE_KILL_BEFORE_RENAME")
    assert reconcile("apply", "--room", "theater") == 0

    assert device.playlist.read_text(encoding="utf-8") == EXPECTED_XSP
    assert "converged" in capsys.readouterr().out


def test_apply_reports_a_device_that_did_not_converge(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.playlists_dir.mkdir(parents=True)
    device.playlist.mkdir()

    assert reconcile("apply", "--room", "theater") == 1

    assert "NewShows.xsp" in capsys.readouterr().err


def test_the_hostname_must_match_exactly(
    device: FakeDevice,
    reconcile: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The Room Overlay names the Device as the Device names itself."""
    monkeypatch.setenv("FAKE_DEVICE_HOSTNAME", "ugoos-theater.lan.example")

    assert reconcile("apply", "--room", "theater") == 1

    assert not device.playlists_dir.exists()
    assert "ugoos-theater.lan.example" in capsys.readouterr().err
