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
9	repository.beta.emby.kodi	1.0.11	9.zip
10	repository.dontpanic	0.2.10	10.zip
11	repository.jurialmunkey	3.4	11.zip
12	script.artistslideshow	4.2.0	12.zip
13	resource.images.arctic.waves	0.0.2	13.zip
14	resource.images.weatherfanart.multi	0.0.6	14.zip
15	resource.images.moviecountryicons.maps	0.0.1	15.zip
16	resource.images.studios.white	0.0.34	16.zip
17	service.upnext	1.1.9+matrix.1	17.zip
18	inputstream.adaptive	21.5.24.1	18.zip
19	inputstream.ffmpegdirect	21.3.8.1	19.zip
20	resource.font.robotocjksc	0.0.3	20.zip
21	resource.images.studios.coloured	0.0.24	21.zip
22	resource.images.weathericons.white	0.0.6	22.zip
23	script.module.addon.signals	0.0.6+matrix.1	23.zip
24	script.module.certifi	2023.5.7	24.zip
25	script.module.chardet	5.1.0	25.zip
26	script.module.defusedxml	0.6.0+matrix.1	26.zip
27	script.module.dateutil	2.8.2	27.zip
28	script.module.future	1.0.0+matrix.1	28.zip
29	script.module.idna	3.10.0	29.zip
30	script.module.infotagger	0.0.9	30.zip
31	script.module.inputstreamhelper	0.8.5	31.zip
32	script.module.iso8601	2.0.0	32.zip
33	script.module.jurialmunkey	0.2.35	33.zip
34	script.module.kodi-six	0.1.3.1	34.zip
35	script.module.pysocks	1.7.0+matrix.1	35.zip
36	script.module.qrcode	6.1.0+matrix.3	36.zip
37	script.module.requests	2.31.0	37.zip
38	script.module.six	1.16.0+matrix.1	38.zip
39	script.module.urllib3	2.2.3	39.zip
40	script.module.yaml	6.0.1	40.zip
41	script.skinvariables	2.2.2	41.zip
42	script.texturemaker	0.2.11	42.zip
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
cec.tv_off_action=36028
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
addon.repository.beta.emby.kodi.installed=1
addon.repository.beta.emby.kodi.version=1.0.11
addon.repository.beta.emby.kodi.enabled=1
addon.repository.beta.emby.kodi.enable_attempted=0
addon.repository.dontpanic.installed=1
addon.repository.dontpanic.version=0.2.10
addon.repository.dontpanic.enabled=1
addon.repository.dontpanic.enable_attempted=0
addon.repository.jurialmunkey.installed=1
addon.repository.jurialmunkey.version=3.4
addon.repository.jurialmunkey.enabled=1
addon.repository.jurialmunkey.enable_attempted=0
addon.script.artistslideshow.installed=1
addon.script.artistslideshow.version=4.2.0
addon.script.artistslideshow.enabled=1
addon.script.artistslideshow.enable_attempted=0
addon.resource.images.arctic.waves.installed=1
addon.resource.images.arctic.waves.version=0.0.2
addon.resource.images.arctic.waves.enabled=1
addon.resource.images.arctic.waves.enable_attempted=0
addon.resource.images.weatherfanart.multi.installed=1
addon.resource.images.weatherfanart.multi.version=0.0.6
addon.resource.images.weatherfanart.multi.enabled=1
addon.resource.images.weatherfanart.multi.enable_attempted=0
addon.resource.images.moviecountryicons.maps.installed=1
addon.resource.images.moviecountryicons.maps.version=0.0.1
addon.resource.images.moviecountryicons.maps.enabled=1
addon.resource.images.moviecountryicons.maps.enable_attempted=0
addon.resource.images.studios.white.installed=1
addon.resource.images.studios.white.version=0.0.34
addon.resource.images.studios.white.enabled=1
addon.resource.images.studios.white.enable_attempted=0
addon.service.upnext.installed=1
addon.service.upnext.version=1.1.9+matrix.1
addon.service.upnext.enabled=1
addon.service.upnext.enable_attempted=0
addon.inputstream.adaptive.installed=1
addon.inputstream.adaptive.version=21.5.24.1
addon.inputstream.adaptive.enabled=1
addon.inputstream.adaptive.enable_attempted=0
addon.inputstream.ffmpegdirect.installed=1
addon.inputstream.ffmpegdirect.version=21.3.8.1
addon.inputstream.ffmpegdirect.enabled=1
addon.inputstream.ffmpegdirect.enable_attempted=0
addon.resource.font.robotocjksc.installed=1
addon.resource.font.robotocjksc.version=0.0.3
addon.resource.font.robotocjksc.enabled=1
addon.resource.font.robotocjksc.enable_attempted=0
addon.resource.images.studios.coloured.installed=1
addon.resource.images.studios.coloured.version=0.0.24
addon.resource.images.studios.coloured.enabled=1
addon.resource.images.studios.coloured.enable_attempted=0
addon.resource.images.weathericons.white.installed=1
addon.resource.images.weathericons.white.version=0.0.6
addon.resource.images.weathericons.white.enabled=1
addon.resource.images.weathericons.white.enable_attempted=0
addon.script.module.addon.signals.installed=1
addon.script.module.addon.signals.version=0.0.6+matrix.1
addon.script.module.addon.signals.enabled=1
addon.script.module.addon.signals.enable_attempted=0
addon.script.module.certifi.installed=1
addon.script.module.certifi.version=2023.5.7
addon.script.module.certifi.enabled=1
addon.script.module.certifi.enable_attempted=0
addon.script.module.chardet.installed=1
addon.script.module.chardet.version=5.1.0
addon.script.module.chardet.enabled=1
addon.script.module.chardet.enable_attempted=0
addon.script.module.defusedxml.installed=1
addon.script.module.defusedxml.version=0.6.0+matrix.1
addon.script.module.defusedxml.enabled=1
addon.script.module.defusedxml.enable_attempted=0
addon.script.module.dateutil.installed=1
addon.script.module.dateutil.version=2.8.2
addon.script.module.dateutil.enabled=1
addon.script.module.dateutil.enable_attempted=0
addon.script.module.future.installed=1
addon.script.module.future.version=1.0.0+matrix.1
addon.script.module.future.enabled=1
addon.script.module.future.enable_attempted=0
addon.script.module.idna.installed=1
addon.script.module.idna.version=3.10.0
addon.script.module.idna.enabled=1
addon.script.module.idna.enable_attempted=0
addon.script.module.infotagger.installed=1
addon.script.module.infotagger.version=0.0.9
addon.script.module.infotagger.enabled=1
addon.script.module.infotagger.enable_attempted=0
addon.script.module.inputstreamhelper.installed=1
addon.script.module.inputstreamhelper.version=0.8.5
addon.script.module.inputstreamhelper.enabled=1
addon.script.module.inputstreamhelper.enable_attempted=0
addon.script.module.iso8601.installed=1
addon.script.module.iso8601.version=2.0.0
addon.script.module.iso8601.enabled=1
addon.script.module.iso8601.enable_attempted=0
addon.script.module.jurialmunkey.installed=1
addon.script.module.jurialmunkey.version=0.2.35
addon.script.module.jurialmunkey.enabled=1
addon.script.module.jurialmunkey.enable_attempted=0
addon.script.module.kodi-six.installed=1
addon.script.module.kodi-six.version=0.1.3.1
addon.script.module.kodi-six.enabled=1
addon.script.module.kodi-six.enable_attempted=0
addon.script.module.pysocks.installed=1
addon.script.module.pysocks.version=1.7.0+matrix.1
addon.script.module.pysocks.enabled=1
addon.script.module.pysocks.enable_attempted=0
addon.script.module.qrcode.installed=1
addon.script.module.qrcode.version=6.1.0+matrix.3
addon.script.module.qrcode.enabled=1
addon.script.module.qrcode.enable_attempted=0
addon.script.module.requests.installed=1
addon.script.module.requests.version=2.31.0
addon.script.module.requests.enabled=1
addon.script.module.requests.enable_attempted=0
addon.script.module.six.installed=1
addon.script.module.six.version=1.16.0+matrix.1
addon.script.module.six.enabled=1
addon.script.module.six.enable_attempted=0
addon.script.module.urllib3.installed=1
addon.script.module.urllib3.version=2.2.3
addon.script.module.urllib3.enabled=1
addon.script.module.urllib3.enable_attempted=0
addon.script.module.yaml.installed=1
addon.script.module.yaml.version=6.0.1
addon.script.module.yaml.enabled=1
addon.script.module.yaml.enable_attempted=0
addon.script.skinvariables.installed=1
addon.script.skinvariables.version=2.2.2
addon.script.skinvariables.enabled=1
addon.script.skinvariables.enable_attempted=0
addon.script.texturemaker.installed=1
addon.script.texturemaker.version=0.2.11
addon.script.texturemaker.enabled=1
addon.script.texturemaker.enable_attempted=0
addon_settings.weather.ha.configured=1
addon_settings.pvr.nextpvr.configured=1
addon_settings.script.plexmod.configured=1
addon_settings.plugin.video.themoviedb.helper.omdb_configured=1
addon_settings.plugin.video.themoviedb.helper.mdblist_configured=1
arctic_fuse.hubs_configured=1
arctic_fuse.next_aired_disabled=1
arctic_fuse.pvr_hub_configured=1
arctic_fuse.addons_hub_configured=1
arctic_fuse.plex_entry_configured=1
arctic_fuse.youtube_entry_configured=1
arctic_fuse.settings_tile_configured=1
arctic_fuse.home_widgets_configured=1
arctic_fuse.power_menu_configured=1
arctic_fuse.playlist.InProgressMovies90Days.configured=1
arctic_fuse.playlist.InProgressShows90Days.configured=1
arctic_fuse.playlist.RecentlyAiredEpisodes30Days.configured=1
arctic_fuse.playlist.RecentlyReleasedMoviesCurrentYear.configured=1
arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent=1
arctic_fuse.playlist.NewShows.configured=1
arctic_fuse.playlist.NewMovies.configured=1
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
    OMDB_API_KEY=omdb-key MDBLIST_API_KEY=mdblist-key \
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
  assert_eq "42" "$(printf '%s\n' "${output}" | grep -c '\.verification=ok$')" \
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

