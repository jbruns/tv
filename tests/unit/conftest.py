"""Shared fixtures.

These tests drive the Reconciler only through its public entry point
(ADR 0011). The fake Device is a local temporary directory plus a stub `ssh`
on PATH; there is no fake-device framework.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import stat
import xml.etree.ElementTree as ElementTree
import zipfile
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
# The Reconciler names five Device paths of its own — the three the platform
# Guard reads, the timezone cache whose unit it knows, and the link that unit
# writes — and those are the operating system's, not a tmp_path a Profile can
# state. They are rewritten
# into the fake Device here, for the same reason every other path in these
# tests is a tmp_path: the fake Device is a directory standing in for the
# theater Ugoos.
cmd=""
for arg in "$@"; do cmd="$arg"; done
if [ -n "$FAKE_DEVICE_SSH_LOG" ]; then
  printf '%s\\n' "$*" >> "$FAKE_DEVICE_SSH_LOG"
fi
PATH="{stub_dir}:$PATH"
export PATH
if [ -n "$FAKE_DEVICE_ROOT" ]; then
  cmd=$(printf '%s' "$cmd" | sed \\
    -e "s#/etc/os-release#$FAKE_DEVICE_ROOT/etc/os-release#g" \\
    -e "s#/etc/release#$FAKE_DEVICE_ROOT/etc/release#g" \\
    -e "s#/proc/asound/cards#$FAKE_DEVICE_ROOT/proc/asound/cards#g" \\
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
# Restarting sshd is the one Effect that takes the connection issuing it, and
# a Device whose storage has gone bad comes back with an empty authorized_keys.
if [ "$1" = "restart" ] && [ -n "$FAKE_DEVICE_EMPTIES_ON_RESTART" ]; then
  : > "$FAKE_DEVICE_EMPTIES_ON_RESTART"
fi
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
# Every unit reads as active unless a test stops Kodi, which is what `survey`
# asks before it reads anything.
if [ "$1" = "is-active" ] && [ "$3" = "kodi.service" ] \\
   && [ -n "$FAKE_DEVICE_KODI_STOPPED" ]; then
  exit 3
fi
if [ "$FAKE_DEVICE_SYSTEMCTL_REFUSES" = "$1" ]; then
  echo "systemctl: $1 refused" >&2
  exit 1
fi
exit 0
"""

CURL_STUB = """#!/bin/sh
# Stub curl: serves a pinned Artifact from a local directory, so the fetch is
# exercised end to end without reaching the internet. The URL's last path
# segment names the file, the way it does on every mirror we pin. A file at
# the URL's whole path, less its query, is served first: every Release
# Channel's index is called addons.xml.
#
# This is the same boundary as the stub `ssh` above: the Reconciler invokes a
# client, and the test stands a client in front of it.
url=""
output=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    --retry|--connect-timeout|--max-time|--proto) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  https://*) ;;
  *) echo "curl: only https is configured here" >&2; exit 1 ;;
esac
name="${url##*/}"
if [ -n "$FAKE_ARTIFACT_REFUSES" ]; then
  echo "curl: (22) The requested URL returned error: 404" >&2
  exit 22
fi
whole="${url#https://}"
whole="${whole%%\?*}"
if [ -f "$FAKE_ARTIFACT_DIR/$whole" ]; then
  cp "$FAKE_ARTIFACT_DIR/$whole" "$output"
  exit 0
fi
if [ ! -f "$FAKE_ARTIFACT_DIR/$name" ]; then
  echo "curl: (22) The requested URL returned error: 404" >&2
  exit 22
fi
cp "$FAKE_ARTIFACT_DIR/$name" "$output"
"""

SQLITE_STUB = """#!/usr/bin/env python3
# Stub sqlite3: the real engine, reached through Python's own binding rather
# than through a command-line tool the runner may not have. Arguments are the
# CLI's: an optional -batch, the database, and one script of statements.
import sqlite3
import sys

arguments = [word for word in sys.argv[1:] if word != "-batch"]
database, statements = arguments[0], arguments[1]
connection = sqlite3.connect(database, isolation_level=None)
try:
    held = [part for part in statements.split(";") if part.strip()]
    if len(held) == 1:
        for row in connection.execute(held[0]).fetchall():
            print("|".join("" if value is None else str(value) for value in row))
    else:
        connection.executescript(statements)
finally:
    connection.close()
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
  sound_card: AMLAUGESOUND
constants:
  timezone: America/Los_Angeles
addresses:
  timezone_cache: {timezone_cache}
  sshd_conf: {sshd_conf}
  addons: {addons}
  addon_database: {addon_database}
  addon_manifest: {addon_manifest}
transport:
  user: root
  port: 22
  identity: {identity}
authorized_keys:
  document: {authorized}
  entries: {entries}
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
documents: {documents}
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

# What the theater Ugoos's kernel reports, verbatim: the card id is padded
# inside its brackets.
SOUND_CARDS = """\
 0 [AMLAUGESOUND   ]: AML-AUGESOUND - AML-AUGESOUND
                      AML-AUGESOUND
