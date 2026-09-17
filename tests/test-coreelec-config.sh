#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"
# shellcheck source=lib/coreelec-config.sh
source "${SCRIPT_DIR}/../lib/coreelec-config.sh"

KODI_WEB_PASSWORD="test-kodi-password"
PROVISIONER="${SCRIPT_DIR}/../provision-coreelec.sh"

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
ADDON_ARTIFACT=weather.ha|3.0.0|https://example.test/c.zip|abad1dea
CONF
  coreelec_config_defaults
  coreelec_config_load "${file}"
  assert_eq "3" "${#ADDON_ARTIFACTS[@]}" "three artifacts recorded"
  assert_contains "${ADDON_ARTIFACTS[0]}" "plugin.service.emby-next-gen" "first artifact preserved"
  assert_contains "${ADDON_ARTIFACTS[1]}" "script.plexmod" "second artifact preserved"
  assert_contains "${ADDON_ARTIFACTS[2]}" "weather.ha" "third artifact preserved"
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

test_kodi_password_in_config_is_rejected_as_a_secret() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  printf 'KODI_WEB_PASSWORD=super-secret-value\n' > "${file}"
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "KODI_WEB_PASSWORD in config must be rejected" || return 1
  assert_contains "${output}" "KODI_WEB_PASSWORD" "error names the offending key" || return 1
  assert_contains "${output}" "secret" "error identifies the shared secret boundary" || return 1
  assert_not_contains "${output}" "super-secret-value" "error must not leak the password"
}

test_service_locations_in_config_are_rejected_as_secrets() {
  local dir file key value rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"

  for key in HOME_ASSISTANT_URL NEXTPVR_HOST; do
    case "${key}" in
      HOME_ASSISTANT_URL) value="https://homeassistant.example.lan:8123" ;;
      NEXTPVR_HOST) value="nextpvr.example.lan" ;;
    esac
    printf '%s=%s\n' "${key}" "${value}" > "${file}"
    coreelec_config_defaults
    set +e
    output="$(coreelec_config_load "${file}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "${key} in config must be rejected" || return 1
    assert_contains "${output}" "${key}" "error names ${key}" || return 1
    assert_contains "${output}" "secret" "error identifies the shared secret boundary" || return 1
    assert_not_contains "${output}" "${value}" "error must not leak ${key}" || return 1
  done
}

