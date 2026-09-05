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
  sha256="$(shasum -a 256 "${zip}" | awk '{print $1}')"
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
  sha256="$(shasum -a 256 "${zip}" | awk '{print $1}')"
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
  sha256="$(shasum -a 256 "${zip}" | awk '{print $1}')"
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
  sha256="$(shasum -a 256 "${zip}" | awk '{print $1}')"
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
  sha256="$(shasum -a 256 "${zip}" | awk '{print $1}')"
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
  sha256="$(shasum -a 256 "${zip}" | awk '{print $1}')"
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
  sha256="$(shasum -a 256 "${zip}" | awk '{print $1}')"
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
  if [[ "${name}" == "deploy" ]]; then
    bash "${PROVISIONER}" --render-remote-deploy-script "${root}"
  else
    bash "${PROVISIONER}" --emit-remote-script "${name}" "${root}"
  fi
}

# Builds the storage root the transaction operates on: a Kodi tree, the
# provisioning cache, and the base64 payload the settings transformer reads.
make_fake_storage() {
  local dir="$1" root="$1/storage" line key value payload
  mkdir -p "${root}/.kodi/addons" "${root}/.kodi/userdata/addon_data" \
    "${root}/.cache/coreelec-provision"
  payload="${root}/.cache/coreelec-provision/settings-payload.conf"
  : > "${payload}"
  chmod 600 "${payload}"
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    printf '%s=%s\n' "${key}" "$(printf '%s' "${value}" | openssl base64 -A)" >> "${payload}"
  done <<'ENTRIES'
TIMEZONE=America/Los_Angeles
TIMEZONE_COUNTRY=United States
LOCALE_LANGUAGE=resource.language.en_us
LOCALE_COUNTRY=USA (12h)
KEYBOARD_LAYOUT=English QWERTY
ADDON_UPDATE_MODE=notify
ENTRIES
  printf '%s\n' "${root}"
}

# Recreates what upload_artifact_bundle leaves on the device: one fixture ZIP
# per add-on plus the deploy.tsv the transaction reads. Each spec is
# "id:version:top-level-directory", so a ZIP root that differs from the add-on
# ID (PM4K, Emby, weather.ha ship such archives) can be exercised.
stage_addon_bundle() {
  local dir="$1" root="$2"
  shift 2
  local stage="${root}/.cache/coreelec-provision/stage"
  local index=0 spec id version topdir work
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
  printf 'TIMEZONE=!!!not-base64!!!\n' \
    > "${root}/.cache/coreelec-provision/settings-payload.conf"
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
    "script.plexmod:1.14.1-beta1:plugin.video.pm4k"

  set +e
  transaction="$(run_remote_script deploy "${root}" "${bin_dir}" 2>/dev/null)"
  rc=$?
  set -e
  assert_success "${rc}" "an add-on whose ZIP root differs from its ID must deploy"

  assert_eq "new weather.ha 0.0.6.6" \
    "$(cat "${root}/.kodi/addons/weather.ha/marker.txt")" \
    "the add-on is installed under its addon.xml ID"
  assert_eq "new script.plexmod 1.14.1-beta1" \
    "$(cat "${root}/.kodi/addons/script.plexmod/marker.txt")" \
    "a differently named ZIP root is installed under its addon.xml ID"
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
  printf 'TIMEZONE=!!!not-base64!!!\n' \
    > "${root}/.cache/coreelec-provision/settings-payload.conf"
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
    printf '1\tplugin.video.youtube\t7.4.4\t1.zip\n'
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

  output="$(print_addon_selection "${manifest}" --addon plugin.video.youtube)"
  assert_eq "1" "$(printf '%s\n' "${output}" | grep -c .)" "only the requested add-on is selected"
  assert_contains "${output}" "plugin.video.youtube" "the requested add-on is kept"
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

run_all_tests \
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
  test_remote_deploy_stops_kodi_after_staging_validation \
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
  test_remote_stage_upload_replaces_a_stale_bundle \
  test_rendered_remote_scripts_are_posix_clean \
  test_addon_selection_defaults_to_the_locked_manifest \
  test_addon_selection_filters_to_requested_ids \
  test_addon_selection_rejects_an_unlocked_id \
  test_deploy_script_embeds_the_fixture_transformer_verbatim \
  test_provisioner_never_installs_addons_through_kodi
