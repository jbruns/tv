#!/bin/bash

# macOS-side bootstrap for a freshly installed CoreELEC device.
#
# The first-boot wizard must already have completed, with wired networking and
# SSH enabled. This script then installs a dedicated administrator key, verifies
# key authentication before disabling password authentication, deploys a pinned,
# checksum-verified set of Kodi add-ons and a reversible Kodi/regional/Home
# Assistant baseline as one remote transaction, verifies the result over the
# device's own localhost JSON-RPC, automatically finalizes or rolls back, and
# writes a redacted, non-secret audit report. See config/README.md for every
# configuration key, the strict KEY=value grammar, and the secret environment
# variables; see docs/runbook.md for the full operator workflow.

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
VERIFY_FIXTURE=()
CLASSIFY_ADDON=""
REPORT_FIXTURE=()
CONCLUDE_FIXTURE=()

TASK_TEMP_DIR=""
CURL_CONFIG_FILE=""
KODI_WEB_PASSWORD=""
KEY_ALREADY_ACCEPTED="0"
ARTIFACT_STAGE_DIR=""
REMOTE_TRANSACTION=""
REMOTE_BACKUP_PATH=""
DEPLOY_MANIFEST=""
DEPLOYMENT_STATE="not-started"
VERIFICATION_RESULT="not-run"
VERIFICATION_REPORT_FILE=""
RECOVERY_INSTRUCTIONS=""
# Reachability of the device's JSON-RPC port *from this Mac*. It is recorded
# for the operator, never used as a verification verdict: the device checks
# itself over its own localhost endpoint.
KODI_JSONRPC_LOCAL_REACHABLE="unknown"

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
                           'deploy', 'rollback', 'finalize', 'verify', or
                           'verify-probe' program for ROOT (default /storage),
                           then exit. Used by the test suites; it never
                           contacts a device.
  --render-remote-deploy-script [ROOT]
                          Alias of --emit-remote-script deploy: print the
                           remote deployment transaction program for ROOT
                           (default /storage), then exit.
  --print-addon-selection MANIFEST
                          Print the manifest lines this run would deploy,
                           honoring --addon, then exit.
  --verify-fixture OBSERVATIONS MANIFEST
                          Compare a fixture observation set with the manifest
                           and print the verification report lines, then exit.
  --classify-addon ID     Print the configured/manual status of one add-on,
                           then exit.
  --report-fixture DIR OBSERVATIONS MANIFEST REACHABLE
                          Write a full audit report into DIR from fixture
                           observations, without the device inventory, then
                           exit.
  --conclude-fixture OBSERVATIONS MANIFEST FINALIZE_STATUS ROLLBACK_STATUS LOG
                          Run the verify -> finalize/rollback decision with
                           the remote calls recorded in LOG, then exit.

Examples:
  ./provision-coreelec.sh --check-config
  ./provision-coreelec.sh --check-artifacts
  ./provision-coreelec.sh --target coreelec-theater
  ./provision-coreelec.sh --config /path/to/device.conf --target 172.16.99.50

The device must first be booted through the CoreELEC wizard with Ethernet and
SSH enabled and a unique root password. The first run may prompt for that root
password and for the passphrase of the dedicated administrator key.

Configuration precedence is: built-in defaults, then the selected --config
file, then explicit CLI options, then secret environment variables (read only
for the fields that require them: OMDB_API_KEY, MDBLIST_API_KEY,
YOUTUBE_API_KEY, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET,
HOME_ASSISTANT_TOKEN, NEXTPVR_PIN, PLEX_TOKEN, and EMBY_PASSWORD). None may appear
in the config file, and TARGET is never a config-file key. See
config/README.md for every supported key, the repeated ADDON_ARTIFACT
grammar, and the full secret list.
EMBY_PASSWORD is consumed only by configure-coreelec-addons.sh --interactive;
this transactional provisioner validates and redacts it but never uses it.

This script deliberately does not configure audio codecs or the display mode
whitelist (room-specific, live HDMI-dependent), and it cannot perform Emby
server sign-in or YouTube's interactive Google device authorization -- those
add-ons are always left for the operator to finish by hand.
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
  # The observations and the comparison they produced are working files; the
  # report keeps the parts an operator needs.
  if [[ -n "${TASK_TEMP_DIR}" ]]; then
    rm -f -- "${TASK_TEMP_DIR}/verify-observations.conf" \
      "${TASK_TEMP_DIR}/verification.conf"
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
import datetime
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
    instance = addon_file("pvr.nextpvr", "instance-settings-1.xml")
    if nextpvr_configured:
        set_addon_setting(instance, "host", config("NEXTPVR_HOST"))
        set_addon_setting(instance, "hostprotocol",
                          config("NEXTPVR_PROTOCOL") or "http")
        set_addon_setting(instance, "kodi_addon_instance_enabled", "true")
        set_addon_setting(instance, "kodi_addon_instance_name",
                          config("NEXTPVR_INSTANCE_NAME") or "NextPVR")
        set_addon_setting(instance, "pin", secret("NEXTPVR_PIN"))
        set_addon_setting(instance, "port", config("NEXTPVR_PORT") or "8866")
    elif not os.path.exists(instance):
        # Without a backend, Kodi's generated localhost instance fails
        # permanently and Kodi disables the add-on itself.
        set_addon_setting(instance, "kodi_addon_instance_enabled", "false")

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

    # --- Arctic Fuse skin settings ------------------------------------------
    skin_settings_path = addon_file(SKIN_ID, "settings.xml")
    if os.path.exists(skin_settings_path):
        skin_tree = ET.parse(skin_settings_path)
        skin_root = skin_tree.getroot()
    else:
        skin_root = ET.Element("settings")
        skin_tree = ET.ElementTree(skin_root)

    def _skin_setting_nodes(root, setting_id):
        wanted = setting_id.casefold()
        return [
            (parent, node)
            for parent in [root] + list(root.findall("category"))
            for node in parent.findall("setting")
            if (node.get("id") or "").casefold() == wanted
        ]

    def set_skin_setting(setting_id, value):
        nodes = _skin_setting_nodes(skin_root, setting_id)
        if nodes:
            node = nodes[0][1]
            for parent, duplicate in nodes[1:]:
                parent.remove(duplicate)
        else:
            node = ET.SubElement(skin_root, "setting", {"id": setting_id})
        node.set("id", setting_id)
        node.set("type", "string")
        node.attrib.pop("value", None)
        node.attrib.pop("default", None)
        node.text = value

    def remove_skin_setting(setting_id):
        for parent, node in _skin_setting_nodes(skin_root, setting_id):
            parent.remove(node)

    # Hub toggles and shortcuts
    set_skin_setting("HomeSwitcher.1101.Name", "Plex")
    set_skin_setting("HomeSwitcher.1101.Toggle", "true")
    set_skin_setting("HomeSwitcher.1101.Icon",
                     "special://home/addons/script.plexmod/icon2.png")
    set_skin_setting("HomeSwitcher.1101.Shortcut.Path",
                     "RunAddon(script.plexmod)")

    set_skin_setting("HomeSwitcher.1102.Name", "YouTube")
    set_skin_setting("HomeSwitcher.1102.Toggle", "true")
    set_skin_setting("HomeSwitcher.1102.Icon",
                     "special://home/addons/plugin.video.youtube/resources/media/icon.png")
    set_skin_setting("HomeSwitcher.1102.Shortcut.Path",
                     "plugin://plugin.video.youtube/")
    set_skin_setting("HomeSwitcher.1102.Shortcut.Target", "videos")

    # Arctic Fuse renders a hub whenever its toggle string is non-empty, so
    # the disabled state is the absence of every case-insensitive toggle node.
    remove_skin_setting("HomeSwitcher.1106.Toggle")
    remove_skin_setting("HomeSwitcher.1106.UpNextMode")
    set_skin_setting("HomeSwitcher.1107.Toggle", "true")
    set_skin_setting("HomeSwitcher.1108.Toggle", "true")
    set_skin_setting("optionstiles.02.include", "Settings")

    # Remove stale direct-hub state
    remove_skin_setting("HomeSwitcher.1101.Shortcut.Target")
    remove_skin_setting("HomeSwitcher.1101.Spotlight.Path")
    remove_skin_setting("HomeSwitcher.1102.Spotlight.Path")

    write_xml_atomic(skin_settings_path, skin_tree)

    # --- Arctic Fuse skinvariables nodes -----------------------------------
    nodes_dir = os.path.join(addon_data, "script.skinvariables",
                             "nodes", SKIN_ID)
    register_managed_directory(os.path.join(addon_data, "script.skinvariables"))
    register_managed_directory(os.path.join(addon_data, "script.skinvariables",
                                            "nodes"))
    register_managed_directory(nodes_dir)

    home_widgets = [
        {"guid": "coreelec-home-inprogress-movies", "icon": "", "label": "In-Progress Movies", "path": "special://profile/playlists/video/InProgressMovies90Days.xsp", "target": "videos"},
        {"guid": "coreelec-home-inprogress-shows", "icon": "", "label": "In-Progress Shows", "path": "special://profile/playlists/video/InProgressShows90Days.xsp", "target": "videos"},
        {"guid": "coreelec-home-recently-aired-shows", "icon": "", "label": "Recently Aired Shows", "path": "special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp", "target": "videos"},
        {"guid": "coreelec-home-recently-released-movies", "icon": "", "label": "Recently Released Movies", "path": "special://profile/playlists/video/RecentlyReleasedMoviesCurrentYear.xsp", "target": "videos"},
        {"guid": "coreelec-home-new-shows", "icon": "", "label": "New Shows", "path": "special://profile/playlists/video/NewShows.xsp", "target": "videos"},
        {"guid": "coreelec-home-new-movies", "icon": "", "label": "New Movies", "path": "special://profile/playlists/video/NewMovies.xsp", "target": "videos"},
    ]
    write_json_atomic(os.path.join(nodes_dir,
                                   "skinvariables-shortcut-homewidgets.json"),
                      home_widgets)

    power_menu = [
        {"guid": "coreelec-power-poweroff", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13016]", "path": "Powerdown()", "target": ""},
        {"guid": "coreelec-power-timer", "icon": "special://skin/extras/icons/timer.png", "label": "$LOCALIZE[20150]", "path": "AlarmClock(shutdowntimer,Shutdown())", "target": ""},
        {"guid": "coreelec-power-suspend", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13011]", "path": "Suspend()", "target": ""},
        {"guid": "coreelec-power-reboot", "icon": "special://skin/extras/icons/refresh.png", "label": "$LOCALIZE[13013]", "path": "Reset()", "target": ""},
        {"guid": "coreelec-power-restart-kodi", "icon": "special://skin/extras/icons/refresh.png", "label": "Restart Kodi", "path": "RestartApp()", "target": ""},
    ]
    write_json_atomic(os.path.join(nodes_dir,
                                   "skinvariables-shortcut-powermenu.json"),
                      power_menu)

    # --- Arctic Fuse smart playlists ----------------------------------------
    playlists_dir = os.path.join(userdata, "playlists", "video")
    register_managed_directory(os.path.join(userdata, "playlists"))
    register_managed_directory(playlists_dir)

    def write_smart_playlist(path, name, media_type, rules, order, limit=50):
        root = ET.Element("smartplaylist", {"type": media_type})
        ET.SubElement(root, "name").text = name
        ET.SubElement(root, "match").text = "all"
        for field, operator, value in rules:
            rule_el = ET.SubElement(root, "rule", {
                "field": field,
                "operator": operator,
            })
            if value:
                ET.SubElement(rule_el, "value").text = value
        ET.SubElement(root, "limit").text = str(limit)
        order_node = ET.SubElement(root, "order", {"direction": order[1]})
        order_node.text = order[0]
        write_xml_atomic(path, ET.ElementTree(root))

    def remove_managed_file(path):
        if not os.path.lexists(path):
            return
        if not os.path.isfile(path) or os.path.islink(path):
            fail("refusing to remove a non-regular managed file: %s" % path)
        os.unlink(path)
        WRITTEN_PATHS.append(path)

    write_smart_playlist(
        os.path.join(playlists_dir, "InProgressMovies90Days.xsp"),
        "In-Progress Movies", "movies",
        [("inprogress", "true", ""), ("lastplayed", "inthelast", "90 days")],
        ("lastplayed", "descending"))

    write_smart_playlist(
        os.path.join(playlists_dir, "InProgressShows90Days.xsp"),
        "In-Progress Shows", "tvshows",
        [("inprogress", "true", ""), ("lastplayed", "inthelast", "90 days")],
        ("lastplayed", "descending"))

    write_smart_playlist(
        os.path.join(playlists_dir, "RecentlyAiredEpisodes30Days.xsp"),
        "Recently Aired Shows", "episodes",
        [("airdate", "inthelast", "30 days"),
         ("airdate", "notinthelast", "-1 days")],
        ("year", "descending"))

    remove_managed_file(
        os.path.join(playlists_dir, "RecentlyReleasedMovies90Days.xsp"))
    write_smart_playlist(
        os.path.join(playlists_dir, "RecentlyReleasedMoviesCurrentYear.xsp"),
        "Recently Released Movies", "movies",
        [("year", "is", str(datetime.date.today().year))],
        ("year", "descending"))

    write_smart_playlist(
        os.path.join(playlists_dir, "NewShows.xsp"),
        "New Shows", "tvshows",
        [("playcount", "is", "0")],
        ("dateadded", "descending"))

    write_smart_playlist(
        os.path.join(playlists_dir, "NewMovies.xsp"),
        "New Movies", "movies",
        [("playcount", "is", "0")],
        ("dateadded", "descending"))

    # --- CoreELEC timezone cache -------------------------------------------
    # Kodi's CoreELEC patch writes this file when the timezone changes through
    # the UI; offline edits must write it explicitly. It holds no secret.
    if config("TIMEZONE"):
        write_text_atomic(os.path.join(storage_root, ".cache", "timezone"),
                          "TIMEZONE=%s\n" % config("TIMEZONE"), mode=0o644)


