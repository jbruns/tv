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
#     transaction directory, holding a `manifest` file and rollback/
#     (pre-images or *.absent markers for the wrapper and authorized_keys)
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

# Determines whether the target's installed `sshd` understands the
# authorized_keys `restrict` keyword (OpenSSH >= 7.2), by parsing the
# version banner `sshd -V` prints, rather than by probing `ssh-keygen -l -f`
# against candidate key text: real OpenSSH's `-l -f` syntax-checks a key
# blob, not the leading option string, so it silently accepts a `restrict`
# option it does not actually understand (see finding I5). This check runs
# before any mutation and fails closed -- an unreadable/unparseable version,
# or a missing `sshd` binary, refuses the deploy rather than guessing.
_coreelec_lifecycle_remote_key_mode_check() {
  cat <<'KEY_MODE_CHECK'
if [ ! -x "${sshd}" ]; then
  printf 'KEY_MODE_CHECK_FAIL:sshd-not-found:%s\n' "${sshd}" >&2
  exit 15
fi
_kmc_version_output="$("${sshd}" -V 2>&1 || true)"
_kmc_version="$(printf '%s\n' "${_kmc_version_output}" | grep -o 'OpenSSH_[0-9][0-9]*\.[0-9][0-9]*' | head -n 1)"
if [ -z "${_kmc_version}" ]; then
  printf 'KEY_MODE_CHECK_FAIL:version-unparseable:%s\n' "${_kmc_version_output}" >&2
  exit 15
fi
_kmc_major="$(printf '%s\n' "${_kmc_version}" | sed -n 's/^OpenSSH_\([0-9][0-9]*\)\.[0-9][0-9]*$/\1/p')"
_kmc_minor="$(printf '%s\n' "${_kmc_version}" | sed -n 's/^OpenSSH_[0-9][0-9]*\.\([0-9][0-9]*\)$/\1/p')"
if [ -z "${_kmc_major}" ] || [ -z "${_kmc_minor}" ]; then
  printf 'KEY_MODE_CHECK_FAIL:version-unparseable:%s\n' "${_kmc_version}" >&2
  exit 15
fi
if [ "${_kmc_major}" -gt 7 ] || { [ "${_kmc_major}" -eq 7 ] && [ "${_kmc_minor}" -ge 2 ]; }; then
  key_mode="restrict"
else
  key_mode="fallback"
fi
KEY_MODE_CHECK
}

# Shared, POSIX `sh` transaction-safety primitives embedded verbatim into
# every remote program that resolves, restores, or discards a transaction
# directory (deploy's own self-rollback, the explicit rollback program, and
# the finalize program). No caller-supplied path -- whether the operator's
# own `--rollback-transaction`/`--finalize-transaction` argument, or the
# device's own pointer file -- is ever restored from, deleted, or reported
# on until its canonical path has been proven to be a non-symlinked,
# immediate child of the lifecycle backup root. Cleanup/inspection may
# resolve a missing leaf only with a matching durable completion receipt. Never the
# root itself, a parent, a sibling namespace such as `/storage`, or an
# arbitrary operator-supplied path (see finding C1).
_coreelec_lifecycle_remote_shared_lib() {
  cat <<'LIFECYCLE_SHARED_LIB'
# Prints the canonical (symlink-resolved) absolute path of an existing file
# or directory. Fails if any path component cannot be resolved.
_lifecycle_canon() {
  _lc_path="$1"
  if [ -d "${_lc_path}" ]; then
    (cd "${_lc_path}" 2>/dev/null && pwd -P)
  else
    _lc_dir="$(dirname "${_lc_path}")"
    _lc_base="$(basename "${_lc_path}")"
    _lc_resolved_dir="$(cd "${_lc_dir}" 2>/dev/null && pwd -P)" || return 1
    printf '%s/%s\n' "${_lc_resolved_dir}" "${_lc_base}"
  fi
}

# Resolves $1 as a transaction directory that must canonically be an
# existing, non-symlinked, immediate child of the canonical backup root
# passed as $2. Prints the canonical transaction path on success; prints
# nothing and returns 1 on failure. The optional allow-missing mode resolves
# a missing leaf for receipt checks only, never as a source of pre-images.
_lifecycle_resolve_transaction() {
  _lrt_candidate="$1"
  _lrt_backup_root_canon="$2"
  case "${_lrt_candidate}" in
    '') return 1 ;;
    *..*) return 1 ;;
  esac
  [ -L "${_lrt_candidate}" ] && return 1
  if [ -e "${_lrt_candidate}" ]; then
    [ -d "${_lrt_candidate}" ] || return 1
  else
    [ "${3:-}" = "allow-missing" ] || return 1
  fi
  _lrt_canon="$(_lifecycle_canon "${_lrt_candidate}")" || return 1
  [ -n "${_lrt_canon}" ] || return 1
  [ "${_lrt_canon}" != "${_lrt_backup_root_canon}" ] || return 1
  _lrt_parent="$(dirname "${_lrt_canon}")"
  [ "${_lrt_parent}" = "${_lrt_backup_root_canon}" ] || return 1
  printf '%s\n' "${_lrt_canon}"
}

