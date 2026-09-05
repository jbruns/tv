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
    info "Artifact download and validation are not implemented in this version."
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

upload_kodi_config_payload() {
  {
    printf 'KODI_WEB_USER=%s\n' "${KODI_USER}"
    printf 'KODI_WEB_PASSWORD=%s\n' "${KODI_WEB_PASSWORD}"
    printf 'KODI_WEB_PORT=%s\n' "${KODI_PORT}"
  } | ssh_keyed 'sh -c '\''
    set -eu
    umask 077
    mkdir -p /storage/.cache/coreelec-provision
    cat > /storage/.cache/coreelec-provision/kodi-web.conf
    chmod 600 /storage/.cache/coreelec-provision/kodi-web.conf
  '\'''
}

apply_kodi_baseline() {
  info "Applying the reversible Kodi and Home Assistant baseline"
  upload_kodi_config_payload

  ssh_keyed 'sh -s' <<'REMOTE_KODI_CONFIG'
set -eu
config_file=/storage/.cache/coreelec-provision/kodi-web.conf

cleanup_remote_config() {
  rm -f "${config_file}"
  systemctl start kodi.service >/dev/null 2>&1 || true
}
trap cleanup_remote_config EXIT HUP INT TERM

systemctl stop kodi.service >/dev/null 2>&1 || true

python3 - <<'PYTHON_KODI_SETTINGS'
import os
import xml.etree.ElementTree as ET

config_path = "/storage/.cache/coreelec-provision/kodi-web.conf"
settings_path = "/storage/.kodi/userdata/guisettings.xml"

config = {}
with open(config_path, "r", encoding="utf-8") as handle:
    for raw_line in handle:
        key, value = raw_line.rstrip("\n").split("=", 1)
        config[key] = value

if os.path.exists(settings_path):
    tree = ET.parse(settings_path)
    root = tree.getroot()
else:
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    root = ET.Element("settings", {"version": "2"})
    tree = ET.ElementTree(root)

values = (
    ("services.webserver", "true"),
    ("services.webserverport", config["KODI_WEB_PORT"]),
    ("services.webserverauthentication", "true"),
    ("services.webserverusername", config["KODI_WEB_USER"]),
    ("services.webserverpassword", config["KODI_WEB_PASSWORD"]),
    ("services.webserverssl", "false"),
    ("services.esenabled", "true"),
    ("services.esallinterfaces", "false"),
    ("videoplayer.adjustrefreshrate", "2"),
    ("videoplayer.usedisplayasclock", "false"),
    ("general.addonupdates", "1"),
)

def set_setting(setting_id, value):
    matches = [
        node for node in root.findall("setting")
        if node.get("id") == setting_id
    ]
    if matches:
        node = matches[0]
        for duplicate in matches[1:]:
            root.remove(duplicate)
    else:
        node = ET.SubElement(root, "setting", {"id": setting_id})
    node.attrib.pop("default", None)
    node.text = value

for identifier, configured_value in values:
    set_setting(identifier, configured_value)

if hasattr(ET, "indent"):
    ET.indent(tree, space="    ")

temporary_path = settings_path + ".provision-new"
tree.write(temporary_path, encoding="UTF-8", xml_declaration=True)
os.chmod(temporary_path, 0o600)
os.replace(temporary_path, settings_path)
PYTHON_KODI_SETTINGS

systemctl start kodi.service
rm -f "${config_file}"
trap - EXIT HUP INT TERM
REMOTE_KODI_CONFIG

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