try:
    main(sys.argv)
finally:
    # Report every path written so far, even on a partial failure: the
    # rollback needs this list to remove newly created managed files.
    for path in WRITTEN_PATHS:
       sys.stdout.write("settings applied: %s\n" % path)
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
.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml
.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-homewidgets.json
.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-powermenu.json
.kodi/userdata/playlists/video/InProgressMovies90Days.xsp
.kodi/userdata/playlists/video/InProgressShows90Days.xsp
.kodi/userdata/playlists/video/RecentlyAiredEpisodes30Days.xsp
.kodi/userdata/playlists/video/RecentlyReleasedMovies90Days.xsp
.kodi/userdata/playlists/video/RecentlyReleasedMoviesCurrentYear.xsp
.kodi/userdata/playlists/video/NewShows.xsp
.kodi/userdata/playlists/video/NewMovies.xsp
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

# Writes one mode-0600 file in the private provisioning cache from stdin. The
# file name is a parameter because the same atomic, private write is used for
# the settings payload and for the verification request; keeping one
# implementation is what stops the second one from being written less
# carefully than the first.
coreelec_remote_payload_script() {
  local root="${1:-/storage}"
  local name="${2:-settings-payload.conf}"
  cat <<REMOTE_PAYLOAD_HEADER
set -eu
umask 077
payload_dir="${root}/.cache/coreelec-provision"
payload_file="\${payload_dir}/${name}"
REMOTE_PAYLOAD_HEADER
  cat <<'REMOTE_PAYLOAD'
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
    # The transformer reports written paths to stdout even on failure, but the
    # sed that normally populates APPLIED.txt only runs on the success path.
    # Processing applied.raw here ensures rollback can remove newly created
    # managed files that had no previous backup copy.
    if [ -f "${transaction}/applied.raw" ]; then
      sed -n 's/^settings applied: //p' "${transaction}/applied.raw" \
        > "${transaction}/APPLIED.txt" 2>/dev/null || :
      rm -f "${transaction}/applied.raw"
    fi
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
  if [ "${plan_id}" = "weather.ha" ]; then
    weather_settings="${expanded_dir}/${plan_id}/${plan_top}/resources/settings.xml"
    [ -f "${weather_settings}" ] \
      || fail "the expanded weather.ha has no resources/settings.xml"
    python3 - "${weather_settings}" <<'PYTHON_PATCH_WEATHER_SETTINGS' \
      || fail "could not apply the Kodi 21 weather.ha settings compatibility patch"
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
matches = [
    node for node in tree.getroot().findall(".//setting")
    if node.get("id") == "ha_request_attempts"
]
if len(matches) != 1 or matches[0].get("type") != "int":
    raise SystemExit("unexpected weather.ha request-attempts setting")
matches[0].set("type", "number")
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYTHON_PATCH_WEATHER_SETTINGS
  fi
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

# --- Remote verification probe ----------------------------------------------
#
# Verification is performed *on the device*, against Kodi's own localhost
# JSON-RPC endpoint, because that is the only observer that cannot be fooled
# by a local firewall, a NAT rule, or a stale file on disk. The probe below is
# emitted as a Python program and run by the wrapper further down; it is also
# emitted on its own (`--emit-remote-script verify-probe`) so the test suite
# runs the exact program the device runs.
#
# It receives one mode-0600 request file of `KEY=base64(value)` lines. The only
# secret in that request is the Kodi web password, which the probe writes into
# a mode-0600 curl config and never echoes. Every other secret is represented
# by a `HAVE_<KEY>` presence flag: the probe compares the *device's* files
# locally and returns booleans, so no token, key, or PIN ever travels back to
# the Mac.
coreelec_remote_verify_probe_source() {
  cat <<'PYTHON_VERIFY_PROBE_SOURCE'
"""CoreELEC remote verification probe.

Usage: python3 - STORAGE_ROOT REQUEST_PATH CURL_CONFIG_PATH [SYSTEM_ROOT]

Prints `key=value` observations only. Never prints a secret: credentials are
compared on the device and reported as booleans.
"""

import base64
import datetime
import errno
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

SETTING_IDS = [
    "locale.language",
    "locale.country",
    "locale.keyboardlayouts",
    "locale.timezonecountry",
    "locale.timezone",
    "lookandfeel.skin",
    "weather.addon",
]

# `date +%Z%z` output: a zone abbreviation followed by a UTC offset. Anything
# else -- an unexpanded format string, an error line, an empty answer -- is not
# zone marks and is never treated as evidence about the device's clock.
ZONE_MARKS_PATTERN = re.compile(r"^([A-Za-z0-9_+-]{1,10}?)([+-][0-9]{4})$")

# CoreELEC images do not agree on where the tz database lives.
ZONEINFO_ROOTS = [
    "usr/share/zoneinfo",
    "usr/share/zoneinfo/posix",
    "share/zoneinfo",
    "etc/zoneinfo",
]

# How many times the probe may ask Kodi to enable what it still reports
# disabled. Each round costs one request per remaining add-on plus one query,
# and the loop also stops as soon as a round changes nothing, so this is only
# the ceiling for a device that keeps making progress.
ENABLE_ROUNDS = 6

OBSERVATIONS = []


class CurlUnavailable(Exception):
    """The device has no curl, so Kodi cannot be asked anything at all."""


def fail(message):
    raise SystemExit("verification probe: " + message)


def observe(key, value):
    """Records one observation. Newlines are folded because the Mac parses
    this output as one key=value pair per line."""
    text = "%s" % (value,)
    text = text.replace("\r", " ").replace("\n", " ")
    OBSERVATIONS.append("%s=%s" % (key, text))


def read_request(path):
    values = {}
    handle = open(path, "r")
    try:
        number = 0
        for raw_line in handle:
            number += 1
            line = raw_line.strip()
            if not line:
                continue
            if "=" not in line:
                fail("request line %d is not KEY=value" % number)
            key, encoded = line.split("=", 1)
            try:
                values[key] = base64.b64decode(encoded).decode("utf-8")
            except Exception:
                fail("request line %d is not valid base64" % number)
    finally:
        handle.close()
    return values


def quote_for_curl(text):
    return text.replace("\\", "\\\\").replace("\"", "\\\"")


def write_curl_config(path, user, password, seconds):
    """Creates the credential file at its final restrictive mode, never a
    mode the umask or a planted file could widen."""
    if os.path.lexists(path):
        os.remove(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    handle = os.fdopen(descriptor, "w")
    try:
        handle.write("user = \"%s:%s\"\n"
                     % (quote_for_curl(user), quote_for_curl(password)))
        handle.write("silent\n")
        handle.write("show-error\n")
        handle.write("fail\n")
        handle.write("max-time = %d\n" % seconds)
    finally:
        handle.close()


def call_jsonrpc(curl_config, url, batch):
    """One JSON-RPC round trip. The request body travels on curl's stdin and
    the credentials travel in the config file, so neither appears in an
    argument list."""
    try:
        process = subprocess.Popen(
            ["curl", "--config", curl_config,
             "-H", "Content-Type: application/json",
             "--data-binary", "@-", url],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
    except OSError as error:
        # A missing curl is a different fact from an unresponsive Kodi, and
        # retrying it would only turn an immediate answer into a long wait.
        if getattr(error, "errno", None) == errno.ENOENT:
            raise CurlUnavailable("curl is not available on this device")
        return None
    body = json.dumps(batch).encode("utf-8")
    output = process.communicate(body)[0]
    if process.returncode != 0:
        return None
    try:
        return json.loads(output.decode("utf-8"))
    except ValueError:
        return None


def require_curl():
    """Checked before the credential file is written, so a device that cannot
    be probed fails at once with the reason rather than after a minute of
    retries against a tool that does not exist."""
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = os.path.join(directory, "curl")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return
    fail("curl is not available on this device, so Kodi cannot be queried "
         "over localhost JSON-RPC")


def index_responses(payload):
    entries = {}
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return entries
    for entry in payload:
        if isinstance(entry, dict) and "id" in entry:
            entries["%s" % (entry["id"],)] = entry
    return entries


def query_batch(addon_ids):
    batch = [{"jsonrpc": "2.0", "id": "version", "method": "JSONRPC.Version"}]
    for setting_id in SETTING_IDS:
        batch.append({"jsonrpc": "2.0",
                      "id": "setting:" + setting_id,
                      "method": "Settings.GetSettingValue",
                      "params": {"setting": setting_id}})
    for addon_id in addon_ids:
        batch.append({"jsonrpc": "2.0",
                      "id": "addon:" + addon_id,
                      "method": "Addons.GetAddonDetails",
                      "params": {"addonid": addon_id,
                                 "properties": ["enabled", "version"]}})
    return batch


def addon_state(entry):
    """(installed, version, enabled) for one Addons.GetAddonDetails reply. An
    add-on Kodi does not know answers with an error, which is 'not
    installed' -- never 'installed and fine'."""
    if not isinstance(entry, dict) or "result" not in entry:
        return (0, "", 0)
    result = entry["result"]
    if not isinstance(result, dict):
        return (0, "", 0)
    details = result.get("addon")
    if not isinstance(details, dict):
        return (0, "", 0)
    return (1,
            details.get("version") or "",
            1 if details.get("enabled") else 0)


def disabled_installed_addons(entries, addon_ids):
    """The installed add-ons Kodi still reports disabled, in request order. An
    add-on Kodi does not have is not enabled here -- a missing add-on is a
    deployment failure, not something to switch on."""
    pending = []
    for addon_id in addon_ids:
        installed, _version, enabled = addon_state(entries.get("addon:" + addon_id))
        if installed and not enabled:
            pending.append(addon_id)
    return pending


def request_enable(curl_config, url, addon_id):
    """Asks Kodi to enable exactly one add-on. Answers whether the request was
    served at all.

    One request per add-on rather than one batch for all of them: nothing
    here may assume the order Kodi serves a batch in, and a single request
    that is cut short -- a slow enable, a closed connection -- would take
    every add-on behind it with it.

    The content of the reply is deliberately not read. `Addons.SetAddonEnabled`
    answers OK for anything installed because Kodi's enable call walks the
    add-on's dependency closure deepest-first and reports success even when a
    step of that walk did not take. Only a fresh query is evidence. Whether an
    answer arrived at all is a different fact, and that one matters: a request
    curl gave up on may have changed nothing.
    """
    return call_jsonrpc(curl_config, url,
                        [{"jsonrpc": "2.0",
                          "id": "enable:" + addon_id,
                          "method": "Addons.SetAddonEnabled",
                          "params": {"addonid": addon_id,
                                     "enabled": True}}]) is not None


def converge_enabled_addons(curl_config, url, addon_ids, entries):
    """Enables every installed add-on Kodi reports disabled, asks Kodi again,
    and repeats until it reports them all enabled, stops changing its answer,
    or the round bound is reached.

    One pass cannot settle this. The deployment manifest lists primary add-ons
    before the modules they depend on, and Kodi leaves a dependent disabled
    when its dependency is not enabled at the moment the request is served --
    so a pass enables dependencies and reports their dependents disabled. The
    dependents have to be asked again *after* that, which is what each further
    round does.

    Rounds are driven by what Kodi reports rather than by waiting: the next
    round exists only because the re-query showed the state changed, or
    because a request in that round was never served and so proved nothing. A
    round that was fully served and changed nothing ends the loop, so an
    add-on Kodi will not enable is reported unresolved instead of retried to
    the bound.

    Returns (entries, attempted, unresolved).
    """
    attempted = []
    for _round in range(ENABLE_ROUNDS):
        pending = disabled_installed_addons(entries, addon_ids)
        if not pending:
            break
        served = True
        for addon_id in pending:
            if addon_id not in attempted:
                attempted.append(addon_id)
            if not request_enable(curl_config, url, addon_id):
                served = False
        requeried = index_responses(
            call_jsonrpc(curl_config, url, query_batch(addon_ids)))
        if not requeried or not jsonrpc_version(requeried):
            # Kodi stopped answering. The last state it did report stands,
            # and an add-on left disabled in it stays a failure.
            break
        entries = requeried
        if served and set(disabled_installed_addons(entries, addon_ids)) == set(pending):
            break
    return entries, attempted, disabled_installed_addons(entries, addon_ids)


def setting_value(entries, setting_id):
    entry = entries.get("setting:" + setting_id)
    if not isinstance(entry, dict) or "result" not in entry:
        return ""
    result = entry["result"]
    if isinstance(result, dict):
        value = result.get("value", "")
    else:
        value = result
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(["%s" % (item,) for item in value])
    return "%s" % (value,)


def jsonrpc_version(entries):
    entry = entries.get("version")
    if not isinstance(entry, dict) or not isinstance(entry.get("result"), dict):
        return ""
    version = entry["result"].get("version")
    if not isinstance(version, dict):
        return ""
    return "%s.%s.%s" % (version.get("major", 0),
                         version.get("minor", 0),
                         version.get("patch", 0))


def read_settings(path):
    """Kodi writes add-on settings in two shapes; both are read here so the
    check is about the stored value, not the file's generation."""
    if not os.path.exists(path):
        return None
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    values = {}
    for node in root.iter("setting"):
        identifier = node.get("id")
        if identifier is None:
            continue
        attribute = node.get("value")
        values[identifier] = attribute if attribute is not None else (node.text or "")
    return values


def timezone_cache_value(storage_root):
    path = os.path.join(storage_root, ".cache", "timezone")
    if not os.path.exists(path):
        return ""
    handle = open(path, "r")
    try:
        for line in handle:
            if line.startswith("TIMEZONE="):
                return line.split("=", 1)[1].strip()
    finally:
        handle.close()
    return ""


def localtime_target(system_root):
    path = os.path.join(system_root, "etc", "localtime")
    try:
        if os.path.islink(path):
            return os.readlink(path)
        if os.path.exists(path):
            return os.path.realpath(path)
    except OSError:
        return ""
    return ""


def localtime_kind(system_root):
    path = os.path.join(system_root, "etc", "localtime")
    if os.path.islink(path):
        return "symlink"
    if os.path.isfile(path):
        return "file"
    return "missing"


def read_file_bytes(path):
    handle = open(path, "rb")
    try:
        return handle.read()
    finally:
        handle.close()


def localtime_zoneinfo_match(system_root, timezone):
    """Whether /etc/localtime holds the requested zone's own bytes.

    CoreELEC images store /etc/localtime either as a symlink into the zoneinfo
    tree or as a plain copy of the zone file. A copy resolves to
    /etc/localtime, so it can never be judged by its path; comparing its
    content with the requested zone's file is what makes that layout
    verifiable. `unavailable` means the question could not be answered here --
    it is never evidence of a match."""
    if not timezone:
        return "unavailable"
    path = os.path.join(system_root, "etc", "localtime")
    try:
        if not os.path.isfile(path):
            return "unavailable"
        current = read_file_bytes(path)
    except (OSError, IOError):
        return "unavailable"
    compared = False
    for root in ZONEINFO_ROOTS:
        reference = os.path.join(system_root, root, timezone)
        if not os.path.isfile(reference):
            continue
        try:
            candidate = read_file_bytes(reference)
        except (OSError, IOError):
            continue
        compared = True
        if candidate == current:
            return 1
    return 0 if compared else "unavailable"


def expected_zone_marks(timezone):
    """The abbreviation and UTC offset the requested zone has right now,
    computed from the device's own tz database."""
    previous = os.environ.get("TZ")
    try:
        os.environ["TZ"] = timezone
        time.tzset()
        now = time.localtime()
        if now.tm_isdst > 0:
            abbreviation = time.tzname[1]
            offset_seconds = -time.altzone
        else:
            abbreviation = time.tzname[0]
            offset_seconds = -time.timezone
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()
    sign = "-" if offset_seconds < 0 else "+"
    total = abs(offset_seconds)
    return "%s%s%02d%02d" % (abbreviation, sign, total // 3600,
                             (total % 3600) // 60)


def observed_zone_marks():
    try:
        process = subprocess.Popen(["date", "+%Z%z"],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    except OSError:
        return None
    output = process.communicate()[0]
    if process.returncode != 0:
        return None
    return output.decode("utf-8", "replace").strip()


def parse_zone_marks(text):
    if not text:
        return None
    match = ZONE_MARKS_PATTERN.match(text)
    if match is None:
        return None
    return (match.group(1), match.group(2))


def sanitize_marks(text):
    """Keeps an unexpected answer readable in the report without letting it
    break the `key=value` grammar the Mac parses."""
    if not text:
        return ""
    kept = [character for character in text
            if character in
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
            "0123456789+-_.:/% "]
    return "".join(kept)[:24].strip()


def zone_marks_verdict(timezone):
    """(verdict, expected, observed) for the device's own local time.

    The verdict compares UTC offsets rather than abbreviations, because
    BusyBox and Python do not always name the same zone identically and a
    naming difference is not evidence that a clock is wrong. Anything that is
    not a well-formed pair of zone marks -- a format BusyBox left unexpanded,
    an empty answer, a `date` that failed or is absent -- is `unavailable`:
    a probe capability question, never a mismatch."""
    try:
        expected_text = expected_zone_marks(timezone)
    except Exception:
        expected_text = ""
    observed_text = observed_zone_marks()
    expected = parse_zone_marks(expected_text)
    observed = parse_zone_marks(observed_text)
    if expected is None or observed is None:
        return ("unavailable", sanitize_marks(expected_text),
                sanitize_marks(observed_text))
    if expected[1] == observed[1]:
        return (1, expected_text, observed_text)
    return (0, expected_text, observed_text)


def main(argv):
    if len(argv) not in (4, 5):
        fail("usage: STORAGE_ROOT REQUEST_PATH CURL_CONFIG_PATH [SYSTEM_ROOT]")
    storage_root, request_path, curl_config = argv[1], argv[2], argv[3]
    system_root = argv[4] if len(argv) == 5 else "/"

    request = read_request(request_path)

    def config(key, default=""):
        return request.get(key, default)

    def have(key):
        return request.get("HAVE_" + key, "0") == "1"

    addon_ids = [line.strip() for line in config("ADDON_IDS").split("\n")
                 if line.strip()]
    port = config("KODI_PORT", "8080")
    url = "http://127.0.0.1:%s/jsonrpc" % port
    try:
        attempts = int(config("JSONRPC_ATTEMPTS", "30"))
    except ValueError:
        attempts = 30
    attempts = max(1, attempts)

    require_curl()
    write_curl_config(curl_config, config("KODI_WEB_USER"),
                      config("KODI_WEB_PASSWORD"), 15)
    try:
        entries = {}
        try:
            for attempt in range(attempts):
                entries = index_responses(
                    call_jsonrpc(curl_config, url, query_batch(addon_ids)))
                if jsonrpc_version(entries):
                    break
                entries = {}
                if attempt + 1 < attempts:
                    time.sleep(2)
        except CurlUnavailable as error:
            fail("%s, so Kodi cannot be queried over localhost JSON-RPC"
                 % (error,))
        if not entries:
            fail("Kodi did not answer authenticated JSON-RPC on %s" % url)

        # An installed add-on that Kodi left disabled is enabled here through
        # JSON-RPC (never a modal dialog), and Kodi is then asked again --
        # round after round -- so the reported state is what Kodi observes
        # once it has settled rather than what a single pass asked for.
        entries, enable_attempted, enable_unresolved = converge_enabled_addons(
            curl_config, url, addon_ids, entries)
    finally:
        if os.path.lexists(curl_config):
            os.remove(curl_config)

    observe("observation_format", "coreelec-verification-1")
    observe("jsonrpc_version", jsonrpc_version(entries))
    for setting_id in SETTING_IDS:
        observe("setting." + setting_id, setting_value(entries, setting_id))

    timezone = config("TIMEZONE")
    observe("timezone_cache", timezone_cache_value(storage_root))
    observe("localtime_path", localtime_target(system_root))
    observe("localtime_kind", localtime_kind(system_root))
    observe("localtime_zoneinfo_match",
            localtime_zoneinfo_match(system_root, timezone))
    if timezone:
        verdict, expected_marks, observed_marks = zone_marks_verdict(timezone)
    else:
        verdict, expected_marks, observed_marks = ("unavailable", "", "")
    observe("date_offset_expected", expected_marks)
    observe("date_offset_observed", observed_marks)
    observe("date_matches_timezone", verdict)

    for addon_id in addon_ids:
        installed, version, enabled = addon_state(entries.get("addon:" + addon_id))
        observe("addon.%s.installed" % addon_id, installed)
        observe("addon.%s.version" % addon_id, version)
        observe("addon.%s.enabled" % addon_id, enabled)
        observe("addon.%s.enable_attempted" % addon_id,
                1 if addon_id in enable_attempted else 0)

    # The add-ons Kodi was asked for and still reports disabled, named exactly.
    # An add-on ID is not a secret, and naming them is what tells the operator
    # which ones to look at.
    observe("addon_enable_unresolved", " ".join(enable_unresolved))

    def addon_data(addon_id, name):
        return os.path.join(storage_root, ".kodi", "userdata", "addon_data",
                            addon_id, name)

    if have("HOME_ASSISTANT_TOKEN") and config("HOME_ASSISTANT_URL") \
            and config("HOME_ASSISTANT_WEATHER_ENTITY"):
        values = read_settings(addon_data("weather.ha", "settings.xml")) or {}
        matched = (values.get("ha_server") == config("HOME_ASSISTANT_URL")
                   and values.get("ha_weather_forecast_entity_id")
                   == config("HOME_ASSISTANT_WEATHER_ENTITY")
                   and bool(values.get("ha_key")))
        observe("addon_settings.weather.ha.configured", 1 if matched else 0)

    if have("NEXTPVR_PIN") and config("NEXTPVR_HOST"):
        values = read_settings(
            addon_data("pvr.nextpvr", "instance-settings-1.xml")) or {}
        matched = (values.get("host") == config("NEXTPVR_HOST")
                   and ("%s" % values.get("kodi_addon_instance_enabled", "")).lower() == "true"
                   and bool(values.get("pin")))
        if config("NEXTPVR_PORT"):
            matched = matched and values.get("port") == config("NEXTPVR_PORT")
        observe("addon_settings.pvr.nextpvr.configured", 1 if matched else 0)

    if have("PLEX_TOKEN") and config("PLEX_SERVER_HOST"):
        values = read_settings(
            addon_data("script.plexmod", "settings.xml")) or {}
        matched = ("%s" % values.get("local_mode", "")).lower() == "true"
        try:
            servers = json.loads(values.get("local_servers_json") or "[]")
        except ValueError:
            servers = []
        if not isinstance(servers, list):
            servers = []
        matched = matched and any(
            isinstance(server, dict)
            and server.get("connection") == config("PLEX_SERVER_HOST")
            and bool(server.get("token"))
            for server in servers)
        observe("addon_settings.script.plexmod.configured", 1 if matched else 0)

    if have("YOUTUBE_API_KEY"):
        matched = False
        try:
            handle = open(addon_data("plugin.video.youtube",
                                     "api_keys.json"), "r")
            try:
                document = json.load(handle)
            finally:
                handle.close()
            user = document.get("keys", {}).get("user", {})
            matched = bool(user.get("api_key") and user.get("client_id")
                           and user.get("client_secret"))
        except Exception:
            matched = False
        observe("addon_settings.plugin.video.youtube.configured",
                1 if matched else 0)

    if have("OMDB_API_KEY") or have("MDBLIST_API_KEY"):
        values = read_settings(
            addon_data("plugin.video.themoviedb.helper", "settings.xml")) or {}
        if have("OMDB_API_KEY"):
            observe("addon_settings.plugin.video.themoviedb.helper.omdb_configured",
                    1 if bool(values.get("omdb_apikey")) else 0)
        if have("MDBLIST_API_KEY"):
            observe("addon_settings.plugin.video.themoviedb.helper.mdblist_configured",
                    1 if bool(values.get("mdblist_apikey")) else 0)

    # --- Arctic Fuse skin state -------------------------------------------

    def read_json(path):
        try:
            with open(path, "r") as handle:
                return json.load(handle)
        except Exception:
            return None

    def xml_setting_values(path):
        return read_settings(path) or {}

    def xml_setting_matches(path, setting_id):
        try:
            root = ET.parse(path).getroot()
        except Exception:
            return []
        wanted = setting_id.casefold()
        return [
            node.get("value")
            if node.get("value") is not None
            else (node.text or "")
            for node in root.iter("setting")
            if (node.get("id") or "").casefold() == wanted
        ]

    def smart_playlist_signature(path):
        try:
            root = ET.parse(path).getroot()
        except Exception:
            return None
        return {
            "type": root.get("type"),
            "name": root.findtext("name") or "",
            "match": root.findtext("match") or "",
            "limit": root.findtext("limit") or "",
            "rules": [
                (node.get("field"), node.get("operator"),
                 node.findtext("value") or "")
                for node in root.findall("rule")
            ],
            "order": (
                root.findtext("order") or "",
                (root.find("order").get("direction")
                 if root.find("order") is not None else ""),
            ),
        }

    SKIN_ID = "skin.arctic.fuse.3"
    userdata = os.path.join(storage_root, ".kodi", "userdata")
    skin_settings_path = os.path.join(
        userdata, "addon_data", SKIN_ID, "settings.xml")
    nodes_dir = os.path.join(
        userdata, "addon_data", "script.skinvariables", "nodes", SKIN_ID)
    playlists_dir = os.path.join(userdata, "playlists", "video")

    skin_values = xml_setting_values(skin_settings_path)

    # Hub toggles. Arctic Fuse renders a hub whenever its toggle string is
    # non-empty and may recreate empty disabled placeholders after startup.
    next_aired_toggles = xml_setting_matches(
        skin_settings_path, "HomeSwitcher.1106.Toggle")
    next_aired_modes = xml_setting_matches(
        skin_settings_path, "HomeSwitcher.1106.UpNextMode")
    hubs_ok = (
        all(value == "" for value in next_aired_toggles)
        and all(value == "" for value in next_aired_modes)
        and skin_values.get("HomeSwitcher.1107.Toggle") == "true"
        and skin_values.get("HomeSwitcher.1108.Toggle") == "true"
    )
    observe("arctic_fuse.hubs_configured", 1 if hubs_ok else 0)

    # Plex entry (1101)
    plex_ok = (
        skin_values.get("HomeSwitcher.1101.Name") == "Plex"
        and skin_values.get("HomeSwitcher.1101.Icon")
            == "special://home/addons/script.plexmod/icon2.png"
        and skin_values.get("HomeSwitcher.1101.Shortcut.Path")
            == "RunAddon(script.plexmod)"
        and not skin_values.get("HomeSwitcher.1101.Shortcut.Target")
    )
    observe("arctic_fuse.plex_entry_configured", 1 if plex_ok else 0)

    # YouTube entry (1102)
    youtube_ok = (
        skin_values.get("HomeSwitcher.1102.Name") == "YouTube"
        and skin_values.get("HomeSwitcher.1102.Icon")
            == "special://home/addons/plugin.video.youtube/resources/media/icon.png"
        and skin_values.get("HomeSwitcher.1102.Shortcut.Path")
            == "plugin://plugin.video.youtube/"
        and skin_values.get("HomeSwitcher.1102.Shortcut.Target") == "videos"
    )
    observe("arctic_fuse.youtube_entry_configured", 1 if youtube_ok else 0)

    # Settings tile
    observe("arctic_fuse.settings_tile_configured",
            1 if skin_values.get("optionstiles.02.include") == "Settings" else 0)

    # Home widgets
    expected_home_widgets = [
        {"guid": "coreelec-home-inprogress-movies", "icon": "", "label": "In-Progress Movies", "path": "special://profile/playlists/video/InProgressMovies90Days.xsp", "target": "videos"},
        {"guid": "coreelec-home-inprogress-shows", "icon": "", "label": "In-Progress Shows", "path": "special://profile/playlists/video/InProgressShows90Days.xsp", "target": "videos"},
        {"guid": "coreelec-home-recently-aired-shows", "icon": "", "label": "Recently Aired Shows", "path": "special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp", "target": "videos"},
        {"guid": "coreelec-home-recently-released-movies", "icon": "", "label": "Recently Released Movies", "path": "special://profile/playlists/video/RecentlyReleasedMoviesCurrentYear.xsp", "target": "videos"},
        {"guid": "coreelec-home-new-shows", "icon": "", "label": "New Shows", "path": "special://profile/playlists/video/NewShows.xsp", "target": "videos"},
        {"guid": "coreelec-home-new-movies", "icon": "", "label": "New Movies", "path": "special://profile/playlists/video/NewMovies.xsp", "target": "videos"},
    ]
    actual_home_widgets = read_json(os.path.join(
        nodes_dir, "skinvariables-shortcut-homewidgets.json"))
    observe("arctic_fuse.home_widgets_configured",
            1 if actual_home_widgets == expected_home_widgets else 0)

    # Power menu
    expected_power_menu = [
        {"guid": "coreelec-power-poweroff", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13016]", "path": "Powerdown()", "target": ""},
        {"guid": "coreelec-power-timer", "icon": "special://skin/extras/icons/timer.png", "label": "$LOCALIZE[20150]", "path": "AlarmClock(shutdowntimer,Shutdown())", "target": ""},
        {"guid": "coreelec-power-suspend", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13011]", "path": "Suspend()", "target": ""},
        {"guid": "coreelec-power-reboot", "icon": "special://skin/extras/icons/refresh.png", "label": "$LOCALIZE[13013]", "path": "Reset()", "target": ""},
        {"guid": "coreelec-power-restart-kodi", "icon": "special://skin/extras/icons/refresh.png", "label": "Restart Kodi", "path": "RestartApp()", "target": ""},
    ]
    actual_power_menu = read_json(os.path.join(
        nodes_dir, "skinvariables-shortcut-powermenu.json"))
    observe("arctic_fuse.power_menu_configured",
            1 if actual_power_menu == expected_power_menu else 0)

    # Smart playlists
    EXPECTED_PLAYLISTS = {
        "InProgressMovies90Days": {
            "type": "movies", "name": "In-Progress Movies", "match": "all",
            "limit": "50",
            "rules": [("inprogress", "true", ""), ("lastplayed", "inthelast", "90 days")],
            "order": ("lastplayed", "descending"),
        },
        "InProgressShows90Days": {
            "type": "tvshows", "name": "In-Progress Shows", "match": "all",
            "limit": "50",
            "rules": [("inprogress", "true", ""), ("lastplayed", "inthelast", "90 days")],
            "order": ("lastplayed", "descending"),
        },
        "RecentlyAiredEpisodes30Days": {
            "type": "episodes", "name": "Recently Aired Shows", "match": "all",
            "limit": "50",
            "rules": [("airdate", "inthelast", "30 days"),
                      ("airdate", "notinthelast", "-1 days")],
            "order": ("year", "descending"),
        },
        "RecentlyReleasedMoviesCurrentYear": {
            "type": "movies", "name": "Recently Released Movies", "match": "all",
            "limit": "50",
            "rules": [("year", "is", str(datetime.date.today().year))],
            "order": ("year", "descending"),
        },
        "NewShows": {
            "type": "tvshows", "name": "New Shows", "match": "all",
            "limit": "50",
            "rules": [("playcount", "is", "0")],
            "order": ("dateadded", "descending"),
        },
        "NewMovies": {
            "type": "movies", "name": "New Movies", "match": "all",
            "limit": "50",
            "rules": [("playcount", "is", "0")],
            "order": ("dateadded", "descending"),
        },
    }
    for playlist_name, expected_sig in EXPECTED_PLAYLISTS.items():
        actual_sig = smart_playlist_signature(
            os.path.join(playlists_dir, playlist_name + ".xsp"))
        observe("arctic_fuse.playlist.%s.configured" % playlist_name,
                1 if actual_sig == expected_sig else 0)

    observe(
        "arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent",
        0 if os.path.lexists(os.path.join(
            playlists_dir, "RecentlyReleasedMovies90Days.xsp")) else 1)

    for line in OBSERVATIONS:
        sys.stdout.write(line + "\n")


main(sys.argv)
PYTHON_VERIFY_PROBE_SOURCE
}

# The `sh` program the device runs. It reads the request the Mac uploaded into
# the private provisioning cache, runs the probe, and removes both the request
# and the curl config by trap on every exit path.
coreelec_remote_verify_script() {
  local root="${1:-/storage}"
  cat <<REMOTE_VERIFY_HEADER
set -eu
umask 077
storage_root="${root}"
REMOTE_VERIFY_HEADER
  cat <<'REMOTE_VERIFY_PROLOGUE'
provision_cache="${storage_root}/.cache/coreelec-provision"
request_file="${provision_cache}/verify-request.conf"
curl_config="${provision_cache}/verify-curl.conf"

discard_verification_material() {
  rm -f "${curl_config}" "${request_file}"
}
trap discard_verification_material EXIT HUP INT TERM

[ -f "${request_file}" ] || {
  printf 'remote verification: no verification request was uploaded: %s\n' \
    "${request_file}" >&2
  exit 1
}
rm -f "${curl_config}"

python3 - "${storage_root}" "${request_file}" "${curl_config}" "/" <<'PYTHON_VERIFY_PROBE'
REMOTE_VERIFY_PROLOGUE
  coreelec_remote_verify_probe_source
  cat <<'REMOTE_VERIFY_EPILOGUE'
PYTHON_VERIFY_PROBE
REMOTE_VERIFY_EPILOGUE
}

# Reads the administrator public key file and prints exactly one normalized
# key line. The grammar is enforced here, once, because the line is embedded
# in a program the device runs: a validated line is a single line of a known
# key type, a base64 blob, and an optional control-character-free comment, so
# it can never contain a quote, a newline, or the here-document delimiter that
# carries it. Carriage returns are stripped -- one inside authorized_keys
# makes the key silently unusable.
coreelec_public_key_line() {
  local key_file="$1" normalized line_count line
  [[ -f "${key_file}" ]] || die "The administrator public key file is missing: ${key_file}"
  normalized="$(sed -e 's/\r$//' -e 's/[[:space:]]*$//' "${key_file}" | grep '[^[:space:]]' || true)"
  line_count="$(printf '%s\n' "${normalized}" | grep -c '[^[:space:]]' || true)"
  [[ "${line_count}" == "1" ]] \
    || die "Expected exactly one public key line in ${key_file}, found ${line_count}"
  line="$(printf '%s\n' "${normalized}" | head -1)"
  printf '%s\n' "${line}" | grep -Eq \
    '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com) [A-Za-z0-9+/]+={0,3}( [^[:cntrl:]]*)?$' \
    || die "The administrator public key in ${key_file} is not a well-formed OpenSSH public key line"
  printf '%s\n' "${line}"
}

# Appends the administrator public key to /storage/.ssh/authorized_keys.
#
# This is the one program that runs over the temporary password session,
# before any key exists, so it gets a single attempt on a device the operator
# is standing in front of. Like every other remote program here it is streamed
# to `sh -s`, which leaves `sh` and `-s` as the only argv words: an argv word
# is joined by the ssh client and re-parsed by the device's login shell, so a
# quoted program placed there loses its quoting in transit. The key itself
# rides inside the program in a quoted here-document -- stdin is already
# carrying the program, and the argv would expose the key to that same
# re-parse and to the device's process list.
coreelec_remote_authorized_key_script() {
  local root="${1:-/storage}" key_file="${2:-}" key_line
  [[ -n "${key_file}" ]] || die "The authorized-key emitter requires a public key file"
  key_line="$(coreelec_public_key_line "${key_file}")" || return 1
  cat <<REMOTE_AUTHORIZED_KEY_HEADER
set -eu
umask 077
ssh_dir="${root}/.ssh"
REMOTE_AUTHORIZED_KEY_HEADER
  cat <<'REMOTE_AUTHORIZED_KEY_PROLOGUE'
authorized="${ssh_dir}/authorized_keys"
candidate="${ssh_dir}/authorized_keys.provision-candidate"
mkdir -p "${ssh_dir}"
chmod 700 "${ssh_dir}"
# An interrupted earlier attempt can leave a candidate whose mode, hard links,
# or symlink target this run does not control, so the name is removed before
# the key lands in a file this program creates under umask 077.
rm -f "${candidate}"
REMOTE_AUTHORIZED_KEY_PROLOGUE
  cat <<REMOTE_AUTHORIZED_KEY_DATA
cat > "\${candidate}" <<'COREELEC_ADMIN_PUBLIC_KEY'
${key_line}
COREELEC_ADMIN_PUBLIC_KEY
REMOTE_AUTHORIZED_KEY_DATA
  cat <<'REMOTE_AUTHORIZED_KEY_INSTALL'
chmod 600 "${candidate}"
test -s "${candidate}"
key_blob="$(awk '{ print $2; exit }' "${candidate}")"
test -n "${key_blob}"
touch "${authorized}"
chmod 600 "${authorized}"
# Matching on the blob alone is what makes a retry idempotent: the comment may
# differ between runs, the key material may not.
if ! grep -Fq "${key_blob}" "${authorized}"; then
  cat "${candidate}" >> "${authorized}"
fi
rm -f "${candidate}"
chmod 600 "${authorized}"
# The install only counts if the device can find the key it is about to be
# asked to authenticate with.
grep -Fq "${key_blob}" "${authorized}"
REMOTE_AUTHORIZED_KEY_INSTALL
}

# Internal test entry point: prints one remote script instead of running it.
coreelec_emit_remote_script() {
  local name="$1" root="${2:-/storage}" key_file="${3:-}"
  case "${name}" in
    backup) coreelec_remote_backup_script "${root}" ;;
    payload) coreelec_remote_payload_script "${root}" ;;
    stage) coreelec_remote_stage_script "${root}" ;;
    deploy) coreelec_remote_deploy_script "${root}" ;;
    rollback) coreelec_remote_rollback_script "${root}" ;;
    finalize) coreelec_remote_finalize_script "${root}" ;;
    verify) coreelec_remote_verify_script "${root}" ;;
    verify-probe) coreelec_remote_verify_probe_source ;;
    authorized-key) coreelec_remote_authorized_key_script "${root}" "${key_file}" ;;
    *)
      die "--emit-remote-script expects backup, payload, stage, deploy, rollback, finalize, verify, verify-probe, or authorized-key, not: ${name}"
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
      emit_script_key=""
      if (( config_scan_index + 2 < ${#config_scan_args[@]} )); then
        emit_script_root="${config_scan_args[$((config_scan_index + 2))]}"
      fi
      # The authorized-key emitter needs the public key file as well; every
      # other emitter stops at ROOT.
      if (( config_scan_index + 3 < ${#config_scan_args[@]} )); then
        emit_script_key="${config_scan_args[$((config_scan_index + 3))]}"
      fi
      coreelec_emit_remote_script \
        "${config_scan_args[$((config_scan_index + 1))]}" \
        "${emit_script_root}" \
        "${emit_script_key}"
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
    --verify-fixture)
      (( $# >= 3 )) || die "--verify-fixture requires OBSERVATIONS and MANIFEST"
      VERIFY_FIXTURE=("$2" "$3")
      shift 3
      ;;
    --classify-addon)
      (( $# >= 2 )) || die "--classify-addon requires an add-on ID"
      CLASSIFY_ADDON="$2"
      shift 2
      ;;
    --report-fixture)
      (( $# >= 5 )) || die "--report-fixture requires DIR, OBSERVATIONS, MANIFEST, and REACHABLE"
      REPORT_FIXTURE=("$2" "$3" "$4" "$5")
      shift 5
      ;;
    --conclude-fixture)
      (( $# >= 6 )) \
        || die "--conclude-fixture requires OBSERVATIONS, MANIFEST, FINALIZE_STATUS, ROLLBACK_STATUS, and LOG"
      CONCLUDE_FIXTURE=("$2" "$3" "$4" "$5" "$6")
      shift 6
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

# Requires that both OMDb and MDbList API keys are set when an actual Kodi
# deployment is requested. Both keys are needed to populate Arctic Fuse 3
# ratings metadata; without them the skin is deployed in a broken state.
# Skipped when APPLY_KODI != 1 (--no-kodi) so config and artifact checks
# remain keyless.
require_arctic_fuse_metadata_keys() {
  [[ "${APPLY_KODI}" == "1" ]] || return 0
  [[ -n "${OMDB_API_KEY:-}" ]] \
    || die "OMDB_API_KEY is required for an Arctic Fuse 3 Kodi deployment"
  [[ -n "${MDBLIST_API_KEY:-}" ]] \
    || die "MDBLIST_API_KEY is required for an Arctic Fuse 3 Kodi deployment"
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

# --- Verification, classification, and the redacted report ------------------
#
# Everything below is a pure function of the configuration, the deployment
# manifest, and the observations the device returned. Nothing here contacts a
# host, which is why the test suite can drive the same code the run uses.

# One observation value, or empty when the device did not report that key.
# Add-on IDs are restricted to letters, digits, dot, underscore, and hyphen, so
# a key can never carry glob syntax into this pattern match.
coreelec_observation_value() {
  local key="$1" file="$2" line
  [[ -r "${file}" ]] || return 1
  while IFS= read -r line || [[ -n "${line}" ]]; do
    case "${line}" in
      "${key}="*)
        printf '%s' "${line#*=}"
        return 0
        ;;
    esac
  done < "${file}"
  return 1
}

# Prints an expected/observed/status triple and fails when they differ. The
# report and the pass/fail decision therefore come from the same comparison.
coreelec_report_comparison() {
  local prefix="$1" expected="$2" observed="$3"
  printf '%s.expected=%s\n' "${prefix}" "${expected}"
  printf '%s.observed=%s\n' "${prefix}" "${observed}"
  if [[ "${expected}" == "${observed}" ]]; then
    printf '%s.status=ok\n' "${prefix}"
    return 0
  fi
  printf '%s.status=mismatch\n' "${prefix}"
  return 1
}

coreelec_weather_configured() {
  [[ -n "${HOME_ASSISTANT_URL}" && -n "${HOME_ASSISTANT_WEATHER_ENTITY}" \
     && -n "${HOME_ASSISTANT_TOKEN:-}" ]]
}

coreelec_nextpvr_configured() {
  [[ -n "${NEXTPVR_HOST}" && -n "${NEXTPVR_PIN:-}" ]]
}

coreelec_plex_configured() {
  [[ -n "${PLEX_SERVER_HOST}" && -n "${PLEX_TOKEN:-}" ]]
}

coreelec_tmdb_helper_configured() {
  [[ -n "${OMDB_API_KEY:-}" && -n "${MDBLIST_API_KEY:-}" ]]
}

coreelec_youtube_configured() {
  [[ -n "${YOUTUBE_API_KEY:-}" && -n "${YOUTUBE_CLIENT_ID:-}" \
     && -n "${YOUTUBE_CLIENT_SECRET:-}" ]]
}

# Whether one add-on ID is part of the set this run deployed.
coreelec_manifest_contains() {
  local manifest="$1" wanted="$2" index addon_id rest
  while IFS=$'\t' read -r index addon_id rest; do
    [[ "${addon_id}" == "${wanted}" ]] && return 0
  done < "${manifest}"
  return 1
}

# `configured`          this run wrote the add-on's settings;
# `installed-manual`    the add-on can only be finished interactively;
# `installed-unconfigured` the add-on is deployed but nothing was configured
#                       for it, either because it needs nothing or because its
#                       optional values were not supplied.
classify_addon_status() {
  local addon_id="$1"
  case "${addon_id}" in
    plugin.service.emby-next-gen|plugin.video.youtube)
      # Emby's server/user selection and Google's device authorization are
      # dialog-driven; supplying credentials does not complete either.
      printf 'installed-manual\n'
      ;;
    weather.ha)
      if coreelec_weather_configured; then
        printf 'configured\n'
      else
        printf 'installed-unconfigured\n'
      fi
      ;;
    pvr.nextpvr)
      if coreelec_nextpvr_configured; then
        printf 'configured\n'
      else
        printf 'installed-unconfigured\n'
      fi
      ;;
    script.plexmod)
      if coreelec_plex_configured; then
        printf 'configured\n'
      else
        printf 'installed-unconfigured\n'
      fi
      ;;
    plugin.video.themoviedb.helper)
      if coreelec_tmdb_helper_configured; then
        printf 'configured\n'
      else
        printf 'installed-unconfigured\n'
      fi
      ;;
    skin.arctic.fuse.3|resource.language.en_us)
      # Both are activated by the regional baseline this run applies.
      printf 'configured\n'
      ;;
    *)
      printf 'installed-unconfigured\n'
      ;;
  esac
}

# Compares the device's observations with what this run requested. Prints the
# report lines for the comparison and returns nonzero on any mismatch, which
# is what makes a verification failure fatal rather than advisory. It returns
# rather than exits even when its own inputs are unusable, because the caller
# is the code that rolls the deployment back.
verify_remote_baseline() {
  local observations="$1" manifest="$2"
  local failures=0
  local index addon_id version filename observed_version installed enabled attempted
  local addon_failed value content match expected_marks observed_marks

  if [[ ! -r "${observations}" ]]; then
    warn "Verification observations are not readable: ${observations}"
    printf 'verification_source=device-localhost-jsonrpc\n'
    printf 'verification_error=the verification observations are not readable\n'
    printf 'verification_failures=1\n'
    printf 'verification_result=fail\n'
    return 1
  fi
  if [[ ! -r "${manifest}" ]]; then
    warn "Deployment manifest is not readable: ${manifest}"
    printf 'verification_source=device-localhost-jsonrpc\n'
    printf 'verification_error=the deployment manifest is not readable\n'
    printf 'verification_failures=1\n'
    printf 'verification_result=fail\n'
    return 1
  fi

  printf 'verification_source=device-localhost-jsonrpc\n'

  value="$(coreelec_observation_value jsonrpc_version "${observations}" || true)"
  printf 'jsonrpc.version=%s\n' "${value}"
  if [[ -n "${value}" ]]; then
    printf 'jsonrpc.status=ok\n'
  else
    printf 'jsonrpc.status=mismatch\n'
    failures=$((failures + 1))
  fi

  coreelec_report_comparison "regional.locale.language" "${LOCALE_LANGUAGE}" \
    "$(coreelec_observation_value setting.locale.language "${observations}" || true)" \
    || failures=$((failures + 1))
  coreelec_report_comparison "regional.locale.country" "${LOCALE_COUNTRY}" \
    "$(coreelec_observation_value setting.locale.country "${observations}" || true)" \
    || failures=$((failures + 1))
  coreelec_report_comparison "regional.locale.keyboardlayouts" "${KEYBOARD_LAYOUT}" \
    "$(coreelec_observation_value setting.locale.keyboardlayouts "${observations}" || true)" \
    || failures=$((failures + 1))
  coreelec_report_comparison "regional.locale.timezonecountry" "${TIMEZONE_COUNTRY}" \
    "$(coreelec_observation_value setting.locale.timezonecountry "${observations}" || true)" \
    || failures=$((failures + 1))
  coreelec_report_comparison "regional.locale.timezone" "${TIMEZONE}" \
    "$(coreelec_observation_value setting.locale.timezone "${observations}" || true)" \
    || failures=$((failures + 1))
  coreelec_report_comparison "regional.timezone_cache" "${TIMEZONE}" \
    "$(coreelec_observation_value timezone_cache "${observations}" || true)" \
    || failures=$((failures + 1))

  # CoreELEC images differ both in where the zoneinfo tree lives and in how
  # /etc/localtime is stored. A symlink is matched against the tail of its
  # target, because the tree's prefix is not fixed. A plain copy of the zone
  # file resolves to /etc/localtime and has no zone in its path at all, so it
  # is judged by the byte comparison the device performed against its own
  # copy of the requested zone. Anything else is still a mismatch: unproven is
  # not proven.
  value="$(coreelec_observation_value localtime_path "${observations}" || true)"
  content="$(coreelec_observation_value localtime_zoneinfo_match "${observations}" || true)"
  printf 'regional.localtime.expected=%s\n' "${TIMEZONE}"
  printf 'regional.localtime.observed=%s\n' "${value}"
  printf 'regional.localtime.kind=%s\n' \
    "$(coreelec_observation_value localtime_kind "${observations}" || true)"
  case "${value}" in
    */"${TIMEZONE}"|"${TIMEZONE}") match="symlink" ;;
    *)
      if [[ "${content}" == "1" ]]; then
        match="zoneinfo-copy"
      else
        match="none"
      fi
      ;;
  esac
  printf 'regional.localtime.match=%s\n' "${match}"
  if [[ "${match}" == "none" ]]; then
    printf 'regional.localtime.status=mismatch\n'
    failures=$((failures + 1))
  else
    printf 'regional.localtime.status=ok\n'
  fi

  # What the device's own `date` reported, as the same expected/observed pair
  # as every other regional value. The verdict is the device's, and only a
  # well-formed comparison can veto: the timezone cache, /etc/localtime, and
  # Kodi's own timezone setting are the applied state this run wrote and are
  # checked strictly above, while `date +%Z%z` is a BusyBox capability
  # question. An unexpanded format or any other unexpected answer is recorded
  # as unavailable and never rolls back a correctly configured device.
  value="$(coreelec_observation_value date_matches_timezone "${observations}" || true)"
  expected_marks="$(coreelec_observation_value date_offset_expected "${observations}" || true)"
  observed_marks="$(coreelec_observation_value date_offset_observed "${observations}" || true)"
  printf 'regional.date_offset.expected=%s\n' "${expected_marks:-unavailable}"
  printf 'regional.date_offset.observed=%s\n' "${observed_marks:-unavailable}"
  case "${value}" in
    1) printf 'regional.date_offset.status=ok\n' ;;
    0)
      printf 'regional.date_offset.status=mismatch\n'
      failures=$((failures + 1))
      ;;
    *)
      printf 'regional.date_offset.status=unavailable\n'
      ;;
  esac

  # The skin and the weather provider are only verified when this run
  # deployed the add-on that provides them.
  if coreelec_manifest_contains "${manifest}" "skin.arctic.fuse.3"; then
    coreelec_report_comparison "skin" "skin.arctic.fuse.3" \
      "$(coreelec_observation_value setting.lookandfeel.skin "${observations}" || true)" \
      || failures=$((failures + 1))
  fi

  value="$(coreelec_observation_value setting.weather.addon "${observations}" || true)"
  if coreelec_weather_configured && coreelec_manifest_contains "${manifest}" "weather.ha"; then
    coreelec_report_comparison "weather_provider" "weather.ha" "${value}" \
      || failures=$((failures + 1))
  else
    # Without a Home Assistant URL, entity, and token the run deliberately
    # leaves the existing provider alone; reporting it is not a verdict.
    printf 'weather_provider.expected=unchanged\n'
    printf 'weather_provider.observed=%s\n' "${value}"
    printf 'weather_provider.status=not-configured\n'
  fi

  while IFS=$'\t' read -r index addon_id version filename; do
    [[ -n "${addon_id}" ]] || continue
    addon_failed=0
    installed="$(coreelec_observation_value "addon.${addon_id}.installed" "${observations}" || true)"
    observed_version="$(coreelec_observation_value "addon.${addon_id}.version" "${observations}" || true)"
    enabled="$(coreelec_observation_value "addon.${addon_id}.enabled" "${observations}" || true)"
    attempted="$(coreelec_observation_value "addon.${addon_id}.enable_attempted" "${observations}" || true)"
    printf 'addon.%s.requested_version=%s\n' "${addon_id}" "${version}"
    printf 'addon.%s.observed_version=%s\n' "${addon_id}" "${observed_version}"
    printf 'addon.%s.installed=%s\n' "${addon_id}" "${installed:-0}"
    printf 'addon.%s.enabled=%s\n' "${addon_id}" "${enabled:-0}"
    printf 'addon.%s.enable_attempted=%s\n' "${addon_id}" "${attempted:-0}"
    printf 'addon.%s.status=%s\n' "${addon_id}" "$(classify_addon_status "${addon_id}")"
    [[ "${installed}" == "1" ]] || addon_failed=1
    [[ "${enabled}" == "1" ]] || addon_failed=1
    [[ "${observed_version}" == "${version}" ]] || addon_failed=1
    if (( addon_failed == 0 )); then
      printf 'addon.%s.verification=ok\n' "${addon_id}"
    else
      printf 'addon.%s.verification=mismatch\n' "${addon_id}"
      failures=$((failures + 1))
    fi
  done < "${manifest}"

  # The add-ons the device asked Kodi to enable and Kodi still reports
  # disabled, named exactly. Each one already counted as a failure above; this
  # line says which they were, so the operator does not have to read the whole
  # per-add-on block to find out. An add-on ID is not a secret.
  value="$(coreelec_observation_value addon_enable_unresolved "${observations}" || true)"
  if [[ -n "${value}" ]]; then
    printf 'addon_enable_unresolved=%s\n' "${value}"
  fi

  # Files this run configured are checked on the device, which returns a
  # boolean rather than the stored token, key, or PIN.
  coreelec_verify_addon_settings "${observations}" "${manifest}" \
    "weather.ha" coreelec_weather_configured || failures=$((failures + 1))
  coreelec_verify_addon_settings "${observations}" "${manifest}" \
    "pvr.nextpvr" coreelec_nextpvr_configured || failures=$((failures + 1))
  coreelec_verify_addon_settings "${observations}" "${manifest}" \
    "script.plexmod" coreelec_plex_configured || failures=$((failures + 1))
  coreelec_verify_addon_settings "${observations}" "${manifest}" \
    "plugin.video.youtube" coreelec_youtube_configured || failures=$((failures + 1))

  # Split ratings-key verification: each key is independently fatal.
  local arctic_fuse_failures=0
  if [[ -n "${OMDB_API_KEY:-}" ]]; then
    coreelec_verify_boolean_observation "${observations}" \
      "addon_settings.plugin.video.themoviedb.helper.omdb_configured" \
      "metadata.omdb" || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
  fi
  if [[ -n "${MDBLIST_API_KEY:-}" ]]; then
    coreelec_verify_boolean_observation "${observations}" \
      "addon_settings.plugin.video.themoviedb.helper.mdblist_configured" \
      "metadata.mdblist" || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
  fi

  # Arctic Fuse skin surfaces
  coreelec_verify_boolean_observation "${observations}" \
    "arctic_fuse.hubs_configured" "arctic_fuse.hubs" \
    || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
  coreelec_verify_boolean_observation "${observations}" \
    "arctic_fuse.plex_entry_configured" "arctic_fuse.plex_entry" \
    || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
  coreelec_verify_boolean_observation "${observations}" \
    "arctic_fuse.youtube_entry_configured" "arctic_fuse.youtube_entry" \
    || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
  coreelec_verify_boolean_observation "${observations}" \
    "arctic_fuse.settings_tile_configured" "arctic_fuse.settings_tile" \
    || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
  coreelec_verify_boolean_observation "${observations}" \
    "arctic_fuse.home_widgets_configured" "arctic_fuse.home" \
    || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
  coreelec_verify_boolean_observation "${observations}" \
    "arctic_fuse.power_menu_configured" "arctic_fuse.power" \
    || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }

  local playlist_name
  for playlist_name in InProgressMovies90Days InProgressShows90Days \
    RecentlyAiredEpisodes30Days RecentlyReleasedMoviesCurrentYear NewShows NewMovies; do
    coreelec_verify_boolean_observation "${observations}" \
      "arctic_fuse.playlist.${playlist_name}.configured" \
      "arctic_fuse.playlist.${playlist_name}" \
      || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }
  done

  coreelec_verify_boolean_observation "${observations}" \
    "arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent" \
    "arctic_fuse.playlist_migration" \
    || { failures=$((failures + 1)); arctic_fuse_failures=$((arctic_fuse_failures + 1)); }

  if (( arctic_fuse_failures == 0 )); then
    printf 'arctic_fuse.status=ok\n'
  else
    printf 'arctic_fuse.status=mismatch\n'
  fi

  printf 'verification_failures=%s\n' "${failures}"
  if (( failures == 0 )); then
    printf 'verification_result=pass\n'
    return 0
  fi
  printf 'verification_result=fail\n'
  return 1
}

