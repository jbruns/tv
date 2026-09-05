#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"
# shellcheck source=lib/coreelec-artifacts.sh
source "${SCRIPT_DIR}/../lib/coreelec-artifacts.sh"

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

run_all_tests \
  test_artifact_record_requires_four_fields \
  test_artifact_record_rejects_non_https_url \
  test_artifact_record_rejects_invalid_sha256 \
  test_artifact_record_accepts_kodi_version_punctuation \
  test_artifact_record_still_rejects_shell_metacharacters_in_version \
  test_matching_checksum_id_and_version_pass \
  test_checksum_mismatch_fails \
  test_addon_id_mismatch_fails \
  test_addon_version_mismatch_fails \
  test_multiple_top_level_directories_fail \
  test_parent_traversal_entry_fails \
  test_absolute_path_entry_fails \
  test_duplicate_artifact_id_fails
