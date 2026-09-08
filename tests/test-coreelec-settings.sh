#!/bin/bash

# Tests for the idempotent Kodi and add-on settings transformer.
#
# The transformer normally runs on the CoreELEC device against /storage. It is
# exercised here through provision-coreelec.sh's internal
# `--transform-fixture ROOT PAYLOAD` mode, which runs the exact same Python
# program against a scratch directory. Assertions compare parsed XML/JSON
# values rather than formatting, except where byte-for-byte stability is the
# property under test.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"

PROVISIONER="${SCRIPT_DIR}/../provision-coreelec.sh"

# --- Fixture helpers -------------------------------------------------------

run_transform() {
  local root="$1" payload="$2"
  bash "${PROVISIONER}" --transform-fixture "${root}" "${payload}"
}

# Appends one KEY=VALUE payload entry, base64-encoding the value exactly the
# way provision-coreelec.sh does before transport.
append_payload_entry() {
  local file="$1" key="$2" value="$3"
  printf '%s=%s\n' "${key}" "$(printf '%s' "${value}" | openssl base64 -A)" >> "${file}"
}

# Reads KEY=VALUE lines from stdin and writes an encoded payload file.
write_payload() {
  local file="$1" line key value
  : > "${file}"
  chmod 600 "${file}"
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    append_payload_entry "${file}" "${key}" "${value}"
  done
}

# The non-secret regional baseline every run receives from the config file.
write_base_payload() {
  write_payload "$1" <<'ENTRIES'
TIMEZONE=America/Los_Angeles
TIMEZONE_COUNTRY=United States
LOCALE_LANGUAGE=resource.language.en_us
LOCALE_COUNTRY=USA (12h)
KEYBOARD_LAYOUT=English QWERTY
ADDON_UPDATE_MODE=notify
ENTRIES
}

# Every managed value present, so each optional branch of the transformer runs.
write_full_payload() {
  write_payload "$1" <<'ENTRIES'
TIMEZONE=America/Los_Angeles
TIMEZONE_COUNTRY=United States
LOCALE_LANGUAGE=resource.language.en_us
LOCALE_COUNTRY=USA (12h)
KEYBOARD_LAYOUT=English QWERTY
ADDON_UPDATE_MODE=notify
KODI_WEB_USER=homeassistant
KODI_WEB_PORT=8080
KODI_WEB_PASSWORD=kodi-web-password-secret
HAVE_KODI_WEB_PASSWORD=1
OMDB_API_KEY=omdb-api-key-secret
HAVE_OMDB_API_KEY=1
MDBLIST_API_KEY=mdblist-api-key-secret
HAVE_MDBLIST_API_KEY=1
YOUTUBE_API_KEY=youtube-api-key-secret
HAVE_YOUTUBE_API_KEY=1
YOUTUBE_CLIENT_ID=youtube-client-id-secret.apps.googleusercontent.com
HAVE_YOUTUBE_CLIENT_ID=1
YOUTUBE_CLIENT_SECRET=youtube-client-secret-secret
HAVE_YOUTUBE_CLIENT_SECRET=1
HOME_ASSISTANT_URL=https://homeassistant.example.lan:8123
HOME_ASSISTANT_WEATHER_ENTITY=weather.forecast_home
HOME_ASSISTANT_SUN_ENTITY=sun.sun
HOME_ASSISTANT_TOKEN=home-assistant-token-secret
HAVE_HOME_ASSISTANT_TOKEN=1
NEXTPVR_HOST=nextpvr.example.lan
NEXTPVR_PORT=8866
NEXTPVR_PROTOCOL=http
NEXTPVR_INSTANCE_NAME=Living Room NextPVR
NEXTPVR_PIN=nextpvr-pin-secret
HAVE_NEXTPVR_PIN=1
PLEX_SERVER_HOST=plex.example.lan
PLEX_SERVER_PORT=32400
PLEX_SERVER_NAME=Basement Plex
PLEX_PROFILE_IDS=11,22
PLEX_TOKEN=plex-token-secret
HAVE_PLEX_TOKEN=1
ENTRIES
}

guisettings_path() {
  printf '%s/.kodi/userdata/guisettings.xml' "$1"
}

addon_data_path() {
  printf '%s/.kodi/userdata/addon_data/%s' "$1" "$2"
}

# Prints one setting's effective value, supporting both the current
# `<setting id="x">value</setting>` form and the legacy `value="y"` attribute.
xml_setting() {
  python3 - "$1" "$2" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path, setting_id = sys.argv[1], sys.argv[2]
root = ET.parse(path).getroot()
for node in root.iter("setting"):
    if node.get("id") == setting_id:
        attribute = node.get("value")
        sys.stdout.write(attribute if attribute is not None else (node.text or ""))
        break
else:
    sys.stderr.write("setting not found: %s in %s\n" % (setting_id, path))
    raise SystemExit(3)
PYEOF
}

xml_setting_count() {
  python3 - "$1" "$2" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path, setting_id = sys.argv[1], sys.argv[2]
root = ET.parse(path).getroot()
sys.stdout.write(str(sum(1 for node in root.iter("setting")
                         if node.get("id") == setting_id)))
PYEOF
}

xml_root_attribute() {
  python3 - "$1" "$2" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path, attribute = sys.argv[1], sys.argv[2]
root = ET.parse(path).getroot()
sys.stdout.write(root.get(attribute) or "")
PYEOF
}