# A run that could not enable an add-on says which one, so the operator is not
# left diffing the per-add-on block to find it.
test_unresolved_enables_are_named_in_the_report() {
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
  set_observation "${observations}" "addon.plugin.video.youtube.enable_attempted" "1"
  set_observation "${observations}" "addon.script.plexmod.enabled" "0"
  set_observation "${observations}" "addon.script.plexmod.enable_attempted" "1"
  set_observation "${observations}" "addon_enable_unresolved" \
    "plugin.video.youtube script.plexmod"

  set +e
  output="$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=1234 PLEX_TOKEN=plex-token \
    run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an add-on that could not be enabled must fail verification" || return 1
  assert_contains "${output}" "addon_enable_unresolved=plugin.video.youtube script.plexmod" \
    "the exact unresolved add-ons are named" || return 1
  assert_contains "${output}" "verification_result=fail" "overall result fails" || return 1
}

# A run where Kodi settled on every add-on says nothing about unresolved ones.
test_a_settled_run_reports_no_unresolved_enables() {
  local dir config manifest observations output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "addon_enable_unresolved" ""

  output="$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=1234 PLEX_TOKEN=plex-token \
    run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  assert_not_contains "${output}" "addon_enable_unresolved" \
    "a settled run does not report an empty unresolved list" || return 1
  assert_contains "${output}" "verification_result=pass" "overall result passes" || return 1
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

# The CEC "TV off action" is not user-configurable: the transformer always
# requests Ignore (36028), so any other observed value is a fatal baseline
# mismatch, not an advisory note.
test_cec_ignore_mismatch_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "cec.tv_off_action" "13011"

  set +e
  output="$(run_verify "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a CEC action other than Ignore must fail verification" || return 1
  assert_contains "${output}" "cec.tv_off_action.expected=36028" \
    "the comparator names the expected CEC action" || return 1
  assert_contains "${output}" "cec.tv_off_action.observed=13011" \
    "the comparator names the observed CEC action" || return 1
  assert_contains "${output}" "cec.tv_off_action.status=mismatch" \
    "the CEC action mismatch is reported" || return 1
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
    "$(OMDB_API_KEY=omdb MDBLIST_API_KEY=mdblist run_classify "${config}" plugin.video.themoviedb.helper)" \
    "TMDb Helper with both metadata keys is configured" || return 1
}

