#!/bin/bash

# Tests for remote baseline verification, add-on status classification, and
# the redacted audit report.
#
# Verification is authoritative on the device: the provisioner asks Kodi over
# localhost JSON-RPC and inspects configured add-on files with a remote Python
# probe that returns booleans and non-secret values only. These tests exercise
# that probe directly (with a stubbed `curl` serving fixture JSON-RPC
# responses) and exercise the Mac-side comparator, classifier, report
# renderer, redaction guard, and the verify -> finalize/rollback decision
# through provision-coreelec.sh's internal fixture entry points. No test
# contacts a device.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"

PROVISIONER="${SCRIPT_DIR}/../provision-coreelec.sh"

# --- Fixture helpers -------------------------------------------------------

file_mode() {
  python3 -c 'import os, sys; sys.stdout.write("%o" % (os.stat(sys.argv[1]).st_mode & 0o7777))' "$1"
}

# The non-secret regional baseline every run verifies against.
write_base_config() {
  cat > "$1" <<'CONFIG'
EXPECTED_RELEASE=21.3
KODI_PORT=8080
KODI_USER=homeassistant
TIMEZONE=America/Los_Angeles
TIMEZONE_COUNTRY=United States
LOCALE_LANGUAGE=resource.language.en_us
LOCALE_COUNTRY=USA (12h)
KEYBOARD_LAYOUT=English QWERTY
ADDON_UPDATE_MODE=notify
CONFIG
}

# The same baseline plus every optional integration's non-secret half. The
# secret half arrives from the environment, exactly as in production.
write_configured_config() {
  write_base_config "$1"
  cat >> "$1" <<'CONFIG'
HOME_ASSISTANT_URL=https://homeassistant.example.lan:8123
HOME_ASSISTANT_WEATHER_ENTITY=weather.forecast_home
HOME_ASSISTANT_SUN_ENTITY=sun.sun
NEXTPVR_HOST=nextpvr.example.lan
NEXTPVR_PORT=8866
NEXTPVR_PROTOCOL=http
NEXTPVR_INSTANCE_NAME=Living Room NextPVR
PLEX_SERVER_HOST=plex.example.lan
PLEX_SERVER_PORT=32400
PLEX_SERVER_NAME=Basement Plex
PLEX_PROFILE_IDS=11,22
CONFIG
}

# The deployment manifest the provisioner resolves before uploading: index,
# add-on ID, pinned version, uploaded archive name.
write_manifest() {
  cat > "$1" <<'MANIFEST'
1	skin.arctic.fuse.3	3.2.16	1.zip
2	weather.ha	0.0.6.6	2.zip
3	pvr.nextpvr	21.3.2.1	3.zip
4	script.plexmod	1.14.1-beta1	4.zip
5	plugin.video.youtube	7.4.4	5.zip
6	plugin.service.emby-next-gen	12.4.23	6.zip
7	plugin.video.themoviedb.helper	6.17.1	7.zip
8	resource.language.en_us	11.0.82	8.zip
MANIFEST
}

# What the remote probe reports when the device matches the request exactly.
write_pass_observations() {
  cat > "$1" <<'OBSERVATIONS'
observation_format=coreelec-verification-1
jsonrpc_version=13.3.0
setting.locale.language=resource.language.en_us
setting.locale.country=USA (12h)
setting.locale.keyboardlayouts=English QWERTY
setting.locale.timezonecountry=United States
setting.locale.timezone=America/Los_Angeles
setting.lookandfeel.skin=skin.arctic.fuse.3
setting.weather.addon=weather.ha
timezone_cache=America/Los_Angeles
localtime_path=/usr/share/zoneinfo/America/Los_Angeles
localtime_kind=symlink
localtime_zoneinfo_match=1
date_offset_expected=PDT-0700
date_offset_observed=PDT-0700
date_matches_timezone=1
addon.skin.arctic.fuse.3.installed=1
addon.skin.arctic.fuse.3.version=3.2.16
addon.skin.arctic.fuse.3.enabled=1
addon.skin.arctic.fuse.3.enable_attempted=0
addon.weather.ha.installed=1
addon.weather.ha.version=0.0.6.6
addon.weather.ha.enabled=1
addon.weather.ha.enable_attempted=0
addon.pvr.nextpvr.installed=1
addon.pvr.nextpvr.version=21.3.2.1
addon.pvr.nextpvr.enabled=1
addon.pvr.nextpvr.enable_attempted=0
addon.script.plexmod.installed=1
addon.script.plexmod.version=1.14.1-beta1
addon.script.plexmod.enabled=1
addon.script.plexmod.enable_attempted=0
addon.plugin.video.youtube.installed=1
addon.plugin.video.youtube.version=7.4.4
addon.plugin.video.youtube.enabled=1
addon.plugin.video.youtube.enable_attempted=0
addon.plugin.service.emby-next-gen.installed=1
addon.plugin.service.emby-next-gen.version=12.4.23
addon.plugin.service.emby-next-gen.enabled=1
addon.plugin.service.emby-next-gen.enable_attempted=0
addon.plugin.video.themoviedb.helper.installed=1
addon.plugin.video.themoviedb.helper.version=6.17.1
addon.plugin.video.themoviedb.helper.enabled=1
addon.plugin.video.themoviedb.helper.enable_attempted=0
addon.resource.language.en_us.installed=1
addon.resource.language.en_us.version=11.0.82
addon.resource.language.en_us.enabled=1
addon.resource.language.en_us.enable_attempted=0
addon_settings.weather.ha.configured=1
addon_settings.pvr.nextpvr.configured=1
addon_settings.script.plexmod.configured=1
OBSERVATIONS
}

# Rewrites one observation line in place, so each test states exactly the one
# device fact it changes.
set_observation() {
  local file="$1" key="$2" value="$3"
  local temporary="${file}.edit"
  awk -v key="${key}" -v value="${value}" -F= '
    {
      if (index($0, key "=") == 1) { print key "=" value; found = 1 }
      else { print }
    }
    END { if (!found) print key "=" value }
  ' "${file}" > "${temporary}"
  mv "${temporary}" "${file}"
}

# Runs the Mac-side comparator over a fixture observation set.
run_verify() {
  local config="$1" observations="$2" manifest="$3"
  bash "${PROVISIONER}" --config "${config}" \
    --verify-fixture "${observations}" "${manifest}"
}

run_classify() {
  local config="$1" addon_id="$2"
  bash "${PROVISIONER}" --config "${config}" --classify-addon "${addon_id}"
}

# Renders a full report through the production writer, minus the remote
# inventory block that needs a device.
run_report() {
  local config="$1" directory="$2" observations="$3" manifest="$4"
  local reachable="${5:-unknown}"
  bash "${PROVISIONER}" --config "${config}" \
    --report-fixture "${directory}" "${observations}" "${manifest}" "${reachable}"
}

