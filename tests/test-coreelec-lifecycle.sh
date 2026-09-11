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

# Installs a fixture `sshd` binary standing in for a real OpenSSH server
# binary, at a fixture-local path never found via $PATH (see finding I5):
# the deploy transaction's key-mode check runs `sshd -V`, and real OpenSSH
# writes its version banner to stderr and exits nonzero for that flag alone,
# which this stub reproduces. `mode` selects which banner (or absence of a
# binary at all) is produced:
#   supported   -- OpenSSH >= 7.2, so `restrict` is understood
#   unsupported -- OpenSSH < 7.2, predating the `restrict` keyword
#   malformed   -- a banner with no parseable "OpenSSH_X.Y" token
#   unavailable -- installs nothing at the returned path, so `[ -x ]` fails
install_fixture_sshd() {
  local dir="$1" mode="$2" bin_dir path banner
  bin_dir="${dir}/sshd-fixture-bin"
  mkdir -p "${bin_dir}"
  path="${bin_dir}/sshd"
  case "${mode}" in
    unavailable)
      printf '%s\n' "${path}"
      return 0
      ;;
    supported) banner="OpenSSH_9.9p1, OpenSSL 3.1.4 11 Feb 2024" ;;
    unsupported) banner="OpenSSH_6.6p1, OpenSSL 1.0.1e-fips 11 Feb 2013" ;;
    malformed) banner="this is not a version string" ;;
  esac
  cat > "${path}" <<STUB
#!/bin/bash
printf '%s\n' "${banner}" >&2
exit 1
STUB
  chmod +x "${path}"
  printf '%s\n' "${path}"
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
# LIFECYCLE_FIXTURE_OS_RELEASE, LIFECYCLE_FIXTURE_BIN_DIR (systemctl), and
# optionally LIFECYCLE_FIXTURE_SSHD (a fixture `sshd` binary path -- see
# install_fixture_sshd -- substituted for the deploy script's own literal
# `sshd='/usr/sbin/sshd'` default). This stub *always* substitutes some
# fixture `sshd` -- it installs and wires in its own deterministic
# "supported" (OpenSSH >= 7.2) fixture at install time, under this call's
# own `dir`, so every full-CLI test reaches pending-verification without
# ever depending on whether the host machine running this suite has a real
# `/usr/sbin/sshd` at all. Setting LIFECYCLE_FIXTURE_SSHD at call time
# overrides that default with the caller's own fixture path instead (used
# by the focused key-mode-check tests to exercise unsupported/malformed/
# unavailable sshd versions), LIFECYCLE_SABOTAGE_ROLLBACK=1, which -- only
# when set -- replaces the fixture authorized_keys path with a directory
# immediately before a rollback script runs, deterministically reproducing
# an unrestorable target for the "incomplete rollback" test,
# LIFECYCLE_SABOTAGE_FINALIZE=1, which makes the backup root read-only
# immediately before a finalize script runs so its `rm -rf` genuinely fails
# (finding I3's cleanup-failed path), and LIFECYCLE_SABOTAGE_DEPLOY_OUTPUT=1,
# which replaces a deploy script's entire execution with an empty,
# unrecognized response (finding C2's "unknown" outcome, standing in for a
# truncated/dropped connection).
install_lifecycle_ssh_stub() {
  local dir bin_dir default_sshd
  dir="$1"
  bin_dir="${dir}/ssh-stub-bin"
  mkdir -p "${bin_dir}"
  # This suite's own deterministic "supported" sshd, wired in as the
  # unconditional fallback below so this stub never falls through to
  # whatever `/usr/sbin/sshd` (if anything) actually exists on the host
  # running these tests.
  default_sshd="$(install_fixture_sshd "${dir}/default-sshd" "supported")"
  cat > "${bin_dir}/ssh.tmpl" <<'STUB'
#!/bin/bash
set -eu
fixture_root="${LIFECYCLE_FIXTURE_ROOT:?LIFECYCLE_FIXTURE_ROOT is required}"
os_release="${LIFECYCLE_FIXTURE_OS_RELEASE:?LIFECYCLE_FIXTURE_OS_RELEASE is required}"
fixture_bin="${LIFECYCLE_FIXTURE_BIN_DIR:?LIFECYCLE_FIXTURE_BIN_DIR is required}"
sshd_fixture="${LIFECYCLE_FIXTURE_SSHD:-__LIFECYCLE_DEFAULT_SSHD__}"

n=$#
last="${!n}"

if [[ "${last}" == "sh -s" ]]; then
  script="$(cat)"
  if [[ -n "${LIFECYCLE_SABOTAGE_ROLLBACK:-}" ]] \
      && printf '%s' "${script}" | grep -q 'ROLLBACK_FAIL:no-pending-transaction'; then
    rm -rf "${fixture_root}/.ssh/authorized_keys"
    mkdir -p "${fixture_root}/.ssh/authorized_keys"
  fi
  if [[ -n "${LIFECYCLE_SABOTAGE_FINALIZE:-}" ]] \
      && printf '%s' "${script}" | grep -q 'FINALIZE_STATE:committed'; then
    chmod 500 "${fixture_root}/backup/kodi-lifecycle"
  fi
  if [[ -n "${LIFECYCLE_SABOTAGE_DEPLOY_OUTPUT:-}" ]] \
      && printf '%s' "${script}" | grep -q 'DEPLOY_STATE:pending-verification'; then
    printf 'unrecognized-truncated-response\n'
    exit 1
  fi
  script="$(printf '%s' "${script}" | sed \
    -e "s#root='/storage'#root='${fixture_root}'#" \
    -e "s#os_release_path='/etc/os-release'#os_release_path='${os_release}'#" \
    -e "s#SYSTEMCTL=\"/usr/bin/systemctl\"#SYSTEMCTL=\"${fixture_bin}/systemctl\"#" \
    -e "s#sshd='/usr/sbin/sshd'#sshd='${sshd_fixture}'#")"
  set +e
  printf '%s\n' "${script}" | PATH="${fixture_bin}:${PATH}" sh -s
  rc=$?
  set -e
  exit "${rc}"
fi

if [[ "${last}" == "id" && -n "${LIFECYCLE_DENIAL_FAULT:-}" ]]; then
  case "${LIFECYCLE_DENIAL_FAULT}" in
    disconnect) printf 'ssh: connection reset\n' >&2; exit 255 ;;
    authentication) printf 'Permission denied (publickey).\n' >&2; exit 255 ;;
    deadline) exit 124 ;;
    wrong-diagnostic) printf 'an unrelated command failed\n' >&2; exit 2 ;;
    unexpected-stdout)
      printf 'uid=0(root)\n'
      printf 'Allowed commands: start, stop, status\n' >&2
      exit 2
      ;;
  esac
