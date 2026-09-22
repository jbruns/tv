"""Shared fixtures.

These tests drive the Reconciler only through its public entry point
(ADR 0011). The fake Device is a local temporary directory plus a stub `ssh`
on PATH; there is no fake-device framework.
"""

from __future__ import annotations

import os
import shutil
import stat
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

SSH_STUB = """#!/bin/sh
# Stub ssh: runs the remote command locally with the stub directory first on
# PATH, so `hostname` and `mv` resolve to the shims beside this script.
#
# The Reconciler names four Device paths of its own — the two the platform
# Guard reads, the timezone cache whose unit it knows, and the link that unit
# writes — and those are the operating system's, not a tmp_path a Profile can
# state. They are rewritten
# into the fake Device here, for the same reason every other path in these
# tests is a tmp_path: the fake Device is a directory standing in for the
# theater Ugoos.
cmd=""
for arg in "$@"; do cmd="$arg"; done
PATH="{stub_dir}:$PATH"
export PATH
if [ -n "$FAKE_DEVICE_ROOT" ]; then
  cmd=$(printf '%s' "$cmd" | sed \\
    -e "s#/etc/os-release#$FAKE_DEVICE_ROOT/etc/os-release#g" \\
    -e "s#/etc/release#$FAKE_DEVICE_ROOT/etc/release#g" \\
    -e "s#/var/run/localtime#$FAKE_DEVICE_ROOT/var/run/localtime#g" \
    -e "s#/storage/.cache#$FAKE_DEVICE_ROOT/storage/.cache#g")
fi
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
# Starting Kodi loads the skin, which compiles its view types over whatever
# the compiled include held.
if [ "$1" = "start" ] && [ -n "$FAKE_DEVICE_COMPILED" ]; then
  printf '%s' "$FAKE_DEVICE_COMPILED_BODY" > "$FAKE_DEVICE_COMPILED"
fi
# tz-data.service is a oneshot reading TIMEZONE from the cache document and
# relinking /var/run/localtime.
if [ "$1" = "start" ] && [ "$2" = "tz-data.service" ] \\
   && [ -n "$FAKE_DEVICE_LOCALTIME" ]; then
  TIMEZONE=""
  if [ -f "$FAKE_DEVICE_TIMEZONE_DOCUMENT" ]; then
    . "$FAKE_DEVICE_TIMEZONE_DOCUMENT"
  fi
  if [ -n "$TIMEZONE" ] && [ -z "$FAKE_DEVICE_TZ_DATA_WRONG" ]; then
    ln -sf "/usr/share/zoneinfo/$TIMEZONE" "$FAKE_DEVICE_LOCALTIME"
  fi
fi
if [ "$FAKE_DEVICE_SYSTEMCTL_REFUSES" = "$1" ]; then
  echo "systemctl: $1 refused" >&2
  exit 1
fi
exit 0
"""

CAT_STUB = """#!/bin/sh
# Scripts successive reads of one path, so a test can watch a Run refuse a
# compile it caught mid-write and accept only the finished file. Every other
# read, and every write, passes straight through.
if [ -n "$FAKE_DEVICE_SCRIPTED_PATH" ]; then
  for arg in "$@"; do
    if [ "$arg" = "$FAKE_DEVICE_SCRIPTED_PATH" ]; then
      reads=0
      if [ -f "$FAKE_DEVICE_SCRIPTED_READS" ]; then
        reads=$({cat} "$FAKE_DEVICE_SCRIPTED_READS")
      fi
      reads=$((reads + 1))
      printf '%s' "$reads" > "$FAKE_DEVICE_SCRIPTED_READS"
      if [ -f "$FAKE_DEVICE_SCRIPTED_DIR/$reads" ]; then
        exec {cat} "$FAKE_DEVICE_SCRIPTED_DIR/$reads"
      fi
      exec {cat} "$FAKE_DEVICE_SCRIPTED_DIR/last"
    fi
  done
fi
exec {cat} "$@"
"""

PROFILE = """\
profile: ugoos-am6b-plus/coreelec-21.3
platform:
  id: coreelec
  version: "21.3"
  device: Amlogic-ng
  release_contains: Amlogic-ng.arm-21.3-Omega
constants:
  timezone: America/Los_Angeles
transport:
  user: root
  port: 22
  identity: {identity}
smart_playlists:
  directory: {directory}
  kodi_directory: special://profile/playlists/video
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
shortcut_nodes: {nodes}
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

# What the theater Ugoos holds, abridged to the keys the Guard reads plus the
# two that carry `coreelec` without saying the Device is one. A Profile
# declaring `id: coreelec` must not be satisfied by those.
OS_RELEASE = """\
NAME="CoreELEC"
VERSION="21.3-Omega"
ID="coreelec"
VERSION_ID="21.3"
PRETTY_NAME="CoreELEC (official): 21.3-Omega"
HOME_URL="https://coreelec.org"
BUG_REPORT_URL="https://github.com/CoreELEC/CoreELEC/issues"
COREELEC_ARCH="Amlogic-ng.arm"
COREELEC_DEVICE="Amlogic-ng"
"""

RELEASE = "Amlogic-ng.arm-21.3-Omega\n"

# The address the Reconciler knows `tz-data.service` reads.
TIMEZONE_CACHE = "/storage/.cache/timezone"


def indent(block: str) -> str:
    """`block` moved four spaces right, into a document's `settings` list."""

    return "".join(f"    {line}\n" if line else "\n" for line in block.splitlines())


