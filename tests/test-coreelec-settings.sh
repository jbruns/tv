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

cec_settings_path() {
  printf '%s/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml' "$1"
}

write_cec_settings() {
  local root="$1" value="$2"
  mkdir -p "${root}/.kodi/userdata/peripheral_data"
  printf '<settings><setting id="standby_pc_on_tv_standby" value="%s" /></settings>\n' \
    "${value}" > "$(cec_settings_path "${root}")"
}

# Seeds a default (untouched-device) CEC peripheral file when a test's root
# does not already provide one. The transformer requires exactly one such
# file to exist, the same way a real CoreELEC device already has one once its
# CEC adapter has been detected; tests exercising unrelated transformer
# behavior should not each have to know that contract. Tests that exercise the
# missing/ambiguous file behavior itself call the provisioner directly instead
# of going through run_transform, so this default never masks their fixture.
ensure_default_cec_settings() {
  local root="$1"
  if ! find "${root}/.kodi/userdata/peripheral_data" -maxdepth 1 -name '*CEC*.xml' \
      2>/dev/null | grep -q .; then
    write_cec_settings "${root}" "13011"
  fi
}

run_transform() {
  local root="$1" payload="$2"
  ensure_default_cec_settings "${root}"
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
# Component flags default to the legacy full baseline so existing tests keep
# exercising exactly the pre-scoping behavior.
write_scoped_base_payload() {
  local file="$1" apply_core="$2" apply_cec="$3" apply_addons="$4"
  local apply_services="$5" apply_skin="$6"
  local apply_room="${7:-0}"
  write_payload "${file}" <<ENTRIES
TIMEZONE=America/Los_Angeles
TIMEZONE_COUNTRY=United States
LOCALE_LANGUAGE=resource.language.en_us
LOCALE_COUNTRY=USA (12h)
KEYBOARD_LAYOUT=English QWERTY
ADDON_UPDATE_MODE=notify
CEC_TV_OFF_ACTION=36028
APPLY_COMPONENT_CORE=${apply_core}
APPLY_COMPONENT_CEC=${apply_cec}
APPLY_COMPONENT_ADDONS=${apply_addons}
APPLY_COMPONENT_SERVICES=${apply_services}
APPLY_COMPONENT_SKIN=${apply_skin}
APPLY_COMPONENT_ROOM=${apply_room}
ENTRIES
}

write_base_payload() {
  write_scoped_base_payload "$1" 1 1 1 1 1
}

# Every managed value present, so each selected optional branch of the
# transformer runs. CEC_TV_OFF_ACTION is included here too because the
# transformer requires it whenever CEC is selected.
write_scoped_full_payload() {
  local file="$1" apply_core="$2" apply_cec="$3" apply_addons="$4"
  local apply_services="$5" apply_skin="$6"
  local apply_room="${7:-0}"
  write_payload "${file}" <<ENTRIES
TIMEZONE=America/Los_Angeles
TIMEZONE_COUNTRY=United States
LOCALE_LANGUAGE=resource.language.en_us
LOCALE_COUNTRY=USA (12h)
KEYBOARD_LAYOUT=English QWERTY
ADDON_UPDATE_MODE=notify
CEC_TV_OFF_ACTION=36028
KODI_WEB_USER=homeassistant
KODI_WEB_PORT=8080
KODI_WEB_PASSWORD=kodi-web-password-secret
HAVE_KODI_WEB_PASSWORD=1
OMDB_API_KEY=omdb-api-key-secret
HAVE_OMDB_API_KEY=1
MDBLIST_API_KEY=mdblist-api-key-secret
HAVE_MDBLIST_API_KEY=1
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
APPLY_COMPONENT_CORE=${apply_core}
APPLY_COMPONENT_CEC=${apply_cec}
APPLY_COMPONENT_ADDONS=${apply_addons}
APPLY_COMPONENT_SERVICES=${apply_services}
APPLY_COMPONENT_SKIN=${apply_skin}
APPLY_COMPONENT_ROOM=${apply_room}
ENTRIES
}

write_full_payload() {
  write_scoped_full_payload "$1" 1 1 1 1 1
}

# Appends the ten room settings keys, letting named overrides replace
# individual values so each test states only what it is testing.
write_room_payload_values() {
  local file="$1"; shift
  local index=41 dv=1 mode=tv-led pass=1 ac3=1 eac3=1 dts=1 truehd=1 dtshd=1
  local entry
  for entry in "$@"; do
    case "${entry}" in
      INDEX=*) index="${entry#INDEX=}" ;;
      DV=*) dv="${entry#DV=}" ;;
      MODE=*) mode="${entry#MODE=}" ;;
      *) printf 'unknown room payload override: %s\n' "${entry}" >&2; return 1 ;;
    esac
  done
  append_payload_entry "${file}" "ROOM_NAME" "theater"
  append_payload_entry "${file}" "ROOM_DISPLAY_RESOLUTION_INDEX" "${index}"
  append_payload_entry "${file}" "ROOM_DISPLAY_WHITELIST" \
    "0409602160024.00000pstd,0384002160060.00000pstd"
  append_payload_entry "${file}" "ROOM_DOLBY_VISION" "${dv}"
  append_payload_entry "${file}" "ROOM_DOLBY_VISION_MODE" "${mode}"
  append_payload_entry "${file}" "ROOM_AUDIO_PASSTHROUGH" "${pass}"
  append_payload_entry "${file}" "ROOM_AUDIO_AC3" "${ac3}"
  append_payload_entry "${file}" "ROOM_AUDIO_EAC3" "${eac3}"
  append_payload_entry "${file}" "ROOM_AUDIO_DTS" "${dts}"
  append_payload_entry "${file}" "ROOM_AUDIO_TRUEHD" "${truehd}"
  append_payload_entry "${file}" "ROOM_AUDIO_DTSHD" "${dtshd}"
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

# Asserts a guisettings.xml setting carries exactly the expected value.
assert_setting_equals() {
  local path="$1" setting_id="$2" expected="$3"
  assert_eq "${expected}" "$(xml_setting "${path}" "${setting_id}")" \
    "${setting_id}"
}

# Asserts a guisettings.xml setting node is entirely absent.
assert_setting_absent() {
  local path="$1" setting_id="$2"
  assert_eq "0" "$(xml_setting_count "${path}" "${setting_id}")" \
    "${setting_id} is absent"
}

xml_setting_type() {
  python3 - "$1" "$2" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path, setting_id = sys.argv[1], sys.argv[2]
root = ET.parse(path).getroot()
for node in root.iter("setting"):
    if node.get("id") == setting_id:
        sys.stdout.write(node.get("type") or "")
        break
else:
    sys.stderr.write("setting not found: %s in %s\n" % (setting_id, path))
    raise SystemExit(3)
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
      sha256sum "${file}"
    done
  ) | sha256sum
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

seed_scoped_settings_sentinels() {
  local root="$1" path
  seed_guisettings "${root}"

  mkdir -p "${root}/.kodi/userdata/peripheral_data"
  cat > "$(cec_settings_path "${root}")" <<'XML'
<settings>
    <setting id="enabled" value="1" />
    <setting id="activate_source" value="1" />
    <setting id="wake_devices" value="36037" />
    <setting id="standby_devices" value="36037" />
    <setting id="standby_tv_on_pc_standby" value="1" />
    <setting id="standby_pc_on_tv_standby" value="13011" />
</settings>
XML

  while IFS='|' read -r path sentinel; do
    mkdir -p "$(dirname "${path}")"
    printf '<settings version="2"><setting id="%s">%s</setting></settings>\n' \
      "${sentinel}" "${sentinel}" > "${path}"
  done <<EOF
$(addon_data_path "${root}" plugin.video.themoviedb.helper)/settings.xml|sentinel.tmdb
$(addon_data_path "${root}" pvr.nextpvr)/instance-settings-1.xml|sentinel.nextpvr
$(addon_data_path "${root}" script.plexmod)/settings.xml|sentinel.plex
$(addon_data_path "${root}" weather.ha)/settings.xml|sentinel.weather
$(skin_settings_path "${root}")|sentinel.skin
EOF

  path="$(skinvariables_node_path "${root}" skinvariables-shortcut-homewidgets.json)"
  mkdir -p "$(dirname "${path}")"
  printf '[{"guid":"sentinel-widget","label":"leave widget alone"}]\n' > "${path}"

  path="$(video_playlist_path "${root}" InProgressMovies90Days.xsp)"
  mkdir -p "$(dirname "${path}")"
  printf '<smartplaylist type="movies"><name>sentinel playlist</name></smartplaylist>\n' \
    > "${path}"
}

applied_path_count() {
  local output="$1" path="$2"
  printf '%s\n' "${output}" | grep -Fxc "settings applied: ${path}" || true
}