fi
set +e
SSH_ORIGINAL_COMMAND="${last}" sh "${fixture_root}/.config/kodi-lifecycle"
rc=$?
set -e
exit "${rc}"
STUB
  sed -e "s#__LIFECYCLE_DEFAULT_SSHD__#${default_sshd}#" "${bin_dir}/ssh.tmpl" > "${bin_dir}/ssh"
  rm -f "${bin_dir}/ssh.tmpl"
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

test_recovery_dry_run_is_rejected_before_any_ssh() {
  local dir mode output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  mkdir -p "${dir}/bin"
  cat > "${dir}/bin/ssh" <<STUB
#!/bin/bash
: > "${dir}/ssh-was-called"
exit 0
STUB
  chmod +x "${dir}/bin/ssh"
  for mode in rollback finalize inspect; do
    set +e
    output="$(PATH="${dir}/bin:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
      --target 127.0.0.1 --dry-run "--${mode}-transaction" 2>&1)"
    rc=$?
    set -e
    [[ ! -e "${dir}/ssh-was-called" ]] || {
      printf 'dry-run contacted target during %s recovery\n' "${mode}" >&2
      return 1
    }
    assert_failure "${rc}" "conflicting recovery dry-run must be refused" || return 1
    assert_contains "${output}" "--dry-run cannot be combined" || return 1
  done
}

test_denial_verification_rejects_transport_and_wrong_denials() {
  local dir fault root os_release systemctl_bin ssh_bin report_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"
  for fault in disconnect authentication deadline wrong-diagnostic unexpected-stdout; do
    root="${dir}/${fault}/root"
    os_release="${dir}/${fault}/os-release"
    write_fixture_os_release "${os_release}"
    systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}/${fault}")"
    ssh_bin="$(install_lifecycle_ssh_stub "${dir}/${fault}")"
    report_dir="${dir}/${fault}/reports"
    set +e
    output="$(LIFECYCLE_DENIAL_FAULT="${fault}" LIFECYCLE_FIXTURE_ROOT="${root}" \
      LIFECYCLE_FIXTURE_OS_RELEASE="${os_release}" \
      LIFECYCLE_FIXTURE_BIN_DIR="$(dirname "${systemctl_bin}")" \
      FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/${fault}/systemctl-config" \
      PATH="${ssh_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
      --target 127.0.0.1 --controller-public-key "${dir}/controller.pub" \
      --controller-identity "${dir}/controller" --report-dir "${report_dir}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "${fault} is not proof that the forced command denied id" || return 1
    assert_contains "$(cat "${report_dir}"/*.txt)" "restricted.arbitrary_command_denied=fail" || return 1
    assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=rolled-back" || return 1
    [[ ! -e "${root}/.ssh/authorized_keys" ]] || return 1
  done
}

test_documented_host_bootstrap_requires_independent_fingerprint() {
  local dir guide script fingerprint output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  guide="${BOOTSTRAP_DOC_FIXTURE:-${SCRIPT_DIR}/../docs/home-assistant/ugoos-kodi-lifecycle.md}"
  script="${dir}/bootstrap.sh"
  mkdir -p "${dir}/bin" "${dir}/ha-ssh"
  python3 - "${guide}" "${script}" "${dir}/ha-ssh" <<'PY'
from pathlib import Path
import re
import sys
guide, output, ssh_dir = sys.argv[1:]
blocks = re.findall(r"```bash\n(.*?)\n```", Path(guide).read_text(), re.S)
block = next(block for block in blocks if "ssh-keyscan" in block)
block = block.replace("/config/.ssh", ssh_dir)
block = block.replace("SHA256:REPLACE_WITH_INDEPENDENTLY_VERIFIED_SERVER_FINGERPRINT",
                      "SHA256:trusted-server")
Path(output).write_text(block + "\n")
PY
  cat > "${dir}/bin/ssh-keyscan" <<'STUB'
#!/bin/bash
printf 'ugoos-theater ssh-ed25519 fixture-server-key\n'
STUB
  cat > "${dir}/bin/ssh-keygen" <<'STUB'
#!/bin/bash
if [[ "${1:-}" == "-t" ]]; then
  while [[ "$#" -gt 0 ]]; do
    if [[ "$1" == "-f" ]]; then
      printf 'fixture-identity\n' > "$2"
      exit 0
    fi
    shift
  done
  exit 1
fi
printf '256 %s server-fixture (ED25519)\n' "${BOOTSTRAP_SCAN_FINGERPRINT:?}"
STUB
  chmod +x "${dir}/bin/ssh-keyscan" "${dir}/bin/ssh-keygen"
  printf 'existing-host-key\n' > "${dir}/ha-ssh/known_hosts"
  for fingerprint in SHA256:untrusted-server SHA256:trusted-server; do
    output="$(BOOTSTRAP_SCAN_FINGERPRINT="${fingerprint}" PATH="${dir}/bin:${PATH}" \
      bash "${script}" 2>&1)"
    if [[ "${fingerprint}" == "SHA256:untrusted-server" ]]; then
      assert_eq "existing-host-key" "$(cat "${dir}/ha-ssh/known_hosts")" \
        "unauthenticated discovery must never modify trusted host keys" || return 1
      assert_contains "${output}" "REFUSED:" || return 1
    else
      assert_eq $'existing-host-key\nugoos-theater ssh-ed25519 fixture-server-key' \
        "$(cat "${dir}/ha-ssh/known_hosts")" "only the independently matched candidate is installed" || return 1
    fi
  done
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
  local dir os_release pubkey systemctl_bin systemctl_dir sshd_bin script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  sshd_bin="$(install_fixture_sshd "${dir}" "supported")"
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
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${dir}/root2" "${os_release}" "${pubkey}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a valid CoreELEC 21.3 Amlogic-ng os-release must pass the platform check: ${output}"
}