# Compares one boolean observation against the expected value of 1.
coreelec_verify_boolean_observation() {
  local observations="$1" observation_key="$2" report_prefix="$3"
  coreelec_report_comparison "${report_prefix}" "1" \
    "$(coreelec_observation_value "${observation_key}" "${observations}" || true)"
}

coreelec_verify_addon_settings() {
  local observations="$1" manifest="$2" addon_id="$3" predicate="$4" value
  coreelec_manifest_contains "${manifest}" "${addon_id}" || return 0
  if ! "${predicate}"; then
    printf 'addon.%s.settings_verified=not-configured\n' "${addon_id}"
    return 0
  fi
  value="$(coreelec_observation_value "addon_settings.${addon_id}.configured" "${observations}" || true)"
  if [[ "${value}" == "1" ]]; then
    printf 'addon.%s.settings_verified=1\n' "${addon_id}"
    return 0
  fi
  printf 'addon.%s.settings_verified=0\n' "${addon_id}"
  return 1
}

# The exact value of one supported secret, read from the environment only
# through this explicit allowlist (never through indirect expansion).
coreelec_secret_value() {
  case "$1" in
    KODI_WEB_PASSWORD) printf '%s' "${KODI_WEB_PASSWORD:-}" ;;
    OMDB_API_KEY) printf '%s' "${OMDB_API_KEY:-}" ;;
    MDBLIST_API_KEY) printf '%s' "${MDBLIST_API_KEY:-}" ;;
    YOUTUBE_API_KEY) printf '%s' "${YOUTUBE_API_KEY:-}" ;;
    YOUTUBE_CLIENT_ID) printf '%s' "${YOUTUBE_CLIENT_ID:-}" ;;
    YOUTUBE_CLIENT_SECRET) printf '%s' "${YOUTUBE_CLIENT_SECRET:-}" ;;
    HOME_ASSISTANT_TOKEN) printf '%s' "${HOME_ASSISTANT_TOKEN:-}" ;;
    NEXTPVR_PIN) printf '%s' "${NEXTPVR_PIN:-}" ;;
    PLEX_TOKEN) printf '%s' "${PLEX_TOKEN:-}" ;;
    EMBY_PASSWORD) printf '%s' "${EMBY_PASSWORD:-}" ;;
    *) die "Internal error: unknown secret name: $1" ;;
  esac
}

