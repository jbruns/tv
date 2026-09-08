#!/bin/bash

# Bash 3.2-compatible helpers for the post-deployment CoreELEC add-on CLI.

if ! declare -F die >/dev/null 2>&1; then
  die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
  }
fi

if ! declare -F warn >/dev/null 2>&1; then
  warn() {
    printf 'WARNING: %s\n' "$*" >&2
  }
fi

coreelec_postdeploy_supported_addons() {
  cat <<'ADDONS'
weather.ha
pvr.nextpvr
script.plexmod
plugin.video.youtube
plugin.service.emby-next-gen
ADDONS
}

coreelec_postdeploy_supported_addon() {
  local addon_id="$1" supported
  while IFS= read -r supported; do
    [[ -n "${supported}" ]] || continue
    [[ "${supported}" == "${addon_id}" ]] && return 0
  done <<EOF
$(coreelec_postdeploy_supported_addons)
EOF
  return 1
}

coreelec_postdeploy_addon_interaction_level() {
  case "$1" in
    weather.ha|pvr.nextpvr)
      printf 'fully-unattended\n'
      ;;
    script.plexmod)
      printf 'fully-unattended / guided (--interactive)\n'
      ;;
    plugin.video.youtube|plugin.service.emby-next-gen)
      printf 'guided (--interactive)\n'
      ;;
    *)
      die "No post-deployment workflow is defined for add-on: $1"
      ;;
  esac
}

coreelec_postdeploy_secret_names() {
  cat <<'SECRETS'
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
SECRETS
}

coreelec_postdeploy_secret_value() {
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
    *)
      die "Unknown secret requested: $1"
      ;;
  esac
}

coreelec_postdeploy_keychain_service_name() {
  local sanitized
  sanitized="$(printf '%s' "${TARGET}" | tr -c 'A-Za-z0-9._-' '_')"
  printf 'coreelec-kodi-ha-%s' "${sanitized}"
}

coreelec_prepare_kodi_web_password() {
  local service_name
  if [[ -n "${KODI_WEB_PASSWORD:-}" ]]; then
    return 0
  fi
  command -v security >/dev/null 2>&1 \
    || die "KODI_WEB_PASSWORD is unset and the macOS security command is unavailable"
  service_name="$(coreelec_postdeploy_keychain_service_name)"
  KODI_WEB_PASSWORD="$(security find-generic-password -a "${KODI_USER}" -s "${service_name}" -w 2>/dev/null || true)"
  [[ -n "${KODI_WEB_PASSWORD}" ]] \
    || die "Could not load the Kodi web password from macOS Keychain service ${service_name}; export KODI_WEB_PASSWORD or re-run the provisioner first"
}

coreelec_prepare_emby_password() {
  if [[ -n "${EMBY_PASSWORD:-}" ]]; then
    return 0
  fi
  [[ -t 0 ]] || return 1
  printf 'Emby password for %s: ' "${EMBY_USERNAME}" >&2
  IFS= read -r -s EMBY_PASSWORD
  printf '\n' >&2
  [[ -n "${EMBY_PASSWORD}" ]]
}

coreelec_trim_surrounding_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

kodi_rpc_request_id() {
  case "$1" in
    JSONRPC.Introspect) printf 'introspect\n' ;;
    GUI.GetProperties) printf 'gui-state\n' ;;
    *)
      printf '%s' "$1" \
        | tr '[:upper:]' '[:lower:]' \
        | tr '.' '-' \
        | tr -cd 'a-z0-9_-'
      printf '\n'
      ;;
  esac
}

coreelec_postdeploy_ssh_batch() {
  local identity_file="${IDENTITY_FILE:-${HOME}/.ssh/coreelec_admin_ed25519}"
  [[ "$#" -eq 1 ]] || die "coreelec_postdeploy_ssh_batch requires one remote script argument"
  [[ -n "${TARGET:-}" ]] || die "TARGET is required before calling coreelec_postdeploy_ssh_batch"
  [[ -n "${SSH_PORT:-}" ]] || die "SSH_PORT is required before calling coreelec_postdeploy_ssh_batch"
  ssh \
    -p "${SSH_PORT}" \
    -o ConnectTimeout=12 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    -i "${identity_file}" \
    -o IdentitiesOnly=yes \
    -o PreferredAuthentications=publickey \
    -o PasswordAuthentication=no \
    -o KbdInteractiveAuthentication=no \
    -o BatchMode=yes \
    "root@${TARGET}" \
    "$1"
}

kodi_rpc() {
  local method="$1" params_json="$2"
  local request_id request_json remote_command
  [[ -n "${TARGET:-}" ]] || die "TARGET is required before calling kodi_rpc"
  [[ -n "${SSH_PORT:-}" ]] || die "SSH_PORT is required before calling kodi_rpc"
  [[ -n "${KODI_PORT:-}" ]] || die "KODI_PORT is required before calling kodi_rpc"
  [[ -n "${KODI_USER:-}" ]] || die "KODI_USER is required before calling kodi_rpc"
  [[ -n "${KODI_WEB_PASSWORD:-}" ]] || die "KODI_WEB_PASSWORD is required before calling kodi_rpc"

  request_id="$(kodi_rpc_request_id "${method}")"
  request_json="$(KODI_RPC_METHOD="${method}" \
    KODI_RPC_REQUEST_ID="${request_id}" \
    KODI_RPC_PARAMS="${params_json}" \
    python3 - <<'PYEOF'
import json
import os
import sys

payload = {
    "jsonrpc": "2.0",
    "id": os.environ["KODI_RPC_REQUEST_ID"],
    "method": os.environ["KODI_RPC_METHOD"],
    "params": json.loads(os.environ["KODI_RPC_PARAMS"]),
}
sys.stdout.write(json.dumps(payload, separators=(",", ":")))
PYEOF
)" || die "Failed to build JSON-RPC request for ${method}"

  remote_command="$(cat <<EOF
set -eu
cache_dir="\${HOME}/.cache"
mkdir -p "\${cache_dir}"
chmod 700 "\${cache_dir}"
cfg="\${cache_dir}/coreelec-addon-rpc-curl.\$\$"
body="\${cache_dir}/coreelec-addon-rpc-body.\$\$"
cleanup() {
  rm -f -- "\${cfg}" "\${body}"
}
trap cleanup EXIT HUP INT TERM
umask 077
IFS= read -r rpc_user || exit 1
IFS= read -r rpc_password || exit 1
cat > "\${body}"
cat > "\${cfg}" <<CONFIG
user = "\${rpc_user}:\${rpc_password}"
url = "http://127.0.0.1:${KODI_PORT}/jsonrpc"
header = "Content-Type: application/json"
request = POST
data = @\${body}
silent
show-error
fail
max-time = 10
CONFIG
# Files are born private under umask 077; chmod is defense in depth.
chmod 600 "\${cfg}" "\${body}"
curl --config "\${cfg}"
EOF
)"

  printf '%s\n%s\n%s\n' "${KODI_USER}" "${KODI_WEB_PASSWORD}" "${request_json}" \
    | coreelec_postdeploy_ssh_batch "${remote_command}"
}