load_provisioner_function() {
  local name="$1" body
  body="$(awk -v start="${name}() {" '
    $0 == start { capturing = 1 }
    capturing { print }
    capturing && $0 == "}" { exit }
  ' "${PROVISIONER}")"
  [[ -n "${body}" ]] || {
    printf 'no %s() definition was found in the provisioner\n' "${name}" >&2
    return 1
  }
  eval "${body}"
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
  assert_eq "1" "$(xml_setting "${settings}" videolibrary.flattentvshows)" \
    "TV seasons are flattened"
  assert_eq "true" "$(xml_setting "${settings}" videolibrary.ignorevideoextras)" \
    "video extras are ignored"
  assert_eq "true" "$(xml_setting "${settings}" videolibrary.ignorevideoversions)" \
    "video versions are ignored"
  assert_eq "false" "$(xml_setting "${settings}" input.enablemouse)" \
    "mouse input is disabled"
  assert_eq "resource.uisounds.fromashes" \
    "$(xml_setting "${settings}" lookandfeel.soundskin)" \
    "From Ashes is the selected sound skin"
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
  python3 - "$(guisettings_path "${root}")" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
root = tree.getroot()
for setting_id, value in (
    ("videolibrary.flattentvshows", "0"),
    ("videolibrary.ignorevideoextras", "false"),
    ("videolibrary.ignorevideoversions", "false"),
    ("input.enablemouse", "true"),
    ("lookandfeel.soundskin", "resource.uisounds.default"),
    ("LOOKANDFEEL.SOUNDSKIN", "stale-case-variant"),
):
    node = ET.SubElement(root, "setting", {"id": setting_id})
    node.text = value
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_eq "1" "$(xml_setting_count "${settings}" locale.timezone)" "one locale.timezone node remains"
  assert_eq "America/Los_Angeles" "$(xml_setting "${settings}" locale.timezone)" "surviving node carries the new value"
  assert_eq "1" "$(xml_setting_count "${settings}" lookandfeel.skin)" "one lookandfeel.skin node remains"
  assert_eq "1" "$(xml_setting_count "${settings}" videolibrary.flattentvshows)" \
    "one videolibrary.flattentvshows node remains"
  assert_eq "1" "$(xml_setting "${settings}" videolibrary.flattentvshows)" \
    "videolibrary.flattentvshows converges to the managed value"
  assert_eq "1" "$(xml_setting_count "${settings}" videolibrary.ignorevideoextras)" \
    "one videolibrary.ignorevideoextras node remains"
  assert_eq "true" "$(xml_setting "${settings}" videolibrary.ignorevideoextras)" \
    "videolibrary.ignorevideoextras converges to the managed value"
  assert_eq "1" "$(xml_setting_count "${settings}" videolibrary.ignorevideoversions)" \
    "one videolibrary.ignorevideoversions node remains"
  assert_eq "true" "$(xml_setting "${settings}" videolibrary.ignorevideoversions)" \
    "videolibrary.ignorevideoversions converges to the managed value"
  assert_eq "1" "$(xml_setting_count "${settings}" input.enablemouse)" \
    "one input.enablemouse node remains"
  assert_eq "false" "$(xml_setting "${settings}" input.enablemouse)" \
    "input.enablemouse converges to the managed value"
  assert_eq "1" "$(xml_setting_count "${settings}" lookandfeel.soundskin)" \
    "one lookandfeel.soundskin node remains"
  assert_eq "resource.uisounds.fromashes" \
    "$(xml_setting "${settings}" lookandfeel.soundskin)" \
    "lookandfeel.soundskin converges to the managed value"
}

# Kodi's settings manager resolves a guisettings ID without regard to case, so
# a differently cased node is the same setting. Leaving one beside the managed
# node lets Kodi read the stale value and makes verification permanently
# ambiguous.
test_kodi_setting_case_variants_are_removed() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  seed_guisettings "${root}"
  python3 - "$(guisettings_path "${root}")" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
root = tree.getroot()
node = ET.SubElement(root, "setting", {"id": "LOOKANDFEEL.SOUNDSKIN"})
node.text = "resource.uisounds.default"
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_eq "0" "$(xml_setting_count "${settings}" "LOOKANDFEEL.SOUNDSKIN")" \
    "the uppercase sound skin variant is removed"
  assert_eq "1 1" "$(xml_setting_scope_counts "${settings}" lookandfeel.soundskin)" \
    "exactly one canonical root sound skin node survives"
  assert_eq "resource.uisounds.fromashes" \
    "$(xml_setting "${settings}" lookandfeel.soundskin)" \
    "the surviving node carries the managed sound skin"
}

# Kodi reads only the direct `<setting>` children of the guisettings root,
# while the verifier reads the document recursively. A managed value left at
# any depth would therefore be invisible to Kodi and still be found, so
# convergence must promote it to one canonical root node without disturbing
# unrelated nested state.
test_nested_kodi_settings_are_promoted_to_root_nodes() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  seed_guisettings "${root}"
  python3 - "$(guisettings_path "${root}")" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
root = tree.getroot()
category = ET.SubElement(root, "category", {"id": "videolibrary"})
ET.SubElement(category, "setting", {"id": "input.enablemouse"}).text = "true"
ET.SubElement(
    category, "setting", {"id": "unmanaged.category.preference"}
).text = "keep-category"
group = ET.SubElement(category, "group", {"id": "general"})
ET.SubElement(
    group, "setting", {"id": "videolibrary.flattentvshows"}
).text = "0"
ET.SubElement(
    group, "setting", {"id": "unmanaged.group.preference"}
).text = "keep-group"
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_eq "1 1" "$(xml_setting_scope_counts "${settings}" input.enablemouse)" \
    "a category-nested managed setting is promoted to one root node"
  assert_eq "false" "$(xml_setting "${settings}" input.enablemouse)" \
    "the promoted mouse setting carries the managed value"
  assert_eq "1 1" \
    "$(xml_setting_scope_counts "${settings}" videolibrary.flattentvshows)" \
    "a deeply nested managed setting is promoted to one root node"
  assert_eq "1" "$(xml_setting "${settings}" videolibrary.flattentvshows)" \
    "the promoted flatten setting carries the managed value"
  assert_eq "keep-category" \
    "$(xml_setting "${settings}" unmanaged.category.preference)" \
    "unrelated category state is preserved"
  assert_eq "keep-group" \
    "$(xml_setting "${settings}" unmanaged.group.preference)" \
    "unrelated deeply nested state is preserved"
}

test_existing_unmanaged_settings_are_preserved() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  seed_guisettings "${root}"
  python3 - "$(guisettings_path "${root}")" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
tree = ET.parse(path)
root = tree.getroot()
for setting_id, value in (
    ("unmanaged.custom.preference", "keep-me"),
    ("unmanaged.custom.secondary", "still-here"),
):
    node = ET.SubElement(root, "setting", {"id": setting_id})
    node.text = value
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_eq "2" "$(xml_setting "${settings}" audiooutput.channels)" "unmanaged setting is untouched"
  assert_eq "1" "$(xml_setting_count "${settings}" audiooutput.channels)" "unmanaged setting is not duplicated"
  assert_eq "keep-me" "$(xml_setting "${settings}" unmanaged.custom.preference)" \
    "custom unmanaged setting is preserved"
  assert_eq "still-here" "$(xml_setting "${settings}" unmanaged.custom.secondary)" \
    "second unmanaged setting is preserved"
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

# --- HDMI-CEC TV standby behavior --------------------------------------------
#
# Kodi's CEC peripheral file, not guisettings.xml, decides what a CEC-capable
# TV's standby broadcast makes the box do. A CEC-selected transform forces this
# to 36028 (Ignore), so a sleeping TV never puts an always-awake box to sleep
# with it. A selected transform fails when the file is missing or ambiguous,
# because guessing which peripheral file to edit is worse than refusing to run.

test_cec_only_transform_is_isolated() {
  local dir root payload cec_path guisettings skin_settings weather_settings
  local playlist widget tmdb nextpvr plex written first_cec second_cec
  local guisettings_before skin_before weather_before playlist_before
  local widget_before tmdb_before nextpvr_before plex_before
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  seed_scoped_settings_sentinels "${root}"
  write_scoped_base_payload "${payload}" 0 1 0 0 0

  cec_path="$(cec_settings_path "${root}")"
  guisettings="$(guisettings_path "${root}")"
  skin_settings="$(skin_settings_path "${root}")"
  weather_settings="$(addon_data_path "${root}" weather.ha)/settings.xml"
  playlist="$(video_playlist_path "${root}" InProgressMovies90Days.xsp)"
  widget="$(skinvariables_node_path "${root}" skinvariables-shortcut-homewidgets.json)"
  tmdb="$(addon_data_path "${root}" plugin.video.themoviedb.helper)/settings.xml"
  nextpvr="$(addon_data_path "${root}" pvr.nextpvr)/instance-settings-1.xml"
  plex="$(addon_data_path "${root}" script.plexmod)/settings.xml"

  guisettings_before="$(sha256sum "${guisettings}")"
  skin_before="$(sha256sum "${skin_settings}")"
  weather_before="$(sha256sum "${weather_settings}")"
  playlist_before="$(sha256sum "${playlist}")"
  widget_before="$(sha256sum "${widget}")"
  tmdb_before="$(sha256sum "${tmdb}")"
  nextpvr_before="$(sha256sum "${nextpvr}")"
  plex_before="$(sha256sum "${plex}")"

  written="$(run_transform "${root}" "${payload}")"

  assert_eq "1" "$(xml_setting "${cec_path}" enabled)" \
    "CEC navigation remains enabled"
  assert_eq "0" "$(xml_setting "${cec_path}" activate_source)"
  assert_eq "231" "$(xml_setting "${cec_path}" wake_devices)"
  assert_eq "231" "$(xml_setting "${cec_path}" standby_devices)"
  assert_eq "0" "$(xml_setting "${cec_path}" standby_tv_on_pc_standby)"
  assert_eq "36028" "$(xml_setting "${cec_path}" standby_pc_on_tv_standby)"
  assert_eq "${guisettings_before}" "$(sha256sum "${guisettings}")"
  assert_eq "${skin_before}" "$(sha256sum "${skin_settings}")"
  assert_eq "${weather_before}" "$(sha256sum "${weather_settings}")"
  assert_eq "${playlist_before}" "$(sha256sum "${playlist}")"
  assert_eq "${widget_before}" "$(sha256sum "${widget}")"
  assert_eq "${tmdb_before}" "$(sha256sum "${tmdb}")"
  assert_eq "${nextpvr_before}" "$(sha256sum "${nextpvr}")"
  assert_eq "${plex_before}" "$(sha256sum "${plex}")"
  assert_eq "1" "$(applied_path_count "${written}" "${cec_path}")" \
    "the CEC path is reported exactly once"
  assert_eq "1" "$(printf '%s\n' "${written}" | grep -c '^settings applied: ')" \
    "CEC-only output contains exactly one changed path"

  first_cec="$(sha256sum "${cec_path}")"
  written="$(run_transform "${root}" "${payload}")"
  second_cec="$(sha256sum "${cec_path}")"
  assert_eq "${first_cec}" "${second_cec}" \
    "a second CEC-only transform is byte-identical"
  assert_eq "1" "$(applied_path_count "${written}" "${cec_path}")" \
    "the idempotent CEC rewrite is reported exactly once"
}

