#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
# shellcheck source=lib/coreelec-addon-workflows.sh
source "${SCRIPT_DIR}/lib/coreelec-addon-workflows.sh"

TARGET=""
INTERACTIVE="0"
DRY_RUN="0"
ADDONS=()

usage() {
  cat <<'USAGE'
Usage:
  configure-coreelec-addons.sh --target HOST [--config PATH]
    [--addon ID ...] [--interactive] [--dry-run] [--report-dir PATH]

Options:
  --target HOST             CoreELEC IPv4 address or DNS/mDNS hostname
  --config PATH             Strict KEY=value settings file (default:
                             config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf)
  --addon ID                Run only this supported pinned add-on workflow;
                             repeatable
  --interactive             Allow guided GUI workflows for add-ons that cannot
                             finish non-interactively
  --dry-run                 Validate configuration and render the report
                             without contacting the device; every selected
                             add-on receives the static status dry-run
  --report-dir PATH         Local report directory
  --version                 Print script version
  -h, --help                Show this help

Supported post-deployment add-ons:
  weather.ha                 fully-unattended
  pvr.nextpvr                fully-unattended
  script.plexmod             fully-unattended / guided (--interactive)
  plugin.video.youtube      guided (--interactive)
  plugin.service.emby-next-gen guided (--interactive)

The default run performs non-interactive checks only. Use --interactive
before any PM4K account, YouTube, or Emby GUI workflow.
This command does not write Home Assistant, NextPVR, or PM4K local-mode
settings. Supply those values to provision-coreelec.sh first, then use this
command to validate them. See config/README.md for the complete input matrix.
Dry-run makes zero SSH/device calls and transmits no secrets, including when
combined with --interactive.
USAGE
}