# True when the setting node stores its value in a `value` attribute, which is
# what Kodi's old (unversioned) add-on settings format uses.
xml_setting_uses_value_attribute() {
  python3 - "$1" "$2" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path, setting_id = sys.argv[1], sys.argv[2]
root = ET.parse(path).getroot()
for node in root.iter("setting"):
    if node.get("id") == setting_id:
        uses_attribute = (node.get("value") is not None
                          and not (node.text or "").strip())
        sys.stdout.write("yes" if uses_attribute else "no")
        break
else:
    sys.stdout.write("missing")
PYEOF
}

# Walks a JSON document by successive dictionary keys and prints the leaf,
# canonicalized when it is not a plain string.
json_path() {
  local file="$1"
  shift
  python3 - "${file}" "$@" <<'PYEOF'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)
for key in sys.argv[2:]:
    data = data[key]
sys.stdout.write(data if isinstance(data, str)
                 else json.dumps(data, sort_keys=True))
PYEOF
}

canonical_json() {
  python3 -c 'import json,sys; sys.stdout.write(json.dumps(json.load(sys.stdin), sort_keys=True))'
}

# A digest over every file path and its content, used to prove that a second
# run rewrites nothing.
tree_digest() {
  local root="$1" file
  (
    cd "${root}"
    find . -type f | LC_ALL=C sort | while IFS= read -r file; do
      shasum -a 256 "${file}"
    done
  ) | shasum -a 256
}

# Permission bits as an octal string. BSD and GNU `stat` take different
# flags, so the mode is read through python3, which both platforms have.
file_mode() {
  python3 -c 'import os, sys; sys.stdout.write("%o" % (os.stat(sys.argv[1]).st_mode & 0o7777))' "$1"
}

# Every leftover `*.provision-new` file under a root. These are the files that
# briefly hold secrets during an atomic write, so a surviving one is a leak.
orphan_temp_files() {
  find "$1" -name '*.provision-new' | LC_ALL=C sort
}

files_containing() {
  local root="$1" needle="$2"
  grep -rl -- "${needle}" "${root}" 2>/dev/null | LC_ALL=C sort || true
}

seed_guisettings() {
  local root="$1"
  mkdir -p "${root}/.kodi/userdata"
  cat > "$(guisettings_path "${root}")" <<'XML'
<?xml version='1.0' encoding='UTF-8'?>
<settings version="2">
    <setting id="audiooutput.channels">2</setting>
    <setting id="locale.timezone">Europe/Berlin</setting>
    <setting id="locale.timezone">Europe/Paris</setting>
    <setting id="weather.addon">weather.gismeteo</setting>
    <setting id="lookandfeel.skin" default="true">skin.estuary</setting>
</settings>
XML
}

# --- Regional baseline ------------------------------------------------------

test_regional_settings_are_created() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_eq "resource.language.en_us" "$(xml_setting "${settings}" locale.language)" "locale.language"
  assert_eq "USA (12h)" "$(xml_setting "${settings}" locale.country)" "locale.country"
  assert_eq "English QWERTY" "$(xml_setting "${settings}" locale.keyboardlayouts)" "locale.keyboardlayouts"
  assert_eq "United States" "$(xml_setting "${settings}" locale.timezonecountry)" "locale.timezonecountry"
  assert_eq "America/Los_Angeles" "$(xml_setting "${settings}" locale.timezone)" "locale.timezone"
  assert_eq "skin.arctic.fuse.3" "$(xml_setting "${settings}" lookandfeel.skin)" "skin is Arctic Fuse 3"
  assert_eq "1" "$(xml_setting "${settings}" general.addonupdates)" "add-on updates notify only"
  assert_eq "TIMEZONE=America/Los_Angeles" "$(cat "${root}/.cache/timezone")" "timezone cache"
}

test_duplicate_settings_are_collapsed() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  seed_guisettings "${root}"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_eq "1" "$(xml_setting_count "${settings}" locale.timezone)" "one locale.timezone node remains"
  assert_eq "America/Los_Angeles" "$(xml_setting "${settings}" locale.timezone)" "surviving node carries the new value"
  assert_eq "1" "$(xml_setting_count "${settings}" lookandfeel.skin)" "one lookandfeel.skin node remains"
}

test_existing_unmanaged_settings_are_preserved() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  seed_guisettings "${root}"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_eq "2" "$(xml_setting "${settings}" audiooutput.channels)" "unmanaged setting is untouched"
  assert_eq "1" "$(xml_setting_count "${settings}" audiooutput.channels)" "unmanaged setting is not duplicated"
}

test_second_run_is_byte_identical() {
  local dir root payload first second
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  seed_guisettings "${root}"
  write_full_payload "${payload}"

  run_transform "${root}" "${payload}" >/dev/null
  first="$(tree_digest "${root}")"
  run_transform "${root}" "${payload}" >/dev/null
  second="$(tree_digest "${root}")"
  assert_eq "${first}" "${second}" "a second run rewrites nothing"
}

# --- Add-on specific behavior -----------------------------------------------

test_tmdb_helper_keys_go_to_tmdb_helper_only() {
  local dir root payload helper matches
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  helper="$(addon_data_path "${root}" plugin.video.themoviedb.helper)/settings.xml"
  assert_eq "omdb-api-key-secret" "$(xml_setting "${helper}" omdb_apikey)" "OMDb key in TMDb Helper"
  assert_eq "mdblist-api-key-secret" "$(xml_setting "${helper}" mdblist_apikey)" "MDbList key in TMDb Helper"

  matches="$(grep -rl 'omdb-api-key-secret' "${root}" | LC_ALL=C sort | tr '\n' ' ')"
  assert_eq "${helper} " "${matches}" "the OMDb key exists in exactly one file"
  matches="$(grep -rl 'mdblist-api-key-secret' "${root}" | LC_ALL=C sort | tr '\n' ' ')"
  assert_eq "${helper} " "${matches}" "the MDbList key exists in exactly one file"
}

