#!/bin/bash

# Shared SSH transport helpers for the CoreELEC provisioner and post-deployment
# add-on/lifecycle CLIs. `die` is owned by the calling CLI (provision-coreelec.sh
# or configure-coreelec-addons.sh); this library only calls it if already
# defined by the sourcing script, matching the existing library pattern.

if ! declare -F die >/dev/null 2>&1; then
  die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
  }
fi

# Validates the globals every SSH helper below depends on: `TARGET` and
# `SSH_PORT` must already be set by the calling CLI. `caller_name` is only
# used to make a missing-global failure point at the helper that needed it.
_coreelec_ssh_require_connection_globals() {
  local caller_name="$1"
  [[ -n "${TARGET:-}" ]] || die "TARGET is required before calling ${caller_name}"
  [[ -n "${SSH_PORT:-}" ]] || die "SSH_PORT is required before calling ${caller_name}"
}

# Runs one remote command over a hardened, key-only SSH session and returns
# its exit status unchanged. The remote command travels as exactly one argv
# word -- the current post-deployment transport -- so it is re-parsed exactly
# once, by the device's login shell.
coreelec_ssh_command() {
  local remote_command="$1"
  local identity_file="${IDENTITY_FILE:-${HOME}/.ssh/coreelec_admin_ed25519}"
  [[ "$#" -eq 1 ]] || die "coreelec_ssh_command requires one remote command"
  _coreelec_ssh_require_connection_globals "coreelec_ssh_command"
  ssh \
    -p "${SSH_PORT}" \
    -o BatchMode=yes \
    -o ConnectTimeout=12 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    -i "${identity_file}" \
    -o IdentitiesOnly=yes \
    -o PreferredAuthentications=publickey \
    -o PasswordAuthentication=no \
    -o KbdInteractiveAuthentication=no \
    "root@${TARGET}" \
    "${remote_command}"
}

# Streams a remote shell program on stdin to `sh -s`, leaving `sh` and `-s` as
# the only remote-command argv words. Used for lifecycle programs that must
# never be re-parsed by the device's login shell.
coreelec_ssh_batch() {
  local remote_script="$1"
  [[ "$#" -eq 1 ]] || die "coreelec_ssh_batch requires one remote script"
  printf '%s\n' "${remote_script}" |
    coreelec_ssh_command 'sh -s'
}

# Reads the administrator public key file and prints exactly one normalized
# key line. The grammar is enforced here, once, because the line is embedded
# in a program the device runs: a validated line is a single line of a known
# key type, a base64 blob, and an optional control-character-free comment, so
# it can never contain a quote, a newline, or the here-document delimiter that
# carries it. Carriage returns are stripped -- one inside authorized_keys
# makes the key silently unusable.
coreelec_public_key_line() {
  local key_file="$1" normalized line_count line
  [[ -f "${key_file}" ]] || die "The administrator public key file is missing: ${key_file}"
  normalized="$(sed -e 's/\r$//' -e 's/[[:space:]]*$//' "${key_file}" | grep '[^[:space:]]' || true)"
  line_count="$(printf '%s\n' "${normalized}" | grep -c '[^[:space:]]' || true)"
  [[ "${line_count}" == "1" ]] \
    || die "Expected exactly one public key line in ${key_file}, found ${line_count}"
  line="$(printf '%s\n' "${normalized}" | head -1)"
  printf '%s\n' "${line}" | grep -Eq \
    '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com) [A-Za-z0-9+/]+={0,3}( [^[:cntrl:]]*)?$' \
    || die "The administrator public key in ${key_file} is not a well-formed OpenSSH public key line"
  printf '%s\n' "${line}"
}