test_removed_local_service_inputs_are_unknown() {
  local dir file key rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"

  for key in \
    PLEX_SERVER_HOST PLEX_SERVER_PORT PLEX_SERVER_NAME PLEX_PROFILE_IDS \
    PLEX_TOKEN EMBY_SERVER_URL EMBY_USERNAME EMBY_ALLOW_LOCAL_HTTP EMBY_PASSWORD; do
    printf '%s=removed-value\n' "${key}" > "${file}"
    coreelec_config_defaults
    set +e
    output="$(coreelec_config_load "${file}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "${key} must no longer be accepted" || return 1
    assert_contains "${output}" "unknown configuration key: ${key}" \
      "${key} is outside the supported input contract" || return 1
  done
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

test_default_component_plan_is_full_baseline() {
  local output
  output="$(bash "${PROVISIONER}" --print-component-plan)"
  assert_contains "${output}" "components.requested=baseline"
  assert_contains "${output}" "components.effective=core,cec,addons,services,skin"
  assert_contains "${output}" "components.dependencies_added=none"
}

test_legacy_addon_filter_preserves_default_baseline() {
  local output
  output="$(bash "${PROVISIONER}" --no-kodi --addon script.plexmod \
    --print-component-plan)"
  assert_contains "${output}" "components.requested=baseline"
  assert_contains "${output}" "components.effective=core,cec,addons,services,skin"
  assert_contains "${output}" "components.dependencies_added=none"
}

test_explicit_cec_plan_is_isolated() {
  local output
  output="$(bash "${PROVISIONER}" --component cec --print-component-plan)"
  assert_contains "${output}" "components.requested=cec"
  assert_contains "${output}" "components.effective=cec"
  assert_contains "${output}" "components.dependencies_added=none"
}

test_skin_expands_dependencies_in_stable_order() {
  local output
  output="$(bash "${PROVISIONER}" --component skin --print-component-plan)"
  assert_contains "${output}" "components.requested=skin"
  assert_contains "${output}" "components.effective=core,addons,skin"
  assert_contains "${output}" "components.dependencies_added=core,addons"
}

test_services_expands_addons_dependency() {
  local output
  output="$(bash "${PROVISIONER}" --component services --print-component-plan)"
  assert_contains "${output}" "components.requested=services"
  assert_contains "${output}" "components.effective=addons,services"
  assert_contains "${output}" "components.dependencies_added=addons"
}

test_explicit_addon_implies_addons_component() {
  local output
  output="$(bash "${PROVISIONER}" --component cec --addon script.plexmod \
    --print-component-plan)"
  assert_contains "${output}" "components.requested=cec,addons"
  assert_contains "${output}" "components.effective=cec,addons"
  assert_contains "${output}" "components.dependencies_added=none"
}

test_duplicate_component_requests_are_normalized() {
  local output
  output="$(bash "${PROVISIONER}" --component skin --component skin \
    --component core --print-component-plan)"
  assert_contains "${output}" "components.requested=skin,core"
  assert_contains "${output}" "components.effective=core,addons,skin"
  assert_contains "${output}" "components.dependencies_added=addons"
}

test_explicit_baseline_expands_full_plan() {
  local output
  output="$(bash "${PROVISIONER}" --component baseline --print-component-plan)"
  assert_contains "${output}" "components.requested=baseline"
  assert_contains "${output}" "components.effective=core,cec,addons,services,skin"
  assert_contains "${output}" "components.dependencies_added=none"
}

test_unknown_component_is_rejected() {
  local output rc
  set +e
  output="$(bash "${PROVISIONER}" --component imaginary --print-component-plan 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "unknown component must be rejected"
  assert_contains "${output}" "Unknown component: imaginary"
}

test_unimplemented_room_component_is_rejected() {
  local output rc
  set +e
  output="$(bash "${PROVISIONER}" --component room --print-component-plan 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "room component must be rejected until implemented"
  assert_contains "${output}" "Component is not implemented: room"
}

test_no_kodi_conflicts_with_explicit_components() {
  local output rc
  set +e
  output="$(bash "${PROVISIONER}" --no-kodi --component cec \
    --print-component-plan 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "--no-kodi must conflict with explicit components"
  assert_contains "${output}" "--no-kodi cannot be used with --component"
}

test_empty_component_request_is_rejected() {
  local output rc
  set +e
  output="$(bash "${PROVISIONER}" --component "" --print-component-plan 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "empty component request must be rejected"
  assert_contains "${output}" "Effective component plan is empty"
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

test_service_location_secrets_are_validated() {
  local rc output

  coreelec_config_defaults
  set +e
  output="$(HOME_ASSISTANT_URL="not-a-url" coreelec_config_validate 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an invalid Home Assistant URL must be rejected" || return 1
  assert_contains "${output}" "HOME_ASSISTANT_URL" "the invalid URL is identified" || return 1
  assert_not_contains "${output}" "not-a-url" "the secret URL value is not echoed" || return 1

  coreelec_config_defaults
  set +e
  output="$(NEXTPVR_HOST='bad host' coreelec_config_validate 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an invalid NextPVR host must be rejected" || return 1
  assert_contains "${output}" "NEXTPVR_HOST" "the invalid host is identified" || return 1
  assert_not_contains "${output}" "bad host" "the secret host value is not echoed"
}

test_missing_optional_secrets_are_allowed() {
  coreelec_config_defaults
  local rc
  set +e
  (
    unset OMDB_API_KEY MDBLIST_API_KEY HOME_ASSISTANT_TOKEN NEXTPVR_PIN \
      PLEX_TOKEN EMBY_PASSWORD 2>/dev/null
    KODI_WEB_PASSWORD="configured-kodi-password"
    coreelec_config_validate
  )
  rc=$?
  set -e
  assert_success "${rc}" "missing optional secrets must be allowed"
}

test_kodi_baseline_requires_password_from_shared_environment() {
  coreelec_config_defaults
  local rc output
  set +e
  output="$({
    unset KODI_WEB_PASSWORD
    coreelec_config_validate
  } 2>&1)"
  rc=$?
  set -e

  assert_failure "${rc}" "Kodi configuration must require the shared web password" || return 1
  assert_contains "${output}" "KODI_WEB_PASSWORD" "the missing variable is named" || return 1
  assert_contains "${output}" ".env" "the error identifies the shared environment source"
}