# Runs the real verify -> finalize/rollback decision with the three remote
# calls replaced by recording stubs whose exit status the test chooses.
run_conclude() {
  local config="$1" observations="$2" manifest="$3"
  local finalize_status="$4" rollback_status="$5" log="$6"
  bash "${PROVISIONER}" --config "${config}" \
    --conclude-fixture "${observations}" "${manifest}" \
    "${finalize_status}" "${rollback_status}" "${log}"
}

report_line() {
  local file="$1" key="$2"
  awk -v key="${key}" 'index($0, key "=") == 1 { print substr($0, length(key) + 2) }' "${file}"
}

# --- Regional and add-on verification --------------------------------------

test_all_expected_addon_versions_are_verified() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  set +e
  output="$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=1234 PLEX_TOKEN=plex-token \
    run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a matching device must verify" || return 1
  assert_contains "${output}" "verification_result=pass" "result line present" || return 1
  assert_contains "${output}" "addon.plugin.video.youtube.requested_version=7.4.4" \
    "requested version is reported" || return 1
  assert_contains "${output}" "addon.plugin.video.youtube.observed_version=7.4.4" \
    "observed version is reported" || return 1
  assert_contains "${output}" "addon.script.plexmod.observed_version=1.14.1-beta1" \
    "pre-release version round-trips" || return 1
  assert_eq "8" "$(printf '%s\n' "${output}" | grep -c '\.verification=ok$')" \
    "every manifest add-on is verified" || return 1
}

test_disabled_addon_is_failure() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "addon.plugin.video.youtube.enabled" "0"

  set +e
  output="$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=1234 PLEX_TOKEN=plex-token \
    run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an installed-but-disabled add-on must fail verification" || return 1
  assert_contains "${output}" "addon.plugin.video.youtube.enabled=0" \
    "the disabled state is reported" || return 1
  assert_contains "${output}" "addon.plugin.video.youtube.verification=mismatch" \
    "the add-on is marked mismatched" || return 1
  assert_contains "${output}" "verification_result=fail" "overall result fails" || return 1
}

test_missing_addon_is_failure() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "addon.pvr.nextpvr.installed" "0"

  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an absent add-on must fail verification" || return 1
  assert_contains "${output}" "addon.pvr.nextpvr.verification=mismatch" \
    "the missing add-on is marked mismatched" || return 1
}

test_addon_version_mismatch_is_failure() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "addon.skin.arctic.fuse.3.version" "3.2.15"

  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a version other than the pinned one must fail" || return 1
  assert_contains "${output}" "addon.skin.arctic.fuse.3.observed_version=3.2.15" \
    "the observed version is reported" || return 1
  assert_contains "${output}" "addon.skin.arctic.fuse.3.verification=mismatch" \
    "the add-on is marked mismatched" || return 1
}

test_active_skin_is_verified() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the activated skin verifies" || return 1
  assert_contains "${output}" "skin.expected=skin.arctic.fuse.3" "expected skin reported" || return 1
  assert_contains "${output}" "skin.observed=skin.arctic.fuse.3" "observed skin reported" || return 1
  assert_contains "${output}" "skin.status=ok" "skin status reported" || return 1

  set_observation "${observations}" "setting.lookandfeel.skin" "skin.estuary"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an inactive pinned skin must fail verification" || return 1
  assert_contains "${output}" "skin.observed=skin.estuary" "the live skin is reported" || return 1
  assert_contains "${output}" "skin.status=mismatch" "skin mismatch is reported" || return 1
}

test_weather_provider_is_verified_only_when_configured() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "setting.weather.addon" "weather.metoffice"

  set +e
  output="$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=1234 PLEX_TOKEN=plex-token \
    run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a configured weather provider that is not active must fail" || return 1
  assert_contains "${output}" "weather_provider.status=mismatch" "mismatch reported" || return 1

  # Same device state, but Home Assistant Weather was never configured: the
  # existing provider is left alone and must not fail the run.
  write_base_config "${config}"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "an unconfigured weather provider must not fail" || return 1
  assert_contains "${output}" "weather_provider.status=not-configured" \
    "the unconfigured state is explicit" || return 1
}

test_timezone_cache_and_zoneinfo_are_verified() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "matching timezone state verifies" || return 1
  assert_contains "${output}" "regional.timezone_cache.observed=America/Los_Angeles" \
    "the CoreELEC timezone cache is reported" || return 1
  assert_contains "${output}" "regional.localtime.status=ok" \
    "/etc/localtime is verified" || return 1
  assert_contains "${output}" "regional.date_offset.status=ok" \
    "device local time is verified" || return 1

  set_observation "${observations}" "timezone_cache" "UTC"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a stale timezone cache must fail" || return 1
  assert_contains "${output}" "regional.timezone_cache.status=mismatch" "cache mismatch reported" || return 1

  write_pass_observations "${observations}"
  set_observation "${observations}" "localtime_path" "/usr/share/zoneinfo/UTC"
  # Neither the path nor the file's content is the requested zone.
  set_observation "${observations}" "localtime_zoneinfo_match" "0"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "zoneinfo pointing elsewhere must fail" || return 1
  assert_contains "${output}" "regional.localtime.status=mismatch" "zoneinfo mismatch reported" || return 1

  write_pass_observations "${observations}"
  set_observation "${observations}" "date_matches_timezone" "0"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "local time not matching the zone must fail" || return 1
  assert_contains "${output}" "regional.date_offset.status=mismatch" "offset mismatch reported" || return 1
}

# CoreELEC images ship /etc/localtime either as a symlink into the zoneinfo
# tree or as a plain copy of the zone file. A copy resolves to /etc/localtime
# and can never match the requested zone by path, so the device also reports
# whether the file's bytes are the requested zone's.
test_regular_file_localtime_is_verified_by_content() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"

  write_pass_observations "${observations}"
  set_observation "${observations}" "localtime_path" "/etc/localtime"
  set_observation "${observations}" "localtime_kind" "file"
  set_observation "${observations}" "localtime_zoneinfo_match" "1"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a zone file copied to /etc/localtime must verify" || return 1
  assert_contains "${output}" "regional.localtime.observed=/etc/localtime" \
    "the observed layout is reported as it is" || return 1
  assert_contains "${output}" "regional.localtime.match=zoneinfo-copy" \
    "the accepted evidence is named" || return 1
  assert_contains "${output}" "regional.localtime.status=ok" \
    "a byte-equal copy is accepted" || return 1

  # A copy of some other zone is still a real mismatch.
  set_observation "${observations}" "localtime_zoneinfo_match" "0"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a copy of another zone must fail" || return 1
  assert_contains "${output}" "regional.localtime.match=none" "no evidence is claimed" || return 1
  assert_contains "${output}" "regional.localtime.status=mismatch" "the mismatch is reported" || return 1

  # Unproven is not proven: a device that cannot answer the content question
  # while its path does not match the zone stays a failure.
  set_observation "${observations}" "localtime_zoneinfo_match" "unavailable"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "unproven localtime content must fail" || return 1
  assert_contains "${output}" "regional.localtime.status=mismatch" "the mismatch is reported" || return 1

  # A symlink into the zoneinfo tree is still accepted on its own.
  write_pass_observations "${observations}"
  set_observation "${observations}" "localtime_zoneinfo_match" "0"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a symlink to the requested zone must verify" || return 1
  assert_contains "${output}" "regional.localtime.match=symlink" "the symlink evidence is named" || return 1
}

