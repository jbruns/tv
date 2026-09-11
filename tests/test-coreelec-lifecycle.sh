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
    # Additive fault-injection hook, unused by any Task 1-2 test: when the
    # marker file is present, a real `systemctl start` failure is
    # reproduced (nonzero exit, no state change) so Task 3's restricted
    # verification-failure tests can deterministically force the wrapper's
    # own `set -eu` to abort mid-command, without touching real state.
    [[ -f "${config_dir}/fault-on-start" ]] && exit 9
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

set_fixture_fault_on_start() {
  local dir="$1" enabled="$2"
  if [[ "${enabled}" == "1" ]]; then
    : > "${dir}/systemctl-config/fault-on-start"
  else
    rm -f "${dir}/systemctl-config/fault-on-start"
  fi
}

# --- Task 3 fixtures: CLI, keys, remote-script emission, dual-mode SSH ---

CONFIGURE_KODI_LIFECYCLE_CLI="${SCRIPT_DIR}/../configure-kodi-lifecycle.sh"

# Generates a real, passphrase-less ed25519 keypair under `${dir}` named
# `${name}` / `${name}.pub`. Real key material (not literal fixture text) is
# required here: the deploy transaction validates candidate authorized_keys
# entries with the target's own `ssh-keygen -l -f`, which genuinely parses
# the base64 blob rather than merely pattern-matching it, and this
# repository's installed OpenSSH accepts any leading option string before a
# real key but rejects one before fixture text that never base64-decodes to
# a real key.
generate_fixture_keypair() {
  local dir="$1" name="$2"
  ssh-keygen -t ed25519 -N '' -f "${dir}/${name}" -q -C "operator@fixture"
}

write_fixture_os_release() {
  local file="$1" valid="${2:-1}"
  mkdir -p "$(dirname "${file}")"
  if [[ "${valid}" == "1" ]]; then
    printf 'NAME="CoreELEC"\nVERSION="21.3-Omega (Amlogic-ng.arm)"\n' > "${file}"
  else
    printf 'NAME="Ubuntu"\nVERSION="22.04"\n' > "${file}"
  fi
}

# Installs a fixture `ssh-keygen` that rejects any authorized_keys line
# containing the literal word "restrict", standing in for an OpenSSH release
# older than 7.2 that does not understand the keyword, so the deploy
# transaction's preferred-syntax probe genuinely fails and the explicit
# fallback is exercised. Every other well-formed, non-empty line is
# accepted; this only replaces the `-l -f` syntax probe, nothing else.
install_fixture_ssh_keygen_rejecting_restrict() {
  local dir bin_dir
  dir="$1"
  bin_dir="${dir}/ssh-keygen-reject-bin"
  mkdir -p "${bin_dir}"
  cat > "${bin_dir}/ssh-keygen" <<'STUB'
#!/bin/bash
set -eu
if [[ "${1:-}" == "-l" && "${2:-}" == "-f" ]]; then
  grep -q 'restrict' "$3" && exit 1
  [[ -s "$3" ]]
  exit $?
fi
exit 1
STUB
  chmod +x "${bin_dir}/ssh-keygen"
  printf '%s\n' "${bin_dir}"
}