test_missing_optional_values_are_classified_unconfigured() {
  local dir config addon_id
  # Isolate from ambient environment secrets so the classification is
  # deterministic regardless of the operator's shell, and put them back so
  # this test does not change the environment later tests observe.
  stash_unset_env OMDB_API_KEY MDBLIST_API_KEY

  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"; restore_stashed_env' RETURN
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
  # Isolate from ambient environment secrets so the presence assertions are
  # deterministic regardless of the operator's shell, and put them back so
  # this test does not change the environment later tests observe.
  stash_unset_env OMDB_API_KEY MDBLIST_API_KEY

  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"; restore_stashed_env' RETURN
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

# The CEC peripheral file's name varies by adapter and is never part of the
# observation contract, so the audit report must record the CEC baseline
# result without ever naming the file it came from.
test_audit_report_records_cec_ignore_without_adapter_filename() {
  local dir config manifest observations report
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_base_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  report="$(run_report "${config}" "${dir}/out" "${observations}" "${manifest}")"
  [[ -f "${report}" ]] || {
    printf 'no report was written\n' >&2
    return 1
  }
  assert_eq "36028" "$(report_line "${report}" cec.tv_off_action.expected)" \
    "the expected CEC action is recorded" || return 1
  assert_eq "36028" "$(report_line "${report}" cec.tv_off_action.observed)" \
    "the observed CEC action is recorded" || return 1
  assert_eq "ok" "$(report_line "${report}" cec.tv_off_action.status)" \
    "a matching CEC action verifies" || return 1
  assert_not_contains "$(cat "${report}")" "cec_CEC_Adapter" \
    "the report never names the dynamic CEC adapter file" || return 1
  assert_not_contains "$(cat "${report}")" "peripheral_data" \
    "the report never names the peripheral_data path" || return 1
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
  assert_eq "5" "$(report_line "${report}" manual_actions)" \
    "only real manual steps are counted" || return 1
  assert_not_contains "${actions}" "Next Aired" \
    "the Next Aired explanation is not a manual action" || return 1
  # It is a fact about the deployed state, so it is reported as one.
  assert_contains "$(cat "${report}")" \
    "next_aired_note=Next Aired is disabled because the installed TMDb Helper requires Trakt OAuth and the local-data alternative is not reliable on this device class." \
    "the Next Aired resolution is reported as information" || return 1

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
  assert_eq "2" "$(report_line "${report}" manual_actions)" \
    "manual action numbering stays contiguous" || return 1
  assert_contains "$(cat "${report}")" "next_aired_note=Next Aired is disabled" \
    "the informational note is independent of the manual actions" || return 1
}

# A test that isolates itself from ambient operator secrets must not leave the
# environment changed for whatever runs after it.
test_ratings_key_isolation_restores_the_environment() {
  local before
  OMDB_API_KEY="omdb-sentinel-not-a-real-key"
  unset MDBLIST_API_KEY 2>/dev/null || true
  before="${OMDB_API_KEY}"

  stash_unset_env OMDB_API_KEY MDBLIST_API_KEY
  assert_eq "" "${OMDB_API_KEY-}" "the key is absent inside the isolated test" || return 1
  assert_eq "" "${OMDB_API_KEY+set}" "the key is unset, not merely empty" || return 1

  restore_stashed_env
  assert_eq "${before}" "${OMDB_API_KEY-}" "the previous value is restored" || return 1
  assert_eq "" "${MDBLIST_API_KEY+set}" \
    "a variable that was unset stays unset" || return 1
  unset OMDB_API_KEY
}

test_report_states_addon_status_and_verification_per_addon() {
  local dir config manifest observations report
  # Isolate from ambient environment secrets so the status assertions are
  # deterministic regardless of the operator's shell, and put them back so
  # this test does not change the environment later tests observe.
  stash_unset_env OMDB_API_KEY MDBLIST_API_KEY

  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"; restore_stashed_env' RETURN
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

test_cec_ignore_mismatch_triggers_rollback() {
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
  set_observation "${observations}" "cec.tv_off_action" "13011"

  set +e
  output="$(run_conclude "${config}" "${observations}" "${manifest}" 0 0 "${log}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a CEC action mismatch must be fatal" || return 1
  assert_contains "${output}" "verification_result=fail" "the failure is reported" || return 1
  assert_contains "${output}" "deployment_state=rolled-back" "the transaction is undone" || return 1
  assert_contains "$(cat "${log}")" "rollback" "rollback was invoked, not finalize" || return 1
  assert_not_contains "$(cat "${log}")" "finalize" "a CEC mismatch must not be committed" || return 1
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

# Serves JSON-RPC in place of the device's curl with the enable semantics the
# device actually showed. Kodi answers `Addons.SetAddonEnabled` with OK for any
# installed add-on -- `CAddonMgr::EnableAddon` enables the dependency closure
# deepest-first and returns true even when a step of that walk did not take --
# so the reply is never evidence. What decides the outcome is the state at the
# moment the request is served: an add-on whose dependencies are not enabled
# yet stays disabled, which is exactly the residue the live run left behind
# (chardet, idna, and urllib3 enabled; certifi and the requests module that
# needs them still disabled).
install_kodi_addon_state_stub() {
  local dir="$1" bin_dir="$1/stub-bin"
  mkdir -p "${bin_dir}" "${dir}/stub"
  cat > "${dir}/stub/fake-kodi.py" <<'FAKE'
import json
import os
import sys

stub = os.environ["JSONRPC_STUB_DIR"]
addons = json.load(open(os.path.join(stub, "addons.json")))
state_path = os.path.join(stub, "enabled.json")
if os.path.exists(state_path):
    enabled = set(json.load(open(state_path)))
else:
    enabled = set()

SETTINGS = {
    "locale.language": "resource.language.en_us",
    "locale.country": "USA (12h)",
    "locale.keyboardlayouts": "English QWERTY",
    "locale.timezonecountry": "United States",
    "locale.timezone": "America/Los_Angeles",
    "lookandfeel.skin": "skin.arctic.fuse.3",
    "weather.addon": "weather.ha",
}

body = json.load(open(sys.argv[1]))
if isinstance(body, dict):
    body = [body]
replies = []
for entry in body:
    ident = entry.get("id")
    method = entry.get("method")
    params = entry.get("params") or {}
    if method == "JSONRPC.Version":
        replies.append({"jsonrpc": "2.0", "id": ident,
                        "result": {"version": {"major": 13, "minor": 5,
                                               "patch": 0}}})
    elif method == "Settings.GetSettingValue":
        replies.append({"jsonrpc": "2.0", "id": ident,
                        "result": {"value": SETTINGS.get(params.get("setting"), "")}})
    elif method == "Addons.GetAddonDetails":
        addon_id = params.get("addonid")
        details = addons.get(addon_id)
        if details is None:
            replies.append({"jsonrpc": "2.0", "id": ident,
                            "error": {"code": -32602, "message": "Invalid params."}})
        else:
            replies.append({"jsonrpc": "2.0", "id": ident,
                            "result": {"addon": {"addonid": addon_id,
                                                 "version": details["version"],
                                                 "enabled": addon_id in enabled}}})
    elif method == "Addons.SetAddonEnabled":
        addon_id = params.get("addonid")
        details = addons.get(addon_id)
        if details is None:
            replies.append({"jsonrpc": "2.0", "id": ident,
                            "error": {"code": -32602, "message": "Invalid params."}})
        else:
            if all(dep in enabled for dep in details.get("requires", [])):
                enabled.add(addon_id)
            replies.append({"jsonrpc": "2.0", "id": ident, "result": "OK"})
    else:
        replies.append({"jsonrpc": "2.0", "id": ident,
                        "error": {"code": -32601, "message": "Method not found."}})

json.dump(sorted(enabled), open(state_path, "w"))
sys.stdout.write(json.dumps(replies))
FAKE
  cat > "${bin_dir}/curl" <<'STUB'
#!/bin/bash
set -u
while (( $# > 0 )); do
  case "$1" in
    --config) shift 2 ;;
    *) shift ;;
  esac
done
count_file="${JSONRPC_STUB_DIR}/call-count"
count=0
[[ -f "${count_file}" ]] && count="$(cat "${count_file}")"
count=$((count + 1))
printf '%s\n' "${count}" > "${count_file}"
cat > "${JSONRPC_STUB_DIR}/request-${count}.json"
cut_off="${JSONRPC_STUB_DIR}/cut-off-call"
if [[ -f "${cut_off}" && "$(cat "${cut_off}")" == "${count}" ]]; then
  # What curl does when `max-time` runs out: no answer, nothing applied.
  exit 28
fi
python3 "${JSONRPC_STUB_DIR}/fake-kodi.py" "${JSONRPC_STUB_DIR}/request-${count}.json"
STUB
  chmod +x "${bin_dir}/curl"
  printf '%s\n' "${bin_dir}"
}

# States what the fake device has installed: `id|version|dep,dep` per line.
# Every listed add-on starts disabled, the way a fresh unzip does.
write_stub_addons() {
  local file="$1"
  python3 -c '
import json
import sys

addons = {}
for line in sys.stdin.read().splitlines():
    line = line.strip()
    if not line:
        continue
    fields = (line.split("|") + ["", ""])[:3]
    addons[fields[0]] = {"version": fields[1],
                         "requires": [dep for dep in fields[2].split(",") if dep]}
with open(sys.argv[1], "w") as handle:
    json.dump(addons, handle)
' "${file}"
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
# payload uses, so no secret ever appears in an argument list. A literal `\\n`
# in a value becomes a newline, because the production request carries the
# add-on list as one multi-line value.
write_probe_request() {
  local file="$1" line key value
  : > "${file}"
  chmod 600 "${file}"
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    value="${value//\\n/$'\n'}"
    printf '%s=%s\n' "${key}" "$(printf '%s' "${value}" | openssl base64 -A)" >> "${file}"
  done
}

# `layout` selects how /etc/localtime is stored, because CoreELEC images use
# both a symlink into the zoneinfo tree and a plain copy of the zone file.
make_probe_fixture_root() {
  local dir="$1" layout="${2:-symlink}" root="$1/storage"
  local zoneinfo="${dir}/system/usr/share/zoneinfo/America/Los_Angeles"
  mkdir -p "${root}/.cache" "${root}/.kodi/userdata/addon_data/weather.ha"
  mkdir -p "${root}/.kodi/userdata/peripheral_data"
  mkdir -p "${dir}/system/etc" "${dir}/system/usr/share/zoneinfo/America"
  mkdir -p "${dir}/stub"
  printf 'TIMEZONE=America/Los_Angeles\n' > "${root}/.cache/timezone"
  printf 'TZif2-fixture-America-Los_Angeles\n' > "${zoneinfo}"
  # A passing CEC peripheral file, matching the transformer's fixed Ignore
  # (36028) baseline. Tests that care about a different CEC state overwrite
  # this file themselves.
  printf '<settings><setting id="standby_pc_on_tv_standby">36028</setting></settings>\n' \
    > "${root}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml"
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

# The CEC peripheral file's name varies by adapter, so the probe must locate
# it by pattern, report only the setting value, and fail loudly rather than
# guess when it is missing or ambiguous.
test_remote_probe_reports_cec_ignore() {
  local dir root bin_dir request output rc
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
  install_date_stub "${bin_dir}" "$(zone_marks America/Los_Angeles)"

  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "cec.tv_off_action=36028" \
    "the CEC TV-off action is reported" || return 1
  assert_not_contains "${output}" "cec_CEC_Adapter" \
    "the dynamic adapter filename is never reported" || return 1

  # A device with no CEC peripheral file at all cannot be verified.
  rm -rf "${root}/.kodi/userdata/peripheral_data"
  set +e
  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a missing CEC peripheral file must fail the probe" || return 1
  assert_contains "${output}" "peripheral_data" \
    "the failure names the peripheral_data directory" || return 1
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

# One pass cannot settle this. The deployment manifest lists primary add-ons
# before the modules they depend on, and Kodi leaves a dependent disabled when
# its dependency is not enabled at the moment the request is served, so a
# single sweep enables dependencies and reports their dependents disabled --
# which is what the live run recorded. The probe must keep asking until Kodi
# reports a settled state.
test_remote_verify_probe_converges_on_dependency_ordered_enables() {
  local dir root bin_dir request output calls
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}")"
  bin_dir="$(install_kodi_addon_state_stub "${dir}")"
  request="${dir}/request.conf"
  write_stub_addons "${dir}/stub/addons.json" <<'ADDONS'
plugin.video.youtube|7.4.4|script.module.requests
script.module.requests|2.31.0|script.module.certifi
script.module.certifi|2023.5.7|
ADDONS
  # Manifest order: the dependent first, its dependency's dependency last.
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=1
ADDON_IDS=plugin.video.youtube\nscript.module.requests\nscript.module.certifi
TIMEZONE=America/Los_Angeles
ENTRIES
  install_date_stub "${bin_dir}" "$(zone_marks America/Los_Angeles)"

  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "addon.script.module.certifi.enabled=1" \
    "the leaf dependency is enabled" || return 1
  assert_contains "${output}" "addon.script.module.requests.enabled=1" \
    "a dependency enabled in an earlier pass lets its dependent enable" || return 1
  assert_contains "${output}" "addon.plugin.video.youtube.enabled=1" \
    "the probe keeps asking until the dependent is enabled too" || return 1
  assert_contains "${output}" "addon.plugin.video.youtube.enable_attempted=1" \
    "the enable attempt is recorded" || return 1
  assert_contains "${output}" "addon.script.module.certifi.enable_attempted=1" \
    "an add-on attempted in an earlier round keeps its attempt recorded" || return 1
  assert_contains "${output}" "addon_enable_unresolved=" \
    "the unresolved set is always stated" || return 1
  assert_not_contains "${output}" "addon_enable_unresolved=plugin" \
    "nothing is left unresolved once Kodi reports every add-on enabled" || return 1
  calls="$(cat "${dir}/stub/call-count")"
  if (( calls > 24 )); then
    printf 'the probe made %s JSON-RPC calls to settle three add-ons\n' "${calls}" >&2
    return 1
  fi
}

# An add-on Kodi will never enable must not spin the probe and must not be
# smoothed over: the run names it and fails.
test_remote_verify_probe_fails_closed_on_an_addon_it_cannot_enable() {
  local dir root bin_dir request output calls
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}")"
  bin_dir="$(install_kodi_addon_state_stub "${dir}")"
  request="${dir}/request.conf"
  # weather.ha needs a module this device does not have installed at all, so
  # no number of passes can enable it.
  write_stub_addons "${dir}/stub/addons.json" <<'ADDONS'
weather.ha|0.0.6.6|script.module.requests
resource.language.en_us|11.0.82|
ADDONS
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=1
ADDON_IDS=weather.ha\nresource.language.en_us
TIMEZONE=America/Los_Angeles
ENTRIES
  install_date_stub "${bin_dir}" "$(zone_marks America/Los_Angeles)"

  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "addon.weather.ha.enabled=0" \
    "an add-on Kodi never enabled is not reported enabled" || return 1
  assert_contains "${output}" "addon.weather.ha.enable_attempted=1" \
    "the attempt is still recorded" || return 1
  assert_contains "${output}" "addon.resource.language.en_us.enabled=1" \
    "the add-ons that can be enabled still are" || return 1
  assert_contains "${output}" "addon_enable_unresolved=weather.ha" \
    "the exact unresolved add-on is named" || return 1
  assert_not_contains "${output}" "kodi-web-password-secret" \
    "no Kodi password leaves the device" || return 1
  calls="$(cat "${dir}/stub/call-count")"
  if (( calls > 24 )); then
    printf 'the probe retried an add-on that cannot be enabled %s times\n' "${calls}" >&2
    return 1
  fi
}

# A request curl gave up on is not an answer. The state Kodi reports right
# after one is not evidence that nothing more can happen, so a round that was
# cut short must not be read as "this device has settled".
test_remote_verify_probe_keeps_going_when_an_enable_request_is_cut_off() {
  local dir root bin_dir request output calls
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_probe_fixture_root "${dir}")"
  bin_dir="$(install_kodi_addon_state_stub "${dir}")"
  request="${dir}/request.conf"
  write_stub_addons "${dir}/stub/addons.json" <<'ADDONS'
weather.ha|0.0.6.6|
ADDONS
  # Call 1 is the first query, so call 2 is the first enable request.
  printf '2\n' > "${dir}/stub/cut-off-call"
  write_probe_request "${request}" <<'ENTRIES'
KODI_WEB_USER=homeassistant
KODI_WEB_PASSWORD=kodi-web-password-secret
KODI_PORT=8080
JSONRPC_ATTEMPTS=1
ADDON_IDS=weather.ha
TIMEZONE=America/Los_Angeles
ENTRIES
  install_date_stub "${bin_dir}" "$(zone_marks America/Los_Angeles)"

  output="$(run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1)"
  assert_contains "${output}" "addon.weather.ha.enabled=1" \
    "the add-on is asked again after a request that was cut off" || return 1
  assert_contains "${output}" "addon.weather.ha.enable_attempted=1" \
    "the enable attempt is recorded" || return 1
  assert_not_contains "${output}" "addon_enable_unresolved=weather.ha" \
    "an add-on that did settle is not reported unresolved" || return 1
  calls="$(cat "${dir}/stub/call-count")"
  if (( calls > 24 )); then
    printf 'the probe made %s JSON-RPC calls to settle one add-on\n' "${calls}" >&2
    return 1
  fi
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

# --- Arctic Fuse integration verification ----------------------------------

# Runs run_verify with both ratings keys set, which is the production baseline.
run_verify_with_keys() {
  local config="$1" observations="$2" manifest="$3"
  HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=1234 PLEX_TOKEN=plex-token \
    OMDB_API_KEY=omdb-key MDBLIST_API_KEY=mdblist-key \
    run_verify "${config}" "${observations}" "${manifest}"
}

# --- Arctic Fuse probe fixture helpers --------------------------------------

# Creates a fixture root with valid Arctic Fuse skin settings, home widgets
# JSON, power menu JSON, and all six smart playlists. Returns the storage root.
# Extends make_probe_fixture_root with the managed skin files the probe reads.
make_arctic_fuse_fixture_root() {
  local dir="$1" root
  root="$(make_probe_fixture_root "${dir}")"
  local userdata="${root}/.kodi/userdata"
  local skin_dir="${userdata}/addon_data/skin.arctic.fuse.3"
  local nodes_dir="${userdata}/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
  local playlists_dir="${userdata}/playlists/video"
  mkdir -p "${skin_dir}" "${nodes_dir}" "${playlists_dir}"
  local current_year
  current_year="$(python3 -c 'import datetime; print(datetime.date.today().year)')"

  # Valid skin settings XML
  cat > "${skin_dir}/settings.xml" <<'XML'
<settings>
    <setting id="HomeSwitcher.1101.Name">Plex</setting>
    <setting id="HomeSwitcher.1101.Toggle">true</setting>
    <setting id="HomeSwitcher.1101.Icon">special://home/addons/script.plexmod/icon2.png</setting>
    <setting id="HomeSwitcher.1101.Shortcut.Path">RunAddon(script.plexmod)</setting>
    <setting id="HomeSwitcher.1102.Name">YouTube</setting>
    <setting id="HomeSwitcher.1102.Toggle">true</setting>
    <setting id="HomeSwitcher.1102.Icon">special://home/addons/plugin.video.youtube/resources/media/icon.png</setting>
    <setting id="HomeSwitcher.1102.Shortcut.Path">plugin://plugin.video.youtube/</setting>
    <setting id="HomeSwitcher.1102.Shortcut.Target">videos</setting>
    <setting id="HomeSwitcher.1107.Toggle">true</setting>
    <setting id="HomeSwitcher.1108.Toggle">true</setting>
    <setting id="optionstiles.02.include">Settings</setting>
</settings>
XML

  # Valid home widgets JSON
  cat > "${nodes_dir}/skinvariables-shortcut-homewidgets.json" <<'JSON'
[{"guid": "coreelec-home-inprogress-movies", "icon": "", "label": "In-Progress Movies", "path": "special://profile/playlists/video/InProgressMovies90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-inprogress-shows", "icon": "", "label": "In-Progress Shows", "path": "special://profile/playlists/video/InProgressShows90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-aired-shows", "icon": "", "label": "Recently Aired Shows", "path": "special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-released-movies", "icon": "", "label": "Recently Released Movies", "path": "special://profile/playlists/video/RecentlyReleasedMoviesCurrentYear.xsp", "target": "videos"}, {"guid": "coreelec-home-new-shows", "icon": "", "label": "New Shows", "path": "special://profile/playlists/video/NewShows.xsp", "target": "videos"}, {"guid": "coreelec-home-new-movies", "icon": "", "label": "New Movies", "path": "special://profile/playlists/video/NewMovies.xsp", "target": "videos"}]
JSON

  # Valid power menu JSON
  cat > "${nodes_dir}/skinvariables-shortcut-powermenu.json" <<'JSON'
[{"guid": "coreelec-power-poweroff", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13016]", "path": "Powerdown()", "target": ""}, {"guid": "coreelec-power-timer", "icon": "special://skin/extras/icons/timer.png", "label": "$LOCALIZE[20150]", "path": "AlarmClock(shutdowntimer,Shutdown())", "target": ""}, {"guid": "coreelec-power-suspend", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13011]", "path": "Suspend()", "target": ""}, {"guid": "coreelec-power-reboot", "icon": "special://skin/extras/icons/refresh.png", "label": "$LOCALIZE[13013]", "path": "Reset()", "target": ""}, {"guid": "coreelec-power-restart-kodi", "icon": "special://skin/extras/icons/refresh.png", "label": "Restart Kodi", "path": "RestartApp()", "target": ""}]
JSON

  # Valid smart playlists
  write_fixture_xsp "${playlists_dir}/InProgressMovies90Days.xsp" movies \
    "In-Progress Movies" "all" 50 "lastplayed" "descending" \
    "inprogress|true|" "lastplayed|inthelast|90 days"
  write_fixture_xsp "${playlists_dir}/InProgressShows90Days.xsp" tvshows \
    "In-Progress Shows" "all" 50 "lastplayed" "descending" \
    "inprogress|true|" "lastplayed|inthelast|90 days"
  write_fixture_xsp "${playlists_dir}/RecentlyAiredEpisodes30Days.xsp" episodes \
    "Recently Aired Shows" "all" 50 "year" "descending" \
    "airdate|inthelast|30 days" "airdate|notinthelast|-1 days"
  write_fixture_xsp "${playlists_dir}/RecentlyReleasedMoviesCurrentYear.xsp" movies \
    "Recently Released Movies" "all" 50 "year" "descending" \
    "year|is|${current_year}"
  write_fixture_xsp "${playlists_dir}/NewShows.xsp" tvshows \
    "New Shows" "all" 50 "dateadded" "descending" \
    "playcount|is|0"
  write_fixture_xsp "${playlists_dir}/NewMovies.xsp" movies \
    "New Movies" "all" 50 "dateadded" "descending" \
    "playcount|is|0"

  printf '%s\n' "${root}"
}

# Writes a valid .xsp smart playlist file. Rules are passed as trailing args
# in field|operator|value format.
write_fixture_xsp() {
  local path="$1" type="$2" name="$3" match="$4" limit="$5"
  local order_field="$6" order_dir="$7"
  shift 7
  {
    printf '<?xml version="1.0" encoding="UTF-8"?>\n'
    printf '<smartplaylist type="%s">\n' "${type}"
    printf '    <name>%s</name>\n' "${name}"
    printf '    <match>%s</match>\n' "${match}"
    local rule_spec field operator value
    for rule_spec in "$@"; do
      IFS='|' read -r field operator value <<< "${rule_spec}"
      printf '    <rule field="%s" operator="%s">' "${field}" "${operator}"
      if [[ -n "${value}" ]]; then
        printf '<value>%s</value>' "${value}"
      fi
      printf '</rule>\n'
    done
    printf '    <limit>%s</limit>\n' "${limit}"
    printf '    <order direction="%s">%s</order>\n' "${order_dir}" "${order_field}"
    printf '</smartplaylist>\n'
  } > "${path}"
}

# Runs the probe with the Arctic Fuse request parameters.
run_arctic_fuse_probe() {
  local dir="$1" bin_dir="$2" root="$3"
  local request="${dir}/request.conf"
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
  run_remote_probe "${dir}" "${bin_dir}" "${root}" "${request}" 2>&1
}

# --- Arctic Fuse probe fixture tests ----------------------------------------

test_probe_arctic_fuse_valid_baseline_emits_all_ones() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=1" "hubs ok" || return 1
  assert_contains "${output}" "arctic_fuse.plex_entry_configured=1" "plex ok" || return 1
  assert_contains "${output}" "arctic_fuse.youtube_entry_configured=1" "youtube ok" || return 1
  assert_contains "${output}" "arctic_fuse.settings_tile_configured=1" "settings tile ok" || return 1
  assert_contains "${output}" "arctic_fuse.home_widgets_configured=1" "home widgets ok" || return 1
  assert_contains "${output}" "arctic_fuse.power_menu_configured=1" "power menu ok" || return 1
  assert_contains "${output}" "arctic_fuse.playlist.InProgressMovies90Days.configured=1" "playlist 1" || return 1
  assert_contains "${output}" "arctic_fuse.playlist.NewMovies.configured=1" "playlist 6" || return 1
  assert_contains "${output}" "arctic_fuse.playlist.RecentlyReleasedMoviesCurrentYear.configured=1" \
    "current year movie playlist ok" || return 1
  assert_contains "${output}" "arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent=1" \
    "obsolete playlist absent" || return 1
}

test_probe_missing_skin_settings_emits_zero() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  rm "${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" "hubs 0 when settings missing" || return 1
  assert_contains "${output}" "arctic_fuse.plex_entry_configured=0" "plex 0" || return 1
  assert_contains "${output}" "arctic_fuse.settings_tile_configured=0" "settings tile 0" || return 1
}

test_probe_malformed_skin_xml_emits_zero() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  printf 'NOT VALID XML <<<>>>' > \
    "${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" "malformed XML → hubs 0" || return 1
  assert_contains "${output}" "arctic_fuse.plex_entry_configured=0" "malformed XML → plex 0" || return 1
}

test_probe_enabled_next_aired_toggle_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "HomeSwitcher.1106.Toggle", "type": "bool"},
).text = "true"
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "enabled Next Aired toggle → hubs 0" || return 1
}