test_core_and_cec_transform_only_owned_surfaces() {
  local dir root payload cec_path guisettings skin_settings weather_settings
  local playlist widget tmdb nextpvr plex written
  local cec_before guisettings_before skin_before weather_before playlist_before
  local widget_before tmdb_before nextpvr_before plex_before
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  seed_scoped_settings_sentinels "${root}"
  write_scoped_base_payload "${payload}" 1 1 0 0 0

  cec_path="$(cec_settings_path "${root}")"
  guisettings="$(guisettings_path "${root}")"
  skin_settings="$(skin_settings_path "${root}")"
  weather_settings="$(addon_data_path "${root}" weather.ha)/settings.xml"
  playlist="$(video_playlist_path "${root}" InProgressMovies90Days.xsp)"
  widget="$(skinvariables_node_path "${root}" skinvariables-shortcut-homewidgets.json)"
  tmdb="$(addon_data_path "${root}" plugin.video.themoviedb.helper)/settings.xml"
  nextpvr="$(addon_data_path "${root}" pvr.nextpvr)/instance-settings-1.xml"
  plex="$(addon_data_path "${root}" script.plexmod)/settings.xml"

  cec_before="$(sha256sum "${cec_path}")"
  guisettings_before="$(sha256sum "${guisettings}")"
  skin_before="$(sha256sum "${skin_settings}")"
  weather_before="$(sha256sum "${weather_settings}")"
  playlist_before="$(sha256sum "${playlist}")"
  widget_before="$(sha256sum "${widget}")"
  tmdb_before="$(sha256sum "${tmdb}")"
  nextpvr_before="$(sha256sum "${nextpvr}")"
  plex_before="$(sha256sum "${plex}")"

  written="$(run_transform "${root}" "${payload}")"

  if [[ "${cec_before}" == "$(sha256sum "${cec_path}")" ]]; then
    printf 'the core+cec transform did not change the CEC surface\n' >&2
    return 1
  fi
  if [[ "${guisettings_before}" == "$(sha256sum "${guisettings}")" ]]; then
    printf 'the core+cec transform did not change the core guisettings surface\n' >&2
    return 1
  fi
  assert_eq "America/Los_Angeles" \
    "$(xml_setting "${guisettings}" locale.timezone)"
  assert_eq "skin.estuary" \
    "$(xml_setting "${guisettings}" lookandfeel.skin)" \
    "core leaves the skin-owned active-skin setting unchanged"
  assert_eq "36028" \
    "$(xml_setting "${cec_path}" standby_pc_on_tv_standby)"
  assert_eq "${skin_before}" "$(sha256sum "${skin_settings}")"
  assert_eq "${weather_before}" "$(sha256sum "${weather_settings}")"
  assert_eq "${playlist_before}" "$(sha256sum "${playlist}")"
  assert_eq "${widget_before}" "$(sha256sum "${widget}")"
  assert_eq "${tmdb_before}" "$(sha256sum "${tmdb}")"
  assert_eq "${nextpvr_before}" "$(sha256sum "${nextpvr}")"
  assert_eq "${plex_before}" "$(sha256sum "${plex}")"
  assert_eq "1" "$(applied_path_count "${written}" "${guisettings}")" \
    "the core guisettings path is reported exactly once"
  assert_eq "1" "$(applied_path_count "${written}" "${cec_path}")" \
    "the CEC path is reported exactly once"
  assert_eq "3" "$(printf '%s\n' "${written}" | grep -c '^settings applied: ')" \
    "core+cec output contains only guisettings, CEC, and timezone"
}

test_core_only_transform_does_not_validate_cec() {
  local dir root payload cec_path before written
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  cec_path="$(cec_settings_path "${root}")"
  mkdir -p "$(dirname "${cec_path}")"
  printf '<peripheral><setting id="sentinel" value="unchanged" /></peripheral>\n' \
    > "${cec_path}"
  write_scoped_base_payload "${payload}" 1 0 0 0 0
  before="$(sha256sum "${cec_path}")"

  written="$(run_transform "${root}" "${payload}")"

  assert_eq "${before}" "$(sha256sum "${cec_path}")" \
    "an unselected CEC file is neither validated nor rewritten"
  assert_eq "America/Los_Angeles" \
    "$(xml_setting "$(guisettings_path "${root}")" locale.timezone)"
  assert_eq "0" "$(applied_path_count "${written}" "${cec_path}")" \
    "an unselected CEC path is absent from transformer output"
}

test_component_payload_flags_are_strict_booleans() {
  local dir root payload output status
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_scoped_base_payload "${payload}" 0 1 0 yes 0
  write_cec_settings "${root}" "13011"

  set +e
  output="$(bash "${PROVISIONER}" --transform-fixture "${root}" "${payload}" 2>&1)"
  status=$?
  set -e

  assert_failure "${status}" "a non-boolean component flag must be rejected"
  assert_contains "${output}" "APPLY_COMPONENT_SERVICES" \
    "the invalid component key is identified without printing its value"
}

test_component_payload_requires_every_implemented_component() {
  local dir root payload output status
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_scoped_base_payload "${payload}" 0 1 0 0 0
  grep -v '^APPLY_COMPONENT_ADDONS=' "${payload}" > "${payload}.missing"
  mv "${payload}.missing" "${payload}"
  chmod 600 "${payload}"
  write_cec_settings "${root}" "13011"

  set +e
  output="$(bash "${PROVISIONER}" --transform-fixture "${root}" "${payload}" 2>&1)"
  status=$?
  set -e

  assert_failure "${status}" "a missing implemented component flag must be rejected"
  assert_contains "${output}" "APPLY_COMPONENT_ADDONS" \
    "the missing component key is identified"
}

test_host_payload_renders_every_effective_component() {
  local flags expected
  local TIMEZONE="" TIMEZONE_COUNTRY="" LOCALE_LANGUAGE="" LOCALE_COUNTRY=""
  local KEYBOARD_LAYOUT="" ADDON_UPDATE_MODE="" KODI_USER="" KODI_PORT=""
  local HOME_ASSISTANT_URL="" HOME_ASSISTANT_WEATHER_ENTITY=""
  local HOME_ASSISTANT_SUN_ENTITY="" NEXTPVR_HOST="" NEXTPVR_PORT=""
  local NEXTPVR_PROTOCOL="" NEXTPVR_INSTANCE_NAME="" KODI_WEB_PASSWORD=""

  load_provisioner_function coreelec_settings_payload
  coreelec_settings_payload_entry() {
    printf '%s=%s\n' "$1" "$2"
  }
  coreelec_settings_payload_secret() {
    :
  }
  coreelec_component_effective() {
    case "$1" in
      cec|addons) return 0 ;;
      *) return 1 ;;
    esac
  }

  flags="$(coreelec_settings_payload | grep '^APPLY_COMPONENT_' || true)"
  expected='APPLY_COMPONENT_CORE=0
APPLY_COMPONENT_CEC=1
APPLY_COMPONENT_ADDONS=1
APPLY_COMPONENT_SERVICES=0
APPLY_COMPONENT_SKIN=0
APPLY_COMPONENT_ROOM=0'
  assert_eq "${expected}" "${flags}" \
    "the settings payload carries one strict flag for every component"
}

test_cec_tv_off_action_is_changed_to_ignore() {
  local dir root payload
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_cec_settings "${root}" "13011"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  assert_eq "36028" "$(xml_setting "$(cec_settings_path "${root}")" standby_pc_on_tv_standby)" \
    "the CEC TV-off action is forced to Ignore"
  assert_eq "yes" "$(xml_setting_uses_value_attribute "$(cec_settings_path "${root}")" standby_pc_on_tv_standby)" \
    "Kodi peripheral LoadPersistedSettings reads only the value attribute"
}

test_cec_navigation_remains_enabled_without_tv_power_coupling() {
  local dir root payload cec_path
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  mkdir -p "${root}/.kodi/userdata/peripheral_data"
  cec_path="$(cec_settings_path "${root}")"
  cat > "${cec_path}" <<'XML'
<settings>
  <setting id="enabled" value="1" />
  <setting id="activate_source" value="1" />
  <setting id="wake_devices" value="36037" />
  <setting id="standby_devices" value="36037" />
  <setting id="standby_tv_on_pc_standby" value="1" />
  <setting id="standby_pc_on_tv_standby" value="13011" />
</settings>
XML
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  assert_eq "1" "$(xml_setting "${cec_path}" enabled)" \
    "CEC remains enabled for navigation"
  assert_eq "0" "$(xml_setting "${cec_path}" activate_source)" \
    "Kodi startup does not make itself the active source"
  assert_eq "231" "$(xml_setting "${cec_path}" wake_devices)" \
    "Kodi startup wakes no HDMI devices"
  assert_eq "231" "$(xml_setting "${cec_path}" standby_devices)" \
    "Kodi shutdown puts no HDMI devices in standby"
  assert_eq "0" "$(xml_setting "${cec_path}" standby_tv_on_pc_standby)" \
    "Kodi shutdown does not power off the TV"
  assert_eq "36028" "$(xml_setting "${cec_path}" standby_pc_on_tv_standby)" \
    "TV standby remains ignored by the always-awake CoreELEC host"
}

test_cec_text_only_setting_is_repaired_to_kodi_attribute() {
  local dir root payload
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_cec_settings "${root}" "13011"
  printf '<settings><setting id="standby_pc_on_tv_standby">36028</setting></settings>\n' \
    > "$(cec_settings_path "${root}")"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  assert_eq "yes" "$(xml_setting_uses_value_attribute "$(cec_settings_path "${root}")" standby_pc_on_tv_standby)" \
    "repair the earlier text-only deployment rather than certifying it"
  assert_eq "36028" "$(xml_setting "$(cec_settings_path "${root}")" standby_pc_on_tv_standby)"
}

test_cec_nested_setting_is_repaired_to_direct_child() {
  local dir root payload value
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_cec_settings "${root}" "13011"
  printf '<settings><category><setting id="standby_pc_on_tv_standby" value="13011" /></category></settings>\n' \
    > "$(cec_settings_path "${root}")"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null
  value="$(python3 - "$(cec_settings_path "${root}")" <<'PY'
import sys
import xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
node = root.find("./setting[@id='standby_pc_on_tv_standby']")
print(node.get("value", "") if node is not None else "")
PY
)"
  assert_eq "36028" "${value}" "Kodi reads direct child peripheral settings only"
}

test_cec_transform_preserves_unmanaged_peripheral_settings() {
  local dir root payload cec_path
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  mkdir -p "${root}/.kodi/userdata/peripheral_data"
  cec_path="$(cec_settings_path "${root}")"
  cat > "${cec_path}" <<'XML'
<settings><setting id="activate_source" value="0" /><setting id="standby_pc_on_tv_standby" value="13011" /></settings>
XML
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  assert_eq "36028" "$(xml_setting "${cec_path}" standby_pc_on_tv_standby)" \
    "the managed CEC setting is changed"
  assert_eq "0" "$(xml_setting "${cec_path}" activate_source)" \
    "an unrelated CEC peripheral setting is untouched"
}