kodi_capabilities() {
  local response missing
  response="$(kodi_rpc "JSONRPC.Introspect" '{"getdescriptions":false,"getmetadata":false}')"
  missing="$(printf '%s' "${response}" | python3 -c '
import json
import sys

required = [
    "JSONRPC.Introspect",
    "JSONRPC.NotifyAll",
    "XBMC.GetInfoLabels",
    "Addons.ExecuteAddon",
    "Addons.GetAddonDetails",
    "GUI.ActivateWindow",
    "GUI.GetProperties",
    "Input.ExecuteAction",
    "Input.SendText",
    "Settings.GetSettingValue",
]
# PVR.GetChannelGroups is intentionally advisory in check_nextpvr, so it is
# not a global capability requirement.
try:
    payload = json.load(sys.stdin)
except Exception as exc:
    sys.stdout.write("invalid introspection response: %s" % exc)
    raise SystemExit(1)

if payload.get("error"):
    sys.stdout.write("introspection error: %s" % payload["error"].get("message", "unknown"))
    raise SystemExit(1)

methods = payload.get("result", {}).get("methods")
names = set()
if isinstance(methods, dict):
    names.update(methods.keys())
elif isinstance(methods, list):
    for item in methods:
        if isinstance(item, dict):
            name = item.get("name") or item.get("id")
            if name:
                names.add(name)
else:
    sys.stdout.write("introspection response did not contain a methods object")
    raise SystemExit(1)

missing = [name for name in required if name not in names]
if missing:
    sys.stdout.write(", ".join(missing))
    raise SystemExit(1)
sys.stdout.write("ok")
')" || die "JSON-RPC introspection is missing required method(s): ${missing}"
  printf '%s\n' "${response}"
}

kodi_gui_state() {
  kodi_rpc "GUI.GetProperties" '{"properties":["currentwindow","currentcontrol"]}'
}

coreelec_postdeploy_parse_gui_state() {
  local response="$1" parsed observed_window observed_control
  parsed="$(printf '%s' "${response}" | python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except Exception as exc:
    sys.stderr.write("manual-required: invalid GUI state response: %s\n" % exc)
    raise SystemExit(1)

if payload.get("error"):
    sys.stderr.write("manual-required: GUI.GetProperties failed: %s\n" %
                     payload["error"].get("message", "unknown"))
    raise SystemExit(1)

result = payload.get("result", {})
window = result.get("currentwindow", {}) if isinstance(result.get("currentwindow"), dict) else {}
control = result.get("currentcontrol", {}) if isinstance(result.get("currentcontrol"), dict) else {}
sys.stdout.write("%s\n%s\n" % (window.get("label", ""), control.get("label", "")))
')" || return 1
  observed_window="$(printf '%s\n' "${parsed}" | sed -n '1p')"
  observed_control="$(printf '%s\n' "${parsed}" | sed -n '2p')"
  observed_window="$(coreelec_trim_surrounding_whitespace "${observed_window}")"
  observed_control="$(coreelec_trim_surrounding_whitespace "${observed_control}")"

  KODI_GUI_WINDOW_LABEL="${observed_window}"
  KODI_GUI_CONTROL_LABEL="${observed_control}"
  return 0
}

capture_gui_state() {
  local response
  response="$(kodi_gui_state)" || return 1
  coreelec_postdeploy_parse_gui_state "${response}"
}

require_gui_state() {
  local expected_window expected_control
  expected_window="$(coreelec_trim_surrounding_whitespace "$1")"
  expected_control="$(coreelec_trim_surrounding_whitespace "$2")"
  capture_gui_state || return 1
  if [[ "${KODI_GUI_WINDOW_LABEL}" != "${expected_window}" || "${KODI_GUI_CONTROL_LABEL}" != "${expected_control}" ]]; then
    printf 'manual-required: expected window=%s control=%s observed window=%s control=%s\n' \
      "${expected_window}" "${expected_control}" "${KODI_GUI_WINDOW_LABEL}" "${KODI_GUI_CONTROL_LABEL}" >&2
    return 1
  fi
  return 0
}

coreelec_postdeploy_pinned_addon_version() {
  local wanted="$1" record addon_id remainder version
  for record in ${ADDON_ARTIFACTS[@]+"${ADDON_ARTIFACTS[@]}"}; do
    addon_id="${record%%|*}"
    remainder="${record#*|}"
    version="${remainder%%|*}"
    if [[ "${addon_id}" == "${wanted}" ]]; then
      printf '%s\n' "${version}"
      return 0
    fi
  done
  return 1
}

coreelec_postdeploy_addon_version() {
  local addon_id="$1" response
  response="$(kodi_rpc "Addons.GetAddonDetails" "{\"addonid\":\"${addon_id}\",\"properties\":[\"version\"]}")" \
    || return 1
  RESPONSE_JSON="${response}" python3 - <<'PYEOF'
import json
import os
import sys

try:
    payload = json.loads(os.environ["RESPONSE_JSON"])
except Exception:
    raise SystemExit(1)

if payload.get("error"):
    raise SystemExit(1)

addon = payload.get("result", {}).get("addon")
if not isinstance(addon, dict):
    raise SystemExit(1)

version = addon.get("version")
if not isinstance(version, str) or not version:
    raise SystemExit(1)

sys.stdout.write(version)
PYEOF
}

coreelec_postdeploy_require_pinned_addon_version() {
  local addon_id="$1" observe_prefix="$2" expected_version observed_version
  expected_version="$(coreelec_postdeploy_pinned_addon_version "${addon_id}" 2>/dev/null || true)"
  observed_version="$(coreelec_postdeploy_addon_version "${addon_id}" 2>/dev/null || true)"
  [[ -n "${expected_version}" ]] && coreelec_postdeploy_observe "${observe_prefix}.requested_version" "${expected_version}"
  [[ -n "${observed_version}" ]] && coreelec_postdeploy_observe "${observe_prefix}.observed_version" "${observed_version}"
  if [[ -z "${expected_version}" || -z "${observed_version}" || "${observed_version}" != "${expected_version}" ]]; then
    coreelec_postdeploy_observe "${observe_prefix}.failure" "version-mismatch"
    return 1
  fi
  return 0
}

coreelec_postdeploy_read_addon_data_file() {
  local addon_id="$1" relative_path="$2" remote_command
  [[ -n "${TARGET:-}" ]] || die "TARGET is required before calling coreelec_postdeploy_read_addon_data_file"
  [[ -n "${SSH_PORT:-}" ]] || die "SSH_PORT is required before calling coreelec_postdeploy_read_addon_data_file"
  remote_command="$(cat <<'EOF'
set -eu
IFS= read -r addon_id || exit 1
IFS= read -r relative_path || exit 1
path="${HOME}/.kodi/userdata/addon_data/${addon_id}/${relative_path}"
if [ -f "${path}" ]; then
  cat "${path}"
fi
EOF
)"
  printf '%s\n%s\n' "${addon_id}" "${relative_path}" \
    | coreelec_postdeploy_ssh_batch "${remote_command}"
}

coreelec_postdeploy_pm4k_account_token_present() {
  local settings_xml
  settings_xml="$(coreelec_postdeploy_read_addon_data_file "script.plexmod" "settings.xml")" || return 1
  SETTINGS_XML="${settings_xml}" python3 - <<'PYEOF'
import json
import os
import sys
import xml.etree.ElementTree as ET

text = os.environ.get("SETTINGS_XML", "")
if not text.strip():
    sys.stdout.write("0")
    raise SystemExit(0)

try:
    root = ET.fromstring(text)
except Exception:
    raise SystemExit(1)

settings = {}
for node in root.findall(".//setting"):
    setting_id = node.attrib.get("id", "")
    value = (node.text or "").strip()
    settings[setting_id] = value

token = settings.get("auth.token", "").strip()
if not token:
    account_state = settings.get("myplex.MyPlexAccount", "").strip()
    if account_state:
        try:
            token = (json.loads(account_state).get("authToken") or "").strip()
        except Exception:
            raise SystemExit(1)

sys.stdout.write("1" if token else "0")
PYEOF
}

