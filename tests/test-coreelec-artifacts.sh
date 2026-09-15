#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"
# shellcheck source=lib/coreelec-artifacts.sh
source "${SCRIPT_DIR}/../lib/coreelec-artifacts.sh"

PROVISIONER="${SCRIPT_DIR}/../provision-coreelec.sh"

# --- Fixture helpers -------------------------------------------------------

fixture_addon_xml() {
  local id="$1" version="$2"
  cat <<XML
<?xml version="1.0" encoding="UTF-8"?>
<addon id="${id}" name="Fixture" version="${version}"
       provider-name="Tests">
  <extension point="xbmc.python.pluginsource" library="default.py"/>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">Fixture</summary>
    <platform>all</platform>
  </extension>
</addon>
XML
}

# Builds a ZIP at zip_path from a manifest file of "archive-name<TAB>source"
# lines. Uses python3's zipfile module (rather than the zip(1) CLI) so
# adversarial entry names -- absolute paths, ".." segments, extra top-level
# directories -- are stored exactly as written instead of being normalized.
build_zip_from_manifest() {
  local zip_path="$1" manifest_file="$2"
  python3 - "${zip_path}" "${manifest_file}" <<'PYEOF'
import sys
import zipfile

zip_path, manifest_file = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(zip_path, "w") as zf, open(manifest_file, "r") as mf:
    for line in mf:
        line = line.rstrip("\n")
        if not line:
            continue
        name, src = line.split("\t", 1)
        with open(src, "rb") as f:
            zf.writestr(name, f.read())
PYEOF
}

# Builds a valid single-top-level-directory fixture ZIP whose addon.xml
# declares the given id/version.
build_valid_fixture_zip() {
  local dir="$1" zip_path="$2" id="$3" version="$4"
  local addon_xml_file="${dir}/addon.xml"
  local manifest_file="${dir}/zip-manifest.tsv"
  fixture_addon_xml "${id}" "${version}" > "${addon_xml_file}"
  printf 'archive.name/addon.xml\t%s\n' "${addon_xml_file}" > "${manifest_file}"
  build_zip_from_manifest "${zip_path}" "${manifest_file}"
}

# The reviewed deployment manifest the provisioner resolves before upload:
# index, add-on ID, pinned version, uploaded archive name.
write_manifest() {
  cat > "$1" <<'MANIFEST'
1	skin.arctic.fuse.3	3.2.16	1.zip
2	weather.ha	0.0.6.6	2.zip
3	pvr.nextpvr	21.3.2.1	3.zip
4	script.plexmod	1.3.19	4.zip
5	resource.uisounds.fromashes	3.0.01	5.zip
6	plugin.service.emby-next-gen	11.1.27	6.zip
7	plugin.video.themoviedb.helper	6.17.1	7.zip
8	resource.language.en_us	11.0.82	8.zip
9	repository.emby.kodi	1.0.8	9.zip
10	repository.dontpanic	0.2.10	10.zip
11	repository.jurialmunkey	3.4	11.zip
12	script.artistslideshow	4.2.0	12.zip
13	resource.images.arctic.waves	0.0.2	13.zip
14	resource.images.weatherfanart.multi	0.0.6	14.zip
15	resource.images.moviecountryicons.maps	0.0.1	15.zip
16	resource.images.studios.white	0.0.34	16.zip
17	inputstream.adaptive	21.5.24.1	17.zip
18	inputstream.ffmpegdirect	21.3.8.1	18.zip
19	resource.font.robotocjksc	0.0.3	19.zip
20	resource.images.studios.coloured	0.0.24	20.zip
21	resource.images.weathericons.white	0.0.6	21.zip
22	script.module.addon.signals	0.0.6+matrix.1	22.zip
23	script.module.certifi	2023.5.7	23.zip
24	script.module.chardet	5.1.0	24.zip
25	script.module.defusedxml	0.6.0+matrix.1	25.zip
26	script.module.dateutil	2.8.2	26.zip
27	script.module.future	1.0.0+matrix.1	27.zip
28	script.module.idna	3.10.0	28.zip
29	script.module.infotagger	0.0.9	29.zip
30	script.module.inputstreamhelper	0.8.5	30.zip
31	script.module.iso8601	2.0.0	31.zip
32	script.module.jurialmunkey	0.2.35	32.zip
33	script.module.kodi-six	0.1.3.1	33.zip
34	script.module.pysocks	1.7.0+matrix.1	34.zip
35	script.module.qrcode	6.1.0+matrix.3	35.zip
36	script.module.requests	2.31.0	36.zip
37	script.module.six	1.16.0+matrix.1	37.zip
38	script.module.urllib3	2.2.3	38.zip
39	script.module.yaml	6.0.1	39.zip
40	script.skinvariables	2.2.2	40.zip
41	script.texturemaker	0.2.11	41.zip
MANIFEST
}

test_reviewed_manifest_fixture_uses_sequential_indices_and_filenames() {
  local dir manifest
  dir="$(make_scratch_dir)"
  trap 'rm -rf "${dir}"' RETURN
  manifest="${dir}/deploy.tsv"
  write_manifest "${manifest}"

  assert_manifest_rows_are_sequential "${manifest}" || return 1
  assert_eq "41" "$(tail -n 1 "${manifest}" | cut -f1)" \
    "the reviewed fixture ends at the 41st artifact" || return 1
  assert_eq "41.zip" "$(tail -n 1 "${manifest}" | cut -f4)" \
    "the reviewed fixture names the tail artifact with 41.zip" || return 1
}