def document_block(
    path: Path | str, dialect: str, settings: str, key: str = "document"
) -> str:
    """One entry in a `settings_documents` list.

    `key` is `document` for a literal path and `document_glob` for a pattern.
    """

    return f"  - {key}: {path}\n    dialect: {dialect}\n    settings:\n{settings}"


def write_document(document: Path, body: str) -> None:
    """Puts `body` on the fake Device, creating the directories it needs."""

    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(body, encoding="utf-8")


def text_values(document: Path) -> dict[str, str | None]:
    """Every setting a text-dialect document holds, as id to element text."""

    root = ElementTree.parse(document).getroot()
    return {node.get("id") or "": node.text for node in root.findall("setting")}


def attribute_values(document: Path) -> dict[str, str | None]:
    """Every setting an `addon_v1` document holds, as id to value attribute."""

    root = ElementTree.parse(document).getroot()
    return {node.get("id") or "": node.get("value") for node in root.findall("setting")}


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
    root: Path

    @property
    def os_release(self) -> Path:
        """What the Device says it is, which the platform Guard reads."""
        return self.root / "etc" / "os-release"

    @property
    def release(self) -> Path:
        """One line of free text, matched by substring."""
        return self.root / "etc" / "release"

    @property
    def localtime(self) -> Path:
        """The link `tz-data.service` writes and `/etc/localtime` points at."""
        return self.root / "var" / "run" / "localtime"

    @property
    def timezone(self) -> Path:
        """The CoreELEC timezone cache, a `shell_vars` Settings Document.

        A Profile states `TIMEZONE_CACHE`; this is where the fake Device
        holds it.
        """
        return self.root / "storage" / ".cache" / "timezone"

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
    def peripheral_data(self) -> Path:
        """Where Kodi keeps a peripheral's document, named after the hardware."""
        return self.userdata / "peripheral_data"

    @property
    def skinvariables(self) -> Path:
        """Where `script.skinvariables` keeps its own data."""
        return self.userdata / "addon_data" / "script.skinvariables"

    @property
    def viewtypes(self) -> Path:
        """The view types document, which the add-on holds as JSON."""
        return self.skinvariables / "skin.arctic.fuse.3-viewtypes.json"

    @property
    def nodes(self) -> Path:
        """The directory of Shortcut Node files, six on the Device and four ours."""
        return self.skinvariables / "nodes" / "skin.arctic.fuse.3"

    @property
    def compiled(self) -> Path:
        """The include `script.skinvariables` compiles the view types into."""
        return (
            self.userdata.parent
            / "addons"
            / "skin.arctic.fuse.3"
            / "1080i"
            / "script-skinviewtypes-includes.xml"
        )

    @property
    def cec(self) -> Path:
        """The CEC adapter's document, whose name the Profile cannot state."""
        return self.peripheral_data / "cec_CEC_Adapter.xml"

    @property
    def effects(self) -> list[str]:
        """Every `systemctl` invocation the Run made, in order."""
        if not self.systemctl_log.exists():
            return []
        return self.systemctl_log.read_text(encoding="utf-8").splitlines()

    def profile_body(
        self,
        settings: Mapping[str, str] | None = None,
        extra: str = "",
        nodes: str = "[]",
    ) -> str:
        """The Profile, declaring guisettings.xml and any `extra` documents."""
        declared = DEFAULT_SETTINGS if settings is None else settings
        return (
            PROFILE.format(
                directory=self.playlists_dir, identity=self.identity, nodes=nodes
            )
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
        ("cat", CAT_STUB.format(cat=shutil.which("cat") or "/bin/cat")),
        ("systemctl", SYSTEMCTL_STUB),
    ):
        stub = stub_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{stub_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DEVICE_ROOT", str(tmp_path))
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
        root=tmp_path,
    )
    # Every Run guards the platform before it plans, so the fake Device says
    # what the theater Ugoos says unless a test changes it.
    write_document(fake.os_release, OS_RELEASE)
    write_document(fake.release, RELEASE)
    fake.localtime.parent.mkdir(parents=True, exist_ok=True)
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