test_duplicate_cec_tv_off_actions_are_collapsed() {
  local dir root payload cec_path
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  mkdir -p "${root}/.kodi/userdata/peripheral_data"
  cec_path="$(cec_settings_path "${root}")"
  cat > "${cec_path}" <<'XML'
<settings><setting id="standby_pc_on_tv_standby" value="13011" /><setting id="standby_pc_on_tv_standby" value="10000" /></settings>
XML
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  assert_eq "1" "$(xml_setting_count "${cec_path}" standby_pc_on_tv_standby)" \
    "one standby_pc_on_tv_standby node remains"
  assert_eq "36028" "$(xml_setting "${cec_path}" standby_pc_on_tv_standby)" \
    "the surviving node carries the Ignore value"
}

test_second_cec_transform_is_byte_identical() {
  local dir root payload cec_path first second
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_cec_settings "${root}" "13011"
  write_base_payload "${payload}"
  cec_path="$(cec_settings_path "${root}")"

  run_transform "${root}" "${payload}" >/dev/null
  first="$(sha256sum "${cec_path}")"
  run_transform "${root}" "${payload}" >/dev/null
  second="$(sha256sum "${cec_path}")"
  assert_eq "${first}" "${second}" "a second CEC transform rewrites nothing"
}

test_missing_cec_adapter_file_fails_loudly() {
  local dir root payload output status
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"

  # No peripheral file at all: call the provisioner directly, bypassing
  # run_transform's default CEC seeding, which exists for unrelated tests only.
  set +e
  output="$(bash "${PROVISIONER}" --transform-fixture "${root}" "${payload}" 2>&1)"
  status=$?
  set -e

  assert_failure "${status}" "a missing CEC peripheral file must fail loudly"
  assert_contains "${output}" "peripheral_data" "the error names the peripheral_data directory"
}

test_multiple_cec_adapter_files_fail_loudly() {
  local dir root payload output status peripheral_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  write_cec_settings "${root}" "13011"
  peripheral_dir="${root}/.kodi/userdata/peripheral_data"
  printf '<settings><setting id="standby_pc_on_tv_standby" value="13011" /></settings>\n' \
    > "${peripheral_dir}/cec_CEC_Adapter_2.xml"

  set +e
  output="$(bash "${PROVISIONER}" --transform-fixture "${root}" "${payload}" 2>&1)"
  status=$?
  set -e

  assert_failure "${status}" "an ambiguous CEC peripheral file set must fail loudly"
  assert_contains "${output}" "peripheral_data" "the error names the peripheral_data directory"
}

test_malformed_cec_adapter_file_fails_loudly() {
  local dir root payload cec_path output status
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"
  cec_path="$(cec_settings_path "${root}")"
  mkdir -p "$(dirname "${cec_path}")"
  # Well-formed XML, but the wrong document shape: not a <settings> root.
  printf '<peripheral><setting id="standby_pc_on_tv_standby" value="13011" /></peripheral>\n' \
    > "${cec_path}"

  set +e
  output="$(bash "${PROVISIONER}" --transform-fixture "${root}" "${payload}" 2>&1)"
  status=$?
  set -e

  assert_failure "${status}" "a structurally invalid CEC document must fail loudly"
  assert_contains "${output}" "unexpected root element" \
    "the error names the shape defect, not just a parse failure"
}

test_cec_settings_file_mode_is_private() {
  local dir root payload
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_cec_settings "${root}" "13011"
  chmod 644 "$(cec_settings_path "${root}")"
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  assert_eq "600" "$(file_mode "$(cec_settings_path "${root}")")" \
    "the CEC settings file is private after being rewritten"
}

test_remote_backup_includes_peripheral_data() {
  local dir root script backup
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  write_cec_settings "${root}" "36028"

  script="$(bash "${PROVISIONER}" --emit-remote-script backup "${root}")"
  backup="$(umask 022; printf '%s\n' "${script}" | sh -s)"

  if [[ ! -f "${backup}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml" ]]; then
    printf 'the backup must copy the CEC peripheral settings file\n' >&2
    return 1
  fi
  assert_eq "600" "$(file_mode "${backup}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml")" \
    "the CEC peripheral backup copy is private"
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

test_services_only_configured_weather_changes_provider() {
  local dir root payload settings written
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/services.conf"
  seed_guisettings "${root}"
  write_scoped_full_payload "${payload}" 0 0 0 1 0

  written="$(run_transform "${root}" "${payload}")"
  settings="$(guisettings_path "${root}")"

  assert_eq "weather.ha" "$(xml_setting "${settings}" weather.addon)" \
    "services owns the configured weather provider" || return 1
  assert_eq "skin.estuary" "$(xml_setting "${settings}" lookandfeel.skin)" \
    "services leaves the skin-owned setting unchanged" || return 1
  assert_eq "Europe/Berlin" "$(xml_setting "${settings}" locale.timezone)" \
    "services leaves core-owned settings unchanged" || return 1
  assert_eq "1" "$(applied_path_count "${written}" "${settings}")" \
    "services reports the guisettings provider update exactly once"
}

test_core_only_configured_weather_leaves_provider_unchanged() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/core.conf"
  seed_guisettings "${root}"
  write_scoped_full_payload "${payload}" 1 0 0 0 0

  run_transform "${root}" "${payload}" >/dev/null
  settings="$(guisettings_path "${root}")"

  assert_eq "weather.gismeteo" "$(xml_setting "${settings}" weather.addon)" \
    "core leaves the services-owned weather provider unchanged" || return 1
  assert_eq "America/Los_Angeles" "$(xml_setting "${settings}" locale.timezone)" \
    "the selected core settings still converge"
}

test_pm4k_local_mode_settings_are_removed() {
  local dir root payload settings setting_id
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  settings="$(addon_data_path "${root}" script.plexmod)/settings.xml"
  mkdir -p "$(dirname "${settings}")"
  cat > "${settings}" <<'XML'
<settings version="2">
    <setting id="allow_insecure">always</setting>
    <setting id="local_mode">true</setting>
    <setting id="local_servers_json">[{"token":"legacy-secret"}]</setting>
    <setting id="local_profiles_json">["11"]</setting>
    <setting id="unmanaged_setting">preserved</setting>
</settings>
XML
  write_base_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  for setting_id in allow_insecure local_mode local_servers_json local_profiles_json; do
    assert_eq "0" "$(xml_setting_count "${settings}" "${setting_id}")" \
      "legacy PM4K ${setting_id} is removed" || return 1
  done
  assert_eq "preserved" "$(xml_setting "${settings}" unmanaged_setting)" \
    "unmanaged PM4K settings are preserved"
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
    "$(addon_data_path "${root}" weather.ha)/settings.xml"; do
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
    "home-assistant-token-secret" \
    "nextpvr-pin-secret"; do
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
  local dir root payload ha_dir
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"

  # The mode must come from the transformer, never from whatever umask the
  # calling shell happened to have.
  (umask 000; run_transform "${root}" "${payload}" >/dev/null)

  ha_dir="$(addon_data_path "${root}" weather.ha)"
  assert_eq "600" "$(file_mode "$(guisettings_path "${root}")")" "guisettings.xml"
  assert_eq "600" "$(file_mode "$(addon_data_path "${root}" weather.ha)/settings.xml")" "weather.ha settings"
  assert_eq "644" "$(file_mode "${root}/.cache/timezone")" "the timezone cache stays readable on purpose"
  assert_eq "700" "$(file_mode "${ha_dir}")" "add-on data directories are private"
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

  # A directory where settings.xml belongs makes the final rename fail after
  # the secret bytes have already been written to the temp file.
  mkdir -p "$(addon_data_path "${root}" weather.ha)/settings.xml"

  set +e
  output="$(run_transform "${root}" "${payload}" 2>&1)"
  status=$?
  set -e

  assert_failure "${status}" "an unwritable target must fail loudly"
  assert_eq "" "$(orphan_temp_files "${root}")" "a failed write must not orphan a secret temp file"
  assert_eq "" "$(files_containing "${root}" "home-assistant-token-secret")" "no file under the root retains the secret"
  assert_not_contains "${output}" "home-assistant-token-secret" "the failure output must not leak a secret"
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
    "limit": "0",
    "rules": [],
    "order": [],
}
name_node = root.find("name")
if name_node is not None:
    result["name"] = name_node.text or ""
match_node = root.find("match")
if match_node is not None:
    result["match"] = match_node.text or ""
limit_node = root.find("limit")
if limit_node is not None:
    result["limit"] = limit_node.text or "0"
for rule in root.findall("rule"):
    value_node = rule.find("value")
    result["rules"].append([
        rule.get("field", ""),
        rule.get("operator", ""),
        (value_node.text or "") if value_node is not None else "",
    ])
order_node = root.find("order")
if order_node is not None:
    result["order"] = [order_node.text or "", order_node.get("direction", "")]
sys.stdout.write(json.dumps(result, sort_keys=True, separators=(',', ':')))
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

# Prints "TOTAL AT_ROOT" for one setting ID, matched case-insensitively the
# way Kodi resolves `Skin.String`. Kodi only reads the direct `<setting>`
# children of the settings root, so a managed value that survives anywhere
# else is invisible to the skin even though a recursive reader finds it.
xml_setting_scope_counts() {
  python3 - "$1" "$2" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path, setting_id = sys.argv[1], sys.argv[2]
root = ET.parse(path).getroot()
wanted = setting_id.casefold()
total = sum(1 for node in root.iter("setting")
            if (node.get("id") or "").casefold() == wanted)
at_root = sum(1 for node in root.findall("setting")
              if (node.get("id") or "").casefold() == wanted)
sys.stdout.write("%d %d" % (total, at_root))
PYEOF
}