# Installs a fake `curl` ahead of the real one on PATH that ignores the
# requested URL and copies a pre-built fixture ZIP to the requested --output
# path. This lets the download-and-validate pipeline be exercised
# deterministically without a network round trip. Prints the augmented PATH.
install_curl_stub() {
  local dir="$1" fixture_zip="$2"
  local bin_dir="${dir}/stub-bin"
  mkdir -p "${bin_dir}"
  cat > "${bin_dir}/curl" <<STUB
#!/bin/bash
output=""
while (( \$# > 0 )); do
  case "\$1" in
    --output)
      output="\$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
cp "${fixture_zip}" "\${output}"
STUB
  chmod +x "${bin_dir}/curl"
  printf '%s:%s\n' "${bin_dir}" "${PATH}"
}

# --- Record parsing tests ---------------------------------------------------

test_artifact_record_requires_four_fields() {
  local rc output
  set +e
  output="$(coreelec_artifact_parse "plugin.video.fixture|1.2.3|https://example.test/a.zip" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "record with only three fields must be rejected"
  assert_contains "${output}" "four" "error mentions the required field count"
}

test_artifact_record_rejects_non_https_url() {
  local rc output
  set +e
  output="$(coreelec_artifact_parse "plugin.video.fixture|1.2.3|http://example.test/a.zip|$(printf 'a%.0s' {1..64})" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "non-https URL must be rejected"
  assert_contains "${output}" "https://" "error mentions https requirement"
}

test_artifact_record_rejects_invalid_sha256() {
  local rc output
  set +e
  output="$(coreelec_artifact_parse "plugin.video.fixture|1.2.3|https://example.test/a.zip|not-a-checksum" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "invalid SHA-256 must be rejected"
  assert_contains "${output}" "SHA-256" "error mentions SHA-256"
}

# Real Kodi add-on versions carry build/pre-release punctuation: the official
# repository publishes script.module.six 1.16.0+matrix.1 and jurialmunkey
# publishes skin.arctic.horizon.2 0.8.30~omega. Both must round-trip.
test_artifact_record_accepts_kodi_version_punctuation() {
  local sha256
  sha256="$(printf 'a%.0s' {1..64})"
  coreelec_artifact_parse \
    "script.module.six|1.16.0+matrix.1|https://example.test/six.zip|${sha256}" \
    || return 1
  assert_eq "1.16.0+matrix.1" "${ARTIFACT_VERSION}" "build metadata version preserved"
  coreelec_artifact_parse \
    "skin.arctic.horizon.2|0.8.30~omega|https://example.test/ah2.zip|${sha256}" \
    || return 1
  assert_eq "0.8.30~omega" "${ARTIFACT_VERSION}" "pre-release version preserved"
}

test_artifact_record_still_rejects_shell_metacharacters_in_version() {
  local rc output sha256
  sha256="$(printf 'a%.0s' {1..64})"
  set +e
  output="$(coreelec_artifact_parse "plugin.video.fixture|1.2.3\$(id)|https://example.test/a.zip|${sha256}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "version containing shell syntax must be rejected"
  assert_contains "${output}" "version" "error names the version field"
}

# A leading "~" sorts below every other Kodi version, so a record starting with
# it is a downgrade trap rather than a real published version. It is rejected
# for the same reason a leading "-" is.
test_artifact_record_rejects_version_starting_with_tilde() {
  local rc output sha256
  sha256="$(printf 'a%.0s' {1..64})"
  set +e
  output="$(coreelec_artifact_parse "plugin.video.fixture|~1.2.3|https://example.test/a.zip|${sha256}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "version starting with ~ must be rejected"
  assert_contains "${output}" "version" "error names the version field"
}

# --- Download-and-validate pipeline tests -----------------------------------

test_matching_checksum_id_and_version_pass() {
  local dir zip sha256 record rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  zip="${dir}/fixture.zip"
  build_valid_fixture_zip "${dir}" "${zip}" "plugin.video.fixture" "1.2.3"
  sha256="$(sha256sum "${zip}" | awk '{print $1}')"
  record="plugin.video.fixture|1.2.3|https://example.test/fixture.zip|${sha256}"

  ADDON_ARTIFACTS=("${record}")
  PATH="$(install_curl_stub "${dir}" "${zip}")"

  set +e
  output="$(coreelec_artifacts_download_and_validate "${dir}/out" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "matching artifact must pass: ${output}"
  [[ -f "${dir}/out/1.zip" ]] || { echo "validated ZIP must be named by stable index"; return 1; }
  assert_contains "$(cat "${dir}/out/manifest.tsv")" "$(printf '1\tplugin.video.fixture\t1.2.3\t1.zip')" "manifest records index, id, version, filename"
}

test_checksum_mismatch_fails() {
  local dir zip record rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  zip="${dir}/fixture.zip"
  build_valid_fixture_zip "${dir}" "${zip}" "plugin.video.fixture" "1.2.3"
  record="plugin.video.fixture|1.2.3|https://example.test/fixture.zip|$(printf '0%.0s' {1..64})"

  ADDON_ARTIFACTS=("${record}")
  PATH="$(install_curl_stub "${dir}" "${zip}")"

  set +e
  output="$(coreelec_artifacts_download_and_validate "${dir}/out" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "checksum mismatch must fail"
  assert_contains "${output}" "Checksum mismatch" "error names checksum mismatch"
}

test_addon_id_mismatch_fails() {
  local dir zip sha256 record rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  zip="${dir}/fixture.zip"
  build_valid_fixture_zip "${dir}" "${zip}" "plugin.video.other" "1.2.3"
  sha256="$(sha256sum "${zip}" | awk '{print $1}')"
  record="plugin.video.fixture|1.2.3|https://example.test/fixture.zip|${sha256}"

  ADDON_ARTIFACTS=("${record}")
  PATH="$(install_curl_stub "${dir}" "${zip}")"

  set +e
  output="$(coreelec_artifacts_download_and_validate "${dir}/out" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "add-on ID mismatch must fail"
  assert_contains "${output}" "ID mismatch" "error names ID mismatch"
}

test_addon_version_mismatch_fails() {
  local dir zip sha256 record rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  zip="${dir}/fixture.zip"
  build_valid_fixture_zip "${dir}" "${zip}" "plugin.video.fixture" "9.9.9"
  sha256="$(sha256sum "${zip}" | awk '{print $1}')"
  record="plugin.video.fixture|1.2.3|https://example.test/fixture.zip|${sha256}"

  ADDON_ARTIFACTS=("${record}")
  PATH="$(install_curl_stub "${dir}" "${zip}")"

  set +e
  output="$(coreelec_artifacts_download_and_validate "${dir}/out" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "add-on version mismatch must fail"
  assert_contains "${output}" "version mismatch" "error names version mismatch"
}

test_multiple_top_level_directories_fail() {
  local dir zip sha256 record rc output
  local addon_xml_file manifest_file extra_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  zip="${dir}/fixture.zip"
  addon_xml_file="${dir}/addon.xml"
  extra_file="${dir}/extra.txt"
  manifest_file="${dir}/zip-manifest.tsv"
  fixture_addon_xml "plugin.video.fixture" "1.2.3" > "${addon_xml_file}"
  printf 'unrelated content\n' > "${extra_file}"
  {
    printf 'plugin.video.fixture/addon.xml\t%s\n' "${addon_xml_file}"
    printf 'another-top-level-dir/extra.txt\t%s\n' "${extra_file}"
  } > "${manifest_file}"
  build_zip_from_manifest "${zip}" "${manifest_file}"
  sha256="$(sha256sum "${zip}" | awk '{print $1}')"
  record="plugin.video.fixture|1.2.3|https://example.test/fixture.zip|${sha256}"

  ADDON_ARTIFACTS=("${record}")
  PATH="$(install_curl_stub "${dir}" "${zip}")"

  set +e
  output="$(coreelec_artifacts_download_and_validate "${dir}/out" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "multiple top-level directories must fail"
  assert_contains "${output}" "more than one top-level directory" "error names the multiple top-level directories"
}

test_parent_traversal_entry_fails() {
  local dir zip sha256 record rc output
  local addon_xml_file manifest_file evil_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  zip="${dir}/fixture.zip"
  addon_xml_file="${dir}/addon.xml"
  evil_file="${dir}/evil.txt"
  manifest_file="${dir}/zip-manifest.tsv"
  fixture_addon_xml "plugin.video.fixture" "1.2.3" > "${addon_xml_file}"
  printf 'traversal payload\n' > "${evil_file}"
  {
    printf 'plugin.video.fixture/addon.xml\t%s\n' "${addon_xml_file}"
    printf 'plugin.video.fixture/../evil.txt\t%s\n' "${evil_file}"
  } > "${manifest_file}"
  build_zip_from_manifest "${zip}" "${manifest_file}"
  sha256="$(sha256sum "${zip}" | awk '{print $1}')"
  record="plugin.video.fixture|1.2.3|https://example.test/fixture.zip|${sha256}"

  ADDON_ARTIFACTS=("${record}")
  PATH="$(install_curl_stub "${dir}" "${zip}")"

  set +e
  output="$(coreelec_artifacts_download_and_validate "${dir}/out" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "parent traversal entry must fail"
  assert_contains "${output}" "traversal" "error names the traversal entry"
}

test_absolute_path_entry_fails() {
  local dir zip sha256 record rc output
  local addon_xml_file manifest_file evil_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  zip="${dir}/fixture.zip"
  addon_xml_file="${dir}/addon.xml"
  evil_file="${dir}/evil.txt"
  manifest_file="${dir}/zip-manifest.tsv"
  fixture_addon_xml "plugin.video.fixture" "1.2.3" > "${addon_xml_file}"
  printf 'absolute payload\n' > "${evil_file}"
  {
    printf 'plugin.video.fixture/addon.xml\t%s\n' "${addon_xml_file}"
    printf '/etc/evil.txt\t%s\n' "${evil_file}"
  } > "${manifest_file}"
  build_zip_from_manifest "${zip}" "${manifest_file}"
  sha256="$(sha256sum "${zip}" | awk '{print $1}')"
  record="plugin.video.fixture|1.2.3|https://example.test/fixture.zip|${sha256}"

  ADDON_ARTIFACTS=("${record}")
  PATH="$(install_curl_stub "${dir}" "${zip}")"

  set +e
  output="$(coreelec_artifacts_download_and_validate "${dir}/out" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "absolute path entry must fail"
  assert_contains "${output}" "absolute path" "error names the absolute path entry"
}

test_duplicate_artifact_id_fails() {
  local dir zip sha256 record_one record_two rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  zip="${dir}/fixture.zip"
  build_valid_fixture_zip "${dir}" "${zip}" "plugin.video.fixture" "1.2.3"
  sha256="$(sha256sum "${zip}" | awk '{print $1}')"
  record_one="plugin.video.fixture|1.2.3|https://example.test/fixture.zip|${sha256}"
  record_two="plugin.video.fixture|1.2.3|https://example.test/fixture-again.zip|${sha256}"

  ADDON_ARTIFACTS=("${record_one}" "${record_two}")
  PATH="$(install_curl_stub "${dir}" "${zip}")"

  set +e
  output="$(coreelec_artifacts_download_and_validate "${dir}/out" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "duplicate artifact ID must fail"
  assert_contains "${output}" "Duplicate artifact ID" "error names the duplicate artifact ID"
}

# --- Remote deployment transaction fixtures ---------------------------------
#
# The deployment transaction normally runs on the CoreELEC device against
# /storage. It is exercised here through provision-coreelec.sh's internal
# rendering modes, which print the exact `sh` program the device receives with
# the storage root as a parameter. Every test below executes that program
# against a scratch storage root with stubbed `systemctl` and `unzip`
# commands, so the assertions are about real transaction behavior rather than
# about the text of the script.

file_mode() {
  python3 -c 'import os, sys; sys.stdout.write("%o" % (os.stat(sys.argv[1]).st_mode & 0o7777))' "$1"
}

render_remote_script() {
  local name="$1" root="$2"
  shift 2
  if [[ "${name}" == "deploy" ]]; then
    bash "${PROVISIONER}" --render-remote-deploy-script "${root}"
  else
    bash "${PROVISIONER}" --emit-remote-script "${name}" "${root}" "$@"
  fi
}

# The rendered rollback program is the transaction prologue followed by a
# six-line body, so everything above its first statement is the exact shared
# prologue text the device receives for deploy, rollback, and finalize. Cutting
# it here lets the device-side validators be exercised directly.
extract_transaction_prologue() {
  local root="$1"
  # awk must consume the whole stream: exiting early would break the render
  # pipeline under `set -o pipefail`.
  render_remote_script rollback "${root}" \
    | awk '/^resolve_pending_transaction/ { reached = 1 } !reached { print }'
}

# Tests that cover Bash 3.2 semantics use /bin/bash when available rather than
# whichever newer shell happens to be first on PATH.
legacy_bash() {
  if [[ -x /bin/bash ]]; then
    printf '/bin/bash\n'
  else
    printf 'bash\n'
  fi
}

# Loads one function definition out of provision-coreelec.sh into the current
# shell so an ordering guarantee inside the main flow can be exercised against
# stubs, without running the provisioner end to end or contacting a device.
# Every provisioner function ends with a `}` in the first column.
load_provisioner_function() {
  local name="$1" body
  body="$(awk -v start="${name}() {" '
    $0 == start { capturing = 1 }
    capturing { print }
    capturing && $0 == "}" { exit }
  ' "${PROVISIONER}")"
  if [[ -z "${body}" ]]; then
    printf 'no %s() definition was found in the provisioner\n' "${name}" >&2
    return 1
  fi
  eval "${body}"
}

# Replaces every command the provisioner could use to reach the device with a
# logging stub that always fails, so a test can assert that a run refused
# before it touched anything remote. Prints the stub directory.
install_network_stubs() {
  local dir="$1" bin_dir="$1/network-bin" name
  mkdir -p "${bin_dir}"
  for name in ssh scp rsync ssh-keygen ssh-add curl; do
    cat > "${bin_dir}/${name}" <<STUB
#!/bin/bash
printf '${name} %s\n' "\$*" >> "${dir}/network-calls.log"
exit 1
STUB
    chmod +x "${bin_dir}/${name}"
  done
  : > "${dir}/network-calls.log"
  printf '%s\n' "${bin_dir}"
}

# Runs provision-coreelec.sh under Bash 3.2 with the network stubs ahead of
# everything on PATH, the repository configuration, and scratch paths for the
# administrator key and the report directory.
run_provisioner_offline() {
  local dir="$1" bin_dir="$2" env_file="$1/.env" name
  shift 2
  printf '%s\n' "KODI_WEB_PASSWORD='test-kodi-password'" > "${env_file}"
  for name in OMDB_API_KEY MDBLIST_API_KEY; do
    if [[ -n "${!name:-}" ]]; then
      printf '%s=%q\n' "${name}" "${!name}" >> "${env_file}"
    fi
  done
  printf 'n\n' | UGOOS_ENV_FILE="${env_file}" PATH="${bin_dir}:${PATH}" "$(legacy_bash)" "${PROVISIONER}" \
    --config "${SCRIPT_DIR}/../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf" \
    --identity "${dir}/scratch_admin_key" \
    --report-dir "${dir}/reports" \
    "$@"
}

test_non_darwin_host_reaches_remote_validation() {
  local dir bin_dir output rc calls
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_network_stubs "${dir}")"
  cat > "${bin_dir}/uname" <<'STUB'
#!/bin/bash
printf 'Linux\n'
STUB
  chmod +x "${bin_dir}/uname"
  printf 'scratch administrator key\n' > "${dir}/scratch_admin_key"
  printf 'ssh-ed25519 AAAA scratch\n' > "${dir}/scratch_admin_key.pub"

  set +e
  output="$(OMDB_API_KEY=fixture-omdb MDBLIST_API_KEY=fixture-mdblist \
    run_provisioner_offline "${dir}" "${bin_dir}" --target 192.0.2.1 --yes 2>&1)"
  rc=$?
  set -e

  assert_failure "${rc}" "the offline target remains unreachable" || return 1
  calls="$(cat "${dir}/network-calls.log")"
  assert_contains "${calls}" "ssh " \
    "a Linux host proceeds to the first remote validation call" || return 1
  assert_contains "${output}" "Nothing on the device has been changed." \
    "the normal remote validation error is reported"
}

test_admin_key_setup_uses_portable_ssh_add_arguments() {
  local dir bin_dir calls
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="${dir}/bin"
  mkdir -p "${bin_dir}"
  cat > "${bin_dir}/ssh-add" <<STUB
#!/bin/bash
printf 'ssh-add %s\n' "\$*" >> "${dir}/ssh-add.log"
STUB
  chmod +x "${bin_dir}/ssh-add"
  : > "${dir}/ssh-add.log"
  printf 'scratch administrator key\n' > "${dir}/admin_key"
  printf 'ssh-ed25519 AAAA scratch\n' > "${dir}/admin_key.pub"

  load_provisioner_function create_or_load_admin_key
  IDENTITY_FILE="${dir}/admin_key"
  PATH="${bin_dir}:${PATH}" create_or_load_admin_key

  calls="$(cat "${dir}/ssh-add.log")"
  assert_eq "ssh-add ${IDENTITY_FILE}" "${calls}" \
    "administrator key setup uses the portable ssh-add interface"
}

# Builds the storage root the transaction operates on: a Kodi tree, the
# provisioning cache, and the base64 payload the settings transformer reads.
make_fake_storage() {
  local dir="$1" root="$1/storage" line key value payload
  mkdir -p "${root}/.kodi/addons" "${root}/.kodi/userdata/addon_data" \
    "${root}/.kodi/userdata/peripheral_data" "${root}/.cache/coreelec-provision"
  # The settings transformer requires exactly one Kodi CEC peripheral file to
  # already exist, the same way a real device already has one once CoreELEC
  # has detected its CEC adapter.
  printf '<settings><setting id="standby_pc_on_tv_standby" value="13011" /></settings>\n' \
    > "${root}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml"
  payload="${root}/.cache/coreelec-provision/settings-payload.conf"
  : > "${payload}"
  chmod 600 "${payload}"
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    printf '%s=%s\n' "${key}" "$(printf '%s' "${value}" | openssl base64 -A)" >> "${payload}"
  done <<'ENTRIES'
APPLY_COMPONENT_CORE=1
APPLY_COMPONENT_CEC=1
APPLY_COMPONENT_ADDONS=1
APPLY_COMPONENT_SERVICES=1
APPLY_COMPONENT_SKIN=1
TIMEZONE=America/Los_Angeles
TIMEZONE_COUNTRY=United States
LOCALE_LANGUAGE=resource.language.en_us
LOCALE_COUNTRY=USA (12h)
KEYBOARD_LAYOUT=English QWERTY
ADDON_UPDATE_MODE=notify
CEC_TV_OFF_ACTION=36028
ENTRIES
  printf '%s\n' "${root}"
}

set_remote_component_scope() {
  local root="$1" core="$2" cec="$3" addons="$4" services="$5" skin="$6"
  local payload="${root}/.cache/coreelec-provision/settings-payload.conf"
  local filtered="${payload}.without-components" key value
  grep -v '^APPLY_COMPONENT_' "${payload}" > "${filtered}"
  mv "${filtered}" "${payload}"
  for key in CORE CEC ADDONS SERVICES SKIN; do
    case "${key}" in
      CORE) value="${core}" ;;
      CEC) value="${cec}" ;;
      ADDONS) value="${addons}" ;;
      SERVICES) value="${services}" ;;
      SKIN) value="${skin}" ;;
    esac
    printf 'APPLY_COMPONENT_%s=%s\n' \
      "${key}" "$(printf '%s' "${value}" | openssl base64 -A)" >> "${payload}"
  done
  chmod 600 "${payload}"
}

replace_remote_payload_entry() {
  local root="$1" key="$2" encoded="$3"
  local payload="${root}/.cache/coreelec-provision/settings-payload.conf"
  local filtered="${payload}.without-${key}"
  grep -v "^${key}=" "${payload}" > "${filtered}"
  printf '%s=%s\n' "${key}" "${encoded}" >> "${filtered}"
  mv "${filtered}" "${payload}"
  chmod 600 "${payload}"
}

# Recreates what upload_artifact_bundle leaves on the device: one fixture ZIP
# per add-on plus the deploy.tsv the transaction reads. Each spec is
# "id:version:top-level-directory", so a ZIP root that differs from the add-on
# ID (PM4K, Emby, weather.ha ship such archives) can be exercised.
stage_addon_bundle() {
  local dir="$1" root="$2"
  shift 2
  local stage="${root}/.cache/coreelec-provision/stage"
  local index=0 spec id version topdir work weather_settings pm4k_monitor
  mkdir -p "${stage}"
  : > "${stage}/deploy.tsv"
  for spec in "$@"; do
    index=$((index + 1))
    id="${spec%%:*}"
    version="${spec#*:}"
    version="${version%%:*}"
    topdir="${spec##*:}"
    work="${dir}/zip-source-${index}"
    mkdir -p "${work}"
    fixture_addon_xml "${id}" "${version}" > "${work}/addon.xml"
    printf 'new %s %s\n' "${id}" "${version}" > "${work}/marker.txt"
    {
      printf '%s/addon.xml\t%s\n' "${topdir}" "${work}/addon.xml"
      printf '%s/marker.txt\t%s\n' "${topdir}" "${work}/marker.txt"
    } > "${work}/zip-manifest.tsv"
    if [[ "${id}" == "weather.ha" ]]; then
      mkdir -p "${work}/resources"
      weather_settings="${work}/resources/settings.xml"
      cat > "${weather_settings}" <<'XML'
<settings>
  <category>
    <setting id="ha_request_attempts" type="int" default="5" />
  </category>
</settings>
XML
      printf '%s/resources/settings.xml\t%s\n' "${topdir}" "${weather_settings}" \
        >> "${work}/zip-manifest.tsv"
    fi
    if [[ "${id}" == "script.plexmod" ]]; then
      mkdir -p "${work}/lib"
      pm4k_monitor="${work}/lib/monitor.py"
      cat > "${pm4k_monitor}" <<'PY'
def onNotification(sender, method):
    if sender == "xbmc" and method == "System.OnQuit":
        from .windows import windowutils
        windowutils.HOME.closeOption = "kodi_exit"
        windowutils.HOME.doClose()
        return
PY
      printf '%s/lib/monitor.py\t%s\n' "${topdir}" "${pm4k_monitor}" \
        >> "${work}/zip-manifest.tsv"
    fi
    build_zip_from_manifest "${stage}/${index}.zip" "${work}/zip-manifest.tsv"
    printf '%s\t%s\t%s\t%s.zip\n' \
      "${index}" "${id}" "${version}" "${index}" >> "${stage}/deploy.tsv"
  done
}

