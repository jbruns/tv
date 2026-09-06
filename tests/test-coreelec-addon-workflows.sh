#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"

WORKFLOW_LIB="${SCRIPT_DIR}/../lib/coreelec-addon-workflows.sh"
CLI_SCRIPT="${SCRIPT_DIR}/../configure-coreelec-addons.sh"

# shellcheck source=lib/coreelec-addon-workflows.sh
source "${WORKFLOW_LIB}"

addon_record() {
  case "$1" in
    weather.ha) printf '%s\n' 'weather.ha|0.0.6.6|https://example.test/weather.ha.zip|deadbeef' ;;
    pvr.nextpvr) printf '%s\n' 'pvr.nextpvr|21.3.2.1|https://example.test/pvr.nextpvr.zip|deadbeef' ;;
    script.plexmod) printf '%s\n' 'script.plexmod|1.14.1-beta1|https://example.test/script.plexmod.zip|deadbeef' ;;
    plugin.video.youtube) printf '%s\n' 'plugin.video.youtube|7.4.4|https://example.test/plugin.video.youtube.zip|deadbeef' ;;
    plugin.service.emby-next-gen) printf '%s\n' 'plugin.service.emby-next-gen|12.4.23|https://example.test/plugin.service.emby-next-gen.zip|deadbeef' ;;
    *)
      printf 'unknown fixture add-on: %s\n' "$1" >&2
      return 1
      ;;
  esac
}

write_config() {
  local file="$1"
  shift
  cat > "${file}" <<'CONFIG'
EXPECTED_RELEASE=21.3
SSH_PORT=22
KODI_PORT=8080
KODI_USER=homeassistant
REPORT_DIR=./ignored-by-tests
CONFIG
  while (( $# > 0 )); do
    printf 'ADDON_ARTIFACT=%s\n' "$(addon_record "$1")" >> "${file}"
    shift
  done
}

install_ssh_stub() {
  local dir bin_dir stub_dir
  dir="$1"
  bin_dir="${dir}/stub-bin"
  stub_dir="${dir}/stub"
  mkdir -p "${bin_dir}" "${stub_dir}"
  cat > "${bin_dir}/ssh" <<'STUB'
#!/bin/bash
set -eu
stub_dir="${COREELEC_SSH_STUB_DIR:?}"
count_file="${stub_dir}/call-count"
count=0
[[ -f "${count_file}" ]] && count="$(cat "${count_file}")"
count=$((count + 1))
printf '%s\n' "${count}" > "${count_file}"
printf '%s\n' "$#" > "${stub_dir}/argc-${count}.log"
: > "${stub_dir}/argv-${count}.log"
index=1
for argument in "$@"; do
  printf '%s' "${argument}" > "${stub_dir}/argument-${count}-${index}.log"
  printf 'argv[%s]=<%s>\n' "${index}" "${argument}" >> "${stub_dir}/argv-${count}.log"
  index=$((index + 1))
done
cat > "${stub_dir}/stdin-${count}.log"
response="${stub_dir}/response-${count}.json"
[[ -f "${response}" ]] || response="${stub_dir}/response-default.json"
if [[ -f "${response}" ]]; then
  cat "${response}"
fi
STUB
  chmod +x "${bin_dir}/ssh"
  printf '%s\n' "${bin_dir}"
}

install_python3_argv_stub() {
  local dir bin_dir log_dir resolved
  dir="$1"
  bin_dir="${dir}/python3-stub-bin"
  log_dir="${dir}/python3-stub-logs"
  mkdir -p "${bin_dir}" "${log_dir}"
  resolved="$(python3 -c 'import sys; sys.stdout.write(sys.executable)')"
  printf '%s\n' "${resolved}" > "${bin_dir}/python3-real"
  cat > "${bin_dir}/python3" <<'STUB'
#!/bin/bash
set -eu
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log_dir="${script_dir}/../python3-stub-logs"
count_file="${log_dir}/call-count"
count=0
[[ -f "${count_file}" ]] && count="$(cat "${count_file}")"
count=$((count + 1))
printf '%s\n' "${count}" > "${count_file}"
printf '%s\n' "$*" > "${log_dir}/argv-${count}.log"
exec "$(cat "${script_dir}/python3-real")" "$@"
STUB
  chmod +x "${bin_dir}/python3"
  printf '%s\n' "${bin_dir}"
}

ssh_call_count() {
  local dir="$1"
  if [[ -f "${dir}/stub/call-count" ]]; then
    cat "${dir}/stub/call-count"
  else
    printf '0\n'
  fi
}

ssh_argc() {
  cat "$1/stub/argc-$2.log"
}

ssh_argv_element() {
  cat "$1/stub/argument-$2-$3.log"
}

ssh_remote_target_index() {
  local dir="$1" call="$2" target="$3" argc index argument
  argc="$(ssh_argc "${dir}" "${call}")"
  for ((index = 1; index <= argc; index++)); do
    argument="$(ssh_argv_element "${dir}" "${call}" "${index}")"
    case "${argument}" in
      "${target}"|"root@${target}")
        printf '%s\n' "${index}"
        return 0
        ;;
    esac
  done
  return 1
}

assert_single_remote_script_argument() {
  local dir="$1" call="$2" target="$3" argc target_index remote_count remote_script
  argc="$(ssh_argc "${dir}" "${call}")"
  target_index="$(ssh_remote_target_index "${dir}" "${call}" "${target}")" || {
    printf 'assert_single_remote_script_argument: target argument not found (call=%s target=%s)\n' \
      "${call}" "${target}" >&2
    return 1
  }
  remote_count=$((argc - target_index))
  assert_eq "1" "${remote_count}" \
    "OpenSSH must receive exactly one remote command argument after the target" || return 1
  remote_script="$(ssh_argv_element "${dir}" "${call}" "$((target_index + 1))")"
  case "${remote_script}" in
    sh|-c)
      printf 'assert_single_remote_script_argument: split remote sh -c transport detected (call=%s)\n' \
        "${call}" >&2
      return 1
      ;;
  esac
  assert_contains "${remote_script}" $'set -eu\n' \
    "the single remote argument must contain the complete strict-mode script"
}