skin_setting_scope_counts() {
  xml_setting_scope_counts "$(skin_settings_path "$1")" "$2"
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

  # Seed skin settings with unrelated.keep=yes, duplicate/case-variant
  # settings, and stale managed values that must be removed.
  mkdir -p "$(dirname "$(skin_settings_path "${root}")")"
  cat > "$(skin_settings_path "${root}")" <<'XML'
<?xml version='1.0' encoding='UTF-8'?>
<settings>
    <setting id="unrelated.keep">yes</setting>
    <setting id="HomeSwitcher.1101.Toggle">false</setting>
    <setting id="homeswitcher.1101.toggle">stale-case-variant</setting>
    <setting id="HomeSwitcher.1101.Shortcut.Path">old-shortcut-path</setting>
    <setting id="HomeSwitcher.1101.Shortcut.Target">oldplex</setting>
    <setting id="HomeSwitcher.1101.Spotlight.Path">old-spotlight</setting>
    <setting id="HomeSwitcher.1102.Name">YouTube</setting>
    <setting id="HomeSwitcher.1102.Toggle">true</setting>
    <setting id="HomeSwitcher.1102.Shortcut.Path">RunAddon(plugin.video.youtube)</setting>
    <setting id="HomeSwitcher.1102.Shortcut.Target">videos</setting>
    <setting id="HomeSwitcher.1103.Shortcut.Target">videos</setting>
    <setting id="HomeSwitcher.1103.Spotlight.Label">Old Plex Spotlight</setting>
    <setting id="HomeSwitcher.1103.Spotlight.Path">old-plex-spotlight</setting>
    <setting id="HomeSwitcher.1103.Spotlight.Target">videos</setting>
    <setting id="HomeSwitcher.1104.Name">YouTube</setting>
    <setting id="HomeSwitcher.1104.Toggle">true</setting>
    <setting id="HomeSwitcher.1104.Icon">old-1104-icon</setting>
    <setting id="HomeSwitcher.1104.Mode">Standard</setting>
    <setting id="HomeSwitcher.1104.Shortcut.Path">RunAddon(plugin.video.youtube)</setting>
    <setting id="HomeSwitcher.1104.Shortcut.Target">videos</setting>
    <setting id="HomeSwitcher.1104.Spotlight.Label">Old 1104 Spotlight</setting>
    <setting id="HomeSwitcher.1104.Spotlight.Path">old-1104-spotlight</setting>
    <setting id="HomeSwitcher.1104.Spotlight.Target">videos</setting>
    <setting id="HomeSwitcher.1107.Toggle">false</setting>
    <setting id="Hub.1107.DisableSearch">true</setting>
    <setting id="Hub.1107.DisableChannels">true</setting>
    <setting id="Hub.1107.DisableGroups">true</setting>
    <setting id="Hub.1107.DisableRecordings">true</setting>
</settings>
XML

  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  skin_file="$(skin_settings_path "${root}")"

  # Unrelated setting is preserved exactly once
  assert_eq "yes" "$(xml_setting "${skin_file}" "unrelated.keep")" "unrelated.keep preserved"
  assert_eq "1" "$(xml_setting_count "${skin_file}" "unrelated.keep")" "unrelated.keep not duplicated"

  # Canonical settings
  assert_eq "TV Shows" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Name")" "1101.Name"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Toggle")" "1101.Toggle"
  assert_eq "special://skin/extras/icons/tv.png" \
    "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Icon")" "1101.Icon"
  assert_eq "Movies" "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Name")" "1102.Name"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Toggle")" "1102.Toggle"
  assert_eq "Plex" "$(xml_setting "${skin_file}" "HomeSwitcher.1103.Name")" "1103.Name"
  assert_eq "RunAddon(script.plexmod)" \
    "$(xml_setting "${skin_file}" "HomeSwitcher.1103.Shortcut.Path")" "1103.Shortcut.Path"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1107.Toggle")" "1107.Toggle"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1108.Toggle")" "1108.Toggle"
  assert_eq "NowPlaying" "$(xml_setting "${skin_file}" "optionstiles.01.include")" "optionstiles.01"
  assert_eq "Settings" "$(xml_setting "${skin_file}" "optionstiles.02.include")" "optionstiles.02"
  assert_eq "Weather" "$(xml_setting "${skin_file}" "optionstiles.03.include")" "optionstiles.03"
  assert_eq "SystemInfo" "$(xml_setting "${skin_file}" "optionstiles.04.include")" "optionstiles.04"

  # Duplicate/case-variant collapsed — only 1 node for 1101.Toggle
  assert_eq "1" "$(xml_setting_count "${skin_file}" "HomeSwitcher.1101.Toggle")" \
    "duplicate 1101.Toggle collapsed"

  # Managed custom hubs own these slot shapes exactly.
  for setting_id in \
    "HomeSwitcher.1101.Shortcut.Path" \
    "HomeSwitcher.1101.Shortcut.Target" \
    "HomeSwitcher.1102.Shortcut.Path" \
    "HomeSwitcher.1102.Shortcut.Target" \
    "HomeSwitcher.1103.Shortcut.Target" \
    "HomeSwitcher.1103.Spotlight.Label" \
    "HomeSwitcher.1103.Spotlight.Path" \
    "HomeSwitcher.1103.Spotlight.Target" \
    "HomeSwitcher.1104.Name" \
    "HomeSwitcher.1104.Toggle" \
    "HomeSwitcher.1104.Icon" \
    "HomeSwitcher.1104.Mode" \
    "HomeSwitcher.1104.Shortcut.Path" \
    "HomeSwitcher.1104.Shortcut.Target" \
    "HomeSwitcher.1104.Spotlight.Label" \
    "HomeSwitcher.1104.Spotlight.Path" \
    "HomeSwitcher.1104.Spotlight.Target" \
    "Hub.1107.DisableSearch" \
    "Hub.1107.DisableChannels" \
    "Hub.1107.DisableGroups" \
    "Hub.1107.DisableRecordings"; do
    skin_setting_absent "${root}" "${setting_id}" \
      || { printf '%s must be absent\n' "${setting_id}" >&2; return 1; }
  done
}

# The Weather tile owns all three of its fields. A stale `.path` or `.target`
# left beside a managed `.include` still points the tile at whatever the
# previous profile configured, so both are removed in the configured branch
# exactly as they are in the unconfigured one.
test_arctic_fuse_configured_weather_tile_clears_stale_path_and_target() {
  local dir root payload skin_file setting_id
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"

  mkdir -p "$(dirname "$(skin_settings_path "${root}")")"
  cat > "$(skin_settings_path "${root}")" <<'XML'
<?xml version='1.0' encoding='UTF-8'?>
<settings>
    <setting id="optionstiles.03.include">Old Weather</setting>
    <setting id="optionstiles.03.path">stale-weather-path</setting>
    <setting id="optionstiles.03.target">stale-weather-target</setting>
</settings>
XML

  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  skin_file="$(skin_settings_path "${root}")"
  assert_eq "Weather" "$(xml_setting "${skin_file}" "optionstiles.03.include")" \
    "the configured Weather tile keeps its managed include"
  for setting_id in "optionstiles.03.path" "optionstiles.03.target"; do
    skin_setting_absent "${root}" "${setting_id}" \
      || { printf '%s must be absent\n' "${setting_id}" >&2; return 1; }
  done
}

test_arctic_fuse_pvr_and_weather_are_absent_when_unconfigured() {
  local dir root payload skin_file setting_id
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"

  mkdir -p "$(dirname "$(skin_settings_path "${root}")")"
  cat > "$(skin_settings_path "${root}")" <<'XML'
<?xml version='1.0' encoding='UTF-8'?>
<settings>
    <setting id="HomeSwitcher.1107.Toggle">true</setting>
    <setting id="optionstiles.03.include">Weather</setting>
    <setting id="optionstiles.03.path">stale-weather-path</setting>
    <setting id="optionstiles.03.target">stale-weather-target</setting>
</settings>
XML

  write_full_payload "${payload}"
  append_payload_entry "${payload}" "NEXTPVR_HOST" ""
  append_payload_entry "${payload}" "HAVE_NEXTPVR_PIN" "0"
  append_payload_entry "${payload}" "HOME_ASSISTANT_URL" ""
  append_payload_entry "${payload}" "HOME_ASSISTANT_WEATHER_ENTITY" ""
  append_payload_entry "${payload}" "HAVE_HOME_ASSISTANT_TOKEN" "0"
  run_transform "${root}" "${payload}" >/dev/null

  skin_file="$(skin_settings_path "${root}")"

  skin_setting_absent "${root}" "HomeSwitcher.1107.Toggle" \
    || { printf 'HomeSwitcher.1107.Toggle must be absent\n' >&2; return 1; }
  for setting_id in \
    "optionstiles.03.include" \
    "optionstiles.03.path" \
    "optionstiles.03.target"; do
    skin_setting_absent "${root}" "${setting_id}" \
      || { printf '%s must be absent\n' "${setting_id}" >&2; return 1; }
  done

  assert_eq "TV Shows" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Name")" "1101.Name survives"
  assert_eq "Movies" "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Name")" "1102.Name survives"
  assert_eq "Plex" "$(xml_setting "${skin_file}" "HomeSwitcher.1103.Name")" "1103.Name survives"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1108.Toggle")" "1108.Toggle survives"
  assert_eq "NowPlaying" "$(xml_setting "${skin_file}" "optionstiles.01.include")" "optionstiles.01 survives"
  assert_eq "Settings" "$(xml_setting "${skin_file}" "optionstiles.02.include")" "optionstiles.02 survives"
  assert_eq "SystemInfo" "$(xml_setting "${skin_file}" "optionstiles.04.include")" "optionstiles.04 survives"
}