# `date +%Z%z` is a BusyBox capability question, not applied state. Anything
# other than a well-formed comparison is advisory, so an unexpanded or
# unexpected answer can never roll back a device whose timezone cache,
# zoneinfo, and Kodi settings all verified.
test_unexpected_device_date_output_is_advisory_not_fatal() {
  local dir config manifest observations output rc value
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"

  for value in "%Z%z" "" "unavailable" "PDT-0700"; do
    write_pass_observations "${observations}"
    set_observation "${observations}" "date_matches_timezone" "${value}"
    set +e
    output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
    rc=$?
    set -e
    assert_success "${rc}" "an unexpected date answer (${value}) must not fail the run" || return 1
    assert_contains "${output}" "regional.date_offset.status=unavailable" \
      "an unexpected date answer (${value}) is recorded as unavailable" || return 1
    assert_not_contains "${output}" "regional.date_offset.status=mismatch" \
      "an unexpected date answer (${value}) is never a mismatch" || return 1
  done
}

# The date-offset comparison is reported as the same expected/observed/status
# triple as every other regional value, so the report says what was wanted and
# what the device actually printed.
test_date_offset_reports_expected_and_observed_marks() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "date_offset_expected" "PST-0800"
  set_observation "${observations}" "date_offset_observed" "PST-0800"

  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "matching marks verify" || return 1
  assert_contains "${output}" "regional.date_offset.expected=PST-0800" \
    "the expected zone marks are reported" || return 1
  assert_contains "${output}" "regional.date_offset.observed=PST-0800" \
    "the observed zone marks are reported" || return 1
  assert_contains "${output}" "regional.date_offset.status=ok" "the status is reported" || return 1

  # A device that could not answer still gets an explicit triple.
  write_pass_observations "${observations}"
  set_observation "${observations}" "date_offset_expected" ""
  set_observation "${observations}" "date_offset_observed" ""
  set_observation "${observations}" "date_matches_timezone" "unavailable"
  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "an unavailable date answer must not fail the run" || return 1
  assert_contains "${output}" "regional.date_offset.expected=unavailable" \
    "the missing expectation is explicit" || return 1
  assert_contains "${output}" "regional.date_offset.observed=unavailable" \
    "the missing observation is explicit" || return 1
}

# The comparator is reachable with material it cannot read; it must report a
# failure and return, because its caller is the code that rolls the deployment
# back. Exiting the process here would leave the transaction pending.
test_unreadable_verification_material_fails_without_exiting() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  set +e
  output="$(run_verify "${config}" "${dir}/absent-observations.conf" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "missing observations must fail verification" || return 1
  assert_contains "${output}" "verification_result=fail" "the failure is a verification verdict" || return 1
  assert_contains "${output}" "verification_error=" "the reason is recorded" || return 1

  set +e
  output="$(run_verify "${config}" "${observations}" "${dir}/absent-manifest.tsv" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a missing manifest must fail verification" || return 1
  assert_contains "${output}" "verification_result=fail" "the failure is a verification verdict" || return 1
}

# The same condition, through the real decision path: an unreadable manifest
# must roll the deployment back rather than abort the process and leave it
# half-committed.
test_unreadable_manifest_rolls_back_the_deployment() {
  local dir config observations log output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  observations="${dir}/observations.conf"
  log="${dir}/remote-calls.log"
  write_base_config "${config}"
  write_pass_observations "${observations}"

  set +e
  output="$(run_conclude "${config}" "${observations}" "${dir}/absent-manifest.tsv" 0 0 "${log}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an unreadable manifest must not be treated as success" || return 1
  assert_contains "${output}" "verification_result=fail" "verification failed" || return 1
  assert_contains "${output}" "deployment_state=rolled-back" "the deployment was rolled back" || return 1
  assert_contains "$(cat "${log}")" "rollback" "the rollback actually ran" || return 1
}

test_english_us_values_are_verified() {
  local dir config manifest observations output rc key
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the English/US baseline verifies" || return 1
  assert_contains "${output}" "regional.locale.language.expected=resource.language.en_us" \
    "expected language reported" || return 1
  assert_contains "${output}" "regional.locale.country.observed=USA (12h)" \
    "observed country reported" || return 1
  assert_contains "${output}" "regional.locale.keyboardlayouts.status=ok" \
    "keyboard layout verified" || return 1
  assert_contains "${output}" "regional.locale.timezonecountry.expected=United States" \
    "canonical timezone country reported" || return 1

  for key in locale.language locale.country locale.keyboardlayouts locale.timezonecountry; do
    write_pass_observations "${observations}"
    set_observation "${observations}" "setting.${key}" "something-else"
    set +e
    output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "a wrong ${key} must fail verification" || return 1
    assert_contains "${output}" "regional.${key}.status=mismatch" \
      "${key} mismatch reported" || return 1
  done
}

test_selected_subset_verifies_only_the_selected_addons() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_pass_observations "${observations}"
  # A run narrowed with --addon deploys, and therefore verifies, only these.
  cat > "${manifest}" <<'MANIFEST'
1	skin.arctic.fuse.3	3.2.16	1.zip
2	resource.language.en_us	11.0.82	2.zip
MANIFEST
  # An add-on outside the selection is disabled on the device; that is not
  # this run's deployment set and must not fail it.
  set_observation "${observations}" "addon.plugin.video.youtube.enabled" "0"

  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "only the selected deployment set is verified" || return 1
  assert_contains "${output}" "addon.skin.arctic.fuse.3.verification=ok" \
    "selected add-on verified" || return 1
  assert_not_contains "${output}" "addon.plugin.video.youtube.verification" \
    "an unselected add-on is not verified" || return 1
}

# --- Add-on status classification -------------------------------------------

test_emby_and_youtube_are_classified_manual() {
  local dir config
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  write_configured_config "${config}"

  assert_eq "installed-manual" \
    "$(run_classify "${config}" plugin.service.emby-next-gen)" \
    "Emby always needs interactive server/user login" || return 1
  # Personal OAuth keys still leave Google device authorization interactive.
  assert_eq "installed-manual" \
    "$(YOUTUBE_API_KEY=k YOUTUBE_CLIENT_ID=i YOUTUBE_CLIENT_SECRET=s \
       run_classify "${config}" plugin.video.youtube)" \
    "YouTube always needs device authorization" || return 1
}

test_configured_nextpvr_ha_and_pm4k_are_classified_configured() {
  local dir config
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  write_configured_config "${config}"

  assert_eq "configured" \
    "$(NEXTPVR_PIN=1234 run_classify "${config}" pvr.nextpvr)" \
    "NextPVR with host and PIN is configured" || return 1
  assert_eq "configured" \
    "$(HOME_ASSISTANT_TOKEN=ha-token run_classify "${config}" weather.ha)" \
    "Home Assistant Weather with URL, entity and token is configured" || return 1
  assert_eq "configured" \
    "$(PLEX_TOKEN=plex-token run_classify "${config}" script.plexmod)" \
    "PM4K local mode with host and token is configured" || return 1
  assert_eq "configured" \
    "$(OMDB_API_KEY=omdb run_classify "${config}" plugin.video.themoviedb.helper)" \
    "TMDb Helper with a metadata key is configured" || return 1
}

