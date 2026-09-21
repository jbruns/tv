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
from typing import Any

import pytest
import yaml

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
# Kodi rewrites a Settings Document from memory as it exits, so stopping it
# can revert a setting that looked converged while it was running.
if [ "$1" = "stop" ] && [ -n "$FAKE_DEVICE_KODI_MEMORY" ]; then
  cat "$FAKE_DEVICE_KODI_MEMORY" > "$FAKE_DEVICE_KODI_DOCUMENT"
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
settings_documents:
"""

DEFAULT_SETTINGS = {"videolibrary.flattentvshows": "1"}

ROOM_HEADER = """\
room: theater
hostname: ugoos-theater
profile: ugoos-am6b-plus/coreelec-21.3
"""

# A Room Overlay must state its Settings Documents even when it has none: the
# block is required, and an empty list says so out loud.
ROOM = ROOM_HEADER + "settings_documents: []\n"

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


def indent(block: str) -> str:
    """`block` moved four spaces right, into a document's `settings` list."""

    return "".join(f"    {line}\n" if line else "\n" for line in block.splitlines())


def document_block(path: Path, dialect: str, settings: str) -> str:
    """One entry in a `settings_documents` list."""

    return f"  - document: {path}\n    dialect: {dialect}\n    settings:\n{settings}"


def shipped_profile() -> dict[str, Any]:
    """The committed Profile, read as YAML.

    Tests that assert on what the fleet actually declares read it from here
    rather than restating it, so a declaration and its test cannot drift.
    """

    profile = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "shared"
        / "ugoos-am6b-plus"
        / "coreelec-21.3"
        / "profile.yaml"
    )
    document: dict[str, Any] = yaml.safe_load(profile.read_text(encoding="utf-8"))
    return document


@dataclass(frozen=True)
class FakeDevice:
    """A temporary directory standing in for the theater Ugoos."""

    config_root: Path
    playlists_dir: Path
    userdata: Path
    identity: Path
    systemctl_log: Path
    env_file: Path

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
    def weather(self) -> Path:
        """The weather.ha document, which Kodi writes in the addon_v1 form."""
        return self.userdata / "addon_data" / "weather.ha" / "settings.xml"

    @property
    def nextpvr(self) -> Path:
        """The NextPVR instance document, in the addon_v2 form."""
        return self.userdata / "addon_data" / "pvr.nextpvr" / "instance-settings-1.xml"

    @property
    def tmdb(self) -> Path:
        """TMDb Helper's document, in the addon_v2 form."""
        return (
            self.userdata
            / "addon_data"
            / "plugin.video.themoviedb.helper"
            / "settings.xml"
        )

    @property
    def skin(self) -> Path:
        """Arctic Fuse's document, in the addon_v2 form."""
        return self.userdata / "addon_data" / "skin.arctic.fuse.3" / "settings.xml"

    @property
    def effects(self) -> list[str]:
        """Every `systemctl` invocation the Run made, in order."""
        if not self.systemctl_log.exists():
            return []
        return self.systemctl_log.read_text(encoding="utf-8").splitlines()

    def profile_body(
        self, settings: Mapping[str, str] | None = None, extra: str = ""
    ) -> str:
        """The Profile, declaring guisettings.xml and any `extra` documents."""
        declared = DEFAULT_SETTINGS if settings is None else settings
        return (
            PROFILE.format(directory=self.playlists_dir, identity=self.identity)
            + document_block(
                self.guisettings,
                "guisettings",
                "".join(
                    f'      - setting: {setting}\n        value: "{value}"\n'
                    for setting, value in declared.items()
                ),
            )
            + extra
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

    def write_env(self, body: str) -> None:
        """Writes the shared `.env`, which no Run reads unless one is named."""
        self.env_file.write_text(body, encoding="utf-8")

    def write_room_settings(self, block: str) -> None:
        """Writes a Room Overlay adding `block` to the Profile's guisettings.

        `block` is a list of settings indented two spaces, the shape a reader
        of a Room Overlay sees; the document it belongs to is supplied here.
        """
        self.write_room(
            ROOM_HEADER
            + "settings_documents:\n"
            + document_block(self.guisettings, "guisettings", indent(block))
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
        "FAKE_DEVICE_KODI_DOCUMENT",
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
        env_file=tmp_path / ".env",
    )
    fake.write_profile(fake.profile_body())
    fake.write_room(ROOM)
    yield fake


@pytest.fixture
def reconcile(device: FakeDevice) -> Callable[..., int]:
    """Runs the CLI against the fake Device and returns its exit code."""

    from coreelec_reconciler import main

    def run(*argv: str) -> int:
        return main(
            [
                *argv,
                "--config-root",
                str(device.config_root),
                "--env-file",
                str(device.env_file),
            ]
        )

    return run
