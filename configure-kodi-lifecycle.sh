#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"

timestamp() {
  date -u '+%Y-%m-%dT%H:%M:%SZ'
}

info() {
  printf '[%s] %s\n' "$(timestamp)" "$*"
}

warn() {
  printf '[%s] WARNING: %s\n' "$(timestamp)" "$*" >&2
}

die() {
  printf '[%s] ERROR: %s\n' "$(timestamp)" "$*" >&2
  exit 1
}

# shellcheck source=lib/coreelec-config.sh
source "${SCRIPT_DIR}/lib/coreelec-config.sh"
# shellcheck source=lib/coreelec-ssh.sh
source "${SCRIPT_DIR}/lib/coreelec-ssh.sh"
# shellcheck source=lib/coreelec-lifecycle.sh
source "${SCRIPT_DIR}/lib/coreelec-lifecycle.sh"

REMOTE_ROOT="/storage"
REMOTE_OS_RELEASE="/etc/os-release"
REMOTE_SYSTEMCTL="/usr/bin/systemctl"

TARGET=""
CONTROLLER_PUBLIC_KEY=""
CONTROLLER_IDENTITY=""
IDENTITY_FILE="${HOME}/.ssh/coreelec_admin_ed25519"
SSH_PORT="22"
DRY_RUN="0"
REPORT_DIR="${PWD}/coreelec-lifecycle-reports"
KNOWN_HOSTS_FILE="${HOME}/.ssh/known_hosts"
ROLLBACK_TRANSACTION=""
INSPECT_TRANSACTION=""