coreelec_secret_names() {
  cat <<'SECRET_NAMES'
KODI_WEB_PASSWORD
OMDB_API_KEY
MDBLIST_API_KEY
YOUTUBE_API_KEY
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
HOME_ASSISTANT_TOKEN
NEXTPVR_PIN
PLEX_TOKEN
EMBY_PASSWORD
SECRET_NAMES
}

# A digest of the configuration this run applied. Only non-secret values are
# fed to it, so the fingerprint identifies a configuration without being able
# to confirm a guessed secret.
coreelec_config_fingerprint() {
  local digest record
  digest="$( {
    printf 'EXPECTED_RELEASE=%s\n' "${EXPECTED_RELEASE}"
    printf 'SSH_PORT=%s\n' "${SSH_PORT}"
    printf 'KODI_PORT=%s\n' "${KODI_PORT}"
    printf 'KODI_USER=%s\n' "${KODI_USER}"
    printf 'APPLY_KODI=%s\n' "${APPLY_KODI}"
    printf 'HARDEN_SSH=%s\n' "${HARDEN_SSH}"
    printf 'TIMEZONE=%s\n' "${TIMEZONE}"
    printf 'TIMEZONE_COUNTRY=%s\n' "${TIMEZONE_COUNTRY}"
    printf 'LOCALE_LANGUAGE=%s\n' "${LOCALE_LANGUAGE}"
    printf 'LOCALE_COUNTRY=%s\n' "${LOCALE_COUNTRY}"
    printf 'KEYBOARD_LAYOUT=%s\n' "${KEYBOARD_LAYOUT}"
    printf 'ADDON_UPDATE_MODE=%s\n' "${ADDON_UPDATE_MODE}"
    printf 'HOME_ASSISTANT_URL=%s\n' "${HOME_ASSISTANT_URL}"
    printf 'HOME_ASSISTANT_WEATHER_ENTITY=%s\n' "${HOME_ASSISTANT_WEATHER_ENTITY}"
    printf 'HOME_ASSISTANT_SUN_ENTITY=%s\n' "${HOME_ASSISTANT_SUN_ENTITY}"
    printf 'NEXTPVR_HOST=%s\n' "${NEXTPVR_HOST}"
    printf 'NEXTPVR_PORT=%s\n' "${NEXTPVR_PORT}"
    printf 'NEXTPVR_PROTOCOL=%s\n' "${NEXTPVR_PROTOCOL}"
    printf 'NEXTPVR_INSTANCE_NAME=%s\n' "${NEXTPVR_INSTANCE_NAME}"
    printf 'PLEX_SERVER_HOST=%s\n' "${PLEX_SERVER_HOST}"
    printf 'PLEX_SERVER_PORT=%s\n' "${PLEX_SERVER_PORT}"
    printf 'PLEX_SERVER_NAME=%s\n' "${PLEX_SERVER_NAME}"
    printf 'PLEX_PROFILE_IDS=%s\n' "${PLEX_PROFILE_IDS}"
    printf 'EMBY_SERVER_URL=%s\n' "${EMBY_SERVER_URL}"
    printf 'EMBY_USERNAME=%s\n' "${EMBY_USERNAME}"
    printf 'EMBY_ALLOW_LOCAL_HTTP=%s\n' "${EMBY_ALLOW_LOCAL_HTTP}"
    for record in ${ADDON_ARTIFACTS[@]+"${ADDON_ARTIFACTS[@]}"}; do
      printf 'ADDON_ARTIFACT=%s\n' "${record}"
    done
  } | shasum -a 256 | awk '{print $1}')"
  printf 'sha256:%s\n' "${digest}"
}