# Stubs the two remote commands the transaction shells out to. Both append to
# one shared log so the ordering between extraction and service control is a
# directly observable property. The `unzip` stub accepts only the BusyBox
# option shape the transaction is allowed to use and then performs a real
# extraction, so a flag the device would reject fails the test here.
install_remote_stubs() {
  local dir="$1" bin_dir="$1/remote-bin"
  mkdir -p "${bin_dir}"
  cat > "${bin_dir}/systemctl" <<'STUB'
#!/bin/bash
printf 'systemctl %s\n' "$*" >> "${REMOTE_CALL_LOG}"
if [[ -n "${SYSTEMCTL_FAIL:-}" && "$*" == *"${SYSTEMCTL_FAIL}"* ]]; then
  exit 1
fi
exit 0
STUB
  cat > "${bin_dir}/unzip" <<'STUB'
#!/bin/bash
printf 'unzip %s\n' "$*" >> "${REMOTE_CALL_LOG}"
destination=""
archive=""
while (( $# > 0 )); do
  case "$1" in
    -o|-q) shift ;;
    -d)
      destination="$2"
      shift 2
      ;;
    -*)
      printf 'BusyBox unzip does not accept: %s\n' "$1" >&2
      exit 2
      ;;
    *)
      archive="$1"
      shift
      ;;
  esac
done
if [[ -z "${destination}" || -z "${archive}" ]]; then
  printf 'unzip stub: expected -d DIR ARCHIVE\n' >&2
  exit 2
fi
if [[ -n "${UNZIP_FAIL:-}" ]]; then
  printf 'unzip stub: forced failure\n' >&2
  exit 1
fi
python3 - "${archive}" "${destination}" <<'PYEOF'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
PYEOF
STUB
  chmod +x "${bin_dir}/systemctl" "${bin_dir}/unzip"
  printf '%s\n' "${bin_dir}"
}

# Executes one rendered remote program with the stubs ahead of it on PATH,
# exactly the way the device's `sh -s` would consume it from the SSH channel.
run_remote_script() {
  local name="$1" root="$2" bin_dir="$3" script
  script="$(render_remote_script "${name}" "${root}")" || return 1
  [[ -n "${script}" ]] || return 1
  printf '%s\n' "${script}" | PATH="${bin_dir}:${PATH}" sh -s
}

# The transaction directory a successful deployment printed, or the last line
# of output, so failures produce a readable assertion message.
remote_calls() {
  cat "${REMOTE_CALL_LOG}"
}

# --- Remote deployment transaction tests ------------------------------------

test_cec_only_transaction_accepts_no_artifacts_and_rolls_back_only_cec() {
  local dir root bin_dir rc output transaction cec_path backup_paths applied_paths
  local guisettings service_settings skin_settings node playlist addon_marker
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  cec_path="${root}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml"
  cp "${cec_path}" "${dir}/cec.before"
  guisettings="${root}/.kodi/userdata/guisettings.xml"
  service_settings="${root}/.kodi/userdata/addon_data/plugin.video.themoviedb.helper/settings.xml"
  skin_settings="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  node="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-homewidgets.json"
  playlist="${root}/.kodi/userdata/playlists/video/NewMovies.xsp"
  addon_marker="${root}/.kodi/addons/plugin.video.untouched/marker.txt"
  mkdir -p "$(dirname "${service_settings}")" "$(dirname "${skin_settings}")" \
    "$(dirname "${node}")" "$(dirname "${playlist}")" "$(dirname "${addon_marker}")"
  printf 'guisettings sentinel\n' > "${guisettings}"
  printf 'service sentinel\n' > "${service_settings}"
  printf 'skin sentinel\n' > "${skin_settings}"
  printf 'node sentinel\n' > "${node}"
  printf 'playlist sentinel\n' > "${playlist}"
  printf 'add-on sentinel\n' > "${addon_marker}"
  cp "${guisettings}" "${dir}/guisettings.before"
  cp "${service_settings}" "${dir}/service.before"
  cp "${skin_settings}" "${dir}/skin.before"
  cp "${node}" "${dir}/node.before"
  cp "${playlist}" "${dir}/playlist.before"
  cp "${addon_marker}" "${dir}/addon.before"

  set_remote_component_scope "${root}" 0 1 0 0 0
  stage_addon_bundle "${dir}" "${root}"

  # Fail the first post-transform Kodi start. The trap must restore the CEC
  # bytes even though no add-on bundle or unrelated settings path participates.
  export SYSTEMCTL_FAIL="start kodi.service"
  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  unset SYSTEMCTL_FAIL
  assert_failure "${rc}" "the injected post-transform failure must fail the transaction"

  transaction="$(find "${root}/backup/coreelec-provision" -mindepth 1 -maxdepth 1 -type d -print | head -1)"
  [[ -n "${transaction}" ]] || {
    printf 'the CEC-only failure did not create rollback material: %s\n' "${output}" >&2
    return 1
  }
  if ! cmp -s "${dir}/cec.before" "${cec_path}"; then
    printf 'CEC rollback did not restore the original bytes\n' >&2
    return 1
  fi
  backup_paths="$(find "${transaction}/files" -type f -print | sort)"
  assert_eq "${transaction}/files/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml" \
    "${backup_paths}" "CEC-only rollback material contains exactly the detected CEC file"
  applied_paths="$(cat "${transaction}/APPLIED.txt")"
  assert_eq "${cec_path}" "${applied_paths}" \
    "the scoped applied plan contains only the CEC file"
  assert_eq $'component\tcore\t0\ncomponent\tcec\t1\ncomponent\taddons\t0\ncomponent\tservices\t0\ncomponent\tskin\t0' \
    "$(cat "${transaction}/PLAN.tsv")" \
    "the persisted remote plan records the complete CEC-only scope"

  cmp -s "${dir}/guisettings.before" "${guisettings}" \
    || { printf 'CEC-only deployment changed guisettings.xml\n' >&2; return 1; }
  cmp -s "${dir}/service.before" "${service_settings}" \
    || { printf 'CEC-only deployment changed service settings\n' >&2; return 1; }
  cmp -s "${dir}/skin.before" "${skin_settings}" \
    || { printf 'CEC-only deployment changed skin settings\n' >&2; return 1; }
  cmp -s "${dir}/node.before" "${node}" \
    || { printf 'CEC-only deployment changed a skin node\n' >&2; return 1; }
  cmp -s "${dir}/playlist.before" "${playlist}" \
    || { printf 'CEC-only deployment changed a playlist\n' >&2; return 1; }
  cmp -s "${dir}/addon.before" "${addon_marker}" \
    || { printf 'CEC-only deployment changed an add-on directory\n' >&2; return 1; }
  assert_not_contains "$(cat "${transaction}/MANIFEST.txt")" ".kodi/addons" \
    "CEC-only transaction metadata never names the add-on tree"
}

test_cec_and_addons_transaction_mutates_only_selected_surfaces() {
  local dir root bin_dir rc output transaction cec_path guisettings service_settings
  local skin_settings node playlist untouched addon_dir calls
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  cec_path="${root}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml"
  guisettings="${root}/.kodi/userdata/guisettings.xml"
  service_settings="${root}/.kodi/userdata/addon_data/script.plexmod/settings.xml"
  skin_settings="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  node="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-homewidgets.json"
  playlist="${root}/.kodi/userdata/playlists/video/NewMovies.xsp"
  untouched="${root}/.kodi/addons/plugin.video.untouched/marker.txt"
  addon_dir="${root}/.kodi/addons/script.plexmod"
  mkdir -p "$(dirname "${service_settings}")" "$(dirname "${skin_settings}")" \
    "$(dirname "${node}")" "$(dirname "${playlist}")" "$(dirname "${untouched}")" \
    "${addon_dir}"
  printf 'guisettings sentinel\n' > "${guisettings}"
  printf 'service sentinel\n' > "${service_settings}"
  printf 'skin sentinel\n' > "${skin_settings}"
  printf 'node sentinel\n' > "${node}"
  printf 'playlist sentinel\n' > "${playlist}"
  printf 'untouched add-on\n' > "${untouched}"
  printf 'old PM4K\n' > "${addon_dir}/marker.txt"
  cp "${guisettings}" "${dir}/guisettings.before"
  cp "${service_settings}" "${dir}/service.before"
  cp "${skin_settings}" "${dir}/skin.before"
  cp "${node}" "${dir}/node.before"
  cp "${playlist}" "${dir}/playlist.before"
  cp "${untouched}" "${dir}/untouched.before"

  set_remote_component_scope "${root}" 0 1 1 0 0
  stage_addon_bundle "${dir}" "${root}" "script.plexmod:1.3.19:plex-for-kodi-fixture"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>"${dir}/deploy.err")"
  rc=$?
  set -e
  output="$(cat "${dir}/deploy.err")"
  assert_success "${rc}" "the scoped CEC plus PM4K transaction must succeed: ${output}"
  assert_contains "$(cat "${cec_path}")" 'value="36028"' \
    "the selected CEC file is transformed"
  assert_eq "new script.plexmod 1.3.19" "$(cat "${addon_dir}/marker.txt")" \
    "the selected PM4K directory is replaced"
  assert_contains "$(cat "${addon_dir}/lib/monitor.py")" "if windowutils.HOME:" \
    "the selected PM4K artifact keeps its compatibility patch"
  assert_eq "old PM4K" \
    "$(cat "${transaction}/rollback/addons/script.plexmod/marker.txt")" \
    "the selected prior add-on directory is rollback material"
  assert_eq "${cec_path}" "$(cat "${transaction}/APPLIED.txt")" \
    "the mixed scoped applied plan contains only the selected settings path"
  assert_eq $'component\tcore\t0\ncomponent\tcec\t1\ncomponent\taddons\t1\ncomponent\tservices\t0\ncomponent\tskin\t0\naddon\t1.zip\tscript.plexmod\tplex-for-kodi-fixture' \
    "$(cat "${transaction}/PLAN.tsv")" \
    "the persisted remote plan records components and the selected PM4K artifact"

  cmp -s "${dir}/guisettings.before" "${guisettings}" \
    || { printf 'CEC plus add-ons changed guisettings.xml\n' >&2; return 1; }
  cmp -s "${dir}/service.before" "${service_settings}" \
    || { printf 'CEC plus add-ons changed service settings\n' >&2; return 1; }
  cmp -s "${dir}/skin.before" "${skin_settings}" \
    || { printf 'CEC plus add-ons changed skin settings\n' >&2; return 1; }
  cmp -s "${dir}/node.before" "${node}" \
    || { printf 'CEC plus add-ons changed a skin node\n' >&2; return 1; }
  cmp -s "${dir}/playlist.before" "${playlist}" \
    || { printf 'CEC plus add-ons changed a playlist\n' >&2; return 1; }
  cmp -s "${dir}/untouched.before" "${untouched}" \
    || { printf 'CEC plus add-ons changed an unselected add-on\n' >&2; return 1; }

  calls="$(remote_calls)"
  assert_eq "1" "$(printf '%s\n' "${calls}" | grep -c '^systemctl stop kodi.service$')" \
    "the combined transaction stops Kodi once"
  assert_eq "1" "$(printf '%s\n' "${calls}" | grep -c '^systemctl start kodi.service$')" \
    "the combined transaction starts Kodi once"
}

test_remote_scope_is_revalidated_before_mutation() {
  local dir root bin_dir rc output cec_path
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  cec_path="${root}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml"
  cp "${cec_path}" "${dir}/cec.before"
  set_remote_component_scope "${root}" 0 1 0 0 0
  grep -v '^APPLY_COMPONENT_SKIN=' \
    "${root}/.cache/coreelec-provision/settings-payload.conf" \
    > "${dir}/malformed-payload.conf"
  mv "${dir}/malformed-payload.conf" \
    "${root}/.cache/coreelec-provision/settings-payload.conf"
  stage_addon_bundle "${dir}" "${root}"

  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a malformed component scope must fail"
  assert_contains "${output}" "missing required component" \
    "the remote scope error names the missing component flag"
  assert_eq "" "$(remote_calls)" "malformed scope fails before Kodi is stopped"
  cmp -s "${dir}/cec.before" "${cec_path}" \
    || { printf 'malformed scope changed the CEC file before rejection\n' >&2; return 1; }
  if [[ -d "${root}/backup/coreelec-provision" ]] \
    && find "${root}/backup/coreelec-provision" -mindepth 1 -print -quit | grep -q .; then
    printf 'malformed scope created transaction material before rejection\n' >&2
    return 1
  fi
}

