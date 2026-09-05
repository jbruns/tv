#!/bin/bash

# macOS-side bootstrap for a freshly installed CoreELEC device.
#
# The first-boot wizard must already have completed, with wired networking and
# SSH enabled. This script then installs a dedicated administrator key, verifies
# key authentication before disabling password authentication, applies a small
# reversible Kodi/Home Assistant baseline, optionally installs add-ons already
# available from enabled Kodi repositories, and writes a non-secret audit report.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_VERSION="1.0.0"
TARGET=""
IDENTITY_FILE="${HOME}/.ssh/coreelec_admin_ed25519"
ADDONS=()
CHECK_CONFIG="0"
CHECK_ARTIFACTS="0"
PRINT_ADDON_SELECTION=""
DEPLOY_ACTION=""

TASK_TEMP_DIR=""
CURL_CONFIG_FILE=""
KODI_WEB_PASSWORD=""
KEY_ALREADY_ACCEPTED="0"
ARTIFACT_STAGE_DIR=""
REMOTE_TRANSACTION=""

usage() {
  cat <<'USAGE'
Usage:
  provision-coreelec.sh --target HOST [options]
  provision-coreelec.sh --check-config [--config PATH]

Required:
  --target HOST             CoreELEC IPv4 address or DNS/mDNS hostname
                             (not required with --check-config/--check-artifacts)

Options:
  --config PATH             Strict KEY=value settings file (default:
                             config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf)
  --check-config             Validate configuration and secrets, then exit
  --check-artifacts           Validate configuration and artifact records, then exit
  --identity PATH           Administrator key (default: ~/.ssh/coreelec_admin_ed25519)
  --ssh-port PORT           SSH port (default: 22)
  --kodi-port PORT          Kodi HTTP/JSON-RPC port (default: 8080)
  --kodi-user USER          Kodi account for Home Assistant (default: homeassistant)
  --addon ID                Deploy only this pinned add-on from the locked
                             manifest; repeatable. An ID that is not locked in
                             the configuration is rejected.
  --with-youtube            Equivalent to --addon plugin.video.youtube
  --report-dir PATH         Local report directory
  --expected-release VER    Required CoreELEC release substring (default: 21.3)
  --no-kodi                 Skip Kodi and Home Assistant baseline configuration
  --no-harden               Leave SSH password authentication enabled
  --force-unsupported       Continue after release/platform checks fail
  --finalize-deployment     Commit the pending remote deployment transaction
                             (releases its rollback material) and exit
  --rollback-deployment     Undo the pending remote deployment transaction and
                             exit
  --yes                     Do not ask for final confirmation
  --version                 Print script version
  -h, --help                Show this help

Internal:
  --transform-fixture ROOT PAYLOAD
                            Apply the Kodi/add-on settings transformer to ROOT
                             using a base64 KEY=value payload file, then exit.
                             Used by tests/test-coreelec-settings.sh; it never
                             contacts a device.
  --emit-remote-script NAME [ROOT]
                          Print the remote 'backup', 'payload', 'stage',
                           'deploy', 'rollback', or 'finalize' shell program
                           for ROOT (default /storage), then exit. Used by
                           the test suites; it never contacts a device.
  --render-remote-deploy-script [ROOT]
                          Alias of --emit-remote-script deploy: print the
                           remote deployment transaction program for ROOT
                           (default /storage), then exit.
  --print-addon-selection MANIFEST
                          Print the manifest lines this run would deploy,
                           honoring --addon, then exit.

Example:
  ./provision-coreelec.sh --target 172.16.99.50 --with-youtube

The device must first be booted through the CoreELEC wizard with Ethernet and
SSH enabled and a unique root password. The first run may prompt for that root
password and for the passphrase of the dedicated administrator key.

This script deliberately does not configure audio codecs, the display mode
whitelist, Emby/Plex account tokens, or third-party repositories. Those depend
on live HDMI capabilities or provider-specific authorization.
USAGE
}

timestamp() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

info() {
  printf '[%s] %s\n' "$(timestamp)" "$*"
}

warn() {
  printf '[%s] WARNING: %s\n' "$(timestamp)" "$*" >&2
}

die() {
  printf '[%s] ERROR: %s\n' "$(timestamp)" "$*" >&2
  exit 1
}

