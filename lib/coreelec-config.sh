#!/bin/bash

# Strict, sourceable configuration interface for provision-coreelec.sh.
#
# The configuration file is declarative KEY=value data, never shell code: it
# is read line-by-line and dispatched through an explicit case allowlist. No
# line is ever passed to eval, source, or indirect expansion, so shell syntax
# embedded in a value is inert data, not a command.
#
# Precedence: coreelec_config_defaults() < coreelec_config_load(FILE) <
# coreelec_config_apply_cli(NAME VALUE) < secret environment variables (which
# are only ever read, never assigned, by coreelec_config_validate()).

# Bash 3.2 compatible: no associative arrays, no `declare -g`, no `mapfile`.

# Fall back to a minimal die() when this library is sourced standalone (e.g.
# by the test suite) without provision-coreelec.sh's timestamped version.
if ! declare -F die >/dev/null 2>&1; then
  die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
  }
fi

# --- Generic validation primitives (also used directly by the CLI parser) ---

validate_host() {
  local value="$1" label="${2:-HOST}"
  case "${value}" in
    ""|-*|*[!A-Za-z0-9._-]*)
      die "${label} must be an IPv4 address or hostname containing only letters, digits, dot, underscore, and hyphen"
      ;;
  esac
}

validate_identifier() {
  local label="$1"
  local value="$2"
  case "${value}" in
    ""|-*|*[!A-Za-z0-9._-]*)
      die "${label} contains unsupported characters: ${value}"
      ;;
  esac
}

