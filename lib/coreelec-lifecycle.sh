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