cleanup() {
  KODI_WEB_PASSWORD=""
  if [[ -n "${CURL_CONFIG_FILE}" && -f "${CURL_CONFIG_FILE}" ]]; then
    rm -f -- "${CURL_CONFIG_FILE}"
  fi
  if [[ -n "${TASK_TEMP_DIR}" && -f "${TASK_TEMP_DIR}/kodi-response.json" ]]; then
    rm -f -- "${TASK_TEMP_DIR}/kodi-response.json"
  fi
  if [[ -n "${TASK_TEMP_DIR}" && -d "${TASK_TEMP_DIR}/artifacts" ]]; then
    rm -rf -- "${TASK_TEMP_DIR}/artifacts"
  fi
  if [[ -n "${TASK_TEMP_DIR}" && -d "${TASK_TEMP_DIR}" ]]; then
    rmdir "${TASK_TEMP_DIR}" 2>/dev/null || true
  fi
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/coreelec-config.sh
source "${SCRIPT_DIR}/lib/coreelec-config.sh"
# shellcheck source=lib/coreelec-artifacts.sh
source "${SCRIPT_DIR}/lib/coreelec-artifacts.sh"

# --- Kodi and add-on settings transformer -----------------------------------
#
# The transformer below is a single Python program used unchanged in two
# places: piped to python3 on the CoreELEC device while Kodi is stopped, and
# run locally against a scratch directory by the internal
# `--transform-fixture ROOT PAYLOAD` test mode. Keeping one copy is what makes
# the offline tests evidence about the remote behavior.
#
# It reads a mode-0600 payload of `KEY=base64(value)` lines. Base64 keeps
# whitespace, newlines, quotes, and JSON out of the line grammar entirely, and
# decoding happens only inside the Python process. Each optional secret also
# carries its own `HAVE_<KEY>` presence flag, so an absent secret is never
# inferred from an empty string.
#
# These definitions must precede the configuration pre-scan below, because the
# pre-scan dispatches `--transform-fixture` before any configuration file is
# read.

coreelec_settings_transformer_source() {
  cat <<'PYTHON_TRANSFORMER_SOURCE'
"""Idempotent CoreELEC/Kodi settings transformer.

Usage: python3 - STORAGE_ROOT PAYLOAD_PATH

Every managed value is written through a temporary file and an atomic rename.
Unmanaged settings are preserved, duplicate managed settings are collapsed,
managed entries are applied in a deterministic order, and a second run over an
unchanged payload produces byte-identical files.
"""

import base64
import json
import os
import sys
import xml.etree.ElementTree as ET

SKIN_ID = "skin.arctic.fuse.3"
WEATHER_ADDON_ID = "weather.ha"
YOUTUBE_CLIENT_ID_SUFFIX = ".apps.googleusercontent.com"

WRITTEN_PATHS = []
ADDON_DOCUMENTS = {}
MANAGED_DIRECTORIES = set()
TEMPORARY_SUFFIX = ".provision-new"


def fail(message):
    raise SystemExit("settings transformer: " + message)


def register_managed_directory(path):
    """Records a directory so orphaned temp files can be swept from it even
    when a run fails before that directory is written."""
    if path:
        MANAGED_DIRECTORIES.add(path)


def _discard_temporary(path, quiet=False):
    """Unlinks a temp path. A symlink is removed, never followed."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError:
        if not quiet:
            raise


def sweep_orphan_temporaries():
    """Removes `*.provision-new` files an interrupted run may have left in a
    managed directory. They can hold secrets, so none may outlive the run."""
    for directory in sorted(MANAGED_DIRECTORIES):
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if name.endswith(TEMPORARY_SUFFIX):
                _discard_temporary(os.path.join(directory, name), quiet=True)


def read_payload(path):
    """Parses `KEY=base64(value)` lines. Never echoes a decoded value."""
    values = {}
    with open(path, "r", encoding="utf-8") as handle:
        for number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip("\n")
            if not line:
                continue
            key, separator, encoded = line.partition("=")
            if not separator or not key:
                fail("payload line %d is not KEY=value" % number)
            try:
                decoded = base64.b64decode(encoded.encode("ascii"),
                                           validate=True)
                values[key] = decoded.decode("utf-8")
            except Exception:
                fail("payload line %d (%s) is not valid base64 UTF-8"
                     % (number, key))
    return values


def validate_payload(values):
    """`HAVE_X=1` with a missing or empty `X` is a contradiction: the caller
    believes the secret is configured while the payload carries nothing.
    Failing here, before any write, keeps an empty managed value from being
    stored as if it were a real credential. Only the key name is reported."""
    for key in sorted(values):
        if not key.startswith("HAVE_") or values[key] != "1":
            continue
        name = key[len("HAVE_"):]
        if not values.get(name, ""):
            fail("%s is flagged present but carries no value" % name)


def _ensure_directory(path, mode=0o700):
    """Creates every missing component at `mode`.

    os.makedirs() applies its mode to the leaf only and leaves intermediate
    directories at the ambient umask, which would expose add-on data holding
    API keys and tokens. Directories that already exist are left alone."""
    if not path or os.path.isdir(path):
        return
    parent = os.path.dirname(path)
    if parent and parent != path:
        _ensure_directory(parent, mode)
    try:
        os.mkdir(path, mode)
    except FileExistsError:
        return
    os.chmod(path, mode)


def _open_exclusive(path, mode):
    """Creates `path` at exactly `mode` before a single byte is written.

    O_EXCL refuses a file that already exists and O_NOFOLLOW refuses a
    symlink, so secret bytes can never land in a stale or planted temp file
    whose mode, hard links, or target this process does not control. fchmod
    then defeats the ambient umask, which would otherwise mask the mode."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    try:
        os.fchmod(descriptor, mode)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def _atomic_write(path, data, mode):
    directory = os.path.dirname(path)
    if directory:
        _ensure_directory(directory)
        register_managed_directory(directory)
    temporary = path + TEMPORARY_SUFFIX
    _discard_temporary(temporary)
    descriptor = _open_exclusive(temporary, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        # A failed write must not leave secret bytes behind under a name
        # nothing will ever clean up.
        _discard_temporary(temporary, quiet=True)
        raise
    WRITTEN_PATHS.append(path)


def write_text_atomic(path, value, mode=0o600):
    _atomic_write(path, value.encode("utf-8"), mode)


def write_json_atomic(path, value):
    """Matches the add-on convention of sorted, four-space JSON."""
    body = json.dumps(value, ensure_ascii=False, indent=4, sort_keys=True)
    write_text_atomic(path, body + "\n", 0o600)


def write_xml_atomic(path, tree, mode=0o600):
    if hasattr(ET, "indent"):
        ET.indent(tree, space="    ")
    body = ET.tostring(tree.getroot(), encoding="UTF-8", xml_declaration=True)
    if not body.endswith(b"\n"):
        body += b"\n"
    _atomic_write(path, body, mode)


def _setting_nodes(root, setting_id):
    """Every matching node with its parent, including the legacy
    `<category>` nesting that old-format settings files may still carry."""
    found = []
    parents = [root]
    parents.extend(root.findall("category"))
    for parent in parents:
        for node in parent.findall("setting"):
            if node.get("id") == setting_id:
                found.append((parent, node))
    return found


def _set_xml_setting(root, setting_id, value, flat):
    # One rule for every managed setting, Kodi or add-on: an empty value is
    # never stored. Writing one would replace a good existing value with
    # nothing, and Kodi reads an empty node as unset anyway.
    if value == "":
        return None
    nodes = _setting_nodes(root, setting_id)
    if nodes:
        node = nodes[0][1]
        for duplicate_parent, duplicate in nodes[1:]:
            duplicate_parent.remove(duplicate)
    else:
        node = ET.SubElement(root, "setting", {"id": setting_id})
    node.attrib.pop("default", None)
    if flat:
        node.text = None
        node.set("value", value)
    else:
        node.attrib.pop("value", None)
        node.text = value
    return node


def set_kodi_setting(root, setting_id, value):
    """Sets one Kodi guisettings value on an already-loaded document root."""
    return _set_xml_setting(root, setting_id, value, flat=False)


def set_addon_setting(path, setting_id, value, version=2):
    """Sets one add-on setting in the document for `path`.

    version=2 uses Kodi's current `<setting id="x">value</setting>` form.
    version=1 uses the old flat `<setting id="x" value="y" />` form, which is
    what add-ons whose settings definition carries no version attribute (such
    as weather.ha) are loaded with. Documents are committed together by
    commit_addon_settings() so each file is written exactly once.
    """
    if value == "":
        return None
    document = ADDON_DOCUMENTS.get(path)
    if document is None:
        if os.path.exists(path):
            tree = ET.parse(path)
            root = tree.getroot()
            if root.tag != "settings":
                fail("unexpected root element in %s" % path)
        else:
            attributes = {} if version == 1 else {"version": "2"}
            root = ET.Element("settings", attributes)
            tree = ET.ElementTree(root)
        document = (tree, root)
        ADDON_DOCUMENTS[path] = document
    return _set_xml_setting(document[1], setting_id, value,
                            flat=(version == 1))


def commit_addon_settings():
    for path in sorted(ADDON_DOCUMENTS):
        write_xml_atomic(path, ADDON_DOCUMENTS[path][0])


def load_kodi_settings(path):
    if os.path.exists(path):
        tree = ET.parse(path)
        root = tree.getroot()
        if root.tag != "settings":
            fail("unexpected root element in %s" % path)
        return tree, root
    root = ET.Element("settings", {"version": "2"})
    return ET.ElementTree(root), root


def main(argv):
    if len(argv) != 3:
        fail("usage: STORAGE_ROOT PAYLOAD_PATH")
    storage_root, payload_path = argv[1], argv[2]

    payload = read_payload(payload_path)
    validate_payload(payload)

    def config(key, default=""):
        return payload.get(key, default)

    def have(key):
        return payload.get("HAVE_" + key, "0") == "1"

    def secret(key):
        return config(key) if have(key) else ""

    userdata = os.path.join(storage_root, ".kodi", "userdata")
    addon_data = os.path.join(userdata, "addon_data")
    register_managed_directory(userdata)
    register_managed_directory(addon_data)
    register_managed_directory(os.path.join(storage_root, ".cache"))

    def addon_file(addon_id, name):
        directory = os.path.join(addon_data, addon_id)
        register_managed_directory(directory)
        return os.path.join(directory, name)

    youtube_configured = (have("YOUTUBE_API_KEY")
                          and have("YOUTUBE_CLIENT_ID")
                          and have("YOUTUBE_CLIENT_SECRET"))
    weather_configured = bool(config("HOME_ASSISTANT_URL")
                              and config("HOME_ASSISTANT_WEATHER_ENTITY")
                              and have("HOME_ASSISTANT_TOKEN"))
    nextpvr_configured = bool(config("NEXTPVR_HOST") and have("NEXTPVR_PIN"))
    plex_configured = bool(config("PLEX_SERVER_HOST") and have("PLEX_TOKEN"))

    # --- Kodi guisettings ---------------------------------------------------
    kodi_values = {
        "general.addonupdates":
            "0" if config("ADDON_UPDATE_MODE") == "auto" else "1",
        "locale.country": config("LOCALE_COUNTRY"),
        "locale.keyboardlayouts": config("KEYBOARD_LAYOUT"),
        "locale.language": config("LOCALE_LANGUAGE"),
        "locale.timezone": config("TIMEZONE"),
        "locale.timezonecountry": config("TIMEZONE_COUNTRY"),
        "lookandfeel.skin": SKIN_ID,
        "videoplayer.adjustrefreshrate": "2",
        "videoplayer.usedisplayasclock": "false",
    }
    if have("KODI_WEB_PASSWORD"):
        kodi_values.update({
            "services.esallinterfaces": "false",
            "services.esenabled": "true",
            "services.webserver": "true",
            "services.webserverauthentication": "true",
            "services.webserverpassword": secret("KODI_WEB_PASSWORD"),
            "services.webserverport": config("KODI_WEB_PORT"),
            "services.webserverssl": "false",
            "services.webserverusername": config("KODI_WEB_USER"),
        })
    if weather_configured:
        kodi_values["weather.addon"] = WEATHER_ADDON_ID

    guisettings_path = os.path.join(userdata, "guisettings.xml")
    guisettings_tree, guisettings_root = load_kodi_settings(guisettings_path)
    for setting_id in sorted(kodi_values):
        set_kodi_setting(guisettings_root, setting_id, kodi_values[setting_id])
    write_xml_atomic(guisettings_path, guisettings_tree)

    # --- YouTube ------------------------------------------------------------
    youtube_settings = addon_file("plugin.video.youtube", "settings.xml")
    set_addon_setting(youtube_settings, "kodion.setup_wizard", "false")
    set_addon_setting(youtube_settings, "youtube.language", "en-US")
    set_addon_setting(youtube_settings, "youtube.region", "US")
    if youtube_configured:
        # The add-on strips whitespace and the Google domain suffix itself;
        # storing the already-stripped values keeps it from rewriting the file.
        api_key = "".join(secret("YOUTUBE_API_KEY").split())
        client_id = "".join(secret("YOUTUBE_CLIENT_ID").split())
        client_id = client_id.replace(YOUTUBE_CLIENT_ID_SUFFIX, "")
        client_secret = "".join(secret("YOUTUBE_CLIENT_SECRET").split())
        write_json_atomic(
            addon_file("plugin.video.youtube", "api_keys.json"),
            {
                "keys": {
                    "developer": {},
                    "user": {
                        "api_key": api_key,
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                },
            },
        )

    # --- TMDb Helper --------------------------------------------------------
    # OMDb and MDbList keys belong to TMDb Helper only, never to the skin.
    tmdb_settings = addon_file("plugin.video.themoviedb.helper", "settings.xml")
    if have("MDBLIST_API_KEY"):
        set_addon_setting(tmdb_settings, "mdblist_apikey",
                          secret("MDBLIST_API_KEY"))
    if have("OMDB_API_KEY"):
        set_addon_setting(tmdb_settings, "omdb_apikey", secret("OMDB_API_KEY"))

    # --- NextPVR ------------------------------------------------------------
    # Kodi 21 has no pvrmanager.enabled setting: the PVR manager starts from an
    # enabled client instance, so instance-settings-1.xml carries the enable.
    if nextpvr_configured:
        instance = addon_file("pvr.nextpvr", "instance-settings-1.xml")
        set_addon_setting(instance, "host", config("NEXTPVR_HOST"))
        set_addon_setting(instance, "hostprotocol",
                          config("NEXTPVR_PROTOCOL") or "http")
        set_addon_setting(instance, "kodi_addon_instance_enabled", "true")
        set_addon_setting(instance, "kodi_addon_instance_name",
                          config("NEXTPVR_INSTANCE_NAME") or "NextPVR")
        set_addon_setting(instance, "pin", secret("NEXTPVR_PIN"))
        set_addon_setting(instance, "port", config("NEXTPVR_PORT") or "8866")

    # --- PM4K local mode ----------------------------------------------------
    if plex_configured:
        plex_settings = addon_file("script.plexmod", "settings.xml")
        try:
            port = int(config("PLEX_SERVER_PORT") or "32400")
        except ValueError:
            fail("PLEX_SERVER_PORT is not numeric")
        server = {
            "connection": config("PLEX_SERVER_HOST"),
            "port": port,
            "token": secret("PLEX_TOKEN"),
            "name": config("PLEX_SERVER_NAME") or None,
        }
        set_addon_setting(plex_settings, "allow_insecure", "always")
        set_addon_setting(plex_settings, "local_mode", "true")
        set_addon_setting(plex_settings, "local_servers_json",
                          json.dumps([server], sort_keys=True))
        profiles = [entry for entry in config("PLEX_PROFILE_IDS").split(",")
                    if entry]
        if profiles:
            set_addon_setting(plex_settings, "local_profiles_json",
                              json.dumps(profiles))

    # --- Home Assistant Weather --------------------------------------------
    if weather_configured:
        weather_settings = addon_file(WEATHER_ADDON_ID, "settings.xml")
        set_addon_setting(weather_settings, "ha_key",
                          secret("HOME_ASSISTANT_TOKEN"), version=1)
        set_addon_setting(weather_settings, "ha_server",
                          config("HOME_ASSISTANT_URL"), version=1)
        set_addon_setting(weather_settings, "ha_weather_forecast_entity_id",
                          config("HOME_ASSISTANT_WEATHER_ENTITY"), version=1)
        set_addon_setting(weather_settings, "ha_sun_entity_id",
                          config("HOME_ASSISTANT_SUN_ENTITY"), version=1)

    commit_addon_settings()

    # --- CoreELEC timezone cache -------------------------------------------
    # Kodi's CoreELEC patch writes this file when the timezone changes through
    # the UI; offline edits must write it explicitly. It holds no secret.
    if config("TIMEZONE"):
        write_text_atomic(os.path.join(storage_root, ".cache", "timezone"),
                          "TIMEZONE=%s\n" % config("TIMEZONE"), mode=0o644)

    for path in WRITTEN_PATHS:
        sys.stdout.write("settings applied: %s\n" % path)


try:
    main(sys.argv)
finally:
    # Sweeps temp files an interrupted earlier run may have orphaned, on both
    # the success and the failure path.
    sweep_orphan_temporaries()
PYTHON_TRANSFORMER_SOURCE
}

# Internal test entry point: applies the transformer to a scratch root.
coreelec_settings_transform_fixture() {
  local root="$1" payload="$2"
  [[ -n "${root}" ]] || die "--transform-fixture requires a root directory"
  [[ -r "${payload}" ]] || die "--transform-fixture payload is not readable: ${payload}"
  require_command python3
  mkdir -p "${root}"
  coreelec_settings_transformer_source | python3 - "${root}" "${payload}"
}

# Every settings path the transformer may write, relative to the storage root.
# Emitted as an `sh` function so the backup snapshot and the deployment
# transaction copy exactly the same set and can never drift apart.
coreelec_managed_settings_paths_block() {
  cat <<'MANAGED_SETTINGS_FUNCTION'
managed_settings_paths() {
  cat <<'MANAGED_SETTINGS_PATHS'
.kodi/userdata/guisettings.xml
.cache/timezone
.kodi/userdata/addon_data/plugin.video.youtube/settings.xml
.kodi/userdata/addon_data/plugin.video.youtube/api_keys.json
.kodi/userdata/addon_data/plugin.video.themoviedb.helper/settings.xml
.kodi/userdata/addon_data/pvr.nextpvr/instance-settings-1.xml
.kodi/userdata/addon_data/script.plexmod/settings.xml
.kodi/userdata/addon_data/weather.ha/settings.xml
MANAGED_SETTINGS_PATHS
}
MANAGED_SETTINGS_FUNCTION
}

# Remote script emitters. Each prints `sh` program text whose storage root is a
# parameter, so tests can execute the exact program the device receives against
# a scratch directory. No emitter reads configuration or contacts a host, and
# none of them interpolates an add-on ID, artifact name, or transaction path:
# those are always read at runtime from files the device itself revalidates.
coreelec_remote_backup_script() {
  local root="${1:-/storage}"
  # umask 077 covers every directory and file the snapshot creates: a copy of
  # guisettings.xml or api_keys.json carries credentials, so the snapshot must
  # not be readable by anyone but root.
  cat <<REMOTE_BACKUP_HEADER
set -eu
umask 077
storage_root="${root}"
REMOTE_BACKUP_HEADER
  coreelec_managed_settings_paths_block
  cat <<'REMOTE_BACKUP'
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="${storage_root}/backup/coreelec-provision/${stamp}"
mkdir -p "${backup}"
chmod 700 "${backup}"

copy_one() {
  source_path="$1"
  if [ -f "${source_path}" ]; then
    relative_path="${source_path#${storage_root}/}"
    destination_dir="${backup}/$(dirname "${relative_path}")"
    mkdir -p "${destination_dir}"
    cp -p "${source_path}" "${backup}/${relative_path}"
    # A snapshot of guisettings.xml or api_keys.json holds credentials even
    # when the original was left world-readable, so the copy's mode is
    # normalized here instead of inherited from the source.
    chmod 600 "${backup}/${relative_path}"
  fi
}

copy_one "${storage_root}/.ssh/authorized_keys"
copy_one "${storage_root}/.cache/services/sshd.conf"
copy_one "${storage_root}/.cache/hostname"
copy_one "${storage_root}/.kodi/userdata/advancedsettings.xml"
copy_one "${storage_root}/.kodi/userdata/sources.xml"
copy_one "${storage_root}/.kodi/userdata/addon_data/service.coreelec.settings/oe_settings.xml"

managed_settings_paths | while IFS= read -r managed_relative; do
  [ -n "${managed_relative}" ] || continue
  copy_one "${storage_root}/${managed_relative}"
done

{
  printf 'created_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname=%s\n' "$(hostname)"
  printf 'release='
  tr '\n' ' ' < /etc/release 2>/dev/null || true
  printf '\n'
} > "${backup}/MANIFEST.txt"

printf '%s\n' "${backup}"
REMOTE_BACKUP
}

coreelec_remote_payload_script() {
  local root="${1:-/storage}"
  cat <<REMOTE_PAYLOAD_HEADER
set -eu
umask 077
payload_dir="${root}/.cache/coreelec-provision"
REMOTE_PAYLOAD_HEADER
  cat <<'REMOTE_PAYLOAD'
payload_file="${payload_dir}/settings-payload.conf"
temporary="${payload_file}.provision-new"
mkdir -p "${payload_dir}"
chmod 700 "${payload_dir}"
# The temp name is removed first so the secrets land in a file this script
# creates under umask 077, never in a stale or planted file whose mode, hard
# links, or symlink target it does not control. The rename is atomic, so the
# payload is never observable half-written.
rm -f "${temporary}"
cat > "${temporary}"
chmod 600 "${temporary}"
mv "${temporary}" "${payload_file}"
REMOTE_PAYLOAD
}

# Receives the artifact bundle as a tar stream on stdin. It travels inside a
# single-quoted remote `sh -c` argument (stdin is the tar stream, so the
# program cannot be piped in), which is why it must never contain a single
# quote of its own.
coreelec_remote_stage_script() {
  local root="${1:-/storage}"
  cat <<REMOTE_STAGE_HEADER
set -eu
umask 077
provision_cache="${root}/.cache/coreelec-provision"
REMOTE_STAGE_HEADER
  cat <<'REMOTE_STAGE'
stage_dir="${provision_cache}/stage"
mkdir -p "${provision_cache}"
chmod 700 "${provision_cache}"
# A previous run may have left a partial or superseded bundle; the new upload
# must never be mixed with it.
rm -rf "${stage_dir}"
mkdir -p "${stage_dir}"
chmod 700 "${stage_dir}"
tar -C "${stage_dir}" -xf -
REMOTE_STAGE
}

# Shared prologue for the deploy, rollback, and finalize programs: the fixed
# paths derived from one storage root plus the helpers all three need.
coreelec_remote_transaction_prologue() {
  local root="${1:-/storage}"
  cat <<REMOTE_TRANSACTION_HEADER
set -eu
umask 077
storage_root="${root}"
REMOTE_TRANSACTION_HEADER
  coreelec_managed_settings_paths_block
  cat <<'REMOTE_TRANSACTION_COMMON'
provision_cache="${storage_root}/.cache/coreelec-provision"
stage_dir="${provision_cache}/stage"
expanded_dir="${stage_dir}/expanded"
plan_file="${provision_cache}/deploy-plan.tsv"
payload_file="${provision_cache}/settings-payload.conf"
pointer_file="${provision_cache}/current-transaction"
addons_dir="${storage_root}/.kodi/addons"
backup_root="${storage_root}/backup/coreelec-provision"
tab="$(printf '\t')"
transaction=""

fail() {
  printf 'remote transaction: %s\n' "$1" >&2
  exit 1
}

# An add-on ID is not the only manifest field this program interpolates into a
# path: the archive name and the ZIP's top-level directory are too. All three
# are rechecked here, symmetrically, even though the local provisioner and the
# staging validator both checked them first.
valid_addon_id() {
  case "$1" in
    ""|-*|.*) return 1 ;;
    *[!A-Za-z0-9._-]*) return 1 ;;
  esac
  return 0
}

# Uploaded archives are named by their stable 1-based manifest index.
valid_archive_name() {
  case "$1" in
    *.zip) ;;
    *) return 1 ;;
  esac
  case "${1%.zip}" in
    ""|*[!0-9]*) return 1 ;;
  esac
  return 0
}