test_deploy_creates_private_directories_and_atomic_candidates() {
  local dir os_release pubkey systemctl_bin systemctl_dir sshd_bin root script output rc mode
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  sshd_bin="$(install_fixture_sshd "${dir}" "supported")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
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
  local dir os_release pubkey systemctl_bin systemctl_dir sshd_bin root script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  sshd_bin="$(install_fixture_sshd "${dir}" "supported")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"
  mkdir -p "${root}/.ssh"
  chmod 700 "${root}/.ssh"
  printf 'ssh-ed25519 AAAAOTHERKEYBLOB000000000000000000000000000 admin@laptop\n' \
    > "${root}/.ssh/authorized_keys"
  chmod 600 "${root}/.ssh/authorized_keys"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
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
  local dir os_release systemctl_bin systemctl_dir sshd_bin root output rc first_pub second_pub script content
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "first"
  generate_fixture_keypair "${dir}" "second"
  first_pub="${dir}/first.pub"
  second_pub="${dir}/second.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  sshd_bin="$(install_fixture_sshd "${dir}" "supported")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"
  mkdir -p "${root}/.ssh"
  printf 'ssh-ed25519 AAAAOTHERKEYBLOB000000000000000000000000000 admin@laptop\n' \
    > "${root}/.ssh/authorized_keys"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${first_pub}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
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

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${second_pub}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
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
  local dir os_release pubkey systemctl_bin systemctl_dir sshd_bin root script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  sshd_bin="$(install_fixture_sshd "${dir}" "supported")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the deploy must succeed: ${output}" || return 1
  assert_contains "${output}" "KEY_MODE:restrict" \
    "when sshd supports it (OpenSSH >= 7.2), the deploy must prefer restrict" || return 1
  assert_contains "$(cat "${root}/.ssh/authorized_keys")" 'restrict,command="/storage/.config/kodi-lifecycle"' \
    "the installed entry must use the restrict syntax"
}

test_deploy_uses_explicit_restrictions_when_restrict_is_unsupported() {
  local dir os_release pubkey systemctl_bin systemctl_dir sshd_bin root script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  sshd_bin="$(install_fixture_sshd "${dir}" "unsupported")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the deploy must succeed via the fallback: ${output}" || return 1
  assert_contains "${output}" "KEY_MODE:fallback" \
    "when sshd predates OpenSSH 7.2, the deploy must use the fallback" || return 1
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
  assert_contains "$(cat "${report_dir}"/*.txt)" "file_rollback_state=rolled-back" \
    "the report must record that file rollback succeeded (finding I4)" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "service_restore_state=restored" \
    "restoring to a stopped initial state never depends on the broken start path (finding I4)" || return 1

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

# --- Fix round 1 helpers --------------------------------------------------

# Reads the transaction path a fixture root's pending-transaction pointer
# currently names.
current_transaction_pointer() {
  local root="$1"
  cat "${root}/.cache/kodi-lifecycle/current-transaction"
}

# Runs the deploy transaction directly (no SSH involved) against a fresh
# fixture root and leaves it pending-verification: a real transaction
# directory, with a real manifest and rollback markers, and a real pointer
# file, exactly as a genuine in-flight deployment would. Used by tests that
# need a legitimate transaction to attack or recover, without re-deriving
# one through the full CLI each time.
deploy_to_pending_verification() {
  local dir="$1" root="$2" os_release="$3" pubkey="$4" systemctl_dir="$5"
  local script output rc sshd_bin
  sshd_bin="$(install_fixture_sshd "${dir}" "supported")"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the setup deploy must reach pending-verification: ${output}"
}

partial_backup_is_rejected() (
  local copy_rc="$1" root os_release systemctl_bin sshd_bin script output rc transaction
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' EXIT
  generate_fixture_keypair "${dir}" "controller"
  root="${dir}/root"
  os_release="${dir}/os-release"
  write_fixture_os_release "${os_release}"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  sshd_bin="$(install_fixture_sshd "${dir}" "supported")"
  mkdir -p "${root}/.config" "${root}/.ssh" "${dir}/fault-bin"
  printf 'HEALTHY_WRAPPER\n' > "${root}/.config/kodi-lifecycle"
  printf 'ADMINISTRATOR_ACCESS_MUST_SURVIVE\n' > "${root}/.ssh/authorized_keys"
  cat > "${dir}/fault-bin/cp" <<'STUB'
#!/bin/bash
if [[ "$#" -eq 3 && "$2" == */.ssh/authorized_keys && "$3" == */rollback/authorized_keys* ]]; then
  printf 'partial\n' > "$3"
  exit "${PARTIAL_BACKUP_RC:?}"
fi
exec /bin/cp "$@"
STUB
  chmod +x "${dir}/fault-bin/cp"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" \
    "${os_release}" "${dir}/controller.pub" "${systemctl_bin}" "${sshd_bin}")"
  set +e
  output="$(printf '%s\n' "${script}" | PARTIAL_BACKUP_RC="${copy_rc}" \
    FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${dir}/fault-bin:$(dirname "${systemctl_bin}"):${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "partial backup must fail before installation" || return 1
  assert_eq "ADMINISTRATOR_ACCESS_MUST_SURVIVE" "$(cat "${root}/.ssh/authorized_keys")" \
    "a partial pre-image must never replace healthy administrator access" || return 1
  assert_eq "HEALTHY_WRAPPER" "$(cat "${root}/.config/kodi-lifecycle")" || return 1
  assert_contains "${output}" "DEPLOY_STATE:incomplete-rollback" || return 1
  transaction="$(current_transaction_pointer "${root}")"
  [[ ! -f "${transaction}/backups-complete" ]] || return 1
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script rollback "${root}")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "manual recovery must also refuse incomplete pre-images" || return 1
  assert_eq "ADMINISTRATOR_ACCESS_MUST_SURVIVE" "$(cat "${root}/.ssh/authorized_keys")"
)

test_failed_partial_authorized_keys_backup_never_overwrites_live_keys() {
  partial_backup_is_rejected 1
}

test_successful_short_backup_copy_is_rejected_before_install() {
  partial_backup_is_rejected 0
}

interrupted_verification_restores_service() (
  local initial="$1" changed="$2" root systemctl_bin os_release script output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' EXIT
  generate_fixture_keypair "${dir}" "controller"
  root="${dir}/root"
  os_release="${dir}/os-release"
  write_fixture_os_release "${os_release}"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  set_fixture_active_state "${dir}" "${initial}"
  mkdir -p "${root}/.config" "${root}/.ssh"
  printf 'ORIGINAL_WRAPPER\n' > "${root}/.config/kodi-lifecycle"
  printf 'ORIGINAL_KEYS\n' > "${root}/.ssh/authorized_keys"
  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" \
    "${dir}/controller.pub" "$(dirname "${systemctl_bin}")"

  # The deploying client has disappeared after one verification command.
  # Recovery has only the on-device journal, not that client's variables.
  set_fixture_active_state "${dir}" "${changed}"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script rollback "${root}")"
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="$(dirname "${systemctl_bin}"):${PATH}" sh -s 2>&1)"
  assert_eq "${initial}" "$(cat "${dir}/systemctl-config/active-state")" \
    "explicit rollback must recover the original service state after interrupted verification"
  assert_eq "ORIGINAL_WRAPPER" "$(cat "${root}/.config/kodi-lifecycle")"
  assert_eq "ORIGINAL_KEYS" "$(cat "${root}/.ssh/authorized_keys")"
  assert_contains "${output}" "SERVICE_RESTORE_STATE:restored:"
  [[ ! -e "${root}/.cache/kodi-lifecycle/current-transaction" ]]
)