# True only for a versioned, state-bearing journal and a published backup
# set with exactly one {present, .absent} marker for each target.
_lifecycle_manifest_complete() {
  _lmc_t="$1"
  [ -f "${_lmc_t}/manifest" ] || return 1
  [ -f "${_lmc_t}/backups-complete" ] || return 1
  for _lmc_item in manifest phase backups-complete rollback rollback/wrapper \
    rollback/wrapper.absent rollback/authorized_keys rollback/authorized_keys.absent; do
    [ ! -L "${_lmc_t}/${_lmc_item}" ] || return 1
  done
  [ "$(sed -n 's/^MANIFEST_VERSION=//p' "${_lmc_t}/manifest")" = "2" ] || return 1
  [ "$(sed -n 's/^TRANSACTION=//p' "${_lmc_t}/manifest")" = "${_lmc_t}" ] || return 1
  _lifecycle_initial_state "${_lmc_t}" >/dev/null || return 1
  case "$(cat "${_lmc_t}/phase" 2>/dev/null)" in
    prepared|installing|pending-verification|rolling-back|rollback-complete|finalizing) ;;
    *) return 1 ;;
  esac
  _lmc_wp=0
  _lmc_wa=0
  [ -f "${_lmc_t}/rollback/wrapper" ] && _lmc_wp=1
  [ -f "${_lmc_t}/rollback/wrapper.absent" ] && _lmc_wa=1
  [ $((_lmc_wp + _lmc_wa)) -eq 1 ] || return 1
  _lmc_ap=0
  _lmc_aa=0
  [ -f "${_lmc_t}/rollback/authorized_keys" ] && _lmc_ap=1
  [ -f "${_lmc_t}/rollback/authorized_keys.absent" ] && _lmc_aa=1
  [ $((_lmc_ap + _lmc_aa)) -eq 1 ] || return 1
  return 0
}

_lifecycle_initial_state() {
  _lis_state="$(sed -n 's/^INITIAL_STATE=//p' "$1/manifest")" || return 1
  case "${_lis_state}" in
    running|stopped) printf '%s\n' "${_lis_state}" ;;
    *) return 1 ;;
  esac
}

_lifecycle_record_phase() {
  printf '%s\n' "$2" > "$1/phase.new" || return 1
  chmod 600 "$1/phase.new" || return 1
  mv -f "$1/phase.new" "$1/phase"
}

_lifecycle_receipt_matches() {
  [ -f "$1" ] && [ ! -L "$1" ] && [ "$(cat "$1")" = "$2" ]
}

_lifecycle_record_receipt() {
  rm -f "$1.new" || return 1
  (umask 077; set -C; printf '%s\n' "$2" > "$1.new") || return 1
  mv -f "$1.new" "$1"
}

_lifecycle_cleanup_verified_rollback() {
  _lifecycle_record_receipt "${cache_root}/last-rolled-back-transaction" "${transaction}" || return 1
  rm -rf "${transaction}" || return 1
  rm -f "${pointer_file}"
}