coreelec_postdeploy_youtube_token_present() {
  local access_manager_json
  access_manager_json="$(coreelec_postdeploy_read_addon_data_file "plugin.video.youtube" "access_manager.json")" || return 1
  ACCESS_MANAGER_JSON="${access_manager_json}" python3 - <<'PYEOF'
import json
import os
import sys

text = os.environ.get("ACCESS_MANAGER_JSON", "")
if not text.strip():
    sys.stdout.write("0")
    raise SystemExit(0)

try:
    payload = json.loads(text)
except Exception:
    raise SystemExit(1)

def has_token(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("access_token", "refresh_token") and isinstance(item, str) and item.strip():
                return True
            if has_token(item):
                return True
    elif isinstance(value, list):
        for item in value:
            if has_token(item):
                return True
    return False

sys.stdout.write("1" if has_token(payload) else "0")
PYEOF
}

coreelec_postdeploy_guided_timeout_seconds() {
  local value="${COREELEC_GUIDED_FLOW_TIMEOUT_SECONDS:-300}"
  case "${value}" in
    ''|*[!0-9]*) value="300" ;;
  esac
  printf '%s\n' "${value}"
}

coreelec_postdeploy_guided_poll_interval_seconds() {
  local value="${COREELEC_GUIDED_FLOW_POLL_INTERVAL_SECONDS:-5}"
  case "${value}" in
    ''|*[!0-9]*) value="5" ;;
  esac
  printf '%s\n' "${value}"
}

coreelec_postdeploy_guided_poll_limit() {
  local timeout_seconds interval_seconds divisor
  timeout_seconds="$(coreelec_postdeploy_guided_timeout_seconds)"
  interval_seconds="$(coreelec_postdeploy_guided_poll_interval_seconds)"
  divisor="${interval_seconds}"
  if (( divisor < 1 )); then
    divisor=1
  fi
  printf '%s\n' "$((timeout_seconds / divisor + 1))"
}

coreelec_postdeploy_gui_state_matches() {
  local expected_window expected_control
  expected_window="$(coreelec_trim_surrounding_whitespace "$1")"
  expected_control="$(coreelec_trim_surrounding_whitespace "$2")"
  capture_gui_state || return 1
  [[ "${KODI_GUI_WINDOW_LABEL}" == "${expected_window}" && "${KODI_GUI_CONTROL_LABEL}" == "${expected_control}" ]]
}

coreelec_postdeploy_gui_control_matches() {
  local expected_control
  expected_control="$(coreelec_trim_surrounding_whitespace "$1")"
  capture_gui_state || return 1
  [[ "${KODI_GUI_CONTROL_LABEL}" == "${expected_control}" ]]
}

coreelec_postdeploy_guided_select() {
  local response
  # Input.ExecuteAction(select) is the select operation covered by the live
  # capability gate, unlike the separate Input.Select method.
  response="$(kodi_rpc "Input.ExecuteAction" '{"action":"select"}')" || return 1
  coreelec_postdeploy_kodi_call_ok "${response}"
}

coreelec_postdeploy_send_text_if_expected() {
  local expected_window="$1" expected_control="$2" text="$3" params response
  require_gui_state "${expected_window}" "${expected_control}" || return 1
  params="$(KODI_INPUT_TEXT="${text}" python3 - <<'PYEOF'
import json
import os
import sys

sys.stdout.write(json.dumps({
    "text": os.environ["KODI_INPUT_TEXT"],
    "done": True,
}, separators=(",", ":")))
PYEOF
)" || return 1
  response="$(kodi_rpc "Input.SendText" "${params}")" || return 1
  coreelec_postdeploy_kodi_call_ok "${response}"
}

coreelec_postdeploy_guided_observe_token_state() {
  local observe_key="$1" token_present="$2"
  coreelec_postdeploy_observe "${observe_key}" "${token_present}"
}

authorize_pm4k_account() {
  local token_present launch_response attempts attempt interval_seconds sign_in_selected=0
  coreelec_postdeploy_require_pinned_addon_version "script.plexmod" "service.script.plexmod" || {
    printf 'manual-required\n'
    return 0
  }

  token_present="$(coreelec_postdeploy_pm4k_account_token_present 2>/dev/null || true)"
  if [[ ! "${token_present}" =~ ^[01]$ ]]; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "token-state-unreadable"
    printf 'manual-required\n'
    return 0
  fi
  coreelec_postdeploy_guided_observe_token_state "service.script.plexmod.account_token_present" "${token_present}"
  if [[ "${token_present}" == "1" ]]; then
    printf 'already-configured\n'
    return 0
  fi

  launch_response="$(kodi_rpc "Addons.ExecuteAddon" '{"addonid":"script.plexmod"}')" || {
    coreelec_postdeploy_observe "service.script.plexmod.failure" "kodi-rpc"
    printf 'manual-required\n'
    return 0
  }
  if ! coreelec_postdeploy_kodi_call_ok "${launch_response}"; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "kodi-rpc"
    printf 'manual-required\n'
    return 0
  fi
  coreelec_postdeploy_observe "service.script.plexmod.kodi_execute" "ok"
  coreelec_postdeploy_observe "service.script.plexmod.next_action" "complete-link-at-https://plex.tv/link"

  attempts="$(coreelec_postdeploy_guided_poll_limit)"
  interval_seconds="$(coreelec_postdeploy_guided_poll_interval_seconds)"
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if (( sign_in_selected == 0 )) && coreelec_postdeploy_gui_control_matches "Sign In"; then
      if ! coreelec_postdeploy_guided_select; then
        coreelec_postdeploy_observe "service.script.plexmod.failure" "kodi-rpc"
        printf 'manual-required\n'
        return 0
      fi
      coreelec_postdeploy_observe "service.script.plexmod.sign_in" "selected"
      sign_in_selected=1
    fi

    token_present="$(coreelec_postdeploy_pm4k_account_token_present 2>/dev/null || true)"
    if [[ ! "${token_present}" =~ ^[01]$ ]]; then
      coreelec_postdeploy_observe "service.script.plexmod.failure" "token-state-unreadable"
      printf 'manual-required\n'
      return 0
    fi
    coreelec_postdeploy_guided_observe_token_state "service.script.plexmod.account_token_present" "${token_present}"
    if [[ "${token_present}" == "1" ]]; then
      printf 'configured\n'
      return 0
    fi

    if (( attempt < attempts && interval_seconds > 0 )); then
      sleep "${interval_seconds}"
    fi
  done

  coreelec_postdeploy_observe "service.script.plexmod.failure" "timeout"
  printf 'manual-required\n'
}