# Installs the dual-mode `ssh` stub used for full-CLI tests. It distinguishes
# the administrator connection (`coreelec_ssh_batch`'s trailing single argv
# word is always the literal string "sh -s") from the restricted controller
# connection (whose trailing argv word is always the bare command word the
# wrapper receives as SSH_ORIGINAL_COMMAND) -- without ever touching the
# real network or a real sshd, matching this repository's existing
# stub-over-daemon convention (see install_ssh_stub in
# tests/test-coreelec-addon-workflows.sh).
#
# The administrator path rewrites the three fixed device paths
# configure-kodi-lifecycle.sh always embeds for production (root=/storage,
# os_release_path=/etc/os-release, and the wrapper's hardcoded
# SYSTEMCTL="/usr/bin/systemctl") to the caller's fixture equivalents before
# executing, so the exact same production rendering code runs against a
# fixture tree instead of a real target -- no separate "test mode" branch
# exists in configure-kodi-lifecycle.sh or lib/coreelec-lifecycle.sh for
# this.
#
# Reads, at call time (not install time): LIFECYCLE_FIXTURE_ROOT,
# LIFECYCLE_FIXTURE_OS_RELEASE, LIFECYCLE_FIXTURE_BIN_DIR (systemctl and,
# where relevant, ssh-keygen), and optionally LIFECYCLE_SABOTAGE_ROLLBACK=1,
# which -- only when set -- replaces the fixture authorized_keys path with a
# directory immediately before a rollback script runs, deterministically
# reproducing an unrestorable target for the "incomplete rollback" test.
install_lifecycle_ssh_stub() {
  local dir bin_dir
  dir="$1"
  bin_dir="${dir}/ssh-stub-bin"
  mkdir -p "${bin_dir}"
  cat > "${bin_dir}/ssh" <<'STUB'
#!/bin/bash
set -eu
fixture_root="${LIFECYCLE_FIXTURE_ROOT:?LIFECYCLE_FIXTURE_ROOT is required}"
os_release="${LIFECYCLE_FIXTURE_OS_RELEASE:?LIFECYCLE_FIXTURE_OS_RELEASE is required}"
fixture_bin="${LIFECYCLE_FIXTURE_BIN_DIR:?LIFECYCLE_FIXTURE_BIN_DIR is required}"

n=$#
last="${!n}"

if [[ "${last}" == "sh -s" ]]; then
  script="$(cat)"
  if [[ -n "${LIFECYCLE_SABOTAGE_ROLLBACK:-}" ]] \
      && printf '%s' "${script}" | grep -q 'ROLLBACK_FAIL:no-pending-transaction'; then
    rm -rf "${fixture_root}/.ssh/authorized_keys"
    mkdir -p "${fixture_root}/.ssh/authorized_keys"
  fi
  script="$(printf '%s' "${script}" | sed \
    -e "s#root='/storage'#root='${fixture_root}'#" \
    -e "s#os_release_path='/etc/os-release'#os_release_path='${os_release}'#" \
    -e "s#SYSTEMCTL=\"/usr/bin/systemctl\"#SYSTEMCTL=\"${fixture_bin}/systemctl\"#")"
  set +e
  printf '%s\n' "${script}" | PATH="${fixture_bin}:${PATH}" sh -s
  rc=$?
  set -e
  exit "${rc}"
fi

set +e
SSH_ORIGINAL_COMMAND="${last}" sh "${fixture_root}/.config/kodi-lifecycle"
rc=$?
set -e
exit "${rc}"
STUB
  chmod +x "${bin_dir}/ssh"
  printf '%s\n' "${bin_dir}"
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

# --- Task 3: CLI parsing, help, and dry-run -----------------------------

test_help_documents_both_controller_key_inputs_and_recovery() {
  local output
  output="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --help)"
  assert_contains "${output}" "--controller-public-key" \
    "help must document --controller-public-key" || return 1
  assert_contains "${output}" "--controller-identity" \
    "help must document --controller-identity" || return 1
  assert_contains "${output}" "--rollback-transaction" \
    "help must document the rollback recovery command" || return 1
  assert_contains "${output}" "--inspect-transaction" \
    "help must document the inspect recovery command"
}