_lifecycle_restore_service() {
  _lrs_initial="$1"
  case "${_lrs_initial}" in
    running)
      if ! systemctl is-active --quiet kodi.service; then
        systemctl start kodi.service || true
      fi
      ;;
    stopped)
      if systemctl is-active --quiet kodi.service; then
        systemctl stop kodi.service || true
      fi
      ;;
    *) return 1 ;;
  esac
  _lrs_state="$(systemctl is-active kodi.service 2>/dev/null || true)"
  case "${_lrs_state}" in
    active) _lrs_result="running" ;;
    inactive)
      if systemctl is-failed --quiet kodi.service; then
        _lrs_result="failed"
      else
        _lrs_result="stopped"
      fi
      ;;
    *) _lrs_result="failed" ;;
  esac
  if [ "${_lrs_result}" = "${_lrs_initial}" ]; then
    printf 'SERVICE_RESTORE_STATE:restored:%s\n' "${_lrs_result}"
    return 0
  fi
  printf 'SERVICE_RESTORE_STATE:mismatch:%s\n' "${_lrs_result}" >&2
  return 1
}

# Publish only byte-verified pre-images. A failed/short copy remains a
# .pending file and can never satisfy the restoration manifest.
_lifecycle_backup_one() {
  _lbo_source="$1"
  _lbo_item="$2"
  if [ -e "${_lbo_source}" ]; then
    cp -p "${_lbo_source}" "${_lbo_item}.pending" || return 1
    cmp -s "${_lbo_source}" "${_lbo_item}.pending" || return 1
    chmod 600 "${_lbo_item}.pending" || return 1
    mv "${_lbo_item}.pending" "${_lbo_item}" || return 1
  else
    [ ! -L "${_lbo_source}" ] || return 1
    : > "${_lbo_item}.absent" || return 1
  fi
}

# Atomically restores one target file from its recorded pre-image at
# "${item}" (or removes the target, if "${item}.absent" was recorded
# instead), never truncating a live path in place: a fresh candidate file is
# written, chmod'd, and fsynced, then renamed over the target in one step.
_lifecycle_restore_one() {
  _lro_item="$1"
  _lro_target="$2"
  _lro_mode="$3"
  if [ -f "${_lro_item}.absent" ]; then
    rm -f "${_lro_target}"
    return $?
  fi
  [ -f "${_lro_item}" ] || return 1
  _lro_candidate="${_lro_target}.rollback-candidate"
  rm -f "${_lro_candidate}"
  cp -p "${_lro_item}" "${_lro_candidate}" || { rm -f "${_lro_candidate}"; return 1; }
  chmod "${_lro_mode}" "${_lro_candidate}" 2>/dev/null || { rm -f "${_lro_candidate}"; return 1; }
  if command -v sync >/dev/null 2>&1; then
    sync "${_lro_candidate}" 2>/dev/null || true
  fi
  mv -f "${_lro_candidate}" "${_lro_target}" || return 1
  return 0
}