assert_hardened_ssh_options() {
  local dir="$1" call="$2" identity_file="$3" target="$4" argc index
  local expected=(
    -p 22
    -o ConnectTimeout=12
    -o ServerAliveInterval=15
    -o ServerAliveCountMax=3
    -o StrictHostKeyChecking=accept-new
    -i "${identity_file}"
    -o IdentitiesOnly=yes
    -o PreferredAuthentications=publickey
    -o PasswordAuthentication=no
    -o KbdInteractiveAuthentication=no
    -o BatchMode=yes
    "root@${target}"
  )
  argc="$(ssh_argc "${dir}" "${call}")"
  assert_eq "24" "${argc}" \
    "hardened SSH options, root target, and one remote script form 24 argv elements" || return 1
  for ((index = 1; index <= ${#expected[@]}; index++)); do
    assert_eq "${expected[index-1]}" "$(ssh_argv_element "${dir}" "${call}" "${index}")" \
      "SSH argv element ${index} must match the provisioner transport" || return 1
  done
}

python3_call_count() {
  local dir="$1"
  if [[ -f "${dir}/python3-stub-logs/call-count" ]]; then
    cat "${dir}/python3-stub-logs/call-count"
  else
    printf '0\n'
  fi
}

python3_argv_logs() {
  local dir="$1" file
  find "${dir}/python3-stub-logs" -type f -name 'argv-*.log' | LC_ALL=C sort | while IFS= read -r file; do
    cat "${file}"
    printf '\n'
  done
}

assert_python3_stub_recorded_calls() {
  local dir="$1" count="$2" message="$3"
  if [[ "${count}" == "0" ]]; then
    printf 'assert_python3_stub_recorded_calls: %s (dir=%s)\n' "${message}" "${dir}" >&2
    return 1
  fi
  return 0
}

ssh_request_body() {
  local dir="$1" count="$2"
  tail -n +3 "${dir}/stub/stdin-${count}.log" | tr -d '\n'
}

ssh_request_id() {
  python3 -c 'import json,sys; sys.stdout.write(json.loads(sys.argv[1])["id"])' "$1"
}

find_single_report() {
  find "$1" -type f -name '*.txt' | LC_ALL=C sort
}

write_introspection_response() {
  local file="$1" missing_method="${2:-}"
  python3 - "${file}" "${missing_method}" <<'PYEOF'
import json
import sys

path, missing = sys.argv[1], sys.argv[2]
methods = [
    "JSONRPC.Introspect",
    "Addons.ExecuteAddon",
    "Addons.GetAddonDetails",
    "GUI.ActivateWindow",
    "GUI.GetProperties",
    "Input.ExecuteAction",
    "Input.SendText",
]
payload = {
    "jsonrpc": "2.0",
    "id": "introspect",
    "result": {
        "methods": {
            name: {"type": "method"}
            for name in methods
            if name != missing
        }
    },
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, separators=(",", ":"))
PYEOF
}

write_gui_state_response() {
  local file="$1" window_label="$2" control_label="$3"
  python3 - "${file}" "${window_label}" "${control_label}" <<'PYEOF'
import json
import sys

path, window_label, control_label = sys.argv[1:4]
payload = {
    "jsonrpc": "2.0",
    "id": "gui-state",
    "result": {
        "currentwindow": {"label": window_label},
        "currentcontrol": {"label": control_label},
    },
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, separators=(",", ":"))
PYEOF
}

write_addon_details_response() {
  local file="$1" addon_id="$2" version="$3"
  python3 - "${file}" "${addon_id}" "${version}" <<'PYEOF'
import json
import sys

path, addon_id, version = sys.argv[1:4]
payload = {
    "jsonrpc": "2.0",
    "id": "addons-getaddondetails",
    "result": {
        "addon": {
            "addonid": addon_id,
            "version": version,
        }
    },
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, separators=(",", ":"))
PYEOF
}

write_http_response() {
  local file="$1" transport="$2" http_status="$3" body="$4" content_type="${5:-application/json}"
  python3 - "${file}" "${transport}" "${http_status}" "${body}" "${content_type}" <<'PYEOF'
import json
import sys

path, transport, http_status, body, content_type = sys.argv[1:6]
payload = {
    "transport": transport,
    "http_status": int(http_status),
    "body": body,
    "content_type": content_type,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, separators=(",", ":"))
PYEOF
}

nextpvr_login_md5() {
  python3 - "$1" "$2" <<'PYEOF'
import hashlib
import sys

pin, salt = sys.argv[1:3]
pin_md5 = hashlib.md5(pin.encode("utf-8")).hexdigest().lower()
combined = ":" + pin_md5 + ":" + salt
sys.stdout.write(hashlib.md5(combined.encode("utf-8")).hexdigest())
PYEOF
}

set_guided_flow_pins() {
  ADDON_ARTIFACTS=(
    "$(addon_record script.plexmod)"
    "$(addon_record plugin.video.youtube)"
  )
}

test_help_lists_supported_addons_and_interaction_levels() {
  local output
  output="$(bash "${CLI_SCRIPT}" --help)"
  assert_contains "${output}" "Supported post-deployment add-ons:" "help lists supported add-ons" || return 1
  assert_contains "${output}" "weather.ha                 fully-unattended" "weather.ha interaction level" || return 1
  assert_contains "${output}" "plugin.video.youtube      guided (--interactive)" "YouTube interaction level" || return 1
  assert_contains "${output}" "plugin.service.emby-next-gen guided (--interactive)" "Emby interaction level" || return 1
}

assert_dry_run_makes_no_ssh_calls() (
  local interactive="$1" dir config bin_dir output rc report report_body addon_id
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' EXIT
  config="${dir}/postdeploy.conf"
  write_config "${config}" \
    weather.ha pvr.nextpvr script.plexmod plugin.video.youtube plugin.service.emby-next-gen
  cat >> "${config}" <<'CONFIG'
HOME_ASSISTANT_URL=https://ha.example.test
HOME_ASSISTANT_WEATHER_ENTITY=weather.forecast_home
CONFIG
  bin_dir="$(install_ssh_stub "${dir}")"
  printf '%s\n' \
    '{"transport":"ok","http_status":401,"body":"{}","content_type":"application/json"}' \
    > "${dir}/stub/response-default.json"
  set +e
  if [[ "${interactive}" == "1" ]]; then
    output="$(
      COREELEC_SSH_STUB_DIR="${dir}/stub" \
      KODI_WEB_PASSWORD="dry-run-kodi-secret" \
      HOME_ASSISTANT_TOKEN="dry-run-home-assistant-secret" \
      COREELEC_GUIDED_FLOW_POLL_INTERVAL_SECONDS="0" \
      PATH="${bin_dir}:${PATH}" \
      bash "${CLI_SCRIPT}" \
        --config "${config}" \
        --report-dir "${dir}/reports" \
        --target coreelec-theater \
        --dry-run \
        --interactive 2>&1
    )"
  else
    output="$(
      COREELEC_SSH_STUB_DIR="${dir}/stub" \
      KODI_WEB_PASSWORD="dry-run-kodi-secret" \
      HOME_ASSISTANT_TOKEN="dry-run-home-assistant-secret" \
      COREELEC_GUIDED_FLOW_POLL_INTERVAL_SECONDS="0" \
      PATH="${bin_dir}:${PATH}" \
      bash "${CLI_SCRIPT}" \
        --config "${config}" \
        --report-dir "${dir}/reports" \
        --target coreelec-theater \
        --dry-run 2>&1
    )"
  fi
  rc=$?
  set -e

  assert_success "${rc}" "dry-run should complete without a device" || return 1
  assert_eq "0" "$(ssh_call_count "${dir}")" \
    "dry-run must make zero SSH/device calls, including interactive mode" || return 1
  assert_eq "0" "$(find "${dir}/stub" -type f -name 'stdin-*.log' | wc -l | tr -d ' ')" \
    "dry-run must not open a transport capable of transmitting secrets" || return 1
  report="$(find_single_report "${dir}/reports")"
  report_body="$(cat "${report}")"
  for addon_id in weather.ha pvr.nextpvr script.plexmod plugin.video.youtube plugin.service.emby-next-gen; do
    assert_contains "${report_body}" "addon.${addon_id}.status=dry-run" \
      "dry-run emits one static status for ${addon_id}" || return 1
  done
  assert_not_contains "${output}${report_body}" "dry-run-kodi-secret" \
    "dry-run output and report must not contain the Kodi secret" || return 1
  assert_not_contains "${output}${report_body}" "dry-run-home-assistant-secret" \
    "dry-run output and report must not contain the Home Assistant secret"
)

test_dry_run_makes_zero_ssh_calls() {
  assert_dry_run_makes_no_ssh_calls "0"
}

test_interactive_dry_run_makes_zero_ssh_calls() {
  assert_dry_run_makes_no_ssh_calls "1"
}

test_report_creation_uses_private_umask_before_chmod() {
  local dir config bin_dir output rc report modes
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/postdeploy.conf"
  write_config "${config}" plugin.video.youtube
  bin_dir="${dir}/stub-bin"
  mkdir -p "${bin_dir}"
  cat > "${bin_dir}/chmod" <<'STUB'
#!/bin/bash
exit 0
STUB
  /bin/chmod +x "${bin_dir}/chmod"

  set +e
  output="$(
    umask 022
    PATH="${bin_dir}:${PATH}" \
      bash "${CLI_SCRIPT}" \
        --config "${config}" \
        --report-dir "${dir}/reports" \
        --target coreelec-theater \
        --addon plugin.video.youtube \
        --dry-run 2>&1
  )"
  rc=$?
  set -e

  assert_success "${rc}" "report creation should succeed when chmod is defense in depth only" || return 1
  report="$(find_single_report "${dir}/reports")"
  modes="$(python3 - "${dir}/reports" "${report}" <<'PYEOF'
import os
import stat
import sys

print("%03o %03o" % (
    stat.S_IMODE(os.stat(sys.argv[1]).st_mode),
    stat.S_IMODE(os.stat(sys.argv[2]).st_mode),
))
PYEOF
)"
  assert_eq "700 600" "${modes}" \
    "umask 077 must protect the report directory and file before chmod runs"
}