test_interrupted_verification_rollback_restores_running_service() {
  interrupted_verification_restores_service active inactive
}

test_interrupted_verification_rollback_restores_stopped_service() {
  interrupted_verification_restores_service inactive active
}

test_finalize_retries_after_pointer_unlink_failure() {
  local dir root os_release systemctl_bin transaction script inspect output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  os_release="${dir}/os-release"
  generate_fixture_keypair "${dir}" "controller"
  write_fixture_os_release "${os_release}"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" \
    "${dir}/controller.pub" "$(dirname "${systemctl_bin}")"
  transaction="$(current_transaction_pointer "${root}")"
  mkdir -p "${dir}/fault-bin"
  cat > "${dir}/fault-bin/rm" <<'STUB'
#!/bin/bash
for argument in "$@"; do
  [[ "${argument}" == */current-transaction ]] && exit 1
done
exec /bin/rm "$@"
STUB
  chmod +x "${dir}/fault-bin/rm"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}" "${transaction}")"
  set +e
  output="$(printf '%s\n' "${script}" | PATH="${dir}/fault-bin:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "pointer unlink failure must not be success" || return 1
  [[ ! -e "${transaction}" && -f "${root}/.cache/kodi-lifecycle/current-transaction" ]] || return 1
  inspect="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script inspect "${root}")"
  output="$(printf '%s\n' "${inspect}" | sh -s)"
  assert_contains "${output}" "INSPECT_STATE:cleanup-pending" "inspection must recognize durable finalize evidence" || return 1
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "retry must finish the authenticated dangling-pointer cleanup: ${output}" || return 1
  assert_contains "${output}" "FINALIZE_STATE:committed" || return 1
  [[ ! -e "${root}/.cache/kodi-lifecycle/current-transaction" ]]
}

test_verified_rollback_cleanup_retries_after_pointer_unlink_failure() {
  local dir root os_release systemctl_bin transaction script inspect output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  os_release="${dir}/os-release"
  generate_fixture_keypair "${dir}" "controller"
  write_fixture_os_release "${os_release}"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" \
    "${dir}/controller.pub" "$(dirname "${systemctl_bin}")"
  transaction="$(current_transaction_pointer "${root}")"
  set_fixture_active_state "${dir}" "active"
  mkdir -p "${dir}/fault-bin"
  cat > "${dir}/fault-bin/rm" <<'STUB'
#!/bin/bash
for argument in "$@"; do
  [[ "${argument}" == */current-transaction ]] && exit 1
done
exec /bin/rm "$@"
STUB
  chmod +x "${dir}/fault-bin/rm"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script rollback "${root}" "${transaction}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${dir}/fault-bin:$(dirname "${systemctl_bin}"):${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" || return 1
  assert_eq "inactive" "$(cat "${dir}/systemctl-config/active-state")" || return 1
  [[ ! -e "${transaction}" && -f "${root}/.cache/kodi-lifecycle/current-transaction" ]] || return 1
  inspect="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script inspect "${root}")"
  output="$(printf '%s\n' "${inspect}" | sh -s)"
  assert_contains "${output}" "INSPECT_STATE:cleanup-pending" "inspection must recognize previously verified rollback" || return 1
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "previously verified rollback must not strand a dangling recovery pointer: ${output}" || return 1
  assert_contains "${output}" "ROLLBACK_STATE:rolled-back" || return 1
  [[ ! -e "${root}/.cache/kodi-lifecycle/current-transaction" ]]
}

test_finalize_lost_response_retry_is_identity_checked() {
  local dir root os_release systemctl_bin transaction script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  os_release="${dir}/os-release"
  generate_fixture_keypair "${dir}" "controller"
  write_fixture_os_release "${os_release}"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" \
    "${dir}/controller.pub" "$(dirname "${systemctl_bin}")"
  transaction="$(current_transaction_pointer "${root}")"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}" "${transaction}")"
  printf '%s\n' "${script}" | sh -s >/dev/null
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a lost response must be retryable with its exact committed identity: ${output}" || return 1
  assert_contains "${output}" "FINALIZE_STATE:committed" || return 1
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}" "${transaction}-other")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a receipt must not certify a different transaction" || return 1
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}")"
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  assert_contains "${output}" "FINALIZE_STATE:committed"
}

test_finalize_without_pending_or_receipt_fails_closed() {
  local dir script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  mkdir -p "${dir}/root/backup/kodi-lifecycle" "${dir}/root/.cache/kodi-lifecycle"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${dir}/root")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" || return 1
  assert_contains "${output}" "FINALIZE_FAIL:no-pending-transaction"
}

test_finalize_missing_transaction_requires_cleanup_receipt() {
  local dir root os_release systemctl_bin transaction script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  os_release="${dir}/os-release"
  generate_fixture_keypair "${dir}" "controller"
  write_fixture_os_release "${os_release}"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" \
    "${dir}/controller.pub" "$(dirname "${systemctl_bin}")"
  transaction="$(current_transaction_pointer "${root}")"
  rm -rf "${transaction}"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}" "${transaction}")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "missing backups alone do not prove successful finalize" || return 1
  assert_eq "${transaction}" "$(current_transaction_pointer "${root}")"
}

test_finalized_transaction_identity_is_not_reused_within_one_second() {
  local dir root os_release systemctl_bin first second script
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/root"
  os_release="${dir}/os-release"
  generate_fixture_keypair "${dir}" "controller"
  write_fixture_os_release "${os_release}"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  cat > "$(dirname "${systemctl_bin}")/date" <<'STUB'
#!/bin/bash
if [[ "${2:-}" == '+%Y%m%dT%H%M%SZ' ]]; then
  printf '20260911T000000Z\n'
else
  exec /bin/date "$@"
fi
STUB
  chmod +x "$(dirname "${systemctl_bin}")/date"
  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" \
    "${dir}/controller.pub" "$(dirname "${systemctl_bin}")"
  first="$(current_transaction_pointer "${root}")"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}" "${first}")"
  printf '%s\n' "${script}" | sh -s >/dev/null
  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" \
    "${dir}/controller.pub" "$(dirname "${systemctl_bin}")"
  second="$(current_transaction_pointer "${root}")"
  [[ "${first}" != "${second}" ]] || {
    printf 'completed transaction identity was reused; stale finalize could commit a new deployment\n' >&2
    return 1
  }
}

# --- Finding C1: rollback/finalize must never accept an arbitrary path ---

