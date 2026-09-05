#!/bin/bash

# Local download, checksum, and ZIP-safety validation for pinned Kodi add-on
# artifacts described by `ADDON_ARTIFACT` records ("id|version|url|sha256").
#
# This library only downloads artifacts into a local destination directory,
# verifies their checksum, inspects their ZIP layout for unsafe entries, and
# confirms the declared add-on ID/version match the pinned record. It never
# extracts a ZIP to disk and never touches a remote CoreELEC device; remote
# staging and deployment are handled elsewhere.
#
# Bash 3.2 compatible: no associative arrays, no `declare -g`, no `mapfile`.

# Fall back to minimal helpers when this library is sourced standalone (e.g.
# by the test suite) without provision-coreelec.sh's versions.
if ! declare -F die >/dev/null 2>&1; then
  die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
  }
fi

if ! declare -F info >/dev/null 2>&1; then
  info() {
    printf '%s\n' "$*"
  }
fi

if ! declare -F require_command >/dev/null 2>&1; then
  require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
  }
fi

ARTIFACT_ID=""
ARTIFACT_VERSION=""
ARTIFACT_URL=""
ARTIFACT_SHA256=""

# Parses one ADDON_ARTIFACT record ("id|version|url|sha256") and sets
# ARTIFACT_ID, ARTIFACT_VERSION, ARTIFACT_URL, and ARTIFACT_SHA256. Dies on
# any structurally or syntactically invalid record.
coreelec_artifact_parse() {
  local record="$1"
  local -a fields
  IFS='|' read -r -a fields <<< "${record}"
  (( ${#fields[@]} == 4 )) || \
    die "Artifact record must have exactly four |-separated fields (id|version|url|sha256): ${record}"

  ARTIFACT_ID="${fields[0]}"
  ARTIFACT_VERSION="${fields[1]}"
  ARTIFACT_URL="${fields[2]}"
  ARTIFACT_SHA256="${fields[3]}"

  case "${ARTIFACT_ID}" in
    ""|-*|*[!A-Za-z0-9._-]*)
      die "Artifact ID contains unsupported characters: ${ARTIFACT_ID}"
      ;;
  esac
  # Kodi add-on versions follow the Debian-ish grammar used by
  # CAddonVersion: digits, letters, and the separators . _ - + ~ (for
  # example "1.16.0+matrix.1" or "0.8.30~omega"). A leading "-" or "~" is
  # refused because it is never a real published version and "~" sorts below
  # every other version, and shell metacharacters are still refused.
  case "${ARTIFACT_VERSION}" in
    ""|-*|~*|*[!A-Za-z0-9._+~-]*)
      die "Artifact version contains unsupported characters: ${ARTIFACT_VERSION}"
      ;;
  esac
  case "${ARTIFACT_URL}" in
    https://?*) ;;
    *) die "Artifact URL must be an https:// URL: ${ARTIFACT_URL}" ;;
  esac
  if (( ${#ARTIFACT_SHA256} != 64 )); then
    die "Artifact SHA-256 must be a 64 character hex digest: ${ARTIFACT_SHA256}"
  fi
  case "${ARTIFACT_SHA256}" in
    *[!0-9A-Fa-f]*)
      die "Artifact SHA-256 must be a hex digest: ${ARTIFACT_SHA256}"
      ;;
  esac
}

# Rejects unsafe ZIP entry names: empty names, absolute paths, backslashes,
# and "." or ".." path segments. Echoes the entry's top-level path segment
# (the text before its first "/", or the whole entry if it has none) so the
# caller can confirm every entry shares a single top-level directory.
_coreelec_artifact_check_entry() {
  local artifact_id="$1" entry="$2"
  local remainder segment

  [[ -n "${entry}" ]] || die "Artifact ${artifact_id} ZIP contains an empty entry name"
  case "${entry}" in
    /*) die "Artifact ${artifact_id} ZIP contains an absolute path entry: ${entry}" ;;
  esac
  case "${entry}" in
    *'\'*) die "Artifact ${artifact_id} ZIP contains a backslash in entry: ${entry}" ;;
  esac

  remainder="${entry}"
  while [[ -n "${remainder}" ]]; do
    segment="${remainder%%/*}"
    case "${segment}" in
      .|..)
        die "Artifact ${artifact_id} ZIP contains a parent/self traversal entry: ${entry}"
        ;;
    esac
    case "${remainder}" in
      */*) remainder="${remainder#*/}" ;;
      *) remainder="" ;;
    esac
  done

  printf '%s\n' "${entry%%/*}"
}