test_missing_optional_values_are_classified_unconfigured() {
  local dir config addon_id
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"

  # No secrets and no service settings at all.
  write_base_config "${config}"
  for addon_id in pvr.nextpvr weather.ha script.plexmod plugin.video.themoviedb.helper; do
    assert_eq "installed-unconfigured" "$(run_classify "${config}" "${addon_id}")" \
      "${addon_id} without configuration is unconfigured" || return 1
  done

  # Non-secret halves present, secret halves missing: still unconfigured.
  write_configured_config "${config}"
  for addon_id in pvr.nextpvr weather.ha script.plexmod; do
    assert_eq "installed-unconfigured" "$(run_classify "${config}" "${addon_id}")" \
      "${addon_id} without its secret is unconfigured" || return 1
  done
}

# --- Report content, fingerprint, and redaction -----------------------------

test_report_lists_secret_presence_without_secret_values() {
  local dir config manifest observations report
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  report="$(HOME_ASSISTANT_TOKEN=ha-token-value NEXTPVR_PIN=pin-value \
    PLEX_TOKEN=plex-token-value \
    run_report "${config}" "${dir}/out" "${observations}" "${manifest}")"
  [[ -f "${report}" ]] || {
    printf 'no report was written\n' >&2
    return 1
  }
  assert_eq "1" "$(report_line "${report}" secret_present.HOME_ASSISTANT_TOKEN)" \
    "a supplied secret is reported present" || return 1
  assert_eq "1" "$(report_line "${report}" secret_present.NEXTPVR_PIN)" \
    "NextPVR PIN presence reported" || return 1
  assert_eq "0" "$(report_line "${report}" secret_present.OMDB_API_KEY)" \
    "an absent secret is reported absent" || return 1
  assert_eq "0" "$(report_line "${report}" secret_present.YOUTUBE_API_KEY)" \
    "absent YouTube credentials reported absent" || return 1
  assert_not_contains "$(cat "${report}")" "ha-token-value" "no token literal" || return 1
  assert_not_contains "$(cat "${report}")" "pin-value" "no PIN literal" || return 1
  assert_not_contains "$(cat "${report}")" "plex-token-value" "no Plex token literal" || return 1
  assert_eq "600" "$(file_mode "${report}")" "the report is private" || return 1
}

test_report_redacts_all_supplied_secret_values() {
  local dir config manifest observations output rc remaining
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  # A secret whose literal value is also a non-secret value the report prints.
  # The guard must catch the occurrence rather than trust the renderer.
  set +e
  output="$(HOME_ASSISTANT_TOKEN=America/Los_Angeles \
    run_report "${config}" "${dir}/out" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a report containing a secret literal must fail" || return 1
  assert_contains "${output}" "HOME_ASSISTANT_TOKEN" "the offending secret is named" || return 1
  assert_not_contains "${output}" "America/Los_Angeles" \
    "the failure message must not echo the secret" || return 1
  remaining="$(find "${dir}/out" -type f -name '*.txt' 2>/dev/null | wc -l | tr -d ' ')"
  assert_eq "0" "${remaining}" "the offending report is deleted" || return 1
}

test_report_records_config_fingerprint_without_secrets() {
  local dir config manifest observations first second third fourth
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  first="$(report_line \
    "$(run_report "${config}" "${dir}/a" "${observations}" "${manifest}")" \
    config_fingerprint)"
  second="$(report_line \
    "$(run_report "${config}" "${dir}/b" "${observations}" "${manifest}")" \
    config_fingerprint)"
  assert_eq "${first}" "${second}" "the fingerprint is stable" || return 1
  case "${first}" in
    sha256:*) ;;
    *)
      printf 'fingerprint is not a labelled digest: %s\n' "${first}" >&2
      return 1
      ;;
  esac

  # Supplying secrets must not move the fingerprint: it covers configuration.
  third="$(report_line \
    "$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=nextpvr-pin-value PLEX_TOKEN=plex-token-value \
       run_report "${config}" "${dir}/c" "${observations}" "${manifest}")" \
    config_fingerprint)"
  assert_eq "${first}" "${third}" "secrets are excluded from the fingerprint" || return 1

  printf 'TIMEZONE=America/New_York\n' >> "${config}"
  # TIMEZONE is already set above, so replace rather than duplicate it.
  grep -v '^TIMEZONE=America/Los_Angeles$' "${config}" > "${config}.new"
  mv "${config}.new" "${config}"
  set_observation "${observations}" "timezone_cache" "America/New_York"
  set_observation "${observations}" "localtime_path" "/usr/share/zoneinfo/America/New_York"
  set_observation "${observations}" "setting.locale.timezone" "America/New_York"
  fourth="$(report_line \
    "$(run_report "${config}" "${dir}/d" "${observations}" "${manifest}")" \
    config_fingerprint)"
  if [[ "${first}" == "${fourth}" ]]; then
    printf 'the fingerprint ignored a changed configuration value\n' >&2
    return 1
  fi
}

test_report_lists_manual_actions_in_order() {
  local dir config manifest observations report actions
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  report="$(run_report "${config}" "${dir}/out" "${observations}" "${manifest}")"
  actions="$(grep '^manual_action\.' "${report}")"
  assert_contains "${actions}" "manual_action.1=Emby" "Emby login is first" || return 1
  assert_contains "${actions}" "manual_action.2=YouTube" "YouTube authorization is second" || return 1
  assert_contains "${actions}" "manual_action.3=Plex" "Plex linking is listed" || return 1
  assert_contains "${actions}" "manual_action.4=NextPVR" "NextPVR setup is listed" || return 1
  assert_contains "${actions}" "manual_action.5=Home Assistant Weather" \
    "Home Assistant Weather setup is listed" || return 1
  assert_contains "${actions}" "manual_action.6=Optional" \
    "optional Trakt/TMDb authorization is listed" || return 1

  # Configured integrations drop out; the always-manual ones remain.
  write_configured_config "${config}"
  report="$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=nextpvr-pin-value PLEX_TOKEN=plex-token-value \
    run_report "${config}" "${dir}/out2" "${observations}" "${manifest}")"
  actions="$(grep '^manual_action\.' "${report}")"
  assert_contains "${actions}" "manual_action.1=Emby" "Emby stays manual" || return 1
  assert_contains "${actions}" "manual_action.2=YouTube" "YouTube stays manual" || return 1
  assert_not_contains "${actions}" "=Plex" "configured PM4K needs no manual Plex step" || return 1
  assert_not_contains "${actions}" "=NextPVR" "configured NextPVR needs no manual step" || return 1
  assert_not_contains "${actions}" "=Home Assistant Weather" \
    "configured weather needs no manual step" || return 1
  assert_contains "${actions}" "manual_action.3=Optional" \
    "manual action numbering stays contiguous" || return 1
}