# Verifies a restored target exactly matches its recorded pre-image, or is
# recorded absent and is indeed gone.
_lifecycle_verify_one() {
  _lvo_item="$1"
  _lvo_target="$2"
  if [ -f "${_lvo_item}.absent" ]; then
    [ ! -e "${_lvo_target}" ]
    return $?
  fi
  cmp -s "${_lvo_item}" "${_lvo_target}"
}
LIFECYCLE_SHARED_LIB
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
# `sshd_path` defaults to its real production location and is only ever
# overridden by tests. Administrator state observation/restoration resolves
# systemctl through PATH; the wrapper's fixed path is baked in separately.
coreelec_lifecycle_remote_deploy_script() {
  local root="${1:-/storage}" os_release_path="${2:-/etc/os-release}"
  local wrapper_content="$3" restrict_entry="$4" fallback_entry="$5"
  local sshd_path="${6:-/usr/sbin/sshd}"
  [[ -n "${wrapper_content}" ]] || die "coreelec_lifecycle_remote_deploy_script requires wrapper content"
  [[ -n "${restrict_entry}" ]] || die "coreelec_lifecycle_remote_deploy_script requires a restrict key entry"
  [[ -n "${fallback_entry}" ]] || die "coreelec_lifecycle_remote_deploy_script requires a fallback key entry"
  cat <<DEPLOY_HEADER
set -eu
umask 077
root='${root}'
os_release_path='${os_release_path}'
sshd='${sshd_path}'
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
  _coreelec_lifecycle_remote_key_mode_check
  _coreelec_lifecycle_remote_shared_lib
  cat <<'DEPLOY_BODY'
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
transaction_id="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')" || {
  printf 'DEPLOY_REFUSED:transaction-id-unavailable\n' >&2
  exit 16
}
printf 'INITIAL_STATE:%s\n' "${initial_state}"

# No mutation happens above this point: both refusals (an already-pending
# transaction, and a kodi.service already in a failed state) are checked
# before the cache directory -- or anything else -- is ever created.
mkdir -p "${cache_root}"
chmod 700 "${cache_root}"

mkdir -p "${backup_root}"
chmod 700 "${backup_root}"
stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
transaction="${backup_root}/${stamp}-${transaction_id}"
collision=0
while [ -d "${transaction}" ]; do
  collision=$((collision + 1))
  transaction="${backup_root}/${stamp}-${transaction_id}-${collision}"
done
mkdir -p "${transaction}/rollback"
chmod 700 "${transaction}" "${transaction}/rollback"
# The pointer is written before any target file is touched: even a failure
# on the very first backup copy below must leave a named, inspectable
# transaction directory behind rather than an orphaned one.
printf '%s\n' "${transaction}" > "${pointer_file}"

# `rollback_now` is defined before anything else touches the transaction
# directory or the two target files, so every mutation below -- including
# writing the manifest itself -- is guarded through this one path (see
# finding C2's "guard every remote command after first mutation" and
# finding I7's restoration-verification requirement).
rollback_now() {
  reason="$1"
  ok=1
  if _lifecycle_manifest_complete "${transaction}" \
      && _lifecycle_record_phase "${transaction}" rolling-back; then
    _lifecycle_restore_one "${transaction}/rollback/wrapper" "${wrapper_path}" 700 || ok=0
    _lifecycle_restore_one "${transaction}/rollback/authorized_keys" "${authorized}" 600 || ok=0
  else
    ok=0
  fi
  rm -f "${wrapper_path}.candidate" "${authorized}.candidate" \
    "${cache_root}/atomic-write.py" "${cache_root}/key-check.tmp" \
    "${cache_root}/authorized-keys-candidate-source.tmp" 2>/dev/null || true

  verified=0
  if [ "${ok}" -eq 1 ]; then
    verified=1
    _lifecycle_verify_one "${transaction}/rollback/wrapper" "${wrapper_path}" || verified=0
    _lifecycle_verify_one "${transaction}/rollback/authorized_keys" "${authorized}" || verified=0
  fi

  service_ok=0
  if _lifecycle_manifest_complete "${transaction}"; then
    _lifecycle_restore_service "$(_lifecycle_initial_state "${transaction}")" && service_ok=1
  fi
  if [ "${ok}" -eq 1 ] && [ "${verified}" -eq 1 ] && [ "${service_ok}" -eq 1 ] \
      && _lifecycle_record_phase "${transaction}" rollback-complete \
      && _lifecycle_cleanup_verified_rollback; then
    printf 'DEPLOY_STATE:rolled-back:%s\n' "${reason}" >&2
  else
    # Recovery material is retained, on purpose, whenever restoration cannot
    # be proven complete or the manifest itself was incomplete: an operator
    # needs the dated directory and a pointer that still names it to retry,
    # not a rollback that quietly gave up or restored only part of the
    # state.
    printf '%s\n' "${transaction}" > "${pointer_file}"
    printf 'DEPLOY_STATE:incomplete-rollback:%s\n' "${reason}" >&2
    printf 'TRANSACTION:%s\n' "${transaction}" >&2
  fi
  exit 1
}

{
  printf 'MANIFEST_VERSION=2\n'
  printf 'TRANSACTION=%s\n' "${transaction}"
  printf 'INITIAL_STATE=%s\n' "${initial_state}"
  printf 'CREATED_UTC=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true)"
} > "${transaction}/manifest" || rollback_now "write-manifest-failed"
chmod 600 "${transaction}/manifest" 2>/dev/null || true
_lifecycle_record_phase "${transaction}" backing-up || rollback_now "record-phase-failed"

_lifecycle_backup_one "${wrapper_path}" "${transaction}/rollback/wrapper" \
  || rollback_now "backup-wrapper-failed"
_lifecycle_backup_one "${authorized}" "${transaction}/rollback/authorized_keys" \
  || rollback_now "backup-authorized-keys-failed"
: > "${transaction}/backups-complete" || rollback_now "complete-backups-failed"
_lifecycle_record_phase "${transaction}" prepared || rollback_now "record-phase-failed"

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
# Only the line carrying our stable marker is ever replaced; every other
# line -- including the administrator's own key -- passes through untouched.
if [ "${key_mode}" = "restrict" ]; then
  chosen_entry="${restrict_entry}"
else
  chosen_entry="${fallback_entry}"
fi
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

_lifecycle_record_phase "${transaction}" installing || rollback_now "record-phase-failed"
mv "${wrapper_candidate}" "${wrapper_path}" || rollback_now "rename-wrapper-failed"
mv "${authorized_candidate}" "${authorized}" || rollback_now "rename-authorized-keys-failed"
chmod 700 "${wrapper_path}" || rollback_now "chmod-wrapper-failed"
chmod 700 "${ssh_dir}" || rollback_now "chmod-ssh-dir-failed"
chmod 600 "${authorized}" || rollback_now "chmod-authorized-keys-failed"
rm -f "${atomic_writer}"
_lifecycle_record_phase "${transaction}" pending-verification || rollback_now "record-phase-failed"

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
# empty (the CLI's own post-verification-failure path, and the operator's
# `--rollback-transaction` with no directory), the transaction named by the
# device's own pointer file is resolved and restored. With it set (an
# operator naming a specific directory), that candidate must resolve to the
# exact same canonical transaction the pointer currently names -- never an
# arbitrary path, a parent, `/storage`, the backup namespace root itself, a
# sibling transaction, or a symlink (see finding C1). Restoration itself is
# always atomic-candidate-then-rename, never in-place (finding I6), and is
# always verified against each item's recorded pre-image digest or absence
# before any recovery material is discarded (finding I7's guarantee, applied
# here too).
coreelec_lifecycle_remote_rollback_script() {
  local root="${1:-/storage}" explicit_transaction="${2:-}"
  cat <<ROLLBACK_HEADER
set -eu
root='${root}'
explicit_transaction='${explicit_transaction}'
ROLLBACK_HEADER
  _coreelec_lifecycle_remote_shared_lib
  cat <<'ROLLBACK_BODY'
ssh_dir="${root}/.ssh"
authorized="${ssh_dir}/authorized_keys"
wrapper_path="${root}/.config/kodi-lifecycle"
backup_root="${root}/backup/kodi-lifecycle"
cache_root="${root}/.cache/kodi-lifecycle"
pointer_file="${cache_root}/current-transaction"

if [ ! -d "${backup_root}" ] || [ ! -f "${pointer_file}" ]; then
  printf 'ROLLBACK_FAIL:no-pending-transaction\n' >&2
  exit 20
fi
backup_root_canon="$(_lifecycle_canon "${backup_root}")" || {
  printf 'ROLLBACK_FAIL:no-pending-transaction\n' >&2
  exit 20
}

pointer_raw="$(cat "${pointer_file}")"
pointer_transaction="$(_lifecycle_resolve_transaction "${pointer_raw}" "${backup_root_canon}" allow-missing)" || {
  printf 'ROLLBACK_FAIL:invalid-transaction-path:pointer\n' >&2
  exit 21
}

if [ -n "${explicit_transaction}" ]; then
  candidate_transaction="$(_lifecycle_resolve_transaction "${explicit_transaction}" "${backup_root_canon}" allow-missing)" || {
    printf 'ROLLBACK_FAIL:invalid-transaction-path:explicit\n' >&2
    exit 21
  }
  if [ "${candidate_transaction}" != "${pointer_transaction}" ]; then
    printf 'ROLLBACK_FAIL:transaction-pointer-mismatch\n' >&2
    exit 23
  fi
  transaction="${candidate_transaction}"
else
  transaction="${pointer_transaction}"
fi

if _lifecycle_receipt_matches "${cache_root}/last-rolled-back-transaction" "${transaction}"; then
  if _lifecycle_cleanup_verified_rollback; then
    printf 'ROLLBACK_RECOVERY:cleanup-only-after-verified-restoration\n'
    printf 'ROLLBACK_STATE:rolled-back\n'
    exit 0
  fi
  printf 'ROLLBACK_STATE:incomplete-rollback\n' >&2
  printf 'TRANSACTION:%s\n' "${transaction}" >&2
  exit 22
fi

if ! _lifecycle_manifest_complete "${transaction}"; then
  printf 'ROLLBACK_FAIL:incomplete-manifest:%s\n' "${transaction}" >&2
  printf 'TRANSACTION:%s\n' "${transaction}" >&2
  exit 24
fi

_lifecycle_record_phase "${transaction}" rolling-back || {
  printf 'ROLLBACK_STATE:incomplete-rollback\n' >&2
  exit 22
}
ok=1
_lifecycle_restore_one "${transaction}/rollback/wrapper" "${wrapper_path}" 700 || ok=0
_lifecycle_restore_one "${transaction}/rollback/authorized_keys" "${authorized}" 600 || ok=0
rm -f "${wrapper_path}.candidate" "${authorized}.candidate" 2>/dev/null || true

verified=0
if [ "${ok}" -eq 1 ]; then
  verified=1
  _lifecycle_verify_one "${transaction}/rollback/wrapper" "${wrapper_path}" || verified=0
  _lifecycle_verify_one "${transaction}/rollback/authorized_keys" "${authorized}" || verified=0
fi

if [ "${ok}" -eq 1 ] && [ "${verified}" -eq 1 ]; then
  printf 'FILE_ROLLBACK_STATE:rolled-back\n'
else
  printf 'FILE_ROLLBACK_STATE:incomplete-rollback\n' >&2
fi
service_ok=0
_lifecycle_restore_service "$(_lifecycle_initial_state "${transaction}")" && service_ok=1
if [ "${ok}" -eq 1 ] && [ "${verified}" -eq 1 ] && [ "${service_ok}" -eq 1 ] \
    && _lifecycle_record_phase "${transaction}" rollback-complete \
    && _lifecycle_cleanup_verified_rollback; then
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
# rollback material for the currently pending (and, with an explicit
# argument, pointer-matching -- see `coreelec_lifecycle_remote_rollback_script`
# for why) transaction, after the CLI has already proven the restricted key
# restores the device to its initial state. It never touches the wrapper or
# authorized_keys themselves. A cleanup failure (the transaction directory
# could not be removed) is reported as its own distinct `cleanup-failed`
# state, never as a rollback. Identity-matched receipts survive directory
# deletion and pointer-unlink failure, including a lost success response.
coreelec_lifecycle_remote_finalize_script() {
  local root="${1:-/storage}" explicit_transaction="${2:-}"
  cat <<FINALIZE_HEADER
set -eu
umask 077
root='${root}'
explicit_transaction='${explicit_transaction}'
FINALIZE_HEADER
  _coreelec_lifecycle_remote_shared_lib
  cat <<'FINALIZE_BODY'
cache_root="${root}/.cache/kodi-lifecycle"
pointer_file="${cache_root}/current-transaction"
backup_root="${root}/backup/kodi-lifecycle"
finalizing_receipt="${cache_root}/finalizing-transaction"
finalized_receipt="${cache_root}/last-finalized-transaction"

cleanup_failed() {
  printf 'FINALIZE_STATE:cleanup-failed\n' >&2
  printf 'TRANSACTION:%s\n' "${transaction}" >&2
  exit 32
}

if [ ! -d "${backup_root}" ]; then
  printf 'FINALIZE_FAIL:no-pending-transaction\n' >&2
  exit 30
fi
backup_root_canon="$(_lifecycle_canon "${backup_root}")" || {
  printf 'FINALIZE_FAIL:no-pending-transaction\n' >&2
  exit 30
}
if [ -f "${pointer_file}" ] && [ ! -L "${pointer_file}" ]; then
  pointer_raw="$(cat "${pointer_file}")"
elif [ ! -e "${pointer_file}" ] && [ ! -L "${pointer_file}" ] \
    && [ -f "${finalized_receipt}" ] && [ ! -L "${finalized_receipt}" ]; then
  pointer_raw="$(cat "${finalized_receipt}")"
else
  printf 'FINALIZE_FAIL:no-pending-transaction\n' >&2
  exit 30
fi
pointer_transaction="$(_lifecycle_resolve_transaction "${pointer_raw}" "${backup_root_canon}" allow-missing)" || {
  printf 'FINALIZE_FAIL:invalid-transaction-path:pointer\n' >&2
  exit 31
}

if [ -n "${explicit_transaction}" ]; then
  candidate_transaction="$(_lifecycle_resolve_transaction "${explicit_transaction}" "${backup_root_canon}" allow-missing)" || {
    printf 'FINALIZE_FAIL:invalid-transaction-path:explicit\n' >&2
    exit 31
  }
  if [ "${candidate_transaction}" != "${pointer_transaction}" ]; then
    printf 'FINALIZE_FAIL:transaction-pointer-mismatch\n' >&2
    exit 33
  fi
  transaction="${candidate_transaction}"
else
  transaction="${pointer_transaction}"
fi

# A receipt outside the directory survives partial rm, a failed pointer
# unlink, and a lost response. Missing backups alone are never proof of
# successful cleanup. Both receipts name one validated transaction only.
if _lifecycle_receipt_matches "${finalizing_receipt}" "${transaction}"; then
  :
elif [ -e "${finalizing_receipt}" ] || [ -L "${finalizing_receipt}" ]; then
  printf 'FINALIZE_FAIL:transaction-receipt-mismatch\n' >&2
  exit 33
elif [ ! -e "${transaction}" ] \
    && _lifecycle_receipt_matches "${finalized_receipt}" "${transaction}"; then
  :
else
  if ! _lifecycle_manifest_complete "${transaction}"; then
    printf 'FINALIZE_FAIL:incomplete-manifest:%s\n' "${transaction}" >&2
    exit 34
  fi
  case "$(cat "${transaction}/phase")" in
    pending-verification|finalizing) ;;
    *)
      printf 'FINALIZE_FAIL:transaction-not-verified\n' >&2
      exit 34
      ;;
  esac
  _lifecycle_record_phase "${transaction}" finalizing || cleanup_failed
  _lifecycle_record_receipt "${finalizing_receipt}" "${transaction}" || cleanup_failed
fi

rm -rf "${transaction}" || cleanup_failed
if _lifecycle_receipt_matches "${finalizing_receipt}" "${transaction}"; then
  mv -f "${finalizing_receipt}" "${finalized_receipt}" || cleanup_failed
fi
rm -f "${pointer_file}" || cleanup_failed
printf 'FINALIZE_STATE:committed\n'
FINALIZE_BODY
}