# Arctic Fuse renders a hub whenever Skin.String(HomeSwitcher.1106.Toggle) is
# non-empty, so the literal string "false" still shows Next Aired.
test_probe_false_next_aired_toggle_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "HomeSwitcher.1106.Toggle", "type": "string"},
).text = "false"
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "non-empty false Next Aired toggle → hubs 0" || return 1
}

test_probe_bool_false_next_aired_toggle_emits_one() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "homeswitcher.1106.toggle", "type": "bool"},
).text = "false"
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "HomeSwitcher.1106.Toggle", "type": "string"},
)
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=1" \
    "bool-false and empty string Next Aired placeholders → hubs 1" || return 1
}

test_probe_empty_next_aired_toggle_placeholder_emits_one() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "homeswitcher.1106.toggle", "type": "string"},
)
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=1" \
    "empty Next Aired toggle placeholder → hubs 1" || return 1
}

test_probe_empty_next_aired_toggle_does_not_mask_stale_variant() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "homeswitcher.1106.toggle", "type": "string"},
)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "HomeSwitcher.1106.Toggle", "type": "string"},
).text = "disabled"
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "empty toggle cannot mask arbitrary stale case variant → hubs 0" || return 1
}

test_probe_duplicate_next_aired_toggle_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "HomeSwitcher.1106.Toggle", "type": "string"},
).text = "true"
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "homeswitcher.1106.toggle", "type": "bool"},
).text = "true"
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "duplicate Next Aired toggle → hubs 0" || return 1
}

