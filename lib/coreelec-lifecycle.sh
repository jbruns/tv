#!/bin/bash

# Renders the restricted Kodi lifecycle command contract used by later
# deployment and Home Assistant tasks: a forced-command wrapper that only
# ever runs `systemctl {start,stop,status} kodi.service`, and the matching
# authorized_keys entries that force every session through it.
#
# `die` is owned by the calling CLI, matching the existing library pattern.
# This library depends on `coreelec_public_key_line` from lib/coreelec-ssh.sh
# for the shared key grammar, and loads that sibling library itself below if
# the caller has not already sourced it, so this file can be sourced on its
# own.

if ! declare -F die >/dev/null 2>&1; then
  die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
  }
fi

# Loads the sibling SSH library for coreelec_public_key_line if it has not
# already been sourced by the caller. Resolved relative to this file's own
# location (matching the SCRIPT_DIR convention used by the CLIs), so sourcing
# this file directly -- the interface the brief documents -- always works,
# regardless of whether the caller pre-sourced lib/coreelec-ssh.sh. Sourcing
# lib/coreelec-ssh.sh is itself idempotent (it only defines functions), so
# this guard is an optimization, not a correctness requirement.
if ! declare -F coreelec_public_key_line >/dev/null 2>&1; then
  _COREELEC_LIFECYCLE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck source=lib/coreelec-ssh.sh
  source "${_COREELEC_LIFECYCLE_LIB_DIR}/coreelec-ssh.sh"
  unset _COREELEC_LIFECYCLE_LIB_DIR
fi

# Stable marker so later deployment tooling can find and replace this entry
# in authorized_keys regardless of the administrator key's own comment.
COREELEC_LIFECYCLE_KEY_MARKER="homeassistant-ugoos-kodi-lifecycle"
# The only program the forced command is ever allowed to name.
COREELEC_LIFECYCLE_FORCED_COMMAND="/storage/.config/kodi-lifecycle"

# Validates and normalizes the administrator public key file for lifecycle
# key installation. This is a thin wrapper: the grammar itself lives in
# coreelec_public_key_line, once, so this library never copies the regular
# expression that enforces it.
coreelec_lifecycle_validate_public_key() {
  local key_file="$1"
  [[ "$#" -eq 1 ]] || die "coreelec_lifecycle_validate_public_key requires one public key file"
  coreelec_public_key_line "${key_file}"
}

# Splits a normalized "type blob [comment]" public key line into type and
# blob only, discarding any original comment so the marker below is the only
# comment that reaches authorized_keys.
_coreelec_lifecycle_key_type_and_blob() {
  local public_key="$1" type blob
  type="$(printf '%s\n' "${public_key}" | awk '{print $1}')"
  blob="$(printf '%s\n' "${public_key}" | awk '{print $2}')"
  [[ -n "${type}" && -n "${blob}" ]] \
    || die "coreelec_lifecycle_key_entry requires a normalized public key line"
  printf '%s %s\n' "${type}" "${blob}"
}

# Renders the preferred authorized_keys entry: `restrict` alone already
# implies no-agent-forwarding, no-port-forwarding, no-pty, no-user-rc, and
# no-X11-forwarding on OpenSSH 7.2+, combined with a forced command that is
# the only program the key may ever run. Never add permitopen, environment,
# or an unrestricted command alongside it.
coreelec_lifecycle_key_entry() {
  local public_key="$1" type_and_blob
  [[ "$#" -eq 1 ]] || die "coreelec_lifecycle_key_entry requires one public key line"
  type_and_blob="$(_coreelec_lifecycle_key_type_and_blob "${public_key}")" || return 1
  printf 'restrict,command="%s" %s %s\n' \
    "${COREELEC_LIFECYCLE_FORCED_COMMAND}" "${type_and_blob}" "${COREELEC_LIFECYCLE_KEY_MARKER}"
}