valid_directory_name() {
  case "$1" in
    ""|-*|.*) return 1 ;;
    *[!A-Za-z0-9._+~-]*) return 1 ;;
  esac
  return 0
}

# Refuses a plan line whose fields are not exactly what the validator promised.
valid_plan_line() {
  valid_archive_name "$1" || return 1
  valid_addon_id "$2" || return 1
  valid_directory_name "$3" || return 1
  return 0
}

copy_into_backup() {
  source_path="$1"
  if [ -f "${source_path}" ]; then
    relative_path="${source_path#${storage_root}/}"
    destination="${transaction}/files/${relative_path}"
    mkdir -p "${transaction}/files/$(dirname "${relative_path}")"
    cp -p "${source_path}" "${destination}"
    # The copy can hold a web-server password or an API token even when the
    # original was left world-readable, so its mode is normalized rather than
    # inherited. Directories stay 0700 through umask 077.
    chmod 600 "${destination}"
    printf 'file %s files/%s\n' "${source_path}" "${relative_path}" \
      >> "${transaction}/MANIFEST.txt"
  fi
}

# Sets `transaction` from the pointer a deployment left behind. Returns 1 when
# nothing is pending; refuses outright when the pointer names something that
# is not a timestamped directory under the backup root.
#
# The pointer is device state that a truncated write, a manual edit, or a
# planted file can corrupt, and `transaction` is exactly what the EXIT trap
# rolls back: removing add-ons, moving directories back, restoring files, and
# clearing the pointer. So the candidate is held in a separate variable and
# only promoted to `transaction` once it is proven to be confined to the
# backup root. A malformed pointer arms nothing and is left in place for the
# operator to look at.
resolve_pending_transaction() {
  [ -f "${pointer_file}" ] || return 1
  pending_candidate="$(cat "${pointer_file}")"
  case "${pending_candidate}" in
    "${backup_root}"/*) ;;
    *) fail "the pending transaction pointer does not name a backup directory: ${pending_candidate}" ;;
  esac
  pending_name="${pending_candidate#${backup_root}/}"
  case "${pending_name}" in
    ""|*[!A-Za-z0-9-]*)
      fail "the pending transaction pointer does not name a timestamp: ${pending_name}"
      ;;
  esac
  [ -d "${pending_candidate}" ] || return 1
  transaction="${pending_candidate}"
  return 0
}

# Undoes everything the transaction recorded: newly deployed add-ons are
# removed, displaced add-ons are moved back, and every settings file the
# transformer wrote is restored from the dated backup or deleted when it did
# not exist before. Kodi is stopped first because it rewrites guisettings.xml
# from memory when it exits.
rollback_transaction() {
  rollback_failed=0
  rollback_marker="${transaction}/.rollback-failed"
  rm -f "${rollback_marker}"
  systemctl stop kodi.service >/dev/null 2>&1 || true

  if [ -f "${transaction}/DEPLOYED.txt" ]; then
    while IFS= read -r deployed_id; do
      [ -n "${deployed_id}" ] || continue
      if valid_addon_id "${deployed_id}"; then
        rm -rf "${addons_dir}/${deployed_id}" || rollback_failed=1
      else
        rollback_failed=1
      fi
    done < "${transaction}/DEPLOYED.txt"
  fi

  if [ -d "${transaction}/rollback/addons" ]; then
    for displaced in "${transaction}/rollback/addons/"*; do
      [ -e "${displaced}" ] || continue
      displaced_id="${displaced##*/}"
      if valid_addon_id "${displaced_id}"; then
        rm -rf "${addons_dir}/${displaced_id}"
        mv "${displaced}" "${addons_dir}/${displaced_id}" || rollback_failed=1
      else
        rollback_failed=1
      fi
    done
  fi

  # Every managed settings file is restored from the backup taken before the
  # transformer ran, not from the list of what it reported applying: a
  # transformer that fails part way through has already rewritten some files
  # but has not reported any of them yet.
  if [ -d "${transaction}/files" ]; then
    find "${transaction}/files" -type f -print | while IFS= read -r backup_copy; do
      backup_relative="${backup_copy#${transaction}/files/}"
      restore_path="${storage_root}/${backup_relative}"
      mkdir -p "$(dirname "${restore_path}")" 2>/dev/null || :
      cp -p "${backup_copy}" "${restore_path}" || : > "${rollback_marker}"
    done
  fi

  # Anything the transformer created that had no previous version is removed;
  # the paths it replaced were already restored above.
  if [ -f "${transaction}/APPLIED.txt" ]; then
    while IFS= read -r applied_path; do
      [ -n "${applied_path}" ] || continue
      case "${applied_path}" in
        "${storage_root}"/*) ;;
        *)
          rollback_failed=1
          continue
          ;;
      esac
      applied_relative="${applied_path#${storage_root}/}"
      if [ ! -f "${transaction}/files/${applied_relative}" ]; then
        rm -f "${applied_path}" || rollback_failed=1
      fi
    done < "${transaction}/APPLIED.txt"
  fi

  if [ -f "${rollback_marker}" ]; then
    rollback_failed=1
    rm -f "${rollback_marker}"
  fi

  systemctl restart tz-data.service >/dev/null 2>&1 || true
  systemctl start kodi.service >/dev/null 2>&1 || true

  # STATE and the pointer are how the operator, a later run, and Task 6 learn
  # what happened here. A rollback whose outcome cannot be recorded is not a
  # completed rollback, so a failed write is a rollback failure and the
  # pointer stays behind rather than being cleared on an unrecorded state.
  if [ "${rollback_failed}" -eq 0 ]; then
    printf 'rolled-back\n' > "${transaction}/STATE" 2>/dev/null || rollback_failed=1
  fi
  if [ "${rollback_failed}" -eq 0 ]; then
    rm -f "${pointer_file}" 2>/dev/null || rollback_failed=1
    if [ -e "${pointer_file}" ]; then
      rollback_failed=1
    fi
  fi

  if [ "${rollback_failed}" -ne 0 ]; then
    printf 'ROLLBACK INCOMPLETE. Retained transaction: %s\n' "${transaction}" >&2
    printf 'ROLLBACK INCOMPLETE. Retained staging: %s\n' "${stage_dir}" >&2
    printf 'ROLLBACK INCOMPLETE. Retained pointer: %s\n' "${pointer_file}" >&2
    printf 'incomplete-rollback\n' > "${transaction}/STATE" 2>/dev/null || true
    return 1
  fi

  return 0
}
REMOTE_TRANSACTION_COMMON
}

coreelec_remote_deploy_script() {
  local root="${1:-/storage}"
  coreelec_remote_transaction_prologue "${root}"
  cat <<'REMOTE_DEPLOY_PROLOGUE'
transaction_state="staging"

finish_transaction() {
  exit_status=$?
  trap - EXIT HUP INT TERM
  # The payload holds every secret this run transports, so it never outlives
  # the transaction on any exit path.
  rm -f "${payload_file}" "${payload_file}.provision-new"
  if [ "${transaction_state}" = "deployed" ]; then
    exit "${exit_status}"
  fi
  if [ -n "${transaction}" ]; then
    printf 'deployment failed while %s; rolling back\n' "${transaction_state}" >&2
    if rollback_transaction; then
      printf 'the device was restored to its pre-deployment state\n' >&2
    fi
  fi
  if [ "${exit_status}" -eq 0 ]; then
    exit 1
  fi
  exit "${exit_status}"
}
trap finish_transaction EXIT HUP INT TERM

[ -d "${stage_dir}" ] || fail "no uploaded artifact bundle was found: ${stage_dir}"
[ -f "${stage_dir}/deploy.tsv" ] || fail "the uploaded bundle has no deploy.tsv manifest"
[ -f "${payload_file}" ] || fail "no settings payload was uploaded: ${payload_file}"

if [ -f "${pointer_file}" ]; then
  if resolve_pending_transaction; then
    pending="${transaction}"
    transaction=""
    fail "a deployment transaction from an earlier run is still pending and this run changed nothing: ${pending}. Verify the device, then commit that transaction with --finalize-deployment or undo it with --rollback-deployment before deploying again"
  fi
  # Only a well-formed pointer whose directory is gone reaches here: a
  # malformed one already refused the run. Clearing it is correct, but it
  # means an earlier run's rollback material no longer exists, so it is
  # reported rather than dropped in silence.
  printf 'discarding a stale transaction pointer: %s no longer exists\n' \
    "$(cat "${pointer_file}")" >&2
  rm -f "${pointer_file}"
  transaction=""
fi

# --- Phase 1: validate and expand the bundle while Kodi keeps running -------
# Nothing outside the provisioning cache is touched here, so a bad bundle
# never interrupts playback and never needs a rollback.
rm -rf "${expanded_dir}"
mkdir -p "${expanded_dir}"
rm -f "${plan_file}"

python3 - "${stage_dir}" > "${plan_file}" <<'PYTHON_DEPLOY_PLAN'
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

STAGE = sys.argv[1]
MANIFEST = os.path.join(STAGE, "deploy.tsv")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~-]*$")
ARCHIVE_PATTERN = re.compile(r"^[0-9]+\.zip$")
DIRECTORY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+~-]*$")


def reject(message):
    raise SystemExit("deployment manifest rejected: " + message)


def top_level_directory(archive, addon_id):
    """The single root directory of a ZIP, refusing every entry name that
    could escape the directory it is extracted into."""
    tops = set()
    for name in archive.namelist():
        if not name:
            reject("%s contains an empty entry name" % addon_id)
        if name.startswith("/") or "\\" in name:
            reject("%s contains an unsafe entry: %s" % (addon_id, name))
        segments = name.split("/")
        for position, segment in enumerate(segments):
            if segment in (".", ".."):
                reject("%s contains a traversal entry: %s" % (addon_id, name))
            if segment == "" and position != len(segments) - 1:
                reject("%s contains an empty path segment: %s"
                       % (addon_id, name))
        tops.add(segments[0])
    if len(tops) != 1:
        reject("%s must have exactly one top-level directory, found %d"
               % (addon_id, len(tops)))
    top = tops.pop()
    if not DIRECTORY_PATTERN.match(top):
        reject("%s has an unsupported top-level directory: %s"
               % (addon_id, top))
    return top


plan = []
seen = set()
with open(MANIFEST, "r", encoding="utf-8") as handle:
    for number, raw_line in enumerate(handle, start=1):
        line = raw_line.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            reject("line %d does not have four tab-separated fields" % number)
        index, addon_id, version, archive_name = fields
        if not index.isdigit():
            reject("line %d has a non-numeric index: %s" % (number, index))
        if not ID_PATTERN.match(addon_id):
            reject("line %d has an unsupported add-on ID: %s"
                   % (number, addon_id))
        if not VERSION_PATTERN.match(version):
            reject("line %d has an unsupported version for %s: %s"
                   % (number, addon_id, version))
        if not ARCHIVE_PATTERN.match(archive_name):
            reject("line %d has an unsupported archive name for %s: %s"
                   % (number, addon_id, archive_name))
        if addon_id in seen:
            reject("line %d repeats add-on ID %s" % (number, addon_id))
        seen.add(addon_id)

        archive_path = os.path.join(STAGE, archive_name)
        if not os.path.isfile(archive_path):
            reject("%s is missing its uploaded archive %s"
                   % (addon_id, archive_name))
        try:
            archive = zipfile.ZipFile(archive_path)
        except Exception:
            reject("%s did not upload as a readable ZIP archive" % addon_id)
        with archive:
            top = top_level_directory(archive, addon_id)
            try:
                document = archive.read(top + "/addon.xml")
            except KeyError:
                reject("%s has no %s/addon.xml" % (addon_id, top))
            try:
                declared = ET.fromstring(document)
            except ET.ParseError:
                reject("%s has an unparseable addon.xml" % addon_id)
        # The ZIP root directory is not the add-on ID for several pinned
        # artifacts, so identity comes from addon.xml and never from the
        # directory name.
        if declared.get("id") != addon_id:
            reject("%s declares add-on ID %s in addon.xml"
                   % (addon_id, declared.get("id")))
        if declared.get("version") != version:
            reject("%s declares version %s in addon.xml"
                   % (addon_id, declared.get("version")))
        plan.append((archive_name, addon_id, top))

if not plan:
    reject("no add-on was selected for deployment")

for archive_name, addon_id, top in plan:
    sys.stdout.write("%s\t%s\t%s\n" % (archive_name, addon_id, top))
PYTHON_DEPLOY_PLAN

[ -s "${plan_file}" ] || fail "the uploaded bundle selected no add-ons"

while IFS="${tab}" read -r plan_archive plan_id plan_top; do
  valid_plan_line "${plan_archive}" "${plan_id}" "${plan_top}" \
    || fail "unsupported deployment plan line: ${plan_archive} ${plan_id} ${plan_top}"
  mkdir -p "${expanded_dir}/${plan_id}"
  # Add-on payloads are public content, so they keep the 0755/0644 modes Kodi
  # expects instead of inheriting the transaction's private umask.
  ( umask 022; unzip -o -q -d "${expanded_dir}/${plan_id}" "${stage_dir}/${plan_archive}" ) \
    || fail "could not expand ${plan_archive} for ${plan_id}"
  [ -f "${expanded_dir}/${plan_id}/${plan_top}/addon.xml" ] \
    || fail "the expanded ${plan_id} has no ${plan_top}/addon.xml"
done < "${plan_file}"

# --- Phase 2: mutate the device inside a recoverable transaction ------------
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
transaction="${backup_root}/${stamp}"
collision=1
while [ -e "${transaction}" ]; do
  collision=$((collision + 1))
  transaction="${backup_root}/${stamp}-${collision}"
done
mkdir -p "${transaction}/files" "${transaction}/rollback/addons"
# Only this run's own subtree is tightened. /storage/backup is CoreELEC's own
# backup location, shared with the device's other tooling, so its mode is left
# exactly as the device set it; umask 077 already makes anything created here
# private.
chmod 700 "${backup_root}" "${transaction}"
: > "${transaction}/DEPLOYED.txt"
: > "${transaction}/APPLIED.txt"
{
  printf 'created_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname=%s\n' "$(hostname)"
  printf 'storage_root=%s\n' "${storage_root}"
  printf 'transaction=%s\n' "${transaction}"
} > "${transaction}/MANIFEST.txt"
chmod 600 "${transaction}/MANIFEST.txt" "${transaction}/DEPLOYED.txt" "${transaction}/APPLIED.txt"
printf 'staged\n' > "${transaction}/STATE"
# Written before anything moves so an interrupted session still leaves the
# operator, and Task 6's verification, a handle on the material to undo it.
printf '%s\n' "${transaction}" > "${pointer_file}"

transaction_state="stopping Kodi"
# Kodi rewrites guisettings.xml from memory when it exits and rescans add-ons
# on start, so it is stopped exactly once, around the whole transaction.
systemctl stop kodi.service >/dev/null 2>&1 || true

transaction_state="backing up replaced paths"
managed_settings_paths | while IFS= read -r managed_relative; do
  [ -n "${managed_relative}" ] || continue
  copy_into_backup "${storage_root}/${managed_relative}"
done

transaction_state="replacing add-ons"
mkdir -p "${addons_dir}"
while IFS="${tab}" read -r plan_archive plan_id plan_top; do
  valid_plan_line "${plan_archive}" "${plan_id}" "${plan_top}" \
    || fail "unsupported deployment plan line: ${plan_archive} ${plan_id} ${plan_top}"
  destination="${addons_dir}/${plan_id}"
  if [ -e "${destination}" ]; then
    # Moving the previous directory into the dated transaction is its backup:
    # it is complete, instant, and cannot half-copy a large skin.
    mv "${destination}" "${transaction}/rollback/addons/${plan_id}"
    printf 'addon %s replaced rollback/addons/%s\n' "${plan_id}" "${plan_id}" \
      >> "${transaction}/MANIFEST.txt"
  else
    printf 'addon %s created -\n' "${plan_id}" >> "${transaction}/MANIFEST.txt"
  fi
  mv "${expanded_dir}/${plan_id}/${plan_top}" "${destination}"
  printf '%s\n' "${plan_id}" >> "${transaction}/DEPLOYED.txt"
done < "${plan_file}"

# --- Phase 3: settings, which may reference the add-ons just deployed -------
transaction_state="applying settings"
python3 - "${storage_root}" "${payload_file}" > "${transaction}/applied.raw" <<'PYTHON_KODI_SETTINGS'
REMOTE_DEPLOY_PROLOGUE

  coreelec_settings_transformer_source

  cat <<'REMOTE_DEPLOY_EPILOGUE'
PYTHON_KODI_SETTINGS

# Only paths are recorded, never values: the list is what rollback restores.
sed -n 's/^settings applied: //p' "${transaction}/applied.raw" \
  > "${transaction}/APPLIED.txt"
rm -f "${transaction}/applied.raw"
chmod 600 "${transaction}/APPLIED.txt"
while IFS= read -r applied_path; do
  [ -n "${applied_path}" ] || continue
  printf 'settings applied: %s\n' "${applied_path}" >&2
done < "${transaction}/APPLIED.txt"

transaction_state="restarting services"
systemctl restart tz-data.service >/dev/null 2>&1 || true
# stdout is the transaction path and nothing else, because the Mac captures it
# through a command substitution; systemctl diagnostics stay on stderr.
systemctl start kodi.service >/dev/null || fail "Kodi did not start after deployment"

# The emergency restart is disarmed here, but the rollback material stays on
# the device until verification finalizes or undoes this transaction.
transaction_state="deployed"
trap - EXIT HUP INT TERM
printf 'deployed\n' > "${transaction}/STATE"
rm -f "${payload_file}" "${payload_file}.provision-new" "${plan_file}"
rm -rf "${expanded_dir}"
printf '%s\n' "${transaction}"
REMOTE_DEPLOY_EPILOGUE
}

coreelec_remote_rollback_script() {
  local root="${1:-/storage}"
  coreelec_remote_transaction_prologue "${root}"
  cat <<'REMOTE_ROLLBACK'
resolve_pending_transaction || fail "no pending deployment transaction was found"
if rollback_transaction; then
  rm -rf "${stage_dir}" "${expanded_dir}"
  rm -f "${plan_file}" "${payload_file}" "${payload_file}.provision-new"
  printf '%s\n' "${transaction}"
  exit 0
fi
exit 1
REMOTE_ROLLBACK
}

coreelec_remote_finalize_script() {
  local root="${1:-/storage}"
  coreelec_remote_transaction_prologue "${root}"
  cat <<'REMOTE_FINALIZE'
resolve_pending_transaction || fail "no pending deployment transaction was found"
# The dated backup and its manifest are kept as the record of what changed;
# only the material that exists to undo the change is released.
rm -rf "${transaction}/rollback"
rm -rf "${stage_dir}" "${expanded_dir}"
rm -f "${plan_file}" "${payload_file}" "${payload_file}.provision-new"
printf 'finalized_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${transaction}/MANIFEST.txt"
printf 'committed\n' > "${transaction}/STATE"
rm -f "${pointer_file}"
printf '%s\n' "${transaction}"
REMOTE_FINALIZE
}

# Internal test entry point: prints one remote script instead of running it.
coreelec_emit_remote_script() {
  local name="$1" root="${2:-/storage}"
  case "${name}" in
    backup) coreelec_remote_backup_script "${root}" ;;
    payload) coreelec_remote_payload_script "${root}" ;;
    stage) coreelec_remote_stage_script "${root}" ;;
    deploy) coreelec_remote_deploy_script "${root}" ;;
    rollback) coreelec_remote_rollback_script "${root}" ;;
    finalize) coreelec_remote_finalize_script "${root}" ;;
    *)
      die "--emit-remote-script expects backup, payload, stage, deploy, rollback, or finalize, not: ${name}"
      ;;
  esac
}

# Precedence: built-in safe defaults, then the selected configuration file,
# then explicit CLI options, then secret environment variables (checked by
# coreelec_config_validate). --config is parsed here in a lightweight,
# non-consuming pre-scan so the file loads before the full CLI pass below
# applies any explicit overrides. --help/--version are honored immediately in
# this same pre-scan so they never require a readable configuration file.
coreelec_config_defaults
config_file_override=""
config_scan_index=0
config_scan_args=("$@")
while (( config_scan_index < ${#config_scan_args[@]} )); do
  case "${config_scan_args[${config_scan_index}]}" in
    -h|--help)
      usage
      exit 0
      ;;
    --version)
      printf '%s\n' "${SCRIPT_VERSION}"
      exit 0
      ;;
    --transform-fixture)
      (( config_scan_index + 2 < ${#config_scan_args[@]} )) \
        || die "--transform-fixture requires ROOT and PAYLOAD"
      coreelec_settings_transform_fixture \
        "${config_scan_args[$((config_scan_index + 1))]}" \
        "${config_scan_args[$((config_scan_index + 2))]}"
      exit 0
      ;;
    --emit-remote-script)
      (( config_scan_index + 1 < ${#config_scan_args[@]} )) \
        || die "--emit-remote-script requires NAME"
      emit_script_root="/storage"
      if (( config_scan_index + 2 < ${#config_scan_args[@]} )); then
        emit_script_root="${config_scan_args[$((config_scan_index + 2))]}"
      fi
      coreelec_emit_remote_script \
        "${config_scan_args[$((config_scan_index + 1))]}" \
        "${emit_script_root}"
      exit 0
      ;;
    --render-remote-deploy-script)
      # A named alias for `--emit-remote-script deploy`, kept because the test
      # suite and the task brief both refer to it. It dispatches through the
      # same emitter so the two modes cannot drift apart.
      emit_script_root="/storage"
      if (( config_scan_index + 1 < ${#config_scan_args[@]} )); then
        emit_script_root="${config_scan_args[$((config_scan_index + 1))]}"
      fi
      coreelec_emit_remote_script deploy "${emit_script_root}"
      exit 0
      ;;
    --config)
      (( config_scan_index + 1 < ${#config_scan_args[@]} )) || die "--config requires a value"
      config_file_override="${config_scan_args[$((config_scan_index + 1))]}"
      config_scan_index=$((config_scan_index + 2))
      ;;
    *)
      config_scan_index=$((config_scan_index + 1))
      ;;
  esac
done
[[ -z "${config_file_override}" ]] || CONFIG_FILE="${config_file_override}"
coreelec_config_load "${CONFIG_FILE}"

while (( $# > 0 )); do
  case "$1" in
    --target)
      (( $# >= 2 )) || die "--target requires a value"
      TARGET="$2"
      shift 2
      ;;
    --config)
      (( $# >= 2 )) || die "--config requires a value"
      shift 2
      ;;
    --check-config)
      CHECK_CONFIG="1"
      shift
      ;;
    --check-artifacts)
      CHECK_ARTIFACTS="1"
      shift
      ;;
    --identity)
      (( $# >= 2 )) || die "--identity requires a value"
      IDENTITY_FILE="$2"
      shift 2
      ;;
    --ssh-port)
      (( $# >= 2 )) || die "--ssh-port requires a value"
      coreelec_config_apply_cli "SSH_PORT" "$2"
      shift 2
      ;;
    --kodi-port)
      (( $# >= 2 )) || die "--kodi-port requires a value"
      coreelec_config_apply_cli "KODI_PORT" "$2"
      shift 2
      ;;
    --kodi-user)
      (( $# >= 2 )) || die "--kodi-user requires a value"
      coreelec_config_apply_cli "KODI_USER" "$2"
      shift 2
      ;;
    --addon)
      (( $# >= 2 )) || die "--addon requires a value"
      coreelec_config_add_cli_addon "$2"
      shift 2
      ;;
    --print-addon-selection)
      (( $# >= 2 )) || die "--print-addon-selection requires a manifest path"
      PRINT_ADDON_SELECTION="$2"
      shift 2
      ;;
    --finalize-deployment)
      DEPLOY_ACTION="finalize"
      shift
      ;;
    --rollback-deployment)
      DEPLOY_ACTION="rollback"
      shift
      ;;
    --with-youtube)
      coreelec_config_add_cli_addon "plugin.video.youtube"
      shift
      ;;
    --report-dir)
      (( $# >= 2 )) || die "--report-dir requires a value"
      coreelec_config_apply_cli "REPORT_DIR" "$2"
      shift 2
      ;;
    --expected-release)
      (( $# >= 2 )) || die "--expected-release requires a value"
      coreelec_config_apply_cli "EXPECTED_RELEASE" "$2"
      shift 2
      ;;
    --no-kodi)
      coreelec_config_apply_cli "APPLY_KODI" "0"
      shift
      ;;
    --no-harden)
      coreelec_config_apply_cli "HARDEN_SSH" "0"
      shift
      ;;
    --force-unsupported)
      coreelec_config_apply_cli "FORCE_UNSUPPORTED" "1"
      shift
      ;;
    --yes)
      coreelec_config_apply_cli "ASSUME_YES" "1"
      shift
      ;;
    --version)
      printf '%s\n' "${SCRIPT_VERSION}"
      exit 0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

# macOS ships Bash 3.2, where expanding "${array[@]}" of an *empty* array
# under `set -u` is an unbound-variable error rather than an empty list. Every
# optional array in this script is therefore iterated through the `${a[@]+...}`
# form, which is defined for an empty array in every Bash version and still
# keeps elements that contain spaces intact. ADDONS is empty on the ordinary
# run (no --addon means "the whole lock"), so this is the common path.

# Prints the manifest lines Task 2 validated that this run should deploy. With
# no --addon the whole locked manifest is selected; with one or more, the
# selection is narrowed to those IDs and an ID that is not locked is refused
# rather than silently ignored, because --addon selects from the lock, it does
# not add to it.
coreelec_addon_selection() {
  local manifest="$1"
  local index id version filename requested selected_ids known_ids
  local selected=0 total=0

  [[ -r "${manifest}" ]] || die "Artifact manifest is not readable: ${manifest}"

  selected_ids=$'\n'
  if (( ${#ADDONS[@]} > 0 )); then
    known_ids=$'\n'
    while IFS=$'\t' read -r index id version filename; do
      [[ -n "${id}" ]] || continue
      known_ids="${known_ids}${id}"$'\n'
    done < "${manifest}"
    for requested in ${ADDONS[@]+"${ADDONS[@]}"}; do
      case "${known_ids}" in
        *$'\n'"${requested}"$'\n'*) ;;
        *)
          die "--addon ${requested} is not in the locked artifact manifest; add an ADDON_ARTIFACT record for it first"
          ;;
      esac
      selected_ids="${selected_ids}${requested}"$'\n'
    done
  fi

  while IFS=$'\t' read -r index id version filename; do
    [[ -n "${id}" ]] || continue
    total=$((total + 1))
    if (( ${#ADDONS[@]} > 0 )); then
      case "${selected_ids}" in
        *$'\n'"${id}"$'\n'*) ;;
        *) continue ;;
      esac
    fi
    printf '%s\t%s\t%s\t%s\n' "${index}" "${id}" "${version}" "${filename}"
    selected=$((selected + 1))
  done < "${manifest}"

  (( selected > 0 )) || die "No pinned add-on artifacts were selected for deployment"
  if (( selected < total )); then
    warn "Only ${selected} of ${total} locked add-ons were selected; dependencies of the selection are not resolved automatically"
  fi
}

# Refuses an --addon that is not in the locked configuration. This is a purely
# local decision -- the IDs come from ADDON_ARTIFACT records, not from the
# device -- so it runs in the preflight, before the administrator key is
# installed, the backup is taken, or SSH is hardened. Catching it later would
# abort a run that had already changed the device three times.
coreelec_validate_addon_selection() {
  local requested record known_ids
  (( ${#ADDONS[@]} > 0 )) || return 0

  known_ids=$'\n'
  for record in ${ADDON_ARTIFACTS[@]+"${ADDON_ARTIFACTS[@]}"}; do
    coreelec_artifact_parse "${record}"
    known_ids="${known_ids}${ARTIFACT_ID}"$'\n'
  done

  for requested in ${ADDONS[@]+"${ADDONS[@]}"}; do
    validate_identifier "Add-on ID" "${requested}"
    case "${known_ids}" in
      *$'\n'"${requested}"$'\n'*) ;;
      *)
        die "--addon ${requested} is not in the locked artifact manifest; add an ADDON_ARTIFACT record for it first"
        ;;
    esac
  done
}

if [[ -n "${PRINT_ADDON_SELECTION}" ]]; then
  coreelec_addon_selection "${PRINT_ADDON_SELECTION}"
  exit 0
fi

if [[ "${CHECK_CONFIG}" == "1" || "${CHECK_ARTIFACTS}" == "1" ]]; then
  coreelec_config_validate
  info "Configuration OK: ${CONFIG_FILE}"
  if [[ "${CHECK_ARTIFACTS}" == "1" ]]; then
    require_command curl
    require_command shasum
    require_command unzip
    require_command xmllint
    TASK_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/coreelec-provision.XXXXXX")"
    chmod 700 "${TASK_TEMP_DIR}"
    coreelec_artifacts_download_and_validate "${TASK_TEMP_DIR}/artifacts"
    info "Artifacts OK: ${#ADDON_ARTIFACTS[@]} artifact(s) downloaded, checksum-verified, and inspected"
  fi
  exit 0
fi

[[ -n "${TARGET}" ]] || {
  usage >&2
  exit 2
}

[[ "$(uname -s)" == "Darwin" ]] || die "This edition of the provisioner is intended to run on macOS"

validate_host "${TARGET}"
validate_port "SSH port" "${SSH_PORT}"
validate_port "Kodi port" "${KODI_PORT}"
validate_identifier "Kodi username" "${KODI_USER}"
validate_identifier "Expected release" "${EXPECTED_RELEASE}"

coreelec_config_validate

# The add-on selection is resolved and refused here, before the first remote
# call of any kind.
coreelec_validate_addon_selection

require_command ssh
require_command ssh-keygen
require_command ssh-add
require_command openssl
require_command curl
require_command security
require_command grep
require_command sed
require_command tr

SSH_COMMON=(
  -p "${SSH_PORT}"
  -o ConnectTimeout=12
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=accept-new
)
SSH_KEY_OPTIONS=(
  -i "${IDENTITY_FILE}"
  -o IdentitiesOnly=yes
  -o PreferredAuthentications=publickey
  -o PasswordAuthentication=no
  -o KbdInteractiveAuthentication=no
)
REMOTE="root@${TARGET}"

ssh_keyed() {
  ssh "${SSH_COMMON[@]}" "${SSH_KEY_OPTIONS[@]}" "${REMOTE}" "$@"
}

ssh_keyed_batch() {
  ssh "${SSH_COMMON[@]}" "${SSH_KEY_OPTIONS[@]}" -o BatchMode=yes "${REMOTE}" "$@"
}

ssh_password() {
  ssh "${SSH_COMMON[@]}" \
    -o PubkeyAuthentication=no \
    -o PreferredAuthentications=keyboard-interactive,password \
    -o NumberOfPasswordPrompts=3 \
    "${REMOTE}" "$@"
}

create_or_load_admin_key() {
  local identity_dir
  identity_dir="$(dirname "${IDENTITY_FILE}")"
  mkdir -p "${identity_dir}"
  chmod 700 "${identity_dir}"

  if [[ ! -f "${IDENTITY_FILE}" ]]; then
    info "Creating dedicated Ed25519 administrator key: ${IDENTITY_FILE}"
    info "Choose a key passphrase when prompted; macOS Keychain can retain it."
    ssh-keygen -t ed25519 -a 64 -C "coreelec-admin@$(hostname -s)" -f "${IDENTITY_FILE}"
  fi

  chmod 600 "${IDENTITY_FILE}"
  if [[ ! -f "${IDENTITY_FILE}.pub" ]]; then
    info "Rebuilding missing public key file"
    ssh-keygen -y -f "${IDENTITY_FILE}" > "${IDENTITY_FILE}.pub"
  fi
  chmod 644 "${IDENTITY_FILE}.pub"

  if ! ssh-add --apple-use-keychain "${IDENTITY_FILE}" >/dev/null 2>&1; then
    warn "The key was not added to macOS Keychain; SSH may ask for its passphrase during this run"
    ssh-add "${IDENTITY_FILE}" >/dev/null 2>&1 || true
  fi
}

install_public_key_if_needed() {
  if [[ "${KEY_ALREADY_ACCEPTED}" == "1" ]]; then
    info "Dedicated administrator key is already accepted"
    return
  fi

  info "Installing the administrator public key"
  info "Enter the temporary CoreELEC root password when SSH prompts."

  if ! sed -e 's/\r$//' "${IDENTITY_FILE}.pub" | ssh_password 'sh -c '\''
    set -eu
    umask 077
    mkdir -p /storage/.ssh
    chmod 700 /storage/.ssh
    candidate=/storage/.ssh/authorized_keys.provision-candidate
    authorized=/storage/.ssh/authorized_keys
    rm -f "${candidate}"
    cat > "${candidate}"
    test -s "${candidate}"
    key_blob="$(awk '\''{ print $2; exit }'\'' "${candidate}")"
    test -n "${key_blob}"
    touch "${authorized}"
    if ! grep -Fq "${key_blob}" "${authorized}"; then
      cat "${candidate}" >> "${authorized}"
    fi
    rm -f "${candidate}"
    chmod 600 "${authorized}"
  '\'''; then
    die "Could not install the SSH public key. Confirm SSH is enabled and the temporary root password is correct."
  fi

  info "Proving key-only authentication in a new SSH connection"
  ssh_keyed true || die "Public-key authentication failed; password authentication has not been disabled"
}

remote_identity() {
  ssh_keyed 'sh -c '\''
    printf "release_begin\n"
    cat /etc/os-release 2>/dev/null || true
    cat /etc/release 2>/dev/null || true
    printf "release_end\n"
    printf "kernel=%s\n" "$(uname -r)"
    printf "model="
    tr -d "\000" < /proc/device-tree/model 2>/dev/null || true
    printf "\n"
    printf "hostname=%s\n" "$(hostname)"
  '\'''
}

remote_identity_with_password() {
  ssh_password 'sh -c '\''
    printf "release_begin\n"
    cat /etc/os-release 2>/dev/null || true
    cat /etc/release 2>/dev/null || true
    printf "release_end\n"
    printf "kernel=%s\n" "$(uname -r)"
    printf "model="
    tr -d "\000" < /proc/device-tree/model 2>/dev/null || true
    printf "\n"
    printf "hostname=%s\n" "$(hostname)"
  '\'''
}

validate_remote() {
  local identity="$1"
  local failed="0"

  if ! printf '%s\n' "${identity}" | grep -qi 'coreelec'; then
    warn "The remote host did not identify itself as CoreELEC"
    failed="1"
  fi
  if ! printf '%s\n' "${identity}" | grep -Fq "${EXPECTED_RELEASE}"; then
    warn "Expected CoreELEC release substring '${EXPECTED_RELEASE}' was not found"
    failed="1"
  fi
  if ! printf '%s\n' "${identity}" | grep -Fqi 'Amlogic-ng'; then
    warn "The remote release metadata does not identify Amlogic-ng"
    failed="1"
  fi
  if ! printf '%s\n' "${identity}" | grep -Eqi 'Ugoos.*AM6'; then
    warn "The device-tree model does not clearly identify a Ugoos AM6-family device"
  fi

  if [[ "${failed}" == "1" && "${FORCE_UNSUPPORTED}" != "1" ]]; then
    die "Target validation failed. Recheck the target, or use --force-unsupported after reviewing the warnings."
  fi
}

create_remote_backup() {
  info "Creating a selective pre-provisioning backup on the CoreELEC STORAGE partition" >&2
  coreelec_remote_backup_script | ssh_keyed 'sh -s'
}

harden_remote_ssh() {
  [[ "${HARDEN_SSH}" == "1" ]] || {
    warn "SSH password authentication was left enabled because --no-harden was selected"
    return
  }

  info "Disabling SSH password authentication"
  ssh_keyed 'sh -s' <<'REMOTE_SSH_CONFIG'
set -eu
umask 077
mkdir -p /storage/.cache/services
temporary="/storage/.cache/services/sshd.conf.provision-new"
# Removed first so the file is created fresh under umask 077 rather than
# inheriting the mode, hard links, or symlink target of a leftover one.
rm -f "${temporary}"
cat > "${temporary}" <<'SSHD_CONFIG'
SSH_ARGS="-o 'PasswordAuthentication no'"
SSHD_DISABLE_PW_AUTH="true"
SSHD_CONFIG
chmod 600 "${temporary}"
mv "${temporary}" /storage/.cache/services/sshd.conf
REMOTE_SSH_CONFIG

  set +e
  ssh_keyed 'systemctl restart sshd.service' >/dev/null 2>&1
  set -e
  sleep 2

  info "Verifying SSH after the daemon restart"
  ssh_keyed 'systemctl is-active --quiet sshd.service && test -s /storage/.ssh/authorized_keys' \
    || die "SSH did not recover cleanly. Use the local console to inspect /storage/.cache/services/sshd.conf."
}

keychain_service_name() {
  local sanitized
  sanitized="$(printf '%s' "${TARGET}" | tr -c 'A-Za-z0-9._-' '_')"
  printf 'coreelec-kodi-ha-%s' "${sanitized}"
}

prepare_kodi_password() {
  local service_name="$1"
  KODI_WEB_PASSWORD="$(security find-generic-password -a "${KODI_USER}" -s "${service_name}" -w 2>/dev/null || true)"
  if [[ -n "${KODI_WEB_PASSWORD}" ]]; then
    info "Reusing the Kodi/Home Assistant credential stored in macOS Keychain"
    return
  fi

  KODI_WEB_PASSWORD="$(openssl rand -hex 24)"
  [[ -n "${KODI_WEB_PASSWORD}" ]] || die "Could not generate the Kodi web password"
  security add-generic-password \
    -U \
    -a "${KODI_USER}" \
    -s "${service_name}" \
    -l "Kodi Home Assistant access for ${TARGET}" \
    -w "${KODI_WEB_PASSWORD}" >/dev/null
  info "Generated the Kodi/Home Assistant password and stored it in macOS Keychain"
}

coreelec_settings_payload_entry() {
  # Values are encoded by a shell builtin piped into openssl, so no secret is
  # ever visible in a process argument list or in the shell's history.
  local key="$1" value="$2"
  printf '%s=%s\n' "${key}" "$(printf '%s' "${value}" | openssl base64 -A)"
}

coreelec_settings_payload_secret() {
  # Presence is recorded separately so the transformer never has to infer
  # "absent" from an empty decoded string.
  local key="$1" value="$2" present="0"
  [[ -n "${value}" ]] && present="1"
  coreelec_settings_payload_entry "HAVE_${key}" "${present}"
  if [[ "${present}" == "1" ]]; then
    coreelec_settings_payload_entry "${key}" "${value}"
  fi
  return 0
}

coreelec_settings_payload() {
  coreelec_settings_payload_entry TIMEZONE "${TIMEZONE}"
  coreelec_settings_payload_entry TIMEZONE_COUNTRY "${TIMEZONE_COUNTRY}"
  coreelec_settings_payload_entry LOCALE_LANGUAGE "${LOCALE_LANGUAGE}"
  coreelec_settings_payload_entry LOCALE_COUNTRY "${LOCALE_COUNTRY}"
  coreelec_settings_payload_entry KEYBOARD_LAYOUT "${KEYBOARD_LAYOUT}"
  coreelec_settings_payload_entry ADDON_UPDATE_MODE "${ADDON_UPDATE_MODE}"
  coreelec_settings_payload_entry KODI_WEB_USER "${KODI_USER}"
  coreelec_settings_payload_entry KODI_WEB_PORT "${KODI_PORT}"
  coreelec_settings_payload_entry HOME_ASSISTANT_URL "${HOME_ASSISTANT_URL}"
  coreelec_settings_payload_entry HOME_ASSISTANT_WEATHER_ENTITY "${HOME_ASSISTANT_WEATHER_ENTITY}"
  coreelec_settings_payload_entry HOME_ASSISTANT_SUN_ENTITY "${HOME_ASSISTANT_SUN_ENTITY}"
  coreelec_settings_payload_entry NEXTPVR_HOST "${NEXTPVR_HOST}"
  coreelec_settings_payload_entry NEXTPVR_PORT "${NEXTPVR_PORT}"
  coreelec_settings_payload_entry NEXTPVR_PROTOCOL "${NEXTPVR_PROTOCOL}"
  coreelec_settings_payload_entry NEXTPVR_INSTANCE_NAME "${NEXTPVR_INSTANCE_NAME}"
  coreelec_settings_payload_entry PLEX_SERVER_HOST "${PLEX_SERVER_HOST}"
  coreelec_settings_payload_entry PLEX_SERVER_PORT "${PLEX_SERVER_PORT}"
  coreelec_settings_payload_entry PLEX_SERVER_NAME "${PLEX_SERVER_NAME}"
  coreelec_settings_payload_entry PLEX_PROFILE_IDS "${PLEX_PROFILE_IDS}"

  coreelec_settings_payload_secret KODI_WEB_PASSWORD "${KODI_WEB_PASSWORD}"
  coreelec_settings_payload_secret OMDB_API_KEY "${OMDB_API_KEY:-}"
  coreelec_settings_payload_secret MDBLIST_API_KEY "${MDBLIST_API_KEY:-}"
  coreelec_settings_payload_secret YOUTUBE_API_KEY "${YOUTUBE_API_KEY:-}"
  coreelec_settings_payload_secret YOUTUBE_CLIENT_ID "${YOUTUBE_CLIENT_ID:-}"
  coreelec_settings_payload_secret YOUTUBE_CLIENT_SECRET "${YOUTUBE_CLIENT_SECRET:-}"
  coreelec_settings_payload_secret HOME_ASSISTANT_TOKEN "${HOME_ASSISTANT_TOKEN:-}"
  coreelec_settings_payload_secret NEXTPVR_PIN "${NEXTPVR_PIN:-}"
  coreelec_settings_payload_secret PLEX_TOKEN "${PLEX_TOKEN:-}"
}

upload_kodi_settings_payload() {
  # The payload is streamed over the existing SSH channel into a mode-0600
  # file, and the remote trap removes it even if the transformer fails. The
  # script text is embedded in a single-quoted remote `sh -c` argument, so it
  # must never contain a single quote of its own.
  local script
  script="$(coreelec_remote_payload_script)"
  [[ "${script}" != *"'"* ]] \
    || die "Internal error: the remote payload script must not contain a single quote"
  coreelec_settings_payload | ssh_keyed "sh -c '${script}'"
}

# Streams the validated artifacts to the device over the SSH connection that
# is already authenticated, so no second transport (scp/rsync) and no second
# credential are involved. The staging program cannot be piped in because
# stdin carries the tar stream, so it travels as a single-quoted `sh -c`
# argument that must not contain a single quote.
upload_artifact_bundle() {
  local validated_dir="$1"
  local script index id version filename
  local -a bundle_files=()

  [[ -d "${validated_dir}" ]] || die "Validated artifact directory is missing: ${validated_dir}"
  # The selection is resolved in the preflight, before anything on the device
  # is touched; reaching here without it is a programming error, not an
  # operator mistake.
  [[ -s "${validated_dir}/deploy.tsv" ]] \
    || die "Internal error: the add-on selection was not resolved before the bundle upload"

  bundle_files=("deploy.tsv")
  while IFS=$'\t' read -r index id version filename; do
    [[ -n "${filename}" ]] || continue
    [[ -f "${validated_dir}/${filename}" ]] \
      || die "Validated artifact file is missing: ${validated_dir}/${filename}"
    bundle_files+=("${filename}")
  done < "${validated_dir}/deploy.tsv"

  script="$(coreelec_remote_stage_script)"
  [[ "${script}" != *"'"* ]] \
    || die "Internal error: the remote staging script must not contain a single quote"

  info "Uploading $(( ${#bundle_files[@]} - 1 )) pinned add-on artifact(s) to the device"
  # COPYFILE_DISABLE stops macOS tar from adding AppleDouble (._*) members for
  # the quarantine attribute curl puts on every download, and ustar keeps the
  # stream free of the pax headers BSD tar would otherwise emit for BusyBox
  # tar to interpret on the device.
  COPYFILE_DISABLE=1 tar -C "${validated_dir}" --format ustar -cf - "${bundle_files[@]}" \
    | ssh_keyed "sh -c '${script}'"
}

# Best effort cleanup for the one window the remote trap cannot cover: if the
# transaction never started (a dropped connection, an SSH failure), the
# uploaded secrets would otherwise sit in the provisioning cache until the
# next run overwrote them.
discard_remote_settings_payload() {
  local payload_dir="/storage/.cache/coreelec-provision"
  ssh_keyed 'sh -c '\''
    set -eu
    rm -f "$1/settings-payload.conf" "$1/settings-payload.conf.provision-new"
  '\'' sh' "${payload_dir}" >/dev/null 2>&1 \
    || warn "Could not confirm removal of the uploaded settings payload in ${payload_dir}"
}

# Runs the whole device-side change as one transaction: expand and verify the
# bundle, stop Kodi once, replace add-ons, apply settings, restart services.
# The rollback material deliberately survives a success so verification can
# still undo it; Task 6 finalizes or rolls back afterwards.
deploy_artifacts_and_settings() {
  local transaction="" status=0

  info "Deploying add-ons and Kodi settings in one recoverable remote transaction"
  set +e
  transaction="$(coreelec_remote_deploy_script | ssh_keyed 'sh -s')"
  status=$?
  set -e

  if (( status != 0 )); then
    discard_remote_settings_payload
    die "Remote deployment failed. The device rolled itself back unless a ROLLBACK INCOMPLETE line above names retained paths."
  fi
  # The remote program prints exactly one line, the transaction path; anything
  # else means the channel carried output this Mac must not treat as a path.
  [[ -n "${transaction}" ]] \
    || die "The remote deployment did not report a transaction directory"
  [[ "${transaction}" != *$'\n'* ]] \
    || die "The remote deployment printed more than the transaction directory"
  case "${transaction}" in
    /*) ;;
    *) die "The remote deployment reported a transaction directory that is not an absolute path" ;;
  esac

  REMOTE_TRANSACTION="${transaction}"
  info "Deployment transaction pending verification: ${transaction}"
}

# Commits the pending transaction: the dated backup and its manifest stay, the
# material that exists only to undo the change is released.
finalize_remote_deployment() {
  info "Finalizing the pending remote deployment transaction" >&2
  coreelec_remote_finalize_script | ssh_keyed 'sh -s'
}

# Restores the pre-deployment state and leaves the dated backup in place as
# the record of what was touched.
rollback_remote_deployment() {
  info "Rolling back the pending remote deployment transaction" >&2
  coreelec_remote_rollback_script | ssh_keyed 'sh -s'
}


apply_kodi_baseline() {
  info "Applying the reversible Kodi and Home Assistant baseline"

  # Only the names of the configured integrations are logged; a value that
  # came from a secret environment variable is never printed.
  [[ -n "${YOUTUBE_API_KEY:-}" ]] && info "YouTube API credentials will be configured"
  [[ -n "${OMDB_API_KEY:-}" || -n "${MDBLIST_API_KEY:-}" ]] && info "TMDb Helper metadata keys will be configured"
  [[ -n "${HOME_ASSISTANT_TOKEN:-}" ]] && info "Home Assistant weather will be configured"
  [[ -n "${NEXTPVR_PIN:-}" ]] && info "NextPVR client instance will be configured"
  [[ -n "${PLEX_TOKEN:-}" ]] && info "PM4K local mode will be configured"

  # The bundle is staged first and the secret payload last, immediately before
  # the deploy that consumes it. Staging is the step most likely to fail (it
  # moves tens of megabytes and verifies checksums on the device), and a
  # failure there must not leave credentials sitting in the remote cache.
  upload_artifact_bundle "${ARTIFACT_STAGE_DIR}"
  upload_kodi_settings_payload
  # One transaction: add-ons land before the transformer runs, so activating
  # the pinned skin and weather provider cannot be rejected for referring to
  # an add-on that is not installed yet.
  deploy_artifacts_and_settings

  wait_for_kodi_jsonrpc
}

wait_for_kodi_jsonrpc() {
  local attempt="1"
  local response_file="${TASK_TEMP_DIR}/kodi-response.json"
  CURL_CONFIG_FILE="${TASK_TEMP_DIR}/curl.conf"
  chmod 700 "${TASK_TEMP_DIR}"
  {
    printf 'user = "%s:%s"\n' "${KODI_USER}" "${KODI_WEB_PASSWORD}"
    printf 'silent\n'
    printf 'show-error\n'
    printf 'fail\n'
    printf 'max-time = 4\n'
  } > "${CURL_CONFIG_FILE}"
  chmod 600 "${CURL_CONFIG_FILE}"

  info "Waiting for authenticated Kodi JSON-RPC on TCP ${KODI_PORT}"
  while (( attempt <= 30 )); do
    if curl --config "${CURL_CONFIG_FILE}" \
      -H 'Content-Type: application/json' \
      --data-binary '{"jsonrpc":"2.0","id":1,"method":"JSONRPC.Version"}' \
      "http://${TARGET}:${KODI_PORT}/jsonrpc" > "${response_file}" 2>/dev/null; then
      if grep -q '"result"' "${response_file}"; then
        info "Kodi JSON-RPC authentication succeeded"
        return
      fi
    fi
    sleep 2
    attempt=$((attempt + 1))
  done

  warn "Kodi settings were applied, but JSON-RPC was not reachable from this Mac. Check pfSense and TCP ${KODI_PORT}."
}

write_audit_report() {
  local report_stamp
  local target_slug
  local report_file
  local deployed_index deployed_id deployed_version deployed_file
  report_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target_slug="$(printf '%s' "${TARGET}" | tr -c 'A-Za-z0-9._-' '_')"
  mkdir -p "${REPORT_DIR}"
  chmod 700 "${REPORT_DIR}"
  report_file="${REPORT_DIR}/${target_slug}-${report_stamp}.txt"

  {
    printf 'report_format=coreelec-provisioning-report-1\n'
    printf 'script_version=%s\n' "${SCRIPT_VERSION}"
    printf 'created_utc=%s\n' "$(timestamp)"
    printf 'target=%s\n' "${TARGET}"
    printf 'ssh_port=%s\n' "${SSH_PORT}"
    printf 'identity_file=%s\n' "${IDENTITY_FILE}"
    printf 'ssh_password_auth_disabled=%s\n' "${HARDEN_SSH}"
    printf 'kodi_baseline_requested=%s\n' "${APPLY_KODI}"
    if [[ "${APPLY_KODI}" == "1" ]]; then
      printf 'kodi_jsonrpc=http://%s:%s/jsonrpc\n' "${TARGET}" "${KODI_PORT}"
      printf 'kodi_username=%s\n' "${KODI_USER}"
      printf 'kodi_password=stored-in-macos-keychain\n'
    fi
    # Every local line is key=value so Task 6 (and any operator running grep)
    # can read the report without parsing prose.
    if (( ${#ADDONS[@]} > 0 )); then
      printf 'requested_addons=%s\n' "$(printf '%s,' ${ADDONS[@]+"${ADDONS[@]}"} | sed 's/,$//')"
    else
      printf 'requested_addons=all-locked-artifacts\n'
    fi
    if [[ -n "${REMOTE_TRANSACTION}" ]]; then
      printf 'deployment_transaction=%s\n' "${REMOTE_TRANSACTION}"
      printf 'deployment_state=pending-verification\n'
    fi
    if [[ -n "${ARTIFACT_STAGE_DIR}" && -f "${ARTIFACT_STAGE_DIR}/deploy.tsv" ]]; then
      while IFS=$'\t' read -r deployed_index deployed_id deployed_version deployed_file; do
        [[ -n "${deployed_id}" ]] || continue
        printf 'deployed_addon.%s=%s\n' "${deployed_id}" "${deployed_version}"
      done < "${ARTIFACT_STAGE_DIR}/deploy.tsv"
    fi
    printf 'remote_inventory=begin\n'

    ssh_keyed 'sh -s' <<'REMOTE_INVENTORY'
printf 'hostname=%s\n' "$(hostname)"
printf 'date_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'kernel=%s\n' "$(uname -a)"
printf 'device_model='
tr -d '\000' < /proc/device-tree/model 2>/dev/null || true
printf '\n'

printf '\n/etc/os-release\n'
cat /etc/os-release 2>/dev/null || true
printf '\n/etc/release\n'
cat /etc/release 2>/dev/null || true

printf '\nnetwork_interfaces\n'
for address_file in /sys/class/net/*/address; do
  interface="${address_file%/address}"
  interface="${interface##*/}"
  [ "${interface}" = "lo" ] && continue
  printf '%s=%s\n' "${interface}" "$(cat "${address_file}")"