test_rollback_refuses_explicit_transaction_outside_backup_root() {
  local dir root os_release pubkey systemctl_bin systemctl_dir transaction script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" "${pubkey}" "${systemctl_dir}" || return 1
  transaction="$(current_transaction_pointer "${root}")"

  for candidate in "${root}" "${root}/backup" "${root}/backup/kodi-lifecycle" \
      "${root}/backup/kodi-lifecycle/../../etc"; do
    script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script rollback "${root}" "${candidate}")"
    set +e
    output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "a candidate outside the backup root must be refused: ${candidate}: ${output}" || return 1
    assert_contains "${output}" "ROLLBACK_FAIL:invalid-transaction-path" \
      "the refusal names the path-validation failure for: ${candidate}" || return 1
  done

  if [[ "$(current_transaction_pointer "${root}")" != "${transaction}" ]]; then
    printf 'the pointer must be unchanged after refused rollback attempts\n' >&2
    return 1
  fi
  if [[ ! -f "${transaction}/manifest" ]]; then
    printf 'the legitimate transaction must be untouched after refused rollback attempts\n' >&2
    return 1
  fi
}

test_rollback_refuses_explicit_transaction_not_matching_pointer() {
  local dir root os_release pubkey systemctl_bin systemctl_dir pointer_transaction sibling script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" "${pubkey}" "${systemctl_dir}" || return 1
  pointer_transaction="$(current_transaction_pointer "${root}")"

  # A second, well-formed-looking transaction directory that the pointer
  # does not name -- e.g. left over from an interrupted prior run.
  sibling="${root}/backup/kodi-lifecycle/20200101T000000Z"
  mkdir -p "${sibling}/rollback"
  printf 'MANIFEST_VERSION=1\nTRANSACTION=%s\n' "${sibling}" > "${sibling}/manifest"
  : > "${sibling}/rollback/wrapper.absent"
  : > "${sibling}/rollback/authorized_keys.absent"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script rollback "${root}" "${sibling}")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a well-formed but non-pointer transaction must be refused: ${output}" || return 1
  assert_contains "${output}" "ROLLBACK_FAIL:transaction-pointer-mismatch" \
    "the refusal names the pointer mismatch" || return 1

  if [[ "$(current_transaction_pointer "${root}")" != "${pointer_transaction}" ]]; then
    printf 'the pointer must be unchanged after a refused mismatched rollback\n' >&2
    return 1
  fi
  if [[ ! -d "${sibling}" ]]; then
    printf 'the sibling transaction must not be deleted by a refused rollback\n' >&2
    return 1
  fi
  if [[ ! -f "${pointer_transaction}/manifest" ]]; then
    printf 'the legitimate pointer transaction must be untouched\n' >&2
    return 1
  fi
}

test_rollback_refuses_when_manifest_incomplete() {
  local dir root os_release pubkey systemctl_bin systemctl_dir transaction original_wrapper original_keys script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" "${pubkey}" "${systemctl_dir}" || return 1
  transaction="$(current_transaction_pointer "${root}")"
  original_wrapper="$(cat "${root}/.config/kodi-lifecycle")"
  original_keys="$(cat "${root}/.ssh/authorized_keys")"
  rm -f "${transaction}/manifest"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script rollback "${root}")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a transaction missing its manifest must be refused: ${output}" || return 1
  assert_contains "${output}" "ROLLBACK_FAIL:incomplete-manifest" \
    "the refusal names the incomplete manifest" || return 1

  assert_eq "${original_wrapper}" "$(cat "${root}/.config/kodi-lifecycle")" \
    "the live wrapper must be untouched when the manifest is incomplete" || return 1
  assert_eq "${original_keys}" "$(cat "${root}/.ssh/authorized_keys")" \
    "the live authorized_keys must be untouched when the manifest is incomplete" || return 1
  if [[ ! -d "${transaction}" ]]; then
    printf 'the transaction directory must be retained, not deleted, when the manifest is incomplete\n' >&2
    return 1
  fi
  if [[ ! -f "${root}/.cache/kodi-lifecycle/current-transaction" ]]; then
    printf 'the pointer must be retained when the manifest is incomplete\n' >&2
    return 1
  fi
}

test_finalize_refuses_mismatched_or_invalid_explicit_transaction() {
  local dir root os_release pubkey systemctl_bin systemctl_dir transaction sibling script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" "${pubkey}" "${systemctl_dir}" || return 1
  transaction="$(current_transaction_pointer "${root}")"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}" "${root}")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a finalize on a path outside the backup root must be refused: ${output}" || return 1
  assert_contains "${output}" "FINALIZE_FAIL:invalid-transaction-path" \
    "the refusal names the path-validation failure" || return 1
  if [[ ! -d "${transaction}" ]]; then
    printf 'the transaction must not be deleted by a refused finalize\n' >&2
    return 1
  fi

  sibling="${root}/backup/kodi-lifecycle/20200101T000000Z"
  mkdir -p "${sibling}/rollback"
  printf 'MANIFEST_VERSION=1\nTRANSACTION=%s\n' "${sibling}" > "${sibling}/manifest"
  : > "${sibling}/rollback/wrapper.absent"
  : > "${sibling}/rollback/authorized_keys.absent"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}" "${sibling}")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a finalize on a non-pointer transaction must be refused: ${output}" || return 1
  assert_contains "${output}" "FINALIZE_FAIL:transaction-pointer-mismatch" \
    "the refusal names the pointer mismatch" || return 1
  if [[ ! -d "${transaction}" || ! -d "${sibling}" ]]; then
    printf 'neither transaction may be deleted by a refused finalize\n' >&2
    return 1
  fi

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}" "${transaction}")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a finalize matching the pointer must succeed: ${output}" || return 1
  assert_contains "${output}" "FINALIZE_STATE:committed" "the matching finalize commits" || return 1
  if [[ -d "${transaction}" ]]; then
    printf 'the matching transaction must be removed after a successful finalize\n' >&2
    return 1
  fi
  if [[ -f "${root}/.cache/kodi-lifecycle/current-transaction" ]]; then
    printf 'the pointer must be cleared after a successful finalize\n' >&2
    return 1
  fi
}

# --- Finding C2: never mislabel an unknown/refused outcome as rolled-back -

test_deploy_refused_reports_platform_check_failure_without_mutation() {
  local dir root os_release systemctl_bin systemctl_dir ssh_bin report_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"
  root="${dir}/root"
  os_release="${dir}/os-release"
  write_fixture_os_release "${os_release}" "0"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  ssh_bin="$(install_lifecycle_ssh_stub "${dir}")"
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
  assert_failure "${rc}" "a platform-check failure must not be reported as success: ${output}" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=refused" \
    "a platform-check failure must be reported as refused, never rolled-back" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "refusal_reason=PLATFORM_CHECK_FAIL" \
    "the report names the platform-check refusal reason" || return 1
  assert_not_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=rolled-back" \
    "a pre-mutation refusal must never claim a rollback occurred" || return 1

  for path in "${root}/.config" "${root}/.ssh" "${root}/backup" "${root}/.cache"; do
    if [[ -e "${path}" ]]; then
      printf 'a platform-check refusal must never mutate the target: %s exists\n' "${path}" >&2
      return 1
    fi
  done
}

