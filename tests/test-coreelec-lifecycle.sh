#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"

SSH_LIB="${SCRIPT_DIR}/../lib/coreelec-ssh.sh"
LIFECYCLE_LIB="${SCRIPT_DIR}/../lib/coreelec-lifecycle.sh"

# shellcheck source=lib/coreelec-ssh.sh
source "${SSH_LIB}"
# shellcheck source=lib/coreelec-lifecycle.sh
source "${LIFECYCLE_LIB}"

# --- Fixture helpers ---------------------------------------------------

write_fixture_public_key() {
  local file="$1" blob="${2:-AAAAC3NzaC1lZDI1NTE5AAAAIFixtureKeyBytesForLifecycleTests0000}" comment="${3:-operator@fixture}"
  printf 'ssh-ed25519 %s %s\n' "${blob}" "${comment}" > "${file}"
}

# Renders the wrapper, writes it to an executable file under the scratch
# directory, and prints the absolute path.
render_wrapper_to_file() {
  local dir="$1" systemctl_path="$2" wrapper
  wrapper="${dir}/kodi-lifecycle"
  coreelec_lifecycle_render_wrapper "${systemctl_path}" > "${wrapper}"
  chmod +x "${wrapper}"
  printf '%s\n' "${wrapper}"
}

# Installs a fixture `systemctl` at an absolute path. It records every argv
# word of every call separately (argv-N.log, one word per line, in order),
# tracks unit "active"/"inactive" state across start/stop calls the way the
# real systemd does, and returns configured values for `is-active` and
# `is-failed` so tests can drive every branch of the wrapper.
install_lifecycle_systemctl_fixture() {
  local dir bin_dir
  dir="$1"
  bin_dir="${dir}/systemctl-bin"
  mkdir -p "${bin_dir}" "${dir}/systemctl-config/calls"
  cat > "${bin_dir}/systemctl" <<'STUB'
#!/bin/bash
set -eu
config_dir="${FIXTURE_SYSTEMCTL_CONFIG_DIR:?FIXTURE_SYSTEMCTL_CONFIG_DIR is required}"
calls_dir="${config_dir}/calls"
mkdir -p "${calls_dir}"
count_file="${config_dir}/call-count"
count=0
[[ -f "${count_file}" ]] && count="$(cat "${count_file}")"
count=$((count + 1))
printf '%s\n' "${count}" > "${count_file}"
: > "${calls_dir}/argv-${count}.log"
for argument in "$@"; do
  printf '%s\n' "${argument}" >> "${calls_dir}/argv-${count}.log"
done

state_file="${config_dir}/active-state"
failed_file="${config_dir}/is-failed"
state="inactive"
[[ -f "${state_file}" ]] && state="$(cat "${state_file}")"

subcommand="${1:-}"
quiet="0"
unit=""
shift || true
for argument in "$@"; do
  if [[ "${argument}" == "--quiet" ]]; then
    quiet="1"
  else
    unit="${argument}"
  fi
done

case "${subcommand}" in
  is-active)
    if [[ "${quiet}" == "0" ]]; then
      printf '%s\n' "${state}"
    fi
    [[ "${state}" == "active" ]]
    ;;
  is-failed)
    [[ -f "${failed_file}" ]]
    ;;
  start)
    printf 'active\n' > "${state_file}"
    rm -f "${failed_file}"
    ;;
  stop)
    printf 'inactive\n' > "${state_file}"
    rm -f "${failed_file}"
    ;;
  *)
    exit 0
    ;;
esac
STUB
  chmod +x "${bin_dir}/systemctl"
  printf '%s\n' "${bin_dir}/systemctl"
}

systemctl_call_count() {
  local dir="$1"
  if [[ -f "${dir}/systemctl-config/call-count" ]]; then
    cat "${dir}/systemctl-config/call-count"
  else
    printf '0\n'
  fi
}

systemctl_argv() {
  cat "$1/systemctl-config/calls/argv-$2.log"
}

set_fixture_active_state() {
  printf '%s\n' "$2" > "$1/systemctl-config/active-state"
}

set_fixture_failed() {
  local dir="$1" failed="$2"
  if [[ "${failed}" == "1" ]]; then
    : > "${dir}/systemctl-config/is-failed"
  else
    rm -f "${dir}/systemctl-config/is-failed"
  fi
}