test_youtube_credentials_require_all_three_values() {
  local dir root payload youtube_dir rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  append_payload_entry "${payload}" "YOUTUBE_API_KEY" "youtube-api-key-secret"
  append_payload_entry "${payload}" "HAVE_YOUTUBE_API_KEY" "1"
  append_payload_entry "${payload}" "HAVE_YOUTUBE_CLIENT_ID" "0"
  append_payload_entry "${payload}" "HAVE_YOUTUBE_CLIENT_SECRET" "0"
  run_transform "${root}" "${payload}" >/dev/null

  youtube_dir="$(addon_data_path "${root}" plugin.video.youtube)"
  [[ ! -e "${youtube_dir}/api_keys.json" ]] || {
    printf 'api_keys.json must not be written for partial credentials\n' >&2
    return 1
  }
  assert_eq "en-US" "$(xml_setting "${youtube_dir}/settings.xml" youtube.language)" "language still provisioned"
  set +e
  grep -rq 'youtube-api-key-secret' "${root}"
  rc=$?
  set -e
  assert_failure "${rc}" "a partial API key is never written anywhere"
}

test_youtube_api_keys_json_has_expected_shape() {
  local dir root payload keys
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  keys="$(addon_data_path "${root}" plugin.video.youtube)/api_keys.json"
  assert_eq "youtube-api-key-secret" "$(json_path "${keys}" keys user api_key)" "api_key"
  assert_eq "youtube-client-id-secret" "$(json_path "${keys}" keys user client_id)" "client_id without the Google domain suffix"
  assert_eq "youtube-client-secret-secret" "$(json_path "${keys}" keys user client_secret)" "client_secret"
  assert_eq "{}" "$(json_path "${keys}" keys developer)" "developer key set stays empty"
  assert_eq '{"developer": {}, "user": {"api_key": "youtube-api-key-secret", "client_id": "youtube-client-id-secret", "client_secret": "youtube-client-secret-secret"}}' \
    "$(json_path "${keys}" keys)" "complete key set shape"

  local settings
  settings="$(addon_data_path "${root}" plugin.video.youtube)/settings.xml"
  assert_eq "US" "$(xml_setting "${settings}" youtube.region)" "region"
  assert_eq "false" "$(xml_setting "${settings}" kodion.setup_wizard)" "setup wizard suppressed"
  assert_eq "2" "$(xml_root_attribute "${settings}" version)" "standard add-on settings use version 2"
}

test_nextpvr_uses_instance_settings_format() {
  local dir root payload instance
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  instance="$(addon_data_path "${root}" pvr.nextpvr)/instance-settings-1.xml"
  [[ -f "${instance}" ]] || {
    printf 'instance-settings-1.xml was not written\n' >&2
    return 1
  }
  [[ ! -e "$(addon_data_path "${root}" pvr.nextpvr)/settings.xml" ]] || {
    printf 'NextPVR must not use the non-instance settings file\n' >&2
    return 1
  }
  assert_eq "Living Room NextPVR" "$(xml_setting "${instance}" kodi_addon_instance_name)" "instance name"
  assert_eq "true" "$(xml_setting "${instance}" kodi_addon_instance_enabled)" "instance enabled"
  assert_eq "nextpvr.example.lan" "$(xml_setting "${instance}" host)" "host"
  assert_eq "8866" "$(xml_setting "${instance}" port)" "port"
  assert_eq "http" "$(xml_setting "${instance}" hostprotocol)" "protocol"
  assert_eq "nextpvr-pin-secret" "$(xml_setting "${instance}" pin)" "pin"
  assert_eq "2" "$(xml_root_attribute "${instance}" version)" "instance settings use version 2"
}

test_home_assistant_weather_uses_flat_settings_format() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(addon_data_path "${root}" weather.ha)/settings.xml"
  assert_eq "" "$(xml_root_attribute "${settings}" version)" "flat format carries no version attribute"
  assert_eq "yes" "$(xml_setting_uses_value_attribute "${settings}" ha_server)" "flat format stores values in attributes"
  assert_eq "https://homeassistant.example.lan:8123" "$(xml_setting "${settings}" ha_server)" "server URL"
  assert_eq "home-assistant-token-secret" "$(xml_setting "${settings}" ha_key)" "token"
  assert_eq "weather.forecast_home" "$(xml_setting "${settings}" ha_weather_forecast_entity_id)" "forecast entity"
  assert_eq "sun.sun" "$(xml_setting "${settings}" ha_sun_entity_id)" "sun entity"
}

test_weather_provider_changes_only_when_configured() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN

  root="${dir}/unconfigured"
  payload="${dir}/base.conf"
  seed_guisettings "${root}"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null
  settings="$(guisettings_path "${root}")"
  assert_eq "weather.gismeteo" "$(xml_setting "${settings}" weather.addon)" "existing provider is left alone"

  root="${dir}/configured"
  payload="${dir}/full.conf"
  seed_guisettings "${root}"
  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null
  settings="$(guisettings_path "${root}")"
  assert_eq "weather.ha" "$(xml_setting "${settings}" weather.addon)" "provider switches once fully configured"
}

test_pm4k_local_mode_json_is_valid() {
  local dir root payload settings servers profiles
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(addon_data_path "${root}" script.plexmod)/settings.xml"
  servers="$(xml_setting "${settings}" local_servers_json | canonical_json)"
  assert_eq '[{"connection": "plex.example.lan", "name": "Basement Plex", "port": 32400, "token": "plex-token-secret"}]' \
    "${servers}" "local server entry"
  profiles="$(xml_setting "${settings}" local_profiles_json | canonical_json)"
  assert_eq '["11", "22"]' "${profiles}" "selected profile ids"
  assert_eq "true" "$(xml_setting "${settings}" local_mode)" "local mode enabled"
  assert_eq "always" "$(xml_setting "${settings}" allow_insecure)" "insecure LAN connections allowed"
}