# The interactive work this run cannot do, in a fixed order. A step is listed
# only when the add-on it belongs to was deployed, and only when provisioning
# did not already complete it.
coreelec_report_manual_actions() {
  local manifest="$1" number=0

  if coreelec_manifest_contains "${manifest}" "plugin.service.emby-next-gen"; then
    number=$((number + 1))
    printf 'manual_action.%s=Emby: select the server and sign in from Kodi; Emby Next Gen stores server and user state in its own database and cannot be preseeded.\n' "${number}"
  fi
  if coreelec_manifest_contains "${manifest}" "plugin.video.youtube"; then
    number=$((number + 1))
    printf 'manual_action.%s=YouTube: complete Google device authorization in the add-on to sign in; API credentials alone do not sign an account in.\n' "${number}"
  fi
  if coreelec_manifest_contains "${manifest}" "script.plexmod" && ! coreelec_plex_configured; then
    number=$((number + 1))
    printf 'manual_action.%s=Plex: link the account in PM4K or set PLEX_SERVER_HOST and PLEX_TOKEN to configure local mode.\n' "${number}"
  fi
  if coreelec_manifest_contains "${manifest}" "pvr.nextpvr" && ! coreelec_nextpvr_configured; then
    number=$((number + 1))
    printf 'manual_action.%s=NextPVR: set the server host and PIN in the client instance, or supply NEXTPVR_HOST and NEXTPVR_PIN.\n' "${number}"
  fi
  if coreelec_manifest_contains "${manifest}" "weather.ha" && ! coreelec_weather_configured; then
    number=$((number + 1))
    printf 'manual_action.%s=Home Assistant Weather: set the Home Assistant URL, long-lived token, and forecast entity, then select the provider.\n' "${number}"
  fi
  if coreelec_manifest_contains "${manifest}" "plugin.video.themoviedb.helper"; then
    number=$((number + 1))
    printf 'manual_action.%s=Next Aired is disabled because the installed TMDb Helper requires Trakt OAuth and the local-data alternative is not reliable on this device class.\n' "${number}"
  fi
  printf 'manual_actions=%s\n' "${number}"
}

