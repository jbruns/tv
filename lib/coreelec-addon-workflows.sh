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

kodi_rpc() {
  local method="$1" params_json="$2"
  local request_id request_json remote_command
  [[ -n "${TARGET:-}" ]] || die "TARGET is required before calling kodi_rpc"
  [[ -n "${SSH_PORT:-}" ]] || die "SSH_PORT is required before calling kodi_rpc"
  [[ -n "${KODI_PORT:-}" ]] || die "KODI_PORT is required before calling kodi_rpc"
  [[ -n "${KODI_USER:-}" ]] || die "KODI_USER is required before calling kodi_rpc"
  [[ -n "${KODI_WEB_PASSWORD:-}" ]] || die "KODI_WEB_PASSWORD is required before calling kodi_rpc"

  request_id="$(kodi_rpc_request_id "${method}")"
  request_json="$(python3 - "${method}" "${request_id}" "${params_json}" <<'PYEOF'
import json
import sys

method, request_id, params = sys.argv[1:4]
payload = {
    "jsonrpc": "2.0",
    "id": request_id,
    "method": method,
    "params": json.loads(params),
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
data = @"\${body}"
silent
show-error
fail
max-time = 10
CONFIG
chmod 600 "\${cfg}" "\${body}"
curl --config "\${cfg}"
EOF
)"

  printf '%s\n%s\n%s\n' "${KODI_USER}" "${KODI_WEB_PASSWORD}" "${request_json}" \
    | ssh -p "${SSH_PORT}" "${TARGET}" sh -c "${remote_command}"
}

kodi_capabilities() {
  local response missing
  response="$(kodi_rpc "JSONRPC.Introspect" '{"getdescriptions":false,"getmetadata":false}')"
  missing="$(printf '%s' "${response}" | python3 -c '
import json
import sys

required = [
    "JSONRPC.Introspect",
    "Addons.ExecuteAddon",
    "GUI.ActivateWindow",
    "GUI.GetProperties",
    "Input.ExecuteAction",
    "Input.SendText",
]
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

require_gui_state() {
  local expected_window expected_control response parsed observed_window observed_control
  expected_window="$(coreelec_trim_surrounding_whitespace "$1")"
  expected_control="$(coreelec_trim_surrounding_whitespace "$2")"
  response="$(kodi_gui_state)" || return 1
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

  if [[ "${observed_window}" != "${expected_window}" || "${observed_control}" != "${expected_control}" ]]; then
    printf 'manual-required: expected window=%s control=%s observed window=%s control=%s\n' \
      "${expected_window}" "${expected_control}" "${observed_window}" "${observed_control}" >&2
    return 1
  fi
  return 0
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

run_addon_workflow() {
  case "$1" in
    weather.ha)
      if coreelec_postdeploy_weather_ready; then
        printf 'already-configured\n'
      else
        printf 'skipped\n'
      fi
      ;;
    pvr.nextpvr)
      if coreelec_postdeploy_nextpvr_ready; then
        printf 'already-configured\n'
      else
        printf 'skipped\n'
      fi
      ;;
    script.plexmod)
      if coreelec_postdeploy_pm4k_local_ready; then
        printf 'already-configured\n'
      elif [[ "${INTERACTIVE:-0}" == "1" ]]; then
        printf 'manual-required\n'
      else
        printf 'authorization-required\n'
      fi
      ;;
    plugin.video.youtube|plugin.service.emby-next-gen)
      if [[ "${INTERACTIVE:-0}" == "1" ]]; then
        printf 'manual-required\n'
      else
        printf 'authorization-required\n'
      fi
      ;;
    *)
      die "No post-deployment workflow is defined for add-on: $1"
      ;;
  esac
}
