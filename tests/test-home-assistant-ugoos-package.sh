#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"

PACKAGE_FILE="${SCRIPT_DIR}/../home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml"
SSH_CONFIG_FILE="${SCRIPT_DIR}/../home-assistant/ssh/ugoos-kodi-lifecycle.conf.example"

package_body() {
  cat "${PACKAGE_FILE}"
}

ssh_config_body() {
  cat "${SSH_CONFIG_FILE}"
}

section_text() {
  local section="$1" file="$2"
  awk -v section="${section}" '
    $0 == section ":" { in_section = 1; print; next }
    in_section && /^[[:alnum:]_]+:/ { exit }
    in_section { print }
  ' "${file}"
}

entity_block() {
  local file="$1" entity="$2"
  awk -v entity="${entity}" '
    $0 == "  " entity ":" { in_block = 1; print; next }
    in_block && /^  [[:alnum:]_]+:/ { exit }
    in_block { print }
  ' "${file}"
}

id_block() {
  local file="$1" id="$2"
  awk -v id="${id}" '
    $0 == "  - id: " id { in_block = 1; print; next }
    in_block && /^  - id: / { exit }
    in_block { print }
  ' "${file}"
}

assert_file_exists() {
  local file="$1"
  if [[ ! -f "${file}" ]]; then
    printf 'missing required file: %s\n' "${file}" >&2
    return 1
  fi
}

assert_line_order() {
  local body="$1" first="$2" second="$3" message="${4:-expected text order}"
  local first_line second_line
  first_line="$(printf '%s\n' "${body}" | grep -nF -- "${first}" | head -1 | cut -d: -f1 || true)"
  second_line="$(printf '%s\n' "${body}" | grep -nF -- "${second}" | head -1 | cut -d: -f1 || true)"
  if [[ -z "${first_line}" || -z "${second_line}" || "${first_line}" -ge "${second_line}" ]]; then
    printf 'assert_line_order: %s (first=%q line=%s second=%q line=%s)\n' \
      "${message}" "${first}" "${first_line}" "${second}" "${second_line}" >&2
    return 1
  fi
}

assert_occurrences() {
  local body="$1" needle="$2" expected="$3" message="${4:-unexpected occurrence count}"
  local actual
  actual="$(printf '%s\n' "${body}" | grep -F -- "${needle}" | wc -l | tr -d ' ')"
  assert_eq "${expected}" "${actual}" "${message}"
}

assert_literal_contains() {
  local haystack="$1" needle="$2" message="${3:-expected literal substring not found}"
  if ! printf '%s\n' "${haystack}" | grep -Fq -- "${needle}"; then
    printf 'assert_literal_contains: %s (needle=%q)\n' "${message}" "${needle}" >&2
    return 1
  fi
}

desired_kodi_state() {
  local policy="$1" keep="$2" sony="$3" off_seconds="$4"
  if [[ "${policy}" != "on" || "${keep}" == "on" ]]; then
    printf 'running\n'
  elif [[ "${sony}" == "off" && "${off_seconds}" -ge 60 ]]; then
    printf 'stopped\n'
  else
    printf 'running\n'
  fi
}

assert_policy_precedence_fixture() {
  assert_eq "running" "$(desired_kodi_state off off off 120)" "policy opt-out keeps Kodi running"
  assert_eq "running" "$(desired_kodi_state on on off 120)" "keep-running override keeps Kodi running"
  assert_eq "running" "$(desired_kodi_state on off off 59)" "Sony off before sixty seconds keeps Kodi running"
  assert_eq "stopped" "$(desired_kodi_state on off off 60)" "Sony off at sixty seconds stops Kodi"
  assert_eq "running" "$(desired_kodi_state on off unknown 120)" "unknown Sony state keeps Kodi running"
  assert_eq "running" "$(desired_kodi_state on off unavailable 120)" "unavailable Sony state keeps Kodi running"
  assert_eq "running" "$(desired_kodi_state on off playing 120)" "non-off Sony state keeps Kodi running"
}