authorize_youtube() {
  local token_present launch_response attempts attempt interval_seconds intro_dismissed=0
  coreelec_postdeploy_require_pinned_addon_version "plugin.video.youtube" "service.plugin.video.youtube" || {
    printf 'manual-required\n'
    return 0
  }

  token_present="$(coreelec_postdeploy_youtube_token_present 2>/dev/null || true)"
  if [[ ! "${token_present}" =~ ^[01]$ ]]; then
    coreelec_postdeploy_observe "service.plugin.video.youtube.failure" "token-state-unreadable"
    printf 'manual-required\n'
    return 0
  fi
  coreelec_postdeploy_guided_observe_token_state "service.plugin.video.youtube.account_token_present" "${token_present}"
  if [[ "${token_present}" == "1" ]]; then
    printf 'already-configured\n'
    return 0
  fi

  launch_response="$(kodi_rpc "GUI.ActivateWindow" '{"window":"videos","parameters":["plugin://plugin.video.youtube/sign/in/"]}')" || {
    coreelec_postdeploy_observe "service.plugin.video.youtube.failure" "kodi-rpc"
    printf 'manual-required\n'
    return 0
  }
  if ! coreelec_postdeploy_kodi_call_ok "${launch_response}"; then
    coreelec_postdeploy_observe "service.plugin.video.youtube.failure" "kodi-rpc"
    printf 'manual-required\n'
    return 0
  fi
  coreelec_postdeploy_observe "service.plugin.video.youtube.kodi_activate" "ok"
  coreelec_postdeploy_observe "service.plugin.video.youtube.note" "multiple-google-codes-possible-in-7.4.4"

  attempts="$(coreelec_postdeploy_guided_poll_limit)"
  interval_seconds="$(coreelec_postdeploy_guided_poll_interval_seconds)"
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if (( intro_dismissed == 0 )) \
      && coreelec_postdeploy_gui_state_matches "Please sign in and complete all access authorisation prompts" "OK"; then
      if ! coreelec_postdeploy_guided_select; then
        coreelec_postdeploy_observe "service.plugin.video.youtube.failure" "kodi-rpc"
        printf 'manual-required\n'
        return 0
      fi
      coreelec_postdeploy_observe "service.plugin.video.youtube.intro_dialog" "dismissed"
      intro_dismissed=1
    fi

    token_present="$(coreelec_postdeploy_youtube_token_present 2>/dev/null || true)"
    if [[ ! "${token_present}" =~ ^[01]$ ]]; then
      coreelec_postdeploy_observe "service.plugin.video.youtube.failure" "token-state-unreadable"
      printf 'manual-required\n'
      return 0
    fi
    coreelec_postdeploy_guided_observe_token_state "service.plugin.video.youtube.account_token_present" "${token_present}"
    if [[ "${token_present}" == "1" ]]; then
      printf 'configured\n'
      return 0
    fi

    if (( attempt < attempts && interval_seconds > 0 )); then
      sleep "${interval_seconds}"
    fi
  done

  coreelec_postdeploy_observe "service.plugin.video.youtube.failure" "timeout"
  printf 'manual-required\n'
}