test_emby_url_requires_https_unless_local_http_is_explicitly_allowed() {
  local rc output

  coreelec_config_defaults
  coreelec_config_assign "test.conf" "1" "EMBY_SERVER_URL" "https://emby.example.test:8920" 0
  coreelec_config_assign "test.conf" "2" "EMBY_USERNAME" "media-user" 0
  coreelec_config_validate

  coreelec_config_defaults
  coreelec_config_assign "test.conf" "1" "EMBY_SERVER_URL" "http://192.168.50.10:8096" 0
  coreelec_config_assign "test.conf" "2" "EMBY_USERNAME" "media-user" 0
  set +e
  output="$(coreelec_config_validate 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "local HTTP must require an explicit opt-in" || return 1
  assert_contains "${output}" "EMBY_ALLOW_LOCAL_HTTP=1" "HTTP rejection explains the local opt-in" || return 1

  coreelec_config_defaults
  coreelec_config_assign "test.conf" "1" "EMBY_SERVER_URL" "http://172.20.1.9:8096" 0
  coreelec_config_assign "test.conf" "2" "EMBY_USERNAME" "media-user" 0
  coreelec_config_assign "test.conf" "3" "EMBY_ALLOW_LOCAL_HTTP" "1" 0
  coreelec_config_validate

  coreelec_config_defaults
  coreelec_config_assign "test.conf" "1" "EMBY_SERVER_URL" "http://emby.example.test:8096" 0
  coreelec_config_assign "test.conf" "2" "EMBY_USERNAME" "media-user" 0
  coreelec_config_assign "test.conf" "3" "EMBY_ALLOW_LOCAL_HTTP" "1" 0
  set +e
  output="$(coreelec_config_validate 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "public HTTP must remain forbidden after local HTTP opt-in" || return 1
  assert_contains "${output}" "RFC1918 or loopback" "public HTTP rejection explains the host restriction"
}

test_private_ipv4_validation_does_not_expand_pathnames() {
  local dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  touch "${dir}/17"

  set +e
  output="$(
    cd "${dir}"
    coreelec_config_ipv4_is_private_or_loopback '10.?7.0.1' 2>&1
  )"
  rc=$?
  set -e

  assert_failure "${rc}" \
    "an invalid wildcard octet must not become a valid private address by matching a pathname" || return 1
  assert_eq "" "${output}" "invalid wildcard IPv4 input is rejected without shell expansion output"
}

test_emby_password_requires_server_and_username() {
  local rc output

  coreelec_config_defaults
  set +e
  output="$(EMBY_PASSWORD="emby-password-secret" coreelec_config_validate 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "Emby password without endpoint and username must be rejected" || return 1
  assert_contains "${output}" "EMBY_SERVER_URL and EMBY_USERNAME" "error names both required companions" || return 1
  assert_not_contains "${output}" "emby-password-secret" "pairing error must not leak the password"
}

test_emby_password_is_rejected_in_config() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  printf 'EMBY_PASSWORD=emby-password-secret\n' > "${file}"
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "EMBY_PASSWORD in config must be rejected" || return 1
  assert_contains "${output}" "EMBY_PASSWORD" "error names EMBY_PASSWORD" || return 1
  assert_contains "${output}" "secret" "error explains why the password was rejected" || return 1
  assert_not_contains "${output}" "emby-password-secret" "error must not leak the password"
}