test_dry_run_makes_no_ssh_calls() {
  local dir bogus_bin report_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"
  bogus_bin="${dir}/bogus-ssh-bin"
  mkdir -p "${bogus_bin}"
  cat > "${bogus_bin}/ssh" <<STUB
#!/bin/bash
: > "${dir}/ssh-was-called"
exit 1
STUB
  chmod +x "${bogus_bin}/ssh"
  report_dir="${dir}/reports"

  set +e
  output="$(PATH="${bogus_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" \
    --dry-run --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "dry-run must succeed: ${output}" || return 1
  if [[ -e "${dir}/ssh-was-called" ]]; then
    printf 'dry-run invoked ssh, which it must never do\n' >&2
    return 1
  fi
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=dry-run" \
    "the dry-run report is labeled dry-run"
}

test_target_and_key_arguments_are_required() {
  local dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"

  set +e
  output="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "missing --target must fail" || return 1
  assert_contains "${output}" "--target is required" "the failure names --target" || return 1

  set +e
  output="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --target 127.0.0.1 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "missing --controller-public-key must fail" || return 1
  assert_contains "${output}" "--controller-public-key is required" \
    "the failure names --controller-public-key" || return 1

  set +e
  output="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "missing --controller-identity must fail" || return 1
  assert_contains "${output}" "--controller-identity is required" \
    "the failure names --controller-identity"
}

# --- Task 3: remote deploy transaction -----------------------------------

test_platform_check_requires_coreelec_21_3_amlogic_ng() {
  local dir os_release pubkey systemctl_bin systemctl_dir script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"

  write_fixture_os_release "${os_release}" "0"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${dir}/root1" "${os_release}" "${pubkey}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a non-CoreELEC os-release must be refused" || return 1
  assert_contains "${output}" "PLATFORM_CHECK_FAIL" "the refusal names the platform check" || return 1

  write_fixture_os_release "${os_release}" "1"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${dir}/root2" "${os_release}" "${pubkey}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a valid CoreELEC 21.3 Amlogic-ng os-release must pass the platform check: ${output}"
}

test_deploy_creates_private_directories_and_atomic_candidates() {
  local dir os_release pubkey systemctl_bin systemctl_dir root script output rc mode
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the deploy transaction must succeed: ${output}" || return 1
  assert_contains "${output}" "DEPLOY_STATE:pending-verification" \
    "the deploy reaches pending-verification" || return 1

  mode="$(stat -f '%Lp' "${root}/.config" 2>/dev/null || stat -c '%a' "${root}/.config")"
  assert_eq "700" "${mode}" ".config must be mode 0700" || return 1
  mode="$(stat -f '%Lp' "${root}/.ssh" 2>/dev/null || stat -c '%a' "${root}/.ssh")"
  assert_eq "700" "${mode}" ".ssh must be mode 0700" || return 1
  mode="$(stat -f '%Lp' "${root}/.config/kodi-lifecycle" 2>/dev/null || stat -c '%a' "${root}/.config/kodi-lifecycle")"
  assert_eq "700" "${mode}" "the wrapper must be mode 0700" || return 1
  mode="$(stat -f '%Lp' "${root}/.ssh/authorized_keys" 2>/dev/null || stat -c '%a' "${root}/.ssh/authorized_keys")"
  assert_eq "600" "${mode}" "authorized_keys must be mode 0600" || return 1
  mode="$(stat -f '%Lp' "${root}/backup/kodi-lifecycle" 2>/dev/null || stat -c '%a' "${root}/backup/kodi-lifecycle")"
  assert_eq "700" "${mode}" "the backup root must be mode 0700" || return 1
  mode="$(stat -f '%Lp' "${root}/.cache/kodi-lifecycle" 2>/dev/null || stat -c '%a' "${root}/.cache/kodi-lifecycle")"
  assert_eq "700" "${mode}" "the cache root must be mode 0700" || return 1

  if [[ -e "${root}/.config/kodi-lifecycle.candidate" || -e "${root}/.ssh/authorized_keys.candidate" ]]; then
    printf 'a completed deploy must never leave a .candidate file behind\n' >&2
    return 1
  fi
}

test_deploy_preserves_unrelated_authorized_keys() {
  local dir os_release pubkey systemctl_bin systemctl_dir root script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"
  mkdir -p "${root}/.ssh"
  chmod 700 "${root}/.ssh"
  printf 'ssh-ed25519 AAAAOTHERKEYBLOB000000000000000000000000000 admin@laptop\n' \
    > "${root}/.ssh/authorized_keys"
  chmod 600 "${root}/.ssh/authorized_keys"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the deploy transaction must succeed: ${output}" || return 1

  assert_contains "$(cat "${root}/.ssh/authorized_keys")" "admin@laptop" \
    "the unrelated administrator key must survive the deploy" || return 1
  assert_contains "$(cat "${root}/.ssh/authorized_keys")" "homeassistant-ugoos-kodi-lifecycle" \
    "the new marked controller key must be present"
}

test_rerun_replaces_only_the_marked_controller_key() {
  local dir os_release systemctl_bin systemctl_dir root output rc first_pub second_pub script content
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "first"
  generate_fixture_keypair "${dir}" "second"
  first_pub="${dir}/first.pub"
  second_pub="${dir}/second.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"
  mkdir -p "${root}/.ssh"
  printf 'ssh-ed25519 AAAAOTHERKEYBLOB000000000000000000000000000 admin@laptop\n' \
    > "${root}/.ssh/authorized_keys"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${first_pub}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the first deploy must succeed: ${output}" || return 1

  # Finalize so the transaction pointer is cleared and a second deploy is
  # accepted, exactly as the CLI does after successful controller
  # verification -- this test is only about which key line survives a
  # rerun, not about finalize/rollback themselves.
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "finalize must succeed: ${output}" || return 1

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${second_pub}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the rerun deploy must succeed: ${output}" || return 1

  content="$(cat "${root}/.ssh/authorized_keys")"
  assert_contains "${content}" "admin@laptop" "the unrelated key must still survive a rerun" || return 1
  assert_eq "1" "$(grep -c 'homeassistant-ugoos-kodi-lifecycle' "${root}/.ssh/authorized_keys")" \
    "exactly one marked controller key line must remain after a rerun" || return 1
  assert_not_contains "${content}" "$(awk '{print $2}' "${first_pub}")" \
    "the first run's key blob must be gone after the rerun"
}

test_deploy_prefers_restrict_when_sshd_supports_it() {
  local dir os_release pubkey systemctl_bin systemctl_dir root script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the deploy must succeed: ${output}" || return 1
  assert_contains "${output}" "KEY_MODE:restrict" \
    "when ssh-keygen accepts restrict, the deploy must prefer it" || return 1
  assert_contains "$(cat "${root}/.ssh/authorized_keys")" 'restrict,command="/storage/.config/kodi-lifecycle"' \
    "the installed entry must use the restrict syntax"
}

test_deploy_uses_explicit_restrictions_when_restrict_is_unsupported() {
  local dir os_release pubkey systemctl_bin systemctl_dir reject_bin root script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  reject_bin="$(install_fixture_ssh_keygen_rejecting_restrict "${dir}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${reject_bin}:${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the deploy must succeed via the fallback: ${output}" || return 1
  assert_contains "${output}" "KEY_MODE:fallback" \
    "when ssh-keygen rejects restrict, the deploy must use the fallback" || return 1
  assert_contains "$(cat "${root}/.ssh/authorized_keys")" \
    "no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc,no-X11-forwarding" \
    "the installed entry must use the explicit fallback syntax"
}

# --- Task 3: restricted controller transport ------------------------------

test_restricted_identity_can_run_status_start_and_stop() {
  local dir root systemctl_bin systemctl_dir ssh_bin identity known_hosts out rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  mkdir -p "${root}/.config"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  coreelec_lifecycle_render_wrapper "${systemctl_bin}" > "${root}/.config/kodi-lifecycle"
  chmod 700 "${root}/.config/kodi-lifecycle"
  ssh_bin="$(install_lifecycle_ssh_stub "${dir}")"
  generate_fixture_keypair "${dir}" "controller"
  identity="${dir}/controller"
  known_hosts="${dir}/known_hosts"
  : > "${known_hosts}"
  set_fixture_active_state "${dir}" "inactive"

  TARGET="127.0.0.1"
  SSH_PORT="22"
  CONTROLLER_IDENTITY="${identity}"
  KNOWN_HOSTS_FILE="${known_hosts}"

  set +e
  out="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${dir}/unused-os-release" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${ssh_bin}:${PATH}" coreelec_lifecycle_ssh_controller "status")"
  rc=$?
  set -e
  assert_success "${rc}" "status over the restricted identity must succeed: ${out}" || return 1
  assert_eq "stopped" "${out}" "status must report the wrapper's exact stopped text" || return 1

  set +e
  out="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${dir}/unused-os-release" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${ssh_bin}:${PATH}" coreelec_lifecycle_ssh_controller "start")"
  rc=$?
  set -e
  assert_success "${rc}" "start over the restricted identity must succeed: ${out}" || return 1
  assert_eq "running" "${out}" "start must report the wrapper's exact running text" || return 1

  set +e
  out="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${dir}/unused-os-release" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${ssh_bin}:${PATH}" coreelec_lifecycle_ssh_controller "stop")"
  rc=$?
  set -e
  assert_success "${rc}" "stop over the restricted identity must succeed: ${out}" || return 1
  assert_eq "stopped" "${out}" "stop must report the wrapper's exact stopped text"
}

test_restricted_identity_cannot_run_an_arbitrary_command() {
  local dir root systemctl_bin systemctl_dir ssh_bin identity known_hosts out rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  mkdir -p "${root}/.config"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  coreelec_lifecycle_render_wrapper "${systemctl_bin}" > "${root}/.config/kodi-lifecycle"
  chmod 700 "${root}/.config/kodi-lifecycle"
  ssh_bin="$(install_lifecycle_ssh_stub "${dir}")"
  generate_fixture_keypair "${dir}" "controller"
  identity="${dir}/controller"
  known_hosts="${dir}/known_hosts"
  : > "${known_hosts}"
  set_fixture_active_state "${dir}" "inactive"

  TARGET="127.0.0.1"
  SSH_PORT="22"
  CONTROLLER_IDENTITY="${identity}"
  KNOWN_HOSTS_FILE="${known_hosts}"

  set +e
  out="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${dir}/unused-os-release" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${ssh_bin}:${PATH}" coreelec_lifecycle_ssh_controller "id" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an arbitrary command must be denied, not merely echoed: ${out}" || return 1
  assert_contains "${out}" "Allowed commands: start, stop, status" \
    "the denial names the allowed commands" || return 1
  assert_eq "0" "$(systemctl_call_count "${dir}")" \
    "an arbitrary command must never reach systemctl"
}

# --- Task 3: full CLI deployment, verification, rollback ------------------

test_verification_restores_initial_running_state() {
  local dir root os_release systemctl_bin systemctl_dir ssh_bin report_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"
  root="${dir}/root"
  os_release="${dir}/os-release"
  write_fixture_os_release "${os_release}" "1"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  ssh_bin="$(install_lifecycle_ssh_stub "${dir}")"
  set_fixture_active_state "${dir}" "active"
  report_dir="${dir}/reports"

  set +e
  output="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${os_release}" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${ssh_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" \
    --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a clean deployment starting from running must succeed: ${output}" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=committed" \
    "a fully verified deployment must be committed" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "restored_state=running" \
    "the device must be restored to its initial running state"
}

test_verification_restores_initial_stopped_state() {
  local dir root os_release systemctl_bin systemctl_dir ssh_bin report_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"
  root="${dir}/root"
  os_release="${dir}/os-release"
  write_fixture_os_release "${os_release}" "1"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  ssh_bin="$(install_lifecycle_ssh_stub "${dir}")"
  set_fixture_active_state "${dir}" "inactive"
  report_dir="${dir}/reports"

  set +e
  output="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${os_release}" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${ssh_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" \
    --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a clean deployment starting from stopped must succeed: ${output}" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=committed" \
    "a fully verified deployment must be committed" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "restored_state=stopped" \
    "the device must be restored to its initial stopped state"
}

test_failed_verification_rolls_back_wrapper_and_authorized_keys() {
  local dir root os_release systemctl_bin systemctl_dir ssh_bin report_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"
  root="${dir}/root"
  os_release="${dir}/os-release"
  write_fixture_os_release "${os_release}" "1"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  ssh_bin="$(install_lifecycle_ssh_stub "${dir}")"
  set_fixture_active_state "${dir}" "inactive"
  set_fixture_fault_on_start "${dir}" "1"
  report_dir="${dir}/reports"

  set +e
  output="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${os_release}" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${ssh_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" \
    --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a verification failure must not be reported as success: ${output}" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=rolled-back" \
    "a failed verification must roll back the deployment" || return 1

  if [[ -e "${root}/.config/kodi-lifecycle" ]]; then
    printf 'the wrapper must not remain installed after a rollback on a fresh root\n' >&2
    return 1
  fi
  if [[ -e "${root}/.ssh/authorized_keys" ]]; then
    printf 'authorized_keys must not remain installed after a rollback on a fresh root\n' >&2
    return 1
  fi
}

test_failed_rollback_retains_recovery_material_and_instructions() {
  local dir root os_release systemctl_bin systemctl_dir ssh_bin report_dir output rc transaction_dirs
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"
  root="${dir}/root"
  os_release="${dir}/os-release"
  write_fixture_os_release "${os_release}" "1"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  ssh_bin="$(install_lifecycle_ssh_stub "${dir}")"
  set_fixture_active_state "${dir}" "inactive"
  set_fixture_fault_on_start "${dir}" "1"
  report_dir="${dir}/reports"

  set +e
  output="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${os_release}" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    LIFECYCLE_SABOTAGE_ROLLBACK="1" \
    PATH="${ssh_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" \
    --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an incomplete rollback must not be reported as success: ${output}" || return 1
  assert_contains "${output}" "--rollback-transaction" \
    "an incomplete rollback must print the exact rollback recovery command" || return 1
  assert_contains "${output}" "--inspect-transaction" \
    "an incomplete rollback must print the exact inspect recovery command" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=incomplete-rollback" \
    "the report must record the incomplete rollback state" || return 1

  transaction_dirs=("${root}/backup/kodi-lifecycle"/*)
  if [[ ! -d "${transaction_dirs[0]}" ]]; then
    printf 'the transaction directory must be retained after an incomplete rollback\n' >&2
    return 1
  fi
  if [[ ! -f "${root}/.cache/kodi-lifecycle/current-transaction" ]]; then
    printf 'the pointer file must be retained after an incomplete rollback\n' >&2
    return 1
  fi
}

test_report_never_contains_public_or_private_key_material() {
  local dir root os_release systemctl_bin systemctl_dir ssh_bin report_dir output rc report_file blob identity_line
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"
  root="${dir}/root"
  os_release="${dir}/os-release"
  write_fixture_os_release "${os_release}" "1"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  ssh_bin="$(install_lifecycle_ssh_stub "${dir}")"
  set_fixture_active_state "${dir}" "inactive"
  report_dir="${dir}/reports"

  set +e
  output="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${os_release}" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${ssh_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" \
    --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a clean deployment must succeed: ${output}" || return 1

  report_file="$(printf '%s\n' "${report_dir}"/*.txt)"
  blob="$(awk '{print $2}' "${dir}/controller.pub")"
  identity_line="$(grep -m1 '[^[:space:]]' "${dir}/controller")"
  assert_not_contains "$(cat "${report_file}")" "${blob}" \
    "the report must never contain the normalized controller key blob" || return 1
  assert_not_contains "$(cat "${report_file}")" "${identity_line}" \
    "the report must never contain the private controller identity's first line" || return 1
  assert_contains "$(cat "${report_file}")" "controller_key_supplied=1" \
    "the report still records that a controller key was supplied"
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
  test_wrapper_never_uses_eval \
  test_help_documents_both_controller_key_inputs_and_recovery \
  test_dry_run_makes_no_ssh_calls \
  test_target_and_key_arguments_are_required \
  test_platform_check_requires_coreelec_21_3_amlogic_ng \
  test_deploy_creates_private_directories_and_atomic_candidates \
  test_deploy_preserves_unrelated_authorized_keys \
  test_rerun_replaces_only_the_marked_controller_key \
  test_deploy_prefers_restrict_when_sshd_supports_it \
  test_deploy_uses_explicit_restrictions_when_restrict_is_unsupported \
  test_restricted_identity_can_run_status_start_and_stop \
  test_restricted_identity_cannot_run_an_arbitrary_command \
  test_verification_restores_initial_running_state \
  test_verification_restores_initial_stopped_state \
  test_failed_verification_rolls_back_wrapper_and_authorized_keys \
  test_failed_rollback_retains_recovery_material_and_instructions \
  test_report_never_contains_public_or_private_key_material