coreelec_postdeploy_emby_state() {
  local remote_command
  remote_command="$(cat <<'EOF'
set -eu
IFS= read -r server_url || exit 1
EMBY_SERVER_URL="${server_url}" python3 - <<'PYEOF'
import glob
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

paths = sorted(glob.glob(os.path.expanduser(
    "~/.kodi/userdata/addon_data/plugin.service.emby-next-gen/servers_*.json")))
if not paths:
    sys.stdout.write("absent\n")
    raise SystemExit(0)
if len(paths) != 1:
    sys.stdout.write("ambiguous\n")
    raise SystemExit(0)

try:
    with open(paths[0], "r", encoding="utf-8") as handle:
        server = json.load(handle)
except Exception:
    sys.stdout.write("invalid\n")
    raise SystemExit(0)

server_id = server.get("ServerId")
token = server.get("AccessToken")
user_id = server.get("UserId")
if not all(isinstance(value, str) and value.strip()
           for value in (server_id, token, user_id)):
    sys.stdout.write("incomplete\n")
    raise SystemExit(0)

expected_name = "servers_%s.json" % server_id
if os.path.basename(paths[0]) != expected_name:
    sys.stdout.write("identity-mismatch\n")
    raise SystemExit(0)

request = urllib.request.Request(
    os.environ["EMBY_SERVER_URL"].rstrip("/") + "/System/Info",
    headers={"X-Emby-Token": token, "Accept": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        system_info = json.loads(response.read().decode("utf-8"))
except (ssl.CertificateError, ssl.SSLCertVerificationError):
    sys.stdout.write("certificate-error\n")
    raise SystemExit(0)
except urllib.error.URLError as exc:
    if isinstance(exc.reason, (ssl.CertificateError,
                               ssl.SSLCertVerificationError)):
        sys.stdout.write("certificate-error\n")
    else:
        sys.stdout.write("server-unavailable\n")
    raise SystemExit(0)
except Exception:
    sys.stdout.write("server-unavailable\n")
    raise SystemExit(0)

if system_info.get("Id") != server_id:
    sys.stdout.write("identity-mismatch\n")
    raise SystemExit(0)

database = os.path.expanduser(
    "~/.kodi/userdata/Database/emby_%s.db" % server_id)
if not os.path.isfile(database):
    sys.stdout.write("handshake-pending\n")
    raise SystemExit(0)
sys.stdout.write("configured\n")
PYEOF
EOF
)"
  printf '%s\n' "${EMBY_SERVER_URL}" \
    | coreelec_postdeploy_ssh_batch "${remote_command}"
}

coreelec_postdeploy_emby_fail() {
  coreelec_postdeploy_observe "service.plugin.service.emby-next-gen.failure" "$1"
  printf 'manual-required\n'
}

assist_emby_login() {
  local pinned_version state launch_response attempts attempt interval_seconds
  local pre_notification_window pre_notification_control
  local gui_input_sent=0 add_server_selected=0 manual_server_selected=0
  local url_sent=0 username_sent=0 password_sent=0 signin_selected=0

  pinned_version="$(coreelec_postdeploy_pinned_addon_version "plugin.service.emby-next-gen" 2>/dev/null || true)"
  if [[ "${pinned_version}" != "12.4.23" ]]; then
    coreelec_postdeploy_emby_fail "version-mismatch"
    return 0
  fi
  coreelec_postdeploy_require_pinned_addon_version \
    "plugin.service.emby-next-gen" "service.plugin.service.emby-next-gen" || {
      printf 'manual-required\n'
      return 0
    }
  if [[ "${LOCALE_LANGUAGE:-}" != "resource.language.en_us" ]]; then
    coreelec_postdeploy_emby_fail "locale-mismatch"
    return 0
  fi
  if [[ -z "${EMBY_SERVER_URL:-}" || -z "${EMBY_USERNAME:-}" ]]; then
    coreelec_postdeploy_emby_fail "not-configured"
    return 0
  fi
  if ! coreelec_prepare_emby_password; then
    coreelec_postdeploy_emby_fail "password-required"
    return 0
  fi

  state="$(coreelec_postdeploy_emby_state 2>/dev/null || true)"
  case "${state}" in
    configured)
      coreelec_postdeploy_observe "service.plugin.service.emby-next-gen.credentials_verified" "1"
      printf 'already-configured\n'
      return 0
      ;;
    absent) ;;
    ambiguous)
      coreelec_postdeploy_emby_fail "server-selection-ambiguity"
      return 0
      ;;
    certificate-error)
      coreelec_postdeploy_emby_fail "certificate-error"
      return 0
      ;;
    *)
      coreelec_postdeploy_emby_fail "credential-state-invalid"
      return 0
      ;;
  esac

  if ! capture_gui_state; then
    coreelec_postdeploy_emby_fail "unexpected-dialog"
    return 0
  fi
  pre_notification_window="${KODI_GUI_WINDOW_LABEL}"
  pre_notification_control="${KODI_GUI_CONTROL_LABEL}"

  launch_response="$(kodi_rpc "JSONRPC.NotifyAll" '{"sender":"Other","message":"manageserver","data":{}}')" || {
    coreelec_postdeploy_emby_fail "kodi-rpc"
    return 0
  }
  if ! coreelec_postdeploy_kodi_call_ok "${launch_response}"; then
    coreelec_postdeploy_emby_fail "kodi-rpc"
    return 0
  fi
  coreelec_postdeploy_observe "service.plugin.service.emby-next-gen.manage_server" "opened"

  attempts="$(coreelec_postdeploy_guided_poll_limit)"
  interval_seconds="$(coreelec_postdeploy_guided_poll_interval_seconds)"
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if (( signin_selected == 1 )); then
      state="$(coreelec_postdeploy_emby_state 2>/dev/null || true)"
      case "${state}" in
        configured)
          coreelec_postdeploy_observe "service.plugin.service.emby-next-gen.credentials_verified" "1"
          coreelec_postdeploy_observe "service.plugin.service.emby-next-gen.handshake_database" "present"
          printf 'configured\n'
          return 0
          ;;
        ambiguous)
          coreelec_postdeploy_emby_fail "server-selection-ambiguity"
          return 0
          ;;
        certificate-error)
          coreelec_postdeploy_emby_fail "certificate-error"
          return 0
          ;;
        invalid|identity-mismatch)
          coreelec_postdeploy_emby_fail "credential-state-invalid"
          return 0
          ;;
      esac
    fi

    if ! capture_gui_state; then
      coreelec_postdeploy_emby_fail "unexpected-dialog"
      return 0
    fi

    if (( gui_input_sent == 0 )) &&
      [[ "${KODI_GUI_WINDOW_LABEL}" == "${pre_notification_window}" &&
         "${KODI_GUI_CONTROL_LABEL}" == "${pre_notification_control}" ]]; then
      if (( attempt < attempts && interval_seconds > 0 )); then
        sleep "${interval_seconds}"
      fi
      continue
    fi

    case "${KODI_GUI_WINDOW_LABEL}|${KODI_GUI_CONTROL_LABEL}" in
      "Select dialog|Add server")
        if (( add_server_selected != 0 || manual_server_selected != 0 ||
              url_sent != 0 || username_sent != 0 || password_sent != 0 )); then
          coreelec_postdeploy_emby_fail "unexpected-dialog"
          return 0
        fi
        coreelec_postdeploy_guided_select || {
          coreelec_postdeploy_emby_fail "kodi-rpc"
          return 0
        }
        gui_input_sent=1
        add_server_selected=1
        ;;
      "Select main server|Manually add server")
        if (( manual_server_selected != 0 || url_sent != 0 || username_sent != 0 || password_sent != 0 )); then
          coreelec_postdeploy_emby_fail "unexpected-dialog"
          return 0
        fi
        coreelec_postdeploy_guided_select || {
          coreelec_postdeploy_emby_fail "kodi-rpc"
          return 0
        }
        gui_input_sent=1
        manual_server_selected=1
        ;;
      "Manage servers|Host")
        if (( manual_server_selected != 1 || url_sent != 0 )); then
          coreelec_postdeploy_emby_fail "unexpected-dialog"
          return 0
        fi
        coreelec_postdeploy_send_text_if_expected \
          "Manage servers" "Host" "${EMBY_SERVER_URL}" || {
            coreelec_postdeploy_emby_fail "unexpected-dialog"
            return 0
          }
        gui_input_sent=1
        url_sent=1
        ;;
      "Please sign in|Username")
        if (( url_sent != 1 || username_sent != 0 )); then
          coreelec_postdeploy_emby_fail "unexpected-dialog"
          return 0
        fi
        coreelec_postdeploy_send_text_if_expected \
          "Please sign in" "Username" "${EMBY_USERNAME}" || {
            coreelec_postdeploy_emby_fail "unexpected-dialog"
            return 0
          }
        gui_input_sent=1
        username_sent=1
        ;;
      "Please sign in|Password")
        if (( username_sent != 1 || password_sent != 0 )); then
          coreelec_postdeploy_emby_fail "password-retry"
          return 0
        fi
        coreelec_postdeploy_send_text_if_expected \
          "Please sign in" "Password" "${EMBY_PASSWORD}" || {
            coreelec_postdeploy_emby_fail "unexpected-dialog"
            return 0
          }
        gui_input_sent=1
        password_sent=1
        ;;
      "Please sign in|Sign in")
        if (( password_sent != 1 || signin_selected != 0 )); then
          coreelec_postdeploy_emby_fail "password-retry"
          return 0
        fi
        coreelec_postdeploy_guided_select || {
          coreelec_postdeploy_emby_fail "kodi-rpc"
          return 0
        }
        gui_input_sent=1
        signin_selected=1
        ;;
      "Please sign in|Manual login")
        coreelec_postdeploy_emby_fail "multiple-public-users"
        return 0
        ;;
      "Select main server|"*)
        coreelec_postdeploy_emby_fail "server-selection-ambiguity"
        return 0
        ;;
      "Please sign in|"*)
        coreelec_postdeploy_emby_fail "multiple-public-users"
        return 0
        ;;
      *[Cc]ertificate*)
        coreelec_postdeploy_emby_fail "certificate-error"
        return 0
        ;;
      *[Rr]esync*|*[Dd]atabase*)
        coreelec_postdeploy_emby_fail "database-resync"
        return 0
        ;;
      *)
        coreelec_postdeploy_emby_fail "unexpected-dialog"
        return 0
        ;;
    esac

    if (( attempt < attempts && interval_seconds > 0 )); then
      sleep "${interval_seconds}"
    fi
  done

  coreelec_postdeploy_emby_fail "timeout"
}

coreelec_postdeploy_weather_ready() {
  [[ -n "${HOME_ASSISTANT_URL:-}" && -n "${HOME_ASSISTANT_WEATHER_ENTITY:-}" \
     && -n "${HOME_ASSISTANT_TOKEN:-}" ]]
}

coreelec_postdeploy_nextpvr_ready() {
  [[ -n "${NEXTPVR_HOST:-}" && -n "${NEXTPVR_PORT:-}" \
     && -n "${NEXTPVR_PROTOCOL:-}" && -n "${NEXTPVR_PIN:-}" ]]
}

coreelec_postdeploy_pm4k_local_ready() {
  [[ -n "${PLEX_SERVER_HOST:-}" && -n "${PLEX_SERVER_PORT:-}" \
     && -n "${PLEX_SERVER_NAME:-}" && -n "${PLEX_PROFILE_IDS:-}" \
     && -n "${PLEX_TOKEN:-}" ]]
}

coreelec_postdeploy_observe() {
  printf '%s=%s\n' "$1" "$2" >&2
}