# --- Production configuration ----------------------------------------------

PRODUCTION_CONFIG="${SCRIPT_DIR}/../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf"

# Publisher commit that added the stable PM4K 1.3.19 repository package.
PLEXMOD_COMMIT="eba134ac09bfe4916b3511d1e377bf6bb03a947e"

# A change detector, not a proof. This list is a transcription of the
# artifact IDs reviewed and recorded in provision.conf; comparing it against
# the same file cannot by itself establish that the dependency closure is
# complete. Closure completeness is established out of band by resolving each
# pinned add-on's <requires><import> entries against its publisher's index
# (recorded in provision.conf and the task report); this test only fails loudly
# when the locked set drifts from the set that was reviewed.
#
# Kodi's own bundled add-ons (script.module.pil, script.module.pycryptodome,
# resource.language.en_gb, ...) are deliberately absent; see
# system/addon-manifest.xml in xbmc/xbmc @ Omega.
reviewed_artifact_ids() {
  cat <<'IDS'
inputstream.adaptive
inputstream.ffmpegdirect
plugin.service.emby-next-gen
plugin.video.themoviedb.helper
pvr.nextpvr
repository.emby.kodi
repository.dontpanic
repository.jurialmunkey
script.artistslideshow
resource.images.arctic.waves
resource.images.moviecountryicons.maps
resource.images.studios.white
resource.images.weatherfanart.multi
resource.font.robotocjksc
resource.images.studios.coloured
resource.images.weathericons.white
resource.uisounds.fromashes
resource.language.en_us
script.module.addon.signals
script.module.certifi
script.module.chardet
script.module.defusedxml
script.module.dateutil
script.module.future
script.module.idna
script.module.infotagger
script.module.inputstreamhelper
script.module.iso8601
script.module.jurialmunkey
script.module.kodi-six
script.module.pysocks
script.module.qrcode
script.module.requests
script.module.six
script.module.urllib3
script.module.yaml
script.plexmod
script.skinvariables
script.texturemaker
skin.arctic.fuse.3
weather.ha
IDS
}

# Prints "id<TAB>version" for every ADDON_ARTIFACT record currently loaded.
artifact_id_versions() {
  local record
  for record in ${ADDON_ARTIFACTS[@]+"${ADDON_ARTIFACTS[@]}"}; do
    printf '%s\t%s\n' "${record%%|*}" "$(cut -d'|' -f2 <<< "${record}")"
  done
}

assert_artifact_version() {
  local id="$1" version="$2" pairs
  pairs="$(artifact_id_versions)"
  assert_contains "${pairs}" "$(printf '%s\t%s' "${id}" "${version}")" \
    "${id} is locked at ${version}"
}

test_production_config_sets_pacific_english_us_baseline() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  assert_eq "21.3" "${EXPECTED_RELEASE}" "EXPECTED_RELEASE"
  assert_eq "United States" "${TIMEZONE_COUNTRY}" "TIMEZONE_COUNTRY"
  assert_eq "America/Los_Angeles" "${TIMEZONE}" "TIMEZONE"
  assert_eq "resource.language.en_us" "${LOCALE_LANGUAGE}" "LOCALE_LANGUAGE"
  assert_eq "USA (12h)" "${LOCALE_COUNTRY}" "LOCALE_COUNTRY"
  assert_eq "English QWERTY" "${KEYBOARD_LAYOUT}" "KEYBOARD_LAYOUT"
  assert_eq "notify" "${ADDON_UPDATE_MODE}" "ADDON_UPDATE_MODE"
  # The Kodi web account is the one Home Assistant authenticates as; renaming
  # it would break the documented Home Assistant integration.
  assert_eq "homeassistant" "${KODI_USER}" "KODI_USER"
}