test_cec_only_predeployment_backup_contains_no_unselected_settings() {
  local dir root script backup output rc cec_path guisettings service_settings skin_settings
  local advancedsettings sources coreelec_settings hostname
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  cec_path="${root}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml"
  guisettings="${root}/.kodi/userdata/guisettings.xml"
  service_settings="${root}/.kodi/userdata/addon_data/script.plexmod/settings.xml"
  skin_settings="${root}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml"
  advancedsettings="${root}/.kodi/userdata/advancedsettings.xml"
  sources="${root}/.kodi/userdata/sources.xml"
  coreelec_settings="${root}/.kodi/userdata/addon_data/service.coreelec.settings/oe_settings.xml"
  hostname="${root}/.cache/hostname"
  mkdir -p "$(dirname "${service_settings}")" "$(dirname "${skin_settings}")" \
    "$(dirname "${coreelec_settings}")"
  printf 'guisettings sentinel\n' > "${guisettings}"
  printf 'service sentinel\n' > "${service_settings}"
  printf 'skin sentinel\n' > "${skin_settings}"
  printf 'advanced settings sentinel\n' > "${advancedsettings}"
  printf 'sources sentinel\n' > "${sources}"
  printf 'CoreELEC service sentinel\n' > "${coreelec_settings}"
  printf 'hostname sentinel\n' > "${hostname}"

  script="$(bash "${PROVISIONER}" --emit-remote-script backup "${root}" cec)"
  set +e
  output="$(printf '%s\n' "${script}" | sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the scoped pre-deployment backup must succeed: ${output}" \
    || return 1
  assert_not_contains "${output}" "not found" \
    "the scoped backup must execute every path selector" || return 1
  backup="$(printf '%s\n' "${output}" | tail -1)"

  if [[ ! -f "${backup}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml" ]]; then
    printf 'the scoped pre-deployment backup omitted the selected CEC file\n' >&2
    return 1
  fi
  cmp -s "${cec_path}" \
    "${backup}/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml" \
    || { printf 'the scoped CEC backup changed the source bytes\n' >&2; return 1; }
  if [[ -e "${backup}/.kodi/userdata/guisettings.xml" ]] \
    || [[ -e "${backup}/.kodi/userdata/addon_data/script.plexmod/settings.xml" ]] \
    || [[ -e "${backup}/.kodi/userdata/addon_data/skin.arctic.fuse.3/settings.xml" ]] \
    || [[ -e "${backup}/.kodi/userdata/advancedsettings.xml" ]] \
    || [[ -e "${backup}/.kodi/userdata/sources.xml" ]] \
    || [[ -e "${backup}/.kodi/userdata/addon_data/service.coreelec.settings/oe_settings.xml" ]] \
    || [[ -e "${backup}/.cache/hostname" ]]; then
    printf 'the CEC-only pre-deployment backup copied unselected settings\n' >&2
    return 1
  fi
}

test_remote_deploy_stops_kodi_after_staging_validation() {
  local dir root bin_dir rc output stage first_service
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  stage="${root}/.cache/coreelec-provision/stage"

  # A staged ZIP whose addon.xml disagrees with the manifest must be refused
  # while Kodi is still running, so a bad bundle never interrupts playback.
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"
  printf '1\tplugin.video.mismatch\t1.2.3\t1.zip\n' > "${stage}/deploy.tsv"

  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a manifest/addon.xml disagreement must fail the transaction"
  assert_contains "${output}" "plugin.video.mismatch" "the error names the rejected add-on"
  assert_eq "" "$(remote_calls)" "no service is touched when staging validation fails"

  # The same bundle, now consistent, stops Kodi only after every ZIP expanded.
  # The rejected attempt consumed the uploaded payload, exactly as a retry on
  # a real device would, so it is uploaded again first.
  : > "${REMOTE_CALL_LOG}"
  make_fake_storage "${dir}" >/dev/null
  stage_addon_bundle "${dir}" "${root}" \
    "plugin.video.fixture:1.2.3:plugin.video.fixture" \
    "script.module.fixture:2.0.0:script.module.fixture"

  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a consistent bundle must deploy: ${output}"

  first_service="$(grep -n '^systemctl ' "${REMOTE_CALL_LOG}" | head -1 | cut -d: -f1)"
  assert_eq "3" "${first_service}" "both extractions precede the first service call"
  assert_contains "$(sed -n '3p' "${REMOTE_CALL_LOG}")" "stop kodi.service" \
    "the first service call stops Kodi"
}

test_remote_deploy_guards_pm4k_shutdown_without_an_open_home_window() {
  local dir root bin_dir output rc monitor
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  stage_addon_bundle "${dir}" "${root}" \
    "script.plexmod:1.3.19:plex-for-kodi-fixture"

  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the pinned PM4K bundle must deploy: ${output}" || return 1

  monitor="${root}/.kodi/addons/script.plexmod/lib/monitor.py"
  assert_contains "$(cat "${monitor}")" "if windowutils.HOME:" \
    "PM4K shutdown must guard the nullable HOME window before dereferencing it"
}

test_remote_deploy_traps_kodi_restart() {
  local dir root bin_dir rc output script last_call
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  script="$(render_remote_script deploy "${root}")"
  assert_contains "${script}" "EXIT HUP INT TERM" "the transaction traps every abrupt exit"

  # A failure after Kodi was stopped must still leave Kodi running. A payload
  # value that is not valid base64 gets past the preflight checks and fails
  # inside the transformer, after the add-ons were already replaced.
  replace_remote_payload_entry "${root}" TIMEZONE '!!!not-base64!!!'
  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a transformer failure must fail the transaction"

  assert_contains "$(remote_calls)" "stop kodi.service" "Kodi was stopped by the transaction"
  last_call="$(grep '^systemctl ' "${REMOTE_CALL_LOG}" | tail -1)"
  assert_contains "${last_call}" "start kodi.service" "the trap restarts Kodi on the failure path"
}

test_remote_deploy_backs_up_each_replaced_path() {
  local dir root bin_dir transaction guisettings rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  mkdir -p "${root}/.kodi/addons/plugin.video.fixture"
  printf 'previous marker\n' > "${root}/.kodi/addons/plugin.video.fixture/marker.txt"
  guisettings="${root}/.kodi/userdata/guisettings.xml"
  printf '<settings version="2"><setting id="locale.language">old</setting></settings>\n' \
    > "${guisettings}"
  chmod 644 "${guisettings}"

  stage_addon_bundle "${dir}" "${root}" \
    "plugin.video.fixture:1.2.3:plugin.video.fixture" \
    "weather.ha:0.0.6.6:weather.ha-0.0.6.6"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "the deployment must succeed"

  assert_eq "previous marker" \
    "$(cat "${transaction}/rollback/addons/plugin.video.fixture/marker.txt")" \
    "the replaced add-on directory is retained in the transaction"
  if [[ ! -f "${transaction}/files/.kodi/userdata/guisettings.xml" ]]; then
    printf 'guisettings.xml must be copied into the dated backup\n' >&2
    return 1
  fi
  assert_contains "$(cat "${transaction}/files/.kodi/userdata/guisettings.xml")" \
    "old" "the backup holds the pre-deployment content"
  assert_eq "600" "$(file_mode "${transaction}/files/.kodi/userdata/guisettings.xml")" \
    "a copied secret-bearing file is normalized to 0600 even from a 0644 source"
  assert_eq "700" "$(file_mode "${transaction}")" "the transaction directory is private"
  assert_contains "$(cat "${transaction}/MANIFEST.txt")" \
    "rollback/addons/plugin.video.fixture" "the manifest records where the replaced add-on went"
  assert_contains "$(cat "${transaction}/MANIFEST.txt")" \
    "files/.kodi/userdata/guisettings.xml" "the manifest records the copied file"
}

test_remote_deploy_extracts_into_staging_before_replace() {
  local dir root bin_dir rc transaction destinations stage
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  stage="${root}/.cache/coreelec-provision/stage"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "the deployment must succeed"
  [[ -n "${transaction}" ]] || { printf 'no transaction path was printed\n' >&2; return 1; }

  destinations="$(sed -n 's/^unzip .*-d \([^ ]*\).*/\1/p' "${REMOTE_CALL_LOG}")"
  [[ -n "${destinations}" ]] || { printf 'no unzip call was recorded\n' >&2; return 1; }
  while IFS= read -r destination; do
    case "${destination}" in
      "${stage}"/*) ;;
      *)
        printf 'extraction escaped the staging directory: %s\n' "${destination}" >&2
        return 1
        ;;
    esac
  done <<< "${destinations}"

  assert_eq "new plugin.video.fixture 1.2.3" \
    "$(cat "${root}/.kodi/addons/plugin.video.fixture/marker.txt")" \
    "the staged add-on is moved into place only after extraction"
}

test_remote_deploy_records_manifest() {
  local dir root bin_dir transaction manifest stamp rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  stage_addon_bundle "${dir}" "${root}" \
    "plugin.video.fixture:1.2.3:plugin.video.fixture" \
    "script.module.fixture:2.0.0:script.module.fixture"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "the deployment must succeed"

  case "${transaction}" in
    "${root}/backup/coreelec-provision/"*) ;;
    *)
      printf 'the transaction must live under the dated backup root: %s\n' "${transaction}" >&2
      return 1
      ;;
  esac
  stamp="${transaction##*/}"
  if ! printf '%s' "${stamp}" | grep -Eq '^[0-9]{8}T[0-9]{6}Z(-[0-9]+)?$'; then
    printf 'the transaction directory must be UTC timestamped: %s\n' "${stamp}" >&2
    return 1
  fi

  manifest="$(cat "${transaction}/MANIFEST.txt")"
  assert_contains "${manifest}" "created_utc=" "the manifest records its creation time"
  assert_contains "${manifest}" "addon plugin.video.fixture" "the manifest records the first add-on"
  assert_contains "${manifest}" "addon script.module.fixture" "the manifest records the second add-on"
  assert_eq "600" "$(file_mode "${transaction}/MANIFEST.txt")" "the manifest is private"
}

test_remote_deploy_has_rollback_for_replaced_paths() {
  local dir root bin_dir transaction rc guisettings output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  mkdir -p "${root}/.kodi/addons/plugin.video.fixture"
  printf 'previous marker\n' > "${root}/.kodi/addons/plugin.video.fixture/marker.txt"
  guisettings="${root}/.kodi/userdata/guisettings.xml"
  printf '<settings version="2"><setting id="locale.language">old</setting></settings>\n' \
    > "${guisettings}"

  stage_addon_bundle "${dir}" "${root}" \
    "plugin.video.fixture:1.2.3:plugin.video.fixture" \
    "script.module.fixture:2.0.0:script.module.fixture"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "the deployment must succeed"
  assert_eq "new plugin.video.fixture 1.2.3" \
    "$(cat "${root}/.kodi/addons/plugin.video.fixture/marker.txt")" "the new add-on is live"
  assert_contains "$(cat "${guisettings}")" "resource.language.en_us" "settings were applied"

  # Rollback material survives the successful deployment so verification can
  # still undo it; Task 6 finalizes only after the device checks out.
  if [[ ! -d "${transaction}/rollback/addons/plugin.video.fixture" ]]; then
    printf 'rollback material must be retained after deployment\n' >&2
    return 1
  fi

  : > "${REMOTE_CALL_LOG}"
  set +e
  output="$(run_remote_script rollback "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the rollback must succeed: ${output}"

  assert_eq "previous marker" \
    "$(cat "${root}/.kodi/addons/plugin.video.fixture/marker.txt")" \
    "the replaced add-on is restored"
  if [[ -e "${root}/.kodi/addons/script.module.fixture" ]]; then
    printf 'a newly deployed add-on must be removed by the rollback\n' >&2
    return 1
  fi
  assert_contains "$(cat "${guisettings}")" ">old<" "guisettings.xml is restored from the backup"
  assert_contains "$(remote_calls)" "start kodi.service" "Kodi is restarted after the rollback"
  if [[ -e "${root}/.cache/coreelec-provision/current-transaction" ]]; then
    printf 'the pending-transaction pointer must be cleared by the rollback\n' >&2
    return 1
  fi
}

test_remote_deploy_rejects_manifest_path_injection() {
  local dir root bin_dir rc output stage victim
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  stage="${root}/.cache/coreelec-provision/stage"
  victim="${dir}/outside-the-root.txt"
  printf 'untouched\n' > "${victim}"

  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  local injection
  for injection in \
    '1\t../../../../etc/evil\t1.2.3\t1.zip\n' \
    '1\tplugin.video.fixture\t1.2.3\t../../../outside-the-root.txt\n' \
    '1\t/absolute\t1.2.3\t1.zip\n' \
    '1\tplugin.video.fixture; rm -rf /\t1.2.3\t1.zip\n'
  do
    : > "${REMOTE_CALL_LOG}"
    # The failure path removes the payload, so each injection starts from a
    # complete, deployable state and can only fail on the manifest itself.
    make_fake_storage "${dir}" >/dev/null
    printf "${injection}" > "${stage}/deploy.tsv"
    set +e
    output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "manifest injection must be refused: ${injection}"
    assert_eq "" "$(remote_calls)" "no service is touched for a rejected manifest"
    if [[ -e "${root}/.kodi/addons/plugin.video.fixture" ]]; then
      printf 'nothing may be deployed from a rejected manifest\n' >&2
      return 1
    fi
    assert_eq "untouched" "$(cat "${victim}")" "a path outside the storage root is never written"
  done
}