test_absent_optional_secrets_do_not_create_secret_settings() {
  local dir root payload path nextpvr_instance
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  for path in \
    "$(addon_data_path "${root}" plugin.video.themoviedb.helper)/settings.xml" \
    "$(addon_data_path "${root}" script.plexmod)/settings.xml" \
    "$(addon_data_path "${root}" weather.ha)/settings.xml" \
    "$(addon_data_path "${root}" plugin.video.youtube)/api_keys.json"; do
    [[ ! -e "${path}" ]] || {
      printf 'unexpected file created without its secret: %s\n' "${path}" >&2
      return 1
    }
  done

  nextpvr_instance="$(addon_data_path "${root}" pvr.nextpvr)/instance-settings-1.xml"
  assert_eq "false" "$(xml_setting "${nextpvr_instance}" kodi_addon_instance_enabled)" \
    "the unconfigured NextPVR placeholder instance is disabled"
  assert_eq "0" "$(xml_setting_count "${nextpvr_instance}" pin)" \
    "the placeholder does not write a NextPVR PIN"
  assert_eq "0" "$(xml_setting_count "${nextpvr_instance}" host)" \
    "the placeholder does not invent a NextPVR host"

  assert_eq "0" "$(xml_setting_count "$(guisettings_path "${root}")" services.webserverpassword)" \
    "no web server password without a password"
}

test_absent_nextpvr_secret_preserves_an_existing_instance() {
  local dir root configured_payload unconfigured_payload instance
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  configured_payload="${dir}/configured.conf"
  unconfigured_payload="${dir}/unconfigured.conf"
  write_full_payload "${configured_payload}"
  write_base_payload "${unconfigured_payload}"

  run_transform "${root}" "${configured_payload}" >/dev/null
  instance="$(addon_data_path "${root}" pvr.nextpvr)/instance-settings-1.xml"
  run_transform "${root}" "${unconfigured_payload}" >/dev/null

  assert_eq "true" "$(xml_setting "${instance}" kodi_addon_instance_enabled)" \
    "an existing NextPVR instance remains enabled"
  assert_eq "nextpvr.example.lan" "$(xml_setting "${instance}" host)" \
    "an existing NextPVR host is preserved"
  assert_eq "nextpvr-pin-secret" "$(xml_setting "${instance}" pin)" \
    "an existing NextPVR PIN is preserved"
}

# --- Transport safety -------------------------------------------------------

test_payload_values_survive_hostile_characters() {
  local dir root payload hostile actual
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  hostile='a b = c	{"json": "value"}
second line'
  write_base_payload "${payload}"
  append_payload_entry "${payload}" "KODI_WEB_USER" "homeassistant"
  append_payload_entry "${payload}" "KODI_WEB_PORT" "8080"
  append_payload_entry "${payload}" "KODI_WEB_PASSWORD" "${hostile}"
  append_payload_entry "${payload}" "HAVE_KODI_WEB_PASSWORD" "1"
  run_transform "${root}" "${payload}" >/dev/null

  actual="$(xml_setting "$(guisettings_path "${root}")" services.webserverpassword)"
  assert_eq "${hostile}" "${actual}" "base64 transport preserves the exact value"
}

test_transformer_output_never_reveals_secrets() {
  local dir root payload output secret
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  output="$(run_transform "${root}" "${payload}" 2>&1)"

  for secret in \
    "kodi-web-password-secret" \
    "omdb-api-key-secret" \
    "mdblist-api-key-secret" \
    "youtube-api-key-secret" \
    "youtube-client-secret-secret" \
    "home-assistant-token-secret" \
    "nextpvr-pin-secret" \
    "plex-token-secret"; do
    assert_not_contains "${output}" "${secret}" "transformer output leaks a secret"
  done
}

# --- Write safety -----------------------------------------------------------

test_atomic_writes_never_reuse_a_preexisting_temp_file() {
  local dir root payload temporary witness
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  seed_guisettings "${root}"

  # A stale or planted temp file must never be opened and filled with secrets:
  # its mode (and any hard link to its inode) is outside the transformer's
  # control. The hard link makes the reuse observable after the rename.
  temporary="$(guisettings_path "${root}").provision-new"
  witness="${dir}/witness.bin"
  printf 'planted\n' > "${temporary}"
  chmod 666 "${temporary}"
  ln "${temporary}" "${witness}"

  run_transform "${root}" "${payload}" >/dev/null

  assert_eq "planted" "$(cat "${witness}")" "a pre-existing temp inode must not receive written bytes"
  assert_eq "666" "$(file_mode "${witness}")" "the planted inode keeps its own mode"
  assert_eq "600" "$(file_mode "$(guisettings_path "${root}")")" "guisettings.xml ends up private"
  assert_eq "" "$(orphan_temp_files "${root}")" "no temp file is left behind"
}

test_atomic_writes_do_not_follow_a_symlinked_temp_path() {
  local dir root payload temporary outside
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  seed_guisettings "${root}"

  outside="${dir}/outside.bin"
  temporary="$(guisettings_path "${root}").provision-new"
  printf 'untouched\n' > "${outside}"
  ln -s "${outside}" "${temporary}"

  run_transform "${root}" "${payload}" >/dev/null

  assert_eq "untouched" "$(cat "${outside}")" "a symlinked temp path must not redirect the write"
  if [[ -L "$(guisettings_path "${root}")" ]]; then
    printf 'guisettings.xml must be a regular file, not a symlink\n' >&2
    return 1
  fi
  assert_eq "600" "$(file_mode "$(guisettings_path "${root}")")" "guisettings.xml ends up private"
}