test_default_run_never_starts_account_authorization() {
  local dir config bin_dir output rc report body
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/postdeploy.conf"
  write_config "${config}" \
    weather.ha pvr.nextpvr script.plexmod plugin.video.youtube plugin.service.emby-next-gen
  bin_dir="$(install_ssh_stub "${dir}")"
  write_introspection_response "${dir}/stub/response-default.json"

  set +e
  output="$(
    COREELEC_SSH_STUB_DIR="${dir}/stub" \
    KODI_WEB_PASSWORD="kodi-web-password-secret" \
    PATH="${bin_dir}:${PATH}" \
    bash "${CLI_SCRIPT}" \
      --config "${config}" \
      --report-dir "${dir}/reports" \
      --target coreelec-theater 2>&1
  )"
  rc=$?
  set -e

  assert_success "${rc}" "default run should succeed with non-interactive statuses only" || return 1
  assert_eq "1" "$(ssh_call_count "${dir}")" "default run should make only the introspection call" || return 1
  body="$(ssh_request_body "${dir}" 1)"
  assert_eq '{"jsonrpc":"2.0","id":"introspect","method":"JSONRPC.Introspect","params":{"getdescriptions":false,"getmetadata":false}}' \
    "${body}" "default run performs the required introspection call" || return 1
  report="$(find_single_report "${dir}/reports")"
  assert_contains "$(cat "${report}")" "addon.plugin.video.youtube.status=authorization-required" \
    "default run reports that YouTube authorization is deferred" || return 1
  assert_contains "$(cat "${report}")" "addon.plugin.service.emby-next-gen.status=authorization-required" \
    "default run reports that Emby authorization is deferred" || return 1
  assert_not_contains "${output}" "Input.ExecuteAction" "default run never attempts guided input" || return 1
}

test_requested_addon_must_be_in_the_pinned_manifest() {
  local dir config output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/postdeploy.conf"
  write_config "${config}" weather.ha

  set +e
  output="$(bash "${CLI_SCRIPT}" --config "${config}" --dry-run --target coreelec-theater --addon plugin.video.youtube 2>&1)"
  rc=$?
  set -e

  assert_failure "${rc}" "an unpinned add-on must be rejected" || return 1
  assert_contains "${output}" "not in the locked artifact manifest" "error names the manifest constraint" || return 1
}

test_introspection_rejects_a_missing_required_method() {
  local dir config bin_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/postdeploy.conf"
  write_config "${config}" plugin.video.youtube
  bin_dir="$(install_ssh_stub "${dir}")"
  write_introspection_response "${dir}/stub/response-default.json" "Input.SendText"

  set +e
  output="$(
    COREELEC_SSH_STUB_DIR="${dir}/stub" \
    KODI_WEB_PASSWORD="kodi-web-password-secret" \
    PATH="${bin_dir}:${PATH}" \
    bash "${CLI_SCRIPT}" \
      --config "${config}" \
      --interactive \
      --target coreelec-theater \
      --addon plugin.video.youtube 2>&1
  )"
  rc=$?
  set -e

  assert_failure "${rc}" "interactive runs must fail closed when a required method is missing" || return 1
  assert_contains "${output}" "Input.SendText" "missing method is named in the failure" || return 1
}

test_introspection_requires_addons_getaddondetails() {
  local dir config bin_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/postdeploy.conf"
  write_config "${config}" plugin.video.youtube
  bin_dir="$(install_ssh_stub "${dir}")"
  write_introspection_response "${dir}/stub/response-default.json" "Addons.GetAddonDetails"

  set +e
  output="$(
    COREELEC_SSH_STUB_DIR="${dir}/stub" \
    KODI_WEB_PASSWORD="kodi-web-password-secret" \
    PATH="${bin_dir}:${PATH}" \
    bash "${CLI_SCRIPT}" \
      --config "${config}" \
      --interactive \
      --target coreelec-theater \
      --addon plugin.video.youtube 2>&1
  )"
  rc=$?
  set -e

  assert_failure "${rc}" \
    "interactive runs must fail at capability discovery without Addons.GetAddonDetails" || return 1
  assert_contains "${output}" "Addons.GetAddonDetails" \
    "the missing add-on details capability is named"
}

test_every_remote_script_is_one_ssh_argument() {
  local dir bin_dir call
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  printf '%s\n' '{}' > "${dir}/stub/response-default.json"
  TARGET="coreelec-theater"
  SSH_PORT="22"
  KODI_PORT="8080"
  KODI_USER="homeassistant"
  KODI_WEB_PASSWORD="kodi-web-password-secret"
  EMBY_SERVER_URL="https://emby.example.test"

  COREELEC_SSH_STUB_DIR="${dir}/stub" PATH="${bin_dir}:${PATH}" \
    kodi_rpc "JSONRPC.Introspect" '{"getdescriptions":false,"getmetadata":false}' >/dev/null
  COREELEC_SSH_STUB_DIR="${dir}/stub" PATH="${bin_dir}:${PATH}" \
    coreelec_postdeploy_read_addon_data_file "script.plexmod" "settings.xml" >/dev/null
  COREELEC_SSH_STUB_DIR="${dir}/stub" PATH="${bin_dir}:${PATH}" \
    coreelec_postdeploy_emby_state >/dev/null
  COREELEC_SSH_STUB_DIR="${dir}/stub" PATH="${bin_dir}:${PATH}" \
    coreelec_postdeploy_http_request "GET" "https://service.example.test/status" '{}' >/dev/null

  assert_eq "4" "$(ssh_call_count "${dir}")" "all four SSH transport paths were exercised" || return 1
  for call in 1 2 3 4; do
    assert_single_remote_script_argument "${dir}" "${call}" "coreelec-theater" || return 1
  done
}

test_ssh_transport_matches_provisioner_hardening() {
  local dir bin_dir identity_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  printf '%s\n' '{}' > "${dir}/stub/response-default.json"
  identity_file="${dir}/coreelec admin key"
  TARGET="coreelec-theater"
  SSH_PORT="22"
  KODI_PORT="8080"
  KODI_USER="homeassistant"
  KODI_WEB_PASSWORD="kodi-web-password-secret"
  IDENTITY_FILE="${identity_file}"

  COREELEC_SSH_STUB_DIR="${dir}/stub" PATH="${bin_dir}:${PATH}" \
    kodi_rpc "JSONRPC.Introspect" '{"getdescriptions":false,"getmetadata":false}' >/dev/null

  assert_hardened_ssh_options "${dir}" "1" "${identity_file}" "coreelec-theater" || return 1
  assert_single_remote_script_argument "${dir}" "1" "coreelec-theater"
}

test_addon_data_reader_keeps_path_values_out_of_remote_command() {
  local dir bin_dir addon_id relative_path remote_script stdin_body
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  addon_id='script.plexmod; printf ADDON_INJECTION'
  relative_path='settings.xml; printf PATH_INJECTION'
  TARGET="coreelec-theater"
  SSH_PORT="22"
  IDENTITY_FILE="${dir}/admin-key"

  COREELEC_SSH_STUB_DIR="${dir}/stub" PATH="${bin_dir}:${PATH}" \
    coreelec_postdeploy_read_addon_data_file "${addon_id}" "${relative_path}" >/dev/null

  remote_script="$(ssh_argv_element "${dir}" "1" "$(ssh_argc "${dir}" "1")")"
  stdin_body="$(cat "${dir}/stub/stdin-1.log")"
  assert_not_contains "${remote_script}" "${addon_id}" \
    "add-on ID must not be interpolated into the remote shell program" || return 1
  assert_not_contains "${remote_script}" "${relative_path}" \
    "relative path must not be interpolated into the remote shell program" || return 1
  assert_eq "${addon_id}"$'\n'"${relative_path}" "${stdin_body}" \
    "add-on path values are passed as quoted stdin data"
}

test_gui_guard_accepts_expected_window_and_control() {
  kodi_gui_state() {
    printf '%s\n' '{"jsonrpc":"2.0","id":"gui-state","result":{"currentwindow":{"label":"  Expected Window  "},"currentcontrol":{"label":" Expected Control "}}}'
  }
  require_gui_state "Expected Window" "Expected Control" >/dev/null
}