done
ip addr show 2>/dev/null || true
ip route show 2>/dev/null || true

printf '\nservices\n'
for service in sshd.service kodi.service opentee_linuxdriver.service; do
  printf '%s=%s\n' "${service}" "$(systemctl is-active "${service}" 2>/dev/null || true)"
done

printf '\ndolby_vision_module\n'
for module_file in /storage/.config/dovi.ko /flash/dovi.ko /storage/dovi.ko; do
  if [ -f "${module_file}" ]; then
    ls -l "${module_file}"
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum "${module_file}"
    fi
  fi
done
lsmod 2>/dev/null | grep -i dovi || true
modinfo dovi 2>/dev/null | sed -n '1,30p' || true

printf '\nhdmi_capabilities\n'
for capability in disp_cap dc_cap hdr_cap dv_cap aud_cap; do
  capability_file="/sys/class/amhdmitx/amhdmitx0/${capability}"
  if [ -r "${capability_file}" ]; then
    printf '[%s]\n' "${capability}"
    cat "${capability_file}"
    printf '\n'
  fi
done

printf '\naudio_devices\n'
cat /proc/asound/cards 2>/dev/null || true
df -h /storage 2>/dev/null || true
REMOTE_INVENTORY
  } > "${report_file}"
  chmod 600 "${report_file}"
  printf '%s\n' "${report_file}"
}

