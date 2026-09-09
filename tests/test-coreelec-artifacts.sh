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

# macOS ships Bash 3.2 as /bin/bash, and the provisioner must run there. Tests
# that care about 3.2 semantics (an empty array expanded under `set -u`) use
# this shell explicitly rather than whichever bash happens to be first on PATH.
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

# Replaces every command the provisioner could reach the device (or the
# Keychain) with a logging stub that always fails, so a test can assert that a
# run refused before it touched anything remote. Prints the stub directory.
install_network_stubs() {
  local dir="$1" bin_dir="$1/network-bin" name
  mkdir -p "${bin_dir}"
  for name in ssh scp rsync ssh-keygen ssh-add security curl; do
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
  local dir="$1" bin_dir="$2"
  shift 2
  printf 'n\n' | PATH="${bin_dir}:${PATH}" "$(legacy_bash)" "${PROVISIONER}" \
    --config "${SCRIPT_DIR}/../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf" \
    --identity "${dir}/scratch_admin_key" \
    --report-dir "${dir}/reports" \
    "$@"
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
  local index=0 spec id version topdir work weather_settings
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

# --- Administrator public-key installation -----------------------------------

# Emulates what the device actually receives: the ssh client joins the
# remote-command argv into one string with single spaces, and sshd hands that
# whole string to the login shell as `-c`. Every quote the Mac writes into
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
  # not one well-formed key line has to be refused on the Mac, before anything
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

# macOS ships Bash 3.2, where "${array[@]}" on an empty array is an unbound
# variable under `set -u`. The default run selects every locked add-on and
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
  # deterministic regardless of the operator's shell.
  unset OMDB_API_KEY MDBLIST_API_KEY 2>/dev/null || true

  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
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
    coreelec_plex_configured coreelec_secret_names coreelec_secret_value \
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
  PLEX_SERVER_HOST=""
  PLEX_SERVER_PORT=""
  PLEX_SERVER_NAME=""
  PLEX_PROFILE_IDS=""
  ADDON_ARTIFACTS=()
  mkdir -p "${ARTIFACT_STAGE_DIR}"
  printf '1\tplugin.video.youtube\t7.4.4\t1.zip\n' > "${ARTIFACT_STAGE_DIR}/deploy.tsv"
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
          ""|*[!A-Za-z0-9_.]*)
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
  assert_contains "${body}" "deployed_addon.plugin.video.youtube=7.4.4" \
    "each deployed add-on is one key=value line"
}

# The managed skin paths added by Task 3 (skin settings, skinvariables nodes,
# and playlists) participate in the same backup/rollback transaction as
# guisettings.xml and add-on settings. This test proves that a pre-existing
# managed file is restored and a newly created managed file is removed when the
# transformer fails mid-run, using the same forced-failure pattern as the
# existing guisettings rollback test.
test_automatic_rollback_restores_skin_managed_paths() {
  local dir root bin_dir rc output home_json playlist_path old_playlist old_playlist_content

  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  root="$(make_fake_storage "${dir}")"
  bin_dir="$(install_remote_stubs "${dir}")"
  export REMOTE_CALL_LOG="${dir}/remote-calls.log"
  : > "${REMOTE_CALL_LOG}"

  # Pre-seed a managed home widgets JSON that rollback must restore.
  home_json="${root}/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-homewidgets.json"
  mkdir -p "$(dirname "${home_json}")"
  printf '[{"guid":"old-widget"}]\n' > "${home_json}"

  # The NewMovies.xsp playlist does not exist yet; rollback must remove it.
  playlist_path="${root}/.kodi/userdata/playlists/video/NewMovies.xsp"

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
  assert_eq '[{"guid":"old-widget"}]' "$(cat "${home_json}")" \
    "the pre-existing home widgets JSON is restored by the rollback"

  # A newly created managed file must be removed by the rollback.
  if [ -e "${playlist_path}" ]; then
    printf 'a newly created playlist must not survive the automatic rollback\n' >&2
    return 1
  fi

  # The obsolete playlist that the transformer deleted must be restored.
  assert_eq "${old_playlist_content}" "$(cat "${old_playlist}")" \
    "the obsolete movie playlist is restored by the rollback"
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
  test_the_transaction_never_changes_the_shared_backup_directory \
  test_the_render_flag_is_an_alias_of_the_deploy_emitter \
  test_the_artifact_bundle_is_staged_before_the_secret_payload \
  test_a_failed_bundle_upload_never_uploads_the_secret_payload \
  test_a_failed_deployment_discards_the_remote_secret_payload \
  test_an_unlocked_addon_is_refused_before_any_remote_call \
  test_a_default_run_survives_the_empty_addon_array_under_bash_3_2 \
  test_an_unreachable_target_fails_with_an_actionable_error \
  test_a_keyed_but_failing_identity_read_fails_with_an_actionable_error \
  test_real_kodi_deployment_requires_both_ratings_keys_before_device_contact \
  test_no_kodi_deployment_does_not_require_ratings_keys \
  test_the_audit_report_is_key_value_and_names_the_pending_transaction
