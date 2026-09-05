#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"
# shellcheck source=lib/coreelec-config.sh
source "${SCRIPT_DIR}/../lib/coreelec-config.sh"

test_defaults_are_pacific_english_us() {
  coreelec_config_defaults
  assert_eq "America/Los_Angeles" "${TIMEZONE}" "default timezone"
  assert_eq "United States" "${TIMEZONE_COUNTRY}" "default timezone country"
  assert_eq "resource.language.en_us" "${LOCALE_LANGUAGE}" "default locale language"
  assert_eq "USA (12h)" "${LOCALE_COUNTRY}" "default locale country"
  assert_eq "English QWERTY" "${KEYBOARD_LAYOUT}" "default keyboard layout"
}

test_comments_blank_lines_and_values_are_parsed() {
  local dir file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  cat > "${file}" <<'CONF'
# a leading comment

   # an indented comment

KODI_PORT=8181
CONF
  coreelec_config_defaults
  coreelec_config_load "${file}"
  assert_eq "8181" "${KODI_PORT}" "KODI_PORT parsed from file"
}

test_repeated_addon_artifacts_preserve_order() {
  local dir file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  cat > "${file}" <<'CONF'
ADDON_ARTIFACT=plugin.service.emby-next-gen|1.0.0|https://example.test/a.zip|deadbeef
ADDON_ARTIFACT=script.plexmod|2.0.0|https://example.test/b.zip|cafebabe
ADDON_ARTIFACT=plugin.video.youtube|3.0.0|https://example.test/c.zip|abad1dea
CONF
  coreelec_config_defaults
  coreelec_config_load "${file}"
  assert_eq "3" "${#ADDON_ARTIFACTS[@]}" "three artifacts recorded"
  assert_contains "${ADDON_ARTIFACTS[0]}" "plugin.service.emby-next-gen" "first artifact preserved"
  assert_contains "${ADDON_ARTIFACTS[1]}" "script.plexmod" "second artifact preserved"
  assert_contains "${ADDON_ARTIFACTS[2]}" "plugin.video.youtube" "third artifact preserved"
}

test_duplicate_scalar_key_is_rejected() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  cat > "${file}" <<'CONF'
KODI_PORT=8080
KODI_PORT=9090
CONF
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "duplicate scalar key must be rejected"
  assert_contains "${output}" "duplicate configuration key" "duplicate error message"
}

test_unknown_key_is_rejected() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  printf 'NOT_A_REAL_KEY=1\n' > "${file}"
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "unknown key must be rejected"
  assert_contains "${output}" "unknown configuration key" "unknown key error message"
}

test_malformed_line_is_rejected() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  printf 'this line has no equals sign\n' > "${file}"
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "malformed line must be rejected"
  assert_contains "${output}" "expected KEY=value" "malformed line error message"
}

test_shell_syntax_is_data_not_executed() {
  local dir file sentinel rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  sentinel="${dir}/sentinel"
  printf 'REPORT_DIR=$(touch "%s")\n' "${sentinel}" > "${file}"
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  if [[ -e "${sentinel}" ]]; then
    echo "sentinel file was created: shell syntax was executed"
    return 1
  fi
  if (( rc == 0 )); then
    assert_contains "${REPORT_DIR}" '$(touch' "literal value retained without execution"
  else
    assert_contains "${output}" "REPORT_DIR" "value rejected without execution"
  fi
}

test_secret_key_in_config_is_rejected() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  printf 'OMDB_API_KEY=super-secret-value\n' > "${file}"
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "secret key in config must be rejected"
  assert_contains "${output}" "OMDB_API_KEY" "error names the offending key"
  assert_contains "${output}" "secret" "error explains why it was rejected"
  assert_not_contains "${output}" "super-secret-value" "error must not leak the value"
}

test_cli_value_overrides_config_value() {
  local dir file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  printf 'KODI_PORT=9000\n' > "${file}"
  coreelec_config_defaults
  coreelec_config_load "${file}"
  assert_eq "9000" "${KODI_PORT}" "config value applied before CLI override"
  coreelec_config_apply_cli "KODI_PORT" "8080"
  assert_eq "8080" "${KODI_PORT}" "CLI override wins over config value"
}

test_target_is_not_loaded_from_shared_config() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  printf 'TARGET=192.0.2.10\n' > "${file}"
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "TARGET must not be a loadable config key"
  assert_contains "${output}" "unknown configuration key" "TARGET is rejected as unknown"
}

test_partial_youtube_credentials_are_rejected() {
  coreelec_config_defaults
  local rc output
  set +e
  output="$(YOUTUBE_API_KEY="key" coreelec_config_validate 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "partial YouTube credentials must be rejected"
  assert_contains "${output}" "YOUTUBE_API_KEY" "error mentions YouTube credentials"
}

test_service_secret_without_endpoint_is_rejected() {
  coreelec_config_defaults
  local rc output
  set +e
  output="$(NEXTPVR_PIN="1234" coreelec_config_validate 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "NEXTPVR_PIN without NEXTPVR_HOST must be rejected"
  assert_contains "${output}" "NEXTPVR_HOST" "error names the required companion value"
  assert_not_contains "${output}" "1234" "error must not leak the secret value"
}

test_missing_optional_secrets_are_allowed() {
  coreelec_config_defaults
  local rc
  set +e
  (
    unset OMDB_API_KEY MDBLIST_API_KEY YOUTUBE_API_KEY YOUTUBE_CLIENT_ID \
      YOUTUBE_CLIENT_SECRET HOME_ASSISTANT_TOKEN NEXTPVR_PIN PLEX_TOKEN 2>/dev/null
    coreelec_config_validate
  )
  rc=$?
  set -e
  assert_success "${rc}" "missing optional secrets must be allowed"
}

run_all_tests \
  test_defaults_are_pacific_english_us \
  test_comments_blank_lines_and_values_are_parsed \
  test_repeated_addon_artifacts_preserve_order \
  test_duplicate_scalar_key_is_rejected \
  test_unknown_key_is_rejected \
  test_malformed_line_is_rejected \
  test_shell_syntax_is_data_not_executed \
  test_secret_key_in_config_is_rejected \
  test_cli_value_overrides_config_value \
  test_target_is_not_loaded_from_shared_config \
  test_partial_youtube_credentials_are_rejected \
  test_service_secret_without_endpoint_is_rejected \
  test_missing_optional_secrets_are_allowed