"""

# The administrator key pair the fake Device is reached with. Only the public
# half is ever read — every connection in these tests goes through the stub
# `ssh` above — so the private half is a placeholder and the public half is
# the line the Reconciler derives the administrator entry from.
ADMINISTRATOR_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIAdministratorKeyForBoundaryTestsOnly0 "
    "coreelec-admin@controller\n"
)
ADMINISTRATOR_ENTRY = ADMINISTRATOR_KEY.strip()

# Home Assistant's lifecycle key, named in `.env` the way a Profile names it.
LIFECYCLE_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILifecycleKeyForBoundaryTestsOnly0"
LIFECYCLE_COMMENT = "homeassistant-ugoos-kodi-lifecycle"
LIFECYCLE_ENTRY = (
    f'restrict,command="/storage/.config/kodi-lifecycle" '
    f"{LIFECYCLE_KEY} {LIFECYCLE_COMMENT}"
)

# The entry a Profile declares for it, as it reads in `authorized_keys`.
LIFECYCLE_ENTRIES = f"""
    - comment: {LIFECYCLE_COMMENT}
      from_env: COREELEC_LIFECYCLE_PUBLIC_KEY
      forced_command: /storage/.config/kodi-lifecycle
"""

# The address the Reconciler knows `sshd.service` reads, and CoreELEC's own
# two keys inside it.
SSHD_CONF = "/storage/.cache/services/sshd.conf"
SSHD_HARDENED = """\
SSH_ARGS="-o 'PasswordAuthentication no'"
SSHD_DISABLE_PW_AUTH="true"
"""
# What the Reconciler leaves. `SSH_ARGS` is byte-identical to CoreELEC's,
# because the quotes are load-bearing; `SSHD_DISABLE_PW_AUTH` is written bare
# like every other `shell_vars` value the Reconciler writes, and the settings
# add-on strips quotes when it reads it back
# (`services.py:488`: `.replace('"', '')`).
SSHD_RECONCILED = """\
SSH_ARGS="-o 'PasswordAuthentication no'"
SSHD_DISABLE_PW_AUTH=true
"""
SSHD_WIZARD_ENABLED = """\
SSH_ARGS=""
SSHD_DISABLE_PW_AUTH="false"
"""
SSHD_DOCUMENT = f"""\
  - document: {SSHD_CONF}
    dialect: shell_vars
    mode: "0644"
    settings:
      - setting: SSH_ARGS
        value: "-o 'PasswordAuthentication no'"
      - setting: SSHD_DISABLE_PW_AUTH
        value: "true"