# Kodi reads only the direct `<setting>` children of a skin settings root,
# while the verifier reads the document recursively. A managed value left
# inside a legacy `<category>` would therefore be invisible to the skin and
# still look converged, so convergence must promote every managed setting to
# exactly one canonical root node and leave unmanaged nesting alone.
test_arctic_fuse_managed_settings_are_promoted_to_root_nodes() {
  local dir root payload skin_file first second setting_id
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"

  mkdir -p "$(dirname "$(skin_settings_path "${root}")")"
  cat > "$(skin_settings_path "${root}")" <<'XML'
<?xml version='1.0' encoding='UTF-8'?>
<settings>
    <category id="hubs">
        <setting id="HomeSwitcher.1101.Name">Old Plex</setting>
        <setting id="HomeSwitcher.1102.Name">YouTube</setting>
        <setting id="HomeSwitcher.1103.Name">Old Plex</setting>
        <setting id="HomeSwitcher.1107.Toggle">false</setting>
        <setting id="homeswitcher.1108.toggle">stale-case-variant</setting>
        <setting id="optionstiles.01.include">Old NowPlaying</setting>
        <setting id="optionstiles.02.include">Old Settings</setting>
        <setting id="optionstiles.03.include">Old Weather</setting>
        <setting id="optionstiles.04.include">Old SystemInfo</setting>
        <setting id="HomeSwitcher.1101.Shortcut.Path">oldplex</setting>
        <setting id="HomeSwitcher.1101.Shortcut.Target">videos</setting>
        <setting id="HomeSwitcher.1102.Shortcut.Path">RunAddon(plugin.video.youtube)</setting>
        <setting id="HomeSwitcher.1102.Shortcut.Target">videos</setting>
        <setting id="HomeSwitcher.1103.Shortcut.Target">videos</setting>
        <setting id="HomeSwitcher.1103.Spotlight.Label">Old Plex Spotlight</setting>
        <setting id="HomeSwitcher.1103.Spotlight.Path">old-plex-spotlight</setting>
        <setting id="HomeSwitcher.1103.Spotlight.Target">videos</setting>
        <setting id="HomeSwitcher.1104.Name">Stale 1104</setting>
        <setting id="HomeSwitcher.1104.Toggle">true</setting>
        <setting id="HomeSwitcher.1104.Icon">old-icon</setting>
        <setting id="HomeSwitcher.1104.Mode">Standard</setting>
        <setting id="HomeSwitcher.1104.Shortcut.Path">old-1104-path</setting>
        <setting id="HomeSwitcher.1104.Shortcut.Target">videos</setting>
        <setting id="HomeSwitcher.1104.Spotlight.Label">Old 1104 Spotlight</setting>
        <setting id="HomeSwitcher.1104.Spotlight.Path">old-1104-spotlight</setting>
        <setting id="HomeSwitcher.1104.Spotlight.Target">videos</setting>
        <setting id="Hub.1107.DisableSearch">true</setting>
        <setting id="Hub.1107.DisableChannels">true</setting>
        <setting id="Hub.1107.DisableGroups">true</setting>
        <setting id="Hub.1107.DisableRecordings">true</setting>
        <setting id="unrelated.nested.keep">yes</setting>
    </category>
</settings>
XML

  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null
  skin_file="$(skin_settings_path "${root}")"

  # Each managed setting converges to exactly one node, and that node is a
  # direct child of the settings root.
  for setting_id in \
    "HomeSwitcher.1101.Name" \
    "HomeSwitcher.1101.Toggle" \
    "HomeSwitcher.1101.Icon" \
    "HomeSwitcher.1101.Mode" \
    "HomeSwitcher.1101.Spotlight.Label" \
    "HomeSwitcher.1101.Spotlight.Path" \
    "HomeSwitcher.1101.Spotlight.Target" \
    "HomeSwitcher.1102.Name" \
    "HomeSwitcher.1102.Toggle" \
    "HomeSwitcher.1102.Icon" \
    "HomeSwitcher.1102.Mode" \
    "HomeSwitcher.1102.Spotlight.Label" \
    "HomeSwitcher.1102.Spotlight.Path" \
    "HomeSwitcher.1102.Spotlight.Target" \
    "HomeSwitcher.1103.Name" \
    "HomeSwitcher.1103.Toggle" \
    "HomeSwitcher.1103.Icon" \
    "HomeSwitcher.1103.Shortcut.Path" \
    "HomeSwitcher.1107.Toggle" \
    "HomeSwitcher.1108.Toggle" \
    "optionstiles.01.include" \
    "optionstiles.02.include" \
    "optionstiles.03.include" \
    "optionstiles.04.include"; do
    assert_eq "1 1" "$(skin_setting_scope_counts "${root}" "${setting_id}")" \
      "${setting_id} is one root node"
  done
  assert_eq "TV Shows" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Name")" \
    "promoted 1101.Name carries the managed value"
  assert_eq "Movies" "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Name")" \
    "promoted 1102.Name carries the managed value"
  assert_eq "Plex" "$(xml_setting "${skin_file}" "HomeSwitcher.1103.Name")" \
    "promoted 1103.Name carries the managed value"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1107.Toggle")" \
    "promoted 1107.Toggle carries the managed value"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1108.Toggle")" \
    "promoted 1108.Toggle carries the managed value"

  # Removed managed settings are gone from every scope.
  for setting_id in \
    "HomeSwitcher.1101.Shortcut.Path" \
    "HomeSwitcher.1101.Shortcut.Target" \
    "HomeSwitcher.1102.Shortcut.Path" \
    "HomeSwitcher.1102.Shortcut.Target" \
    "HomeSwitcher.1103.Shortcut.Target" \
    "HomeSwitcher.1103.Spotlight.Label" \
    "HomeSwitcher.1103.Spotlight.Path" \
    "HomeSwitcher.1103.Spotlight.Target" \
    "HomeSwitcher.1104.Name" \
    "HomeSwitcher.1104.Toggle" \
    "HomeSwitcher.1104.Icon" \
    "HomeSwitcher.1104.Mode" \
    "HomeSwitcher.1104.Shortcut.Path" \
    "HomeSwitcher.1104.Shortcut.Target" \
    "HomeSwitcher.1104.Spotlight.Label" \
    "HomeSwitcher.1104.Spotlight.Path" \
    "HomeSwitcher.1104.Spotlight.Target" \
    "Hub.1107.DisableSearch" \
    "Hub.1107.DisableChannels" \
    "Hub.1107.DisableGroups" \
    "Hub.1107.DisableRecordings"; do
    assert_eq "0 0" "$(skin_setting_scope_counts "${root}" "${setting_id}")" \
      "${setting_id} is removed everywhere"
  done

  # Unmanaged nested state is left exactly where the skin put it.
  assert_eq "1 0" "$(skin_setting_scope_counts "${root}" "unrelated.nested.keep")" \
    "an unmanaged nested setting is preserved in place"

  # Convergence is still a transaction that reaches a fixed point.
  first="$(cat "${skin_file}")"
  run_transform "${root}" "${payload}" >/dev/null
  second="$(cat "${skin_file}")"
  assert_eq "${first}" "${second}" "a second run over promoted settings changes nothing"
}

test_arctic_fuse_deeply_nested_managed_settings_are_promoted_to_root_nodes() {
  local dir root payload skin_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"

  mkdir -p "$(dirname "$(skin_settings_path "${root}")")"
  cat > "$(skin_settings_path "${root}")" <<'XML'
<?xml version='1.0' encoding='UTF-8'?>
<settings>
    <category id="outer">
        <group>
            <category id="inner">
                <setting id="HomeSwitcher.1101.Name">Old Plex</setting>
                <setting id="homeswitcher.1101.name">stale-case-variant</setting>
                <setting id="HomeSwitcher.1107.Toggle">false</setting>
                <setting id="HomeSwitcher.1101.Shortcut.Target">videos</setting>
                <setting id="unrelated.deep.keep">yes</setting>
            </category>
        </group>
    </category>
</settings>
XML

  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null
  skin_file="$(skin_settings_path "${root}")"

  assert_eq "1 1" "$(skin_setting_scope_counts "${root}" "HomeSwitcher.1101.Name")" \
    "deeply nested 1101.Name converges to one root node"
  assert_eq "1 1" "$(skin_setting_scope_counts "${root}" "HomeSwitcher.1107.Toggle")" \
    "deeply nested 1107.Toggle converges to one root node"
  assert_eq "0 0" "$(skin_setting_scope_counts "${root}" "HomeSwitcher.1101.Shortcut.Target")" \
    "deeply nested managed removals apply everywhere"
  assert_eq "TV Shows" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Name")" \
    "deeply nested 1101.Name carries the managed value"
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1107.Toggle")" \
    "deeply nested 1107.Toggle carries the managed value"

  assert_eq "1 0" "$(skin_setting_scope_counts "${root}" "unrelated.deep.keep")" \
    "deeply nested unmanaged state is preserved in place"
  assert_eq "yes" "$(xml_setting "${skin_file}" "unrelated.deep.keep")" \
    "deeply nested unmanaged state keeps its value"
}