# Renders the read-only administrator inspection program for
# `--inspect-transaction [DIR]`. With no directory, it inspects whatever the
# device's own pointer currently names. It reports which recovery items
# exist and whether a manifest is present, never their contents: a stray
# authorized_keys backup can carry other operators' key material, and that
# must never reach a report or a terminal.
coreelec_lifecycle_remote_inspect_script() {
  local root="${1:-/storage}" transaction_dir="${2:-}"
  cat <<INSPECT_HEADER
set -eu
root='${root}'
explicit_transaction='${transaction_dir}'
INSPECT_HEADER
  _coreelec_lifecycle_remote_shared_lib
  cat <<'INSPECT_BODY'
cache_root="${root}/.cache/kodi-lifecycle"
pointer_file="${cache_root}/current-transaction"
backup_root="${root}/backup/kodi-lifecycle"

if [ -n "${explicit_transaction}" ]; then
  candidate="${explicit_transaction}"
else
  if [ ! -f "${pointer_file}" ]; then
    printf 'INSPECT_STATE:missing\n'
    exit 0
  fi
  candidate="$(cat "${pointer_file}")"
fi

if [ ! -d "${backup_root}" ]; then
  printf 'INSPECT_STATE:missing\n'
  exit 0
fi
backup_root_canon="$(_lifecycle_canon "${backup_root}")" || {
  printf 'INSPECT_STATE:missing\n'
  exit 0
}
transaction="$(_lifecycle_resolve_transaction "${candidate}" "${backup_root_canon}" allow-missing)" || {
  printf 'INSPECT_STATE:invalid\n'
  exit 0
}

for receipt in finalizing-transaction last-finalized-transaction last-rolled-back-transaction; do
  if _lifecycle_receipt_matches "${cache_root}/${receipt}" "${transaction}"; then
    if _lifecycle_receipt_matches "${pointer_file}" "${transaction}"; then
      printf 'INSPECT_STATE:cleanup-pending\n'
    else
      printf 'INSPECT_STATE:completed\n'
    fi
    printf 'TRANSACTION:%s\n' "${transaction}"
    case "${receipt}" in
      last-rolled-back-transaction) printf 'COMPLETION:rolled-back\n' ;;
      *) printf 'COMPLETION:committed\n' ;;
    esac
    exit 0
  fi