coreelec_postdeploy_http_request() {
  local method="$1" url="$2" headers_json="$3" request_json remote_command
  [[ -n "${TARGET:-}" ]] || die "TARGET is required before calling coreelec_postdeploy_http_request"
  [[ -n "${SSH_PORT:-}" ]] || die "SSH_PORT is required before calling coreelec_postdeploy_http_request"

request_json="$(HTTP_REQUEST_METHOD="${method}" \
  HTTP_REQUEST_URL="${url}" \
  HTTP_REQUEST_HEADERS_JSON="${headers_json}" \
  python3 - <<'PYEOF'
import json
import os
import sys

payload = {
  "method": os.environ["HTTP_REQUEST_METHOD"],
  "url": os.environ["HTTP_REQUEST_URL"],
  "headers": json.loads(os.environ["HTTP_REQUEST_HEADERS_JSON"]),
}
sys.stdout.write(json.dumps(payload, separators=(",", ":")))
PYEOF
)" || die "Failed to build HTTP request for ${url}"

  remote_command="$(cat <<'EOF'
set -eu
cache_dir="${HOME}/.cache"
mkdir -p "${cache_dir}"
chmod 700 "${cache_dir}"
request_file="${cache_dir}/coreelec-addon-http-request.$$"
cleanup() {
  rm -f -- "${request_file}"
}
trap cleanup EXIT HUP INT TERM
umask 077
cat > "${request_file}"
python3 - "${request_file}" <<'PYEOF'
import json
import sys
import urllib.error
import urllib.request

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    spec = json.load(handle)

request = urllib.request.Request(spec["url"], method=spec["method"])
for name, value in spec.get("headers", {}).items():
    request.add_header(name, value)

result = {
    "transport": "error",
    "http_status": 0,
    "body": "",
    "content_type": "",
    "error": "",
}

try:
    with urllib.request.urlopen(request, timeout=10) as response:
        result["transport"] = "ok"
        result["http_status"] = int(response.getcode() or 0)
        result["body"] = response.read().decode("utf-8", "replace")
        result["content_type"] = response.headers.get("Content-Type", "")
except urllib.error.HTTPError as exc:
    result["transport"] = "ok"
    result["http_status"] = int(exc.code or 0)
    result["body"] = exc.read().decode("utf-8", "replace")
    result["content_type"] = exc.headers.get("Content-Type", "")
except Exception as exc:
    result["error"] = str(exc)

sys.stdout.write(json.dumps(result, separators=(",", ":")))
PYEOF
EOF
)"

  printf '%s\n' "${request_json}" | coreelec_postdeploy_ssh_batch "${remote_command}"
}

coreelec_postdeploy_http_field() {
  local response_json="$1" field_name="$2"
  RESPONSE_JSON="${response_json}" FIELD_NAME="${field_name}" python3 - <<'PYEOF'
import json
import os
import sys

payload = json.loads(os.environ["RESPONSE_JSON"])
value = payload.get(os.environ["FIELD_NAME"], "")
if value is None:
    value = ""
if isinstance(value, (dict, list)):
    sys.stdout.write(json.dumps(value, separators=(",", ":")))
else:
    sys.stdout.write(str(value))
PYEOF
}

coreelec_postdeploy_join_url() {
  local base="$1" suffix="$2"
  base="${base%/}"
  printf '%s%s\n' "${base}" "${suffix}"
}

coreelec_postdeploy_md5_hex() {
  MD5_INPUT="$1" python3 - <<'PYEOF'
import hashlib
import os
import sys

sys.stdout.write(hashlib.md5(os.environ["MD5_INPUT"].encode("utf-8")).hexdigest())
PYEOF
}

coreelec_postdeploy_kodi_call_ok() {
  local response="$1"
  KODI_RESPONSE="${response}" python3 - <<'PYEOF'
import json
import os
import sys

try:
    payload = json.loads(os.environ["KODI_RESPONSE"])
except Exception:
    raise SystemExit(1)
if payload.get("error") is not None:
    raise SystemExit(1)
raise SystemExit(0)
PYEOF
}

coreelec_postdeploy_validate_json_object() {
  local payload="$1"
  JSON_OBJECT_PAYLOAD="${payload}" python3 - <<'PYEOF'
import json
import os
import sys

try:
    value = json.loads(os.environ["JSON_OBJECT_PAYLOAD"])
except Exception:
    raise SystemExit(1)
if not isinstance(value, dict):
    raise SystemExit(1)
raise SystemExit(0)
PYEOF
}

coreelec_postdeploy_weather_labels_populated() {
  local payload="$1"
  JSON_PAYLOAD="${payload}" python3 - <<'PYEOF'
import json
import os

payload = json.loads(os.environ["JSON_PAYLOAD"])
if payload.get("error") is not None:
    raise SystemExit(1)
result = payload.get("result")
if not isinstance(result, dict):
    raise SystemExit(1)
for label in ("Weather.Location", "Weather.Temperature", "Weather.Conditions"):
    value = result.get(label)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(1)
PYEOF
}

coreelec_postdeploy_json_string_field() {
  local payload="$1" dotted_path="$2"
  JSON_PAYLOAD="${payload}" JSON_PATH="${dotted_path}" python3 - <<'PYEOF'
import json
import os
import sys

value = json.loads(os.environ["JSON_PAYLOAD"])
for part in os.environ["JSON_PATH"].split("."):
    if not isinstance(value, dict) or part not in value:
        raise SystemExit(1)
    value = value[part]
if not isinstance(value, str) or value == "":
    raise SystemExit(1)
sys.stdout.write(value)
PYEOF
}

coreelec_postdeploy_nextpvr_initiate_fields() {
  local payload="$1"
  XML_PAYLOAD="${payload}" python3 - <<'PYEOF'
import os
import sys
import xml.etree.ElementTree as ET

try:
    root = ET.fromstring(os.environ["XML_PAYLOAD"])
except Exception:
    raise SystemExit(1)
if root.attrib.get("stat") != "ok":
    raise SystemExit(1)
sid = root.findtext("sid") or ""
salt = root.findtext("salt") or ""
if not sid or not salt:
    raise SystemExit(1)
sys.stdout.write("%s\n%s\n" % (sid, salt))
PYEOF
}

coreelec_postdeploy_nextpvr_login_ok() {
  local payload="$1"
  XML_PAYLOAD="${payload}" python3 - <<'PYEOF'
import os
import sys
import xml.etree.ElementTree as ET

try:
    root = ET.fromstring(os.environ["XML_PAYLOAD"])
except Exception:
    raise SystemExit(1)
if root.attrib.get("stat") != "ok":
    raise SystemExit(1)
raise SystemExit(0)
PYEOF
}