# Counts how many recorded systemctl calls invoked a given subcommand
# ("start" or "stop"), so idempotency can be asserted on the subcommand that
# actually changes unit state, independent of how many read-only is-active /
# is-failed checks the wrapper also performs.
systemctl_subcommand_count() {
  local dir="$1" subcommand="$2" total count=0 index
  total="$(systemctl_call_count "${dir}")"
  for ((index = 1; index <= total; index++)); do
    if [[ "$(head -1 "${dir}/systemctl-config/calls/argv-${index}.log")" == "${subcommand}" ]]; then
      count=$((count + 1))
    fi
  done
  printf '%s\n' "${count}"
}

run_wrapper() {
  local dir="$1" wrapper="$2" ssh_original_command="$3"
  FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    SSH_ORIGINAL_COMMAND="${ssh_original_command}" \
    sh "${wrapper}"
}

# --- Library self-containment test --------------------------------------

# The brief's own setup for this file is "source tests/test-helper.sh and
# lib/coreelec-lifecycle.sh" -- nothing else. This test proves the library
# honors that directly, in a fresh subprocess that never sources
# lib/coreelec-ssh.sh itself, instead of only being exercised through this
# file's own top-of-file sourcing order (which sources coreelec-ssh.sh first
# and would hide a hard dependency on that pre-sourcing).
test_lifecycle_library_sources_cleanly_on_its_own() {
  local output rc
  set +e
  output="$(bash -c '
    set -Eeuo pipefail
    source "'"${LIFECYCLE_LIB}"'"
    declare -F coreelec_public_key_line >/dev/null 2>&1 || exit 1
    declare -F coreelec_lifecycle_render_wrapper >/dev/null 2>&1 || exit 1
    printf "loaded\n"
  ' 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "sourcing only lib/coreelec-lifecycle.sh must succeed: ${output}" || return 1
  assert_eq "loaded" "${output}" \
    "sourcing only lib/coreelec-lifecycle.sh must load its coreelec-ssh.sh dependency automatically"
}

# --- Public key validation and key entry tests --------------------------

test_public_key_validation_accepts_one_ed25519_key() {
  local dir key_file line
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  key_file="${dir}/admin.pub"
  write_fixture_public_key "${key_file}"

  line="$(coreelec_lifecycle_validate_public_key "${key_file}")"
  assert_eq "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixtureKeyBytesForLifecycleTests0000 operator@fixture" \
    "${line}" "a single well-formed ed25519 key is accepted and normalized"
}