test_report_states_addon_status_and_verification_per_addon() {
  local dir config manifest observations report
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  report="$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=nextpvr-pin-value PLEX_TOKEN=plex-token-value \
    run_report "${config}" "${dir}/out" "${observations}" "${manifest}")"
  assert_eq "installed-manual" \
    "$(report_line "${report}" addon.plugin.service.emby-next-gen.status)" \
    "Emby status in the report" || return 1
  assert_eq "configured" "$(report_line "${report}" addon.weather.ha.status)" \
    "weather.ha status in the report" || return 1
  assert_eq "installed-unconfigured" \
    "$(report_line "${report}" addon.plugin.video.themoviedb.helper.status)" \
    "TMDb Helper without metadata keys" || return 1
  assert_eq "pass" "$(report_line "${report}" verification_result)" \
    "verification result in the report" || return 1
  assert_eq "committed" "$(report_line "${report}" deployment_state)" \
    "deployment state in the report" || return 1
  assert_eq "all-locked-artifacts" "$(report_line "${report}" addon_selection)" \
    "the selection scope is explicit" || return 1
}

test_report_keeps_subset_dependency_warning_explicit() {
  local dir config manifest observations report
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_pass_observations "${observations}"
  cat > "${manifest}" <<'MANIFEST'
1	skin.arctic.fuse.3	3.2.16	1.zip
2	resource.language.en_us	11.0.82	2.zip
MANIFEST

  report="$(bash "${PROVISIONER}" --config "${config}" \
    --addon skin.arctic.fuse.3 --addon resource.language.en_us \
    --report-fixture "${dir}/out" "${observations}" "${manifest}" unknown)"
  assert_eq "subset" "$(report_line "${report}" addon_selection)" \
    "a narrowed selection is reported as a subset" || return 1
  assert_eq "manual" "$(report_line "${report}" addon_dependency_resolution)" \
    "the dependency warning stays explicit" || return 1
  assert_eq "2" "$(grep -c '^addon\..*\.status=' "${report}")" \
    "only the selected add-ons are reported" || return 1
}

test_report_is_strict_key_value() {
  local dir config manifest observations report offenders
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  report="$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=nextpvr-pin-value PLEX_TOKEN=plex-token-value \
    run_report "${config}" "${dir}/out" "${observations}" "${manifest}")"
  offenders="$(grep -vc '^[A-Za-z0-9_.-]\{1,\}=' "${report}" || true)"
  assert_eq "0" "${offenders}" "every report line is key=value" || return 1
}

test_local_jsonrpc_unreachability_is_environmental_only() {
  local dir config manifest observations report
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  report="$(run_report "${config}" "${dir}/out" "${observations}" "${manifest}" 0)"
  assert_eq "0" "$(report_line "${report}" kodi_jsonrpc_reachable_from_mac)" \
    "the Mac-side probe result is recorded" || return 1
  assert_eq "pass" "$(report_line "${report}" verification_result)" \
    "device verification stays authoritative" || return 1
  assert_eq "device-localhost-jsonrpc" "$(report_line "${report}" verification_source)" \
    "the authoritative source is named" || return 1
}

# Every run writes the audit report, and its configuration fingerprint is a
# `shasum` call, so a Mac without it must be refused before the device is
# touched -- including the run that applies no Kodi baseline at all.
test_report_fingerprint_tool_is_required_even_without_kodi() {
  local dir config bin_dir tool resolved output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  write_base_config "${config}"
  bin_dir="${dir}/bin"
  mkdir -p "${bin_dir}"
  for tool in bash sh ssh ssh-keygen ssh-add openssl curl security grep sed tr awk \
    date uname mktemp dirname basename cat chmod mkdir rm cp mv ln sleep head tail \
    sort wc id stat python3 xmllint unzip tar; do
    resolved="$(command -v "${tool}" 2>/dev/null || true)"
    if [[ -n "${resolved}" && -x "${resolved}" ]]; then
      ln -sf "${resolved}" "${bin_dir}/${tool}"
    fi
  done

  set +e
  output="$(PATH="${bin_dir}" /bin/bash "${PROVISIONER}" --config "${config}" \
    --target 192.0.2.1 --no-kodi --report-dir "${dir}/reports" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a run that cannot fingerprint its configuration must be refused" || return 1
  assert_contains "${output}" "shasum" "the missing tool is named" || return 1
}

# --- Verification outcome: finalize, rollback, fatality ---------------------

test_verification_success_finalizes_and_commits() {
  local dir config manifest observations log output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  log="${dir}/remote-calls.log"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  set +e
  output="$(run_conclude "${config}" "${observations}" "${manifest}" 0 0 "${log}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a verified deployment succeeds" || return 1
  assert_contains "${output}" "deployment_state=committed" "the transaction is committed" || return 1
  assert_contains "${output}" "verification_result=pass" "verification passed" || return 1
  assert_contains "$(cat "${log}")" "finalize" "finalize was invoked" || return 1
  assert_not_contains "$(cat "${log}")" "rollback" "rollback was not invoked" || return 1
  # Verification must precede the commit, or a bad deployment is unrecoverable.
  assert_eq "verify" "$(head -n 1 "${log}")" "verification ran before finalize" || return 1
}

test_verification_mismatch_is_fatal() {
  local dir config manifest observations log output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  log="${dir}/remote-calls.log"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "addon.weather.ha.enabled" "0"

  set +e
  output="$(run_conclude "${config}" "${observations}" "${manifest}" 0 0 "${log}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a verification mismatch must be fatal" || return 1
  assert_contains "${output}" "verification_result=fail" "the failure is reported" || return 1
  assert_contains "${output}" "deployment_state=rolled-back" "the transaction is undone" || return 1
  assert_contains "$(cat "${log}")" "rollback" "rollback was invoked" || return 1
  assert_not_contains "$(cat "${log}")" "finalize" "a failed run must not commit" || return 1
}

test_incomplete_rollback_is_fatal_with_recovery_path() {
  local dir config manifest observations log output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  log="${dir}/remote-calls.log"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "setting.lookandfeel.skin" "skin.estuary"

  set +e
  output="$(run_conclude "${config}" "${observations}" "${manifest}" 0 1 "${log}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an incomplete rollback must be fatal" || return 1
  assert_contains "${output}" "deployment_state=incomplete-rollback" \
    "the incomplete rollback is named" || return 1
  assert_contains "${output}" "--rollback-deployment" \
    "the exact manual recovery command is given" || return 1
  assert_contains "${output}" "/storage/.cache/coreelec-provision/current-transaction" \
    "the retained pointer is named" || return 1
  assert_not_contains "$(cat "${log}")" "finalize" "a failed rollback must not commit" || return 1
}