# --- Transaction lifecycle tests --------------------------------------------

test_remote_deploy_uses_addon_xml_id_not_zip_directory_name() {
  local dir root bin_dir rc transaction
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  # weather.ha, PM4K, and the Emby client all ship a ZIP whose root directory
  # carries a version suffix or an entirely different name.
  stage_addon_bundle "${dir}" "${root}" \
    "weather.ha:0.0.6.6:weather.ha-0.0.6.6" \
    "script.plexmod:1.3.19:plugin.video.pm4k"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "an add-on whose ZIP root differs from its ID must deploy"

  assert_eq "new weather.ha 0.0.6.6" \
    "$(cat "${root}/.kodi/addons/weather.ha/marker.txt")" \
    "the add-on is installed under its addon.xml ID"
  assert_eq "new script.plexmod 1.3.19" \
    "$(cat "${root}/.kodi/addons/script.plexmod/marker.txt")" \
    "a differently named ZIP root is installed under its addon.xml ID"
  assert_contains \
    "$(cat "${root}/.kodi/addons/weather.ha/resources/settings.xml")" \
    'type="number"' \
    "the deployed Weather schema uses Kodi 21's valid legacy numeric type" || return 1
  assert_not_contains \
    "$(cat "${root}/.kodi/addons/weather.ha/resources/settings.xml")" \
    'type="int"' \
    "the incompatible upstream Weather setting type is removed" || return 1
  if [[ -e "${root}/.kodi/addons/weather.ha-0.0.6.6" || -e "${root}/.kodi/addons/plugin.video.pm4k" ]]; then
    printf 'the ZIP root directory name must never become the install path\n' >&2
    return 1
  fi
}

test_remote_deploy_finalize_releases_rollback_material() {
  local dir root bin_dir transaction finalized rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  mkdir -p "${root}/.kodi/addons/plugin.video.fixture"
  printf 'previous marker\n' > "${root}/.kodi/addons/plugin.video.fixture/marker.txt"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "the deployment must succeed"

  set +e
  finalized="$(run_remote_script finalize "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "finalize must succeed after a deployment"
  assert_eq "${transaction}" "${finalized}" "finalize acts on the pending transaction"

  if [[ -e "${transaction}/rollback" ]]; then
    printf 'finalize must release the rollback material\n' >&2
    return 1
  fi
  if [[ -e "${root}/.cache/coreelec-provision/stage" ]]; then
    printf 'finalize must remove the uploaded staging bundle\n' >&2
    return 1
  fi
  if [[ -e "${root}/.cache/coreelec-provision/current-transaction" ]]; then
    printf 'finalize must clear the pending-transaction pointer\n' >&2
    return 1
  fi
  if [[ ! -f "${transaction}/MANIFEST.txt" ]]; then
    printf 'finalize must keep the dated backup and its manifest\n' >&2
    return 1
  fi
  assert_eq "new plugin.video.fixture 1.2.3" \
    "$(cat "${root}/.kodi/addons/plugin.video.fixture/marker.txt")" \
    "the deployed add-on stays in place after finalize"
  assert_contains "$(cat "${transaction}/MANIFEST.txt")" "finalized_utc=" \
    "finalize records its own timestamp"
}

test_remote_deploy_rolls_back_automatically_when_a_step_fails() {
  local dir root bin_dir rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  mkdir -p "${root}/.kodi/addons/plugin.video.fixture"
  printf 'previous marker\n' > "${root}/.kodi/addons/plugin.video.fixture/marker.txt"
  stage_addon_bundle "${dir}" "${root}" \
    "plugin.video.fixture:1.2.3:plugin.video.fixture" \
    "script.module.fixture:2.0.0:script.module.fixture"

  # The transformer runs after the add-ons are in place; a payload value that
  # is not valid base64 fails it mid-transaction, which is exactly the window
  # rollback exists for.
  replace_remote_payload_entry "${root}" TIMEZONE '!!!not-base64!!!'
  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a mid-transaction failure must fail the deployment"

  assert_eq "previous marker" \
    "$(cat "${root}/.kodi/addons/plugin.video.fixture/marker.txt")" \
    "the previous add-on is restored automatically"
  if [[ -e "${root}/.kodi/addons/script.module.fixture" ]]; then
    printf 'a newly deployed add-on must not survive the automatic rollback\n' >&2
    return 1
  fi
  assert_contains "$(remote_calls)" "start kodi.service" "Kodi is restarted after the rollback"
  if [[ -e "${root}/.cache/coreelec-provision/current-transaction" ]]; then
    printf 'a completed automatic rollback must clear the pointer\n' >&2
    return 1
  fi
}

# The transformer can fail after it has already rewritten some settings
# files, and the list of what it applied is only complete once it finishes.
# The automatic rollback must therefore restore from the backup it took, not
# from that partial list.
test_automatic_rollback_restores_settings_written_before_the_failure() {
  local dir root bin_dir rc output guisettings

  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  guisettings="${root}/.kodi/userdata/guisettings.xml"
  printf '<settings version="2"><setting id="locale.language">old</setting></settings>\n' \
    > "${guisettings}"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  # guisettings.xml is rewritten first and /storage/.cache/timezone last, so a
  # directory in the way of the last write fails the transformer only after
  # the first file is already on disk.
  mkdir -p "${root}/.cache/timezone"

  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a transformer failure must fail the transaction"

  assert_contains "$(cat "${guisettings}")" ">old<" \
    "a settings file written before the failure is restored from the backup"
  assert_not_contains "$(cat "${guisettings}")" "resource.language.en_us" \
    "no partially applied setting may survive the rollback"
}

# The failure path rebuilds APPLIED.txt from the transformer's raw output.
# That list is what rollback uses to delete managed files this run created,
# so a rebuild that cannot be completed must fail the rollback loudly rather
# than leave a truncated list behind and claim a complete restoration.
test_a_failed_applied_list_rebuild_never_claims_a_complete_rollback() {
  local dir root bin_dir rc output

  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  # Only the rebuild of the applied-path list fails; every other sed the
  # transaction runs behaves exactly as the device's own sed does.
  cat > "${bin_dir}/sed" <<'STUB'
#!/bin/bash
for argument in "$@"; do
  if [[ "${argument}" == *applied.raw ]]; then
    printf 'sed stub: forced failure reading %s\n' "${argument}" >&2
    exit 1
  fi
done
for candidate in /usr/bin/sed /bin/sed; do
  [[ -x "${candidate}" ]] && exec "${candidate}" "$@"
done
printf 'sed stub: no system sed was found\n' >&2
exit 127
STUB
  chmod 755 "${bin_dir}/sed"

  # Block the timezone cache write so the transformer fails after it has
  # already created managed files.
  mkdir -p "${root}/.cache/timezone"

  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a transformer failure must fail the transaction"
  assert_contains "${output}" "could not be rebuilt" \
    "the unusable applied-path list is reported"
  assert_contains "${output}" "ROLLBACK INCOMPLETE" \
    "a rollback without the applied-path list is incomplete"
  assert_not_contains "${output}" "the device was restored to its pre-deployment state" \
    "no complete restoration may be claimed"
  if [[ ! -f "${root}/.cache/coreelec-provision/current-transaction" ]]; then
    printf 'an incomplete rollback must retain the transaction pointer\n' >&2
    return 1
  fi
}

test_remote_deploy_refuses_a_second_pending_transaction() {
  local dir root bin_dir rc output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  set +e
  run_remote_script deploy "${root}" "${bin_dir}" >/dev/null 2>&1
  rc=$?
  set -e
  assert_success "${rc}" "the first deployment must succeed"

  # A real retry re-uploads the payload and the bundle; the refusal must come
  # from the pending transaction, not from a missing payload.
  make_fake_storage "${dir}" >/dev/null
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"
  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a second deployment must not discard pending rollback material"
  assert_contains "${output}" "rollback" "the refusal explains how to resolve the pending transaction"
}

test_remote_stage_upload_replaces_a_stale_bundle() {
  local dir root script stage source_dir rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  stage="${root}/.cache/coreelec-provision/stage"
  source_dir="${dir}/validated"
  mkdir -p "${source_dir}" "${stage}"
  printf 'stale\n' > "${stage}/stale.zip"
  chmod 777 "${stage}"
  printf '1\tplugin.video.fixture\t1.2.3\t1.zip\n' > "${source_dir}/deploy.tsv"
  printf 'zip bytes\n' > "${source_dir}/1.zip"

  script="$(render_remote_script stage "${root}")"
  assert_not_contains "${script}" "'" "the staging script travels inside a single-quoted remote command"

  set +e
  (cd "${source_dir}" && COPYFILE_DISABLE=1 tar -cf - deploy.tsv 1.zip) \
    | (umask 000; sh -c "${script}")
  rc=$?
  set -e
  assert_success "${rc}" "the staging upload must succeed"

  assert_eq "1	plugin.video.fixture	1.2.3	1.zip" "$(cat "${stage}/deploy.tsv")" \
    "the manifest is delivered"
  assert_eq "zip bytes" "$(cat "${stage}/1.zip")" "the artifact is delivered"
  assert_eq "700" "$(file_mode "${stage}")" "the staging directory is private"
  if [[ -e "${stage}/stale.zip" ]]; then
    printf 'a stale bundle must never survive a new upload\n' >&2
    return 1
  fi
}

test_rendered_remote_scripts_are_posix_clean() {
  local dir root name script
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"

  for name in stage deploy rollback finalize backup payload; do
    script="$(render_remote_script "${name}" "${root}")"
    if ! printf '%s\n' "${script}" | sh -n; then
      printf 'rendered %s script is not valid POSIX sh\n' "${name}" >&2
      return 1
    fi
    assert_not_contains "${script}" "[[" "rendered ${name} script avoids the bash test keyword"
    assert_not_contains "${script}" "declare " "rendered ${name} script avoids bash builtins"
  done
}

# --- Administrator public-key installation -----------------------------------

# Emulates what the device actually receives: the ssh client joins the
# remote-command argv into one string with single spaces, and sshd hands that
# whole string to the login shell as `-c`. Every quote the host writes into
# that argv is therefore parsed a second time on the device, which is exactly
# how a nested single-quoted program loses its quoting in transit.
run_through_ssh_transport() {
  local joined="$1"
  shift
  local word
  for word in "$@"; do
    joined="${joined} ${word}"
  done
  sh -c "${joined}"
}

# Writes one syntactically valid public key file. The CRLF is deliberate: a
# key file that travelled through a clipboard or a Windows editor carries one,
# and a carriage return inside authorized_keys makes the key unusable.
write_fixture_public_key() {
  local path="$1" blob="$2"
  printf 'ssh-ed25519 %s coreelec-admin@fixture\r\n' "${blob}" > "${path}"
}

# The administrator key is installed over the single password session a run is
# allowed, before any key exists, so this program gets exactly one attempt on
# a device the operator is standing in front of. It must therefore reach the
# device intact -- the program travels on stdin (`sh -s`), so the only argv
# words are `sh` and `-s` and the device's login shell has nothing of ours to
# re-parse -- and it must leave a usable, private authorized_keys behind.
test_the_public_key_program_installs_the_key_through_the_device_login_shell() {
  local dir root key_file program output rc blob candidate
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  mkdir -p "${root}"
  key_file="${dir}/coreelec-admin.pub"
  blob="AAAAC3NzaC1lZDI1NTE5AAAAIFixtureKeyBytesForProvisioningTests000"
  write_fixture_public_key "${key_file}" "${blob}"
  candidate="${root}/.ssh/authorized_keys.provision-candidate"

  program="$(render_remote_script authorized-key "${root}" "${key_file}")"
  if ! printf '%s\n' "${program}" | sh -n; then
    printf 'rendered authorized-key script is not valid POSIX sh\n' >&2
    return 1
  fi

  set +e
  output="$(printf '%s\n' "${program}" | run_through_ssh_transport sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the key install program must survive the device shell: ${output}"
  assert_eq "700" "$(file_mode "${root}/.ssh")" "the key directory stays private"
  assert_eq "600" "$(file_mode "${root}/.ssh/authorized_keys")" "authorized_keys stays private"
  assert_eq "1" "$(grep -c -F "${blob}" "${root}/.ssh/authorized_keys")" \
    "the administrator key is installed exactly once"
  assert_not_contains "$(cat "${root}/.ssh/authorized_keys")" "$(printf '\r')" \
    "no carriage return reaches authorized_keys"
  if [[ -e "${candidate}" ]]; then
    printf 'the candidate file must never be left behind\n' >&2
    return 1
  fi

  # A retry after a dropped connection, and an operator key that was already
  # there: neither may be duplicated or lost.
  printf 'ssh-rsa AAAAB3NzaC1yc2AAAAOperatorKeyBytes operator@fixture\n' \
    >> "${root}/.ssh/authorized_keys"
  set +e
  output="$(printf '%s\n' "${program}" | run_through_ssh_transport sh -s 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "re-running the key install must succeed: ${output}"
  assert_eq "1" "$(grep -c -F "${blob}" "${root}/.ssh/authorized_keys")" \
    "a second run never duplicates the administrator key"
  assert_eq "1" "$(grep -c -F "AAAAB3NzaC1yc2AAAAOperatorKeyBytes" "${root}/.ssh/authorized_keys")" \
    "an existing operator key survives the install"
  assert_eq "600" "$(file_mode "${root}/.ssh/authorized_keys")" \
    "authorized_keys is still private after the second run"

  # The key line is embedded in the program the device runs, so a file that is
  # not one well-formed key line has to be refused on the host, before anything
  # is sent and before it can close the here-document that carries it.
  printf "evil' \$(touch %s/pwned) key\n" "${dir}" > "${key_file}"
  set +e
  output="$(render_remote_script authorized-key "${root}" "${key_file}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a malformed public key file must be refused before any remote call"
  if [[ -e "${dir}/pwned" ]]; then
    printf 'a malformed key file must never execute anything\n' >&2
    return 1
  fi
}