assert_ordered_policy_template() {
  local body="$1"
  if ! printf '%s\n' "${body}" | grep -Fq "{% set stop_when_display_off = true %}" \
    && ! printf '%s\n' "${body}" | grep -Fq "stop_when_display_off: true"; then
    printf 'policy literal must be present in Jinja or YAML variable form\n' >&2
    return 1
  fi
  assert_contains "${body}" "{% set sony_off_seconds =" "Sony off duration must be computed"
  assert_contains "${body}" "{% if not stop_when_display_off %}" "policy opt-out condition"
  assert_contains "${body}" "{% elif is_state('input_boolean.ugoos_theater_keep_kodi_running', 'on') %}" "keep-running condition"
  assert_contains "${body}" "{% elif is_state('media_player.sony_xr_65a90j', 'off') and sony_off_seconds >= 60 %}" "Sony off condition requires sixty continuous seconds"
  assert_contains "${body}" "{% else %}" "running fallback for unknown/unavailable/non-off Sony"
  assert_line_order "${body}" "{% if not stop_when_display_off %}" "{% elif is_state('input_boolean.ugoos_theater_keep_kodi_running', 'on') %}" \
    "policy opt-out precedes keep-running"
  assert_line_order "${body}" "{% elif is_state('input_boolean.ugoos_theater_keep_kodi_running', 'on') %}" "{% elif is_state('media_player.sony_xr_65a90j', 'off') and sony_off_seconds >= 60 %}" \
    "keep-running precedes Sony off"
  assert_line_order "${body}" "{% elif is_state('media_player.sony_xr_65a90j', 'off') and sony_off_seconds >= 60 %}" "{% else %}" \
    "Sony off precedes running fallback"
}

test_package_uses_expected_theater_entities_and_host() {
  assert_file_exists "${PACKAGE_FILE}"
  assert_file_exists "${SSH_CONFIG_FILE}"
  local body
  body="$(package_body)"
  for expected in \
    "media_player.sony_xr_65a90j" \
    "media_player.kodi_theater" \
    "ugoos-theater" \
    "/config/.ssh/ugoos_kodi_lifecycle_ed25519" \
    "/config/.ssh/known_hosts" \
    "input_boolean.ugoos_theater_keep_kodi_running" \
    "input_boolean.ugoos_theater_idle_poweroff_sent" \
    "input_boolean.ugoos_theater_input_idle" \
    "input_datetime.ugoos_theater_idle_probe_updated" \
    "input_text.ugoos_theater_kodi_lifecycle_state" \
    "input_number.ugoos_theater_idle_timeout_minutes" \
    "input_boolean.ugoos_theater_host_reachable" \
    "input_text.ugoos_theater_last_lifecycle_command" \
    "input_datetime.ugoos_theater_last_reconciliation" \
    "input_text.ugoos_theater_last_lifecycle_error" \
    "default_entity_id: sensor.ugoos_theater_desired_kodi_state" \
    "sensor.ugoos_theater_desired_kodi_state"; do
    assert_contains "${body}" "${expected}" "package references ${expected}"
  done
}

test_package_defaults_keep_running_override_to_off() {
  assert_file_exists "${PACKAGE_FILE}"
  local block
  block="$(entity_block "${PACKAGE_FILE}" "ugoos_theater_keep_kodi_running")"
  assert_contains "${block}" "name: Theater - Keep Kodi running" "keep-running helper name"
  assert_not_contains "${block}" "initial:" "keep-running must restore state and default off when newly created"
}

test_package_defaults_idle_timeout_to_thirty_minutes() {
  assert_file_exists "${PACKAGE_FILE}"
  local block
  block="$(entity_block "${PACKAGE_FILE}" "ugoos_theater_idle_timeout_minutes")"
  assert_contains "${block}" "name: Theater - Kodi idle timeout" "idle timeout helper name"
  for expected in "min: 5" "max: 120" "step: 5" "unit_of_measurement: min" "mode: box" "initial: 30"; do
    assert_contains "${block}" "${expected}" "idle timeout includes ${expected}"
  done
}

test_package_contains_only_static_start_stop_status_ssh_commands() {
  assert_file_exists "${PACKAGE_FILE}"
  local shell_section command_count
  shell_section="$(section_text shell_command "${PACKAGE_FILE}")"
  assert_contains "${shell_section}" "ugoos_theater_kodi_start: >-" "start shell command"
  assert_contains "${shell_section}" "ugoos_theater_kodi_stop: >-" "stop shell command"
  assert_contains "${shell_section}" "ugoos_theater_kodi_status: >-" "status shell command"
  assert_contains "${shell_section}" "ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf" "static SSH config path"
  assert_contains "${shell_section}" "ugoos-theater-lifecycle start" "exact start command"
  assert_contains "${shell_section}" "ugoos-theater-lifecycle stop" "exact stop command"
  assert_contains "${shell_section}" "ugoos-theater-lifecycle status" "exact status command"
  assert_not_contains "${shell_section}" "{{" "shell commands must not be templated"
  command_count="$(printf '%s\n' "${shell_section}" | grep -E '^  ugoos_theater_kodi_(start|stop|status):' | wc -l | tr -d ' ')"
  assert_eq "3" "${command_count}" "only start/stop/status lifecycle shell commands"
}