# A device that cannot answer the probe is unverified, and an unverified
# deployment must be undone rather than left in place.
test_an_unanswered_probe_is_a_verification_failure() {
  local dir config manifest log output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  log="${dir}/remote-calls.log"
  write_base_config "${config}"
  write_manifest "${manifest}"

  set +e
  output="$(run_conclude "${config}" "${dir}/no-such-observations.conf" \
    "${manifest}" 0 0 "${log}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an unanswered probe must be fatal" || return 1
  assert_contains "${output}" "verification_result=fail" \
    "an unobservable device does not verify" || return 1
  assert_contains "${output}" "deployment_state=rolled-back" \
    "the transaction is undone" || return 1
  assert_not_contains "$(cat "${log}")" "finalize" \
    "an unverified deployment must not commit" || return 1
}

test_failed_finalize_is_fatal() {
  local dir config manifest observations log output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  log="${dir}/remote-calls.log"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  set +e
  output="$(run_conclude "${config}" "${observations}" "${manifest}" 1 0 "${log}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a finalize that fails must not be reported as committed" || return 1
  assert_contains "${output}" "deployment_state=pending-verification" \
    "the transaction stays pending for the operator" || return 1
}

# --- Remote localhost JSON-RPC probe ---------------------------------------

# Serves fixture JSON-RPC responses in place of the device's curl, records
# every request body, and honors a per-call response sequence so an
# enable-then-requery round trip can be observed.
install_jsonrpc_curl_stub() {
  local dir="$1" bin_dir="$1/stub-bin"
  mkdir -p "${bin_dir}"
  cat > "${bin_dir}/curl" <<'STUB'
#!/bin/bash
set -u
config=""
body_file="${JSONRPC_STUB_DIR}/request-$(date +%s%N 2>/dev/null || date +%s).json"
while (( $# > 0 )); do
  case "$1" in
    --config)
      config="$2"
      shift 2
      ;;
    *) shift ;;
  esac
done
count_file="${JSONRPC_STUB_DIR}/call-count"
count=0
[[ -f "${count_file}" ]] && count="$(cat "${count_file}")"
count=$((count + 1))
printf '%s\n' "${count}" > "${count_file}"
cat > "${JSONRPC_STUB_DIR}/request-${count}.json"
if [[ -n "${config}" ]]; then
  printf '%s\n' "${config}" > "${JSONRPC_STUB_DIR}/curl-config-path"
  python3 -c 'import os, sys; sys.stdout.write("%o\n" % (os.stat(sys.argv[1]).st_mode & 0o7777))' \
    "${config}" > "${JSONRPC_STUB_DIR}/curl-config-mode"
  cp "${config}" "${JSONRPC_STUB_DIR}/curl-config-copy"
fi
response="${JSONRPC_STUB_DIR}/response-${count}.json"
[[ -f "${response}" ]] || response="${JSONRPC_STUB_DIR}/response-default.json"
cat "${response}"
STUB
  chmod +x "${bin_dir}/curl"
  printf '%s\n' "${bin_dir}"
}

# Builds a JSON-RPC batch response for the fixed probe request set.
write_jsonrpc_response() {
  local file="$1" youtube_enabled="$2"
  python3 - "${file}" "${youtube_enabled}" <<'PYEOF'
import json
import sys

path, youtube_enabled = sys.argv[1], sys.argv[2] == "true"
settings = {
    "locale.language": "resource.language.en_us",
    "locale.country": "USA (12h)",
    "locale.keyboardlayouts": "English QWERTY",
    "locale.timezonecountry": "United States",
    "locale.timezone": "America/Los_Angeles",
    "lookandfeel.skin": "skin.arctic.fuse.3",
    "weather.addon": "weather.ha",
}
batch = [{"jsonrpc": "2.0", "id": "version", "result": {"version": {"major": 13}}}]
for setting_id, value in settings.items():
    batch.append({"jsonrpc": "2.0", "id": "setting:" + setting_id,
                  "result": {"value": value}})
batch.append({"jsonrpc": "2.0", "id": "addon:weather.ha",
              "result": {"addon": {"addonid": "weather.ha", "enabled": True,
                                   "version": "0.0.6.6"}}})
batch.append({"jsonrpc": "2.0", "id": "addon:plugin.video.youtube",
              "result": {"addon": {"addonid": "plugin.video.youtube",
                                   "enabled": youtube_enabled,
                                   "version": "7.4.4"}}})
batch.append({"jsonrpc": "2.0", "id": "addon:script.missing",
              "error": {"code": -32602, "message": "Invalid params."}})
with open(path, "w") as handle:
    json.dump(batch, handle)
PYEOF
}

# Runs the remote probe exactly as the device would: the emitted Python
# program, a private storage root, and a stubbed curl. The ambient timezone is
# deliberately *not* the requested zone, so nothing the probe concludes about
# the device's local time can be satisfied by the environment these tests
# happen to run in; what the device "prints" is decided by a `date` stub.
run_remote_probe() {
  local dir="$1" bin_dir="$2" root="$3" request="$4"
  run_remote_probe_with_path "${dir}" "${bin_dir}:${PATH}" "${root}" "${request}"
}

# The same probe run with the search path stated exactly, so a test can prove
# what happens when a tool the probe needs is absent from the device.
run_remote_probe_with_path() {
  local dir="$1" path_value="$2" root="$3" request="$4"
  local probe="${dir}/verify-probe.py"
  bash "${PROVISIONER}" --emit-remote-script verify-probe > "${probe}"
  JSONRPC_STUB_DIR="${dir}/stub" PATH="${path_value}" TZ="${PROBE_AMBIENT_TZ:-UTC}" \
    python3 "${probe}" "${root}" "${request}" "${dir}/curl.conf" "${dir}/system/"
}

# What a correct device would print for one zone, read from this machine's own
# tz database through the real `date` rather than from the probe's own logic.
zone_marks() {
  TZ="$1" /bin/date +%Z%z
}

# Stubs `date` so a test decides exactly what the device reports, including
# answers BusyBox can give that are not zone marks at all.
install_date_stub() {
  local bin_dir="$1" output="$2" status="${3:-0}"
  printf '%s\n' "${output}" > "${bin_dir}/date-output"
  printf '%s\n' "${status}" > "${bin_dir}/date-status"
  cat > "${bin_dir}/date" <<'STUB'
#!/bin/bash
stub_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cat "${stub_dir}/date-output"
exit "$(cat "${stub_dir}/date-status")"
STUB
  chmod +x "${bin_dir}/date"
}

# A search path holding only what the test harness itself needs to start the
# probe, so `curl` is genuinely missing the way it would be on a device whose
# image does not ship it. The interpreter is linked from its real path rather
# than from a wrapper that would need a shell of its own.
install_probe_path_without_curl() {
  local dir="$1" bin_dir="$1/nocurl-bin" resolved
  mkdir -p "${bin_dir}"
  resolved="$(python3 -c 'import sys; sys.stdout.write(sys.executable)')"
  ln -sf "${resolved}" "${bin_dir}/python3"
  ln -sf "$(command -v date)" "${bin_dir}/date"
  printf '%s\n' "${bin_dir}"
}