test_gui_guard_rejects_an_unexpected_window_without_sending_input() {
  local dir bin_dir output rc body
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  write_gui_state_response "${dir}/stub/response-1.json" "Wrong Window" "Expected Control"
  TARGET="coreelec-theater"
  SSH_PORT="22"
  KODI_PORT="8080"
  KODI_USER="homeassistant"
  KODI_WEB_PASSWORD="kodi-web-password-secret"

  set +e
  output="$(
    COREELEC_SSH_STUB_DIR="${dir}/stub" PATH="${bin_dir}:${PATH}" bash -c '
      source "'"${WORKFLOW_LIB}"'"
      TARGET="coreelec-theater"
      SSH_PORT="22"
      KODI_PORT="8080"
      KODI_USER="homeassistant"
      KODI_WEB_PASSWORD="kodi-web-password-secret"
      if require_gui_state "Expected Window" "Expected Control"; then
        kodi_rpc "Input.ExecuteAction" "{\"action\":\"select\"}" >/dev/null
        exit 0
      fi
      exit 1
    ' 2>&1
  )"
  rc=$?
  set -e

  assert_failure "${rc}" "the GUI guard must reject an unexpected window" || return 1
  assert_eq "1" "$(ssh_call_count "${dir}")" "a rejected guard must stop before sending input" || return 1
  body="$(ssh_request_body "${dir}" 1)"
  assert_eq '{"jsonrpc":"2.0","id":"gui-state","method":"GUI.GetProperties","params":{"properties":["currentwindow","currentcontrol"]}}' \
    "${body}" "only the GUI state request is sent" || return 1
  assert_contains "${output}" "Wrong Window" "guard output names the observed window" || return 1
}

test_rpc_request_ids_never_contain_secret_values() {
  local dir bin_dir secret body request_id
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  printf '%s\n' '{"jsonrpc":"2.0","id":"input-sendtext","result":"OK"}' > "${dir}/stub/response-default.json"
  TARGET="coreelec-theater"
  SSH_PORT="22"
  KODI_PORT="8080"
  KODI_USER="homeassistant"
  KODI_WEB_PASSWORD="kodi-web-password-secret"
  secret="emby-password-secret"

  COREELEC_SSH_STUB_DIR="${dir}/stub" PATH="${bin_dir}:${PATH}" \
    kodi_rpc "Input.SendText" "{\"text\":\"${secret}\",\"done\":true}" >/dev/null

  body="$(ssh_request_body "${dir}" 1)"
  request_id="$(ssh_request_id "${body}")"
  assert_eq "input-sendtext" "${request_id}" "request id derives from the method name only" || return 1
  assert_not_contains "${request_id}" "${secret}" "request id must not contain the secret text" || return 1
  assert_not_contains "$(cat "${dir}/stub/argv-1.log")" "${secret}" "secret must not leak into ssh arguments" || return 1
}

test_report_contains_statuses_but_no_secret_values() {
  local dir config bin_dir output rc report report_body
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  config="${dir}/postdeploy.conf"
  write_config "${config}" weather.ha plugin.video.youtube
  bin_dir="$(install_ssh_stub "${dir}")"
  write_introspection_response "${dir}/stub/response-default.json"

  set +e
  output="$(
    COREELEC_SSH_STUB_DIR="${dir}/stub" \
    KODI_WEB_PASSWORD="kodi-web-password-secret" \
    PATH="${bin_dir}:${PATH}" \
    bash "${CLI_SCRIPT}" \
      --config "${config}" \
      --report-dir "${dir}/reports" \
      --target coreelec-theater 2>&1
  )"
  rc=$?
  set -e

  assert_success "${rc}" "report fixture run should succeed" || return 1
  report="$(find_single_report "${dir}/reports")"
  report_body="$(cat "${report}")"
  assert_contains "${report_body}" "addon.weather.ha.status=skipped" "weather status is written" || return 1
  assert_contains "${report_body}" "addon.plugin.video.youtube.status=authorization-required" \
    "YouTube status is written" || return 1
  assert_not_contains "${report_body}" "kodi-web-password-secret" "report must not leak the Kodi password" || return 1
  assert_contains "${output}" "Report:" "run output points to the report file" || return 1
}

test_weather_check_accepts_config_and_entity_responses() {
  local dir bin_dir python_bin_dir output body
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  python_bin_dir="$(install_python3_argv_stub "${dir}")"
  write_http_response "${dir}/stub/response-1.json" ok 200 '{"location_name":"Home"}'
  write_http_response "${dir}/stub/response-2.json" ok 200 '{"entity_id":"weather.forecast_home","state":"sunny"}'
  printf '%s\n' '{"jsonrpc":"2.0","id":"addons-executeaddon","result":"OK"}' > "${dir}/stub/response-3.json"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${python_bin_dir}:${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    HOME_ASSISTANT_URL="https://ha.example.lan:8123"
    HOME_ASSISTANT_WEATHER_ENTITY="weather.forecast_home"
    HOME_ASSISTANT_TOKEN="home-assistant-token-secret"
    printf 'workflow_status=%s\n' "$(check_home_assistant_weather)"
  } 2>&1)"

  assert_eq "3" "$(ssh_call_count "${dir}")" "weather check performs two HTTP requests and one Kodi launch" || return 1
  assert_contains "${output}" "service.weather.ha.config_http_status=200" "config endpoint is reported" || return 1
  assert_contains "${output}" "service.weather.ha.entity_http_status=200" "entity endpoint is reported" || return 1
  assert_contains "${output}" "service.weather.ha.kodi_execute=ok" "add-on launch is reported" || return 1
  assert_contains "${output}" "workflow_status=configured" "healthy weather configuration is accepted" || return 1
  assert_not_contains "$(python3_argv_logs "${dir}")" "home-assistant-token-secret" \
    "weather token must not leak into local python argv" || return 1
  assert_python3_stub_recorded_calls "${dir}" "$(python3_call_count "${dir}")" \
    "weather check should exercise local python helpers through the stub" || return 1
  body="$(ssh_request_body "${dir}" 3)"
  assert_eq '{"jsonrpc":"2.0","id":"addons-executeaddon","method":"Addons.ExecuteAddon","params":{"addonid":"weather.ha"}}' \
    "${body}" "weather check executes the configured add-on once" || return 1
}

test_weather_check_reports_unauthorized_without_echoing_token() {
  local dir bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  write_http_response "${dir}/stub/response-1.json" ok 401 '{"message":"unauthorized"}'

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    HOME_ASSISTANT_URL="https://ha.example.lan:8123"
    HOME_ASSISTANT_WEATHER_ENTITY="weather.forecast_home"
    HOME_ASSISTANT_TOKEN="home-assistant-token-secret"
    printf 'workflow_status=%s\n' "$(check_home_assistant_weather)"
  } 2>&1)"

  assert_eq "1" "$(ssh_call_count "${dir}")" "unauthorized weather checks stop before entity or add-on launch" || return 1
  assert_contains "${output}" "service.weather.ha.failure=unauthorized" "weather auth failure is classified distinctly" || return 1
  assert_contains "${output}" "service.weather.ha.config_http_status=401" "weather auth failure reports the status code" || return 1
  assert_contains "${output}" "workflow_status=authorization-required" "weather auth failure requires new credentials" || return 1
  assert_not_contains "${output}" "home-assistant-token-secret" "weather output must not echo the token" || return 1
  assert_not_contains "$(cat "${dir}/stub/argv-1.log")" "home-assistant-token-secret" "weather token must not leak into ssh argv" || return 1
}

test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin() {
  local dir bin_dir python_bin_dir output expected_md5
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  python_bin_dir="$(install_python3_argv_stub "${dir}")"
  write_http_response "${dir}/stub/response-1.json" ok 200 '<rsp stat="ok"><sid>sid-123</sid><salt>salt-456</salt></rsp>' application/xml
  write_http_response "${dir}/stub/response-2.json" ok 200 '<rsp stat="ok"></rsp>' application/xml
  printf '%s\n' '{"jsonrpc":"2.0","id":"pvr-getchannelgroups","result":{"channelgroups":[],"limits":{"start":0,"end":0,"total":0}}}' > "${dir}/stub/response-3.json"
  expected_md5="$(nextpvr_login_md5 "2468" "salt-456")"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${python_bin_dir}:${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    NEXTPVR_PROTOCOL="https"
    NEXTPVR_HOST="nextpvr.example.lan"
    NEXTPVR_PORT="8867"
    NEXTPVR_PIN="2468"
    printf 'workflow_status=%s\n' "$(check_nextpvr)"
  } 2>&1)"

  assert_eq "3" "$(ssh_call_count "${dir}")" "NextPVR check performs backend login and advisory Kodi observation" || return 1
  assert_contains "$(cat "${dir}/stub/stdin-1.log")" '"url":"https://nextpvr.example.lan:8867/service?method=session.initiate&ver=1.0&device=xbmc"' \
    "NextPVR initiate request uses the configured protocol, host, and port" || return 1
  assert_contains "$(cat "${dir}/stub/stdin-2.log")" "session.login&sid=sid-123&md5=${expected_md5}" \
    "NextPVR login request uses the pinned lower-case MD5 combination" || return 1
  assert_not_contains "$(cat "${dir}/stub/stdin-2.log")" "2468" "NextPVR login request must not send the plain PIN" || return 1
  assert_contains "${output}" "service.pvr.nextpvr.session_initiate_http_status=200" "NextPVR initiate status is reported" || return 1
  assert_contains "${output}" "service.pvr.nextpvr.session_login=ok" "NextPVR login success is reported" || return 1
  assert_contains "${output}" "service.pvr.nextpvr.kodi_channel_groups=ok" "NextPVR advisory Kodi observation is reported" || return 1
  assert_contains "${output}" "workflow_status=configured" "healthy NextPVR configuration is accepted" || return 1
  assert_not_contains "$(python3_argv_logs "${dir}")" "2468" "NextPVR PIN must not leak into local python argv" || return 1
  assert_python3_stub_recorded_calls "${dir}" "$(python3_call_count "${dir}")" \
    "NextPVR check should exercise local python helpers through the stub" || return 1
}