test_ssh_commands_have_total_fifteen_second_deadline() {
  assert_file_exists "${PACKAGE_FILE}"
  local shell_section
  shell_section="$(section_text shell_command "${PACKAGE_FILE}")"
  assert_occurrences "${shell_section}" "timeout 15s ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf" "3" \
    "each restricted SSH command must have a total 15-second deadline"
  assert_line_order "${shell_section}" "timeout 15s ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf" "ugoos-theater-lifecycle start" \
    "start timeout wraps SSH before remote command"
}

test_ssh_commands_require_batch_mode_strict_host_key_and_persistent_paths() {
  assert_file_exists "${SSH_CONFIG_FILE}"
  local body
  body="$(ssh_config_body)"
  for expected in \
    "Host ugoos-theater-lifecycle" \
    "HostName ugoos-theater" \
    "User root" \
    "Port 22" \
    "IdentityFile /config/.ssh/ugoos_kodi_lifecycle_ed25519" \
    "UserKnownHostsFile /config/.ssh/known_hosts" \
    "IdentitiesOnly yes" \
    "BatchMode yes" \
    "StrictHostKeyChecking yes" \
    "ConnectTimeout 12" \
    "ConnectionAttempts 1" \
    "RequestTTY no" \
    "ClearAllForwardings yes"; do
    assert_contains "${body}" "${expected}" "SSH config includes ${expected}"
  done
}

test_unknown_and_unavailable_sony_states_demand_running() {
  assert_policy_precedence_fixture
  local body sensor_section reconcile_script
  body="$(package_body)"
  sensor_section="$(section_text template "${PACKAGE_FILE}")"
  reconcile_script="$(entity_block "${PACKAGE_FILE}" "ugoos_theater_reconcile_kodi")"
  assert_ordered_policy_template "${sensor_section}"
  assert_ordered_policy_template "${reconcile_script}"
  assert_contains "${body}" "not_to: \"off\"" "non-off, unknown, and unavailable Sony states trigger start/reconcile"
}

test_sony_off_requires_sixty_continuous_seconds() {
  assert_file_exists "${PACKAGE_FILE}"
  assert_policy_precedence_fixture
  local body sensor_section reconcile_script
  body="$(package_body)"
  sensor_section="$(section_text template "${PACKAGE_FILE}")"
  reconcile_script="$(entity_block "${PACKAGE_FILE}" "ugoos_theater_reconcile_kodi")"
  assert_contains "${body}" "to: \"off\"" "Sony off trigger exists"
  assert_occurrences "${body}" "for: \"00:01:00\"" "1" "state trigger uses exactly one continuous 60-second off interval"
  assert_contains "${body}" "delay: \"00:01:00\"" "startup off path waits a fresh 60 seconds"
  assert_contains "${sensor_section}" "sony_off_seconds >= 60" "desired sensor exposes 60-second stop threshold"
  assert_contains "${reconcile_script}" "sony_off_seconds >= 60" "reconciler enforces 60-second stop threshold"
}

test_keep_running_and_policy_opt_out_precede_sony_off() {
  assert_file_exists "${PACKAGE_FILE}"
  local sensor_section reconcile_script
  sensor_section="$(section_text template "${PACKAGE_FILE}")"
  reconcile_script="$(entity_block "${PACKAGE_FILE}" "ugoos_theater_reconcile_kodi")"
  body="$(package_body)"
  assert_policy_precedence_fixture
  assert_ordered_policy_template "${sensor_section}"
  assert_ordered_policy_template "${reconcile_script}"
}

test_reconciler_policy_matches_desired_state_sensor() {
  assert_file_exists "${PACKAGE_FILE}"
  local sensor_section reconcile_script
  sensor_section="$(section_text template "${PACKAGE_FILE}")"
  reconcile_script="$(entity_block "${PACKAGE_FILE}" "ugoos_theater_reconcile_kodi")"
  for expected in \
    "{% set sony_off_seconds =" \
    "{% if not stop_when_display_off %}" \
    "{% elif is_state('input_boolean.ugoos_theater_keep_kodi_running', 'on') %}" \
    "{% elif is_state('media_player.sony_xr_65a90j', 'off') and sony_off_seconds >= 60 %}" \
    "{% else %}"; do
    assert_contains "${sensor_section}" "${expected}" "sensor contains policy line ${expected}"
    assert_contains "${reconcile_script}" "${expected}" "reconciler contains policy line ${expected}"
  done
  assert_contains "${sensor_section}" "{% set stop_when_display_off = true %}" "sensor contains policy literal"
  assert_contains "${reconcile_script}" "stop_when_display_off: true" "reconciler contains policy literal"
}