# Downloads, verifies, and inspects every configured ADDON_ARTIFACT into
# DESTINATION. On success, DESTINATION contains one ZIP per artifact named by
# its stable 1-based index ("1.zip", "2.zip", ...) and a "manifest.tsv" with
# columns: index, ID, version, filename.
coreelec_artifacts_download_and_validate() {
  local destination="$1"
  local total="${#ADDON_ARTIFACTS[@]}"
  local manifest="${destination}/manifest.tsv"
  local seen_ids=$'\n'
  local index=0
  local record zip_path zip_name computed_sha256 wanted_sha256
  local zip_listing entry top_level_dir this_top addon_xml_path
  local addon_xml declared_id declared_version

  require_command curl
  require_command shasum
  require_command unzip
  require_command xmllint

  mkdir -p "${destination}"
  : > "${manifest}"

  for record in "${ADDON_ARTIFACTS[@]}"; do
    index=$((index + 1))
    coreelec_artifact_parse "${record}"

    case "${seen_ids}" in
      *$'\n'"${ARTIFACT_ID}"$'\n'*)
        die "Duplicate artifact ID in ADDON_ARTIFACT records: ${ARTIFACT_ID}"
        ;;
    esac
    seen_ids="${seen_ids}${ARTIFACT_ID}"$'\n'

    zip_name="${index}.zip"
    zip_path="${destination}/${zip_name}"
    info "Downloading artifact ${index}/${total}: ${ARTIFACT_ID} ${ARTIFACT_VERSION}"
    curl --fail --location --proto '=https' --tlsv1.2 \
      --retry 3 --retry-all-errors --connect-timeout 15 \
      --output "${zip_path}" "${ARTIFACT_URL}" \
      || die "Failed to download artifact ${ARTIFACT_ID}: ${ARTIFACT_URL}"

    computed_sha256="$(shasum -a 256 "${zip_path}" | awk '{print $1}' | tr 'A-F' 'a-f')"
    wanted_sha256="$(printf '%s' "${ARTIFACT_SHA256}" | tr 'A-F' 'a-f')"
    if [[ "${computed_sha256}" != "${wanted_sha256}" ]]; then
      die "Checksum mismatch for artifact ${ARTIFACT_ID}: expected ${ARTIFACT_SHA256}, got ${computed_sha256}"
    fi

    zip_listing="$(unzip -Z1 "${zip_path}")" || die "Failed to list ZIP contents for artifact ${ARTIFACT_ID}"
    top_level_dir=""
    while IFS= read -r entry; do
      [[ -n "${entry}" ]] || continue
      this_top="$(_coreelec_artifact_check_entry "${ARTIFACT_ID}" "${entry}")"
      if [[ -z "${top_level_dir}" ]]; then
        top_level_dir="${this_top}"
      elif [[ "${this_top}" != "${top_level_dir}" ]]; then
        die "Artifact ${ARTIFACT_ID} ZIP has more than one top-level directory: ${top_level_dir}, ${this_top}"
      fi
    done <<< "${zip_listing}"
    [[ -n "${top_level_dir}" ]] || die "Artifact ${ARTIFACT_ID} ZIP is empty"

    addon_xml_path="${top_level_dir}/addon.xml"
    addon_xml="$(unzip -p "${zip_path}" "${addon_xml_path}" 2>/dev/null)" \
      || die "Artifact ${ARTIFACT_ID} ZIP is missing ${addon_xml_path}"

    declared_id="$(printf '%s' "${addon_xml}" | xmllint --xpath 'string(/addon/@id)' - 2>/dev/null)"
    declared_version="$(printf '%s' "${addon_xml}" | xmllint --xpath 'string(/addon/@version)' - 2>/dev/null)"

    [[ "${declared_id}" == "${ARTIFACT_ID}" ]] \
      || die "Artifact ID mismatch for ${ARTIFACT_ID}: addon.xml declares '${declared_id}'"
    [[ "${declared_version}" == "${ARTIFACT_VERSION}" ]] \
      || die "Artifact version mismatch for ${ARTIFACT_ID}: expected ${ARTIFACT_VERSION}, addon.xml declares '${declared_version}'"

    printf '%s\t%s\t%s\t%s\n' "${index}" "${ARTIFACT_ID}" "${ARTIFACT_VERSION}" "${zip_name}" >> "${manifest}"
    info "Validated artifact ${ARTIFACT_ID} ${ARTIFACT_VERSION}"
  done

  info "Validated ${index} artifact(s) in ${destination}"
}