done
if [ ! -d "${transaction}" ]; then
  printf 'INSPECT_STATE:invalid\n'
  exit 0
fi

printf 'INSPECT_STATE:present\n'
printf 'TRANSACTION:%s\n' "${transaction}"
if [ -f "${transaction}/manifest" ]; then
  printf 'MANIFEST:present\n'
  if initial_state="$(_lifecycle_initial_state "${transaction}")"; then
    printf 'INITIAL_STATE:%s\n' "${initial_state}"
  else
    printf 'INITIAL_STATE:unknown\n'
  fi
  case "$(cat "${transaction}/phase" 2>/dev/null)" in
    backing-up|prepared|installing|pending-verification|rolling-back|rollback-complete|finalizing)
      printf 'PHASE:%s\n' "$(cat "${transaction}/phase")" ;;
    *) printf 'PHASE:unknown\n' ;;
  esac
else
  printf 'MANIFEST:absent\n'
fi
for item in wrapper wrapper.absent authorized_keys authorized_keys.absent; do
  if [ -e "${transaction}/rollback/${item}" ]; then
    printf 'ROLLBACK_ITEM:%s:present\n' "${item}"
  else
    printf 'ROLLBACK_ITEM:%s:absent\n' "${item}"
  fi
done
INSPECT_BODY
}