test_probe_stale_next_aired_mode_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "HomeSwitcher.1106.UpNextMode"},
).text = "library_nextaired"
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "stale Next Aired mode → hubs 0" || return 1
}

test_probe_empty_next_aired_mode_placeholder_emits_one() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "homeswitcher.1106.UpNextMode", "type": "string"},
)
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=1" \
    "empty Next Aired mode placeholder → hubs 1" || return 1
}

test_probe_bool_empty_next_aired_mode_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "homeswitcher.1106.upnextmode", "type": "bool"},
)
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "bool-typed empty Next Aired mode → hubs 0" || return 1
}

test_probe_empty_next_aired_mode_does_not_mask_stale_variant() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  python3 - "${skin_file}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "HomeSwitcher.1106.UpNextMode", "type": "string"},
)
ET.SubElement(
    tree.getroot(),
    "setting",
    {"id": "homeswitcher.1106.upnextmode", "type": "string"},
).text = "library_nextaired"
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "empty mode cannot mask stale case variant → hubs 0" || return 1
}

# --- Managed skin settings: case-insensitive exact state --------------------

# Kodi resolves `Skin.String` without regard to case, so any case variant of a
# managed ID is a real value the skin may resolve. These helpers seed one.

# Appends one <setting> node as a direct child of the settings root.
append_skin_setting_node() {
  local skin_file="$1" setting_id="$2" setting_type="$3" value="$4"
  python3 - "${skin_file}" "${setting_id}" "${setting_type}" "${value}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path, setting_id, setting_type, value = sys.argv[1:5]
tree = ET.parse(path)
attributes = {"id": setting_id}
if setting_type:
    attributes["type"] = setting_type
node = ET.SubElement(tree.getroot(), "setting", attributes)
if value:
    node.text = value
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
}

# Moves one managed setting out of the root and into a <category>, which Kodi
# never reads even though a recursive reader still finds it.
nest_skin_setting_in_category() {
  local skin_file="$1" setting_id="$2"
  python3 - "${skin_file}" "${setting_id}" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path, setting_id = sys.argv[1], sys.argv[2]
tree = ET.parse(path)
root = tree.getroot()
category = ET.SubElement(root, "category", {"id": "hubs"})
for node in list(root.findall("setting")):
    if (node.get("id") or "").casefold() == setting_id.casefold():
        root.remove(node)
        category.append(node)
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
}

test_probe_case_variant_pvr_toggle_duplicate_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  # A lowercase duplicate that reads as an unset hub: Kodi may resolve it
  # instead of the managed node, so the PVR hub would silently disappear.
  append_skin_setting_node "${skin_file}" "homeswitcher.1107.toggle" "string" ""

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.pvr_hub_configured=0" \
    "a case-variant PVR toggle duplicate → pvr hub 0" || return 1
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "a case-variant PVR toggle duplicate → hubs 0" || return 1
}

test_probe_case_variant_addons_toggle_duplicate_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  append_skin_setting_node "${skin_file}" "HOMESWITCHER.1108.TOGGLE" "string" "false"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.addons_hub_configured=0" \
    "a case-variant Add-ons toggle duplicate → add-ons hub 0" || return 1
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "a case-variant Add-ons toggle duplicate → hubs 0" || return 1
}