test_nextpvr_check_requires_a_successful_session_login() {
  local dir bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  write_http_response "${dir}/stub/response-1.json" ok 200 '<rsp stat="ok"><sid>sid-123</sid><salt>salt-456</salt></rsp>' application/xml
  write_http_response "${dir}/stub/response-2.json" ok 200 '<rsp stat="fail"><err code="8" message="bad login" /></rsp>' application/xml

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    NEXTPVR_PROTOCOL="http"
    NEXTPVR_HOST="nextpvr.example.lan"
    NEXTPVR_PORT="8866"
    NEXTPVR_PIN="2468"
    printf 'workflow_status=%s\n' "$(check_nextpvr)"
  } 2>&1)"

  assert_eq "2" "$(ssh_call_count "${dir}")" "failed NextPVR login stops before the advisory Kodi call" || return 1
  assert_contains "${output}" "service.pvr.nextpvr.failure=authorization-required" "NextPVR login failure is classified distinctly" || return 1
  assert_contains "${output}" "service.pvr.nextpvr.session_login=failed" "NextPVR login result is reported" || return 1
  assert_contains "${output}" "workflow_status=authorization-required" "failed NextPVR login requires new credentials" || return 1
}

test_pm4k_local_check_requires_identity_and_token_authorized_root() {
  local success_dir success_bin success_python_bin success_output failure_dir failure_bin failure_output body

  success_dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${success_dir}" "${failure_dir:-}"' RETURN
  success_bin="$(install_ssh_stub "${success_dir}")"
  success_python_bin="$(install_python3_argv_stub "${success_dir}")"
  write_http_response "${success_dir}/stub/response-1.json" ok 200 '{"MediaContainer":{"machineIdentifier":"plex-machine-1"}}'
  write_http_response "${success_dir}/stub/response-2.json" ok 200 '{"MediaContainer":{"friendlyName":"Basement Plex"}}'
  printf '%s\n' '{"jsonrpc":"2.0","id":"addons-executeaddon","result":"OK"}' > "${success_dir}/stub/response-3.json"

  success_output="$({
    export COREELEC_SSH_STUB_DIR="${success_dir}/stub"
    export PATH="${success_python_bin}:${success_bin}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    PLEX_SERVER_HOST="plex.example.lan"
    PLEX_SERVER_PORT="32400"
    PLEX_SERVER_NAME="Basement Plex"
    PLEX_PROFILE_IDS="11,22"
    PLEX_TOKEN="plex-token-secret"
    printf 'workflow_status=%s\n' "$(check_pm4k_local)"
  } 2>&1)"

  assert_eq "3" "$(ssh_call_count "${success_dir}")" "PM4K local check launches the add-on after both Plex probes pass" || return 1
  assert_contains "${success_output}" "service.script.plexmod.identity_http_status=200" "PM4K identity probe is reported" || return 1
  assert_contains "${success_output}" "service.script.plexmod.root_http_status=200" "PM4K authenticated root probe is reported" || return 1
  assert_contains "${success_output}" "service.script.plexmod.kodi_execute=ok" "PM4K launch is reported" || return 1
  assert_contains "${success_output}" "workflow_status=configured" "healthy PM4K local configuration is accepted" || return 1
  assert_not_contains "$(python3_argv_logs "${success_dir}")" "plex-token-secret" \
    "PM4K token must not leak into local python argv" || return 1
  assert_python3_stub_recorded_calls "${success_dir}" "$(python3_call_count "${success_dir}")" \
    "PM4K check should exercise local python helpers through the stub" || return 1
  body="$(ssh_request_body "${success_dir}" 3)"
  assert_eq '{"jsonrpc":"2.0","id":"addons-executeaddon","method":"Addons.ExecuteAddon","params":{"addonid":"script.plexmod"}}' \
    "${body}" "PM4K local check launches script.plexmod after successful validation" || return 1

  failure_dir="$(make_scratch_dir)"
  failure_bin="$(install_ssh_stub "${failure_dir}")"
  write_http_response "${failure_dir}/stub/response-1.json" ok 200 '{"MediaContainer":{"machineIdentifier":"plex-machine-1"}}'
  write_http_response "${failure_dir}/stub/response-2.json" ok 401 '{"errors":[{"code":401,"message":"unauthorized"}]}'

  failure_output="$({
    export COREELEC_SSH_STUB_DIR="${failure_dir}/stub"
    export PATH="${failure_bin}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    PLEX_SERVER_HOST="plex.example.lan"
    PLEX_SERVER_PORT="32400"
    PLEX_SERVER_NAME="Basement Plex"
    PLEX_PROFILE_IDS="11,22"
    PLEX_TOKEN="plex-token-secret"
    printf 'workflow_status=%s\n' "$(check_pm4k_local)"
  } 2>&1)"

  assert_eq "2" "$(ssh_call_count "${failure_dir}")" "unauthorized PM4K root access stops before launch" || return 1
  assert_contains "${failure_output}" "service.script.plexmod.failure=unauthorized" "PM4K auth failure is classified distinctly" || return 1
  assert_contains "${failure_output}" "service.script.plexmod.root_http_status=401" "PM4K auth failure reports the status code" || return 1
  assert_contains "${failure_output}" "workflow_status=authorization-required" "PM4K auth failure requires new credentials" || return 1
}

test_pm4k_local_check_skips_when_local_configuration_is_absent() {
  local output
  output="$({
    unset PLEX_SERVER_HOST PLEX_SERVER_PORT PLEX_SERVER_NAME PLEX_PROFILE_IDS PLEX_TOKEN
    printf 'workflow_status=%s\n' "$(check_pm4k_local)"
  } 2>&1)"

  assert_contains "${output}" "service.script.plexmod.failure=not-configured" \
    "PM4K local check reports the direct-path skip reason" || return 1
  assert_contains "${output}" "workflow_status=skipped" \
    "PM4K local check must skip when local mode is not configured" || return 1
}