test_idle_requires_kodi_idle_duration_and_fresh_input_idle() {
  assert_file_exists "${PACKAGE_FILE}"
  local body
  body="$(package_body)"
  assert_contains "${body}" "is_state('media_player.kodi_theater', 'idle')" "HA Kodi idle state required"
  assert_contains "${body}" "states.media_player.kodi_theater.last_changed" "continuous Kodi idle duration required"
  assert_contains "${body}" "is_state('input_boolean.ugoos_theater_input_idle', 'on')" "Kodi input-idle evidence required"
  assert_contains "${body}" "states('input_datetime.ugoos_theater_idle_probe_updated')" "fresh idle evidence timestamp required"
  assert_contains "${body}" "<= 30" "idle evidence freshness threshold"
  assert_contains "${body}" "is_state('input_boolean.ugoos_theater_idle_poweroff_sent', 'off')" "duplicate Sony power-off guard"
}

test_playing_and_paused_do_not_trigger_idle_poweroff() {
  assert_file_exists "${PACKAGE_FILE}"
  local body
  body="$(package_body)"
  assert_contains "${body}" "is_state('media_player.kodi_theater', 'idle')" "idle power-off requires exact idle state"
  assert_not_contains "${body}" "is_state('media_player.kodi_theater', 'playing')" "playing must not trigger idle power-off"
  assert_not_contains "${body}" "is_state('media_player.kodi_theater', 'paused')" "paused must not trigger idle power-off"
}

test_idle_probe_calls_exact_kodi_boolean() {
  assert_file_exists "${PACKAGE_FILE}"
  local body
  body="$(package_body)"
  assert_contains "${body}" "action: kodi.call_method" "Kodi method call action"
  assert_contains "${body}" "entity_id: media_player.kodi_theater" "Kodi entity target"
  assert_contains "${body}" "method: XBMC.GetInfoBooleans" "exact Kodi JSON-RPC method"
  assert_contains "${body}" "System.IdleTime({{" "exact idle boolean prefix"
  assert_contains "${body}" "states('input_number.ugoos_theater_idle_timeout_minutes') | int(30)" "idle timeout helper drives boolean"
  assert_contains "${body}" "* 60" "idle timeout converted to seconds"
  assert_contains "${body}" "event_type: kodi_call_method_result" "Kodi call result event consumed"
  assert_contains "${body}" "trigger.event.data.method == 'XBMC.GetInfoBooleans'" "event method match required"
  assert_contains "${body}" "trigger.event.data.booleans == [expected_boolean]" "event boolean list exact match required"
}

test_start_readiness_rejects_unknown_kodi_state() {
  assert_file_exists "${PACKAGE_FILE}"
  local reconcile_script
  reconcile_script="$(entity_block "${PACKAGE_FILE}" "ugoos_theater_reconcile_kodi")"
  assert_contains "${reconcile_script}" "wait_template: \"{{ states('media_player.kodi_theater') not in ['off', 'unknown', 'unavailable'] }}\"" \
    "start readiness must wait for Kodi to leave off, unknown, and unavailable"
}

test_idle_evidence_expires_after_thirty_seconds() {
  assert_file_exists "${PACKAGE_FILE}"
  local body
  body="$(package_body)"
  assert_contains "${body}" "seconds: \"/15\"" "15-second cadence present"
  assert_contains "${body}" "> 30" "stale idle evidence threshold"
  assert_contains "${body}" "action: input_boolean.turn_off" "stale evidence clears input-idle helper"
  assert_contains "${body}" "input_boolean.ugoos_theater_input_idle" "input-idle helper is cleared"
}