# The defect this covers put the program in the ssh argv inside nested single
# quotes, where the device's login shell closed the quote at the embedded awk
# program and handed `sh -c` a program truncated mid-command substitution. The
# transport is the fix, so the transport is what is asserted here.
test_the_public_key_install_never_sends_a_quoted_program_in_the_ssh_argv() {
  local source install_body
  source="$(cat "${PROVISIONER}")"
  install_body="$(printf '%s\n' "${source}" \
    | sed -n '/^install_public_key_if_needed()/,/^}/p')"
  assert_contains "${install_body}" "ssh_password 'sh -s'" \
    "the key install program travels on stdin, not in the argv"
  assert_not_contains "${install_body}" "sh -c" \
    "no remote program is passed as a re-parsed argv word"
  assert_not_contains "${install_body}" "awk" \
    "the awk program never crosses the local, ssh, and device shells"
}

# --- Add-on selection tests --------------------------------------------------

print_addon_selection() {
  local manifest="$1"
  shift
  bash "${PROVISIONER}" \
    --config "${SCRIPT_DIR}/../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf" \
    --print-addon-selection "${manifest}" "$@"
}

write_selection_manifest() {
  local manifest="$1"
  {
    printf '1\tscript.plexmod\t1.3.19\t1.zip\n'
    printf '2\tscript.module.requests\t2.31.0\t2.zip\n'
    printf '3\tweather.ha\t0.0.6.6\t3.zip\n'
  } > "${manifest}"
}

test_addon_selection_defaults_to_the_locked_manifest() {
  local dir manifest output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  manifest="${dir}/manifest.tsv"
  write_selection_manifest "${manifest}"

  output="$(print_addon_selection "${manifest}")"
  assert_eq "3" "$(printf '%s\n' "${output}" | grep -c .)" "every locked artifact is selected"
  assert_contains "${output}" "weather.ha" "the selection keeps the locked IDs"
}

test_addon_selection_filters_to_requested_ids() {
  local dir manifest output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  manifest="${dir}/manifest.tsv"
  write_selection_manifest "${manifest}"

  output="$(print_addon_selection "${manifest}" --addon script.plexmod)"
  assert_eq "1" "$(printf '%s\n' "${output}" | grep -c .)" "only the requested add-on is selected"
  assert_contains "${output}" "script.plexmod" "the requested add-on is kept"
  assert_not_contains "${output}" "weather.ha" "unrequested add-ons are dropped"
}

test_addon_selection_rejects_an_unlocked_id() {
  local dir manifest output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  manifest="${dir}/manifest.tsv"
  write_selection_manifest "${manifest}"

  set +e
  output="$(print_addon_selection "${manifest}" --addon plugin.video.unknown 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an add-on outside the locked manifest must be refused"
  assert_contains "${output}" "plugin.video.unknown" "the error names the unknown add-on"
}

# The device and the local fixture harness must run the same transformer, or
# a fixture rehearsal would stop predicting what the device does. This runs
# both copies over identical inputs and compares the resulting trees.
test_deploy_script_embeds_the_fixture_transformer_verbatim() {
  local dir fixture_root deploy_root payload embedded

  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN

  fixture_root="$(make_fake_storage "${dir}")"
  payload="${dir}/payload.conf"
  cp "${fixture_root}/.cache/coreelec-provision/settings-payload.conf" "${payload}"

  deploy_root="${dir}/deploy-storage"
  cp -R "${fixture_root}" "${deploy_root}"

  embedded="${dir}/embedded-transformer.py"
  render_remote_script deploy /storage \
    | awk '/^python3 - .* <<.PYTHON_KODI_SETTINGS.$/ { capture = 1; next }
           /^PYTHON_KODI_SETTINGS$/ { capture = 0 }
           capture { print }' > "${embedded}"
  [[ -s "${embedded}" ]] \
    || { printf 'no transformer is embedded in the deployment script\n' >&2; return 1; }

  bash "${PROVISIONER}" --transform-fixture "${fixture_root}" "${payload}" >/dev/null
  python3 "${embedded}" "${deploy_root}" "${payload}" >/dev/null

  rm -rf -- "${fixture_root}/.cache" "${deploy_root}/.cache"
  if ! diff -r "${fixture_root}" "${deploy_root}" >/dev/null; then
    printf 'the embedded transformer produced a different result than the fixture path:\n' >&2
    diff -r "${fixture_root}" "${deploy_root}" >&2
    return 1
  fi
}

test_provisioner_never_installs_addons_through_kodi() {
  local source
  source="$(cat "${PROVISIONER}")"
  assert_not_contains "${source}" "InstallAddon(" "modal add-on installation is gone"
  assert_not_contains "${source}" "EnableAddon(" "modal add-on enabling is gone"
  assert_not_contains "${source}" "install_requested_addons" "the modal installer function is gone"
}

# --- Transaction pointer confinement ----------------------------------------

# The pointer file is device state: a truncated write, a manual edit, or a
# planted file can name anything. It is what the EXIT trap rolls back, so a
# pointer that is not confined to the backup root must be refused before it is
# ever adopted, not after.
test_a_malformed_transaction_pointer_never_arms_rollback() {
  local dir root bin_dir rc output pointer outside
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  mkdir -p "${root}/.kodi/addons/plugin.video.fixture"
  printf 'live marker\n' > "${root}/.kodi/addons/plugin.video.fixture/marker.txt"

  # A complete, plausible transaction directory outside the backup root: if
  # the pointer were adopted before validation, the rollback would delete the
  # live add-on and move this planted copy into its place.
  outside="${dir}/outside-the-backup-root"
  mkdir -p "${outside}/rollback/addons/plugin.video.fixture" "${outside}/files"
  printf 'planted marker\n' \
    > "${outside}/rollback/addons/plugin.video.fixture/marker.txt"
  printf 'plugin.video.fixture\n' > "${outside}/DEPLOYED.txt"
  pointer="${root}/.cache/coreelec-provision/current-transaction"
  printf '%s\n' "${outside}" > "${pointer}"

  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a malformed transaction pointer must refuse the deployment"
  assert_contains "${output}" "pointer" "the refusal names the pointer"
  assert_eq "" "$(remote_calls)" "no service is touched for a malformed pointer"
  assert_eq "${outside}" "$(cat "${pointer}")" \
    "the malformed pointer is retained for the operator, never silently removed"
  assert_eq "planted marker" \
    "$(cat "${outside}/rollback/addons/plugin.video.fixture/marker.txt")" \
    "nothing outside the backup root is moved"
  assert_eq "live marker" \
    "$(cat "${root}/.kodi/addons/plugin.video.fixture/marker.txt")" \
    "no add-on is removed or restored"
  if [[ -e "${outside}/STATE" ]]; then
    printf 'nothing may be written into an unvalidated transaction directory\n' >&2
    return 1
  fi
  if [[ -e "${root}/.kodi/addons/script.module.fixture" ]]; then
    printf 'nothing may be deployed behind a malformed pointer\n' >&2
    return 1
  fi
}

# A pointer that is well formed but names a directory that no longer exists is
# stale, not pending. Clearing it is correct, but doing so silently hides the
# fact that a previous run's rollback material is gone.
test_a_stale_transaction_pointer_is_reported_when_it_is_cleared() {
  local dir root bin_dir rc output pointer
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  pointer="${root}/.cache/coreelec-provision/current-transaction"
  printf '%s\n' "${root}/backup/coreelec-provision/20200101T000000Z" > "${pointer}"

  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "a stale pointer must not block a new deployment: ${output}"
  assert_contains "${output}" "stale" "the discarded stale pointer is reported"
  assert_contains "${output}" "20200101T000000Z" "the report names the missing transaction"
}

# --- Rollback completeness ---------------------------------------------------

# STATE and the pointer are how the operator and Task 6 learn what happened. A
# rollback that restores the files but cannot record its own outcome is an
# incomplete rollback: it must keep the pointer and fail loudly.
test_a_rollback_that_cannot_record_its_state_reports_failure() {
  local dir root bin_dir transaction rc output pointer
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  mkdir -p "${root}/.kodi/addons/plugin.video.fixture"
  printf 'previous marker\n' > "${root}/.kodi/addons/plugin.video.fixture/marker.txt"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "the deployment must succeed"

  # A directory where STATE belongs fails the write for any user, including
  # root, which a mode change would not.
  rm -f "${transaction}/STATE"
  mkdir "${transaction}/STATE"

  : > "${REMOTE_CALL_LOG}"
  set +e
  output="$(run_remote_script rollback "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a rollback that cannot record its outcome must not report success"
  assert_contains "${output}" "ROLLBACK INCOMPLETE" "the incomplete rollback is announced"
  assert_contains "${output}" "${transaction}" "the retained transaction path is printed"

  pointer="${root}/.cache/coreelec-provision/current-transaction"
  if [[ ! -f "${pointer}" ]]; then
    printf 'an incomplete rollback must keep the pending-transaction pointer\n' >&2
    return 1
  fi
  assert_eq "${transaction}" "$(cat "${pointer}")" "the pointer still names the transaction"
  assert_eq "previous marker" \
    "$(cat "${root}/.kodi/addons/plugin.video.fixture/marker.txt")" \
    "the restore itself still happened"
}

# --- Remote plan-field validation -------------------------------------------

# The plan's archive name and top-level directory are interpolated into device
# paths exactly like the add-on ID, so all three are revalidated by the shell
# that uses them, not only by the Python validator that produced them.
test_the_remote_transaction_revalidates_every_plan_field() {
  local dir root program output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  program="${dir}/plan-validators.sh"

  {
    extract_transaction_prologue "${root}"
    cat <<'CHECKS'
check() {
  if "$1" "$2"; then
    printf '%s accepts %s\n' "$1" "$2"
  else
    printf '%s rejects %s\n' "$1" "$2"
  fi
}
check valid_addon_id plugin.video.fixture
check valid_addon_id ../../../etc/evil
check valid_archive_name 1.zip
check valid_archive_name ../../outside.zip
check valid_archive_name evil.zip
check valid_directory_name weather.ha-0.0.6.6
check valid_directory_name ../escape
check valid_directory_name /absolute
CHECKS
  } > "${program}"

  set +e
  output="$(sh "${program}" 2>&1)"
  rc=$?
  set -e
  assert_success "${rc}" "the rendered validators must run under POSIX sh: ${output}"
  assert_contains "${output}" "valid_addon_id accepts plugin.video.fixture" "a real ID is accepted"
  assert_contains "${output}" "valid_addon_id rejects ../../../etc/evil" "a traversal ID is refused"
  assert_contains "${output}" "valid_archive_name accepts 1.zip" "an indexed archive is accepted"
  assert_contains "${output}" "valid_archive_name rejects ../../outside.zip" "a traversal archive is refused"
  assert_contains "${output}" "valid_archive_name rejects evil.zip" "only indexed archive names are accepted"
  assert_contains "${output}" "valid_directory_name accepts weather.ha-0.0.6.6" "a real ZIP root is accepted"
  assert_contains "${output}" "valid_directory_name rejects ../escape" "a traversal ZIP root is refused"
  assert_contains "${output}" "valid_directory_name rejects /absolute" "an absolute ZIP root is refused"
}

test_the_remote_transaction_rejects_malformed_plan_shape() {
  local dir root program plan output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  program="${dir}/plan-shape-validator.sh"
  plan="${dir}/malformed-plan.tsv"
  printf 'component\tcore\t0\t\n' > "${plan}"
  printf 'component\tcec\t1\n' >> "${plan}"
  printf 'component\taddons\t0\n' >> "${plan}"
  printf 'component\tservices\t0\n' >> "${plan}"
  printf 'component\tskin\t0\n' >> "${plan}"

  {
    extract_transaction_prologue "${root}"
    printf 'load_deployment_plan %q complete\n' "${plan}"
    printf '%s\n' "printf 'malformed plan accepted\n'"
  } > "${program}"

  set +e
  output="$(sh "${program}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a component row with an extra field must be rejected"
  assert_contains "${output}" "malformed" \
    "the remote plan-shape failure is reported explicitly"
  assert_not_contains "${output}" "malformed plan accepted" \
    "the malformed remote plan never reaches mutation"
}

# /storage/backup is CoreELEC's own backup location. The transaction makes its
# own subtree private and leaves the shared parent's mode alone.
test_the_transaction_never_changes_the_shared_backup_directory() {
  local dir root bin_dir transaction rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"
  mkdir -p "${root}/backup"
  chmod 755 "${root}/backup"
  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "the deployment must succeed"
  assert_eq "755" "$(file_mode "${root}/backup")" \
    "the shared backup directory keeps the mode the device gave it"
  assert_eq "700" "$(file_mode "${transaction}")" "the transaction itself is private"
}

test_the_render_flag_is_an_alias_of_the_deploy_emitter() {
  local dir root rendered emitted
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="${dir}/storage"
  rendered="$(bash "${PROVISIONER}" --render-remote-deploy-script "${root}")"
  emitted="$(bash "${PROVISIONER}" --emit-remote-script deploy "${root}")"
  assert_eq "${emitted}" "${rendered}" "both internal modes must render the same program"
}