if [[ -n "${DEPLOY_ACTION}" ]]; then
  create_or_load_admin_key
  case "${DEPLOY_ACTION}" in
    finalize)
      FINALIZED_TRANSACTION="$(finalize_remote_deployment)"
      info "Deployment finalized: ${FINALIZED_TRANSACTION}"
      ;;
    rollback)
      ROLLED_BACK_TRANSACTION="$(rollback_remote_deployment)"
      info "Deployment rolled back: ${ROLLED_BACK_TRANSACTION}"
      ;;
  esac
  exit 0
fi

if [[ "${ASSUME_YES}" != "1" ]]; then
  printf 'Target:             %s\n' "${TARGET}"
  printf 'Expected release:   %s / Amlogic-ng\n' "${EXPECTED_RELEASE}"
  printf 'Administrator key:  %s\n' "${IDENTITY_FILE}"
  printf 'Harden SSH:         %s\n' "${HARDEN_SSH}"
  printf 'Apply Kodi baseline:%s\n' "${APPLY_KODI}"
  printf 'Locked add-ons:     %s\n' "${#ADDON_ARTIFACTS[@]}"
  printf 'Selected add-ons:   %s\n' "$( (( ${#ADDONS[@]} > 0 )) && printf '%s' "${#ADDONS[@]}" || printf 'all')"
  printf 'Continue? [y/N] '
  read -r confirmation
  case "${confirmation}" in
    y|Y|yes|YES) ;;
    *) die "Cancelled" ;;
  esac