test_production_config_carries_no_secret_values() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  local rc
  set +e
  (
    unset OMDB_API_KEY MDBLIST_API_KEY HOME_ASSISTANT_TOKEN NEXTPVR_PIN \
      PLEX_TOKEN EMBY_PASSWORD 2>/dev/null
    coreelec_config_validate
  )
  rc=$?
  set -e
  assert_success "${rc}" "production config validates with only the required Kodi password present"
}

# Every primary add-on named in the task brief must be locked; none may be
# silently dropped or substituted.
test_production_config_locks_primary_addon_versions() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  assert_artifact_version "repository.emby.kodi" "1.0.8"
  assert_artifact_version "plugin.service.emby-next-gen" "11.1.27"
  assert_artifact_version "script.plexmod" "1.3.19"
  assert_artifact_version "skin.arctic.fuse.3" "3.2.16"
  assert_artifact_version "plugin.video.themoviedb.helper" "6.17.1"
  assert_artifact_version "weather.ha" "0.0.6.6"
  assert_artifact_version "resource.language.en_us" "11.0.82"
  # CoreELEC republishes upstream pvr.nextpvr 21.3.2-Omega for Amlogic-ng
  # arm with its own packaging revision appended (PKG_REV=1), so the
  # addon.xml on this platform declares 21.3.2.1. The Kodi Omega mirror
  # publishes no Linux/arm build at all.
  assert_artifact_version "pvr.nextpvr" "21.3.2.1"
}

test_production_config_uses_only_stable_emby_sources() {
  local body
  body="$(< "${PRODUCTION_CONFIG}")"
  assert_contains "${body}" \
    "https://embydata.com/downloads/addons/xbmb3c/multi-repo/release/v21_omega/" \
    "Emby artifacts come from the stable Omega release tree"
  assert_not_contains "${body}" "repository.beta.emby.kodi" \
    "the beta Emby repository is absent"
  assert_not_contains "${body}" "/multi-repo/beta/" \
    "the beta Emby artifact tree is absent"
}

test_production_config_locks_arctic_fuse_supported_optional_addons() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  assert_artifact_version "script.artistslideshow" "4.2.0"
  assert_artifact_version "resource.images.arctic.waves" "0.0.2"
  assert_artifact_version "resource.images.weatherfanart.multi" "0.0.6"
  assert_artifact_version "resource.images.moviecountryicons.maps" "0.0.1"
  assert_artifact_version "resource.images.studios.white" "0.0.34"
  assert_artifact_version "resource.uisounds.fromashes" "3.0.01"
  assert_artifact_version "script.module.defusedxml" "0.6.0+matrix.1"
  assert_artifact_version "script.module.future" "1.0.0+matrix.1"
}

test_production_config_matches_the_reviewed_artifact_id_set() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  local expected actual
  expected="$(reviewed_artifact_ids | LC_ALL=C sort)"
  actual="$(artifact_id_versions | cut -f1 | LC_ALL=C sort)"
  assert_eq "${expected}" "${actual}" "locked artifact ID set"
}

# The externally hosted add-ons are pinned to immutable publisher revisions,
# so the config must record which revision each one came from rather than
# pointing at a moving ref.
test_production_config_records_immutable_upstream_sources() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  local body record plexmod_url weather_url
  body="$(cat "${PRODUCTION_CONFIG}")"
  for record in ${ADDON_ARTIFACTS[@]+"${ADDON_ARTIFACTS[@]}"}; do
    case "${record}" in
      script.plexmod\|*) plexmod_url="$(cut -d'|' -f3 <<< "${record}")" ;;
      weather.ha\|*) weather_url="$(cut -d'|' -f3 <<< "${record}")" ;;
    esac
  done
  assert_contains "${plexmod_url:-}" \
    "https://raw.githubusercontent.com/pannal/dontpanickodi/${PLEXMOD_COMMIT}/omega/zips/script.plexmod/script.plexmod-1.3.19.zip" \
    "script.plexmod is pinned to its immutable stable repository package"
  assert_contains "${weather_url:-}" \
    "https://codeload.github.com/Eugeniusz-Gienek/kodi_weather_ha/zip/refs/tags/0.0.6.6" \
    "weather.ha is pinned to its upstream tag archive"
  assert_contains "${body}" "${PLEXMOD_COMMIT}" "the pinned plexmod commit SHA is recorded"
  assert_contains "${body}" "latest published stable PM4K release" \
    "the stable plexmod selection rationale is recorded"
}