# --- Local ordering and preflight -------------------------------------------

test_non_addon_plan_creates_an_empty_manifest_without_artifact_work() {
  local dir log
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  log="${dir}/artifact-preflight.log"
  : > "${log}"

  load_provisioner_function prepare_artifact_deployment || return 1
  coreelec_component_effective() { [[ "$1" == "cec" ]]; }
  require_command() { printf 'require %s\n' "$1" >> "${log}"; }
  info() { printf 'info\n' >> "${log}"; }
  warn() { printf 'warn\n' >> "${log}"; }
  coreelec_artifacts_download_and_validate() { printf 'download\n' >> "${log}"; }
  coreelec_addon_selection() { printf 'selection\n' >> "${log}"; }
  TASK_TEMP_DIR="${dir}"
  ARTIFACT_STAGE_DIR=""
  DEPLOY_MANIFEST=""

  prepare_artifact_deployment

  assert_eq "${dir}/artifacts/deploy.tsv" "${DEPLOY_MANIFEST}" \
    "the non-add-on plan still exposes a deploy manifest"
  if [[ ! -f "${DEPLOY_MANIFEST}" || -s "${DEPLOY_MANIFEST}" ]]; then
    printf 'the non-add-on deploy manifest must exist and be genuinely empty\n' >&2
    return 1
  fi
  assert_eq "600" "$(file_mode "${DEPLOY_MANIFEST}")" \
    "the empty deploy manifest is private"
  assert_eq "" "$(cat "${log}")" \
    "non-add-on planning does not require, download, select, or warn about artifacts"
}

test_non_addon_baseline_skips_artifact_upload() {
  local dir log
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  log="${dir}/baseline-calls.log"
  : > "${log}"

  load_provisioner_function apply_kodi_baseline || return 1
  coreelec_component_effective() { [[ "$1" == "cec" ]]; }
  info() { :; }
  upload_artifact_bundle() { printf 'bundle\n' >> "${log}"; }
  upload_kodi_settings_payload() { printf 'payload\n' >> "${log}"; }
  deploy_artifacts_and_settings() { printf 'deploy\n' >> "${log}"; }
  wait_for_kodi_jsonrpc() { printf 'verify\n' >> "${log}"; }
  ARTIFACT_STAGE_DIR="${dir}/artifacts"

  apply_kodi_baseline

  assert_eq "payload
deploy
verify" "$(cat "${log}")" \
    "a non-add-on transaction skips bundle upload but keeps one combined transaction"
}

# The payload is the only thing that carries secrets to the device. It is
# uploaded last, immediately before the transaction that consumes and removes
# it, so no earlier failure can strand it.
test_the_artifact_bundle_is_staged_before_the_secret_payload() {
  local dir log
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  log="${dir}/baseline-calls.log"
  : > "${log}"

  load_provisioner_function apply_kodi_baseline || return 1
  coreelec_component_effective() { [[ "$1" == "addons" ]]; }
  info() { :; }
  upload_artifact_bundle() { printf 'bundle %s\n' "$1" >> "${log}"; }
  upload_kodi_settings_payload() { printf 'payload\n' >> "${log}"; }
  deploy_artifacts_and_settings() { printf 'deploy\n' >> "${log}"; }
  wait_for_kodi_jsonrpc() { printf 'verify\n' >> "${log}"; }
  ARTIFACT_STAGE_DIR="${dir}/artifacts"

  apply_kodi_baseline

  assert_eq "bundle ${dir}/artifacts
payload
deploy
verify" "$(cat "${log}")" \
    "the bundle is staged first and the payload is uploaded immediately before the transaction"
}

test_a_failed_bundle_upload_never_uploads_the_secret_payload() {
  local dir log rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  log="${dir}/baseline-calls.log"
  : > "${log}"

  load_provisioner_function apply_kodi_baseline || return 1
  coreelec_component_effective() { [[ "$1" == "addons" ]]; }
  info() { :; }
  upload_artifact_bundle() { printf 'bundle\n' >> "${log}"; return 1; }
  upload_kodi_settings_payload() { printf 'payload\n' >> "${log}"; }
  deploy_artifacts_and_settings() { printf 'deploy\n' >> "${log}"; }
  wait_for_kodi_jsonrpc() { printf 'verify\n' >> "${log}"; }
  ARTIFACT_STAGE_DIR="${dir}/artifacts"

  set +e
  ( set -e; apply_kodi_baseline ) >/dev/null 2>&1
  rc=$?
  set -e
  assert_failure "${rc}" "a failed staging step must fail the baseline"
  assert_eq "bundle" "$(cat "${log}")" \
    "a failure before the transaction leaves no secret payload on the device"
}

# A transport failure can drop the connection before the transaction (and its
# trap) ever runs, which is the one window where the payload could survive on
# the device.
test_a_failed_deployment_discards_the_remote_secret_payload() {
  local dir log rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  log="${dir}/deploy-calls.log"
  : > "${log}"

  load_provisioner_function deploy_artifacts_and_settings || return 1
  info() { :; }
  die() { printf 'die\n' >> "${log}"; exit 1; }
  coreelec_remote_deploy_script() { printf 'true\n'; }
  ssh_keyed() { cat >/dev/null; return 9; }
  discard_remote_settings_payload() { printf 'discard\n' >> "${log}"; }

  set +e
  ( set -e; deploy_artifacts_and_settings ) >/dev/null 2>&1
  rc=$?
  set -e
  assert_failure "${rc}" "a failed deployment must fail the run"
  assert_eq "discard
die" "$(cat "${log}")" "the secret payload is discarded before the run gives up"
}

# An --addon that is not in the lock is a local mistake. It must cancel the run
# before the administrator key is installed, the backup is taken, and SSH is
# hardened, not after all three have already changed the device.
test_an_unlocked_addon_is_refused_before_any_remote_call() {
  local dir bin_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_network_stubs "${dir}")"

  set +e
  output="$(OMDB_API_KEY=fixture-omdb MDBLIST_API_KEY=fixture-mdblist \
    run_provisioner_offline "${dir}" "${bin_dir}" \
    --target 192.0.2.1 --addon plugin.video.unknown --yes 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an --addon outside the lock must cancel the run"
  assert_contains "${output}" "plugin.video.unknown" "the error names the unknown add-on"
  assert_eq "" "$(cat "${dir}/network-calls.log")" \
    "no key install, backup, or hardening runs before the selection is validated"
  if [[ -e "${dir}/scratch_admin_key" ]]; then
    printf 'no administrator key may be created for a refused selection\n' >&2
    return 1
  fi
}

# Bash 3.2 treats "${array[@]}" on an empty array as an unbound variable under
# `set -u`. The default run selects every locked add-on and
# therefore leaves ADDONS empty, so this is the ordinary path, not an edge case.
test_a_default_run_survives_the_empty_addon_array_under_bash_3_2() {
  local dir bin_dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_network_stubs "${dir}")"

  set +e
  output="$(OMDB_API_KEY=fixture-omdb MDBLIST_API_KEY=fixture-mdblist \
    run_provisioner_offline "${dir}" "${bin_dir}" --target 192.0.2.1 2>&1)"
  rc=$?
  set -e
  assert_not_contains "${output}" "unbound variable" \
    "an empty add-on selection must not abort under Bash 3.2"
  assert_contains "${output}" "Continue?" "the default run reaches the confirmation prompt"
  assert_failure "${rc}" "declining the confirmation cancels the run"
  assert_eq "" "$(cat "${dir}/network-calls.log")" "a cancelled run never contacts the device"
}

# The read-only platform check is the first remote call of a run, and an
# unreachable or unauthenticated device is its most common outcome. Ending on
# ssh's own exit status leaves the operator with a bare transport message right
# after being told to type a password that was never asked for, so the run must
# fail with its own diagnostic instead.
test_an_unreachable_target_fails_with_an_actionable_error() {
  local dir bin_dir output rc calls
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_network_stubs "${dir}")"
  # An administrator key that already exists carries the run past key creation
  # and into the platform read, which is the call under test.
  printf 'scratch administrator key\n' > "${dir}/scratch_admin_key"
  printf 'ssh-ed25519 AAAA scratch\n' > "${dir}/scratch_admin_key.pub"

  set +e
  output="$(OMDB_API_KEY=fixture-omdb MDBLIST_API_KEY=fixture-mdblist \
    run_provisioner_offline "${dir}" "${bin_dir}" --target 192.0.2.1 --yes 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "an unreachable target must fail the run" || return 1
  assert_contains "${output}" "ERROR:" \
    "the run reports its own error rather than ssh's exit status" || return 1
  assert_contains "${output}" "192.0.2.1" \
    "the diagnostic names the target that could not be reached" || return 1
  assert_contains "${output}" "Nothing on the device has been changed." \
    "the diagnostic states that the device is untouched" || return 1
  calls="$(cat "${dir}/network-calls.log")"
  assert_not_contains "${calls}" "curl " \
    "a failed platform read stops before any artifact is downloaded" || return 1
  assert_not_contains "${calls}" "authorized_keys" \
    "a failed platform read stops before the key install" || return 1
}

# The platform read has a second branch: the administrator key is already
# accepted (BatchMode probe succeeds, so KEY_ALREADY_ACCEPTED=1 and password
# auth is never attempted), but the identity read itself then fails -- the
# device dropped off the network, or the key was revoked, between the probe
# and the read. This must die with its own diagnostic naming the identity
# file, not fall through to the password branch or leak ssh's bare exit
# status, and it must still stop before any artifact download or key install.
test_a_keyed_but_failing_identity_read_fails_with_an_actionable_error() {
  local dir bin_dir output rc calls
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_network_stubs "${dir}")"
  # Only the BatchMode probe ("ssh_keyed_batch true") succeeds, simulating an
  # already-accepted key; every other ssh invocation -- including the
  # sh -c identity script that ssh_keyed sends -- still fails.
  cat > "${bin_dir}/ssh" <<STUB
#!/bin/bash
printf 'ssh %s\n' "\$*" >> "${dir}/network-calls.log"
case " \$* " in
  *" -o BatchMode=yes "*" true"*) exit 0 ;;
  *) exit 255 ;;
esac
STUB
  chmod +x "${bin_dir}/ssh"
  printf 'scratch administrator key\n' > "${dir}/scratch_admin_key"
  printf 'ssh-ed25519 AAAA scratch\n' > "${dir}/scratch_admin_key.pub"

  set +e
  output="$(OMDB_API_KEY=fixture-omdb MDBLIST_API_KEY=fixture-mdblist \
    run_provisioner_offline "${dir}" "${bin_dir}" --target 192.0.2.1 --yes 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a keyed but failing identity read must fail the run" || return 1
  assert_contains "${output}" "ERROR:" \
    "the run reports its own error rather than ssh's exit status" || return 1
  assert_contains "${output}" "192.0.2.1" \
    "the diagnostic names the target that could not be reached" || return 1
  assert_contains "${output}" "scratch_admin_key" \
    "the diagnostic names the administrator key file that was used" || return 1
  assert_contains "${output}" "Nothing on the device has been changed." \
    "the diagnostic states that the device is untouched" || return 1
  assert_not_contains "${output}" "temporary CoreELEC root password" \
    "an already-accepted key must never prompt for the temporary password" || return 1
  calls="$(cat "${dir}/network-calls.log")"
  assert_not_contains "${calls}" "curl " \
    "a failed identity read stops before any artifact is downloaded" || return 1
  assert_not_contains "${calls}" "authorized_keys" \
    "a failed identity read stops before the key install" || return 1
}

# --- Ratings-key preflight ---------------------------------------------------

# A real Kodi deployment (APPLY_KODI=1, the default) must refuse before any
# network command when both API keys are absent, when only OMDB is set, or
# when only MDBLIST is set.
test_real_kodi_deployment_requires_both_ratings_keys_before_device_contact() {
  local dir bin_dir output rc
  # Isolate from ambient environment secrets so the preflight tests are
  # deterministic regardless of the operator's shell, and put them back so
  # this test does not change the environment later tests observe.
  stash_unset_env OMDB_API_KEY MDBLIST_API_KEY

  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"; restore_stashed_env' RETURN
  bin_dir="$(install_network_stubs "${dir}")"

  # Case 1: neither key.
  set +e
  output="$(run_provisioner_offline "${dir}" "${bin_dir}" \
    --target 192.0.2.1 --yes 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "neither key: run must fail" || return 1
  assert_contains "${output}" "OMDB_API_KEY" \
    "neither key: error names OMDB_API_KEY" || return 1
  assert_eq "" "$(cat "${dir}/network-calls.log")" \
    "neither key: no network contact before the preflight" || return 1
  : > "${dir}/network-calls.log"

  # Case 2: only OMDB_API_KEY set — MDBLIST_API_KEY missing.
  set +e
  output="$(OMDB_API_KEY=omdb-secret-never-log \
    run_provisioner_offline "${dir}" "${bin_dir}" --target 192.0.2.1 --yes 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "only OMDB: run must fail" || return 1
  assert_contains "${output}" "MDBLIST_API_KEY" \
    "only OMDB: error names MDBLIST_API_KEY" || return 1
  assert_not_contains "${output}" "omdb-secret-never-log" \
    "only OMDB: secret value must not appear in output" || return 1
  assert_eq "" "$(cat "${dir}/network-calls.log")" \
    "only OMDB: no network contact before the preflight" || return 1
  : > "${dir}/network-calls.log"

  # Case 3: only MDBLIST_API_KEY set — OMDB_API_KEY missing.
  set +e
  output="$(MDBLIST_API_KEY=mdblist-secret-never-log \
    run_provisioner_offline "${dir}" "${bin_dir}" --target 192.0.2.1 --yes 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "only MDBLIST: run must fail" || return 1
  assert_contains "${output}" "OMDB_API_KEY" \
    "only MDBLIST: error names OMDB_API_KEY" || return 1
  assert_not_contains "${output}" "mdblist-secret-never-log" \
    "only MDBLIST: secret value must not appear in output" || return 1
  assert_eq "" "$(cat "${dir}/network-calls.log")" \
    "only MDBLIST: no network contact before the preflight" || return 1
}