fi

TASK_TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/coreelec-provision.XXXXXX")"
chmod 700 "${TASK_TEMP_DIR}"

create_or_load_admin_key

info "Reading and validating the remote platform"
if ssh_keyed_batch true >/dev/null 2>&1; then
  KEY_ALREADY_ACCEPTED="1"
  REMOTE_IDENTITY="$(remote_identity)"
else
  info "Enter the temporary CoreELEC root password for this read-only platform check."
  REMOTE_IDENTITY="$(remote_identity_with_password)"
fi
printf '%s\n' "${REMOTE_IDENTITY}"
validate_remote "${REMOTE_IDENTITY}"

# Every artifact is downloaded, checksum-verified, and inspected before the
# first mutating SSH call, so a bad or unreachable artifact cancels the run
# while the device is still untouched.
if [[ "${APPLY_KODI}" == "1" ]]; then
  require_command shasum
  require_command unzip
  require_command xmllint
  require_command tar
  ARTIFACT_STAGE_DIR="${TASK_TEMP_DIR}/artifacts"
  info "Validating pinned add-on artifacts before changing anything on the device"
  coreelec_artifacts_download_and_validate "${ARTIFACT_STAGE_DIR}"
  # Resolving the selection here keeps every "which add-ons" decision -- and
  # every way it can be refused -- on the untouched-device side of the run.
  coreelec_addon_selection "${ARTIFACT_STAGE_DIR}/manifest.tsv" > "${ARTIFACT_STAGE_DIR}/deploy.tsv"