test_idle_powers_off_sony_before_normal_kodi_stop_flow() {
  assert_file_exists "${PACKAGE_FILE}"
  local body idle_script sent_line sony_line
  body="$(package_body)"
  idle_script="$(entity_block "${PACKAGE_FILE}" "ugoos_theater_power_off_idle_sony")"
  sent_line="$(printf '%s\n' "${idle_script}" | grep -nF "entity_id: input_boolean.ugoos_theater_idle_poweroff_sent" | head -1 | cut -d: -f1 || true)"
  sony_line="$(printf '%s\n' "${idle_script}" | grep -nF "action: media_player.turn_off" | head -1 | cut -d: -f1 || true)"
  if [[ -z "${sent_line}" || -z "${sony_line}" || "${sent_line}" -ge "${sony_line}" ]]; then
    printf 'idle power-off must set sent helper before Sony turn_off\n' >&2
    return 1
  fi
  assert_contains "${idle_script}" "wait_template: \"{{ is_state('media_player.sony_xr_65a90j', 'off') }}\"" "wait for Sony off"
  assert_contains "${idle_script}" "timeout: \"00:00:30\"" "Sony off confirmation timeout"
  assert_not_contains "${idle_script}" "shell_command.ugoos_theater_kodi_stop" "idle flow must leave Kodi stop to Sony-off reconciliation"
}

test_package_has_no_suspend_shutdown_reboot_wol_or_toggle_command() {
  assert_file_exists "${PACKAGE_FILE}"
  local body lowered
  body="$(package_body)"
  lowered="$(printf '%s\n' "${body}" | tr '[:upper:]' '[:lower:]')"
  for forbidden in suspend shutdown reboot wake_on_lan wol toggle halt; do
    assert_not_contains "${lowered}" "${forbidden}" "package must not contain forbidden command ${forbidden}"
  done
  local shell_section
  shell_section="$(section_text shell_command "${PACKAGE_FILE}")"
  assert_not_contains "${shell_section}" "sh -c" "no arbitrary local shell command"
}

test_errors_create_persistent_notifications() {
  assert_file_exists "${PACKAGE_FILE}"
  local body
  body="$(package_body)"
  assert_contains "${body}" "action: persistent_notification.create" "errors create persistent notifications"
  assert_contains "${body}" "notification_id: ugoos_theater_kodi_lifecycle" "lifecycle notifications are namespaced"
  assert_contains "${body}" "notification_id: ugoos_theater_kodi_idle_poweroff" "idle notifications are namespaced"
  assert_literal_contains "${body}" "regex_replace('/config/\\\\.ssh/[^[:space:]]+', '[ssh-path]')" "stderr is sanitized before notification"
  assert_not_contains "${body}" "IdentityFile /config/.ssh/ugoos_kodi_lifecycle_ed25519" "package notifications must not embed key path"
}

test_failed_lifecycle_state_is_recorded_without_marking_host_unreachable() {
  assert_file_exists "${PACKAGE_FILE}"
  local body poll_block
  body="$(package_body)"
  poll_block="$(id_block "${PACKAGE_FILE}" "ugoos_theater_kodi_status_poll")"
  assert_contains "${body}" "status_stdout == 'failed'" "status failed output has an explicit branch"
  assert_contains "${poll_block}" "poll_stdout in ['running', 'stopped', 'failed']" "status poll treats failed as a reachable lifecycle state"
  assert_contains "${poll_block}" "value: \"{{ poll_stdout }}\"" "status poll records returned lifecycle state"
  assert_line_order "${poll_block}" "poll_stdout in ['running', 'stopped', 'failed']" "action: input_boolean.turn_on" \
    "reachable valid poll output turns host reachable on"
}

run_all_tests \
  test_package_uses_expected_theater_entities_and_host \
  test_package_defaults_keep_running_override_to_off \
  test_package_defaults_idle_timeout_to_thirty_minutes \
  test_package_contains_only_static_start_stop_status_ssh_commands \
  test_ssh_commands_have_total_fifteen_second_deadline \
  test_ssh_commands_require_batch_mode_strict_host_key_and_persistent_paths \
  test_unknown_and_unavailable_sony_states_demand_running \
  test_sony_off_requires_sixty_continuous_seconds \
  test_keep_running_and_policy_opt_out_precede_sony_off \
  test_reconciler_policy_matches_desired_state_sensor \
  test_idle_requires_kodi_idle_duration_and_fresh_input_idle \
  test_playing_and_paused_do_not_trigger_idle_poweroff \
  test_idle_probe_calls_exact_kodi_boolean \
  test_start_readiness_rejects_unknown_kodi_state \
  test_idle_evidence_expires_after_thirty_seconds \
  test_idle_powers_off_sony_before_normal_kodi_stop_flow \
  test_package_has_no_suspend_shutdown_reboot_wol_or_toggle_command \
  test_errors_create_persistent_notifications \
  test_failed_lifecycle_state_is_recorded_without_marking_host_unreachable