# Writes the probe request in the same base64 KEY=value grammar the settings
# payload uses, so no secret ever appears in an argument list.
write_probe_request() {
  local file="$1" line key value
  : > "${file}"
  chmod 600 "${file}"
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    printf '%s=%s\n' "${key}" "$(printf '%s' "${value}" | openssl base64 -A)" >> "${file}"
  done
}

# `layout` selects how /etc/localtime is stored, because CoreELEC images use
# both a symlink into the zoneinfo tree and a plain copy of the zone file.
make_probe_fixture_root() {
  local dir="$1" layout="${2:-symlink}" root="$1/storage"
  local zoneinfo="${dir}/system/usr/share/zoneinfo/America/Los_Angeles"
  mkdir -p "${root}/.cache" "${root}/.kodi/userdata/addon_data/weather.ha"
  mkdir -p "${dir}/system/etc" "${dir}/system/usr/share/zoneinfo/America"
  mkdir -p "${dir}/stub"
  printf 'TIMEZONE=America/Los_Angeles\n' > "${root}/.cache/timezone"
  printf 'TZif2-fixture-America-Los_Angeles\n' > "${zoneinfo}"
  rm -f "${dir}/system/etc/localtime"
  case "${layout}" in
    symlink) ln -sf "/usr/share/zoneinfo/America/Los_Angeles" "${dir}/system/etc/localtime" ;;
    copy) cp "${zoneinfo}" "${dir}/system/etc/localtime" ;;
    foreign-copy) printf 'TZif2-fixture-UTC\n' > "${dir}/system/etc/localtime" ;;
    *) printf 'unknown localtime layout: %s\n' "${layout}" >&2; return 1 ;;
  esac
  cat > "${root}/.kodi/userdata/addon_data/weather.ha/settings.xml" <<'XML'
<settings>
    <setting id="ha_key" value="home-assistant-token-secret" />
    <setting id="ha_server" value="https://homeassistant.example.lan:8123" />
    <setting id="ha_weather_forecast_entity_id" value="weather.forecast_home" />
    <setting id="ha_sun_entity_id" value="sun.sun" />
</settings>
XML
  printf '%s\n' "${root}"
}

test_remote_verify_script_passes_shell_syntax_check() {
  local dir script
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  script="${dir}/verify.sh"
  bash "${PROVISIONER}" --emit-remote-script verify /storage > "${script}"
  sh -n "${script}" || return 1
  assert_contains "$(cat "${script}")" "127.0.0.1" \
    "verification talks to Kodi over device localhost" || return 1
  assert_contains "$(cat "${script}")" "trap" "the curl config is removed by trap" || return 1
  # It travels on the remote shell's stdin, so it is free to contain quotes;
  # what matters is that it reads the request from the private cache.
  assert_contains "$(cat "${script}")" "verify-request.conf" \
    "the request is read from the private provisioning cache" || return 1
  assert_not_contains "$(cat "${script}")" "EnableAddon" \
    "no modal enable dialog is used" || return 1
}

test_remote_verify_probe_reports_state_without_secrets() {
  local dir root bin_dir request output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  request="${dir}/request.conf"
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=1
ADDON_IDS=weather.ha
TIMEZONE=America/Los_Angeles
HOME_ASSISTANT_URL=https://homeassistant.example.lan:8123
HOME_ASSISTANT_WEATHER_ENTITY=weather.forecast_home
HOME_ASSISTANT_SUN_ENTITY=sun.sun
HAVE_HOME_ASSISTANT_TOKEN=1
ENTRIES
  write_jsonrpc_response "${dir}/stub/response-default.json" true
  install_date_stub "${bin_dir}" "$(zone_marks America/Los_Angeles)"

  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "jsonrpc_version=" "the JSON-RPC version is reported" || return 1
  assert_contains "${output}" "setting.locale.language=resource.language.en_us" \
    "regional settings come from Kodi" || return 1
  assert_contains "${output}" "setting.lookandfeel.skin=skin.arctic.fuse.3" \
    "the active skin comes from Kodi" || return 1
  assert_contains "${output}" "addon.weather.ha.installed=1" "add-on presence reported" || return 1
  assert_contains "${output}" "addon.weather.ha.version=0.0.6.6" "add-on version reported" || return 1
  assert_contains "${output}" "addon.weather.ha.enabled=1" "add-on enabled state reported" || return 1
  assert_contains "${output}" "timezone_cache=America/Los_Angeles" "timezone cache reported" || return 1
  assert_contains "${output}" "localtime_path=/usr/share/zoneinfo/America/Los_Angeles" \
    "zoneinfo target reported" || return 1
  assert_contains "${output}" "localtime_kind=symlink" "the localtime layout is reported" || return 1
  assert_contains "${output}" "date_matches_timezone=1" "device local time reported" || return 1
  assert_contains "${output}" "addon_settings.weather.ha.configured=1" \
    "configured add-on files are checked on the device" || return 1
  assert_not_contains "${output}" "kodi-web-password-secret" "no Kodi password leaves the device" || return 1
  assert_not_contains "${output}" "home-assistant-token-secret" "no add-on token leaves the device" || return 1
}

# The probe is what makes a copied /etc/localtime verifiable at all, so it
# answers the content question the Mac cannot ask.
test_remote_verify_probe_compares_a_copied_localtime_by_content() {
  local dir root bin_dir request output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}" copy)"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  request="${dir}/request.conf"
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=1
ADDON_IDS=weather.ha
TIMEZONE=America/Los_Angeles
ENTRIES
  write_jsonrpc_response "${dir}/stub/response-default.json" true
  install_date_stub "${bin_dir}" "$(zone_marks America/Los_Angeles)"

  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "localtime_kind=file" "a plain file layout is reported as such" || return 1
  assert_contains "${output}" "localtime_zoneinfo_match=1" \
    "a byte-equal copy of the requested zone is recognized" || return 1

  # The same layout holding a different zone's bytes is not a match.
  make_probe_fixture_root "${dir}" foreign-copy >/dev/null
  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "localtime_zoneinfo_match=0" \
    "a copy of another zone is not claimed to match" || return 1
}

# The device's local time is observed, not assumed: the ambient timezone is
# wrong on purpose and `date` is stubbed, so each answer is genuinely tested.
test_remote_verify_probe_judges_device_date_against_the_requested_zone() {
  local dir root bin_dir request output expected
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  request="${dir}/request.conf"
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=1
ADDON_IDS=weather.ha
TIMEZONE=America/Los_Angeles
ENTRIES
  write_jsonrpc_response "${dir}/stub/response-default.json" true

  # Right zone, wrong ambient TZ: the expectation must come from the request.
  expected="$(zone_marks America/Los_Angeles)"
  install_date_stub "${bin_dir}" "${expected}"
  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "date_matches_timezone=1" "a correct device clock is recognized" || return 1
  assert_contains "${output}" "date_offset_expected=${expected}" \
    "the expectation is computed for the requested zone" || return 1
  assert_contains "${output}" "date_offset_observed=${expected}" \
    "the device's own answer is reported" || return 1

  # A device genuinely running in another zone is a real mismatch.
  install_date_stub "${bin_dir}" "$(zone_marks Australia/Sydney)"
  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "date_matches_timezone=0" "a wrong device clock is reported" || return 1

  # BusyBox that does not expand the format exits 0 with unusable output.
  install_date_stub "${bin_dir}" '%Z%z'
  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "date_matches_timezone=unavailable" \
    "an unexpanded format is a capability gap, not a mismatch" || return 1
  assert_not_contains "${output}" "date_matches_timezone=0" \
    "an unexpanded format is never reported as a wrong clock" || return 1

  # Neither is an empty answer or a nonzero exit.
  install_date_stub "${bin_dir}" "" 1
  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "date_matches_timezone=unavailable" \
    "a failing date is a capability gap" || return 1
}