preparse_config_path() {
  local args=("$@")
  local i=0
  while (( i < ${#args[@]} )); do
    case "${args[i]}" in
      --config)
        (( i + 1 < ${#args[@]} )) || die "--config requires a path"
        CONFIG_FILE="${args[i+1]}"
        i=$((i + 2))
        ;;
      *)
        i=$((i + 1))
        ;;
    esac
  done
}

parse_args() {
  while (( $# > 0 )); do
    case "$1" in
      --target)
        (( $# >= 2 )) || die "--target requires a host"
        validate_host "$2" "TARGET"
        TARGET="$2"
        shift 2
        ;;
      --config)
        (( $# >= 2 )) || die "--config requires a path"
        CONFIG_FILE="$2"
        shift 2
        ;;
      --addon)
        (( $# >= 2 )) || die "--addon requires an add-on ID"
        coreelec_config_add_cli_addon "$2"
        shift 2
        ;;
      --interactive)
        INTERACTIVE="1"
        shift
        ;;
      --dry-run)
        DRY_RUN="1"
        shift
        ;;
      --report-dir)
        (( $# >= 2 )) || die "--report-dir requires a path"
        coreelec_config_apply_cli "REPORT_DIR" "$2"
        shift 2
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

coreelec_postdeploy_pinned_addon() {
  local wanted="$1" record addon_id
  for record in ${ADDON_ARTIFACTS[@]+"${ADDON_ARTIFACTS[@]}"}; do
    addon_id="${record%%|*}"
    [[ "${addon_id}" == "${wanted}" ]] && return 0
  done
  return 1
}

coreelec_postdeploy_selected_addons() {
  local supported
  if (( ${#ADDONS[@]} > 0 )); then
    printf '%s\n' "${ADDONS[@]}"
    return 0
  fi
  while IFS= read -r supported; do
    [[ -n "${supported}" ]] || continue
    if coreelec_postdeploy_pinned_addon "${supported}"; then
      printf '%s\n' "${supported}"
    fi
  done <<EOF
$(coreelec_postdeploy_supported_addons)
EOF
}

validate_selected_addons() {
  local addon_id selected_any=0
  while IFS= read -r addon_id; do
    [[ -n "${addon_id}" ]] || continue
    selected_any=1
    coreelec_postdeploy_pinned_addon "${addon_id}" \
      || die "--addon ${addon_id} is not in the locked artifact manifest; add an ADDON_ARTIFACT record for it first"
    coreelec_postdeploy_supported_addon "${addon_id}" \
      || die "No post-deployment workflow is defined for add-on: ${addon_id}"
  done <<EOF
$(coreelec_postdeploy_selected_addons)
EOF
  (( selected_any == 1 )) || die "No supported pinned add-ons were selected for post-deployment configuration"
}

prepare_interactive_secrets() {
  local addon_id
  [[ "${INTERACTIVE}" == "1" ]] || return 0
  [[ "${DRY_RUN}" != "1" ]] || return 0
  [[ -n "${EMBY_SERVER_URL:-}" && -n "${EMBY_USERNAME:-}" ]] || return 0
  while IFS= read -r addon_id; do
    if [[ "${addon_id}" == "plugin.service.emby-next-gen" ]]; then
      coreelec_prepare_emby_password || true
      return 0
    fi
  done <<EOF
$(coreelec_postdeploy_selected_addons)
EOF
}

selected_addons_csv() {
  local addon_id output=""
  while IFS= read -r addon_id; do
    [[ -n "${addon_id}" ]] || continue
    if [[ -n "${output}" ]]; then
      output="${output},"
    fi
    output="${output}${addon_id}"
  done <<EOF
$(coreelec_postdeploy_selected_addons)
EOF
  printf '%s\n' "${output}"
}

report_path() {
  local sanitized
  sanitized="$(printf '%s' "${TARGET}" | tr -c 'A-Za-z0-9._-' '_')"
  printf '%s/%s-%s.txt\n' "${REPORT_DIR}" "${sanitized}" "$(date -u '+%Y%m%dT%H%M%SZ')"
}

report_redaction_check() {
  local report_file="$1" name value
  while IFS= read -r name; do
    [[ -n "${name}" ]] || continue
    value="$(coreelec_postdeploy_secret_value "${name}")"
    [[ -n "${value}" ]] || continue
    if printf '%s\n' "${value}" | grep -v '^[[:space:]]*$' | grep -F -q -f - "${report_file}"; then
      rm -f -- "${report_file}"
      die "The report contained the literal value of ${name} and was deleted"
    fi
  done <<EOF
$(coreelec_postdeploy_secret_names)
EOF
}

write_report() {
  local file="$1" capability_state="$2" addon_id status
  umask 077
  mkdir -p "${REPORT_DIR}"
  # The private umask protects creation; explicit modes remain defense in depth.
  chmod 700 "${REPORT_DIR}"
  {
    printf 'report_format=coreelec-addon-configuration-report-1\n'
    printf 'script_version=%s\n' "${SCRIPT_VERSION}"
    printf 'created_utc=%s\n' "$(timestamp)"
    printf 'target=%s\n' "${TARGET}"
    printf 'config_file=%s\n' "${CONFIG_FILE}"
    printf 'interactive=%s\n' "${INTERACTIVE}"
    printf 'dry_run=%s\n' "${DRY_RUN}"
    printf 'selected_addons=%s\n' "$(selected_addons_csv)"
    printf 'jsonrpc_capabilities=%s\n' "${capability_state}"
    while IFS= read -r addon_id; do
      [[ -n "${addon_id}" ]] || continue
      printf 'addon.%s.interaction_level=%s\n' "${addon_id}" \
        "$(coreelec_postdeploy_addon_interaction_level "${addon_id}")"
      if [[ "${DRY_RUN}" == "1" ]]; then
        status="dry-run"
      else
        status="$(run_addon_workflow "${addon_id}")"
      fi
      printf 'addon.%s.status=%s\n' "${addon_id}" "${status}"
    done <<EOF
$(coreelec_postdeploy_selected_addons)
EOF
  } > "${file}"
  chmod 600 "${file}"
  report_redaction_check "${file}"
}

main() {
  local report_file capability_state="skipped"
  coreelec_config_defaults
  preparse_config_path "$@"
  coreelec_config_load "${CONFIG_FILE}"
  parse_args "$@"
  [[ -n "${TARGET}" ]] || die "--target is required"
  coreelec_config_validate
  validate_selected_addons
  prepare_interactive_secrets

  if [[ "${DRY_RUN}" != "1" ]]; then
    coreelec_prepare_kodi_web_password
    kodi_capabilities >/dev/null
    capability_state="validated"
  fi

  report_file="$(report_path)"
  write_report "${report_file}" "${capability_state}"

  printf 'Report: %s\n' "${report_file}"
}

main "$@"
