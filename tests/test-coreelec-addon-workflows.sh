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
  local dir="$1" bin_dir="${dir}/stub-bin" stub_dir="${dir}/stub"
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
printf '%s\n' "$*" > "${stub_dir}/argv-${count}.log"
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

ssh_call_count() {
  local dir="$1"
  if [[ -f "${dir}/stub/call-count" ]]; then
    cat "${dir}/stub/call-count"
  else
    printf '0\n'
  fi
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

test_help_lists_supported_addons_and_interaction_levels() {
  local output
  output="$(bash "${CLI_SCRIPT}" --help)"
  assert_contains "${output}" "Supported post-deployment add-ons:" "help lists supported add-ons" || return 1
  assert_contains "${output}" "weather.ha                 fully-unattended" "weather.ha interaction level" || return 1
  assert_contains "${output}" "plugin.video.youtube      guided (--interactive)" "YouTube interaction level" || return 1
  assert_contains "${output}" "plugin.service.emby-next-gen guided (--interactive)" "Emby interaction level" || return 1
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

run_all_tests \
  test_help_lists_supported_addons_and_interaction_levels \
  test_default_run_never_starts_account_authorization \
  test_requested_addon_must_be_in_the_pinned_manifest \
  test_introspection_rejects_a_missing_required_method \
  test_gui_guard_accepts_expected_window_and_control \
  test_gui_guard_rejects_an_unexpected_window_without_sending_input \
  test_rpc_request_ids_never_contain_secret_values \
  test_report_contains_statuses_but_no_secret_values
