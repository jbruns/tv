"""Shared fixtures.

These tests drive the Reconciler only through its public entry point
(ADR 0011). The fake Device is a local temporary directory plus a stub `ssh`
on PATH; there is no fake-device framework.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

SSH_STUB = """#!/bin/sh
# Stub ssh: runs the remote command locally with the stub directory first on
# PATH, so `hostname` and `mv` resolve to the shims beside this script.
cmd=""
for arg in "$@"; do cmd="$arg"; done
PATH="{stub_dir}:$PATH"
export PATH
exec sh -c "$cmd"
"""

HOSTNAME_STUB = """#!/bin/sh
printf '%s\\n' "${FAKE_DEVICE_HOSTNAME:-ugoos-theater}"
"""

MV_STUB = """#!/bin/sh
# Simulates a Run killed between the staged write and the atomic rename.
if [ -n "$FAKE_DEVICE_KILL_BEFORE_RENAME" ]; then
  kill -9 $PPID
  exit 137
fi
exec {mv} "$@"
"""

PROFILE = """\
profile: ugoos-am6b-plus/coreelec-21.3
transport:
  user: root
  port: 22
  identity: {identity}
smart_playlists:
  directory: {directory}
  playlists:
    - file: NewShows.xsp
      name: New Shows
      type: tvshows
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

ROOM = """\
room: theater
hostname: ugoos-theater
profile: ugoos-am6b-plus/coreelec-21.3
"""

EXPECTED_XSP = """\
<?xml version='1.0' encoding='UTF-8'?>
<smartplaylist type="tvshows">
    <name>New Shows</name>
    <match>all</match>
    <rule field="playcount" operator="is">
        <value>0</value>
    </rule>
    <limit>50</limit>
    <order direction="descending">dateadded</order>
</smartplaylist>
"""


@dataclass(frozen=True)
class FakeDevice:
    """A temporary directory standing in for the theater Ugoos."""

    config_root: Path
    playlists_dir: Path

    @property
    def playlist(self) -> Path:
        return self.playlists_dir / "NewShows.xsp"

    @property
    def staged(self) -> Path:
        return self.playlists_dir / ".NewShows.xsp.tmp"

    def write_profile(self, body: str) -> None:
        profile = (
            self.config_root
            / "shared"
            / "ugoos-am6b-plus"
            / "coreelec-21.3"
            / "profile.yaml"
        )
        profile.write_text(body, encoding="utf-8")

    def write_room(self, body: str) -> None:
        (self.config_root / "rooms" / "theater" / "room.yaml").write_text(
            body, encoding="utf-8"
        )


@pytest.fixture
def device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDevice]:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    for name, body in (
        ("ssh", SSH_STUB.format(stub_dir=stub_dir)),
        ("hostname", HOSTNAME_STUB),
        ("mv", MV_STUB.format(mv=shutil.which("mv") or "/bin/mv")),
    ):
        stub = stub_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{stub_dir}{os.pathsep}{os.environ['PATH']}")

    config_root = tmp_path / "config"
    (config_root / "shared" / "ugoos-am6b-plus" / "coreelec-21.3").mkdir(parents=True)
    (config_root / "rooms" / "theater").mkdir(parents=True)

    playlists_dir = tmp_path / "storage" / ".kodi" / "userdata" / "playlists" / "video"
    fake = FakeDevice(config_root=config_root, playlists_dir=playlists_dir)
    fake.write_profile(
        PROFILE.format(directory=playlists_dir, identity=tmp_path / "id_ed25519")
    )
    fake.write_room(ROOM)
    yield fake


@pytest.fixture
def reconcile(device: FakeDevice) -> Callable[..., int]:
    """Runs the CLI against the fake Device and returns its exit code."""

    from coreelec_reconciler import main

    def run(*argv: str) -> int:
        return main([*argv, "--config-root", str(device.config_root)])

    return run
