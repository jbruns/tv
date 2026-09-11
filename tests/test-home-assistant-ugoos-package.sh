#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"

PACKAGE_FILE="${SCRIPT_DIR}/../home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml"
SSH_CONFIG_FILE="${SCRIPT_DIR}/../home-assistant/ssh/ugoos-kodi-lifecycle.conf.example"

package_fixture() {
  python3 -B "${SCRIPT_DIR}/home-assistant-ugoos-fixture.py" "${PACKAGE_FILE}" "$1"
}

test_real_kodi_result_envelope_establishes_idle_evidence() {
  package_fixture idle_event_envelope
}

test_failed_or_mismatched_kodi_events_cannot_prove_idle() {
  package_fixture idle_event_failed_or_mismatched
}

test_queued_reconciliation_uses_current_desired_state() {
  package_fixture queued_reconciliation_current_state
}

test_reconciliation_computes_desired_state_after_status() {
  package_fixture reconciliation_rechecks_after_status
}

test_stop_rechecks_live_eligibility_after_bookkeeping() {
  package_fixture stop_eligibility_rechecked
}

test_host_and_service_recovery_start_fresh_off_observation() {
  package_fixture recovery_starts_fresh_observation
}

test_start_and_reload_invalidate_queued_off_intervals() {
  package_fixture reload_starts_fresh_observation
}

test_kodi_availability_recovery_reconciles_with_a_fresh_epoch() {
  package_fixture kodi_recovery_starts_fresh_observation
}

test_fresh_observation_epoch_blocks_old_idle_duration() {
  package_fixture fresh_epoch_blocks_old_idle_episode
}

test_sony_timeout_is_once_per_idle_episode() {
  package_fixture sony_failure_is_once_per_idle_episode
}

test_sony_action_exception_reaches_bounded_failure_notification() {
  package_fixture sony_action_exception_is_not_silent
}

test_stale_or_failed_idle_evidence_does_not_rearm_sony() {
  package_fixture stale_idle_evidence_does_not_rearm_sony
}

test_failed_sony_episode_latch_survives_ha_restart() {
  package_fixture failed_sony_latch_survives_restart
}

test_status_poll_does_not_claim_reconciliation_or_clear_start_error() {
  package_fixture status_observation_does_not_claim_reconciliation
}

test_running_service_still_requires_kodi_readiness() {
  package_fixture already_running_still_requires_readiness
}

test_reconciliation_checks_service_after_readiness_wait() {
  package_fixture reconciliation_rechecks_status_after_readiness
}

test_operation_errors_clear_only_after_matching_convergence() {
  package_fixture operation_errors_clear_only_on_matching_convergence
}

test_reachable_stale_probe_notifies_and_valid_probe_recovers() {
  package_fixture reachable_stale_probe_is_reported
}

test_stale_probe_is_quiet_while_unreachable_or_in_a_new_epoch() {
  package_fixture stale_probe_unreachable_and_fresh_epoch_are_quiet
}

test_valid_probe_clears_only_its_own_error() {
  package_fixture valid_probe_clears_only_its_own_error
}

test_stderr_filter_redacts_actual_identity_and_known_host_paths() {
  package_fixture stderr_paths_are_actually_redacted
}

test_shell_action_exceptions_reach_lifecycle_error_handling() {
  package_fixture shell_action_exception_is_reported
}

test_malformed_poll_preserves_host_reachability_without_inventing_service_state() {
  package_fixture malformed_poll_preserves_reachable_host
}

test_missing_entities_notify_and_configured_unknown_sony_fails_awake() {
  package_fixture missing_entities_are_reported_without_rejecting_unknown_states
}

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

assert_file_exists() {
  local file="$1"
  if [[ ! -f "${file}" ]]; then
    printf 'missing required file: %s\n' "${file}" >&2
    return 1
  fi
}

assert_occurrences() {
  local body="$1" needle="$2" expected="$3" message="${4:-unexpected occurrence count}"
  local actual
  actual="$(printf '%s\n' "${body}" | grep -F -- "${needle}" | wc -l | tr -d ' ')"
  assert_eq "${expected}" "${actual}" "${message}"
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
  package_fixture static_ssh_deadline_boundary
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
  package_fixture unknown_sony_policy
}

test_sony_off_requires_sixty_continuous_seconds() {
  package_fixture sony_off_interval_and_cancel
}

test_keep_running_and_policy_opt_out_precede_sony_off() {
  package_fixture policy_override_precedence
}

test_reconciler_policy_matches_desired_state_sensor() {
  package_fixture policy_sensor_and_reconciler_matrix
}

test_idle_requires_kodi_idle_duration_and_fresh_input_idle() {
  package_fixture idle_poweroff_gates
}

test_playing_and_paused_do_not_trigger_idle_poweroff() {
  package_fixture idle_poweroff_gates
}

test_idle_probe_calls_exact_kodi_boolean() {
  package_fixture idle_probe_request
}

test_start_readiness_rejects_unknown_kodi_state() {
  package_fixture already_running_still_requires_readiness
}

test_idle_evidence_expires_after_thirty_seconds() {
  package_fixture freshness_boundary
}

test_idle_powers_off_sony_before_normal_kodi_stop_flow() {
  package_fixture sony_off_precedes_normal_kodi_stop
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
  package_fixture shell_action_exception_is_reported
}

test_failed_lifecycle_state_is_recorded_without_marking_host_unreachable() {
  package_fixture failed_service_is_reachable_and_notifies
}

run_all_tests \
  test_shell_action_exceptions_reach_lifecycle_error_handling \
  test_malformed_poll_preserves_host_reachability_without_inventing_service_state \
  test_missing_entities_notify_and_configured_unknown_sony_fails_awake \
  test_status_poll_does_not_claim_reconciliation_or_clear_start_error \
  test_running_service_still_requires_kodi_readiness \
  test_reconciliation_checks_service_after_readiness_wait \
  test_operation_errors_clear_only_after_matching_convergence \
  test_reachable_stale_probe_notifies_and_valid_probe_recovers \
  test_stale_probe_is_quiet_while_unreachable_or_in_a_new_epoch \
  test_valid_probe_clears_only_its_own_error \
  test_stderr_filter_redacts_actual_identity_and_known_host_paths \
  test_sony_timeout_is_once_per_idle_episode \
  test_sony_action_exception_reaches_bounded_failure_notification \
  test_stale_or_failed_idle_evidence_does_not_rearm_sony \
  test_failed_sony_episode_latch_survives_ha_restart \
  test_fresh_observation_epoch_blocks_old_idle_duration \
  test_host_and_service_recovery_start_fresh_off_observation \
  test_start_and_reload_invalidate_queued_off_intervals \
  test_kodi_availability_recovery_reconciles_with_a_fresh_epoch \
  test_queued_reconciliation_uses_current_desired_state \
  test_reconciliation_computes_desired_state_after_status \
  test_stop_rechecks_live_eligibility_after_bookkeeping \
  test_real_kodi_result_envelope_establishes_idle_evidence \
  test_failed_or_mismatched_kodi_events_cannot_prove_idle \
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
