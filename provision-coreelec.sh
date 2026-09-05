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

TASK_TEMP_DIR=""
CURL_CONFIG_FILE=""
KODI_WEB_PASSWORD=""
KEY_ALREADY_ACCEPTED="0"

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
  --addon ID                Install an add-on from an enabled repository; repeatable
  --with-youtube            Equivalent to --addon plugin.video.youtube
  --report-dir PATH         Local report directory
  --expected-release VER    Required CoreELEC release substring (default: 21.3)
  --no-kodi                 Skip Kodi and Home Assistant baseline configuration
  --no-harden               Leave SSH password authentication enabled
  --force-unsupported       Continue after release/platform checks fail
  --yes                     Do not ask for final confirmation
  --version                 Print script version
  -h, --help                Show this help

Internal:
  --transform-fixture ROOT PAYLOAD
                            Apply the Kodi/add-on settings transformer to ROOT
                             using a base64 KEY=value payload file, then exit.
                             Used by tests/test-coreelec-settings.sh; it never
                             contacts a device.

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


def fail(message):
    raise SystemExit("settings transformer: " + message)


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


def _atomic_write(path, data, mode):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = path + ".provision-new"
    with open(temporary, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
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

    def config(key, default=""):
        return payload.get(key, default)

    def have(key):
        return payload.get("HAVE_" + key, "0") == "1"

    def secret(key):
        return config(key) if have(key) else ""

    userdata = os.path.join(storage_root, ".kodi", "userdata")
    addon_data = os.path.join(userdata, "addon_data")

    def addon_file(addon_id, name):
        return os.path.join(addon_data, addon_id, name)

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
        value = kodi_values[setting_id]
        if value == "":
            continue
        set_kodi_setting(guisettings_root, setting_id, value)
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
        if config("HOME_ASSISTANT_SUN_ENTITY"):
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


main(sys.argv)
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

for addon_id in "${ADDONS[@]}"; do
  validate_identifier "Add-on ID" "${addon_id}"
done

coreelec_config_validate

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
  ssh_keyed 'sh -s' <<'REMOTE_BACKUP'
set -eu
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="/storage/backup/coreelec-provision/${stamp}"
mkdir -p "${backup}"

copy_one() {
  source_path="$1"
  if [ -f "${source_path}" ]; then
    relative_path="${source_path#/storage/}"
    destination_dir="${backup}/$(dirname "${relative_path}")"
    mkdir -p "${destination_dir}"
    cp -p "${source_path}" "${backup}/${relative_path}"
  fi
}

copy_one /storage/.ssh/authorized_keys
copy_one /storage/.cache/services/sshd.conf
copy_one /storage/.cache/hostname
copy_one /storage/.kodi/userdata/guisettings.xml
copy_one /storage/.kodi/userdata/advancedsettings.xml
copy_one /storage/.kodi/userdata/sources.xml
copy_one /storage/.kodi/userdata/addon_data/service.coreelec.settings/oe_settings.xml
copy_one /storage/.cache/timezone
copy_one /storage/.kodi/userdata/addon_data/plugin.video.youtube/settings.xml
copy_one /storage/.kodi/userdata/addon_data/plugin.video.youtube/api_keys.json
copy_one /storage/.kodi/userdata/addon_data/plugin.video.themoviedb.helper/settings.xml
copy_one /storage/.kodi/userdata/addon_data/pvr.nextpvr/instance-settings-1.xml
copy_one /storage/.kodi/userdata/addon_data/script.plexmod/settings.xml
copy_one /storage/.kodi/userdata/addon_data/weather.ha/settings.xml

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
  # file, and the remote trap removes it even if the transformer fails.
  coreelec_settings_payload | ssh_keyed 'sh -c '\''
    set -eu
    umask 077
    mkdir -p /storage/.cache/coreelec-provision
    chmod 700 /storage/.cache/coreelec-provision
    cat > /storage/.cache/coreelec-provision/settings-payload.conf
    chmod 600 /storage/.cache/coreelec-provision/settings-payload.conf
  '\'''
}

coreelec_remote_settings_script() {
  cat <<'REMOTE_SETTINGS_PROLOGUE'
set -eu
payload_file=/storage/.cache/coreelec-provision/settings-payload.conf

cleanup_remote_payload() {
  rm -f "${payload_file}"
  systemctl start kodi.service >/dev/null 2>&1 || true
}
trap cleanup_remote_payload EXIT HUP INT TERM

# Kodi rewrites guisettings.xml from memory when it exits, so it has to be
# stopped before the files are edited or the changes would be discarded.
systemctl stop kodi.service >/dev/null 2>&1 || true

python3 - /storage "${payload_file}" <<'PYTHON_KODI_SETTINGS'
REMOTE_SETTINGS_PROLOGUE

  coreelec_settings_transformer_source

  cat <<'REMOTE_SETTINGS_EPILOGUE'
PYTHON_KODI_SETTINGS

systemctl restart tz-data.service >/dev/null 2>&1 || true
systemctl start kodi.service
rm -f "${payload_file}"
trap - EXIT HUP INT TERM
REMOTE_SETTINGS_EPILOGUE
}