test_deploy_refused_reports_key_mode_check_failure_without_mutation() {
  local dir root os_release systemctl_bin systemctl_dir sshd_bin ssh_bin report_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller"
  root="${dir}/root"
  os_release="${dir}/os-release"
  write_fixture_os_release "${os_release}" "1"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  sshd_bin="$(install_fixture_sshd "${dir}" "malformed")"
  ssh_bin="$(install_lifecycle_ssh_stub "${dir}")"
  report_dir="${dir}/reports"

  set +e
  output="$(LIFECYCLE_FIXTURE_ROOT="${root}" LIFECYCLE_FIXTURE_OS_RELEASE="${os_release}" \
    LIFECYCLE_FIXTURE_BIN_DIR="${systemctl_dir}" FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    LIFECYCLE_FIXTURE_SSHD="${sshd_bin}" \
    PATH="${ssh_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" \
    --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a key-mode-check failure must not be reported as success: ${output}" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=refused" \
    "a key-mode-check failure must be reported as refused, never rolled-back" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "refusal_reason=KEY_MODE_CHECK_FAIL" \
    "the report names the key-mode-check refusal reason" || return 1

  for path in "${root}/.config" "${root}/.ssh" "${root}/backup" "${root}/.cache"; do
    if [[ -e "${path}" ]]; then
      printf 'a key-mode-check refusal must never mutate the target: %s exists\n' "${path}" >&2
      return 1
    fi
  done
}

test_deploy_refused_with_pending_transaction_surfaces_existing_path() {
  local dir root os_release systemctl_bin systemctl_dir ssh_bin report_dir output rc transaction
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

  generate_fixture_keypair "${dir}" "admin"
  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" "${dir}/admin.pub" "${systemctl_dir}" || return 1
  transaction="$(current_transaction_pointer "${root}")"

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
  assert_failure "${rc}" "a deploy over a pending transaction must not succeed: ${output}" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=refused" \
    "a pending-transaction refusal must be reported as refused" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "refusal_reason=pending-transaction" \
    "the report names the pending-transaction refusal reason" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "transaction=${transaction}" \
    "the report surfaces the existing transaction's exact path" || return 1
  assert_contains "${output}" "--rollback-transaction ${transaction}" \
    "a targeted rollback recovery command is printed even for this refusal" || return 1
  assert_contains "${output}" "--inspect-transaction ${transaction}" \
    "a targeted inspect recovery command is printed even for this refusal"
}

test_unknown_deploy_output_is_never_labeled_rolled_back() {
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
    LIFECYCLE_SABOTAGE_DEPLOY_OUTPUT="1" \
    PATH="${ssh_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" \
    --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an unparseable deploy response must not be reported as success: ${output}" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=unknown" \
    "an unparseable deploy response must be reported as unknown" || return 1
  assert_not_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=rolled-back" \
    "an unknown outcome must never be assumed to be a completed rollback" || return 1
  assert_contains "${output}" "--inspect-transaction" \
    "an unknown outcome still prints an inspect recovery command" || return 1
  if grep -q -- "--inspect-transaction ${root}" <<<"${output}"; then
    printf 'an unknown outcome must use the no-argument recovery form, not a guessed path\n' >&2
    return 1
  fi
}

# --- Finding I3: a finalize cleanup failure must never suggest a rollback -

test_finalize_cleanup_failure_reports_committed_cleanup_pending_and_retries() {
  local dir root os_release systemctl_bin systemctl_dir ssh_bin report_dir output rc transaction
  dir="$(make_scratch_dir)"
  trap 'chmod -R u+w "${root}/backup" 2>/dev/null || true; rm -rf -- "${dir}"' RETURN
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
    LIFECYCLE_SABOTAGE_FINALIZE="1" \
    PATH="${ssh_bin}:${PATH}" "${CONFIGURE_KODI_LIFECYCLE_CLI}" \
    --target 127.0.0.1 \
    --controller-public-key "${dir}/controller.pub" \
    --controller-identity "${dir}/controller" \
    --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a finalize cleanup failure must not be reported as a full success: ${output}" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=committed-cleanup-pending" \
    "a verified install with a finalize cleanup failure must not suggest a rollback" || return 1
  assert_not_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=incomplete-rollback" \
    "a finalize cleanup failure is never an incomplete rollback" || return 1
  assert_contains "${output}" "--finalize-transaction" \
    "the recovery command retries finalize, not rollback" || return 1

  transaction="$(current_transaction_pointer "${root}")"
  chmod -R u+w "${root}/backup"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script finalize "${root}" "${transaction}")"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "retrying finalize after the fault clears must succeed: ${output}" || return 1
  assert_contains "${output}" "FINALIZE_STATE:committed" "the retried finalize commits" || return 1
  if [[ -d "${transaction}" ]]; then
    printf 'the transaction must be removed once the retried finalize succeeds\n' >&2
    return 1
  fi
}

# --- Finding I4: a failed verification must also restore the service ------

test_failed_verification_with_running_initial_state_reports_incomplete_rollback_on_service_restore_mismatch() {
  local dir root os_release systemctl_bin systemctl_dir ssh_bin report_dir output rc transaction script
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
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=incomplete-rollback" \
    "a service-restore mismatch must not be reported as a completed rollback" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "file_rollback_state=rolled-back" \
    "file rollback is independent of the broken start path and must still succeed" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "service_restore_state=mismatch" \
    "the report must record the service-restore mismatch distinctly (finding I4)" || return 1
  [[ -f "${root}/.cache/kodi-lifecycle/current-transaction" ]] || {
    printf 'service restoration failed but its recovery pointer was deleted\n' >&2
    return 1
  }
  transaction="$(current_transaction_pointer "${root}")"
  [[ -f "${transaction}/manifest" && -f "${transaction}/backups-complete" ]] || return 1
  assert_contains "$(cat "${transaction}/manifest")" "INITIAL_STATE=running" || return 1
  assert_eq "rolling-back" "$(cat "${transaction}/phase")" || return 1

  set_fixture_fault_on_start "${dir}" "0"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script rollback "${root}" "${transaction}")"
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  assert_eq "active" "$(cat "${dir}/systemctl-config/active-state")" || return 1
  assert_contains "${output}" "ROLLBACK_STATE:rolled-back" || return 1
  [[ ! -e "${transaction}" && ! -e "${root}/.cache/kodi-lifecycle/current-transaction" ]]
}