test_production_config_records_each_artifact_exactly_once() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  local duplicates
  duplicates="$(artifact_id_versions | cut -f1 | LC_ALL=C sort | uniq -d)"
  assert_eq "" "${duplicates}" "no artifact ID appears twice"
  assert_eq "41" "${#ADDON_ARTIFACTS[@]}" "locked artifact count"
}

# An artifact URL must be immutably addressed so the pinned bytes cannot be
# replaced under the checksum: either the URL embeds the pinned version, or it
# is addressed by a full 40-character commit SHA.
artifact_url_is_immutably_addressed() {
  local url="$1" version="$2" tail
  case "${url}" in
    *"${version}"*) return 0 ;;
  esac
  tail="${url##*/}"
  if (( ${#tail} == 40 )); then
    case "${tail}" in
      *[!0-9a-f]*) ;;
      *) return 0 ;;
    esac
  fi
  return 1
}

test_production_config_artifact_records_are_well_formed() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  # shellcheck source=lib/coreelec-artifacts.sh
  source "${SCRIPT_DIR}/../lib/coreelec-artifacts.sh"
  local record
  for record in ${ADDON_ARTIFACTS[@]+"${ADDON_ARTIFACTS[@]}"}; do
    coreelec_artifact_parse "${record}" || return 1
    if ! artifact_url_is_immutably_addressed "${ARTIFACT_URL}" "${ARTIFACT_VERSION}"; then
      printf 'artifact URL is not immutably addressed: %s\n' "${ARTIFACT_URL}" >&2
      return 1
    fi
    if [[ "${ARTIFACT_SHA256}" != "$(tr 'A-Z' 'a-z' <<< "${ARTIFACT_SHA256}")" ]]; then
      printf 'artifact checksum is not lowercase: %s\n' "${ARTIFACT_ID}" >&2
      return 1
    fi
  done
}

# Every requested pin now resolves to a real, checksummable artifact, so no
# "BLOCKED" carve-out may survive in the shipped config.
test_production_config_has_no_blocked_pins() {
  local body ids
  body="$(cat "${PRODUCTION_CONFIG}")"
  assert_not_contains "${body}" "BLOCKED" "no pin is left unresolved"
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  ids="$(artifact_id_versions | cut -f1)"
  assert_contains "${ids}" "script.plexmod" "PM4K is locked, not absent"
  assert_contains "${ids}" "weather.ha" "Home Assistant Weather is locked, not absent"
}