test_public_key_validation_rejects_multiple_or_malformed_keys() {
  local dir key_file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  key_file="${dir}/admin.pub"

  {
    printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixtureKeyBytesForLifecycleTests0000 first@fixture\n'
    printf 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISecondFixtureKeyBytesForTests0000000 second@fixture\n'
  } > "${key_file}"
  set +e
  output="$(coreelec_lifecycle_validate_public_key "${key_file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a file with more than one key line must be rejected" || return 1
  assert_contains "${output}" "Expected exactly one public key line" \
    "the multiple-key failure names the shared normalizer's error" || return 1

  printf "evil' \$(touch %s/pwned) key\n" "${dir}" > "${key_file}"
  set +e
  output="$(coreelec_lifecycle_validate_public_key "${key_file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a malformed key line must be rejected" || return 1
  if [[ -e "${dir}/pwned" ]]; then
    printf 'a malformed key file must never execute anything\n' >&2
    return 1
  fi
}

test_key_entry_uses_restrict_and_forced_command() {
  local dir key_file line entry
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  key_file="${dir}/admin.pub"
  write_fixture_public_key "${key_file}"
  line="$(coreelec_lifecycle_validate_public_key "${key_file}")"

  entry="$(coreelec_lifecycle_key_entry "${line}")"
  assert_contains "${entry}" 'restrict,command="/storage/.config/kodi-lifecycle"' \
    "the preferred entry restricts the session and forces the lifecycle command" || return 1
  assert_contains "${entry}" "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixtureKeyBytesForLifecycleTests0000" \
    "the entry carries the normalized key type and blob" || return 1
  assert_contains "${entry}" "homeassistant-ugoos-kodi-lifecycle" \
    "the entry carries the stable marker comment" || return 1
  assert_not_contains "${entry}" "operator@fixture" \
    "the entry never carries the operator's original key comment" || return 1
  assert_not_contains "${entry}" "permitopen" "the entry never adds permitopen" || return 1
  assert_not_contains "${entry}" "environment" "the entry never adds environment" || return 1
}

test_key_entry_fallback_disables_forwarding_pty_x11_and_user_rc() {
  local dir key_file line entry
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  key_file="${dir}/admin.pub"
  write_fixture_public_key "${key_file}"
  line="$(coreelec_lifecycle_validate_public_key "${key_file}")"

  entry="$(coreelec_lifecycle_key_entry_fallback "${line}")"
  assert_contains "${entry}" "no-agent-forwarding" "the fallback disables agent forwarding" || return 1
  assert_contains "${entry}" "no-port-forwarding" "the fallback disables port forwarding" || return 1
  assert_contains "${entry}" "no-pty" "the fallback disables pty allocation" || return 1
  assert_contains "${entry}" "no-user-rc" "the fallback disables the user rc file" || return 1
  assert_contains "${entry}" "no-X11-forwarding" "the fallback disables X11 forwarding" || return 1
  assert_contains "${entry}" 'command="/storage/.config/kodi-lifecycle"' \
    "the fallback still forces the lifecycle command" || return 1
  assert_contains "${entry}" "homeassistant-ugoos-kodi-lifecycle" \
    "the fallback carries the stable marker comment" || return 1
  assert_not_contains "${entry}" "permitopen" "the fallback never adds permitopen" || return 1
  assert_not_contains "${entry}" "environment" "the fallback never adds environment" || return 1
}

# --- Wrapper rendering and behavior tests -------------------------------

test_wrapper_start_is_idempotent() {
  local dir systemctl wrapper output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  systemctl="$(install_lifecycle_systemctl_fixture "${dir}")"
  wrapper="$(render_wrapper_to_file "${dir}" "${systemctl}")"
  set_fixture_active_state "${dir}" "inactive"

  output="$(run_wrapper "${dir}" "${wrapper}" "start")"
  assert_eq "running" "${output}" "starting an inactive unit reports running" || return 1
  assert_eq "1" "$(grep -c '^start$' "${dir}/systemctl-config/calls/argv-2.log" || true)" \
    "the first start call actually issues systemctl start" || return 1

  output="$(run_wrapper "${dir}" "${wrapper}" "start")"
  assert_eq "running" "${output}" "starting an already-active unit still reports running" || return 1
  assert_eq "1" "$(systemctl_subcommand_count "${dir}" "start")" \
    "a second start on an already-active unit must not call systemctl start again"
}

test_wrapper_stop_is_idempotent() {
  local dir systemctl wrapper output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  systemctl="$(install_lifecycle_systemctl_fixture "${dir}")"
  wrapper="$(render_wrapper_to_file "${dir}" "${systemctl}")"
  set_fixture_active_state "${dir}" "active"

  output="$(run_wrapper "${dir}" "${wrapper}" "stop")"
  assert_eq "stopped" "${output}" "stopping an active unit reports stopped" || return 1
  assert_eq "1" "$(grep -c '^stop$' "${dir}/systemctl-config/calls/argv-2.log" || true)" \
    "the first stop call actually issues systemctl stop" || return 1

  output="$(run_wrapper "${dir}" "${wrapper}" "stop")"
  assert_eq "stopped" "${output}" "stopping an already-inactive unit still reports stopped" || return 1
  assert_eq "1" "$(systemctl_subcommand_count "${dir}" "stop")" \
    "a second stop on an already-inactive unit must not call systemctl stop again"
}

test_wrapper_status_maps_active_inactive_and_failed() {
  local dir systemctl wrapper
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  systemctl="$(install_lifecycle_systemctl_fixture "${dir}")"
  wrapper="$(render_wrapper_to_file "${dir}" "${systemctl}")"

  set_fixture_active_state "${dir}" "active"
  set_fixture_failed "${dir}" "0"
  assert_eq "running" "$(run_wrapper "${dir}" "${wrapper}" "status")" \
    "an active unit reports running" || return 1

  set_fixture_active_state "${dir}" "inactive"
  set_fixture_failed "${dir}" "0"
  assert_eq "stopped" "$(run_wrapper "${dir}" "${wrapper}" "status")" \
    "a cleanly inactive unit reports stopped" || return 1

  set_fixture_active_state "${dir}" "inactive"
  set_fixture_failed "${dir}" "1"
  assert_eq "failed" "$(run_wrapper "${dir}" "${wrapper}" "status")" \
    "an inactive unit that is-failed reports failed via the is-failed check" || return 1

  set_fixture_active_state "${dir}" "failed"
  assert_eq "failed" "$(run_wrapper "${dir}" "${wrapper}" "status")" \
    "a directly failed unit reports failed"
}

test_wrapper_rejects_transitional_and_unknown_states() {
  local dir systemctl wrapper output rc state
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  systemctl="$(install_lifecycle_systemctl_fixture "${dir}")"
  wrapper="$(render_wrapper_to_file "${dir}" "${systemctl}")"

  for state in activating deactivating reloading maintenance not-found; do
    set_fixture_active_state "${dir}" "${state}"
    set +e
    output="$(run_wrapper "${dir}" "${wrapper}" "status" 2>&1)"
    rc=$?
    set -e
    assert_eq "3" "${rc}" "an unmapped state (${state}) must be reported as an error, not silently accepted" || return 1
    assert_contains "${output}" "Unsupported kodi.service state: ${state}" \
      "the unmapped state (${state}) is named in the error" || return 1
  done
}

test_wrapper_rejects_empty_unknown_compound_and_extra_argument_commands() {
  local dir systemctl wrapper rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  systemctl="$(install_lifecycle_systemctl_fixture "${dir}")"
  wrapper="$(render_wrapper_to_file "${dir}" "${systemctl}")"

  set +e
  output="$(FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" sh "${wrapper}" 2>&1)"
  rc=$?
  set -e
  assert_eq "2" "${rc}" "an empty SSH_ORIGINAL_COMMAND must be rejected" || return 1
  assert_contains "${output}" "Allowed commands: start, stop, status" \
    "the empty-command rejection names the allowed commands" || return 1
  assert_eq "0" "$(systemctl_call_count "${dir}")" \
    "an empty command must never call systemctl" || return 1

  for output in "unknown" "start; id" "start && id" "start kodi.service" "start extra-argument" "STATUS" "status "; do
    set +e
    FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
      SSH_ORIGINAL_COMMAND="${output}" sh "${wrapper}" >/dev/null 2>&1
    rc=$?
    set -e
    assert_eq "2" "${rc}" "the command '${output}' must be rejected" || return 1
  done
  assert_eq "0" "$(systemctl_call_count "${dir}")" \
    "no rejected command may ever call systemctl"
}

test_wrapper_never_accepts_a_caller_supplied_unit() {
  local dir systemctl wrapper rc argc index argument
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  systemctl="$(install_lifecycle_systemctl_fixture "${dir}")"
  wrapper="$(render_wrapper_to_file "${dir}" "${systemctl}")"
  set_fixture_active_state "${dir}" "inactive"

  set +e
  FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    SSH_ORIGINAL_COMMAND="start other.service" sh "${wrapper}" >/dev/null 2>&1
  rc=$?
  set -e
  assert_eq "2" "${rc}" "a caller-supplied unit must be refused, not substituted" || return 1
  assert_eq "0" "$(systemctl_call_count "${dir}")" \
    "a caller-supplied unit must never reach systemctl" || return 1

  run_wrapper "${dir}" "${wrapper}" "start" >/dev/null
  argc="$(systemctl_call_count "${dir}")"
  for ((index = 1; index <= argc; index++)); do
    argument="$(tail -1 "${dir}/systemctl-config/calls/argv-${index}.log")"
    assert_eq "kodi.service" "${argument}" \
      "every systemd call names exactly kodi.service, never a caller-supplied unit" || return 1
  done
}

test_wrapper_never_uses_eval() {
  local dir systemctl source
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  systemctl="$(install_lifecycle_systemctl_fixture "${dir}")"
  source="$(coreelec_lifecycle_render_wrapper "${systemctl}")"
  assert_not_contains "${source}" "eval" "the rendered wrapper must never use eval"
}

run_all_tests \
  test_lifecycle_library_sources_cleanly_on_its_own \
  test_public_key_validation_accepts_one_ed25519_key \
  test_public_key_validation_rejects_multiple_or_malformed_keys \
  test_key_entry_uses_restrict_and_forced_command \
  test_key_entry_fallback_disables_forwarding_pty_x11_and_user_rc \
  test_wrapper_start_is_idempotent \
  test_wrapper_stop_is_idempotent \
  test_wrapper_status_maps_active_inactive_and_failed \
  test_wrapper_rejects_transitional_and_unknown_states \
  test_wrapper_rejects_empty_unknown_compound_and_extra_argument_commands \
  test_wrapper_never_accepts_a_caller_supplied_unit \
  test_wrapper_never_uses_eval