validate_port() {
  local label="$1"
  local value="$2"
  local numeric_value
  case "${value}" in
    ""|*[!0-9]*) die "${label} must be a decimal port number" ;;
  esac
  if (( ${#value} > 5 )); then
    die "${label} must be between 1 and 65535"
  fi
  numeric_value=$((10#${value}))
  if (( numeric_value < 1 || numeric_value > 65535 )); then
    die "${label} must be between 1 and 65535"
  fi
}

# --- Configuration-specific validators ---

coreelec_config_validate_bool() {
  local label="$1" value="$2"
  case "${value}" in
    0|1) ;;
    *) die "${label} must be 0 or 1" ;;
  esac
}

# Free-text display strings such as "USA (12h)" or "English QWERTY".
coreelec_config_validate_text() {
  local label="$1" value="$2"
  case "${value}" in
    "") die "${label} must not be empty" ;;
    *[!A-Za-z0-9\ \(\)_.,\'/-]*)
      die "${label} contains unsupported characters: ${value}"
      ;;
  esac
}

# Rejects shell metacharacters so command substitution or quoting embedded in
# a value is refused rather than silently stored; the value is never
# evaluated either way.
coreelec_config_validate_path() {
  local label="$1" value="$2"
  [[ -n "${value}" ]] || die "${label} must not be empty"
  case "${value}" in
    *'$'*|*'`'*|*';'*|*'|'*|*'&'*|*'<'*|*'>'*|*'"'*|*"'"*)
      die "${label} contains unsupported characters"
      ;;
  esac
}

# A relative zoneinfo path such as "America/Los_Angeles".
coreelec_config_validate_timezone() {
  local value="$1"
  case "${value}" in
    "") die "TIMEZONE must not be empty" ;;
    /*) die "TIMEZONE must be a relative zoneinfo path" ;;
    *..*) die "TIMEZONE must not contain .." ;;
    *[!A-Za-z0-9_+/-]*) die "TIMEZONE contains unsupported characters: ${value}" ;;
  esac
}

coreelec_config_validate_url() {
  local label="$1" value="$2"
  case "${value}" in
    https://?*) ;;
    *) die "${label} must be an https:// URL" ;;
  esac
}

coreelec_config_ipv4_is_private_or_loopback() {
  local value="$1" old_ifs="$IFS" first second third fourth octet
  local restore_pathname_expansion=0
  case "$-" in
    *f*) ;;
    *)
      set -f
      restore_pathname_expansion=1
      ;;
  esac
  IFS=.
  set -- ${value}
  IFS="${old_ifs}"
  if (( restore_pathname_expansion == 1 )); then
    set +f
  fi
  [[ "$#" -eq 4 ]] || return 1
  first="$1"
  second="$2"
  third="$3"
  fourth="$4"
  for octet in "${first}" "${second}" "${third}" "${fourth}"; do
    case "${octet}" in
      ""|*[!0-9]*) return 1 ;;
    esac
    (( 10#${octet} <= 255 )) || return 1
  done
  (( 10#${first} == 10 )) && return 0
  (( 10#${first} == 127 )) && return 0
  (( 10#${first} == 192 && 10#${second} == 168 )) && return 0
  (( 10#${first} == 172 && 10#${second} >= 16 && 10#${second} <= 31 )) && return 0
  return 1
}

coreelec_config_validate_emby_url() {
  local value="$1" remainder authority host suffix port=""
  case "${value}" in
    https://*) remainder="${value#https://}" ;;
    http://*) remainder="${value#http://}" ;;
    *) die "EMBY_SERVER_URL must be an https:// URL" ;;
  esac
  case "${value}" in
    *[[:space:]]*|*'@'*) die "EMBY_SERVER_URL contains unsupported URL syntax" ;;
  esac
  authority="${remainder%%/*}"
  [[ -n "${authority}" ]] || die "EMBY_SERVER_URL must include a host"
  case "${authority}" in
    \[*\]*)
      host="${authority%%]*}"
      host="${host#[}"
      suffix="${authority#*]}"
      case "${suffix}" in
        "") ;;
        :*) port="${suffix#:}" ;;
        *) die "EMBY_SERVER_URL contains unsupported URL syntax" ;;
      esac
      case "${port}" in *[!0-9]*) die "EMBY_SERVER_URL has an invalid port" ;; esac
      ;;
    *:*)
      host="${authority%%:*}"
      port="${authority#*:}"
      case "${port}" in ""|*[!0-9]*) die "EMBY_SERVER_URL has an invalid port" ;; esac
      ;;
    *) host="${authority}" ;;
  esac
  [[ -n "${host}" ]] || die "EMBY_SERVER_URL must include a host"
  [[ -z "${port}" ]] || validate_port "EMBY_SERVER_URL port" "${port}"

  case "${value}" in
    https://*) return 0 ;;
  esac
  [[ "${EMBY_ALLOW_LOCAL_HTTP}" == "1" ]] \
    || die "EMBY_SERVER_URL requires https unless EMBY_ALLOW_LOCAL_HTTP=1 is set"
  case "${host}" in
    localhost|::1) return 0 ;;
  esac
  coreelec_config_ipv4_is_private_or_loopback "${host}" \
    || die "EMBY_SERVER_URL HTTP host must be RFC1918 or loopback"
}

coreelec_config_validate_enum() {
  local label="$1" value="$2"
  shift 2
  local allowed
  for allowed in "$@"; do
    [[ "${value}" == "${allowed}" ]] && return 0
  done
  die "${label} must be one of: $*"
}

# A comma-separated list of numeric IDs, e.g. "1,2,3".
coreelec_config_validate_id_list() {
  local label="$1" value="$2" token
  [[ -n "${value}" ]] || die "${label} must not be empty"
  local remainder="${value}"
  while [[ -n "${remainder}" ]]; do
    token="${remainder%%,*}"
    case "${token}" in
      ""|*[!0-9]*) die "${label} must be a comma-separated list of numeric IDs: ${value}" ;;
    esac
    case "${remainder}" in
      *,*) remainder="${remainder#*,}" ;;
      *) remainder="" ;;
    esac
  done
}

# --- Defaults ---

coreelec_config_defaults() {
  CONFIG_FILE="config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf"
  EXPECTED_RELEASE="21.3"
  SSH_PORT="22"
  KODI_PORT="8080"
  KODI_USER="homeassistant"
  REPORT_DIR="${PWD}/coreelec-provision-reports"
  APPLY_KODI="1"
  HARDEN_SSH="1"
  FORCE_UNSUPPORTED="0"
  ASSUME_YES="0"

  TIMEZONE_COUNTRY="United States"
  TIMEZONE="America/Los_Angeles"
  LOCALE_LANGUAGE="resource.language.en_us"
  LOCALE_COUNTRY="USA (12h)"
  KEYBOARD_LAYOUT="English QWERTY"
  ADDON_UPDATE_MODE="notify"

  HOME_ASSISTANT_URL=""
  HOME_ASSISTANT_WEATHER_ENTITY=""
  HOME_ASSISTANT_SUN_ENTITY=""

  NEXTPVR_HOST=""
  NEXTPVR_PORT=""
  NEXTPVR_PROTOCOL=""
  NEXTPVR_INSTANCE_NAME=""

  PLEX_SERVER_HOST=""
  PLEX_SERVER_PORT=""
  PLEX_SERVER_NAME=""
  PLEX_PROFILE_IDS=""

  EMBY_SERVER_URL=""
  EMBY_USERNAME=""
  EMBY_ALLOW_LOCAL_HTTP="0"

  ADDON_ARTIFACTS=()

  COREELEC_CONFIG_SEEN_KEYS=$'\n'
}

# --- Strict parser ---

# Explicit allowlist dispatch. Never uses eval, source, indirect expansion,
# or generated variable names. `is_cli` (0/1) distinguishes a config-file
# assignment (duplicate scalar keys are rejected) from a CLI override
# (always allowed to win over a config value).
coreelec_config_assign() {
  local source="$1" line_number="$2" key="$3" value="$4" is_cli="${5:-0}"
  local location="${source}:${line_number}"
  if [[ "${is_cli}" == "1" ]]; then
    location="command line (${key})"
  fi

  case "${key}" in
    KODI_WEB_PASSWORD|OMDB_API_KEY|MDBLIST_API_KEY|YOUTUBE_API_KEY|YOUTUBE_CLIENT_ID|YOUTUBE_CLIENT_SECRET|HOME_ASSISTANT_TOKEN|NEXTPVR_PIN|PLEX_TOKEN|EMBY_PASSWORD|TMDB_API_KEY)
      die "${location}: ${key} is a secret and must be supplied only as an environment variable"
      ;;
  esac

  if [[ "${is_cli}" != "1" && "${key}" != "ADDON_ARTIFACT" ]]; then
    case "${COREELEC_CONFIG_SEEN_KEYS}" in
      *$'\n'"${key}"$'\n'*)
        die "${location}: duplicate configuration key: ${key}"
        ;;
    esac
    COREELEC_CONFIG_SEEN_KEYS="${COREELEC_CONFIG_SEEN_KEYS}${key}"$'\n'
  fi

  case "${key}" in
    EXPECTED_RELEASE)
      validate_identifier "EXPECTED_RELEASE" "${value}"
      EXPECTED_RELEASE="${value}"
      ;;
    SSH_PORT)
      validate_port "SSH_PORT" "${value}"
      SSH_PORT="${value}"
      ;;
    KODI_PORT)
      validate_port "KODI_PORT" "${value}"
      KODI_PORT="${value}"
      ;;
    KODI_USER)
      validate_identifier "KODI_USER" "${value}"
      KODI_USER="${value}"
      ;;
    REPORT_DIR)
      coreelec_config_validate_path "REPORT_DIR" "${value}"
      REPORT_DIR="${value}"
      ;;
    APPLY_KODI)
      coreelec_config_validate_bool "APPLY_KODI" "${value}"
      APPLY_KODI="${value}"
      ;;
    HARDEN_SSH)
      coreelec_config_validate_bool "HARDEN_SSH" "${value}"
      HARDEN_SSH="${value}"
      ;;
    FORCE_UNSUPPORTED)
      coreelec_config_validate_bool "FORCE_UNSUPPORTED" "${value}"
      FORCE_UNSUPPORTED="${value}"
      ;;
    ASSUME_YES)
      coreelec_config_validate_bool "ASSUME_YES" "${value}"
      ASSUME_YES="${value}"
      ;;
    TIMEZONE_COUNTRY)
      coreelec_config_validate_text "TIMEZONE_COUNTRY" "${value}"
      TIMEZONE_COUNTRY="${value}"
      ;;
    TIMEZONE)
      coreelec_config_validate_timezone "${value}"
      TIMEZONE="${value}"
      ;;
    LOCALE_LANGUAGE)
      validate_identifier "LOCALE_LANGUAGE" "${value}"
      LOCALE_LANGUAGE="${value}"
      ;;
    LOCALE_COUNTRY)
      coreelec_config_validate_text "LOCALE_COUNTRY" "${value}"
      LOCALE_COUNTRY="${value}"
      ;;
    KEYBOARD_LAYOUT)
      coreelec_config_validate_text "KEYBOARD_LAYOUT" "${value}"
      KEYBOARD_LAYOUT="${value}"
      ;;
    ADDON_UPDATE_MODE)
      coreelec_config_validate_enum "ADDON_UPDATE_MODE" "${value}" "notify" "auto"
      ADDON_UPDATE_MODE="${value}"
      ;;
    HOME_ASSISTANT_URL)
      coreelec_config_validate_url "HOME_ASSISTANT_URL" "${value}"
      HOME_ASSISTANT_URL="${value}"
      ;;
    HOME_ASSISTANT_WEATHER_ENTITY)
      validate_identifier "HOME_ASSISTANT_WEATHER_ENTITY" "${value}"
      HOME_ASSISTANT_WEATHER_ENTITY="${value}"
      ;;
    HOME_ASSISTANT_SUN_ENTITY)
      validate_identifier "HOME_ASSISTANT_SUN_ENTITY" "${value}"
      HOME_ASSISTANT_SUN_ENTITY="${value}"
      ;;
    NEXTPVR_HOST)
      validate_host "${value}" "NEXTPVR_HOST"
      NEXTPVR_HOST="${value}"
      ;;
    NEXTPVR_PORT)
      validate_port "NEXTPVR_PORT" "${value}"
      NEXTPVR_PORT="${value}"
      ;;
    NEXTPVR_PROTOCOL)
      coreelec_config_validate_enum "NEXTPVR_PROTOCOL" "${value}" "http" "https"
      NEXTPVR_PROTOCOL="${value}"
      ;;
    NEXTPVR_INSTANCE_NAME)
      coreelec_config_validate_text "NEXTPVR_INSTANCE_NAME" "${value}"
      NEXTPVR_INSTANCE_NAME="${value}"
      ;;
    PLEX_SERVER_HOST)
      validate_host "${value}" "PLEX_SERVER_HOST"
      PLEX_SERVER_HOST="${value}"
      ;;
    PLEX_SERVER_PORT)
      validate_port "PLEX_SERVER_PORT" "${value}"
      PLEX_SERVER_PORT="${value}"
      ;;
    PLEX_SERVER_NAME)
      coreelec_config_validate_text "PLEX_SERVER_NAME" "${value}"
      PLEX_SERVER_NAME="${value}"
      ;;
    PLEX_PROFILE_IDS)
      coreelec_config_validate_id_list "PLEX_PROFILE_IDS" "${value}"
      PLEX_PROFILE_IDS="${value}"
      ;;
    EMBY_SERVER_URL)
      [[ -n "${value}" ]] || die "EMBY_SERVER_URL must not be empty"
      EMBY_SERVER_URL="${value}"
      ;;
    EMBY_USERNAME)
      [[ -n "${value}" ]] || die "EMBY_USERNAME must not be empty"
      EMBY_USERNAME="${value}"
      ;;
    EMBY_ALLOW_LOCAL_HTTP)
      coreelec_config_validate_bool "EMBY_ALLOW_LOCAL_HTTP" "${value}"
      EMBY_ALLOW_LOCAL_HTTP="${value}"
      ;;
    ADDON_ARTIFACT)
      [[ -n "${value}" ]] || die "${location}: ADDON_ARTIFACT must not be empty"
      ADDON_ARTIFACTS+=("${value}")
      ;;
    *)
      die "${location}: unknown configuration key: ${key}"
      ;;
  esac
}

coreelec_config_load() {
  local file="$1" line line_number=0 key value trimmed
  [[ -r "${file}" ]] || die "Configuration file is not readable: ${file}"
  COREELEC_CONFIG_SEEN_KEYS=$'\n'
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line_number=$((line_number + 1))
    # Trim leading whitespace only to recognize blank/comment lines; the
    # documented grammar accepts a comment whose first non-whitespace
    # character is '#'. The raw, untrimmed line is still used for KEY=value
    # extraction below.
    trimmed="${line#"${line%%[![:space:]]*}"}"
    case "${trimmed}" in
      ''|'#'*) continue ;;
      *=*) key="${line%%=*}"; value="${line#*=}" ;;
      *) die "${file}:${line_number}: expected KEY=value" ;;
    esac
    coreelec_config_assign "${file}" "${line_number}" "${key}" "${value}" 0
  done < "${file}"
}

coreelec_config_apply_cli() {
  local name="$1" value="$2"
  coreelec_config_assign "cli" "0" "${name}" "${value}" 1
}

coreelec_config_add_cli_addon() {
  local id="$1"
  validate_identifier "Add-on ID" "${id}"
  ADDONS+=("${id}")
}

# Semantic cross-field validation performed after defaults, config file, and
# CLI overrides have all been applied. Secret environment variables are read
# here only to check presence/companionship; their values are never stored
# in a global, logged, or copied into a diagnostic string.
coreelec_config_validate() {
  local youtube_present=0
  if [[ "${APPLY_KODI}" == "1" && -z "${KODI_WEB_PASSWORD:-}" ]]; then
    die "KODI_WEB_PASSWORD must be set in the shared .env file when APPLY_KODI=1"
  fi

  [[ -n "${YOUTUBE_API_KEY:-}" ]] && youtube_present=$((youtube_present + 1))
  [[ -n "${YOUTUBE_CLIENT_ID:-}" ]] && youtube_present=$((youtube_present + 1))
  [[ -n "${YOUTUBE_CLIENT_SECRET:-}" ]] && youtube_present=$((youtube_present + 1))
  if (( youtube_present != 0 && youtube_present != 3 )); then
    die "YOUTUBE_API_KEY, YOUTUBE_CLIENT_ID, and YOUTUBE_CLIENT_SECRET must be all present or all absent"
  fi

  if [[ -n "${HOME_ASSISTANT_TOKEN:-}" && -z "${HOME_ASSISTANT_URL:-}" ]]; then
    die "HOME_ASSISTANT_TOKEN requires HOME_ASSISTANT_URL to be configured"
  fi
  if [[ -n "${NEXTPVR_PIN:-}" && -z "${NEXTPVR_HOST:-}" ]]; then
    die "NEXTPVR_PIN requires NEXTPVR_HOST to be configured"
  fi
  if [[ -n "${PLEX_TOKEN:-}" && -z "${PLEX_SERVER_HOST:-}" ]]; then
    die "PLEX_TOKEN requires PLEX_SERVER_HOST to be configured"
  fi
  if [[ -n "${EMBY_SERVER_URL:-}" ]]; then
    coreelec_config_validate_emby_url "${EMBY_SERVER_URL}"
  fi
  if [[ -n "${EMBY_PASSWORD:-}" \
     && ( -z "${EMBY_SERVER_URL:-}" || -z "${EMBY_USERNAME:-}" ) ]]; then
    die "EMBY_PASSWORD requires EMBY_SERVER_URL and EMBY_USERNAME to be configured"
  fi

  return 0
}