test_written_modes_ignore_a_permissive_umask() {
  local dir root payload youtube_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"

  # The mode must come from the transformer, never from whatever umask the
  # calling shell happened to have.
  (umask 000; run_transform "${root}" "${payload}" >/dev/null)

  youtube_dir="$(addon_data_path "${root}" plugin.video.youtube)"
  assert_eq "600" "$(file_mode "$(guisettings_path "${root}")")" "guisettings.xml"
  assert_eq "600" "$(file_mode "${youtube_dir}/api_keys.json")" "api_keys.json"
  assert_eq "600" "$(file_mode "$(addon_data_path "${root}" weather.ha)/settings.xml")" "weather.ha settings"
  assert_eq "644" "$(file_mode "${root}/.cache/timezone")" "the timezone cache stays readable on purpose"
  assert_eq "700" "$(file_mode "${youtube_dir}")" "add-on data directories are private"
  assert_eq "700" "$(file_mode "${root}/.kodi/userdata/addon_data")" "intermediate directories are private"
  assert_eq "700" "$(file_mode "${root}/.cache")" "the cache directory is private"
}

test_a_failed_write_leaves_no_secret_temp_file() {
  local dir root payload output status
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"

  # A directory where api_keys.json belongs makes the final rename fail after
  # the secret bytes have already been written to the temp file.
  mkdir -p "$(addon_data_path "${root}" plugin.video.youtube)/api_keys.json"

  set +e
  output="$(run_transform "${root}" "${payload}" 2>&1)"
  status=$?
  set -e

  assert_failure "${status}" "an unwritable target must fail loudly"
  assert_eq "" "$(orphan_temp_files "${root}")" "a failed write must not orphan a secret temp file"
  assert_eq "" "$(files_containing "${root}" "youtube-api-key-secret")" "no file under the root retains the secret"
  assert_not_contains "${output}" "youtube-api-key-secret" "the failure output must not leak a secret"
}

test_present_but_empty_secret_is_rejected() {
  local dir root payload output status
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  append_payload_entry "${payload}" "NEXTPVR_HOST" "nextpvr.example.lan"
  append_payload_entry "${payload}" "HAVE_NEXTPVR_PIN" "1"
  append_payload_entry "${payload}" "NEXTPVR_PIN" ""

  set +e
  output="$(run_transform "${root}" "${payload}" 2>&1)"
  status=$?
  set -e

  assert_failure "${status}" "a present-but-empty secret is a contradiction, not a value"
  assert_contains "${output}" "NEXTPVR_PIN" "the error names the offending key"
  if [[ -e "$(addon_data_path "${root}" pvr.nextpvr)/instance-settings-1.xml" ]]; then
    printf 'an empty PIN must never be written\n' >&2
    return 1
  fi
}

test_remote_payload_upload_replaces_a_permissive_file() {
  local dir root script target witness
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  mkdir -p "${root}/.cache/coreelec-provision"
  chmod 777 "${root}/.cache/coreelec-provision"

  target="${root}/.cache/coreelec-provision/settings-payload.conf"
  witness="${dir}/witness.bin"
  printf 'stale-payload\n' > "${target}"
  chmod 666 "${target}"
  ln "${target}" "${witness}"

  script="$(bash "${PROVISIONER}" --emit-remote-script payload "${root}")"
  (umask 000; printf 'KEY=dmFsdWU=\n' | sh -c "${script}")

  assert_eq "KEY=dmFsdWU=" "$(cat "${target}")" "the payload is delivered"
  assert_eq "600" "$(file_mode "${target}")" "the payload file is private"
  assert_eq "700" "$(file_mode "${root}/.cache/coreelec-provision")" "the payload directory is private"
  assert_eq "stale-payload" "$(cat "${witness}")" "a pre-existing payload inode never receives the new secrets"
  assert_eq "" "$(orphan_temp_files "${root}")" "no payload temp file survives"
}

test_remote_backup_directory_is_private() {
  local dir root script backup
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  mkdir -p "${root}/.kodi/userdata"
  printf '<settings version="2"><setting id="services.webserverpassword">s3cret</setting></settings>\n' \
    > "$(guisettings_path "${root}")"
  chmod 644 "$(guisettings_path "${root}")"

  script="$(bash "${PROVISIONER}" --emit-remote-script backup "${root}")"
  backup="$(umask 022; printf '%s\n' "${script}" | sh -s)"

  assert_eq "700" "$(file_mode "${backup}")" "the backup snapshot directory is private"
  assert_eq "700" "$(file_mode "${root}/backup/coreelec-provision")" "the backup parent directory is private"
  assert_eq "600" "$(file_mode "${backup}/MANIFEST.txt")" "the manifest is private"
  if [[ ! -f "${backup}/.kodi/userdata/guisettings.xml" ]]; then
    printf 'the backup must still copy guisettings.xml\n' >&2
    return 1
  fi
}

# --- Arctic Fuse skin helpers -----------------------------------------------

skin_settings_path() {
  printf '%s/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml' "$1"
}

skinvariables_node_path() {
  printf '%s/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/%s' \
    "$1" "$2"
}

video_playlist_path() {
  printf '%s/.kodi/userdata/playlists/video/%s' "$1" "$2"
}