# Renders the explicit fallback entry for OpenSSH releases older than 7.2,
# which do not understand the `restrict` keyword. Spells out the same
# restrictions individually and never adds permitopen, environment, or an
# unrestricted command.
coreelec_lifecycle_key_entry_fallback() {
  local public_key="$1" type_and_blob
  [[ "$#" -eq 1 ]] || die "coreelec_lifecycle_key_entry_fallback requires one public key line"
  type_and_blob="$(_coreelec_lifecycle_key_type_and_blob "${public_key}")" || return 1
  printf 'no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc,no-X11-forwarding,command="%s" %s %s\n' \
    "${COREELEC_LIFECYCLE_FORCED_COMMAND}" "${type_and_blob}" "${COREELEC_LIFECYCLE_KEY_MARKER}"
}

# Renders the forced-command wrapper. `systemctl_path` must be absolute; the
# only reason it is a parameter at all is so tests can point it at a fixture,
# production always renders it with /usr/bin/systemctl. The wrapper consumes
# only SSH_ORIGINAL_COMMAND values `start`, `stop`, or `status`, hardcodes the
# unit name, and never uses eval, so nothing beyond those three words can
# reach the shell that runs it.
coreelec_lifecycle_render_wrapper() {
  local systemctl_path="$1"
  [[ "$#" -eq 1 ]] || die "coreelec_lifecycle_render_wrapper requires one systemctl path"
  case "${systemctl_path}" in
    /*) ;;
    *) die "coreelec_lifecycle_render_wrapper requires an absolute systemctl path" ;;
  esac
  cat <<WRAPPER_HEADER
#!/bin/sh
set -eu

SYSTEMCTL="${systemctl_path}"
UNIT="kodi.service"
WRAPPER_HEADER
  cat <<'WRAPPER_BODY'

status() {
  state="$("${SYSTEMCTL}" is-active "${UNIT}" 2>/dev/null || true)"
  case "${state}" in
    active) printf 'running\n' ;;
    inactive)
      if "${SYSTEMCTL}" is-failed --quiet "${UNIT}"; then
        printf 'failed\n'
      else
        printf 'stopped\n'
      fi
      ;;
    failed) printf 'failed\n' ;;
    *)
      printf 'Unsupported kodi.service state: %s\n' "${state}" >&2
      return 3
      ;;
  esac
}

case "${SSH_ORIGINAL_COMMAND:-}" in
  start)
    "${SYSTEMCTL}" is-active --quiet "${UNIT}" || "${SYSTEMCTL}" start "${UNIT}"
    status
    ;;
  stop)
    "${SYSTEMCTL}" is-active --quiet "${UNIT}" && "${SYSTEMCTL}" stop "${UNIT}"
    status
    ;;
  status) status ;;
  *)
    printf 'Allowed commands: start, stop, status\n' >&2
    exit 2
    ;;
esac
WRAPPER_BODY
}

# --- Transactional deployment: remote administrator programs -------------
#
# These render the small, independently recoverable POSIX `sh` programs the
# deployment CLI streams to the device's `sh -s` over the administrator SSH
# connection (see `coreelec_ssh_batch`). They intentionally do not share a
# combined prologue/epilogue with the add-on deployment transaction: this
# transaction only ever touches two paths, so each program restates its own
# small amount of setup rather than importing that larger machinery.
#
# Namespace on the device:
#   /storage/backup/kodi-lifecycle/<UTC timestamp>/         one dated
#     transaction directory, holding rollback/ (pre-images or *.absent
#     markers for the wrapper and authorized_keys)
#   /storage/.cache/kodi-lifecycle/current-transaction       pointer file
#     naming the pending transaction directory; its presence is what makes a
#     transaction "pending verification", and its removal is what finalize
#     and a successful rollback both do to close one out.

# A parser for /etc/os-release content is deliberately not used: only the
# literal substrings the brief specifies are required, matching this
# repository's existing (grep-based) platform identity convention rather than
# adding a new one.
_coreelec_lifecycle_remote_platform_check() {
  cat <<'PLATFORM_CHECK'
os_release_content="$(cat "${os_release_path}" 2>/dev/null || true)"
case "${os_release_content}" in
  *'CoreELEC'*) ;;
  *) printf 'PLATFORM_CHECK_FAIL:not-coreelec\n' >&2; exit 12 ;;
esac
case "${os_release_content}" in
  *'21.3'*) ;;
  *) printf 'PLATFORM_CHECK_FAIL:not-21.3\n' >&2; exit 12 ;;
esac
case "${os_release_content}" in
  *'Amlogic-ng'*) ;;
  *) printf 'PLATFORM_CHECK_FAIL:not-amlogic-ng\n' >&2; exit 12 ;;
esac
PLATFORM_CHECK
}

# Renders the administrator deploy program. `root` and `os_release_path` are
# embedded as literal paths (overridable so tests can point both at a
# scratch fixture tree, exactly like the add-on deployment's `ROOT`
# convention); `wrapper_content`, `restrict_entry`, and `fallback_entry` are
# pre-rendered, already-validated text this function only embeds, never
# builds. `restrict_entry`/`fallback_entry` are single lines made only of a
# key type, a base64 blob, our fixed marker, and fixed option keywords (see
# `_coreelec_lifecycle_key_type_and_blob`), so embedding them inside a single
# `'...'` remote shell literal is safe: that grammar can never contain a
# single quote. `wrapper_content` is entirely our own generated text.
coreelec_lifecycle_remote_deploy_script() {
  local root="${1:-/storage}" os_release_path="${2:-/etc/os-release}"
  local wrapper_content="$3" restrict_entry="$4" fallback_entry="$5"
  [[ -n "${wrapper_content}" ]] || die "coreelec_lifecycle_remote_deploy_script requires wrapper content"
  [[ -n "${restrict_entry}" ]] || die "coreelec_lifecycle_remote_deploy_script requires a restrict key entry"
  [[ -n "${fallback_entry}" ]] || die "coreelec_lifecycle_remote_deploy_script requires a fallback key entry"
  cat <<DEPLOY_HEADER
set -eu
umask 077
root='${root}'
os_release_path='${os_release_path}'
marker='${COREELEC_LIFECYCLE_KEY_MARKER}'
restrict_entry='${restrict_entry}'
fallback_entry='${fallback_entry}'
DEPLOY_HEADER
  cat <<'DEPLOY_PATHS'
ssh_dir="${root}/.ssh"
authorized="${ssh_dir}/authorized_keys"
config_dir="${root}/.config"
wrapper_path="${config_dir}/kodi-lifecycle"
backup_root="${root}/backup/kodi-lifecycle"
cache_root="${root}/.cache/kodi-lifecycle"
pointer_file="${cache_root}/current-transaction"
DEPLOY_PATHS
  _coreelec_lifecycle_remote_platform_check
  cat <<'DEPLOY_BODY'
mkdir -p "${cache_root}"
chmod 700 "${cache_root}"
if [ -f "${pointer_file}" ]; then
  printf 'DEPLOY_REFUSED:pending-transaction:%s\n' "$(cat "${pointer_file}")" >&2
  exit 14
fi

state="$(systemctl is-active kodi.service 2>/dev/null || true)"
case "${state}" in
  active) initial_state="running" ;;
  inactive)
    if systemctl is-failed --quiet kodi.service; then
      initial_state="failed"
    else
      initial_state="stopped"
    fi
    ;;
  failed) initial_state="failed" ;;
  *) initial_state="failed" ;;
esac
if [ "${initial_state}" = "failed" ]; then
  printf 'DEPLOY_REFUSED:kodi-service-failed\n' >&2
  exit 13
fi
printf 'INITIAL_STATE:%s\n' "${initial_state}"

mkdir -p "${backup_root}"
chmod 700 "${backup_root}"
stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
transaction="${backup_root}/${stamp}"
collision=0
while [ -d "${transaction}" ]; do
  collision=$((collision + 1))
  transaction="${backup_root}/${stamp}-${collision}"
done
mkdir -p "${transaction}/rollback"
chmod 700 "${transaction}" "${transaction}/rollback"
# The pointer is written before any target file is touched: even a failure
# on the very first backup copy below must leave a named, inspectable
# transaction directory behind rather than an orphaned one.
printf '%s\n' "${transaction}" > "${pointer_file}"

rollback_now() {
  reason="$1"
  ok=1
  if [ -f "${transaction}/rollback/wrapper.absent" ]; then
    rm -f "${wrapper_path}" || ok=0
  elif [ -f "${transaction}/rollback/wrapper" ]; then
    cp -p "${transaction}/rollback/wrapper" "${wrapper_path}" || ok=0
    chmod 700 "${wrapper_path}" 2>/dev/null || ok=0
  fi
  if [ -f "${transaction}/rollback/authorized_keys.absent" ]; then
    rm -f "${authorized}" || ok=0
  elif [ -f "${transaction}/rollback/authorized_keys" ]; then
    cp -p "${transaction}/rollback/authorized_keys" "${authorized}" || ok=0
    chmod 600 "${authorized}" 2>/dev/null || ok=0
  fi
  rm -f "${wrapper_path}.candidate" "${authorized}.candidate" \
    "${cache_root}/atomic-write.py" "${cache_root}/key-check.tmp" \
    "${cache_root}/authorized-keys-candidate-source.tmp" 2>/dev/null || true
  if [ "${ok}" -eq 1 ]; then
    rm -rf "${transaction}"
    rm -f "${pointer_file}"
    printf 'DEPLOY_STATE:rolled-back:%s\n' "${reason}" >&2
  else
    printf 'DEPLOY_STATE:incomplete-rollback:%s\n' "${reason}" >&2
    printf 'TRANSACTION:%s\n' "${transaction}" >&2
  fi
  exit 1
}

if [ -e "${wrapper_path}" ]; then
  cp -p "${wrapper_path}" "${transaction}/rollback/wrapper" || rollback_now "backup-wrapper-failed"
  chmod 600 "${transaction}/rollback/wrapper" || rollback_now "backup-wrapper-chmod-failed"
else
  : > "${transaction}/rollback/wrapper.absent"
fi
if [ -e "${authorized}" ]; then
  cp -p "${authorized}" "${transaction}/rollback/authorized_keys" || rollback_now "backup-authorized-keys-failed"
  chmod 600 "${transaction}/rollback/authorized_keys" || rollback_now "backup-authorized-keys-chmod-failed"
else
  : > "${transaction}/rollback/authorized_keys.absent"
fi

mkdir -p "${config_dir}" "${ssh_dir}"
chmod 700 "${config_dir}" "${ssh_dir}"

atomic_writer="${cache_root}/atomic-write.py"
rm -f "${atomic_writer}"
cat > "${atomic_writer}" <<'ATOMIC_WRITER_PY'
import os
import sys

path, mode_octal = sys.argv[1], sys.argv[2]
mode = int(mode_octal, 8)
data = sys.stdin.buffer.read()
# O_EXCL refuses a path that already exists -- including a planted hard link
# -- and O_NOFOLLOW refuses a planted symlink at the leaf, so the candidate
# can only ever be a brand-new regular file this process created.
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
fd = os.open(path, flags, mode)
try:
    os.fchmod(fd, mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
except BaseException:
    os.close(fd)
    raise
ATOMIC_WRITER_PY
chmod 700 "${atomic_writer}"

wrapper_candidate="${wrapper_path}.candidate"
authorized_candidate="${authorized}.candidate"
rm -f "${wrapper_candidate}" "${authorized_candidate}"
DEPLOY_BODY
  # This one command is rendered outside the quoted DEPLOY_BODY heredocs, on
  # purpose: `wrapper_content` must be substituted by *this* function, once,
  # at render time, not left as a literal `${wrapper_content}` for the
  # device's `sh` to fail to resolve. The inner `<<'WRAPPER_CANDIDATE_EOF'`
  # delimiter it renders stays quoted, so the device never re-expands the
  # wrapper's own `${SYSTEMCTL}`/`${UNIT}` references while writing it out.
  cat <<WRAPPER_CANDIDATE_COMMAND
python3 "\${atomic_writer}" "\${wrapper_candidate}" 700 <<'WRAPPER_CANDIDATE_EOF' || rollback_now "write-wrapper-candidate-failed"
${wrapper_content}
WRAPPER_CANDIDATE_EOF
WRAPPER_CANDIDATE_COMMAND
  cat <<'DEPLOY_BODY'
# The target's own ssh-keygen is the arbiter of whether it understands the
# `restrict` keyword: older OpenSSH releases (before 7.2) do not, and a
# device that rejects it must fall back to the equivalent explicit options
# instead of silently shipping an authorized_keys line sshd cannot parse.
key_check="${cache_root}/key-check.tmp"
rm -f "${key_check}"
printf '%s\n' "${restrict_entry}" > "${key_check}"
if ssh-keygen -l -f "${key_check}" >/dev/null 2>&1; then
  key_mode="restrict"
  chosen_entry="${restrict_entry}"
else
  printf '%s\n' "${fallback_entry}" > "${key_check}"
  if ssh-keygen -l -f "${key_check}" >/dev/null 2>&1; then
    key_mode="fallback"
    chosen_entry="${fallback_entry}"
  else
    rm -f "${key_check}"
    rollback_now "no-supported-key-restriction-syntax"
  fi
fi
rm -f "${key_check}"

# Only the line carrying our stable marker is ever replaced; every other
# line -- including the administrator's own key -- passes through untouched.
candidate_source="${cache_root}/authorized-keys-candidate-source.tmp"
rm -f "${candidate_source}"
{
  if [ -e "${authorized}" ]; then
    grep -v "${marker}" "${authorized}" 2>/dev/null || true
  fi
  printf '%s\n' "${chosen_entry}"
} > "${candidate_source}" || rollback_now "compose-authorized-keys-candidate-failed"
python3 "${atomic_writer}" "${authorized_candidate}" 600 < "${candidate_source}" \
  || rollback_now "write-authorized-keys-candidate-failed"
rm -f "${candidate_source}"

mv "${wrapper_candidate}" "${wrapper_path}" || rollback_now "rename-wrapper-failed"
mv "${authorized_candidate}" "${authorized}" || rollback_now "rename-authorized-keys-failed"
chmod 700 "${wrapper_path}" || rollback_now "chmod-wrapper-failed"
chmod 700 "${ssh_dir}" || rollback_now "chmod-ssh-dir-failed"
chmod 600 "${authorized}" || rollback_now "chmod-authorized-keys-failed"
rm -f "${atomic_writer}"

# The transaction directory and pointer are deliberately left in place: this
# deployment is only "pending-verification" until the restricted key has
# proven itself over a real SSH session, at which point the CLI issues a
# separate finalize (success) or rollback (failure) program.
printf 'TRANSACTION:%s\n' "${transaction}"
printf 'KEY_MODE:%s\n' "${key_mode}"
printf 'DEPLOY_STATE:pending-verification\n'
DEPLOY_BODY
}

# Renders the administrator rollback program. With `explicit_transaction`
# empty (the CLI's own post-verification-failure path), the pending
# transaction named by the pointer file is restored. With it set (the
# operator-facing `--rollback-transaction DIR` recovery path), that exact
# directory is restored instead, regardless of what the pointer currently
# names -- an operator retrying a previously incomplete rollback needs this
# to work even if the pointer file itself did not survive.
coreelec_lifecycle_remote_rollback_script() {
  local root="${1:-/storage}" explicit_transaction="${2:-}"
  cat <<ROLLBACK_HEADER
set -eu
root='${root}'
explicit_transaction='${explicit_transaction}'
ROLLBACK_HEADER
  cat <<'ROLLBACK_BODY'
ssh_dir="${root}/.ssh"
authorized="${ssh_dir}/authorized_keys"
wrapper_path="${root}/.config/kodi-lifecycle"
cache_root="${root}/.cache/kodi-lifecycle"
pointer_file="${cache_root}/current-transaction"

if [ -n "${explicit_transaction}" ]; then
  transaction="${explicit_transaction}"
else
  if [ ! -f "${pointer_file}" ]; then
    printf 'ROLLBACK_FAIL:no-pending-transaction\n' >&2
    exit 20
  fi
  transaction="$(cat "${pointer_file}")"
fi
if [ ! -d "${transaction}" ]; then
  printf 'ROLLBACK_FAIL:transaction-directory-missing:%s\n' "${transaction}" >&2
  exit 21
fi

ok=1
if [ -f "${transaction}/rollback/wrapper.absent" ]; then
  rm -f "${wrapper_path}" || ok=0
elif [ -f "${transaction}/rollback/wrapper" ]; then
  cp -p "${transaction}/rollback/wrapper" "${wrapper_path}" || ok=0
  chmod 700 "${wrapper_path}" 2>/dev/null || ok=0
fi
if [ -f "${transaction}/rollback/authorized_keys.absent" ]; then
  rm -f "${authorized}" || ok=0
elif [ -f "${transaction}/rollback/authorized_keys" ]; then
  cp -p "${transaction}/rollback/authorized_keys" "${authorized}" || ok=0
  chmod 600 "${authorized}" 2>/dev/null || ok=0
fi
rm -f "${wrapper_path}.candidate" "${authorized}.candidate" 2>/dev/null || true

# Exact restoration is verified, not assumed: the restored path must match
# its recorded pre-run digest, or its recorded absence, before this counts
# as a completed rollback.
verified=1
if [ -f "${transaction}/rollback/wrapper.absent" ]; then
  [ -e "${wrapper_path}" ] && verified=0
elif [ -f "${transaction}/rollback/wrapper" ]; then
  cmp -s "${transaction}/rollback/wrapper" "${wrapper_path}" || verified=0
fi
if [ -f "${transaction}/rollback/authorized_keys.absent" ]; then
  [ -e "${authorized}" ] && verified=0
elif [ -f "${transaction}/rollback/authorized_keys" ]; then
  cmp -s "${transaction}/rollback/authorized_keys" "${authorized}" || verified=0
fi

if [ "${ok}" -eq 1 ] && [ "${verified}" -eq 1 ]; then
  rm -rf "${transaction}"
  rm -f "${pointer_file}"
  printf 'ROLLBACK_STATE:rolled-back\n'
  exit 0
fi
# Recovery material is retained, on purpose, whenever restoration cannot be
# proven complete: an operator needs the dated directory and a pointer that
# still names it to retry, not a rollback that quietly gave up.
printf '%s\n' "${transaction}" > "${pointer_file}"
printf 'ROLLBACK_STATE:incomplete-rollback\n' >&2
printf 'TRANSACTION:%s\n' "${transaction}" >&2
exit 22
ROLLBACK_BODY
}

# Renders the administrator finalize program: it only ever discards the
# rollback material for the currently pending transaction, after the CLI has
# already proven the restricted key restores the device to its initial
# state. It never touches the wrapper or authorized_keys themselves.
coreelec_lifecycle_remote_finalize_script() {
  local root="${1:-/storage}"
  cat <<FINALIZE_HEADER
set -eu
root='${root}'
FINALIZE_HEADER
  cat <<'FINALIZE_BODY'
cache_root="${root}/.cache/kodi-lifecycle"
pointer_file="${cache_root}/current-transaction"

if [ ! -f "${pointer_file}" ]; then
  printf 'FINALIZE_FAIL:no-pending-transaction\n' >&2
  exit 30
fi
transaction="$(cat "${pointer_file}")"
if [ ! -d "${transaction}" ]; then
  printf 'FINALIZE_FAIL:transaction-directory-missing:%s\n' "${transaction}" >&2
  exit 31
fi
if ! rm -rf "${transaction}"; then
  printf 'FINALIZE_STATE:incomplete-rollback\n' >&2
  printf 'TRANSACTION:%s\n' "${transaction}" >&2
  exit 32
fi
rm -f "${pointer_file}"
printf 'FINALIZE_STATE:committed\n'
FINALIZE_BODY
}

# Renders the read-only administrator inspection program for
# `--inspect-transaction DIR`. It reports which recovery items exist, never
# their contents: a stray authorized_keys backup can carry other operators'
# key material, and that must never reach a report or a terminal.
coreelec_lifecycle_remote_inspect_script() {
  local root="${1:-/storage}" transaction_dir="$2"
  [[ -n "${transaction_dir}" ]] || die "coreelec_lifecycle_remote_inspect_script requires a transaction directory"
  cat <<INSPECT_HEADER
set -eu
root='${root}'
transaction='${transaction_dir}'
INSPECT_HEADER
  cat <<'INSPECT_BODY'
if [ ! -d "${transaction}" ]; then
  printf 'INSPECT_STATE:missing\n'
  exit 0
fi
printf 'INSPECT_STATE:present\n'
printf 'TRANSACTION:%s\n' "${transaction}"
for item in wrapper wrapper.absent authorized_keys authorized_keys.absent; do
  if [ -e "${transaction}/rollback/${item}" ]; then
    printf 'ROLLBACK_ITEM:%s:present\n' "${item}"
  else
    printf 'ROLLBACK_ITEM:%s:absent\n' "${item}"
  fi
done
INSPECT_BODY
}

# --- Controller transport: hardened, forced-command-only SSH -------------

# Runs "$@" under a hard wall-clock deadline. Uses GNU coreutils `timeout`
# when the platform provides it; otherwise runs the command in the
# background and races it against a `sleep` watchdog, terminating the
# command if the watchdog wins. This keeps the deadline identical on macOS
# (which ships no `timeout` by default) and on Linux without depending on
# GNU coreutils, and is the "portable background/wait helper" referenced by
# `coreelec_lifecycle_ssh_controller` below.
coreelec_lifecycle_run_with_deadline() {
  local deadline_seconds="$1"
  shift
  [[ "$#" -ge 1 ]] || die "coreelec_lifecycle_run_with_deadline requires a command"
  if command -v timeout >/dev/null 2>&1; then
    timeout "${deadline_seconds}" "$@"
    return $?
  fi
  local command_pid watchdog_pid rc
  "$@" &
  command_pid=$!
  (
    sleep "${deadline_seconds}"
    kill -TERM "${command_pid}" 2>/dev/null
  ) &
  watchdog_pid=$!
  set +e
  wait "${command_pid}"
  rc=$?
  set -e
  kill "${watchdog_pid}" 2>/dev/null || true
  wait "${watchdog_pid}" 2>/dev/null || true
  return "${rc}"
}

# Runs one command over the restricted controller identity. This is a
# distinct transport from `coreelec_ssh_command` (the administrator
# transport in lib/coreelec-ssh.sh): it uses its own identity and known-hosts
# globals, never accepts a new host key (`StrictHostKeyChecking=yes` with an
# explicit `UserKnownHostsFile`, so controller verification can never be the
# first connection to *learn* the target's host key), only ever attempts one
# connection, and is bounded by the 15-second outer deadline above. The
# authorized_keys `command=` restriction, not this transport, is what
# confines the remote side to `start`/`stop`/`status`; `remote_command` here
# is only ever the client's requested command word, which the device is free
# to ignore.
coreelec_lifecycle_ssh_controller() {
  local remote_command="$1"
  [[ "$#" -eq 1 ]] || die "coreelec_lifecycle_ssh_controller requires one remote command"
  _coreelec_ssh_require_connection_globals "coreelec_lifecycle_ssh_controller"
  [[ -n "${CONTROLLER_IDENTITY:-}" ]] || die "CONTROLLER_IDENTITY is required before calling coreelec_lifecycle_ssh_controller"
  [[ -n "${KNOWN_HOSTS_FILE:-}" ]] || die "KNOWN_HOSTS_FILE is required before calling coreelec_lifecycle_ssh_controller"
  coreelec_lifecycle_run_with_deadline 15 \
    ssh \
    -p "${SSH_PORT}" \
    -o BatchMode=yes \
    -o ConnectTimeout=12 \
    -o ConnectionAttempts=1 \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="${KNOWN_HOSTS_FILE}" \
    -i "${CONTROLLER_IDENTITY}" \
    -o IdentitiesOnly=yes \
    "root@${TARGET}" \
    "${remote_command}"
}