# The device documentation mandates `CoreELEC-Amlogic-ng.arm-21.3-Omega-Generic`
# and explicitly forbids substituting `Amlogic-ne` or `aarch64`, and
# `validate_remote` refuses any device that does not identify as Amlogic-ng.
# CoreELEC publishes its binary add-ons per branch and architecture --
# Amlogic-ng carries `arm` only, Amlogic-ne carries `aarch64` -- so a binary
# add-on taken from the wrong tree installs and then fails to load on the
# device.
#
# This asserts each of the three binary add-ons by exact ID, rather than
# scanning ADDON_ARTIFACTS for whatever happens to be hosted on
# addons.coreelec.org: an earlier version of this test filtered records by
# `*addons.coreelec.org*` in the URL and skipped anything else, so if one of
# these three IDs were ever repinned to a different host (or dropped from the
# config entirely) the loop would silently `continue` past it -- the specific
# add-on the device depends on would go unchecked while the test still
# reported green. Requiring each ID to be present, and requiring its URL to
# start with the exact Amlogic-ng/arm prefix, fails loudly on both a missing
# add-on and a moved-host add-on.
test_production_config_takes_binary_addons_from_the_installed_branch() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  local expected_prefix="https://addons.coreelec.org/Amlogic-ng/${EXPECTED_RELEASE}/arm/"
  local required_ids=(pvr.nextpvr inputstream.adaptive inputstream.ffmpegdirect)
  local id record record_id url found
  for id in "${required_ids[@]}"; do
    found=0
    for record in ${ADDON_ARTIFACTS[@]+"${ADDON_ARTIFACTS[@]}"}; do
      record_id="$(cut -d'|' -f1 <<< "${record}")"
      [[ "${record_id}" == "${id}" ]] || continue
      found=1
      url="$(cut -d'|' -f3 <<< "${record}")"
      case "${url}" in
        "${expected_prefix}"*) ;;
        *)
          printf 'assert: %s must be sourced from %s* (got %s)\n' \
            "${id}" "${expected_prefix}" "${url}" >&2
          return 1
          ;;
      esac
    done
    if [[ "${found}" -ne 1 ]]; then
      printf 'assert: required binary add-on %s is missing from ADDON_ARTIFACTS\n' "${id}" >&2
      return 1
    fi
  done
}

test_room_config_parses_every_key() {
  local dir file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/room.conf"
  cat > "${file}" <<'CONF'
# theater
ROOM_DISPLAY_RESOLUTION=3840x2160p
ROOM_DISPLAY_WHITELIST=0409602160024.00000pstd,0384002160060.00000pstd
ROOM_DOLBY_VISION=1
ROOM_DOLBY_VISION_MODE=tv-led
ROOM_AUDIO_PASSTHROUGH=1
ROOM_AUDIO_AC3=1
ROOM_AUDIO_EAC3=1
ROOM_AUDIO_DTS=1
ROOM_AUDIO_TRUEHD=1
ROOM_AUDIO_DTSHD=0
CONF
  coreelec_room_config_defaults
  coreelec_room_config_load "${file}"
  coreelec_room_config_validate
  assert_eq "3840x2160p" "${ROOM_DISPLAY_RESOLUTION}" "resolution label"
  assert_eq "0409602160024.00000pstd,0384002160060.00000pstd" \
    "${ROOM_DISPLAY_WHITELIST}" "whitelist"
  assert_eq "tv-led" "${ROOM_DOLBY_VISION_MODE}" "dolby vision mode"
  assert_eq "0" "${ROOM_AUDIO_DTSHD}" "dts-hd passthrough"
}

test_room_config_missing_key_is_rejected() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/room.conf"
  cat > "${file}" <<'CONF'
ROOM_DISPLAY_RESOLUTION=3840x2160p
CONF
  coreelec_room_config_defaults
  coreelec_room_config_load "${file}"
  set +e
  output="$(coreelec_room_config_validate 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an incomplete room file must be rejected"
  assert_contains "${output}" "ROOM_DISPLAY_WHITELIST"
}

test_room_config_rejects_provision_keys_and_secrets() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/room.conf"
  printf 'KODI_PORT=8181\n' > "${file}"
  coreelec_room_config_defaults
  set +e
  output="$(coreelec_room_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a provision.conf key must not be accepted in room.conf"
  assert_contains "${output}" "unknown room configuration key: KODI_PORT"

  printf 'KODI_WEB_PASSWORD=hunter2\n' > "${file}"
  coreelec_room_config_defaults
  set +e
  output="$(coreelec_room_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a secret must not be accepted in room.conf"
  assert_contains "${output}" "is a secret"
  assert_not_contains "${output}" "hunter2"
}