test_arctic_fuse_home_widgets_are_exact_and_ordered() {
  local dir root payload home_json expected actual
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  home_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-homewidgets.json")"
  [[ -f "${home_json}" ]] || { printf 'home widgets JSON not found\n' >&2; return 1; }

  expected='[{"guid": "coreelec-home-inprogress-movies", "icon": "", "label": "In-Progress Movies", "path": "special://profile/playlists/video/InProgressMovies90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-inprogress-shows", "icon": "", "label": "In-Progress Shows", "path": "special://profile/playlists/video/InProgressShows90Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-aired-shows", "icon": "", "label": "Recently Aired Shows", "path": "special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp", "target": "videos"}, {"guid": "coreelec-home-recently-released-movies", "icon": "", "label": "Recently Released Movies", "path": "special://profile/playlists/video/RecentlyReleasedMoviesCurrentAndPreviousYear.xsp", "target": "videos"}, {"guid": "coreelec-home-new-shows", "icon": "", "label": "New Shows", "path": "special://profile/playlists/video/NewShows.xsp", "target": "videos"}, {"guid": "coreelec-home-new-movies", "icon": "", "label": "New Movies", "path": "special://profile/playlists/video/NewMovies.xsp", "target": "videos"}]'
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

test_arctic_fuse_hub_widgets_are_exact_and_ordered() {
  local dir root payload tv_json movies_json expected actual
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  tv_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-1101widgets.json")"
  [[ -f "${tv_json}" ]] || { printf 'TV widgets JSON not found\n' >&2; return 1; }
  expected='[{"guid": "coreelec-tv-inprogress", "icon": "", "label": "In-Progress Shows", "path": "special://profile/playlists/video/InProgressShows90Days.xsp", "target": "videos"}, {"guid": "coreelec-tv-recently-aired", "icon": "", "label": "Recently Aired Shows", "path": "special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp", "target": "videos"}, {"guid": "coreelec-tv-trakt-popular", "icon": "", "label": "Trakt Popular TV Shows", "path": "special://profile/playlists/video/TraktPopularTVShows.xsp", "target": "videos"}, {"guid": "coreelec-tv-new", "icon": "", "label": "New Shows", "path": "special://profile/playlists/video/NewShows.xsp", "target": "videos"}]'
  actual="$(python3 -c 'import json,sys; sys.stdout.write(json.dumps(json.load(open(sys.argv[1])),sort_keys=False))' "${tv_json}")"
  assert_eq "${expected}" "${actual}" "TV widgets JSON content"

  movies_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-1102widgets.json")"
  [[ -f "${movies_json}" ]] || { printf 'Movies widgets JSON not found\n' >&2; return 1; }
  expected='[{"guid": "coreelec-movies-inprogress", "icon": "", "label": "In-Progress Movies", "path": "special://profile/playlists/video/InProgressMovies90Days.xsp", "target": "videos"}, {"guid": "coreelec-movies-recently-released", "icon": "", "label": "Recently Released Movies", "path": "special://profile/playlists/video/RecentlyReleasedMoviesCurrentAndPreviousYear.xsp", "target": "videos"}, {"guid": "coreelec-movies-trakt-box-office", "icon": "", "label": "Trakt Weekend Box Office", "path": "special://profile/playlists/video/TraktWeekendBoxOffice.xsp", "target": "videos"}, {"guid": "coreelec-movies-new", "icon": "", "label": "New Movies", "path": "special://profile/playlists/video/NewMovies.xsp", "target": "videos"}]'
  actual="$(python3 -c 'import json,sys; sys.stdout.write(json.dumps(json.load(open(sys.argv[1])),sort_keys=False))' "${movies_json}")"
  assert_eq "${expected}" "${actual}" "Movies widgets JSON content"
}

test_arctic_fuse_power_menu_is_coreelec_appropriate() {
  local dir root payload power_json expected actual raw
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_full_payload "${payload}"
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
  local dir root payload summary current_year lower_bound upper_bound expected_recent
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
  assert_eq \
    '{"limit":"50","match":"all","name":"Recently Aired Shows","order":["year","descending"],"rules":[["airdate","inthelast","30 days"],["airdate","notinthelast","-1 days"]],"type":"episodes"}' \
    "${summary}" \
    "Recently Aired Shows exact XSP"

  # TraktPopularTVShows.xsp
  summary="$(smart_playlist_summary "$(video_playlist_path "${root}" TraktPopularTVShows.xsp)")"
  assert_eq \
    '{"limit":"25","match":"all","name":"Trakt Popular TV Shows","order":["dateadded","descending"],"rules":[["tag","contains","trakt-popular"]],"type":"tvshows"}' \
    "${summary}" \
    "Trakt Popular TV Shows exact XSP"

  # RecentlyReleasedMoviesCurrentAndPreviousYear.xsp
  current_year="$(python3 -c 'import datetime; print(datetime.date.today().year)')"
  lower_bound="$((current_year - 2))"
  upper_bound="$((current_year + 1))"
  expected_recent="$(printf '{"limit":"50","match":"all","name":"Recently Released Movies","order":["year","descending"],"rules":[["year","greaterthan","%s"],["year","lessthan","%s"]],"type":"movies"}' "${lower_bound}" "${upper_bound}")"
  summary="$(smart_playlist_summary "$(video_playlist_path "${root}" RecentlyReleasedMoviesCurrentAndPreviousYear.xsp)")"
  assert_eq "${expected_recent}" "${summary}" \
    "Recently Released Movies exact XSP"

  # TraktWeekendBoxOffice.xsp
  summary="$(smart_playlist_summary "$(video_playlist_path "${root}" TraktWeekendBoxOffice.xsp)")"
  assert_eq \
    '{"limit":"25","match":"all","name":"Trakt Weekend Box Office","order":["dateadded","descending"],"rules":[["tag","contains","trakt-weekend-box-office"]],"type":"movies"}' \
    "${summary}" \
    "Trakt Weekend Box Office exact XSP"

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
  local dir root payload skin_file home_json tv_json movies_json power_json
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

  tv_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-1101widgets.json")"
  assert_eq "600" "$(file_mode "${tv_json}")" "TV widgets mode"

  movies_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-1102widgets.json")"
  assert_eq "600" "$(file_mode "${movies_json}")" "Movies widgets mode"

  power_json="$(skinvariables_node_path "${root}" "skinvariables-shortcut-powermenu.json")"
  assert_eq "600" "$(file_mode "${power_json}")" "power menu mode"

  local xsp
  for xsp in InProgressMovies90Days.xsp InProgressShows90Days.xsp \
    RecentlyAiredEpisodes30Days.xsp TraktPopularTVShows.xsp \
    RecentlyReleasedMoviesCurrentAndPreviousYear.xsp \
    TraktWeekendBoxOffice.xsp NewShows.xsp NewMovies.xsp; do
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

  [[ -f "$(skinvariables_node_path "${root}" "skinvariables-shortcut-1101widgets.json")" ]] \
    || { printf 'TV widgets JSON not found\n' >&2; return 1; }
  [[ -f "$(skinvariables_node_path "${root}" "skinvariables-shortcut-1102widgets.json")" ]] \
    || { printf 'Movies widgets JSON not found\n' >&2; return 1; }
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

test_each_scoped_backup_covers_transformer_applied_paths() {
  local dir scope flags backup_scope root payload written backup_program backup
  local line relative plex_settings
  local apply_core apply_cec apply_addons apply_services apply_skin
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN

  while IFS='|' read -r scope flags backup_scope; do
    [[ -n "${scope}" ]] || continue
    root="${dir}/${scope}/storage"
    payload="${dir}/${scope}/payload.conf"
    mkdir -p "$(dirname "${payload}")"
    # A non-default filename proves CEC coverage comes from dynamic discovery.
    # Failure output names only the scope, never the adapter filename.
    if [[ "${scope}" == "cec" ]]; then
      mkdir -p "${root}/.kodi/userdata/peripheral_data"
      printf '<settings><setting id="standby_pc_on_tv_standby" value="13011" /></settings>\n' \
        > "${root}/.kodi/userdata/peripheral_data/review-dynamic-CEC.xml"
    fi
    IFS=',' read -r apply_core apply_cec apply_addons apply_services apply_skin \
      <<< "${flags}"
    if [[ "${apply_services}" == "1" ]]; then
      plex_settings="$(addon_data_path "${root}" script.plexmod)/settings.xml"
      mkdir -p "$(dirname "${plex_settings}")"
      cat > "${plex_settings}" <<'XML'
<settings version="2">
    <setting id="local_mode">true</setting>
    <setting id="unmanaged_setting">preserved</setting>
</settings>
XML
    fi
    write_scoped_full_payload "${payload}" \
      "${apply_core}" "${apply_cec}" "${apply_addons}" "${apply_services}" "${apply_skin}"
    written="$(run_transform "${root}" "${payload}")"
    backup_program="$(bash "${PROVISIONER}" \
      --emit-remote-script backup "${root}" "${backup_scope}")"
    backup="$(umask 022; printf '%s\n' "${backup_program}" | sh -s)"

    while IFS= read -r line; do
      [[ "${line}" == "settings applied: "* ]] || continue
      relative="${line#settings applied: }"
      relative="${relative#"${root}/"}"
      if [[ ! -f "${backup}/${relative}" ]]; then
        printf 'the %s backup does not capture a transformer-applied path\n' \
          "${scope}" >&2
        return 1
      fi
    done <<< "${written}"
  done <<'SCOPES'
core|1,0,0,0,0|core
cec|0,1,0,0,0|cec
services|0,0,1,1,0|addons,services
skin|1,0,1,0,1|core,addons,skin
baseline|1,1,1,1,1|baseline
SCOPES
}

test_arctic_fuse_managed_settings_carry_type_string() {
  local dir root payload skin_file setting_id
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"

  # Seed a skin settings file with one managed node carrying the wrong type
  # and another missing it entirely. The transformer must converge both.
  mkdir -p "$(dirname "$(skin_settings_path "${root}")")"
  cat > "$(skin_settings_path "${root}")" <<'XML'
<?xml version='1.0' encoding='UTF-8'?>
<settings>
    <setting id="HomeSwitcher.1101.Toggle" type="bool">false</setting>
    <setting id="HomeSwitcher.1101.Name">stale</setting>
    <setting id="unrelated.keep" type="integer">42</setting>
</settings>
XML

  write_full_payload "${payload}"
  run_transform "${root}" "${payload}" >/dev/null

  skin_file="$(skin_settings_path "${root}")"

  # Every managed setting must carry type="string" so Kodi 21.3 preserves it.
  for setting_id in \
    "HomeSwitcher.1101.Name" \
    "HomeSwitcher.1101.Toggle" \
    "HomeSwitcher.1101.Icon" \
    "HomeSwitcher.1101.Mode" \
    "HomeSwitcher.1101.Spotlight.Label" \
    "HomeSwitcher.1101.Spotlight.Path" \
    "HomeSwitcher.1101.Spotlight.Target" \
    "HomeSwitcher.1102.Name" \
    "HomeSwitcher.1102.Toggle" \
    "HomeSwitcher.1102.Icon" \
    "HomeSwitcher.1102.Mode" \
    "HomeSwitcher.1102.Spotlight.Label" \
    "HomeSwitcher.1102.Spotlight.Path" \
    "HomeSwitcher.1102.Spotlight.Target" \
    "HomeSwitcher.1103.Name" \
    "HomeSwitcher.1103.Toggle" \
    "HomeSwitcher.1103.Icon" \
    "HomeSwitcher.1103.Shortcut.Path" \
    "HomeSwitcher.1107.Toggle" \
    "HomeSwitcher.1108.Toggle" \
    "optionstiles.01.include" \
    "optionstiles.02.include" \
    "optionstiles.03.include" \
    "optionstiles.04.include"; do
    assert_eq "string" "$(xml_setting_type "${skin_file}" "${setting_id}")" \
      "${setting_id} must have type=\"string\""
  done

  # Pre-existing wrong type was converged
  assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Toggle")" \
    "1101.Toggle value converged despite wrong type"

  # Unrelated settings must not have their type changed
  assert_eq "integer" "$(xml_setting_type "${skin_file}" "unrelated.keep")" \
    "unrelated.keep type is not changed"
}

test_arctic_fuse_failed_write_cleans_temporary_files() {
  local dir payload root output status blocked_path case_name
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"

  while IFS='|' read -r case_name blocked_path; do
    root="${dir}/${case_name}/storage"

    mkdir -p "$(dirname "$(skin_settings_path "${root}")")"
    printf '<settings><setting id="pre-existing">value</setting></settings>\n' \
      > "$(skin_settings_path "${root}")"
    mkdir -p "${blocked_path}"

    set +e
    output="$(run_transform "${root}" "${payload}" 2>&1)"
    status=$?
    set -e

    assert_failure "${status}" "the blocked write must fail for ${case_name}: ${output}"
    assert_eq "" "$(orphan_temp_files "${root}")" "no temp files left behind for ${case_name}"
  done <<EOF
tv-widgets|$(skinvariables_node_path "${dir}/tv-widgets/storage" "skinvariables-shortcut-1101widgets.json")
movies-widgets|$(skinvariables_node_path "${dir}/movies-widgets/storage" "skinvariables-shortcut-1102widgets.json")
trakt-popular|$(video_playlist_path "${dir}/trakt-popular/storage" TraktPopularTVShows.xsp)
recent-movies|$(video_playlist_path "${dir}/recent-movies/storage" RecentlyReleasedMoviesCurrentAndPreviousYear.xsp)
trakt-box-office|$(video_playlist_path "${dir}/trakt-box-office/storage" TraktWeekendBoxOffice.xsp)
EOF
}

test_arctic_fuse_replaces_obsolete_recently_released_playlists() {
  local dir root payload old_current_year old_rolling new_playlist unrelated written
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.conf"
  write_base_payload "${payload}"

  old_current_year="$(video_playlist_path "${root}" RecentlyReleasedMoviesCurrentYear.xsp)"
  old_rolling="$(video_playlist_path "${root}" RecentlyReleasedMovies90Days.xsp)"
  new_playlist="$(video_playlist_path "${root}" RecentlyReleasedMoviesCurrentAndPreviousYear.xsp)"
  mkdir -p "$(dirname "${old_current_year}")"
  printf 'obsolete current-year managed content\n' > "${old_current_year}"
  printf 'obsolete rolling managed content\n' > "${old_rolling}"

  # An unrelated playlist beside these files must survive unchanged.
  unrelated="$(video_playlist_path "${root}" UnrelatedPlaylist.xsp)"
  printf 'unrelated content\n' > "${unrelated}"

  written="$(run_transform "${root}" "${payload}")"

  [[ ! -e "${old_current_year}" ]] || {
    printf 'obsolete current-year movie playlist still exists\n' >&2
    return 1
  }
  [[ ! -e "${old_rolling}" ]] || {
    printf 'obsolete rolling movie playlist still exists\n' >&2
    return 1
  }
  [[ -f "${new_playlist}" ]] || {
    printf 'current-and-previous-year movie playlist was not created\n' >&2
    return 1
  }
  assert_contains "${written}" "${old_current_year}" \
    "obsolete current-year playlist deletion is recorded for rollback"
  assert_contains "${written}" "${old_rolling}" \
    "obsolete rolling playlist deletion is recorded for rollback"
  assert_contains "${written}" "${new_playlist}" \
    "replacement playlist write is recorded for rollback"

  assert_eq "unrelated content" "$(cat "${unrelated}")" \
    "unrelated playlist beside new files is unchanged"
}

# --- Room display and audio settings ----------------------------------------

test_room_transform_writes_display_and_audio_settings() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  append_payload_entry "${payload}" "ROOM_NAME" "theater"
  append_payload_entry "${payload}" "ROOM_DISPLAY_RESOLUTION_INDEX" "41"
  append_payload_entry "${payload}" "ROOM_DISPLAY_WHITELIST" \
    "0409602160024.00000pstd,0384002160060.00000pstd"
  append_payload_entry "${payload}" "ROOM_DOLBY_VISION" "1"
  append_payload_entry "${payload}" "ROOM_DOLBY_VISION_MODE" "tv-led"
  append_payload_entry "${payload}" "ROOM_AUDIO_PASSTHROUGH" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_AC3" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_EAC3" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_DTS" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_TRUEHD" "1"
  append_payload_entry "${payload}" "ROOM_AUDIO_DTSHD" "0"
  run_transform "${root}" "${payload}" >/dev/null

  settings="$(guisettings_path "${root}")"
  assert_setting_equals "${settings}" "videoscreen.resolution" "41"
  assert_setting_equals "${settings}" "videoscreen.whitelist" \
    "0409602160024.00000pstd,0384002160060.00000pstd"
  assert_setting_equals "${settings}" "audiooutput.passthrough" "true"
  assert_setting_equals "${settings}" "audiooutput.truehdpassthrough" "true"
  assert_setting_equals "${settings}" "audiooutput.dtshdpassthrough" "false"
  assert_setting_equals "${settings}" "coreelec.amlogic.dolbyvisionled" "0"
}

test_room_transform_inverts_dolby_vision() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}" DV=1 MODE=player-led
  run_transform "${root}" "${payload}" >/dev/null
  settings="$(guisettings_path "${root}")"
  assert_setting_equals "${settings}" "coreelec.amlogic.disabledolbyvision" "false"
  assert_setting_equals "${settings}" "coreelec.amlogic.dolbyvisionled" "1"

  rm -rf -- "${root}"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}" DV=0 MODE=tv-led
  run_transform "${root}" "${payload}" >/dev/null
  assert_setting_equals "${settings}" "coreelec.amlogic.disabledolbyvision" "true"
}