smart_playlist_summary() {
  python3 - "$1" <<'PYEOF'
import json
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
root = ET.parse(path).getroot()
result = {
    "type": root.get("type", ""),
    "name": "",
    "match": "",
    "limit": 0,
    "rules": [],
    "order": {},
}
name_node = root.find("name")
if name_node is not None:
    result["name"] = name_node.text or ""
match_node = root.find("match")
if match_node is not None:
    result["match"] = match_node.text or ""
limit_node = root.find("limit")
if limit_node is not None:
    result["limit"] = int(limit_node.text or "0")
for rule in root.findall("rule"):
    value_node = rule.find("value")
    result["rules"].append({
        "field": rule.get("field", ""),
        "operator": rule.get("operator", ""),
        "value": (value_node.text or "") if value_node is not None else "",
    })
order_node = root.find("order")
if order_node is not None:
    result["order"] = {
        "field": order_node.text or "",
        "direction": order_node.get("direction", ""),
    }
sys.stdout.write(json.dumps(result, sort_keys=True))
PYEOF
}

# Reads a skin setting value (case-sensitive ID match).
skin_setting() {
  xml_setting "$(skin_settings_path "$1")" "$2"
}

# Counts how many setting nodes have this exact ID in the skin settings file.
skin_setting_count() {
  xml_setting_count "$(skin_settings_path "$1")" "$2"
}

# True if a setting ID has no node at all in the skin settings file.
skin_setting_absent() {
  local count
  count="$(skin_setting_count "$1" "$2")"
  [[ "${count}" == "0" ]]
}

# --- Arctic Fuse convergence tests ------------------------------------------

test_arctic_fuse_hubs_and_options_tray_are_converged() {
  local dir root payload skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"

  # Seed skin settings with unrelated.keep=yes, a duplicate/case-variant
  # HomeSwitcher.1101.Toggle, and a stale HomeSwitcher.1101.Shortcut.Target.
  mkdir -p "$(dirname "$(skin_settings_path "${root}")")"
  cat > "$(skin_settings_path "${root}")" <<'XML'
<?xml version='1.0' encoding='UTF-8'?>
<settings>
    <setting id="unrelated.keep">yes</setting>
    <setting id="HomeSwitcher.1101.Toggle">false</setting>
    <setting id="homeswitcher.1101.toggle">stale-case-variant</setting>
    <setting id="HomeSwitcher.1101.Shortcut.Target">oldplex</setting>
    <setting id="HomeSwitcher.1101.Spotlight.Path">old-spotlight</setting>
    <setting id="HomeSwitcher.1102.Spotlight.Path">old-spotlight-2</setting>
</settings>
XML

  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  skin_file="$(skin_settings_path "${root}")"

  # Unrelated setting is preserved exactly once
  assert_eq "yes" "$(xml_setting "${skin_file}" "unrelated.keep")" "unrelated.keep preserved"
  assert_eq "1" "$(xml_setting_count "${skin_file}" "unrelated.keep")" "unrelated.keep not duplicated"

  # Canonical settings
  assert_eq "Plex" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Name")" "1101.Name"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Toggle")" "1101.Toggle"
  assert_eq "special://home/addons/script.plexmod/icon2.png" \
    "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Icon")" "1101.Icon"
  assert_eq "RunAddon(script.plexmod)" \
    "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Shortcut.Path")" "1101.Shortcut.Path"

  assert_eq "YouTube" "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Name")" "1102.Name"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Toggle")" "1102.Toggle"
  assert_eq "special://home/addons/plugin.video.youtube/resources/media/icon.png" \
    "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Icon")" "1102.Icon"
  assert_eq "plugin://plugin.video.youtube/" \
    "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Shortcut.Path")" "1102.Shortcut.Path"
  assert_eq "videos" \
    "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Shortcut.Target")" "1102.Shortcut.Target"

  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1106.Toggle")" "1106.Toggle"
  assert_eq "library_nextaired" \
    "$(xml_setting "${skin_file}" "HomeSwitcher.1106.UpNextMode")" "1106.UpNextMode"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1107.Toggle")" "1107.Toggle"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1108.Toggle")" "1108.Toggle"
  assert_eq "Settings" "$(xml_setting "${skin_file}" "optionstiles.02.include")" "optionstiles.02"

  # Duplicate/case-variant collapsed — only 1 node for 1101.Toggle
  assert_eq "1" "$(xml_setting_count "${skin_file}" "HomeSwitcher.1101.Toggle")" \
    "duplicate 1101.Toggle collapsed"

  # Stale settings must be absent
  skin_setting_absent "${root}" "HomeSwitcher.1101.Shortcut.Target" \
    || { printf '1101.Shortcut.Target must be absent\n' >&2; return 1; }
  skin_setting_absent "${root}" "HomeSwitcher.1101.Spotlight.Path" \
    || { printf '1101.Spotlight.Path must be absent\n' >&2; return 1; }
  skin_setting_absent "${root}" "HomeSwitcher.1102.Spotlight.Path" \
    || { printf '1102.Spotlight.Path must be absent\n' >&2; return 1; }
}