test_room_config_rejects_room_keys_in_provision_conf() {
  local dir file rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/provision.conf"
  printf 'ROOM_DISPLAY_RESOLUTION=3840x2160p\n' > "${file}"
  coreelec_config_defaults
  set +e
  output="$(coreelec_config_load "${file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a room key must not be accepted in provision.conf"
  assert_contains "${output}" "unknown configuration key: ROOM_DISPLAY_RESOLUTION"
}

test_room_config_rejects_malformed_values() {
  local dir file rc output entry
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  file="${dir}/room.conf"
  for entry in \
    'ROOM_DISPLAY_RESOLUTION=3840*2160p' \
    'ROOM_DISPLAY_WHITELIST=not-a-mode' \
    'ROOM_DISPLAY_WHITELIST=0384002160060.00000pstd,' \
    'ROOM_DOLBY_VISION_MODE=player' \
    'ROOM_AUDIO_DTS=yes'; do
    printf '%s\n' "${entry}" > "${file}"
    coreelec_room_config_defaults
    set +e
    output="$(coreelec_room_config_load "${file}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "malformed entry must be rejected: ${entry}"
    assert_contains "${output}" "${entry%%=*}"
  done
}

test_room_name_rejects_path_traversal() {
  local name rc output
  for name in '.' '..' 'a/b' '' '-theater'; do
    set +e
    output="$(coreelec_validate_room_name "${name}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "room name must be rejected: '${name}'"
  done
  set +e
  coreelec_validate_room_name theater >/dev/null 2>&1
  rc=$?
  set -e
  assert_success "${rc}" "a plain room name is accepted"
}

test_shipped_theater_room_config_is_complete() {
  coreelec_room_config_defaults
  coreelec_room_config_load "${SCRIPT_DIR}/../config/rooms/theater/room.conf"
  coreelec_room_config_validate
  assert_eq "3840x2160p" "${ROOM_DISPLAY_RESOLUTION}" "theater resolution"
  assert_eq "tv-led" "${ROOM_DOLBY_VISION_MODE}" "theater dolby vision mode"
  assert_eq "1" "${ROOM_AUDIO_TRUEHD}" "theater truehd passthrough"
  assert_contains "${ROOM_DISPLAY_WHITELIST}" "0384002160060.00000pstd"
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
  test_kodi_password_in_config_is_rejected_as_a_secret \
  test_service_locations_in_config_are_rejected_as_secrets \
  test_removed_local_service_inputs_are_unknown \
  test_cli_value_overrides_config_value \
  test_target_is_not_loaded_from_shared_config \
  test_default_component_plan_is_full_baseline \
  test_legacy_addon_filter_preserves_default_baseline \
  test_explicit_cec_plan_is_isolated \
  test_skin_expands_dependencies_in_stable_order \
  test_services_expands_addons_dependency \
  test_explicit_addon_implies_addons_component \
  test_duplicate_component_requests_are_normalized \
  test_explicit_baseline_expands_full_plan \
  test_unknown_component_is_rejected \
  test_unimplemented_room_component_is_rejected \
  test_no_kodi_conflicts_with_explicit_components \
  test_empty_component_request_is_rejected \
  test_service_secret_without_endpoint_is_rejected \
  test_service_location_secrets_are_validated \
  test_missing_optional_secrets_are_allowed \
  test_kodi_baseline_requires_password_from_shared_environment \
  test_private_ipv4_validation_does_not_expand_pathnames \
  test_production_config_sets_pacific_english_us_baseline \
  test_production_config_carries_no_secret_values \
  test_production_config_locks_primary_addon_versions \
  test_production_config_uses_only_stable_emby_sources \
  test_production_config_locks_arctic_fuse_supported_optional_addons \
  test_production_config_matches_the_reviewed_artifact_id_set \
  test_production_config_records_immutable_upstream_sources \
  test_production_config_records_each_artifact_exactly_once \
  test_production_config_artifact_records_are_well_formed \
  test_production_config_has_no_blocked_pins \
  test_production_config_takes_binary_addons_from_the_installed_branch \
  test_room_config_parses_every_key \
  test_room_config_missing_key_is_rejected \
  test_room_config_rejects_provision_keys_and_secrets \
  test_room_config_rejects_room_keys_in_provision_conf \
  test_room_config_rejects_malformed_values \
  test_room_name_rejects_path_traversal \
  test_shipped_theater_room_config_is_complete