# Renders the standalone administrator service-state-restoration program,
# sharing the exact restoration check used by transaction rollback. It forces
# `kodi.service` back to
# `initial_state` ("running" or "stopped") over the *administrator*
# transport and verifies the resulting state, so a restricted-verification
# failure can be diagnosed independently. Every mutating call is guarded so a failure
# never aborts the script before the final state check runs: whatever
# actually happened is always reported, never assumed. Uses the bare
# `systemctl` command, resolved via PATH, matching the deploy script's own
# `INITIAL_STATE` probe above: this program always runs on the
# administrator transport, where PATH already contains the real
# `/usr/bin`, so no parameterized path is needed here.
coreelec_lifecycle_remote_service_restore_script() {
  local initial_state="$1"
  [[ -n "${initial_state}" ]] || die "coreelec_lifecycle_remote_service_restore_script requires an initial state"
  cat <<SERVICE_RESTORE_HEADER
set -eu
initial_state='${initial_state}'
SERVICE_RESTORE_HEADER
  _coreelec_lifecycle_remote_shared_lib
  cat <<'SERVICE_RESTORE_BODY'
_lifecycle_restore_service "${initial_state}" || exit 41
SERVICE_RESTORE_BODY
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
  local command_pid watchdog_pid rc had_errexit
  # `errexit` is shell-global, not function-scoped: restore the caller's
  # original setting exactly rather than unconditionally turning it back on,
  # since every caller of this helper (e.g. `_controller_call` in
  # configure-kodi-lifecycle.sh) deliberately runs it with `set +e` in
  # effect and expects that to still hold immediately after this function
  # returns, however it exits.
  case "$-" in
    *e*) had_errexit=1 ;;
    *) had_errexit=0 ;;
  esac
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
  (( had_errexit )) && set -e
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