apply_kodi_baseline() {
  info "Applying the reversible Kodi and Home Assistant baseline"
  upload_kodi_settings_payload

  # Only the names of the configured integrations are logged; a value that
  # came from a secret environment variable is never printed.
  [[ -n "${YOUTUBE_API_KEY:-}" ]] && info "YouTube API credentials will be configured"
  [[ -n "${OMDB_API_KEY:-}" || -n "${MDBLIST_API_KEY:-}" ]] && info "TMDb Helper metadata keys will be configured"
  [[ -n "${HOME_ASSISTANT_TOKEN:-}" ]] && info "Home Assistant weather will be configured"
  [[ -n "${NEXTPVR_PIN:-}" ]] && info "NextPVR client instance will be configured"
  [[ -n "${PLEX_TOKEN:-}" ]] && info "PM4K local mode will be configured"

  coreelec_remote_settings_script | ssh_keyed 'sh -s'

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

install_requested_addons() {
  (( ${#ADDONS[@]} > 0 )) || return 0

  info "Refreshing enabled Kodi repositories"
  ssh_keyed 'kodi-send --action="UpdateLocalAddons" >/dev/null 2>&1; kodi-send --action="UpdateAddonRepos" >/dev/null 2>&1'
  sleep 8

  local addon_id
  local attempt
  for addon_id in "${ADDONS[@]}"; do
    info "Requesting Kodi add-on installation: ${addon_id}"
    ssh_keyed "kodi-send --action='InstallAddon(${addon_id})' >/dev/null 2>&1"
    attempt="1"
    while (( attempt <= 30 )); do
      if ssh_keyed "[ -f '/storage/.kodi/addons/${addon_id}/addon.xml' ] || [ -f '/usr/share/kodi/addons/${addon_id}/addon.xml' ]"; then
        info "Kodi add-on is present: ${addon_id}"
        break
      fi
      sleep 3
      attempt=$((attempt + 1))
    done
    if (( attempt > 30 )); then
      warn "Kodi did not install ${addon_id}. Its repository may not be enabled, or the repository may be unreachable."
    fi
  done
}

write_audit_report() {
  local report_stamp
  local target_slug
  local report_file
  report_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target_slug="$(printf '%s' "${TARGET}" | tr -c 'A-Za-z0-9._-' '_')"
  mkdir -p "${REPORT_DIR}"
  chmod 700 "${REPORT_DIR}"
  report_file="${REPORT_DIR}/${target_slug}-${report_stamp}.txt"

  {
    printf 'CoreELEC provisioning report\n'
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
    if (( ${#ADDONS[@]} > 0 )); then
      printf 'requested_addons='
      printf '%s ' "${ADDONS[@]}"
      printf '\n'
    else
      printf 'requested_addons=none\n'
    fi
    printf '\nRemote inventory\n'

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

if [[ "${ASSUME_YES}" != "1" ]]; then
  printf 'Target:             %s\n' "${TARGET}"
  printf 'Expected release:   %s / Amlogic-ng\n' "${EXPECTED_RELEASE}"
  printf 'Administrator key:  %s\n' "${IDENTITY_FILE}"
  printf 'Harden SSH:         %s\n' "${HARDEN_SSH}"
  printf 'Apply Kodi baseline:%s\n' "${APPLY_KODI}"
  printf 'Requested add-ons:  %s\n' "${#ADDONS[@]}"
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

install_public_key_if_needed

REMOTE_BACKUP_PATH="$(create_remote_backup)"
info "Remote backup created: ${REMOTE_BACKUP_PATH}"

harden_remote_ssh

KEYCHAIN_SERVICE=""
if [[ "${APPLY_KODI}" == "1" ]]; then
  KEYCHAIN_SERVICE="$(keychain_service_name)"
  prepare_kodi_password "${KEYCHAIN_SERVICE}"
  apply_kodi_baseline
  install_requested_addons
elif (( ${#ADDONS[@]} > 0 )); then
  warn "Add-on requests were ignored because --no-kodi was selected"
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
printf 'Use the wired MAC in the audit report for the pfSense DHCP reservation.\n'