"""

# The address the Reconciler knows `tz-data.service` reads.
TIMEZONE_CACHE = "/storage/.cache/timezone"

# The one add-on this slice pins, as the Artifact Lock states it. The stub
# `curl` serves the archive the fixture builds under the same last path segment.
ADDON_ID = "script.module.six"
ADDON_VERSION = "1.16.0+matrix.1"
ADDON_URL = (
    "https://mirrors.kodi.tv/addons/omega/script.module.six/"
    f"{ADDON_ID}-{ADDON_VERSION}.zip"
)

# The Release Channel the one pinned add-on comes from, named the way the
# Lock names it.
ADDON_CHANNEL = "kodi-omega"
ADDON_CHANNELS = (
    "channels:\n"
    f"  {ADDON_CHANNEL}:\n"
    "    addons_xml: https://mirrors.kodi.tv/addons/omega/addons.xml.gz\n"
)

# An Artifact Lock pinning nothing. Every Profile has the file; most tests
# are about something else, so theirs is empty.
NO_ADDONS = "channels: {}\naddons: []\n"

# The Profile's four content blocks, each in its own file beside
# `profile.yaml`. Everything else stays in `profile.yaml`.
PROFILE_FILES = {
    "smart_playlists": "playlists.yaml",
    "shortcut_nodes": "shortcuts.yaml",
    "documents": "documents.yaml",
    "settings_documents": "settings.yaml",
}

# Kodi's `installed` table, as Addons33 declares it (`AddonDatabase.cpp`).
# The fake Device holds the real schema so a statement that names a column
# Kodi does not have fails here rather than on the television.
ADDONS33_SCHEMA = """\
CREATE TABLE installed (
  id INTEGER PRIMARY KEY,
  addonID TEXT UNIQUE,
  enabled BOOLEAN,
  installDate TEXT,
  lastUpdated TEXT,
  lastUsed TEXT,
  origin TEXT NOT NULL DEFAULT \'\',
  disabledReason INTEGER NOT NULL DEFAULT 0
);
"""


# What Kodi ships with, as `/usr/share/kodi/system/addon-manifest.xml` states
# it. Two entries, one of them carrying the `optional` attribute two real
# entries carry, so a reader taking the id from the element text is exercised
# on both shapes.
SHIPPED_WITH_KODI = "metadata.generic.albums"
SHIPPED_WITH_KODI_OPTIONAL = "inputstream.adaptive"
KODI_ADDON_MANIFEST = f"""\
<?xml version="1.0"?>
<addons>
  <addon>{SHIPPED_WITH_KODI}</addon>
  <addon optional="true">{SHIPPED_WITH_KODI_OPTIONAL}</addon>
</addons>
"""


def addon_manifest(addon_id: str = ADDON_ID, version: str = ADDON_VERSION) -> str:
    """An `addon.xml` with its attributes spread across lines, as several real
    add-ons write it, so nothing here can be read with a pattern."""

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<addon\n"
        f'  id="{addon_id}"\n'
        f'  name="{addon_id}"\n'
        f'  version="{version}"\n'
        '  provider-name="kodi">\n'
        '  <extension point="xbmc.python.module" library="lib" />\n'
        "</addon>\n"
    )


def addon_lock(
    addon_id: str = ADDON_ID,
    version: str = ADDON_VERSION,
    url: str = ADDON_URL,
    digest: str = "",
    role: str = "dependency",
    notes: str = "~",
    patches: tuple[str, ...] = (),
    patched_files: Mapping[str, str | None] | None = None,
    channel: str = ADDON_CHANNEL,
    channels: str = ADDON_CHANNELS,
) -> str:
    """The Artifact Lock, pinning one add-on."""

    record = (
        channels + "addons:\n"
        f"  - id: {addon_id}\n"
        f'    version: "{version}"\n'
        f"    url: {url}\n"
        f'    sha256: "{digest}"\n'
        f"    role: {role}\n"
        f"    channel: {channel}\n"
        f"    notes: {notes}\n"
    )
    if patches:
        record += "    patches:\n" + "".join(f"      - {name}\n" for name in patches)
    if patched_files is not None:
        record += "    patched_files:\n" + "".join(
            f"      {path}: ~\n" if held is None else f'      {path}: "{held}"\n'
            for path, held in patched_files.items()
        )
    return record


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


def skin_profile(device: FakeDevice, settings: str) -> str:
    """The Profile, declaring guisettings.xml and Arctic Fuse's `skin` document."""

    return device.profile_body(extra=document_block(device.skin, "skin", settings))


def write_document(document: Path, body: str) -> None:
    """Puts `body` on the fake Device, creating the directories it needs."""

    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(body, encoding="utf-8")


def text_values(document: Path) -> dict[str, str | None]:
    """Every setting a text-dialect document holds, as id to element text."""

    root = ElementTree.parse(document).getroot()
    return {node.get("id") or "": node.text for node in root.findall("setting")}


def typed_values(document: Path) -> dict[str, tuple[str | None, str | None]]:
    """Every setting a `skin` document holds, as id to (type, element text)."""

    root = ElementTree.parse(document).getroot()
    return {
        node.get("id") or "": (node.get("type"), node.text)
        for node in root.findall("setting")
    }


def attribute_values(document: Path) -> dict[str, str | None]:
    """Every setting an `addon_v1` document holds, as id to value attribute."""

    root = ElementTree.parse(document).getroot()
    return {node.get("id") or "": node.get("value") for node in root.findall("setting")}