test_probe_case_variant_plex_shortcut_duplicate_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  append_skin_setting_node "${skin_file}" "homeswitcher.1101.shortcut.path" \
    "string" "RunAddon(plugin.video.other)"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.plex_entry_configured=0" \
    "a case-variant Plex shortcut duplicate → plex entry 0" || return 1
}

test_probe_case_variant_stale_plex_shortcut_target_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  # The managed state removes this setting; a case variant is the same
  # functional value to Kodi and must not pass unnoticed.
  append_skin_setting_node "${skin_file}" "homeswitcher.1101.shortcut.target" \
    "string" "videos"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.plex_entry_configured=0" \
    "a case-variant stale Plex shortcut target → plex entry 0" || return 1
}

test_probe_case_variant_youtube_name_duplicate_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  append_skin_setting_node "${skin_file}" "homeswitcher.1102.name" "string" \
    "YouTube Kids"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.youtube_entry_configured=0" \
    "a case-variant YouTube name duplicate → youtube entry 0" || return 1
}

test_probe_case_variant_settings_tile_duplicate_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  append_skin_setting_node "${skin_file}" "OptionsTiles.02.Include" "string" "Power"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.settings_tile_configured=0" \
    "a case-variant settings tile duplicate → settings tile 0" || return 1
}

# A managed value that only exists inside a <category> is never read by Kodi,
# so recursive verification must not report it as configured.
test_probe_managed_setting_only_inside_a_category_emits_zero() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  nest_skin_setting_in_category "${skin_file}" "HomeSwitcher.1107.Toggle"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.pvr_hub_configured=0" \
    "a managed toggle Kodi cannot read → pvr hub 0" || return 1
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "a managed toggle Kodi cannot read → hubs 0" || return 1
}

# The aggregate hub verdict says only that something is wrong; the split
# observations say which hub, so an operator reads the cause from the report.
test_probe_reports_each_hub_observation_independently() {
  local dir root bin_dir output skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  skin_file="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.next_aired_disabled=1" \
    "baseline Next Aired is disabled" || return 1
  assert_contains "${output}" "arctic_fuse.pvr_hub_configured=1" \
    "baseline PVR hub is enabled" || return 1
  assert_contains "${output}" "arctic_fuse.addons_hub_configured=1" \
    "baseline Add-ons hub is enabled" || return 1
  assert_contains "${output}" "arctic_fuse.hubs_configured=1" \
    "baseline aggregate hub verdict" || return 1

  # Only Next Aired is wrong: the two enabled hubs still report separately.
  append_skin_setting_node "${skin_file}" "HomeSwitcher.1106.Toggle" "string" "true"
  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.next_aired_disabled=0" \
    "a rendered Next Aired hub is named on its own line" || return 1
  assert_contains "${output}" "arctic_fuse.pvr_hub_configured=1" \
    "PVR stays ok while Next Aired fails" || return 1
  assert_contains "${output}" "arctic_fuse.addons_hub_configured=1" \
    "Add-ons stays ok while Next Aired fails" || return 1
  assert_contains "${output}" "arctic_fuse.hubs_configured=0" \
    "the aggregate hub verdict still fails" || return 1
}

test_probe_malformed_json_emits_zero_for_home_widgets() {
  local dir root bin_dir output nodes_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  nodes_dir="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
  printf '{broken json' > "${nodes_dir}/skinvariables-shortcut-homewidgets.json"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.home_widgets_configured=0" \
    "malformed JSON → home widgets 0" || return 1
  # Power menu is unaffected
  assert_contains "${output}" "arctic_fuse.power_menu_configured=1" \
    "power menu still ok" || return 1
}

test_probe_malformed_json_emits_zero_for_power_menu() {
  local dir root bin_dir output nodes_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  nodes_dir="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
  printf 'NOT JSON' > "${nodes_dir}/skinvariables-shortcut-powermenu.json"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.power_menu_configured=0" \
    "malformed JSON → power menu 0" || return 1
}

test_probe_missing_home_widgets_file_emits_zero() {
  local dir root bin_dir output nodes_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  nodes_dir="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
  rm "${nodes_dir}/skinvariables-shortcut-homewidgets.json"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.home_widgets_configured=0" \
    "missing file → home widgets 0" || return 1
}

test_probe_reordered_home_widgets_emits_zero() {
  local dir root bin_dir output nodes_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  nodes_dir="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
  # Swap first two entries
  cat > "${nodes_dir}/skinvariables-shortcut-homewidgets.json" <<'JSON'
[{"guid": "coreelec-home-inprogress-shows", "icon": "", "label": "In-Progress Shows", "path": "special://profile/playlists/video/InProgressShows90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-inprogress-movies", "icon": "", "label": "In-Progress Movies", "path": "special://profile/playlists/video/InProgressMovies90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-aired-shows", "icon": "", "label": "Recently Aired Shows", "path": "special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-released-movies", "icon": "", "label": "Recently Released Movies", "path": "special://profile/playlists/video/RecentlyReleasedMoviesCurrentYear.xsp", "target": "videos"}, {"guid": "coreelec-home-new-shows", "icon": "", "label": "New Shows", "path": "special://profile/playlists/video/NewShows.xsp", "target": "videos"}, {"guid": "coreelec-home-new-movies", "icon": "", "label": "New Movies", "path": "special://profile/playlists/video/NewMovies.xsp", "target": "videos"}]
JSON

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.home_widgets_configured=0" \
    "reordered home widgets → 0" || return 1
}

test_probe_reordered_power_menu_emits_zero() {
  local dir root bin_dir output nodes_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  nodes_dir="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
  # Swap first two entries
  cat > "${nodes_dir}/skinvariables-shortcut-powermenu.json" <<'JSON'
[{"guid": "coreelec-power-timer", "icon": "special://skin/extras/icons/timer.png", "label": "$LOCALIZE[20150]", "path": "AlarmClock(shutdowntimer,Shutdown())", "target": ""}, {"guid": "coreelec-power-poweroff", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13016]", "path": "Powerdown()", "target": ""}, {"guid": "coreelec-power-suspend", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13011]", "path": "Suspend()", "target": ""}, {"guid": "coreelec-power-reboot", "icon": "special://skin/extras/icons/refresh.png", "label": "$LOCALIZE[13013]", "path": "Reset()", "target": ""}, {"guid": "coreelec-power-restart-kodi", "icon": "special://skin/extras/icons/refresh.png", "label": "Restart Kodi", "path": "RestartApp()", "target": ""}]
JSON

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.power_menu_configured=0" \
    "reordered power menu → 0" || return 1
}

test_probe_duplicate_power_menu_entry_emits_zero() {
  local dir root bin_dir output nodes_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  nodes_dir="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
  # Add a duplicate Powerdown entry
  cat > "${nodes_dir}/skinvariables-shortcut-powermenu.json" <<'JSON'
[{"guid": "coreelec-power-poweroff", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13016]", "path": "Powerdown()", "target": ""}, {"guid": "coreelec-power-timer", "icon": "special://skin/extras/icons/timer.png", "label": "$LOCALIZE[20150]", "path": "AlarmClock(shutdowntimer,Shutdown())", "target": ""}, {"guid": "coreelec-power-suspend", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13011]", "path": "Suspend()", "target": ""}, {"guid": "coreelec-power-reboot", "icon": "special://skin/extras/icons/refresh.png", "label": "$LOCALIZE[13013]", "path": "Reset()", "target": ""}, {"guid": "coreelec-power-restart-kodi", "icon": "special://skin/extras/icons/refresh.png", "label": "Restart Kodi", "path": "RestartApp()", "target": ""}, {"guid": "coreelec-power-poweroff", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13016]", "path": "Powerdown()", "target": ""}]
JSON

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.power_menu_configured=0" \
    "duplicate entry → 0" || return 1
}

test_probe_unexpected_home_widget_entry_emits_zero() {
  local dir root bin_dir output nodes_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  nodes_dir="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3"
  # Add an unexpected 7th entry
  cat > "${nodes_dir}/skinvariables-shortcut-homewidgets.json" <<'JSON'
[{"guid": "coreelec-home-inprogress-movies", "icon": "", "label": "In-Progress Movies", "path": "special://profile/playlists/video/InProgressMovies90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-inprogress-shows", "icon": "", "label": "In-Progress Shows", "path": "special://profile/playlists/video/InProgressShows90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-aired-shows", "icon": "", "label": "Recently Aired Shows", "path": "special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-released-movies", "icon": "", "label": "Recently Released Movies", "path": "special://profile/playlists/video/RecentlyReleasedMoviesCurrentYear.xsp", "target": "videos"}, {"guid": "coreelec-home-new-shows", "icon": "", "label": "New Shows", "path": "special://profile/playlists/video/NewShows.xsp", "target": "videos"}, {"guid": "coreelec-home-new-movies", "icon": "", "label": "New Movies", "path": "special://profile/playlists/video/NewMovies.xsp", "target": "videos"}, {"guid": "coreelec-home-unexpected", "icon": "", "label": "Unexpected", "path": "special://profile/playlists/video/Unexpected.xsp", "target": "videos"}]
JSON

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.home_widgets_configured=0" \
    "unexpected entry → 0" || return 1
}

test_probe_missing_playlist_file_emits_zero() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  rm "${root}/.kodi/userdata/playlists/video/NewMovies.xsp"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.playlist.NewMovies.configured=0" \
    "missing playlist → 0" || return 1
  # Other playlists still pass
  assert_contains "${output}" "arctic_fuse.playlist.InProgressMovies90Days.configured=1" \
    "unaffected playlist still 1" || return 1
}