test_arctic_fuse_home_widgets_are_exact_and_ordered() {
  local dir root payload home_json expected actual
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  home_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-homewidgets.json")"
  [[ -f "${home_json}" ]] || { printf 'home widgets JSON not found\n' >&2; return 1; }

  expected='[{"guid": "coreelec-home-inprogress-movies", "icon": "", "label": "In-Progress Movies", "path": "special://profile/playlists/video/InProgressMovies90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-inprogress-shows", "icon": "", "label": "In-Progress Shows", "path": "special://profile/playlists/video/InProgressShows90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-aired-shows", "icon": "", "label": "Recently Aired Shows", "path": "special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-released-movies", "icon": "", "label": "Recently Released Movies", "path": "special://profile/playlists/video/RecentlyReleasedMovies90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-new-shows", "icon": "", "label": "New Shows", "path": "special://profile/playlists/video/NewShows.xsp", "target": "videos"}, {"guid": "coreelec-home-new-movies", "icon": "", "label": "New Movies", "path": "special://profile/playlists/video/NewMovies.xsp", "target": "videos"}]'
  actual="$(python3 -c 'import json,sys; sys.stdout.write(json.dumps(json.load(open(sys.argv[1])),sort_keys=False))' "${home_json}")"
  assert_eq "${expected}" "${actual}" "home widgets JSON content"

  # Negative assertions on raw file
  local raw
  raw="$(cat "${home_json}")"
  assert_not_contains "${raw}" "Quit()" "no Quit in home"
  assert_not_contains "${raw}" "Profiles" "no Profiles in home"
  assert_not_contains "${raw}" "ActivateWindow(1195)" "no Favourites window in home"
  assert_not_contains "${raw}" "Favourites" "no Favourites in home"
  assert_not_contains "${raw}" "File manager" "no File manager in home"
  assert_not_contains "${raw}" "Hibernate" "no Hibernate in home"
  assert_not_contains "${raw}" "rebootfromnand" "no rebootfromnand in home"
}

test_arctic_fuse_power_menu_is_coreelec_appropriate() {
  local dir root payload power_json expected actual raw
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  power_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-powermenu.json")"
  [[ -f "${power_json}" ]] || { printf 'power menu JSON not found\n' >&2; return 1; }

  expected='[{"guid": "coreelec-power-poweroff", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13016]", "path": "Powerdown()", "target": ""}, {"guid": "coreelec-power-timer", "icon": "special://skin/extras/icons/timer.png", "label": "$LOCALIZE[20150]", "path": "AlarmClock(shutdowntimer,Shutdown())", "target": ""}, {"guid": "coreelec-power-suspend", "icon": "special://skin/extras/icons/power.png", "label": "$LOCALIZE[13011]", "path": "Suspend()", "target": ""}, {"guid": "coreelec-power-reboot", "icon": "special://skin/extras/icons/refresh.png", "label": "$LOCALIZE[13013]", "path": "Reset()", "target": ""}, {"guid": "coreelec-power-restart-kodi", "icon": "special://skin/extras/icons/refresh.png", "label": "Restart Kodi", "path": "RestartApp()", "target": ""}]'
  actual="$(python3 -c 'import json,sys; sys.stdout.write(json.dumps(json.load(open(sys.argv[1])),sort_keys=False))' "${power_json}")"
  assert_eq "${expected}" "${actual}" "power menu JSON content"

  raw="$(cat "${power_json}")"
  assert_not_contains "${raw}" "Quit()" "no Quit in power"
  assert_not_contains "${raw}" "Profiles" "no Profiles in power"
  assert_not_contains "${raw}" "ActivateWindow(1195)" "no Favourites window in power"
  assert_not_contains "${raw}" "Favourites" "no Favourites in power"
  assert_not_contains "${raw}" "File manager" "no File manager in power"
  assert_not_contains "${raw}" "Hibernate" "no Hibernate in power"
  assert_not_contains "${raw}" "rebootfromnand" "no rebootfromnand in power"
}

test_arctic_fuse_smart_playlists_have_exact_rules() {
  local dir root payload summary
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  # InProgressMovies90Days.xsp
  summary="$(smart_playlist_summary "$(video_playlist_path "${root}" InProgressMovies90Days.xsp)")"
  assert_eq "movies" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["type"])')" "IPM type"
  assert_eq "In-Progress Movies" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')" "IPM name"
  assert_eq "50" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["limit"])')" "IPM limit"
  assert_eq "all" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["match"])')" "IPM match"

  # InProgressShows90Days.xsp
  summary="$(smart_playlist_summary "$(video_playlist_path "${root}" InProgressShows90Days.xsp)")"
  assert_eq "tvshows" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["type"])')" "IPS type"
  assert_eq "In-Progress Shows" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')" "IPS name"

  # RecentlyAiredEpisodes30Days.xsp
  summary="$(smart_playlist_summary "$(video_playlist_path "${root}" RecentlyAiredEpisodes30Days.xsp)")"
  assert_eq "episodes" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["type"])')" "RAE type"
  assert_eq "Recently Aired Shows" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')" "RAE name"

  # RecentlyReleasedMovies90Days.xsp
  summary="$(smart_playlist_summary "$(video_playlist_path "${root}" RecentlyReleasedMovies90Days.xsp)")"
  assert_eq "movies" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["type"])')" "RRM type"
  assert_eq "Recently Released Movies" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')" "RRM name"

  # NewShows.xsp
  summary="$(smart_playlist_summary "$(video_playlist_path "${root}" NewShows.xsp)")"
  assert_eq "tvshows" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["type"])')" "NS type"
  assert_eq "New Shows" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')" "NS name"

  # NewMovies.xsp
  summary="$(smart_playlist_summary "$(video_playlist_path "${root}" NewMovies.xsp)")"
  assert_eq "movies" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["type"])')" "NM type"
  assert_eq "New Movies" "$(printf '%s' "${summary}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')" "NM name"
}