test_room_transform_skips_resolution_without_a_resolved_index() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}" INDEX=
  run_transform "${root}" "${payload}" >/dev/null
  settings="$(guisettings_path "${root}")"
  assert_setting_absent "${settings}" "videoscreen.resolution"
  assert_setting_equals "${settings}" "audiooutput.passthrough" "true"
}

test_room_transform_touches_no_other_component_setting() {
  local dir root payload settings setting
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}"
  run_transform "${root}" "${payload}" >/dev/null
  settings="$(guisettings_path "${root}")"
  for setting in locale.language locale.country locale.timezone \
    videoplayer.adjustrefreshrate videoplayer.usedisplayasclock \
    lookandfeel.skin weather.addon services.webserver; do
    assert_setting_absent "${settings}" "${setting}"
  done
}

test_core_and_skin_transform_touch_no_room_setting() {
  local dir root payload settings setting
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.env"
  write_scoped_base_payload "${payload}" 1 0 1 1 1 0
  run_transform "${root}" "${payload}" >/dev/null
  settings="$(guisettings_path "${root}")"
  for setting in videoscreen.resolution videoscreen.whitelist \
    audiooutput.passthrough audiooutput.ac3passthrough \
    audiooutput.eac3passthrough audiooutput.dtspassthrough \
    audiooutput.truehdpassthrough audiooutput.dtshdpassthrough \
    coreelec.amlogic.disabledolbyvision coreelec.amlogic.dolbyvisionled; do
    assert_setting_absent "${settings}" "${setting}"
  done
}

test_room_transform_preserves_unmanaged_settings() {
  local dir root payload settings
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  payload="${dir}/payload.env"
  mkdir -p "${root}/.kodi/userdata"
  settings="$(guisettings_path "${root}")"
  cat > "${settings}" <<'XML'
<settings version="2">
    <setting id="audiooutput.audiodevice">ALSA:@</setting>
    <setting id="audiooutput.passthrough" default="true">false</setting>
</settings>
XML
  write_scoped_base_payload "${payload}" 0 0 0 0 0 1
  write_room_payload_values "${payload}"
  run_transform "${root}" "${payload}" >/dev/null
  assert_setting_equals "${settings}" "audiooutput.audiodevice" "ALSA:@"
  assert_setting_equals "${settings}" "audiooutput.passthrough" "true"
}

run_all_tests \
  test_regional_settings_are_created \
  test_duplicate_settings_are_collapsed \
  test_kodi_setting_case_variants_are_removed \
  test_nested_kodi_settings_are_promoted_to_root_nodes \
  test_existing_unmanaged_settings_are_preserved \
  test_second_run_is_byte_identical \
  test_cec_only_transform_is_isolated \
  test_core_and_cec_transform_only_owned_surfaces \
  test_core_only_transform_does_not_validate_cec \
  test_component_payload_flags_are_strict_booleans \
  test_component_payload_requires_every_implemented_component \
  test_host_payload_renders_every_effective_component \
  test_cec_tv_off_action_is_changed_to_ignore \
  test_cec_navigation_remains_enabled_without_tv_power_coupling \
  test_cec_text_only_setting_is_repaired_to_kodi_attribute \
  test_cec_nested_setting_is_repaired_to_direct_child \
  test_cec_transform_preserves_unmanaged_peripheral_settings \
  test_duplicate_cec_tv_off_actions_are_collapsed \
  test_second_cec_transform_is_byte_identical \
  test_missing_cec_adapter_file_fails_loudly \
  test_multiple_cec_adapter_files_fail_loudly \
  test_malformed_cec_adapter_file_fails_loudly \
  test_cec_settings_file_mode_is_private \
  test_remote_backup_includes_peripheral_data \
  test_tmdb_helper_keys_go_to_tmdb_helper_only \
  test_nextpvr_uses_instance_settings_format \
  test_home_assistant_weather_uses_flat_settings_format \
  test_weather_provider_changes_only_when_configured \
  test_services_only_configured_weather_changes_provider \
  test_core_only_configured_weather_leaves_provider_unchanged \
  test_pm4k_local_mode_settings_are_removed \
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
  test_arctic_fuse_configured_weather_tile_clears_stale_path_and_target \
  test_arctic_fuse_pvr_and_weather_are_absent_when_unconfigured \
  test_arctic_fuse_managed_settings_are_promoted_to_root_nodes \
  test_arctic_fuse_deeply_nested_managed_settings_are_promoted_to_root_nodes \
  test_arctic_fuse_home_widgets_are_exact_and_ordered \
  test_arctic_fuse_hub_widgets_are_exact_and_ordered \
  test_arctic_fuse_power_menu_is_coreelec_appropriate \
  test_arctic_fuse_smart_playlists_have_exact_rules \
  test_arctic_fuse_managed_files_are_private_and_primary_profile_only \
  test_arctic_fuse_convergence_preserves_unmanaged_skinvariables_nodes \
  test_arctic_fuse_second_run_is_byte_identical \
  test_arctic_fuse_managed_settings_carry_type_string \
  test_each_scoped_backup_covers_transformer_applied_paths \
  test_arctic_fuse_replaces_obsolete_recently_released_playlists \
  test_arctic_fuse_failed_write_cleans_temporary_files \
  test_room_transform_writes_display_and_audio_settings \
  test_room_transform_inverts_dolby_vision \
  test_room_transform_skips_resolution_without_a_resolved_index \
  test_room_transform_touches_no_other_component_setting \
  test_core_and_skin_transform_touch_no_room_setting \
  test_room_transform_preserves_unmanaged_settings