test_service_checks_do_not_modify_addon_settings() {
  local dir bin_dir root output weather_before weather_after nextpvr_before nextpvr_after pm4k_before pm4k_after
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  root="${dir}/root/.kodi/userdata/addon_data"
  mkdir -p "${root}/weather.ha" "${root}/pvr.nextpvr" "${root}/script.plexmod"
  printf '%s\n' '<settings><setting id="token">persisted-weather</setting></settings>' > "${root}/weather.ha/settings.xml"
  printf '%s\n' '<settings><setting id="host">persisted-nextpvr</setting></settings>' > "${root}/pvr.nextpvr/instance-settings-1.xml"
  printf '%s\n' '<settings><setting id="local_mode">persisted-pm4k</setting></settings>' > "${root}/script.plexmod/settings.xml"
  weather_before="$(cat "${root}/weather.ha/settings.xml")"
  nextpvr_before="$(cat "${root}/pvr.nextpvr/instance-settings-1.xml")"
  pm4k_before="$(cat "${root}/script.plexmod/settings.xml")"

  write_http_response "${dir}/stub/response-1.json" ok 200 '{"location_name":"Home"}'
  write_http_response "${dir}/stub/response-2.json" ok 200 '{"entity_id":"weather.forecast_home","state":"sunny"}'
  printf '%s\n' '{"jsonrpc":"2.0","id":"addons-executeaddon","result":"OK"}' > "${dir}/stub/response-3.json"
  write_http_response "${dir}/stub/response-4.json" ok 200 '<rsp stat="ok"><sid>sid-123</sid><salt>salt-456</salt></rsp>' application/xml
  write_http_response "${dir}/stub/response-5.json" ok 200 '<rsp stat="ok"></rsp>' application/xml
  printf '%s\n' '{"jsonrpc":"2.0","id":"pvr-getchannelgroups","result":{"channelgroups":[],"limits":{"start":0,"end":0,"total":0}}}' > "${dir}/stub/response-6.json"
  write_http_response "${dir}/stub/response-7.json" ok 200 '{"MediaContainer":{"machineIdentifier":"plex-machine-1"}}'
  write_http_response "${dir}/stub/response-8.json" ok 200 '{"MediaContainer":{"friendlyName":"Basement Plex"}}'
  printf '%s\n' '{"jsonrpc":"2.0","id":"addons-executeaddon","result":"OK"}' > "${dir}/stub/response-9.json"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    HOME_ASSISTANT_URL="https://ha.example.lan:8123"
    HOME_ASSISTANT_WEATHER_ENTITY="weather.forecast_home"
    HOME_ASSISTANT_TOKEN="home-assistant-token-secret"
    NEXTPVR_PROTOCOL="http"
    NEXTPVR_HOST="nextpvr.example.lan"
    NEXTPVR_PORT="8866"
    NEXTPVR_PIN="2468"
    PLEX_SERVER_HOST="plex.example.lan"
    PLEX_SERVER_PORT="32400"
    PLEX_SERVER_NAME="Basement Plex"
    PLEX_PROFILE_IDS="11,22"
    PLEX_TOKEN="plex-token-secret"
    printf 'weather_status=%s\n' "$(check_home_assistant_weather)"
    printf 'nextpvr_status=%s\n' "$(check_nextpvr)"
    printf 'pm4k_status=%s\n' "$(check_pm4k_local)"
  } 2>&1)"

  weather_after="$(cat "${root}/weather.ha/settings.xml")"
  nextpvr_after="$(cat "${root}/pvr.nextpvr/instance-settings-1.xml")"
  pm4k_after="$(cat "${root}/script.plexmod/settings.xml")"

  assert_eq "${weather_before}" "${weather_after}" "weather check must not rewrite settings" || return 1
  assert_eq "${nextpvr_before}" "${nextpvr_after}" "NextPVR check must not rewrite settings" || return 1
  assert_eq "${pm4k_before}" "${pm4k_after}" "PM4K check must not rewrite settings" || return 1
  assert_contains "${output}" "weather_status=configured" "weather check completed" || return 1
  assert_contains "${output}" "nextpvr_status=configured" "NextPVR check completed" || return 1
  assert_contains "${output}" "pm4k_status=configured" "PM4K check completed" || return 1
}

test_pm4k_launch_uses_addons_executeaddon() {
  local dir bin_dir output body
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  set_guided_flow_pins
  write_addon_details_response "${dir}/stub/response-1.json" "script.plexmod" "1.14.1-beta1"
  printf '%s\n' '<settings></settings>' > "${dir}/stub/response-2.json"
  printf '%s\n' '{"jsonrpc":"2.0","id":"addons-executeaddon","result":"OK"}' > "${dir}/stub/response-3.json"
  write_gui_state_response "${dir}/stub/response-4.json" "Plex" "Sign In"
  printf '%s\n' '{"jsonrpc":"2.0","id":"input-executeaction","result":"OK"}' > "${dir}/stub/response-5.json"
  printf '%s\n' '<settings><setting id="auth.token">pm4k-account-token-secret</setting></settings>' \
    > "${dir}/stub/response-6.json"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    export COREELEC_GUIDED_FLOW_TIMEOUT_SECONDS="1"
    export COREELEC_GUIDED_FLOW_POLL_INTERVAL_SECONDS="0"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    printf 'workflow_status=%s\n' "$(authorize_pm4k_account)"
  } 2>&1)"

  body="$(ssh_request_body "${dir}" 1)"
  assert_eq '{"jsonrpc":"2.0","id":"addons-getaddondetails","method":"Addons.GetAddonDetails","params":{"addonid":"script.plexmod","properties":["version"]}}' \
    "${body}" "PM4K account flow checks the installed version before private steps" || return 1
  body="$(ssh_request_body "${dir}" 3)"
  assert_eq '{"jsonrpc":"2.0","id":"addons-executeaddon","method":"Addons.ExecuteAddon","params":{"addonid":"script.plexmod"}}' \
    "${body}" "PM4K account flow launches the add-on through Addons.ExecuteAddon" || return 1
  body="$(ssh_request_body "${dir}" 5)"
  assert_eq '{"jsonrpc":"2.0","id":"input-executeaction","method":"Input.ExecuteAction","params":{"action":"select"}}' \
    "${body}" "PM4K account flow uses Input.ExecuteAction(select) for Sign In" || return 1
  assert_contains "${output}" "https://plex.tv/link" "PM4K account flow points the operator at Plex linking" || return 1
  assert_contains "${output}" "service.script.plexmod.account_token_present=1" "PM4K account flow reports token presence as a boolean" || return 1
  assert_contains "${output}" "workflow_status=configured" "PM4K account flow succeeds once the token appears" || return 1
  assert_not_contains "${output}" "pm4k-account-token-secret" "PM4K account flow must not print the token" || return 1
}

test_pm4k_selects_sign_in_only_when_expected_control_is_focused() {
  local dir bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  set_guided_flow_pins
  write_addon_details_response "${dir}/stub/response-1.json" "script.plexmod" "1.14.1-beta1"
  printf '%s\n' '<settings></settings>' > "${dir}/stub/response-2.json"
  printf '%s\n' '{"jsonrpc":"2.0","id":"addons-executeaddon","result":"OK"}' > "${dir}/stub/response-3.json"
  write_gui_state_response "${dir}/stub/response-4.json" "Plex" "Go to Settings"
  printf '%s\n' '<settings></settings>' > "${dir}/stub/response-5.json"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    export COREELEC_GUIDED_FLOW_TIMEOUT_SECONDS="0"
    export COREELEC_GUIDED_FLOW_POLL_INTERVAL_SECONDS="0"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    printf 'workflow_status=%s\n' "$(authorize_pm4k_account)"
  } 2>&1)"

  assert_eq "5" "$(ssh_call_count "${dir}")" "PM4K account flow times out without selecting an unexpected control" || return 1
  assert_not_contains "${output}" "input-executeaction" "PM4K account flow must not select when Sign In is not focused" || return 1
  assert_contains "${output}" "service.script.plexmod.failure=timeout" "PM4K account flow reports a bounded guided timeout" || return 1
  assert_contains "${output}" "workflow_status=manual-required" "PM4K account flow fails closed when Sign In is not focused" || return 1
}