check_home_assistant_weather() {
  local config_response entity_response config_transport config_status config_body
  local entity_transport entity_status entity_body entity_id kodi_response provider_response provider
  if ! coreelec_postdeploy_weather_ready; then
    coreelec_postdeploy_observe "service.weather.ha.failure" "not-configured"
    printf 'skipped\n'
    return 0
  fi

  config_response="$(
    coreelec_postdeploy_http_request \
      "GET" \
      "$(coreelec_postdeploy_join_url "${HOME_ASSISTANT_URL}" "/api/config")" \
      "$(HOME_ASSISTANT_TOKEN_VALUE="${HOME_ASSISTANT_TOKEN:-}" python3 - <<'PYEOF'
import json
import os
import sys

token = os.environ["HOME_ASSISTANT_TOKEN_VALUE"]
sys.stdout.write(json.dumps({
    "Authorization": "Bearer " + token,
    "Accept": "application/json",
}, separators=(",", ":")))
PYEOF
)"
  )"
  config_transport="$(coreelec_postdeploy_http_field "${config_response}" "transport")"
  config_status="$(coreelec_postdeploy_http_field "${config_response}" "http_status")"
  config_body="$(coreelec_postdeploy_http_field "${config_response}" "body")"
  coreelec_postdeploy_observe "service.weather.ha.config_http_status" "${config_status}"
  if [[ "${config_transport}" != "ok" ]]; then
    coreelec_postdeploy_observe "service.weather.ha.failure" "transport"
    printf 'failed\n'
    return 0
  fi
  case "${config_status}" in
    401|403)
      coreelec_postdeploy_observe "service.weather.ha.failure" "unauthorized"
      printf 'authorization-required\n'
      return 0
      ;;
    200) ;;
    *)
      coreelec_postdeploy_observe "service.weather.ha.failure" "http-status"
      printf 'failed\n'
      return 0
      ;;
  esac
  if ! coreelec_postdeploy_validate_json_object "${config_body}"; then
    coreelec_postdeploy_observe "service.weather.ha.failure" "malformed-payload"
    printf 'failed\n'
    return 0
  fi

  entity_response="$(
    coreelec_postdeploy_http_request \
      "GET" \
      "$(coreelec_postdeploy_join_url "${HOME_ASSISTANT_URL}" "/api/states/${HOME_ASSISTANT_WEATHER_ENTITY}")" \
      "$(HOME_ASSISTANT_TOKEN_VALUE="${HOME_ASSISTANT_TOKEN:-}" python3 - <<'PYEOF'
import json
import os
import sys

token = os.environ["HOME_ASSISTANT_TOKEN_VALUE"]
sys.stdout.write(json.dumps({
    "Authorization": "Bearer " + token,
    "Accept": "application/json",
}, separators=(",", ":")))
PYEOF
)"
  )"
  entity_transport="$(coreelec_postdeploy_http_field "${entity_response}" "transport")"
  entity_status="$(coreelec_postdeploy_http_field "${entity_response}" "http_status")"
  entity_body="$(coreelec_postdeploy_http_field "${entity_response}" "body")"
  coreelec_postdeploy_observe "service.weather.ha.entity_http_status" "${entity_status}"
  if [[ "${entity_transport}" != "ok" ]]; then
    coreelec_postdeploy_observe "service.weather.ha.failure" "transport"
    printf 'failed\n'
    return 0
  fi
  case "${entity_status}" in
    401|403)
      coreelec_postdeploy_observe "service.weather.ha.failure" "unauthorized"
      printf 'authorization-required\n'
      return 0
      ;;
    200) ;;
    *)
      coreelec_postdeploy_observe "service.weather.ha.failure" "http-status"
      printf 'failed\n'
      return 0
      ;;
  esac
  if ! coreelec_postdeploy_validate_json_object "${entity_body}"; then
    coreelec_postdeploy_observe "service.weather.ha.failure" "malformed-payload"
    printf 'failed\n'
    return 0
  fi
  if ! entity_id="$(coreelec_postdeploy_json_string_field "${entity_body}" "entity_id" 2>/dev/null)"; then
    coreelec_postdeploy_observe "service.weather.ha.failure" "malformed-payload"
    printf 'failed\n'
    return 0
  fi
  if [[ "${entity_id}" != "${HOME_ASSISTANT_WEATHER_ENTITY}" ]]; then
    coreelec_postdeploy_observe "service.weather.ha.failure" "identity-mismatch"
    printf 'failed\n'
    return 0
  fi

  kodi_response="$(kodi_rpc "XBMC.GetInfoLabels" '{"labels":["Weather.Location","Weather.Temperature","Weather.Conditions"]}')" || {
    coreelec_postdeploy_observe "service.weather.ha.failure" "transport"
    printf 'failed\n'
    return 0
  }
  if ! coreelec_postdeploy_weather_labels_populated "${kodi_response}"; then
    coreelec_postdeploy_observe "service.weather.ha.failure" "kodi-weather-labels"
    printf 'failed\n'
    return 0
  fi
  coreelec_postdeploy_observe "service.weather.ha.kodi_weather_labels" "populated"

  provider_response="$(kodi_rpc "Settings.GetSettingValue" '{"setting":"weather.addon"}')" || {
    coreelec_postdeploy_observe "service.weather.ha.failure" "transport"
    printf 'failed\n'
    return 0
  }
  if ! provider="$(coreelec_postdeploy_json_string_field "${provider_response}" "result.value" 2>/dev/null)" \
    || [[ "${provider}" != "weather.ha" ]]; then
    coreelec_postdeploy_observe "service.weather.ha.failure" "kodi-weather-provider"
    printf 'failed\n'
    return 0
  fi
  coreelec_postdeploy_observe "service.weather.ha.kodi_provider" "${provider}"
  printf 'configured\n'
}

check_nextpvr() {
  local initiate_response initiate_transport initiate_status initiate_body parsed sid salt
  local pin_md5 login_hash_input login_md5 login_response login_transport login_status login_body
  local kodi_response
  if ! coreelec_postdeploy_nextpvr_ready; then
    coreelec_postdeploy_observe "service.pvr.nextpvr.failure" "not-configured"
    printf 'skipped\n'
    return 0
  fi

  initiate_response="$(
    coreelec_postdeploy_http_request \
      "GET" \
      "${NEXTPVR_PROTOCOL}://${NEXTPVR_HOST}:${NEXTPVR_PORT}/service?method=session.initiate&ver=1.0&device=xbmc" \
      '{}'
  )"
  initiate_transport="$(coreelec_postdeploy_http_field "${initiate_response}" "transport")"
  initiate_status="$(coreelec_postdeploy_http_field "${initiate_response}" "http_status")"
  initiate_body="$(coreelec_postdeploy_http_field "${initiate_response}" "body")"
  coreelec_postdeploy_observe "service.pvr.nextpvr.session_initiate_http_status" "${initiate_status}"
  if [[ "${initiate_transport}" != "ok" ]]; then
    coreelec_postdeploy_observe "service.pvr.nextpvr.failure" "transport"
    printf 'failed\n'
    return 0
  fi
  case "${initiate_status}" in
    401|403)
      coreelec_postdeploy_observe "service.pvr.nextpvr.failure" "unauthorized"
      printf 'authorization-required\n'
      return 0
      ;;
    200) ;;
    *)
      coreelec_postdeploy_observe "service.pvr.nextpvr.failure" "http-status"
      printf 'failed\n'
      return 0
      ;;
  esac
  if ! parsed="$(coreelec_postdeploy_nextpvr_initiate_fields "${initiate_body}" 2>/dev/null)"; then
    coreelec_postdeploy_observe "service.pvr.nextpvr.failure" "malformed-payload"
    printf 'failed\n'
    return 0
  fi
  sid="$(printf '%s\n' "${parsed}" | sed -n '1p')"
  salt="$(printf '%s\n' "${parsed}" | sed -n '2p')"

  pin_md5="$(coreelec_postdeploy_md5_hex "${NEXTPVR_PIN}" | tr '[:upper:]' '[:lower:]')"
  login_hash_input=":${pin_md5}:${salt}"
  login_md5="$(coreelec_postdeploy_md5_hex "${login_hash_input}" | tr '[:upper:]' '[:lower:]')"

  login_response="$(
    coreelec_postdeploy_http_request \
      "GET" \
      "${NEXTPVR_PROTOCOL}://${NEXTPVR_HOST}:${NEXTPVR_PORT}/service?method=session.login&sid=${sid}&md5=${login_md5}" \
      '{}'
  )"
  login_transport="$(coreelec_postdeploy_http_field "${login_response}" "transport")"
  login_status="$(coreelec_postdeploy_http_field "${login_response}" "http_status")"
  login_body="$(coreelec_postdeploy_http_field "${login_response}" "body")"
  coreelec_postdeploy_observe "service.pvr.nextpvr.session_login_http_status" "${login_status}"
  if [[ "${login_transport}" != "ok" ]]; then
    coreelec_postdeploy_observe "service.pvr.nextpvr.failure" "transport"
    printf 'failed\n'
    return 0
  fi
  case "${login_status}" in
    401|403)
      coreelec_postdeploy_observe "service.pvr.nextpvr.failure" "unauthorized"
      printf 'authorization-required\n'
      return 0
      ;;
    200) ;;
    *)
      coreelec_postdeploy_observe "service.pvr.nextpvr.failure" "http-status"
      printf 'failed\n'
      return 0
      ;;
  esac
  if ! coreelec_postdeploy_nextpvr_login_ok "${login_body}" 2>/dev/null; then
    coreelec_postdeploy_observe "service.pvr.nextpvr.session_login" "failed"
    coreelec_postdeploy_observe "service.pvr.nextpvr.failure" "authorization-required"
    printf 'authorization-required\n'
    return 0
  fi
  coreelec_postdeploy_observe "service.pvr.nextpvr.session_login" "ok"

  # Advisory only: the authenticated backend session determines the workflow
  # status even when this Kodi-side observation is unavailable.
  kodi_response="$(kodi_rpc "PVR.GetChannelGroups" '{"channeltype":"tv"}')" || {
    coreelec_postdeploy_observe "service.pvr.nextpvr.kodi_channel_groups" "transport-failed"
    printf 'configured\n'
    return 0
  }
  if coreelec_postdeploy_kodi_call_ok "${kodi_response}"; then
    coreelec_postdeploy_observe "service.pvr.nextpvr.kodi_channel_groups" "ok"
  else
    coreelec_postdeploy_observe "service.pvr.nextpvr.kodi_channel_groups" "failed"
  fi
  printf 'configured\n'
}