def shipped_profile() -> dict[str, Any]:
    """The committed Profile, read as YAML and merged from its five files.

    Tests that assert on what the fleet actually declares read it from here
    rather than restating it, so a declaration and its test cannot drift.
    """

    directory = shipped_profile_directory()
    document: dict[str, Any] = {}
    for name in ("profile.yaml", *PROFILE_FILES.values()):
        document.update(yaml.safe_load((directory / name).read_text(encoding="utf-8")))
    return document


def shipped_profile_directory() -> Path:
    """The committed Profile's directory."""

    return (
        Path(__file__).resolve().parents[2]
        / "config"
        / "shared"
        / "ugoos-am6b-plus"
        / "coreelec-21.3"
    )


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
    def sound_cards(self) -> Path:
        """The kernel's sound cards, which the platform Guard reads."""
        return self.root / "proc" / "asound" / "cards"

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
    def sshd_conf(self) -> Path:
        """CoreELEC's service document for `sshd`, a `shell_vars` document.

        A Profile states `SSHD_CONF`; this is where the fake Device holds it.
        """
        return self.root / "storage" / ".cache" / "services" / "sshd.conf"

    @property
    def authorized_keys(self) -> Path:
        """Who may log in, which the Reconciler renders whole."""
        return self.root / "storage" / ".ssh" / "authorized_keys"

    @property
    def addons(self) -> Path:
        """Where Kodi keeps add-ons, one expanded tree per id."""
        return self.root / "storage" / ".kodi" / "addons"

    @property
    def addon_database(self) -> Path:
        """Kodi's add-on database, whose schema version is in its filename."""
        return self.userdata / "Database" / "Addons33.db"

    @property
    def addon_manifest(self) -> Path:
        """Kodi's own list of the add-ons it ships with."""
        return self.root / "usr" / "share" / "kodi" / "system" / "addon-manifest.xml"

    @property
    def artifacts(self) -> Path:
        """What the stub `curl` serves, one file per URL's last segment."""
        return self.root / "artifacts"

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
        """Arctic Fuse's document, in the skin form."""
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
        entries: str = "[]",
        documents: str = "[]",
    ) -> str:
        """The Profile, declaring guisettings.xml and any `extra` documents."""
        declared = DEFAULT_SETTINGS if settings is None else settings
        return (
            PROFILE.format(
                directory=self.playlists_dir,
                identity=self.identity,
                nodes=nodes,
                documents=documents,
                authorized=self.authorized_keys,
                entries=entries,
                # The two the operating system owns are stated as the
                # Device's own paths, which the stub `ssh` rewrites into the
                # fake Device, because that is how a Profile states them.
                timezone_cache=TIMEZONE_CACHE,
                sshd_conf=SSHD_CONF,
                addons=self.addons,
                addon_database=self.addon_database,
                addon_manifest=self.addon_manifest,
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

    def profile_directory(self) -> Path:
        return self.config_root / "shared" / "ugoos-am6b-plus" / "coreelec-21.3"

    def write_addons(self, body: str) -> None:
        """Writes the Artifact Lock beside the Profile."""
        (self.profile_directory() / "addons.yaml").write_text(body, encoding="utf-8")

    def read_addons(self) -> str:
        """The Artifact Lock as it stands, which `record-patches` rewrites."""
        return (self.profile_directory() / "addons.yaml").read_text(encoding="utf-8")

    def write_patch(self, name: str, body: str, addon_id: str = ADDON_ID) -> None:
        """Writes an Artifact Patch into `patches/<id>/` beside the Lock."""
        directory = self.profile_directory() / "patches" / addon_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(body, encoding="utf-8")

    def publish_artifact(
        self,
        addon_id: str = ADDON_ID,
        version: str = ADDON_VERSION,
        root: str | None = None,
        manifest: str | None = None,
        extra: Mapping[str, str] | None = None,
        entries: Mapping[str, str] | None = None,
        url: str = ADDON_URL,
    ) -> str:
        """Builds the pinned ZIP the stub `curl` serves, and returns its SHA-256.

        `root` is the archive's single top-level directory, which is not
        always the add-on id: two pins in this fleet are GitHub tag archives.
        `entries` writes raw names straight into the archive, which is how a
        test asks for one no add-on would ever ship.
        """
        self.artifacts.mkdir(parents=True, exist_ok=True)
        top = addon_id if root is None else root
        held = {
            f"{top}/addon.xml": (
                addon_manifest(addon_id, version) if manifest is None else manifest
            ),
            f"{top}/lib/six.py": "SIX = True\n",
        }
        for name, body in (extra or {}).items():
            held[f"{top}/{name}"] = body
        held.update(entries or {})
        archive = self.artifacts / url.rsplit("/", 1)[1]
        with zipfile.ZipFile(archive, "w") as zipped:
            for name, body in held.items():
                zipped.writestr(name, body)
        return hashlib.sha256(archive.read_bytes()).hexdigest()

    def install_addon(
        self,
        addon_id: str = ADDON_ID,
        version: str = ADDON_VERSION,
        enabled: bool | None = True,
        files: Mapping[str, str] | None = None,
    ) -> None:
        """Puts the add-on on the fake Device the way a provisioned one holds it."""
        manifest = self.addons / addon_id / "addon.xml"
        write_document(manifest, addon_manifest(addon_id, version))
        (self.addons / addon_id / "lib").mkdir(parents=True, exist_ok=True)
        for path, body in (files or {}).items():
            write_document(self.addons / addon_id / path, body)
        if enabled is not None:
            self.write_addon_row(addon_id, enabled)

    def create_addon_database(self) -> None:
        """Kodi's own `installed` table, as Addons33 declares it."""
        self.create_addon_database_at(self.addon_database)

    def create_addon_database_at(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            connection.executescript(ADDONS33_SCHEMA)

    def write_addon_row(self, addon_id: str, enabled: bool) -> None:
        with sqlite3.connect(self.addon_database) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO installed(addonID, enabled, installDate)"
                " VALUES(?, ?, ?)",
                (addon_id, int(enabled), "2026-01-01 00:00:00"),
            )

    def forget_addon_row(self, addon_id: str) -> None:
        """What Kodi does on start when the add-on is no longer on disk."""
        with sqlite3.connect(self.addon_database) as connection:
            connection.execute("DELETE FROM installed WHERE addonID=?", (addon_id,))

    def addon_row(
        self, addon_id: str, database: Path | None = None
    ) -> tuple[int, int, str] | None:
        """The row Kodi reads: whether the add-on is enabled, and why not."""
        with sqlite3.connect(
            self.addon_database if database is None else database
        ) as connection:
            held = connection.execute(
                "SELECT enabled, disabledReason, origin FROM installed WHERE addonID=?",
                (addon_id,),
            ).fetchone()
        return None if held is None else (held[0], held[1], held[2])

    def write_source(self, name: str, body: str) -> None:
        """Writes a document's source into the Profile directory."""
        source = self.profile_directory() / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(body, encoding="utf-8")

    def write_profile(self, body: str) -> None:
        """Writes a whole logical Profile, each block to the file it lives in."""
        files: dict[str, list[str]] = {"profile.yaml": []}
        files.update({name: [] for name in PROFILE_FILES.values()})
        target = "profile.yaml"
        for line in body.splitlines(keepends=True):
            key = re.match(r"([A-Za-z_]\w*):", line)
            if key:
                target = PROFILE_FILES.get(key.group(1), "profile.yaml")
            files[target].append(line)
        for name, lines in files.items():
            (self.profile_directory() / name).write_text(
                "".join(lines), encoding="utf-8"
            )

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
        ("curl", CURL_STUB),
        ("sqlite3", SQLITE_STUB),
    ):
        stub = stub_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{stub_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DEVICE_ROOT", str(tmp_path))
    monkeypatch.setenv("FAKE_DEVICE_SYSTEMCTL_LOG", str(tmp_path / "systemctl.log"))
    monkeypatch.setenv("FAKE_ARTIFACT_DIR", str(tmp_path / "artifacts"))
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
    write_document(fake.sound_cards, SOUND_CARDS)
    # Every Run also declares who may log in, and derives the administrator
    # entry from the public half of the transport identity. The fake Device
    # already holds that entry, so a Run that is about something else plans
    # nothing here.
    fake.identity.with_name(f"{fake.identity.name}.pub").write_text(
        ADMINISTRATOR_KEY, encoding="utf-8"
    )
    write_document(fake.authorized_keys, f"{ADMINISTRATOR_ENTRY}\n")
    fake.localtime.parent.mkdir(parents=True, exist_ok=True)
    # Every Run reports the add-ons nobody declared, and the Device's answer
    # to which ones are Kodi's own is this file.
    write_document(fake.addon_manifest, KODI_ADDON_MANIFEST)
    fake.write_profile(fake.profile_body())
    # Every Profile has an Artifact Lock. A test that is about something else
    # pins nothing, so no Run of it reaches an add-on.
    fake.write_addons(NO_ADDONS)
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