test_youtube_launch_uses_the_pinned_sign_in_plugin_route() {
  local dir bin_dir output body
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  set_guided_flow_pins
  write_addon_details_response "${dir}/stub/response-1.json" "plugin.video.youtube" "7.4.4"
  printf '%s\n' '{}' > "${dir}/stub/response-2.json"
  printf '%s\n' '{"jsonrpc":"2.0","id":"gui-activatewindow","result":"OK"}' > "${dir}/stub/response-3.json"
  write_gui_state_response "${dir}/stub/response-4.json" \
    "Please sign in and complete all access authorisation prompts" "OK"
  printf '%s\n' '{"jsonrpc":"2.0","id":"input-executeaction","result":"OK"}' > "${dir}/stub/response-5.json"
  cat > "${dir}/stub/response-6.json" <<'JSON'
{"access_manager":{"users":{"0":{"access_token":"","refresh_token":"youtube-refresh-token-secret","token_expires":9999999999}},"current_user":0,"last_origin":"plugin.video.youtube","developers":{}}}
JSON

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    export COREELEC_GUIDED_FLOW_TIMEOUT_SECONDS="1"
    export COREELEC_GUIDED_FLOW_POLL_INTERVAL_SECONDS="0"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    printf 'workflow_status=%s\n' "$(authorize_youtube)"
  } 2>&1)"

  body="$(ssh_request_body "${dir}" 1)"
  assert_eq '{"jsonrpc":"2.0","id":"addons-getaddondetails","method":"Addons.GetAddonDetails","params":{"addonid":"plugin.video.youtube","properties":["version"]}}' \
    "${body}" "YouTube guided flow checks the installed version before private steps" || return 1
  body="$(ssh_request_body "${dir}" 3)"
  assert_eq '{"jsonrpc":"2.0","id":"gui-activatewindow","method":"GUI.ActivateWindow","params":{"window":"videos","parameters":["plugin://plugin.video.youtube/sign/in/"]}}' \
    "${body}" "YouTube guided flow uses the pinned sign-in plugin route" || return 1
  body="$(ssh_request_body "${dir}" 5)"
  assert_eq '{"jsonrpc":"2.0","id":"input-executeaction","method":"Input.ExecuteAction","params":{"action":"select"}}' \
    "${body}" "YouTube guided flow dismisses the intro dialog through Input.ExecuteAction(select)" || return 1
  assert_contains "${output}" "service.plugin.video.youtube.note=multiple-google-codes-possible-in-7.4.4" \
    "YouTube guided flow reports the pinned add-on caveat" || return 1
  assert_contains "${output}" "service.plugin.video.youtube.account_token_present=1" \
    "YouTube guided flow reports token presence as a boolean" || return 1
  assert_contains "${output}" "workflow_status=configured" "YouTube guided flow succeeds once the token appears" || return 1
  assert_not_contains "${output}" "youtube-refresh-token-secret" "YouTube guided flow must not print the token" || return 1
}

test_youtube_dismisses_only_the_expected_intro_dialog() {
  local dir bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  set_guided_flow_pins
  write_addon_details_response "${dir}/stub/response-1.json" "plugin.video.youtube" "7.4.4"
  printf '%s\n' '{}' > "${dir}/stub/response-2.json"
  printf '%s\n' '{"jsonrpc":"2.0","id":"gui-activatewindow","result":"OK"}' > "${dir}/stub/response-3.json"
  write_gui_state_response "${dir}/stub/response-4.json" "Unexpected Dialog" "Cancel"
  printf '%s\n' '{}' > "${dir}/stub/response-5.json"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    export COREELEC_GUIDED_FLOW_TIMEOUT_SECONDS="0"
    export COREELEC_GUIDED_FLOW_POLL_INTERVAL_SECONDS="0"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    printf 'workflow_status=%s\n' "$(authorize_youtube)"
  } 2>&1)"

  assert_eq "5" "$(ssh_call_count "${dir}")" "YouTube guided flow times out without dismissing an unexpected dialog" || return 1
  assert_not_contains "${output}" "input-executeaction" "YouTube guided flow must not dismiss the wrong dialog" || return 1
  assert_contains "${output}" "service.plugin.video.youtube.failure=timeout" "YouTube guided flow reports a bounded guided timeout" || return 1
  assert_contains "${output}" "workflow_status=manual-required" "YouTube guided flow fails closed on an unexpected dialog" || return 1
}

test_guided_flow_times_out_as_manual_required() {
  local dir bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  set_guided_flow_pins
  write_addon_details_response "${dir}/stub/response-1.json" "plugin.video.youtube" "7.4.4"
  printf '%s\n' '{}' > "${dir}/stub/response-2.json"
  printf '%s\n' '{"jsonrpc":"2.0","id":"gui-activatewindow","result":"OK"}' > "${dir}/stub/response-3.json"
  write_gui_state_response "${dir}/stub/response-4.json" \
    "Please sign in and complete all access authorisation prompts" "OK"
  printf '%s\n' '{"jsonrpc":"2.0","id":"input-executeaction","result":"OK"}' > "${dir}/stub/response-5.json"
  printf '%s\n' '{}' > "${dir}/stub/response-6.json"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    export COREELEC_GUIDED_FLOW_TIMEOUT_SECONDS="0"
    export COREELEC_GUIDED_FLOW_POLL_INTERVAL_SECONDS="0"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    printf 'workflow_status=%s\n' "$(authorize_youtube)"
  } 2>&1)"

  assert_contains "${output}" "service.plugin.video.youtube.account_token_present=0" "guided timeout reports token absence as a boolean" || return 1
  assert_contains "${output}" "service.plugin.video.youtube.failure=timeout" "guided timeout is classified distinctly" || return 1
  assert_contains "${output}" "workflow_status=manual-required" "guided timeout returns manual-required" || return 1
}

test_guided_flow_detects_persisted_tokens_without_printing_them() {
  local dir bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  set_guided_flow_pins
  write_addon_details_response "${dir}/stub/response-1.json" "script.plexmod" "1.14.1-beta1"
  printf '%s\n' '<settings><setting id="auth.token">pm4k-account-token-secret</setting></settings>' \
    > "${dir}/stub/response-2.json"
  write_addon_details_response "${dir}/stub/response-3.json" "plugin.video.youtube" "7.4.4"
  cat > "${dir}/stub/response-4.json" <<'JSON'
{"access_manager":{"users":{"0":{"access_token":"youtube-access-token-secret","refresh_token":"youtube-refresh-token-secret","token_expires":9999999999}},"current_user":0,"last_origin":"plugin.video.youtube","developers":{}}}
JSON

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    INTERACTIVE="1"
    printf 'pm4k_status=%s\n' "$(run_addon_workflow script.plexmod)"
    printf 'youtube_status=%s\n' "$(run_addon_workflow plugin.video.youtube)"
  } 2>&1)"

  assert_eq "4" "$(ssh_call_count "${dir}")" "persisted-token detection stops before launch when already configured" || return 1
  assert_contains "${output}" "pm4k_status=already-configured" "PM4K account flow detects an existing token" || return 1
  assert_contains "${output}" "youtube_status=already-configured" "YouTube guided flow detects an existing token" || return 1
  assert_not_contains "${output}" "pm4k-account-token-secret" "PM4K token must not be printed" || return 1
  assert_not_contains "${output}" "youtube-access-token-secret" "YouTube access token must not be printed" || return 1
  assert_not_contains "${output}" "youtube-refresh-token-secret" "YouTube refresh token must not be printed" || return 1
}

test_guided_flow_refuses_addon_version_mismatch_before_private_steps() {
  local dir bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  set_guided_flow_pins
  write_addon_details_response "${dir}/stub/response-1.json" "script.plexmod" "1.14.0"
  write_addon_details_response "${dir}/stub/response-2.json" "plugin.video.youtube" "7.4.3"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${bin_dir}:${PATH}"
    TARGET="coreelec-theater"
    SSH_PORT="22"
    KODI_PORT="8080"
    KODI_USER="homeassistant"
    KODI_WEB_PASSWORD="kodi-web-password-secret"
    INTERACTIVE="1"
    printf 'pm4k_status=%s\n' "$(run_addon_workflow script.plexmod)"
    printf 'youtube_status=%s\n' "$(run_addon_workflow plugin.video.youtube)"
  } 2>&1)"

  assert_eq "2" "$(ssh_call_count "${dir}")" "version mismatches stop before any private state or GUI steps" || return 1
  assert_contains "${output}" "pm4k_status=manual-required" "PM4K version mismatch fails closed" || return 1
  assert_contains "${output}" "youtube_status=manual-required" "YouTube version mismatch fails closed" || return 1
  assert_contains "${output}" "service.script.plexmod.failure=version-mismatch" "PM4K mismatch is classified explicitly" || return 1
  assert_contains "${output}" "service.plugin.video.youtube.failure=version-mismatch" "YouTube mismatch is classified explicitly" || return 1
}

test_emby_password_never_appears_in_argv_log_or_report() {
  local dir bin_dir python_bin_dir config report_dir report output argv_logs secret
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_ssh_stub "${dir}")"
  python_bin_dir="$(install_python3_argv_stub "${dir}")"
  config="${dir}/provision.conf"
  report_dir="${dir}/reports"
  secret="emby-password-secret"
  write_config "${config}" plugin.service.emby-next-gen
  cat >> "${config}" <<'CONFIG'