check_pm4k_local() {
  local identity_response identity_transport identity_status identity_body machine_id
  local root_response root_transport root_status root_body root_name kodi_response
  if ! coreelec_postdeploy_pm4k_local_ready; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "not-configured"
    printf 'skipped\n'
    return 0
  fi

  identity_response="$(
    coreelec_postdeploy_http_request \
      "GET" \
      "http://${PLEX_SERVER_HOST}:${PLEX_SERVER_PORT}/identity" \
      '{"Accept":"application/json"}'
  )"
  identity_transport="$(coreelec_postdeploy_http_field "${identity_response}" "transport")"
  identity_status="$(coreelec_postdeploy_http_field "${identity_response}" "http_status")"
  identity_body="$(coreelec_postdeploy_http_field "${identity_response}" "body")"
  coreelec_postdeploy_observe "service.script.plexmod.identity_http_status" "${identity_status}"
  if [[ "${identity_transport}" != "ok" ]]; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "transport"
    printf 'failed\n'
    return 0
  fi
  case "${identity_status}" in
    401|403)
      coreelec_postdeploy_observe "service.script.plexmod.failure" "unauthorized"
      printf 'authorization-required\n'
      return 0
      ;;
    200) ;;
    *)
      coreelec_postdeploy_observe "service.script.plexmod.failure" "http-status"
      printf 'failed\n'
      return 0
      ;;
  esac
  if ! machine_id="$(coreelec_postdeploy_json_string_field "${identity_body}" "MediaContainer.machineIdentifier" 2>/dev/null)"; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "malformed-payload"
    printf 'failed\n'
    return 0
  fi

  root_response="$(
    coreelec_postdeploy_http_request \
      "GET" \
      "http://${PLEX_SERVER_HOST}:${PLEX_SERVER_PORT}/" \
      "$(PLEX_TOKEN_VALUE="${PLEX_TOKEN:-}" python3 - <<'PYEOF'
import json
import os
import sys

token = os.environ["PLEX_TOKEN_VALUE"]
sys.stdout.write(json.dumps({
    "Accept": "application/json",
    "X-Plex-Token": token,
}, separators=(",", ":")))
PYEOF
)"
  )"
  root_transport="$(coreelec_postdeploy_http_field "${root_response}" "transport")"
  root_status="$(coreelec_postdeploy_http_field "${root_response}" "http_status")"
  root_body="$(coreelec_postdeploy_http_field "${root_response}" "body")"
  coreelec_postdeploy_observe "service.script.plexmod.root_http_status" "${root_status}"
  if [[ "${root_transport}" != "ok" ]]; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "transport"
    printf 'failed\n'
    return 0
  fi
  case "${root_status}" in
    401|403)
      coreelec_postdeploy_observe "service.script.plexmod.failure" "unauthorized"
      printf 'authorization-required\n'
      return 0
      ;;
    200) ;;
    *)
      coreelec_postdeploy_observe "service.script.plexmod.failure" "http-status"
      printf 'failed\n'
      return 0
      ;;
  esac
  if ! root_name="$(coreelec_postdeploy_json_string_field "${root_body}" "MediaContainer.friendlyName" 2>/dev/null)"; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "malformed-payload"
    printf 'failed\n'
    return 0
  fi
  if [[ "${root_name}" != "${PLEX_SERVER_NAME}" ]]; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "identity-mismatch"
    printf 'failed\n'
    return 0
  fi
  coreelec_postdeploy_observe "service.script.plexmod.identity_machine_id" "${machine_id}"

  kodi_response="$(kodi_rpc "Addons.ExecuteAddon" '{"addonid":"script.plexmod"}')" || {
    coreelec_postdeploy_observe "service.script.plexmod.failure" "transport"
    printf 'failed\n'
    return 0
  }
  if ! coreelec_postdeploy_kodi_call_ok "${kodi_response}"; then
    coreelec_postdeploy_observe "service.script.plexmod.failure" "kodi-rpc"
    printf 'failed\n'
    return 0
  fi
  coreelec_postdeploy_observe "service.script.plexmod.kodi_execute" "ok"
  printf 'configured\n'
}

run_addon_workflow() {
  case "$1" in
    weather.ha)
      if coreelec_postdeploy_weather_ready; then
        check_home_assistant_weather
      else
        printf 'skipped\n'
      fi
      ;;
    pvr.nextpvr)
      if coreelec_postdeploy_nextpvr_ready; then
        check_nextpvr
      else
        printf 'skipped\n'
      fi
      ;;
    script.plexmod)
      if coreelec_postdeploy_pm4k_local_ready; then
        check_pm4k_local
      elif [[ "${INTERACTIVE:-0}" == "1" ]]; then
        authorize_pm4k_account
      else
        printf 'authorization-required\n'
      fi
      ;;
    plugin.video.youtube)
      if [[ "${INTERACTIVE:-0}" == "1" ]]; then
        authorize_youtube
      else
        printf 'authorization-required\n'
      fi
      ;;
    plugin.service.emby-next-gen)
      if [[ "${INTERACTIVE:-0}" == "1" ]]; then
        assist_emby_login
      else
        printf 'authorization-required\n'
      fi
      ;;
    *)
      die "No post-deployment workflow is defined for add-on: $1"
      ;;
  esac
}
