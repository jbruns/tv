"""Declaring many Smart Playlists, including one the calendar moves.

The Profile's playlist list is a list, and every entry is an independent
State Address. One of the shipped playlists selects on the current and the
previous release year, which no literal can state without going stale on 1
January, so its offset is declared and the year is resolved on every read.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest

from .conftest import EXPECTED_XSP, FakeDevice, shipped_profile_directory

SECOND_PLAYLIST = """\
    - file: NewMovies.xsp
      name: New Movies
      type: movies
      match: all
      limit: 50
      order:
        field: dateadded
        direction: descending
      rules:
        - field: playcount
          operator: is
          value: "0"
"""

RELATIVE_PLAYLIST = """\
    - file: RecentlyReleasedMovies.xsp
      name: Recently Released Movies
      type: movies
      match: all
      limit: 50
      order:
        field: year
        direction: descending
      rules:
        - field: year
          operator: greaterthan
          value: -2
          relative_to: current_year
        - field: year
          operator: lessthan
          value: 1
          relative_to: current_year
"""


def with_playlist(device: FakeDevice, block: str) -> str:
    """The Profile with `block` appended to its playlist list."""

    body = device.profile_body()
    marker = "shortcut_nodes:"
    head, _, tail = body.partition(marker)
    return head + block + marker + tail


def test_every_declared_playlist_lands_and_a_second_plan_is_empty(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(with_playlist(device, SECOND_PLAYLIST))

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    assert (device.playlists_dir / "NewShows.xsp").read_text(
        encoding="utf-8"
    ) == EXPECTED_XSP
    assert "New Movies" in (device.playlists_dir / "NewMovies.xsp").read_text(
        encoding="utf-8"
    )

    assert reconcile("plan", "--room", "theater") == 0
    assert "no changes" in capsys.readouterr().out.lower()


def test_a_plan_names_the_path_of_every_playlist_that_differs(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(with_playlist(device, SECOND_PLAYLIST))

    assert reconcile("plan", "--room", "theater") == 0

    out = capsys.readouterr().out
    assert str(device.playlists_dir / "NewShows.xsp") in out
    assert str(device.playlists_dir / "NewMovies.xsp") in out


def test_a_year_relative_rule_resolves_against_the_current_year(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(with_playlist(device, RELATIVE_PLAYLIST))

    assert reconcile("apply", "--room", "theater") == 0
    capsys.readouterr()

    year = datetime.date.today().year
    rendered = (device.playlists_dir / "RecentlyReleasedMovies.xsp").read_text(
        encoding="utf-8"
    )
    assert '<rule field="year" operator="greaterthan">' in rendered
    assert f"<value>{year - 2}</value>" in rendered
    assert f"<value>{year + 1}</value>" in rendered

    assert reconcile("plan", "--room", "theater") == 0
    assert "no changes" in capsys.readouterr().out.lower()


def test_an_unknown_relative_base_is_named_before_device_contact(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        with_playlist(
            device, RELATIVE_PLAYLIST.replace("current_year", "current_decade")
        )
    )

    assert reconcile("apply", "--room", "theater") == 1

    err = capsys.readouterr().err
    assert "current_decade" in err
    assert "current_year" in err


def test_a_relative_rule_needs_a_whole_number_offset(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    device.write_profile(
        with_playlist(device, RELATIVE_PLAYLIST.replace("value: -2", "value: recent"))
    )

    assert reconcile("apply", "--room", "theater") == 1

    assert "offset" in capsys.readouterr().err


def test_an_empty_relative_base_is_rejected_rather_than_read_as_absent(
    device: FakeDevice,
    reconcile: Callable[..., int],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`relative_to:` with nothing after it must not render the raw offset.

    Kodi would accept `year greaterthan -2` and quietly select everything.
    """
    device.write_profile(
        with_playlist(
            device,
            RELATIVE_PLAYLIST.replace("relative_to: current_year", "relative_to:"),
        )
    )

    assert reconcile("apply", "--room", "theater") == 1

    assert "relative_to" in capsys.readouterr().err


def test_the_shipped_profile_declares_the_whole_playlist_surface() -> None:
    """Every playlist the shell writes is declared, and none is retired."""

    body = (shipped_profile_directory() / "playlists.yaml").read_text(encoding="utf-8")

    for name in (
        "InProgressMovies90Days.xsp",
        "InProgressShows90Days.xsp",
        "RecentlyAiredEpisodes30Days.xsp",
        "RecentlyReleasedMoviesCurrentAndPreviousYear.xsp",
        "TraktPopularTVShows.xsp",
        "TraktWeekendBoxOffice.xsp",
        "NewShows.xsp",
        "NewMovies.xsp",
    ):
        assert f"file: {name}" in body

    # The two superseded playlists are Managed Absences the shell deletes by
    # hand; declaring either would ask the Reconciler for a mechanism it does
    # not have (ADR 0012).
    assert "file: RecentlyReleasedMovies90Days.xsp" not in body
    assert "file: RecentlyReleasedMoviesCurrentYear.xsp" not in body