usage() {
  cat <<USAGE
Usage:
  ${SCRIPT_NAME} --target HOST --controller-public-key FILE \\
    --controller-identity FILE [--identity-file FILE] [--ssh-port PORT] \\
    [--dry-run] [--report-dir DIR]

Options:
  --target HOST                CoreELEC IPv4 address or DNS/mDNS hostname
  --controller-public-key FILE Public key file for the restricted lifecycle
                                controller identity Home Assistant will use
  --controller-identity FILE   Matching private key file; used only to
                                confirm it pairs with --controller-public-key
                                and to run the post-install verification
                                over a separate, hardened SSH session
  --identity-file FILE         Administrator identity used for the
                                transactional install itself (default:
                                ${HOME}/.ssh/coreelec_admin_ed25519)
  --ssh-port PORT              SSH port for both connections (default: 22)
  --dry-run                    Render and validate the wrapper and key
                                entries and write a redacted plan without
                                making any SSH connection
  --report-dir DIR             Local report directory (default:
                                ${PWD}/coreelec-lifecycle-reports)
  --rollback-transaction DIR   Recovery: roll back one named transaction
                                directory on --target and exit
  --inspect-transaction DIR    Recovery: report which rollback material a
                                named transaction directory on --target
                                still holds, without printing its contents
  --version                    Print script version
  -h, --help                    Show this help

This command installs a restricted, forced-command SSH identity on the
CoreELEC target that can only run \`start\`, \`stop\`, or \`status\` against
kodi.service, verifies it end to end over that restricted identity, and
either commits or rolls back the change. Reports never contain public or
private key material.
USAGE
}

parse_args() {
  while (( $# > 0 )); do
    case "$1" in
      --target)
        (( $# >= 2 )) || die "--target requires a host"
        validate_host "$2" "--target"
        TARGET="$2"
        shift 2
        ;;
      --controller-public-key)
        (( $# >= 2 )) || die "--controller-public-key requires a path"
        CONTROLLER_PUBLIC_KEY="$2"
        shift 2
        ;;
      --controller-identity)
        (( $# >= 2 )) || die "--controller-identity requires a path"
        CONTROLLER_IDENTITY="$2"
        shift 2
        ;;
      --identity-file)
        (( $# >= 2 )) || die "--identity-file requires a path"
        IDENTITY_FILE="$2"
        shift 2
        ;;
      --ssh-port)
        (( $# >= 2 )) || die "--ssh-port requires a port"
        validate_port "--ssh-port" "$2"
        SSH_PORT="$2"
        shift 2
        ;;
      --dry-run)
        DRY_RUN="1"
        shift
        ;;
      --report-dir)
        (( $# >= 2 )) || die "--report-dir requires a path"
        coreelec_config_validate_path "--report-dir" "$2"
        REPORT_DIR="$2"
        shift 2
        ;;
      --rollback-transaction)
        (( $# >= 2 )) || die "--rollback-transaction requires a transaction directory"
        coreelec_config_validate_path "--rollback-transaction" "$2"
        ROLLBACK_TRANSACTION="$2"
        shift 2
        ;;
      --inspect-transaction)
        (( $# >= 2 )) || die "--inspect-transaction requires a transaction directory"
        coreelec_config_validate_path "--inspect-transaction" "$2"
        INSPECT_TRANSACTION="$2"
        shift 2
        ;;
      --emit-remote-script)
        # Hidden test-support hook, matching provision-coreelec.sh's
        # convention: prints one rendered remote program and exits, so the
        # transaction scripts can be unit tested locally without any SSH
        # involvement. Not documented in --help.
        (( $# >= 2 )) || die "--emit-remote-script requires NAME"
        # Note: deliberately `shift` then pass "$@" rather than slice with
        # "${@:2}" -- under this script's custom IFS, Bash 3.2's positional
        # parameter *offset slicing* collapses all remaining arguments into
        # one word (a real, reproduced Bash 3.2 quirk), while plain "$@"
        # after a `shift` is unaffected by IFS and preserves each argument.
        shift
        _emit_remote_script "$@"
        exit 0
        ;;
      --version)
        printf '%s\n' "${SCRIPT_VERSION}"
        exit 0
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
  done
}

# Internal test entry point: prints one remote transaction script instead of
# running it, exactly mirroring provision-coreelec.sh's --emit-remote-script
# convention so this transaction can be exercised locally against fixture
# binaries (see tests/test-coreelec-lifecycle.sh).
_emit_remote_script() {
  local name="$1" root="${2:-${REMOTE_ROOT}}"
  case "${name}" in
    deploy)
      local os_release_path="${3:-${REMOTE_OS_RELEASE}}" public_key_file="${4:-}"
      local systemctl_path="${5:-${REMOTE_SYSTEMCTL}}"
      [[ -n "${public_key_file}" ]] || die "--emit-remote-script deploy requires a public key file"
      local normalized restrict_entry fallback_entry wrapper_content
      normalized="$(coreelec_lifecycle_validate_public_key "${public_key_file}")"
      restrict_entry="$(coreelec_lifecycle_key_entry "${normalized}")"
      fallback_entry="$(coreelec_lifecycle_key_entry_fallback "${normalized}")"
      wrapper_content="$(coreelec_lifecycle_render_wrapper "${systemctl_path}")"
      coreelec_lifecycle_remote_deploy_script \
        "${root}" "${os_release_path}" "${wrapper_content}" "${restrict_entry}" "${fallback_entry}"
      ;;
    rollback)
      coreelec_lifecycle_remote_rollback_script "${root}" "${3:-}"
      ;;
    finalize)
      coreelec_lifecycle_remote_finalize_script "${root}"
      ;;
    inspect)
      coreelec_lifecycle_remote_inspect_script "${root}" "${3:-}"
      ;;
    *)
      die "--emit-remote-script expects deploy, rollback, finalize, or inspect, not: ${name}"
      ;;
  esac
}

# Validates that the controller identity actually pairs with the supplied
# controller public key, before this program ever contacts the target. Only
# the normalized type and blob are compared -- never a fingerprint that would
# require logging a key -- and the comparison happens whether or not
# --dry-run was requested, matching the brief's "reject mismatch before
# contacting the target" requirement.
validate_controller_key_pair() {
  local scratch="$1" derived_public normalized_supplied normalized_derived
  derived_public="${scratch}/controller-identity-public.tmp"
  rm -f "${derived_public}"
  ssh-keygen -y -f "${CONTROLLER_IDENTITY}" > "${derived_public}" 2>/dev/null \
    || die "Unable to derive a public key from --controller-identity ${CONTROLLER_IDENTITY}"
  normalized_supplied="$(coreelec_lifecycle_validate_public_key "${CONTROLLER_PUBLIC_KEY}")"
  normalized_derived="$(coreelec_lifecycle_validate_public_key "${derived_public}")"
  rm -f "${derived_public}"
  [[ "$(awk '{print $1, $2}' <<<"${normalized_supplied}")" \
      == "$(awk '{print $1, $2}' <<<"${normalized_derived}")" ]] \
    || die "--controller-public-key does not match --controller-identity"
}

# --- Report writing --------------------------------------------------------

report_path() {
  local sanitized
  sanitized="$(printf '%s' "${TARGET}" | tr -c 'A-Za-z0-9._-' '_')"
  printf '%s/%s-%s.txt\n' "${REPORT_DIR}" "${sanitized}" "$(date -u '+%Y%m%dT%H%M%SZ')"
}

# Scans the finished report for the two things it must never contain: the
# normalized controller key blob, and the first nonempty line of the private
# controller identity file. Either one appearing deletes the report and
# fails the run -- a redacted report is a load-bearing guarantee, not best
# effort.
report_redaction_check() {
  local report_file="$1" key_blob identity_line
  key_blob="$(awk '{print $2}' <<<"$(coreelec_lifecycle_validate_public_key "${CONTROLLER_PUBLIC_KEY}")")"
  if [[ -n "${key_blob}" ]] && grep -F -q -- "${key_blob}" "${report_file}"; then
    rm -f -- "${report_file}"
    die "The report contained the normalized controller key blob and was deleted"
  fi
  identity_line="$(grep -m1 '[^[:space:]]' "${CONTROLLER_IDENTITY}" || true)"
  if [[ -n "${identity_line}" ]] && grep -F -q -- "${identity_line}" "${report_file}"; then
    rm -f -- "${report_file}"
    die "The report contained the private controller identity's first line and was deleted"
  fi
}

write_report() {
  local file="$1"
  umask 077
  mkdir -p "${REPORT_DIR}"
  chmod 700 "${REPORT_DIR}"
  {
    printf 'report_format=coreelec-lifecycle-deployment-report-1\n'
    printf 'script_version=%s\n' "${SCRIPT_VERSION}"
    printf 'created_utc=%s\n' "$(timestamp)"
    printf 'target=%s\n' "${TARGET}"
    printf 'dry_run=%s\n' "${DRY_RUN}"
    printf 'wrapper_path=%s\n' "${REMOTE_ROOT}/.config/kodi-lifecycle"
    printf 'controller_key_supplied=%s\n' "$([[ -n "${CONTROLLER_PUBLIC_KEY}" ]] && echo 1 || echo 0)"
    printf 'controller_identity_supplied=%s\n' "$([[ -n "${CONTROLLER_IDENTITY}" ]] && echo 1 || echo 0)"
    if [[ "${DRY_RUN}" == "1" ]]; then
      printf 'deployment_state=dry-run\n'
    else
      printf 'deployment_state=%s\n' "${DEPLOYMENT_STATE}"
      [[ -z "${KEY_MODE:-}" ]] || printf 'key_mode=%s\n' "${KEY_MODE}"
      [[ -z "${TRANSACTION:-}" ]] || printf 'transaction=%s\n' "${TRANSACTION}"
      if [[ -n "${VERIFICATION_ATTEMPTED:-}" ]]; then
        printf 'restricted.status=%s\n' "${RESTRICTED_STATUS}"
        printf 'restricted.start=%s\n' "${RESTRICTED_START}"
        printf 'restricted.stop=%s\n' "${RESTRICTED_STOP}"
        printf 'restricted.arbitrary_command_denied=%s\n' "${RESTRICTED_ARBITRARY}"
        printf 'restored_state=%s\n' "${RESTORED_STATE}"
      fi
    fi
  } > "${file}"
  chmod 600 "${file}"
  if [[ "${DRY_RUN}" != "1" ]]; then
    report_redaction_check "${file}"
  fi
}

# --- Controller verification -----------------------------------------------

# Runs one controller command, requiring its stdout to equal "${expected}"
# exactly and its stderr to be empty. Sets CONTROLLER_LAST_RC. Never treats a
# nonzero exit as fatal to the caller -- the caller decides how to react.
_controller_call() {
  local remote_command="$1" expected="$2" scratch="$3" out_file err_file actual
  out_file="${scratch}/controller-stdout.tmp"
  err_file="${scratch}/controller-stderr.tmp"
  rm -f "${out_file}" "${err_file}"
  set +e
  coreelec_lifecycle_ssh_controller "${remote_command}" >"${out_file}" 2>"${err_file}"
  CONTROLLER_LAST_RC=$?
  set -e
  actual="$(cat "${out_file}")"
  [[ "${CONTROLLER_LAST_RC}" -eq 0 && "${actual}" == "${expected}" && ! -s "${err_file}" ]]
}

# Attempts an arbitrary (disallowed) command and requires the connection to
# fail: proof that the forced-command restriction, not merely the wrapper's
# own goodwill, is what confines this identity.
_controller_denied() {
  local scratch="$1"
  set +e
  coreelec_lifecycle_ssh_controller "id" >/dev/null 2>/dev/null
  CONTROLLER_LAST_RC=$?
  set -e
  [[ "${CONTROLLER_LAST_RC}" -ne 0 ]]
}

# Runs the full 7-call restore sequence plus the arbitrary-command denial
# check, and sets RESTRICTED_STATUS/START/STOP/ARBITRARY and RESTORED_STATE.
# Returns success only when every one of those checks passed and the device
# was returned to its pre-deployment state.
run_verification() {
  local initial_state="$1" scratch="$2"
  local start_or_stop start_or_stop_expected overall=0
  VERIFICATION_ATTEMPTED="1"
  RESTRICTED_STATUS="pass"
  RESTRICTED_START="pass"
  RESTRICTED_STOP="pass"
  RESTRICTED_ARBITRARY="pass"

  _controller_call "status" "${initial_state}" "${scratch}" || RESTRICTED_STATUS="fail"
  _controller_call "start" "running" "${scratch}" || RESTRICTED_START="fail"
  _controller_call "status" "running" "${scratch}" || RESTRICTED_STATUS="fail"
  _controller_call "stop" "stopped" "${scratch}" || RESTRICTED_STOP="fail"
  _controller_call "status" "stopped" "${scratch}" || RESTRICTED_STATUS="fail"

  if [[ "${initial_state}" == "running" ]]; then
    start_or_stop="start"
    start_or_stop_expected="running"
  else
    start_or_stop="stop"
    start_or_stop_expected="stopped"
  fi
  if ! _controller_call "${start_or_stop}" "${start_or_stop_expected}" "${scratch}"; then
    if [[ "${start_or_stop}" == "start" ]]; then RESTRICTED_START="fail"; else RESTRICTED_STOP="fail"; fi
    overall=1
  fi

  # The final status call is both the last exact-output check and the
  # authoritative record of the restored state, whatever it turned out to be.
  rm -f "${scratch}/controller-stdout.tmp" "${scratch}/controller-stderr.tmp"
  set +e
  coreelec_lifecycle_ssh_controller "status" \
    >"${scratch}/controller-stdout.tmp" 2>"${scratch}/controller-stderr.tmp"
  CONTROLLER_LAST_RC=$?
  set -e
  RESTORED_STATE="$(cat "${scratch}/controller-stdout.tmp")"
  if [[ "${CONTROLLER_LAST_RC}" -ne 0 || -s "${scratch}/controller-stderr.tmp" \
        || -z "${RESTORED_STATE}" ]]; then
    RESTRICTED_STATUS="fail"
    RESTORED_STATE="${RESTORED_STATE:-unknown}"
  fi

  _controller_denied "${scratch}" || RESTRICTED_ARBITRARY="fail"

  [[ "${RESTRICTED_STATUS}" == "pass" && "${RESTRICTED_START}" == "pass" \
     && "${RESTRICTED_STOP}" == "pass" && "${RESTRICTED_ARBITRARY}" == "pass" \
     && "${RESTORED_STATE}" == "${initial_state}" && "${overall}" -eq 0 ]]
}

# --- Main flow --------------------------------------------------------------

run_recovery_mode() {
  local script output rc
  if [[ -n "${ROLLBACK_TRANSACTION}" ]]; then
    [[ -n "${TARGET}" ]] || die "--target is required"
    script="$(coreelec_lifecycle_remote_rollback_script "${REMOTE_ROOT}" "${ROLLBACK_TRANSACTION}")"
    set +e
    output="$(coreelec_ssh_batch "${script}" 2>&1)"
    rc=$?
    set -e
    printf '%s\n' "${output}"
    exit "${rc}"
  fi
  if [[ -n "${INSPECT_TRANSACTION}" ]]; then
    [[ -n "${TARGET}" ]] || die "--target is required"
    script="$(coreelec_lifecycle_remote_inspect_script "${REMOTE_ROOT}" "${INSPECT_TRANSACTION}")"
    output="$(coreelec_ssh_batch "${script}")"
    printf '%s\n' "${output}"
    exit 0
  fi
}

main() {
  # Deliberately not `local`: the EXIT trap below runs after main returns,
  # once the function's own local scope is already gone, so it needs a
  # variable that is still set at that point.
  scratch=""
  local report_file
  parse_args "$@"

  if [[ -n "${ROLLBACK_TRANSACTION}" || -n "${INSPECT_TRANSACTION}" ]]; then
    run_recovery_mode
    return 0
  fi

  [[ -n "${TARGET}" ]] || die "--target is required"
  [[ -n "${CONTROLLER_PUBLIC_KEY}" ]] || die "--controller-public-key is required"
  [[ -n "${CONTROLLER_IDENTITY}" ]] || die "--controller-identity is required"
  [[ -f "${CONTROLLER_PUBLIC_KEY}" ]] || die "--controller-public-key file does not exist: ${CONTROLLER_PUBLIC_KEY}"
  [[ -f "${CONTROLLER_IDENTITY}" ]] || die "--controller-identity file does not exist: ${CONTROLLER_IDENTITY}"

  mkdir -p "${REPORT_DIR}"
  chmod 700 "${REPORT_DIR}"
  scratch="${REPORT_DIR}/.scratch.$$"
  rm -rf "${scratch}"
  mkdir -p "${scratch}"
  chmod 700 "${scratch}"
  trap 'rm -rf "${scratch:-}"' EXIT

  validate_controller_key_pair "${scratch}"

  # Local, SSH-free rendering and validation, always performed: dry-run stops
  # here, a real run continues on to the transaction below.
  local normalized_key restrict_entry fallback_entry wrapper_content
  normalized_key="$(coreelec_lifecycle_validate_public_key "${CONTROLLER_PUBLIC_KEY}")"
  restrict_entry="$(coreelec_lifecycle_key_entry "${normalized_key}")"
  fallback_entry="$(coreelec_lifecycle_key_entry_fallback "${normalized_key}")"
  wrapper_content="$(coreelec_lifecycle_render_wrapper "${REMOTE_SYSTEMCTL}")"

  if [[ "${DRY_RUN}" == "1" ]]; then
    report_file="$(report_path)"
    write_report "${report_file}"
    printf 'Report: %s\n' "${report_file}"
    return 0
  fi

  local deploy_script deploy_output deploy_rc
  deploy_script="$(coreelec_lifecycle_remote_deploy_script \
    "${REMOTE_ROOT}" "${REMOTE_OS_RELEASE}" "${wrapper_content}" "${restrict_entry}" "${fallback_entry}")"
  set +e
  deploy_output="$(coreelec_ssh_batch "${deploy_script}" 2>&1)"
  deploy_rc=$?
  set -e
  info "Deploy transaction output:"
  printf '%s\n' "${deploy_output}"

  INITIAL_STATE="$(printf '%s\n' "${deploy_output}" | sed -n 's/^INITIAL_STATE:\(.*\)$/\1/p' | tail -1)"
  TRANSACTION="$(printf '%s\n' "${deploy_output}" | sed -n 's/^TRANSACTION:\(.*\)$/\1/p' | tail -1)"
  KEY_MODE="$(printf '%s\n' "${deploy_output}" | sed -n 's/^KEY_MODE:\(.*\)$/\1/p' | tail -1)"
  local deploy_state
  deploy_state="$(printf '%s\n' "${deploy_output}" | sed -n 's/^DEPLOY_STATE:\([^:]*\).*$/\1/p' | tail -1)"

  if [[ "${deploy_rc}" -ne 0 || "${deploy_state}" != "pending-verification" ]]; then
    DEPLOYMENT_STATE="${deploy_state:-rolled-back}"
    report_file="$(report_path)"
    write_report "${report_file}"
    warn "Deployment did not reach pending-verification: ${DEPLOYMENT_STATE}"
    if [[ "${DEPLOYMENT_STATE}" == "incomplete-rollback" ]]; then
      printf 'Recovery: %s --target %s --rollback-transaction %s\n' \
        "${SCRIPT_NAME}" "${TARGET}" "${TRANSACTION}"
      printf 'Recovery: %s --target %s --inspect-transaction %s\n' \
        "${SCRIPT_NAME}" "${TARGET}" "${TRANSACTION}"
    fi
    printf 'Report: %s\n' "${report_file}"
    exit 1
  fi

  if run_verification "${INITIAL_STATE}" "${scratch}"; then
    local finalize_script finalize_output
    finalize_script="$(coreelec_lifecycle_remote_finalize_script "${REMOTE_ROOT}")"
    set +e
    finalize_output="$(coreelec_ssh_batch "${finalize_script}" 2>&1)"
    set -e
    if grep -q '^FINALIZE_STATE:committed$' <<<"${finalize_output}"; then
      DEPLOYMENT_STATE="committed"
    else
      DEPLOYMENT_STATE="incomplete-rollback"
    fi
  else
    local rollback_script rollback_output
    rollback_script="$(coreelec_lifecycle_remote_rollback_script "${REMOTE_ROOT}" "${TRANSACTION}")"
    set +e
    rollback_output="$(coreelec_ssh_batch "${rollback_script}" 2>&1)"
    set -e
    if grep -q '^ROLLBACK_STATE:rolled-back$' <<<"${rollback_output}"; then
      DEPLOYMENT_STATE="rolled-back"
    else
      DEPLOYMENT_STATE="incomplete-rollback"
    fi
  fi

  report_file="$(report_path)"
  write_report "${report_file}"

  if [[ "${DEPLOYMENT_STATE}" == "incomplete-rollback" ]]; then
    printf 'Recovery: %s --target %s --rollback-transaction %s\n' \
      "${SCRIPT_NAME}" "${TARGET}" "${TRANSACTION}"
    printf 'Recovery: %s --target %s --inspect-transaction %s\n' \
      "${SCRIPT_NAME}" "${TARGET}" "${TRANSACTION}"
  fi

  printf 'Report: %s\n' "${report_file}"
  [[ "${DEPLOYMENT_STATE}" == "committed" ]]
}

main "$@"