EMBY_SERVER_URL=https://emby.example.test
EMBY_USERNAME=media-user
CONFIG

  write_introspection_response "${dir}/stub/response-1.json"
  write_addon_details_response "${dir}/stub/response-2.json" "plugin.service.emby-next-gen" "12.4.23"
  printf 'absent\n' > "${dir}/stub/response-3.json"
  write_gui_state_response "${dir}/stub/response-4.json" "Select main server" "Manually add server"
  printf '%s\n' '{"jsonrpc":"2.0","id":"input-executeaction","result":"OK"}' > "${dir}/stub/response-5.json"
  write_gui_state_response "${dir}/stub/response-6.json" "Manage servers" "Host"
  write_gui_state_response "${dir}/stub/response-7.json" "Manage servers" "Host"
  printf '%s\n' '{"jsonrpc":"2.0","id":"input-sendtext","result":"OK"}' > "${dir}/stub/response-8.json"
  write_gui_state_response "${dir}/stub/response-9.json" "Please sign in" "Username"
  write_gui_state_response "${dir}/stub/response-10.json" "Please sign in" "Username"
  printf '%s\n' '{"jsonrpc":"2.0","id":"input-sendtext","result":"OK"}' > "${dir}/stub/response-11.json"
  write_gui_state_response "${dir}/stub/response-12.json" "Please sign in" "Password"
  write_gui_state_response "${dir}/stub/response-13.json" "Please sign in" "Password"
  printf '%s\n' '{"jsonrpc":"2.0","id":"input-sendtext","result":"OK"}' > "${dir}/stub/response-14.json"
  write_gui_state_response "${dir}/stub/response-15.json" "Please sign in" "Sign in"
  printf '%s\n' '{"jsonrpc":"2.0","id":"input-executeaction","result":"OK"}' > "${dir}/stub/response-16.json"
  printf 'configured\n' > "${dir}/stub/response-17.json"

  output="$({
    export COREELEC_SSH_STUB_DIR="${dir}/stub"
    export PATH="${python_bin_dir}:${bin_dir}:${PATH}"
    COREELEC_GUIDED_FLOW_POLL_INTERVAL_SECONDS="0" \
    KODI_WEB_PASSWORD="kodi-web-password-secret" \
    EMBY_PASSWORD="${secret}" \
      bash "${CLI_SCRIPT}" \
        --config "${config}" \
        --target coreelec-theater \
        --interactive \
        --addon plugin.service.emby-next-gen \
        --report-dir "${report_dir}"
  } 2>&1)"

  report="$(find_single_report "${report_dir}")"
  argv_logs="$(cat "${dir}"/stub/argv-*.log; python3_argv_logs "${dir}")"
  assert_contains "$(cat "${report}")" "addon.plugin.service.emby-next-gen.status=configured" \
    "successful Emby assistance is reported" || return 1
  assert_not_contains "${output}" "${secret}" "Emby password must not appear in output" || return 1
  assert_not_contains "${argv_logs}" "${secret}" "Emby password must not appear in process arguments" || return 1
  assert_not_contains "$(cat "${report}")" "${secret}" "Emby password must not appear in the report"
}

test_emby_assistant_stops_on_each_unexpected_dialog() {
  local dir phase output sent
  for phase in server url username password; do
    dir="$(make_scratch_dir)"
    : > "${dir}/methods.log"
    cat > "${dir}/scenario.sh" <<EOF
#!/bin/bash
set -Eeuo pipefail
source "${WORKFLOW_LIB}"
EMBY_SERVER_URL="https://emby.example.test"
EMBY_USERNAME="media-user"
LOCALE_LANGUAGE="resource.language.en_us"
ADDON_ARTIFACTS=("$(addon_record plugin.service.emby-next-gen)")
gui_calls=0
coreelec_postdeploy_addon_version() { printf '12.4.23\n'; }
coreelec_postdeploy_emby_state() { printf 'absent\n'; }
capture_gui_state() {
  gui_calls=\$((gui_calls + 1))
  case "\${EMBY_TEST_PHASE}:\${gui_calls}" in
    server:1) KODI_GUI_WINDOW_LABEL="Unexpected"; KODI_GUI_CONTROL_LABEL="Unknown" ;;
    url:1) KODI_GUI_WINDOW_LABEL="Select main server"; KODI_GUI_CONTROL_LABEL="Manually add server" ;;
    url:2) KODI_GUI_WINDOW_LABEL="Unexpected"; KODI_GUI_CONTROL_LABEL="Unknown" ;;
    username:1) KODI_GUI_WINDOW_LABEL="Select main server"; KODI_GUI_CONTROL_LABEL="Manually add server" ;;
    username:2|username:3) KODI_GUI_WINDOW_LABEL="Manage servers"; KODI_GUI_CONTROL_LABEL="Host" ;;
    username:4) KODI_GUI_WINDOW_LABEL="Unexpected"; KODI_GUI_CONTROL_LABEL="Unknown" ;;
    password:1) KODI_GUI_WINDOW_LABEL="Select main server"; KODI_GUI_CONTROL_LABEL="Manually add server" ;;
    password:2|password:3) KODI_GUI_WINDOW_LABEL="Manage servers"; KODI_GUI_CONTROL_LABEL="Host" ;;
    password:4|password:5) KODI_GUI_WINDOW_LABEL="Please sign in"; KODI_GUI_CONTROL_LABEL="Username" ;;
    password:6) KODI_GUI_WINDOW_LABEL="Unexpected"; KODI_GUI_CONTROL_LABEL="Unknown" ;;
  esac
}
kodi_rpc() {
  printf '%s\n' "\$1" >> "${dir}/methods.log"
  printf '%s\n' '{"jsonrpc":"2.0","id":"test","result":"OK"}'
}
coreelec_postdeploy_guided_select() {
  printf '%s\n' "Input.ExecuteAction" >> "${dir}/methods.log"
}
printf 'workflow_status=%s\n' "\$(assist_emby_login)"
EOF
    output="$(EMBY_TEST_PHASE="${phase}" EMBY_PASSWORD="emby-password-secret" \
      bash "${dir}/scenario.sh" 2>&1)"
    sent="$(grep -c '^Input.SendText$' "${dir}/methods.log" || true)"
    case "${phase}" in
      server|url) assert_eq "0" "${sent}" "${phase} drift stops before any text submission" || return 1 ;;
      username) assert_eq "1" "${sent}" "username drift stops after only the URL submission" || return 1 ;;
      password) assert_eq "2" "${sent}" "password drift stops after URL and username submissions" || return 1 ;;
    esac
    assert_contains "${output}" "workflow_status=manual-required" "${phase} drift fails closed" || return 1
    assert_contains "${output}" "service.plugin.service.emby-next-gen.failure=unexpected-dialog" \
      "${phase} drift is classified explicitly" || return 1
    rm -rf -- "${dir}"
  done
}

run_all_tests \
  test_help_lists_supported_addons_and_interaction_levels \
  test_dry_run_makes_zero_ssh_calls \
  test_interactive_dry_run_makes_zero_ssh_calls \
  test_report_creation_uses_private_umask_before_chmod \
  test_default_run_never_starts_account_authorization \
  test_requested_addon_must_be_in_the_pinned_manifest \
  test_introspection_rejects_a_missing_required_method \
  test_introspection_requires_addons_getaddondetails \
  test_every_remote_script_is_one_ssh_argument \
  test_ssh_transport_matches_provisioner_hardening \
  test_addon_data_reader_keeps_path_values_out_of_remote_command \
  test_gui_guard_accepts_expected_window_and_control \
  test_gui_guard_rejects_an_unexpected_window_without_sending_input \
  test_rpc_request_ids_never_contain_secret_values \
  test_report_contains_statuses_but_no_secret_values \
  test_weather_check_accepts_config_and_entity_responses \
  test_weather_check_reports_unauthorized_without_echoing_token \
  test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin \
  test_nextpvr_check_requires_a_successful_session_login \
  test_pm4k_local_check_requires_identity_and_token_authorized_root \
  test_pm4k_local_check_skips_when_local_configuration_is_absent \
  test_service_checks_do_not_modify_addon_settings \
  test_pm4k_launch_uses_addons_executeaddon \
  test_pm4k_selects_sign_in_only_when_expected_control_is_focused \
  test_youtube_launch_uses_the_pinned_sign_in_plugin_route \
  test_youtube_dismisses_only_the_expected_intro_dialog \
  test_guided_flow_times_out_as_manual_required \
  test_guided_flow_detects_persisted_tokens_without_printing_them \
  test_guided_flow_refuses_addon_version_mismatch_before_private_steps \
  test_emby_password_never_appears_in_argv_log_or_report \
  test_emby_assistant_stops_on_each_unexpected_dialog