test_probe_malformed_playlist_xml_emits_zero() {
  local dir root bin_dir output
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  printf 'NOT VALID XML <<<>>>' > \
    "${root}/.kodi/userdata/playlists/video/InProgressShows90Days.xsp"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.playlist.InProgressShows90Days.configured=0" \
    "malformed playlist XML → 0" || return 1
}

test_probe_incorrect_playlist_rule_emits_zero() {
  local dir root bin_dir output playlists_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  playlists_dir="${root}/.kodi/userdata/playlists/video"
  # Replace with old-style firstaired rules (probe now expects airdate)
  write_fixture_xsp "${playlists_dir}/RecentlyAiredEpisodes30Days.xsp" episodes \
    "Recently Aired Shows" "all" 50 "firstaired" "descending" \
    "firstaired|inthelast|30 days" "firstaired|before|tomorrow"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.playlist.RecentlyAiredEpisodes30Days.configured=0" \
    "old-style firstaired rules → 0" || return 1
}

test_probe_previous_year_movie_playlist_emits_zero() {
  local dir root bin_dir output playlists_dir current_year
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  playlists_dir="${root}/.kodi/userdata/playlists/video"
  current_year="$(python3 -c 'import datetime; print(datetime.date.today().year)')"
  # Overwrite with previous year's rule value
  write_fixture_xsp "${playlists_dir}/RecentlyReleasedMoviesCurrentYear.xsp" movies \
    "Recently Released Movies" "all" 50 "year" "descending" \
    "year|is|$((current_year - 1))"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.playlist.RecentlyReleasedMoviesCurrentYear.configured=0" \
    "previous year rule → 0" || return 1
}

test_probe_obsolete_movie_playlist_emits_absent_zero() {
  local dir root bin_dir output playlists_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  root="$(make_arctic_fuse_fixture_root "${dir}")"
  bin_dir="$(install_jsonrpc_curl_stub "${dir}")"
  playlists_dir="${root}/.kodi/userdata/playlists/video"
  # Introduce the obsolete file that migration should have removed
  printf '<?xml version="1.0" encoding="UTF-8"?>\n<smartplaylist type="movies"><name>old</name></smartplaylist>\n' \
    > "${playlists_dir}/RecentlyReleasedMovies90Days.xsp"

  output="$(run_arctic_fuse_probe "${dir}" "${bin_dir}" "${root}")"
  assert_contains "${output}" "arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent=0" \
    "obsolete playlist present → absent=0" || return 1
}

# --- Arctic Fuse comparator tests ------------------------------------------

test_arctic_fuse_complete_state_verifies() {
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
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "complete Arctic Fuse state must verify" || return 1
  assert_contains "${output}" "verification_result=pass" "result line present" || return 1
  assert_contains "${output}" "arctic_fuse.status=ok" "arctic fuse overall status" || return 1
  assert_contains "${output}" "arctic_fuse.home.status=ok" "home status" || return 1
  assert_contains "${output}" "arctic_fuse.power.status=ok" "power status" || return 1
  assert_contains "${output}" "arctic_fuse.plex_entry.status=ok" "plex entry status" || return 1
  assert_contains "${output}" "arctic_fuse.youtube_entry.status=ok" "youtube entry status" || return 1
  assert_contains "${output}" "metadata.omdb.status=ok" "omdb status" || return 1
  assert_contains "${output}" "metadata.mdblist.status=ok" "mdblist status" || return 1
}

test_comparator_home_widgets_zero_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.home_widgets_configured" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a home widgets 0 must fail verification" || return 1
  assert_contains "${output}" "verification_result=fail" "overall result fails" || return 1
}

test_comparator_power_menu_zero_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.power_menu_configured" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a power menu 0 must fail verification" || return 1
  assert_contains "${output}" "verification_result=fail" "overall result fails" || return 1
}

test_arctic_fuse_hub_mismatch_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.hubs_configured" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a hub mismatch must fail verification" || return 1
  assert_contains "${output}" "verification_result=fail" "overall result fails" || return 1
  assert_contains "${output}" "arctic_fuse.hubs" "the mismatching surface is named" || return 1
}

# The split hub observations must reach the report as their own statuses, so
# the operator reads which hub failed rather than only that "hubs" failed.
test_arctic_fuse_split_hub_statuses_name_the_failing_hub() {
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
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a complete hub state verifies" || return 1
  assert_contains "${output}" "arctic_fuse.next_aired_hub.status=ok" \
    "the Next Aired hub has its own status" || return 1
  assert_contains "${output}" "arctic_fuse.pvr_hub.status=ok" \
    "the PVR hub has its own status" || return 1
  assert_contains "${output}" "arctic_fuse.addons_hub.status=ok" \
    "the Add-ons hub has its own status" || return 1

  set_observation "${observations}" "arctic_fuse.pvr_hub_configured" "0"
  set_observation "${observations}" "arctic_fuse.hubs_configured" "0"
  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a PVR hub mismatch must fail verification" || return 1
  assert_contains "${output}" "arctic_fuse.pvr_hub.status=mismatch" \
    "the PVR hub is identified as the failure" || return 1
  assert_contains "${output}" "arctic_fuse.next_aired_hub.status=ok" \
    "Next Aired stays ok while PVR fails" || return 1
  assert_contains "${output}" "arctic_fuse.addons_hub.status=ok" \
    "Add-ons stays ok while PVR fails" || return 1
  assert_contains "${output}" "arctic_fuse.status=mismatch" \
    "the aggregate Arctic Fuse outcome stays fatal" || return 1
}

test_arctic_fuse_plex_entry_mismatch_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.plex_entry_configured" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a Plex entry mismatch must fail verification" || return 1
  assert_contains "${output}" "arctic_fuse.plex_entry.status=mismatch" "plex entry mismatch" || return 1
}

test_arctic_fuse_youtube_entry_mismatch_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.youtube_entry_configured" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a YouTube entry mismatch must fail verification" || return 1
  assert_contains "${output}" "arctic_fuse.youtube_entry.status=mismatch" "youtube entry mismatch" || return 1
}

test_arctic_fuse_home_widget_order_mismatch_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.home_widgets_configured" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a home widget order mismatch must fail verification" || return 1
  assert_contains "${output}" "arctic_fuse.home" "home surface named" || return 1
}

test_comparator_settings_tile_zero_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.settings_tile_configured" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a settings tile 0 must fail verification" || return 1
  assert_contains "${output}" "verification_result=fail" "overall result fails" || return 1
}

test_arctic_fuse_power_action_mismatch_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.power_menu_configured" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a power action mismatch must fail verification" || return 1
  assert_contains "${output}" "arctic_fuse.power.status=mismatch" "power mismatch" || return 1
}

test_arctic_fuse_playlist_rule_mismatch_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.playlist.InProgressMovies90Days.configured" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a playlist rule mismatch must fail verification" || return 1
  assert_contains "${output}" "verification_result=fail" "overall result fails" || return 1
}

test_comparator_obsolete_playlist_present_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"
  set_observation "${observations}" "arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent" "0"

  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an obsolete playlist still present must fail verification" || return 1
  assert_contains "${output}" "verification_result=fail" "overall result fails" || return 1
  assert_contains "${output}" "arctic_fuse.playlist_migration" "migration surface named" || return 1
}

test_arctic_fuse_optional_addon_version_or_enabled_mismatch_fails_verification() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  # Version mismatch subcase
  set_observation "${observations}" "addon.script.artistslideshow.version" "4.1.0"
  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a version mismatch for an optional addon must fail" || return 1
  assert_contains "${output}" "addon.script.artistslideshow.verification=mismatch" \
    "version mismatch is fatal" || return 1

  # Enabled mismatch subcase
  write_pass_observations "${observations}"
  set_observation "${observations}" "addon.resource.images.arctic.waves.enabled" "0"
  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a disabled optional addon must fail" || return 1
  assert_contains "${output}" "addon.resource.images.arctic.waves.verification=mismatch" \
    "enabled mismatch is fatal" || return 1
}