# A device without curl cannot be probed at all. Saying so at once is both
# accurate and fast; retrying a tool that does not exist is neither.
test_remote_verify_probe_fails_immediately_when_curl_is_missing() {
  local dir root bin_dir path_value request output rc start elapsed
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  path_value="$(install_probe_path_without_curl "${dir}")"
  request="${dir}/request.conf"
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=30
ADDON_IDS=weather.ha
TIMEZONE=America/Los_Angeles
ENTRIES

  start="${SECONDS}"
  set +e
  output="$(run_remote_probe_with_path "${dir}" "${path_value}" "${root}" "${request}" 2>&1)"
  rc=$?
  set -e
  elapsed=$(( SECONDS - start ))
  assert_failure "${rc}" "a device without curl cannot be verified" || return 1
  assert_contains "${output}" "curl" "the error names the missing tool" || return 1
  assert_not_contains "${output}" "did not answer" \
    "a missing tool is not relabelled as an unresponsive Kodi" || return 1
  if (( elapsed > 15 )); then
    printf 'the probe retried a tool that does not exist for %ss\n' "${elapsed}" >&2
    return 1
  fi
  if [[ -e "${dir}/curl.conf" ]]; then
    printf 'the curl config outlived the probe\n' >&2
    return 1
  fi
}

test_remote_verify_probe_enables_a_disabled_addon_over_jsonrpc() {
  local dir root bin_dir request output requests
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  request="${dir}/request.conf"
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=1
ADDON_IDS=plugin.video.youtube
TIMEZONE=America/Los_Angeles
ENTRIES
  # First query: installed but disabled. After SetAddonEnabled, the re-query
  # reports it enabled.
  write_jsonrpc_response "${dir}/stub/response-1.json" false
  printf '[{"jsonrpc":"2.0","id":"enable:plugin.video.youtube","result":"OK"}]\n' \
    > "${dir}/stub/response-2.json"
  write_jsonrpc_response "${dir}/stub/response-3.json" true
  write_jsonrpc_response "${dir}/stub/response-default.json" true

  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  requests="$(cat "${dir}"/stub/request-*.json)"
  assert_contains "${requests}" "Addons.SetAddonEnabled" \
    "a disabled add-on is enabled over JSON-RPC" || return 1
  assert_not_contains "${requests}" "EnableAddon" "no modal dialog is used" || return 1
  assert_contains "${output}" "addon.plugin.video.youtube.enabled=1" \
    "the re-query observes the enabled state" || return 1
  assert_contains "${output}" "addon.plugin.video.youtube.enable_attempted=1" \
    "the enable attempt is recorded" || return 1
  assert_eq "3" "$(cat "${dir}/stub/call-count")" "query, enable, re-query" || return 1
}

test_remote_verify_probe_reports_a_missing_addon() {
  local dir root bin_dir request output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  request="${dir}/request.conf"
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=1
ADDON_IDS=script.missing
TIMEZONE=America/Los_Angeles
ENTRIES
  write_jsonrpc_response "${dir}/stub/response-default.json" true

  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "addon.script.missing.installed=0" \
    "an add-on Kodi does not know is reported absent" || return 1
  assert_contains "${output}" "addon.script.missing.enabled=0" \
    "an absent add-on is not reported enabled" || return 1
}

test_remote_verify_probe_uses_a_private_curl_config_and_removes_it() {
  local dir root bin_dir request
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  request="${dir}/request.conf"
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=1
ADDON_IDS=weather.ha
TIMEZONE=America/Los_Angeles
ENTRIES
  write_jsonrpc_response "${dir}/stub/response-default.json" true

  run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" >/dev/null 2>&1
  assert_eq "600" "$(cat "${dir}/stub/curl-config-mode")" \
    "the credential file is private while curl reads it" || return 1
  assert_contains "$(cat "${dir}/stub/curl-config-copy")" "homeassistant:" \
    "credentials travel in the curl config, not the argument list" || return 1
  if [[ -e "${dir}/curl.conf" ]]; then
    printf 'the curl config outlived the probe\n' >&2
    return 1
  fi
}

run_all_tests \
  test_all_expected_addon_versions_are_verified \
  test_disabled_addon_is_failure \
  test_missing_addon_is_failure \
  test_addon_version_mismatch_is_failure \
  test_active_skin_is_verified \
  test_weather_provider_is_verified_only_when_configured \
  test_timezone_cache_and_zoneinfo_are_verified \
  test_regular_file_localtime_is_verified_by_content \
  test_unexpected_device_date_output_is_advisory_not_fatal \
  test_date_offset_reports_expected_and_observed_marks \
  test_unreadable_verification_material_fails_without_exiting \
  test_unreadable_manifest_rolls_back_the_deployment \
  test_english_us_values_are_verified \
  test_selected_subset_verifies_only_the_selected_addons \
  test_emby_and_youtube_are_classified_manual \
  test_configured_nextpvr_ha_and_pm4k_are_classified_configured \
  test_missing_optional_values_are_classified_unconfigured \
  test_report_lists_secret_presence_without_secret_values \
  test_report_redacts_all_supplied_secret_values \
  test_report_records_config_fingerprint_without_secrets \
  test_report_lists_manual_actions_in_order \
  test_report_states_addon_status_and_verification_per_addon \
  test_report_keeps_subset_dependency_warning_explicit \
  test_report_is_strict_key_value \
  test_local_jsonrpc_unreachability_is_environmental_only \
  test_report_fingerprint_tool_is_required_even_without_kodi \
  test_verification_success_finalizes_and_commits \
  test_verification_mismatch_is_fatal \
  test_incomplete_rollback_is_fatal_with_recovery_path \
  test_an_unanswered_probe_is_a_verification_failure \
  test_failed_finalize_is_fatal \
  test_remote_verify_script_passes_shell_syntax_check \
  test_remote_verify_probe_reports_state_without_secrets \
  test_remote_verify_probe_compares_a_copied_localtime_by_content \
  test_remote_verify_probe_judges_device_date_against_the_requested_zone \
  test_remote_verify_probe_fails_immediately_when_curl_is_missing \
  test_remote_verify_probe_enables_a_disabled_addon_over_jsonrpc \
  test_remote_verify_probe_reports_a_missing_addon \
  test_remote_verify_probe_uses_a_private_curl_config_and_removes_it