# The report body. Every line is key=value; the raw device inventory the
# production report appends afterwards is the one deliberately free-form
# section, and it is fenced by begin/end markers.
coreelec_report_render() {
  local manifest="$1" name value index filename
  printf 'report_format=coreelec-provisioning-report-2\n'
  printf 'script_version=%s\n' "${SCRIPT_VERSION}"
  printf 'created_utc=%s\n' "$(timestamp)"
  printf 'target=%s\n' "${TARGET}"
  printf 'ssh_port=%s\n' "${SSH_PORT}"
  printf 'identity_file=%s\n' "${IDENTITY_FILE}"
  printf 'ssh_password_auth_disabled=%s\n' "${HARDEN_SSH}"
  printf 'config_file=%s\n' "${CONFIG_FILE}"
  printf 'config_fingerprint=%s\n' "$(coreelec_config_fingerprint)"
  printf 'kodi_baseline_requested=%s\n' "${APPLY_KODI}"
  if [[ "${APPLY_KODI}" == "1" ]]; then
    printf 'kodi_jsonrpc=http://%s:%s/jsonrpc\n' "${TARGET}" "${KODI_PORT}"
    printf 'kodi_username=%s\n' "${KODI_USER}"
    printf 'kodi_password=stored-in-macos-keychain\n'
  fi
  # Reachability from this Mac is environmental: the device verified itself
  # over its own localhost JSON-RPC, so a blocked port cannot demote a
  # successful verification to a warning.
  printf 'kodi_jsonrpc_reachable_from_mac=%s\n' "${KODI_JSONRPC_LOCAL_REACHABLE}"
  if [[ -n "${REMOTE_BACKUP_PATH}" ]]; then
    printf 'remote_backup_path=%s\n' "${REMOTE_BACKUP_PATH}"
  fi

  if (( ${#ADDONS[@]} > 0 )); then
    printf 'requested_addons=%s\n' "$(printf '%s,' ${ADDONS[@]+"${ADDONS[@]}"} | sed 's/,$//')"
    printf 'addon_selection=subset\n'
    # A narrowed selection deploys exactly what was named; nothing resolves
    # its dependencies, so that stays the operator's problem and is stated.
    printf 'addon_dependency_resolution=manual\n'
  else
    printf 'requested_addons=all-locked-artifacts\n'
    printf 'addon_selection=all-locked-artifacts\n'
    printf 'addon_dependency_resolution=complete-locked-closure\n'
  fi

  if [[ -n "${REMOTE_TRANSACTION}" ]]; then
    printf 'deployment_transaction=%s\n' "${REMOTE_TRANSACTION}"
  fi
  printf 'deployment_state=%s\n' "${DEPLOYMENT_STATE}"
  printf 'verification_result=%s\n' "${VERIFICATION_RESULT}"
  # What this run deployed, independently of what verification observed, so
  # the record of the change survives even a failed verification.
  if [[ -n "${manifest}" && -r "${manifest}" ]]; then
    while IFS=$'\t' read -r index name value filename; do
      [[ -n "${name}" ]] || continue
      printf 'deployed_addon.%s=%s\n' "${name}" "${value}"
    done < "${manifest}"
  fi
  if [[ -n "${VERIFICATION_REPORT_FILE}" && -r "${VERIFICATION_REPORT_FILE}" ]]; then
    # The comparison lines are already report-shaped, and they are the same
    # lines the pass/fail decision was made from.
    grep -v '^verification_result=' "${VERIFICATION_REPORT_FILE}" || true
  fi
  if [[ -n "${RECOVERY_INSTRUCTIONS}" ]]; then
    printf '%s\n' "${RECOVERY_INSTRUCTIONS}"
  fi

  coreelec_secret_names | while IFS= read -r name; do
    [[ -n "${name}" ]] || continue
    value="0"
    [[ -n "$(coreelec_secret_value "${name}")" ]] && value="1"
    printf 'secret_present.%s=%s\n' "${name}" "${value}"
  done

  if [[ -n "${manifest}" && -r "${manifest}" ]]; then
    coreelec_report_manual_actions "${manifest}"
  fi
}

# Fails, and destroys the report, if any supplied secret occurs in it
# literally. The patterns are piped to grep so no secret reaches an argument
# list, and the diagnostic names the variable rather than echoing its value.
coreelec_report_redaction_check() {
  local report_file="$1" name value
  while IFS= read -r name; do
    [[ -n "${name}" ]] || continue
    value="$(coreelec_secret_value "${name}")"
    [[ -n "${value}" ]] || continue
    # Blank pattern lines are dropped: an empty pattern matches every line and
    # would delete a clean report. A multi-line secret is still caught,
    # because each of its non-blank lines is its own fixed-string pattern.
    if printf '%s\n' "${value}" | grep -v '^[[:space:]]*$' \
      | grep -F -q -f - "${report_file}"; then
      rm -f "${report_file}"
      die "The audit report contained the literal value of ${name} and was deleted. This is a provisioner defect; report it before re-running."
    fi
  done <<EOF
$(coreelec_secret_names)
EOF
}

# Writes one report file: the key=value body, optionally the raw device
# inventory, then the redaction guard. The guard runs before the path is
# announced, so a report that leaked a secret is never handed to anyone.
coreelec_write_report_file() {
  local report_file="$1" manifest="$2" include_inventory="$3"
  local report_dir
  report_dir="$(dirname "${report_file}")"
  mkdir -p "${report_dir}"
  chmod 700 "${report_dir}"
  rm -f "${report_file}"
  {
    coreelec_report_render "${manifest}"
    if [[ "${include_inventory}" == "1" ]]; then
      printf 'remote_inventory=begin\n'
      coreelec_remote_inventory
      printf 'remote_inventory=end\n'
    fi
  } > "${report_file}"
  chmod 600 "${report_file}"
  coreelec_report_redaction_check "${report_file}"
  printf '%s\n' "${report_file}"
}

# Decides the fate of the pending deployment transaction: verify first,
# finalize only on success, roll back on failure. Returns nonzero when the
# deployment must not be treated as complete; the caller still writes the
# report before failing, because a failed run needs its record most.
coreelec_conclude_deployment() {
  local manifest="$1"
  local observations="${TASK_TEMP_DIR}/verify-observations.conf"
  local verification="${TASK_TEMP_DIR}/verification.conf"
  local status=0

  DEPLOYMENT_STATE="pending-verification"
  info "Verifying the deployed baseline on the device over localhost JSON-RPC" >&2
  : > "${observations}"
  chmod 600 "${observations}" 2>/dev/null || true
  # A probe that cannot run is a verification failure, not a fatal error: the
  # deployment still has to be undone rather than left half-committed.
  coreelec_collect_remote_observations "${observations}" || status=$?

  # `|| status=$?` rather than toggling errexit: this function is called from
  # both an errexit and a non-errexit context, and toggling it here would
  # change the caller's setting behind its back.
  if (( status == 0 )); then
    verify_remote_baseline "${observations}" "${manifest}" > "${verification}" \
      || status=$?
  else
    printf 'verification_source=device-localhost-jsonrpc\n' > "${verification}"
    printf 'verification_error=the device did not answer the verification probe\n' \
      >> "${verification}"
  fi
  chmod 600 "${verification}" 2>/dev/null || true
  VERIFICATION_REPORT_FILE="${verification}"

  if (( status == 0 )); then
    VERIFICATION_RESULT="pass"
    info "Device verification passed; committing the deployment transaction" >&2
    if finalize_remote_deployment >/dev/null; then
      DEPLOYMENT_STATE="committed"
      return 0
    fi
    # The device is verified but the rollback material could not be released.
    # Nothing was undone, so the transaction stays pending for the operator.
    DEPLOYMENT_STATE="pending-verification"
    RECOVERY_INSTRUCTIONS="$(coreelec_recovery_instructions finalize)"
    warn "The verified deployment could not be finalized; the transaction is still pending"
    return 1
  fi

  VERIFICATION_RESULT="fail"
  warn "Device verification failed; rolling back the deployment transaction"
  if rollback_remote_deployment >/dev/null; then
    DEPLOYMENT_STATE="rolled-back"
    return 1
  fi

  DEPLOYMENT_STATE="incomplete-rollback"
  RECOVERY_INSTRUCTIONS="$(coreelec_recovery_instructions rollback)"
  return 1
}

# The exact commands and retained paths an operator needs when the device
# could not finish the transaction by itself.
coreelec_recovery_instructions() {
  local kind="$1"
  printf 'recovery.reason=%s\n' "${kind}"
  printf 'recovery.transaction=%s\n' "${REMOTE_TRANSACTION}"
  printf 'recovery.pointer_file=/storage/.cache/coreelec-provision/current-transaction\n'
  printf 'recovery.staging_directory=/storage/.cache/coreelec-provision/stage\n'
  if [[ "${kind}" == "finalize" ]]; then
    printf 'recovery.command=%s --target %s --finalize-deployment\n' "$0" "${TARGET}"
  else
    printf 'recovery.command=%s --target %s --rollback-deployment\n' "$0" "${TARGET}"
  fi
  printf 'recovery.inspect=ssh -i %s -p %s root@%s\n' \
    "${IDENTITY_FILE}" "${SSH_PORT}" "${TARGET}"
}

# The report file name identifies the device and the moment, so repeated runs
# accumulate rather than overwrite each other.
coreelec_report_path() {
  local report_dir="$1" target_slug
  target_slug="$(printf '%s' "${TARGET:-fixture}" | tr -c 'A-Za-z0-9._-' '_')"
  printf '%s/%s-%s.txt\n' "${report_dir}" "${target_slug}" "$(date -u +%Y%m%dT%H%M%SZ)"
}

# --- Internal fixture entry points -------------------------------------------
#
# These run the production verification, classification, report, and
# transaction-outcome code with the three device calls replaced by stubs, so
# the test suite exercises the same functions a real run uses without a device.

if (( ${#VERIFY_FIXTURE[@]} > 0 )); then
  verify_remote_baseline "${VERIFY_FIXTURE[0]}" "${VERIFY_FIXTURE[1]}"
  exit $?
fi

if [[ -n "${CLASSIFY_ADDON}" ]]; then
  classify_addon_status "${CLASSIFY_ADDON}"
  exit 0
fi

if (( ${#REPORT_FIXTURE[@]} > 0 )); then
  TASK_TEMP_DIR="$(mktemp -d "${REPORT_FIXTURE[0]}.XXXXXX")"
  KODI_JSONRPC_LOCAL_REACHABLE="${REPORT_FIXTURE[3]}"
  REMOTE_TRANSACTION="fixture-transaction"
  coreelec_collect_remote_observations() { cp "${REPORT_FIXTURE[1]}" "$1"; }
  finalize_remote_deployment() { printf '%s\n' "${REMOTE_TRANSACTION}"; }
  rollback_remote_deployment() { printf '%s\n' "${REMOTE_TRANSACTION}"; }
  coreelec_conclude_deployment "${REPORT_FIXTURE[2]}" >/dev/null 2>&1 || true
  coreelec_write_report_file \
    "$(coreelec_report_path "${REPORT_FIXTURE[0]}")" "${REPORT_FIXTURE[2]}" "0"
  exit 0
fi

if (( ${#CONCLUDE_FIXTURE[@]} > 0 )); then
  TASK_TEMP_DIR="$(mktemp -d "${CONCLUDE_FIXTURE[4]}.XXXXXX")"
  REMOTE_TRANSACTION="fixture-transaction"
  : > "${CONCLUDE_FIXTURE[4]}"
  coreelec_collect_remote_observations() {
    printf 'verify\n' >> "${CONCLUDE_FIXTURE[4]}"
    cp "${CONCLUDE_FIXTURE[0]}" "$1"
  }
  finalize_remote_deployment() {
    printf 'finalize\n' >> "${CONCLUDE_FIXTURE[4]}"
    return "${CONCLUDE_FIXTURE[2]}"
  }
  rollback_remote_deployment() {
    printf 'rollback\n' >> "${CONCLUDE_FIXTURE[4]}"
    return "${CONCLUDE_FIXTURE[3]}"
  }
  set +e
  coreelec_conclude_deployment "${CONCLUDE_FIXTURE[1]}"
  conclude_status=$?
  set -e
  printf 'verification_result=%s\n' "${VERIFICATION_RESULT}"
  printf 'deployment_state=%s\n' "${DEPLOYMENT_STATE}"
  [[ -z "${RECOVERY_INSTRUCTIONS}" ]] || printf '%s\n' "${RECOVERY_INSTRUCTIONS}"
  exit "${conclude_status}"
fi

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

require_arctic_fuse_metadata_keys

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
# Every run ends by writing the audit report, whose configuration fingerprint
# is a shasum call -- including the --no-kodi run that deploys no add-ons.
require_command shasum

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

  # The program is rendered (and the key validated) before the pipeline, so a
  # malformed key file fails here instead of silently feeding an empty program
  # to the device.
  local install_program
  install_program="$(coreelec_remote_authorized_key_script "/storage" "${IDENTITY_FILE}.pub")" \
    || die "Could not build the SSH public key installation program from ${IDENTITY_FILE}.pub"

  if ! printf '%s\n' "${install_program}" | ssh_password 'sh -s'; then
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

  # This probe is a convenience check of the operator's own network path. The
  # verification that decides the run's outcome happens on the device against
  # Kodi's localhost endpoint, so a firewall between this Mac and the device
  # is recorded here and nowhere else.
  info "Checking whether Kodi JSON-RPC is reachable from this Mac on TCP ${KODI_PORT}"
  while (( attempt <= 5 )); do
    if curl --config "${CURL_CONFIG_FILE}" \
      -H 'Content-Type: application/json' \
      --data-binary '{"jsonrpc":"2.0","id":1,"method":"JSONRPC.Version"}' \
      "http://${TARGET}:${KODI_PORT}/jsonrpc" > "${response_file}" 2>/dev/null; then
      if grep -q '"result"' "${response_file}"; then
        KODI_JSONRPC_LOCAL_REACHABLE="1"
        info "Kodi JSON-RPC is reachable from this Mac"
        return
      fi
    fi
    sleep 2
    attempt=$((attempt + 1))
  done

  KODI_JSONRPC_LOCAL_REACHABLE="0"
  warn "Kodi JSON-RPC is not reachable from this Mac on TCP ${KODI_PORT}; check pfSense. Verification is unaffected: the device checks itself over its own localhost endpoint."
}

# The verification request. Only the Kodi web password crosses to the device
# again, because the probe must authenticate to Kodi. Every other secret is
# sent as a presence flag: the probe compares the device's own files and
# answers with a boolean.
coreelec_verify_request() {
  local index id version filename ids=""
  coreelec_settings_payload_entry KODI_WEB_USER "${KODI_USER}"
  coreelec_settings_payload_entry KODI_WEB_PASSWORD "${KODI_WEB_PASSWORD}"
  coreelec_settings_payload_entry KODI_PORT "${KODI_PORT}"
  coreelec_settings_payload_entry TIMEZONE "${TIMEZONE}"
  coreelec_settings_payload_entry HOME_ASSISTANT_URL "${HOME_ASSISTANT_URL}"
  coreelec_settings_payload_entry HOME_ASSISTANT_WEATHER_ENTITY "${HOME_ASSISTANT_WEATHER_ENTITY}"
  coreelec_settings_payload_entry NEXTPVR_HOST "${NEXTPVR_HOST}"
  coreelec_settings_payload_entry NEXTPVR_PORT "${NEXTPVR_PORT}"
  coreelec_settings_payload_entry PLEX_SERVER_HOST "${PLEX_SERVER_HOST}"
  coreelec_settings_payload_entry HAVE_HOME_ASSISTANT_TOKEN \
    "$([[ -n "${HOME_ASSISTANT_TOKEN:-}" ]] && printf '1' || printf '0')"
  coreelec_settings_payload_entry HAVE_NEXTPVR_PIN \
    "$([[ -n "${NEXTPVR_PIN:-}" ]] && printf '1' || printf '0')"
  coreelec_settings_payload_entry HAVE_PLEX_TOKEN \
    "$([[ -n "${PLEX_TOKEN:-}" ]] && printf '1' || printf '0')"
  coreelec_settings_payload_entry HAVE_YOUTUBE_API_KEY \
    "$([[ -n "${YOUTUBE_API_KEY:-}" ]] && printf '1' || printf '0')"
  coreelec_settings_payload_entry HAVE_OMDB_API_KEY \
    "$([[ -n "${OMDB_API_KEY:-}" ]] && printf '1' || printf '0')"
  coreelec_settings_payload_entry HAVE_MDBLIST_API_KEY \
    "$([[ -n "${MDBLIST_API_KEY:-}" ]] && printf '1' || printf '0')"
  while IFS=$'\t' read -r index id version filename; do
    [[ -n "${id}" ]] || continue
    ids="${ids}${id}"$'\n'
  done < "${DEPLOY_MANIFEST}"
  coreelec_settings_payload_entry ADDON_IDS "${ids}"
}

upload_kodi_verify_request() {
  local script
  script="$(coreelec_remote_payload_script /storage verify-request.conf)"
  [[ "${script}" != *"'"* ]] \
    || die "Internal error: the remote payload script must not contain a single quote"
  coreelec_verify_request | ssh_keyed "sh -c '${script}'"
}

# Removes the uploaded verification request. The verify script's own trap does
# this on every path it reaches, so this covers the case where the request was
# uploaded but the probe never ran.
discard_remote_verify_request() {
  local payload_dir="/storage/.cache/coreelec-provision"
  ssh_keyed 'sh -c '\''
    set -eu
    rm -f "$1/verify-request.conf" "$1/verify-request.conf.provision-new" \
      "$1/verify-curl.conf"
  '\'' sh' "${payload_dir}" >/dev/null 2>&1 \
    || warn "Could not confirm removal of the uploaded verification request in ${payload_dir}"
}

# Asks the device what state it is actually in. The probe runs on the device
# and writes its observations to this file. A failure here is a verification
# failure rather than a fatal error, so the caller can still roll the
# deployment back: a baseline that cannot be observed must not be committed.
coreelec_collect_remote_observations() {
  local destination="$1" status=0
  upload_kodi_verify_request
  coreelec_remote_verify_script | ssh_keyed 'sh -s' > "${destination}" || status=$?
  if (( status != 0 )); then
    discard_remote_verify_request
    warn "The device could not be verified over its localhost JSON-RPC endpoint"
    return 1
  fi
}

# The device inventory appended to the report. It is the one deliberately
# free-form section, fenced by begin/end markers so a parser can skip it.
coreelec_remote_inventory() {
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
}

write_audit_report() {
  coreelec_write_report_file "$(coreelec_report_path "${REPORT_DIR}")" \
    "${DEPLOY_MANIFEST}" "1"
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
# The platform read is the first remote call of a run. Both of its paths end
# the run on failure, so each one reports what the operator has to fix instead
# of leaving ssh's transport status as the only explanation.
if ssh_keyed_batch true >/dev/null 2>&1; then
  KEY_ALREADY_ACCEPTED="1"
  REMOTE_IDENTITY="$(remote_identity)" || die "Could not read the platform from root@${TARGET}:${SSH_PORT} using ${IDENTITY_FILE}. Confirm the device is still reachable and that the administrator key is still authorized. Nothing on the device has been changed."
else
  info "Enter the temporary CoreELEC root password for this read-only platform check."
  REMOTE_IDENTITY="$(remote_identity_with_password)" || die "Could not complete the read-only platform check on root@${TARGET}:${SSH_PORT}. Confirm the device is powered on and reachable at that address, that SSH is enabled in CoreELEC's Services settings, and that the temporary root password is correct. Nothing on the device has been changed."
fi
printf '%s\n' "${REMOTE_IDENTITY}"
validate_remote "${REMOTE_IDENTITY}"

# Every artifact is downloaded, checksum-verified, and inspected before the
# first mutating SSH call, so a bad or unreachable artifact cancels the run
# while the device is still untouched.
if [[ "${APPLY_KODI}" == "1" ]]; then
  require_command unzip
  require_command xmllint
  require_command tar
  ARTIFACT_STAGE_DIR="${TASK_TEMP_DIR}/artifacts"
  info "Validating pinned add-on artifacts before changing anything on the device"
  coreelec_artifacts_download_and_validate "${ARTIFACT_STAGE_DIR}"
  # Resolving the selection here keeps every "which add-ons" decision -- and
  # every way it can be refused -- on the untouched-device side of the run.
  coreelec_addon_selection "${ARTIFACT_STAGE_DIR}/manifest.tsv" > "${ARTIFACT_STAGE_DIR}/deploy.tsv"
  DEPLOY_MANIFEST="${ARTIFACT_STAGE_DIR}/deploy.tsv"
fi

install_public_key_if_needed

REMOTE_BACKUP_PATH="$(create_remote_backup)"
info "Remote backup created: ${REMOTE_BACKUP_PATH}"

harden_remote_ssh

KEYCHAIN_SERVICE=""
CONCLUDE_STATUS=0
if [[ "${APPLY_KODI}" == "1" ]]; then
  KEYCHAIN_SERVICE="$(keychain_service_name)"
  prepare_kodi_password "${KEYCHAIN_SERVICE}"
  apply_kodi_baseline
  # Verify before committing: a deployment that cannot be confirmed on the
  # device is undone rather than finalized, and the report is written either
  # way because a failed run is the one that most needs its record.
  set +e
  coreelec_conclude_deployment "${DEPLOY_MANIFEST}"
  CONCLUDE_STATUS=$?
  set -e
elif (( ${#ADDONS[@]} > 0 )); then
  warn "Add-on selection was ignored because --no-kodi was selected"
fi

REPORT_FILE="$(write_audit_report)"

if (( CONCLUDE_STATUS != 0 )); then
  printf 'Audit report: %s\n' "${REPORT_FILE}" >&2
  if [[ -n "${RECOVERY_INSTRUCTIONS}" ]]; then
    printf '%s\n' "${RECOVERY_INSTRUCTIONS}" >&2
  fi
  case "${DEPLOYMENT_STATE}" in
    incomplete-rollback)
      die "Verification failed and the rollback did not complete. The transaction and its pointer are retained on the device; run the recovery command above before using this device."
      ;;
    pending-verification)
      die "The deployment was verified but could not be finalized. It is still pending; run the recovery command above."
      ;;
    *)
      die "Verification failed and the deployment was rolled back. The device is back to its pre-deployment state; see the audit report."
      ;;
  esac
fi

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
  printf '\nDeployment transaction: %s\n' "${REMOTE_TRANSACTION}"
  printf 'State: %s (verification: %s)\n' "${DEPLOYMENT_STATE}" "${VERIFICATION_RESULT}"
  printf 'The dated backup named in the report remains on the device.\n'
fi
printf 'Use the wired MAC in the audit report for the pfSense DHCP reservation.\n'