fi

install_public_key_if_needed

REMOTE_BACKUP_PATH="$(create_remote_backup)"
info "Remote backup created: ${REMOTE_BACKUP_PATH}"

harden_remote_ssh

KEYCHAIN_SERVICE=""
if [[ "${APPLY_KODI}" == "1" ]]; then
  KEYCHAIN_SERVICE="$(keychain_service_name)"
  prepare_kodi_password "${KEYCHAIN_SERVICE}"
  apply_kodi_baseline
elif (( ${#ADDONS[@]} > 0 )); then
  warn "Add-on selection was ignored because --no-kodi was selected"
fi

REPORT_FILE="$(write_audit_report)"

info "Provisioning completed"
printf 'Audit report: %s\n' "${REPORT_FILE}"
printf 'SSH command:  ssh -i %q -p %q root@%q\n' "${IDENTITY_FILE}" "${SSH_PORT}" "${TARGET}"
if [[ "${APPLY_KODI}" == "1" ]]; then
  printf 'Kodi JSON-RPC: http://%s:%s/jsonrpc\n' "${TARGET}" "${KODI_PORT}"
  printf 'Kodi username: %s\n' "${KODI_USER}"
  printf 'Retrieve the Kodi password from Keychain with:\n'
  printf '  security find-generic-password -a %q -s %q -w\n' "${KODI_USER}" "${KEYCHAIN_SERVICE}"
fi
if [[ -n "${REMOTE_TRANSACTION}" ]]; then
  printf '\nThe deployment transaction is still undoable:\n'
  printf '  %s\n' "${REMOTE_TRANSACTION}"
  printf 'Verify the device, then commit or undo it:\n'
  printf '  %q --target %q --finalize-deployment\n' "$0" "${TARGET}"
  printf '  %q --target %q --rollback-deployment\n' "$0" "${TARGET}"
fi
printf 'Use the wired MAC in the audit report for the pfSense DHCP reservation.\n'