test_each_ratings_key_presence_is_verified_separately() {
  local dir config manifest observations output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  # Only OMDb missing
  set_observation "${observations}" "addon_settings.plugin.video.themoviedb.helper.omdb_configured" "0"
  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "missing OMDb key must fail" || return 1
  assert_contains "${output}" "metadata.omdb.status=mismatch" "omdb mismatch" || return 1
  assert_contains "${output}" "metadata.mdblist.status=ok" "mdblist still ok" || return 1

  # Only MDbList missing
  write_pass_observations "${observations}"
  set_observation "${observations}" "addon_settings.plugin.video.themoviedb.helper.mdblist_configured" "0"
  set +e
  output="$(run_verify_with_keys "${config}" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "missing MDbList key must fail" || return 1
  assert_contains "${output}" "metadata.mdblist.status=mismatch" "mdblist mismatch" || return 1
  assert_contains "${output}" "metadata.omdb.status=ok" "omdb still ok" || return 1
}

# --- Report content for Arctic Fuse surfaces --------------------------------

test_report_names_every_arctic_fuse_surface() {
  local dir config manifest observations report
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  manifest="${dir}/deploy.tsv"
  observations="${dir}/observations.conf"
  write_configured_config "${config}"
  write_manifest "${manifest}"
  write_pass_observations "${observations}"

  report="$(HOME_ASSISTANT_TOKEN=ha-token NEXTPVR_PIN=1234 PLEX_TOKEN=plex-token \
    OMDB_API_KEY=omdb-key MDBLIST_API_KEY=mdblist-key \
    run_report "${config}" "${dir}/out" "${observations}" "${manifest}")"
  [[ -f "${report}" ]] || { printf 'no report\n' >&2; return 1; }
  assert_contains "$(cat "${report}")" "arctic_fuse.status=ok" "arctic fuse status" || return 1
  assert_contains "$(cat "${report}")" "arctic_fuse.home.status=ok" "home status" || return 1
  assert_contains "$(cat "${report}")" "arctic_fuse.power.status=ok" "power status" || return 1
  assert_contains "$(cat "${report}")" "arctic_fuse.plex_entry.status=ok" "plex entry" || return 1
  assert_contains "$(cat "${report}")" "arctic_fuse.youtube_entry.status=ok" "youtube entry" || return 1
  assert_contains "$(cat "${report}")" "metadata.omdb.status=ok" "omdb" || return 1
  assert_contains "$(cat "${report}")" "metadata.mdblist.status=ok" "mdblist" || return 1
}

test_report_never_contains_ratings_key_values_or_managed_file_contents() {
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
    OMDB_API_KEY=omdb-report-secret MDBLIST_API_KEY=mdblist-report-secret \
    run_report "${config}" "${dir}/out" "${observations}" "${manifest}" 2>&1)"
  rc=$?
  set -e
  assert_not_contains "${output}" "omdb-report-secret" "no OMDb key literal" || return 1
  assert_not_contains "${output}" "mdblist-report-secret" "no MDbList key literal" || return 1
}

test_tmdb_helper_is_always_classified_configured_for_a_real_skin_deployment() {
  local dir config
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  config="${dir}/provision.conf"
  write_configured_config "${config}"

  assert_eq "configured" \
    "$(OMDB_API_KEY=omdb MDBLIST_API_KEY=mdblist \
       run_classify "${config}" plugin.video.themoviedb.helper)" \
    "TMDb Helper with both keys is configured" || return 1
}

run_all_tests \
  test_all_expected_addon_versions_are_verified \
  test_disabled_addon_is_failure \
  test_unresolved_enables_are_named_in_the_report \
  test_a_settled_run_reports_no_unresolved_enables \
  test_missing_addon_is_failure \
  test_addon_version_mismatch_is_failure \
  test_active_skin_is_verified \
  test_weather_provider_is_verified_only_when_configured \
  test_timezone_cache_and_zoneinfo_are_verified \
  test_cec_ignore_mismatch_fails_verification \
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
  test_audit_report_records_cec_ignore_without_adapter_filename \
  test_report_redacts_all_supplied_secret_values \
  test_report_records_config_fingerprint_without_secrets \
  test_report_lists_manual_actions_in_order \
  test_ratings_key_isolation_restores_the_environment \
  test_report_states_addon_status_and_verification_per_addon \
  test_report_keeps_subset_dependency_warning_explicit \
  test_report_is_strict_key_value \
  test_local_jsonrpc_unreachability_is_environmental_only \
  test_report_fingerprint_tool_is_required_even_without_kodi \
  test_verification_success_finalizes_and_commits \
  test_verification_mismatch_is_fatal \
  test_cec_ignore_mismatch_triggers_rollback \
  test_incomplete_rollback_is_fatal_with_recovery_path \
  test_an_unanswered_probe_is_a_verification_failure \
  test_failed_finalize_is_fatal \
  test_remote_verify_script_passes_shell_syntax_check \
  test_remote_verify_probe_reports_state_without_secrets \
  test_remote_probe_reports_cec_ignore \
  test_remote_verify_probe_compares_a_copied_localtime_by_content \
  test_remote_verify_probe_judges_device_date_against_the_requested_zone \
  test_remote_verify_probe_fails_immediately_when_curl_is_missing \
  test_remote_verify_probe_enables_a_disabled_addon_over_jsonrpc \
  test_remote_verify_probe_converges_on_dependency_ordered_enables \
  test_remote_verify_probe_fails_closed_on_an_addon_it_cannot_enable \
  test_remote_verify_probe_keeps_going_when_an_enable_request_is_cut_off \
  test_remote_verify_probe_reports_a_missing_addon \
  test_remote_verify_probe_uses_a_private_curl_config_and_removes_it \
  test_probe_arctic_fuse_valid_baseline_emits_all_ones \
  test_probe_missing_skin_settings_emits_zero \
  test_probe_malformed_skin_xml_emits_zero \
  test_probe_enabled_next_aired_toggle_emits_zero \
  test_probe_false_next_aired_toggle_emits_zero \
  test_probe_bool_false_next_aired_toggle_emits_one \
  test_probe_empty_next_aired_toggle_placeholder_emits_one \
  test_probe_empty_next_aired_toggle_does_not_mask_stale_variant \
  test_probe_duplicate_next_aired_toggle_emits_zero \
  test_probe_stale_next_aired_mode_emits_zero \
  test_probe_empty_next_aired_mode_placeholder_emits_one \
  test_probe_bool_empty_next_aired_mode_emits_zero \
  test_probe_empty_next_aired_mode_does_not_mask_stale_variant \
  test_probe_case_variant_pvr_toggle_duplicate_emits_zero \
  test_probe_case_variant_addons_toggle_duplicate_emits_zero \
  test_probe_case_variant_plex_shortcut_duplicate_emits_zero \
  test_probe_case_variant_stale_plex_shortcut_target_emits_zero \
  test_probe_case_variant_youtube_name_duplicate_emits_zero \
  test_probe_case_variant_settings_tile_duplicate_emits_zero \
  test_probe_managed_setting_only_inside_a_category_emits_zero \
  test_probe_reports_each_hub_observation_independently \
  test_probe_malformed_json_emits_zero_for_home_widgets \
  test_probe_malformed_json_emits_zero_for_power_menu \
  test_probe_missing_home_widgets_file_emits_zero \
  test_probe_reordered_home_widgets_emits_zero \
  test_probe_reordered_power_menu_emits_zero \
  test_probe_duplicate_power_menu_entry_emits_zero \
  test_probe_unexpected_home_widget_entry_emits_zero \
  test_probe_missing_playlist_file_emits_zero \
  test_probe_malformed_playlist_xml_emits_zero \
  test_probe_incorrect_playlist_rule_emits_zero \
  test_probe_previous_year_movie_playlist_emits_zero \
  test_probe_obsolete_movie_playlist_emits_absent_zero \
  test_arctic_fuse_complete_state_verifies \
  test_comparator_home_widgets_zero_fails_verification \
  test_comparator_power_menu_zero_fails_verification \
  test_arctic_fuse_hub_mismatch_fails_verification \
  test_arctic_fuse_split_hub_statuses_name_the_failing_hub \
  test_arctic_fuse_plex_entry_mismatch_fails_verification \
  test_arctic_fuse_youtube_entry_mismatch_fails_verification \
  test_arctic_fuse_home_widget_order_mismatch_fails_verification \
  test_comparator_settings_tile_zero_fails_verification \
  test_arctic_fuse_power_action_mismatch_fails_verification \
  test_arctic_fuse_playlist_rule_mismatch_fails_verification \
  test_comparator_obsolete_playlist_present_fails_verification \
  test_arctic_fuse_optional_addon_version_or_enabled_mismatch_fails_verification \
  test_each_ratings_key_presence_is_verified_separately \
  test_report_names_every_arctic_fuse_surface \
  test_report_never_contains_ratings_key_values_or_managed_file_contents \
  test_tmdb_helper_is_always_classified_configured_for_a_real_skin_deployment