# --- Finding I5: fail closed on an unusable sshd version probe ------------

test_key_mode_check_fails_closed_on_unavailable_or_malformed_sshd() {
  local dir os_release pubkey systemctl_bin systemctl_dir root script output rc sshd_bin
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"

  root="${dir}/root-unavailable"
  sshd_bin="$(install_fixture_sshd "${dir}/unavailable-case" "unavailable")"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a missing sshd must refuse the deploy: ${output}" || return 1
  assert_contains "${output}" "KEY_MODE_CHECK_FAIL:sshd-not-found" \
    "the refusal names the missing sshd binary" || return 1
  if [[ -e "${root}/.ssh" || -e "${root}/.config" ]]; then
    printf 'a missing-sshd refusal must never mutate the target\n' >&2
    return 1
  fi

  root="${dir}/root-malformed"
  sshd_bin="$(install_fixture_sshd "${dir}/malformed-case" "malformed")"
  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an unparseable sshd version must refuse the deploy: ${output}" || return 1
  assert_contains "${output}" "KEY_MODE_CHECK_FAIL:version-unparseable" \
    "the refusal names the unparseable version" || return 1
  if [[ -e "${root}/.ssh" || -e "${root}/.config" ]]; then
    printf 'an unparseable-version refusal must never mutate the target\n' >&2
    return 1
  fi
}

# --- Finding I6: rollback restoration is atomic, never in-place -----------

test_rollback_restoration_replaces_a_symlinked_target_without_following_it() {
  local dir root os_release pubkey systemctl_bin systemctl_dir transaction canary script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  mkdir -p "${root}/.config" "${root}/.ssh"
  printf 'ORIGINAL_WRAPPER\n' > "${root}/.config/kodi-lifecycle"
  chmod 700 "${root}/.config/kodi-lifecycle"
  printf 'ORIGINAL_KEYS\n' > "${root}/.ssh/authorized_keys"
  chmod 600 "${root}/.ssh/authorized_keys"

  deploy_to_pending_verification "${dir}" "${root}" "${os_release}" "${pubkey}" "${systemctl_dir}" || return 1
  transaction="$(current_transaction_pointer "${root}")"

  printf 'CANARY-UNTOUCHED\n' > "${dir}/canary"
  rm -f "${root}/.config/kodi-lifecycle"
  ln -s "${dir}/canary" "${root}/.config/kodi-lifecycle"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script rollback "${root}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the rollback must succeed even with a symlinked target: ${output}" || return 1
  assert_contains "${output}" "ROLLBACK_STATE:rolled-back" "the rollback commits" || return 1

  if [[ -L "${root}/.config/kodi-lifecycle" ]]; then
    printf 'the rollback must replace a symlinked target with a real file, not write through it\n' >&2
    return 1
  fi
  assert_eq "ORIGINAL_WRAPPER" "$(cat "${root}/.config/kodi-lifecycle")" \
    "the restored wrapper content must exactly match the original" || return 1
  assert_eq "CANARY-UNTOUCHED" "$(cat "${dir}/canary")" \
    "the symlink target outside the tree must never be written through"
}

# --- Finding I7: deploy's own self-rollback must verify before reporting --

test_deploy_self_rollback_restores_and_verifies_before_reporting_rolled_back() {
  local dir root os_release pubkey systemctl_bin systemctl_dir sshd_bin fake_python_dir real_python script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "admin"
  pubkey="${dir}/admin.pub"
  systemctl_bin="$(install_lifecycle_systemctl_fixture "${dir}")"
  systemctl_dir="$(dirname "${systemctl_bin}")"
  sshd_bin="$(install_fixture_sshd "${dir}" "supported")"
  os_release="${dir}/etc/os-release"
  write_fixture_os_release "${os_release}" "1"
  root="${dir}/root"

  mkdir -p "${root}/.config" "${root}/.ssh"
  printf 'ORIGINAL_WRAPPER\n' > "${root}/.config/kodi-lifecycle"
  chmod 700 "${root}/.config/kodi-lifecycle"
  printf 'ORIGINAL_KEYS\n' > "${root}/.ssh/authorized_keys"
  chmod 600 "${root}/.ssh/authorized_keys"

  # Fail only the atomic candidate writer, after validated backups exist.
  fake_python_dir="${dir}/fake-python-bin"
  mkdir -p "${fake_python_dir}"
  real_python="$(command -v python3)"
  cat > "${fake_python_dir}/python3" <<FAKESTUB
#!/bin/bash
[[ "\${1:-}" == */atomic-write.py ]] && exit 1
exec "${real_python}" "\$@"
FAKESTUB
  chmod +x "${fake_python_dir}/python3"

  script="$("${CONFIGURE_KODI_LIFECYCLE_CLI}" --emit-remote-script deploy "${root}" "${os_release}" "${pubkey}" \
    "/usr/bin/systemctl" "${sshd_bin}")"
  set +e
  output="$(printf '%s\n' "${script}" | FIXTURE_SYSTEMCTL_CONFIG_DIR="${dir}/systemctl-config" \
    PATH="${fake_python_dir}:${systemctl_dir}:${PATH}" sh -s 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a mutation-phase failure must not be reported as a successful deploy: ${output}" || return 1
  assert_contains "${output}" "DEPLOY_STATE:rolled-back:write-wrapper-candidate-failed" \
    "the self-rollback names the mutation that failed" || return 1

  assert_eq "ORIGINAL_WRAPPER" "$(cat "${root}/.config/kodi-lifecycle")" \
    "the wrapper must be restored to its exact original content" || return 1
  assert_eq "ORIGINAL_KEYS" "$(cat "${root}/.ssh/authorized_keys")" \
    "authorized_keys must be restored to its exact original content" || return 1
  if [[ -f "${root}/.cache/kodi-lifecycle/current-transaction" ]]; then
    printf 'a verified self-rollback must clear the pointer\n' >&2
    return 1
  fi
  if compgen -G "${root}/backup/kodi-lifecycle/*" > /dev/null 2>&1; then
    printf 'a verified self-rollback must remove the transaction directory\n' >&2
    return 1
  fi
}

# --- Finding I8: the controller transport and its deadline are tested -----

test_run_with_deadline_terminates_a_hung_command() {
  local start end elapsed rc
  start="$(date +%s)"
  set +e
  coreelec_lifecycle_run_with_deadline 1 sleep 20
  rc=$?
  set -e
  end="$(date +%s)"
  elapsed=$((end - start))
  assert_failure "${rc}" "a command that outlives its deadline must not be reported as success" || return 1
  if [[ "${elapsed}" -ge 10 ]]; then
    printf 'run_with_deadline must terminate near its deadline, not wait for the full command (took %ss)\n' \
      "${elapsed}" >&2
    return 1
  fi
}