test_arctic_fuse_managed_files_are_private_and_primary_profile_only() {
  local dir root payload skin_file home_json power_json
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  # Every generated XML/JSON file is mode 600
  skin_file="$(skin_settings_path "${root}")"
  assert_eq "600" "$(file_mode "${skin_file}")" "skin settings mode"

  home_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-homewidgets.json")"
  assert_eq "600" "$(file_mode "${home_json}")" "home widgets mode"

  power_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-powermenu.json")"
  assert_eq "600" "$(file_mode "${power_json}")" "power menu mode"

  local xsp
  for xsp in InProgressMovies90Days.xsp InProgressShows90Days.xsp \
    RecentlyAiredEpisodes30Days.xsp RecentlyReleasedMovies90Days.xsp \
    NewShows.xsp NewMovies.xsp; do
    assert_eq "600" "$(file_mode "$(video_playlist_path "${root}" "${xsp}")")" "${xsp} mode"
  done

  # Created directories are mode 700
  assert_eq "700" "$(file_mode "$(dirname "${skin_file}")")" "skin data dir mode"
  assert_eq "700" "$(file_mode "$(dirname "${home_json}")")" "skinvariables node dir mode"
  assert_eq "700" "$(file_mode "${root}/.kodi/userdata/playlists/video")" "playlists video dir mode"

  # No profiles/ path is created
  if find "${root}" -path '*/profiles/*' -print -quit 2>/dev/null | grep -q .; then
    printf 'profiles/ path must not be created\n' >&2
    return 1
  fi
}

test_arctic_fuse_convergence_preserves_unmanaged_skinvariables_nodes() {
  local dir root payload sibling_path
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"

  # Create a sibling file before the transformer runs
  sibling_path="$(skinvariables_node_path "${root}" "skinvariables-shortcut-searchwidgets.json")"
  mkdir -p "$(dirname "${sibling_path}")"
  printf '{"unmanaged": true}\n' > "${sibling_path}"

  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  assert_eq '{"unmanaged": true}' "$(cat "${sibling_path}")" "unmanaged sibling unchanged"
}

test_arctic_fuse_second_run_is_byte_identical() {
  local dir root payload first second
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"

  run_transform "${root}" "${payload}" >/dev/null
  first="$(tree_digest "${root}")"
  run_transform "${root}" "${payload}" >/dev/null
  second="$(tree_digest "${root}")"
  assert_eq "${first}" "${second}" "a second run (with skin state) rewrites nothing"
}

test_arctic_fuse_managed_paths_are_backed_up_and_rolled_back() {
  local dir root payload managed_output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  # Check that coreelec_managed_settings_paths_block lists the skin settings,
  # both node JSON files, and all six XSP files.
  managed_output="$(bash "${PROVISIONER}" --emit-remote-script backup "${root}")"

  assert_contains "${managed_output}" ".kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml" \
    "skin settings in managed paths"
  assert_contains "${managed_output}" "skinvariables-shortcut-homewidgets.json" \
    "home widgets in managed paths"
  assert_contains "${managed_output}" "skinvariables-shortcut-powermenu.json" \
    "power menu in managed paths"
  assert_contains "${managed_output}" "InProgressMovies90Days.xsp" "IPM in managed paths"
  assert_contains "${managed_output}" "InProgressShows90Days.xsp" "IPS in managed paths"
  assert_contains "${managed_output}" "RecentlyAiredEpisodes30Days.xsp" "RAE in managed paths"
  assert_contains "${managed_output}" "RecentlyReleasedMovies90Days.xsp" "RRM in managed paths"
  assert_contains "${managed_output}" "NewShows.xsp" "NS in managed paths"
  assert_contains "${managed_output}" "NewMovies.xsp" "NM in managed paths"
}

test_arctic_fuse_failed_write_cleans_temporary_files() {
  local dir root payload output status
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"

  # Pre-create a managed skin file that will be backed up
  mkdir -p "$(dirname "$(skin_settings_path "${root}")")"
  printf '<settings><setting id="pre-existing">value</setting></settings>\n' \
    > "$(skin_settings_path "${root}")"

  # Create a directory where a playlist file belongs, forcing rename to fail
  mkdir -p "$(video_playlist_path "${root}" InProgressMovies90Days.xsp)"

  set +e
  output="$(run_transform "${root}" "${payload}" 2>&1)"
  status=$?
  set -e

  assert_failure "${status}" "the blocked write must fail"
  assert_eq "" "$(orphan_temp_files "${root}")" "no temp files left behind"
}

run_all_tests \
  test_regional_settings_are_created \
  test_duplicate_settings_are_collapsed \
  test_existing_unmanaged_settings_are_preserved \
  test_second_run_is_byte_identical \
  test_tmdb_helper_keys_go_to_tmdb_helper_only \
  test_youtube_credentials_require_all_three_values \
  test_youtube_api_keys_json_has_expected_shape \
  test_nextpvr_uses_instance_settings_format \
  test_home_assistant_weather_uses_flat_settings_format \
  test_weather_provider_changes_only_when_configured \
  test_pm4k_local_mode_json_is_valid \
  test_absent_optional_secrets_do_not_create_secret_settings \
  test_absent_nextpvr_secret_preserves_an_existing_instance \
  test_payload_values_survive_hostile_characters \
  test_transformer_output_never_reveals_secrets \
  test_atomic_writes_never_reuse_a_preexisting_temp_file \
  test_atomic_writes_do_not_follow_a_symlinked_temp_path \
  test_written_modes_ignore_a_permissive_umask \
  test_a_failed_write_leaves_no_secret_temp_file \
  test_present_but_empty_secret_is_rejected \
  test_remote_payload_upload_replaces_a_permissive_file \
  test_remote_backup_directory_is_private \
  test_arctic_fuse_hubs_and_options_tray_are_converged \
  test_arctic_fuse_home_widgets_are_exact_and_ordered \
  test_arctic_fuse_power_menu_is_coreelec_appropriate \
  test_arctic_fuse_smart_playlists_have_exact_rules \
  test_arctic_fuse_managed_files_are_private_and_primary_profile_only \
  test_arctic_fuse_convergence_preserves_unmanaged_skinvariables_nodes \
  test_arctic_fuse_second_run_is_byte_identical \
  test_arctic_fuse_managed_paths_are_backed_up_and_rolled_back \
  test_arctic_fuse_failed_write_cleans_temporary_files