# A --no-kodi run does not write Arctic Fuse state and must not be gated on
# ratings keys. It should reach the first read-only SSH call, proving that
# the preflight is skipped for non-Kodi deployment.
test_no_kodi_deployment_does_not_require_ratings_keys() {
  local dir bin_dir rc calls
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  bin_dir="$(install_network_stubs "${dir}")"
  # Provide an existing admin key so the run skips key creation and reaches
  # the platform-read SSH call immediately.
  printf 'scratch administrator key\n' > "${dir}/scratch_admin_key"
  printf 'ssh-ed25519 AAAA scratch\n' > "${dir}/scratch_admin_key.pub"

  set +e
  run_provisioner_offline "${dir}" "${bin_dir}" \
    --target 192.0.2.1 --yes --no-kodi >/dev/null 2>&1
  rc=$?
  set -e
  assert_failure "${rc}" "--no-kodi without keys fails (SSH stub exits 1), not a key-gate failure" || return 1
  calls="$(cat "${dir}/network-calls.log")"
  assert_contains "${calls}" "ssh " \
    "--no-kodi reached the first SSH call without a ratings-key gate" || return 1
}

# --- Audit report ------------------------------------------------------------

# Task 6 reads this report. Every line the provisioner writes itself is
# key=value, and the pending transaction and its state are named explicitly.
test_the_audit_report_is_key_value_and_names_the_pending_transaction() {
  local dir report body line name
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN

  # The writer is assembled from several small functions; loading each one
  # keeps this a unit test of the report itself, including the device
  # inventory block that the Task 6 fixtures deliberately skip.
  for name in coreelec_report_path coreelec_manifest_contains \
    coreelec_weather_configured coreelec_nextpvr_configured \
    coreelec_secret_names coreelec_secret_value \
    coreelec_config_fingerprint coreelec_report_manual_actions \
    coreelec_report_render coreelec_report_redaction_check \
    coreelec_write_report_file coreelec_remote_inventory write_audit_report; do
    load_provisioner_function "${name}" || return 1
  done
  timestamp() { printf '2026-01-01T00:00:00Z\n'; }
  ssh_keyed() { cat >/dev/null; printf 'hostname=fixture\n'; }
  SCRIPT_VERSION="9.9.9"
  TARGET="192.0.2.1"
  SSH_PORT="22"
  IDENTITY_FILE="${dir}/scratch_admin_key"
  HARDEN_SSH="1"
  APPLY_KODI="1"
  KODI_PORT="8080"
  KODI_USER="homeassistant"
  REPORT_DIR="${dir}/reports"
  REMOTE_TRANSACTION="/storage/backup/coreelec-provision/20260101T000000Z"
  REMOTE_BACKUP_PATH=""
  ARTIFACT_STAGE_DIR="${dir}/artifacts"
  ADDONS=()
  DEPLOYMENT_STATE="pending-verification"
  VERIFICATION_RESULT="not-run"
  VERIFICATION_REPORT_FILE=""
  RECOVERY_INSTRUCTIONS=""
  KODI_JSONRPC_LOCAL_REACHABLE="unknown"
  CONFIG_FILE="${dir}/provision.conf"
  EXPECTED_RELEASE="21.3"
  TIMEZONE="America/Los_Angeles"
  TIMEZONE_COUNTRY="United States"
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
  ADDON_ARTIFACTS=()
  mkdir -p "${ARTIFACT_STAGE_DIR}"
  write_manifest "${ARTIFACT_STAGE_DIR}/deploy.tsv"
  DEPLOY_MANIFEST="${ARTIFACT_STAGE_DIR}/deploy.tsv"

  report="$(write_audit_report)"
  [[ -f "${report}" ]] || { printf 'no report file was written\n' >&2; return 1; }

  body="$(awk '/^remote_inventory=/ { exit } { print }' "${report}")"
  [[ -n "${body}" ]] || { printf 'the report has no local section\n' >&2; return 1; }
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    case "${line}" in
      *=*)
        case "${line%%=*}" in
          ""|*[!A-Za-z0-9_.-]*)
            printf 'report key is not a plain identifier: %s\n' "${line}" >&2
            return 1
            ;;
        esac
        ;;
      *)
        printf 'report line is not key=value: %s\n' "${line}" >&2
        return 1
        ;;
    esac
  done <<< "${body}"

  assert_contains "${body}" \
    "deployment_transaction=/storage/backup/coreelec-provision/20260101T000000Z" \
    "Task 6 can find the pending transaction"
  assert_contains "${body}" "deployment_state=pending-verification" \
    "the report records the deployment state"
  assert_contains "${body}" "requested_addons=all-locked-artifacts" \
    "a default run records that the whole lock was selected"
  assert_eq "41" "$(printf '%s\n' "${body}" | grep -c '^deployed_addon\.')" \
    "the report inventories every locked deployed artifact"
  assert_contains "${body}" "deployed_addon.resource.uisounds.fromashes=3.0.01" \
    "the generic deployed-add-on inventory includes From Ashes"
  assert_contains "${body}" "deployed_addon.script.texturemaker=0.2.11" \
    "the generic deployed-add-on inventory reaches the end of the lock"
}

# The managed skin paths added by Task 3 (skin settings, skinvariables nodes,
# and playlists) participate in the same backup/rollback transaction as
# guisettings.xml and add-on settings. This test proves that a pre-existing
# managed file is restored and a newly created managed file is removed when the
# transformer fails mid-run, using the same forced-failure pattern as the
# existing guisettings rollback test.
test_automatic_rollback_restores_skin_managed_paths() {
  local dir root bin_dir rc output
  local tv_widgets_path tv_widgets_content
  local movie_widgets_path
  local trakt_playlist_path
  local current_year_playlist current_year_playlist_content
  local old_playlist old_playlist_content

  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  tv_widgets_path="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-1101widgets.json"
  tv_widgets_content='[{"guid":"old-tv-widget"}]'
  movie_widgets_path="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-1102widgets.json"
  trakt_playlist_path="${root}/.kodi/userdata/playlists/video/TraktPopularTVShows.xsp"
  current_year_playlist="${root}/.kodi/userdata/playlists/video/RecentlyReleasedMoviesCurrentYear.xsp"
  current_year_playlist_content='<?xml version="1.0"?><smartplaylist type="movies"><name>current-year</name></smartplaylist>'
  mkdir -p "$(dirname "${tv_widgets_path}")"
  printf '%s\n' "${tv_widgets_content}" > "${tv_widgets_path}"
  mkdir -p "$(dirname "${current_year_playlist}")"
  printf '%s\n' "${current_year_playlist_content}" > "${current_year_playlist}"

  # Pre-seed the obsolete movie playlist; rollback must restore its exact content.
  old_playlist="${root}/.kodi/userdata/playlists/video/RecentlyReleasedMovies90Days.xsp"
  old_playlist_content='<?xml version="1.0"?><smartplaylist type="movies"><name>old</name></smartplaylist>'
  mkdir -p "$(dirname "${old_playlist}")"
  printf '%s\n' "${old_playlist_content}" > "${old_playlist}"

  stage_addon_bundle "${dir}" "${root}" "plugin.video.fixture:1.2.3:plugin.video.fixture"

  # Block the timezone cache write so the transformer fails after it has
  # already rewritten the home widgets JSON and created the playlists.
  mkdir -p "${root}/.cache/timezone"

  set +e
  output="$(run_remote_script deploy "${root}" "${bin_dir}" 2>&1)"
  rc=$?
  set -e
  assert_failure "${rc}" "a transformer failure must fail the transaction"

  # A pre-existing managed file must be restored from the backup.
  if [ ! -f "${tv_widgets_path}" ]; then
    printf 'the pre-existing TV widgets JSON was not restored by rollback\n' >&2
    return 1
  fi
  assert_eq "${tv_widgets_content}" "$(cat "${tv_widgets_path}")" \
    "the pre-existing TV widgets JSON is restored byte-for-byte by the rollback"

  # A newly created managed file must be removed by the rollback.
  if [ -e "${movie_widgets_path}" ]; then
    printf 'a newly created movie widgets JSON must not survive the automatic rollback\n' >&2
    return 1
  fi
  if [ -e "${trakt_playlist_path}" ]; then
    printf 'a newly created Trakt playlist must not survive the automatic rollback\n' >&2
    return 1
  fi

  if [ ! -f "${current_year_playlist}" ]; then
    printf 'the removed current-year movie playlist was not restored by rollback\n' >&2
    return 1
  fi
  assert_eq "${current_year_playlist_content}" "$(cat "${current_year_playlist}")" \
    "the removed current-year movie playlist is restored byte-for-byte by the rollback"

  # The obsolete playlist that the transformer deleted must be restored.
  assert_eq "${old_playlist_content}" "$(cat "${old_playlist}")" \
    "the obsolete movie playlist is restored by the rollback"
}

run_all_tests \
  test_reviewed_manifest_fixture_uses_sequential_indices_and_filenames \
  test_artifact_record_requires_four_fields \
  test_artifact_record_rejects_non_https_url \
  test_artifact_record_rejects_invalid_sha256 \
  test_artifact_record_accepts_kodi_version_punctuation \
  test_artifact_record_still_rejects_shell_metacharacters_in_version \
  test_artifact_record_rejects_version_starting_with_tilde \
  test_matching_checksum_id_and_version_pass \
  test_checksum_mismatch_fails \
  test_addon_id_mismatch_fails \
  test_addon_version_mismatch_fails \
  test_multiple_top_level_directories_fail \
  test_parent_traversal_entry_fails \
  test_absolute_path_entry_fails \
  test_duplicate_artifact_id_fails \
  test_cec_only_transaction_accepts_no_artifacts_and_rolls_back_only_cec \
  test_cec_and_addons_transaction_mutates_only_selected_surfaces \
  test_remote_scope_is_revalidated_before_mutation \
  test_cec_only_predeployment_backup_contains_no_unselected_settings \
  test_remote_deploy_stops_kodi_after_staging_validation \
  test_remote_deploy_guards_pm4k_shutdown_without_an_open_home_window \
  test_remote_deploy_traps_kodi_restart \
  test_remote_deploy_backs_up_each_replaced_path \
  test_remote_deploy_extracts_into_staging_before_replace \
  test_remote_deploy_records_manifest \
  test_remote_deploy_has_rollback_for_replaced_paths \
  test_remote_deploy_rejects_manifest_path_injection \
  test_remote_deploy_uses_addon_xml_id_not_zip_directory_name \
  test_remote_deploy_finalize_releases_rollback_material \
  test_remote_deploy_rolls_back_automatically_when_a_step_fails \
  test_remote_deploy_refuses_a_second_pending_transaction \
  test_automatic_rollback_restores_settings_written_before_the_failure \
  test_a_failed_applied_list_rebuild_never_claims_a_complete_rollback \
  test_automatic_rollback_restores_skin_managed_paths \
  test_remote_stage_upload_replaces_a_stale_bundle \
  test_rendered_remote_scripts_are_posix_clean \
  test_the_public_key_program_installs_the_key_through_the_device_login_shell \
  test_the_public_key_install_never_sends_a_quoted_program_in_the_ssh_argv \
  test_addon_selection_defaults_to_the_locked_manifest \
  test_addon_selection_filters_to_requested_ids \
  test_addon_selection_rejects_an_unlocked_id \
  test_deploy_script_embeds_the_fixture_transformer_verbatim \
  test_provisioner_never_installs_addons_through_kodi \
  test_a_malformed_transaction_pointer_never_arms_rollback \
  test_a_stale_transaction_pointer_is_reported_when_it_is_cleared \
  test_a_rollback_that_cannot_record_its_state_reports_failure \
  test_the_remote_transaction_revalidates_every_plan_field \
  test_the_remote_transaction_rejects_malformed_plan_shape \
  test_the_transaction_never_changes_the_shared_backup_directory \
  test_the_render_flag_is_an_alias_of_the_deploy_emitter \
  test_non_addon_plan_creates_an_empty_manifest_without_artifact_work \
  test_non_addon_baseline_skips_artifact_upload \
  test_the_artifact_bundle_is_staged_before_the_secret_payload \
  test_a_failed_bundle_upload_never_uploads_the_secret_payload \
  test_a_failed_deployment_discards_the_remote_secret_payload \
  test_an_unlocked_addon_is_refused_before_any_remote_call \
  test_a_default_run_survives_the_empty_addon_array_under_bash_3_2 \
  test_non_darwin_host_reaches_remote_validation \
  test_admin_key_setup_uses_portable_ssh_add_arguments \
  test_an_unreachable_target_fails_with_an_actionable_error \
  test_a_keyed_but_failing_identity_read_fails_with_an_actionable_error \
  test_real_kodi_deployment_requires_both_ratings_keys_before_device_contact \
  test_no_kodi_deployment_does_not_require_ratings_keys \
  test_the_audit_report_is_key_value_and_names_the_pending_transaction