test_controller_transport_uses_hardened_ssh_options_and_controller_identity() {
  local dir recording_bin argv_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  recording_bin="${dir}/recording-ssh-bin"
  mkdir -p "${recording_bin}"
  argv_file="${dir}/ssh-argv.log"
  cat > "${recording_bin}/ssh" <<STUB
#!/bin/bash
: > "${argv_file}"
for argument in "\$@"; do
  printf '%s\n' "\${argument}" >> "${argv_file}"
done
printf 'running\n'
exit 0
STUB
  chmod +x "${recording_bin}/ssh"

  generate_fixture_keypair "${dir}" "controller"
  local out rc
  TARGET="192.0.2.10"
  SSH_PORT="22"
  CONTROLLER_IDENTITY="${dir}/controller"
  KNOWN_HOSTS_FILE="${dir}/known_hosts"
  : > "${KNOWN_HOSTS_FILE}"
  set +e
  out="$(PATH="${recording_bin}:${PATH}" coreelec_lifecycle_ssh_controller "status")"
  rc=$?
  set -e
  assert_success "${rc}" "the controller transport call must succeed against the recording stub" || return 1
  assert_eq "running" "${out}" "the controller transport returns the remote command's stdout" || return 1

  local recorded
  recorded="$(cat "${argv_file}")"
  assert_contains "${recorded}" "-p
22" "the controller transport passes -p SSH_PORT" || return 1
  assert_contains "${recorded}" "BatchMode=yes" "the controller transport requires BatchMode=yes" || return 1
  assert_contains "${recorded}" "ConnectTimeout=12" "the controller transport bounds connection time" || return 1
  assert_contains "${recorded}" "ConnectionAttempts=1" "the controller transport allows only one attempt" || return 1
  assert_contains "${recorded}" "StrictHostKeyChecking=yes" \
    "the controller transport never auto-accepts a new host key" || return 1
  assert_contains "${recorded}" "UserKnownHostsFile=${KNOWN_HOSTS_FILE}" \
    "the controller transport uses its own known_hosts file" || return 1
  assert_contains "${recorded}" "${CONTROLLER_IDENTITY}" \
    "the controller transport uses the controller identity" || return 1
  assert_contains "${recorded}" "IdentitiesOnly=yes" \
    "the controller transport never falls back to an ssh-agent identity" || return 1
  assert_contains "${recorded}" "root@${TARGET}" "the controller transport targets the right host" || return 1
  assert_not_contains "${recorded}" "${IDENTITY_FILE:-coreelec_admin_ed25519}" \
    "the controller transport must never use the administrator identity"
}

# --- Finding I9: key-mismatch and failed-service refusal regressions ------

test_mismatched_controller_key_pair_is_rejected_before_any_ssh_call() {
  local dir bogus_bin report_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  generate_fixture_keypair "${dir}" "controller_a"
  generate_fixture_keypair "${dir}" "controller_b"
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
    --controller-public-key "${dir}/controller_a.pub" \
    --controller-identity "${dir}/controller_b" \
    --report-dir "${report_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a mismatched controller key pair must be rejected: ${output}" || return 1
  assert_contains "${output}" "does not match" "the CLI explains the key-pair mismatch" || return 1
  if [[ -e "${dir}/ssh-was-called" ]]; then
    printf 'a key-pair mismatch must be rejected before any ssh call\n' >&2
    return 1
  fi
  if compgen -G "${report_dir}/*.txt" > /dev/null 2>&1; then
    printf 'a key-pair mismatch must never write a report\n' >&2
    return 1
  fi
}

test_kodi_service_failed_refuses_before_any_mutation() {
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
  set_fixture_failed "${dir}" "1"
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
  assert_failure "${rc}" "a deploy against a failed kodi.service must be refused: ${output}" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "deployment_state=refused" \
    "a failed-service refusal must be reported as refused" || return 1
  assert_contains "$(cat "${report_dir}"/*.txt)" "refusal_reason=kodi-service-failed" \
    "the report names the kodi-service-failed refusal reason" || return 1

  for path in "${root}/.config" "${root}/.ssh" "${root}/backup" "${root}/.cache"; do
    if [[ -e "${path}" ]]; then
      printf 'a kodi-service-failed refusal must never mutate the target: %s exists\n' "${path}" >&2
      return 1
    fi
  done
}

run_all_tests \
  test_documented_host_bootstrap_requires_independent_fingerprint \
  test_verified_rollback_cleanup_retries_after_pointer_unlink_failure \
  test_recovery_dry_run_is_rejected_before_any_ssh \
  test_denial_verification_rejects_transport_and_wrong_denials \
  test_finalized_transaction_identity_is_not_reused_within_one_second \
  test_finalize_retries_after_pointer_unlink_failure \
  test_finalize_lost_response_retry_is_identity_checked \
  test_finalize_without_pending_or_receipt_fails_closed \
  test_finalize_missing_transaction_requires_cleanup_receipt \
  test_interrupted_verification_rollback_restores_running_service \
  test_interrupted_verification_rollback_restores_stopped_service \
  test_failed_partial_authorized_keys_backup_never_overwrites_live_keys \
  test_successful_short_backup_copy_is_rejected_before_install \
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
  test_report_never_contains_public_or_private_key_material \
  test_rollback_refuses_explicit_transaction_outside_backup_root \
  test_rollback_refuses_explicit_transaction_not_matching_pointer \
  test_rollback_refuses_when_manifest_incomplete \
  test_finalize_refuses_mismatched_or_invalid_explicit_transaction \
  test_deploy_refused_reports_platform_check_failure_without_mutation \
  test_deploy_refused_reports_key_mode_check_failure_without_mutation \
  test_deploy_refused_with_pending_transaction_surfaces_existing_path \
  test_unknown_deploy_output_is_never_labeled_rolled_back \
  test_finalize_cleanup_failure_reports_committed_cleanup_pending_and_retries \
  test_failed_verification_with_running_initial_state_reports_incomplete_rollback_on_service_restore_mismatch \
  test_key_mode_check_fails_closed_on_unavailable_or_malformed_sshd \
  test_rollback_restoration_replaces_a_symlinked_target_without_following_it \
  test_deploy_self_rollback_restores_and_verifies_before_reporting_rolled_back \
  test_run_with_deadline_terminates_a_hung_command \
  test_controller_transport_uses_hardened_ssh_options_and_controller_identity \
  test_mismatched_controller_key_pair_is_rejected_before_any_ssh_call \
  test_kodi_service_failed_refuses_before_any_mutation
