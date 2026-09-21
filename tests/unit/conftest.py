"""Shared fixtures.

These tests drive the Reconciler only through its public entry point
(ADR 0011). The fake Device is a local temporary directory plus a stub `ssh`
on PATH; there is no fake-device framework.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable, Iterator, Mapping
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

CHMOD_STUB = """#!/bin/sh
# Refuses to stage any path containing $FAKE_DEVICE_CHMOD_REFUSES, so a single
# write can be made to fail partway through an apply.
if [ -n "$FAKE_DEVICE_CHMOD_REFUSES" ]; then
  for arg in "$@"; do
    case "$arg" in
      *"$FAKE_DEVICE_CHMOD_REFUSES"*) echo "chmod: refused" >&2; exit 1 ;;
    esac
  done
fi
exec {chmod} "$@"
"""

SYSTEMCTL_STUB = """#!/bin/sh
# Records every service Effect the Run takes, in order.
printf '%s\\n' "$*" >> "$FAKE_DEVICE_SYSTEMCTL_LOG"
# Kodi rewrites guisettings.xml from memory as it exits, so stopping it can
# revert a setting that looked converged while it was running.
if [ "$1" = "stop" ] && [ -n "$FAKE_DEVICE_KODI_MEMORY" ]; then
  cat "$FAKE_DEVICE_KODI_MEMORY" > "$FAKE_DEVICE_GUISETTINGS"
fi
if [ "$FAKE_DEVICE_SYSTEMCTL_REFUSES" = "$1" ]; then
  echo "systemctl: $1 refused" >&2
  exit 1
fi
exit 0
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
kodi_settings:
  document: {document}
  settings:
"""

DEFAULT_SETTINGS = {"videolibrary.flattentvshows": "1"}

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
    userdata: Path
    identity: Path
    systemctl_log: Path

    @property
    def playlist(self) -> Path:
        return self.playlists_dir / "NewShows.xsp"

    @property
    def staged(self) -> Path:
        return self.playlists_dir / ".NewShows.xsp.tmp"

    @property
    def guisettings(self) -> Path:
        return self.userdata / "guisettings.xml"

    @property
    def effects(self) -> list[str]:
        """Every `systemctl` invocation the Run made, in order."""
        if not self.systemctl_log.exists():
            return []
        return self.systemctl_log.read_text(encoding="utf-8").splitlines()

    def profile_body(self, settings: Mapping[str, str] | None = None) -> str:
        declared = DEFAULT_SETTINGS if settings is None else settings
        return PROFILE.format(
            directory=self.playlists_dir,
            identity=self.identity,
            document=self.guisettings,
        ) + "".join(
            f'    - setting: {setting}\n      value: "{value}"\n'
            for setting, value in declared.items()
        )

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
        ("chmod", CHMOD_STUB.format(chmod=shutil.which("chmod") or "/bin/chmod")),
        ("systemctl", SYSTEMCTL_STUB),
    ):
        stub = stub_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{stub_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DEVICE_SYSTEMCTL_LOG", str(tmp_path / "systemctl.log"))
    monkeypatch.setenv(
        "FAKE_DEVICE_GUISETTINGS",
        str(tmp_path / "storage" / ".kodi" / "userdata" / "guisettings.xml"),
    )

    config_root = tmp_path / "config"
    (config_root / "shared" / "ugoos-am6b-plus" / "coreelec-21.3").mkdir(parents=True)
    (config_root / "rooms" / "theater").mkdir(parents=True)

    userdata = tmp_path / "storage" / ".kodi" / "userdata"
    fake = FakeDevice(
        config_root=config_root,
        playlists_dir=userdata / "playlists" / "video",
        userdata=userdata,
        identity=tmp_path / "id_ed25519",
        systemctl_log=tmp_path / "systemctl.log",
    )
    fake.write_profile(fake.profile_body())
    fake.write_room(ROOM)
    yield fake


@pytest.fixture
def reconcile(device: FakeDevice) -> Callable[..., int]:
    """Runs the CLI against the fake Device and returns its exit code."""

    from coreelec_reconciler import main

    def run(*argv: str) -> int:
        return main([*argv, "--config-root", str(device.config_root)])

    return run
