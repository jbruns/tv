#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/test-helper.sh
source "${SCRIPT_DIR}/test-helper.sh"

ENV_LIB="${SCRIPT_DIR}/../lib/coreelec-env.sh"
REPO_ROOT="${SCRIPT_DIR}/.."
# shellcheck source=lib/coreelec-env.sh
source "${ENV_LIB}"

copy_ugoos_scripts() {
  local destination="$1"
  mkdir -p "${destination}"
  cp -R "${REPO_ROOT}/lib" "${REPO_ROOT}/config" "${destination}/"
  cp \
    "${REPO_ROOT}/provision-coreelec.sh" \
    "${REPO_ROOT}/configure-coreelec-addons.sh" \
    "${REPO_ROOT}/configure-kodi-lifecycle.sh" \
    "${destination}/"
}

test_env_loader_fails_with_setup_instructions_when_file_is_missing() {
  local dir missing output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  missing="${dir}/.env"

  set +e
  output="$({
    coreelec_env_load "${missing}"
  } 2>&1)"
  rc=$?
  set -e

  assert_failure "${rc}" "a missing shared environment file must stop the operation" || return 1
  assert_contains "${output}" ".env.example" "the error explains how to create the environment file"
}

test_env_loader_sources_and_exports_shared_values() {
  local dir env_file output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  env_file="${dir}/.env"
  cat > "${env_file}" <<'ENV'
KODI_WEB_PASSWORD='value with spaces # and symbols'
ENV

  output="$(
    coreelec_env_load "${env_file}"
    sh -c 'printf "%s" "${KODI_WEB_PASSWORD}"'
  )"

  assert_eq "value with spaces # and symbols" "${output}" \
    "the shared environment value is sourced and exported to child tools"
}

test_env_loader_preserves_existing_allexport_mode() {
  local dir env_file output
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  env_file="${dir}/.env"
  printf "KODI_WEB_PASSWORD='test-password'\n" > "${env_file}"

  set -a
  coreelec_env_load "${env_file}"
  case "$-" in
    *a*) output="enabled" ;;
    *) output="disabled" ;;
  esac

  assert_eq "enabled" "${output}" "loading .env preserves the caller's allexport mode"
}

test_env_loader_does_not_override_non_secret_script_state() {
  local dir env_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  env_file="${dir}/.env"
  cat > "${env_file}" <<'ENV'
TARGET=unexpected-target
DRY_RUN=1
KODI_WEB_PASSWORD='test-password'
ENV
  TARGET="cli-target"
  DRY_RUN="0"

  coreelec_env_load "${env_file}"

  assert_eq "cli-target" "${TARGET}" ".env cannot override the CLI target" || return 1
  assert_eq "0" "${DRY_RUN}" ".env cannot change operation mode"
}

test_env_loader_does_not_fall_back_to_ambient_secrets() {
  local dir env_file
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  env_file="${dir}/.env"
  : > "${env_file}"
  KODI_WEB_PASSWORD="ambient-password"

  coreelec_env_load "${env_file}"

  assert_eq "" "${KODI_WEB_PASSWORD}" "the shared file is the authoritative secret source"
}

test_all_ugoos_entry_points_require_the_shared_environment_file() {
  local dir script output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  copy_ugoos_scripts "${dir}"

  for script in \
    provision-coreelec.sh \
    configure-coreelec-addons.sh \
    configure-kodi-lifecycle.sh; do
    set +e
    output="$(cd "${dir}" && bash "./${script}" 2>&1)"
    rc=$?
    set -e
    assert_failure "${rc}" "${script} must refuse to run without .env" || return 1
    assert_contains "${output}" ".env.example" \
      "${script} explains how to create the shared environment file" || return 1
  done
}

test_addon_cli_loads_the_repository_environment_file() {
  local dir output rc
  dir="$(make_scratch_dir)"
  trap 'rm -rf -- "${dir}"' RETURN
  copy_ugoos_scripts "${dir}"
  cat > "${dir}/.env" <<'ENV'
KODI_WEB_PASSWORD='shared-kodi-password'
ENV

  set +e
  output="$(
    cd "${dir}"
    bash ./configure-coreelec-addons.sh \
      --target coreelec-test \
      --dry-run \
      --report-dir "${dir}/reports"
  2>&1)"
  rc=$?
  set -e

  assert_success "${rc}" "the add-on CLI loads KODI_WEB_PASSWORD from .env" || return 1
  assert_contains "${output}" "Report:" "the operation reaches its normal result"
}

run_all_tests \
  test_env_loader_fails_with_setup_instructions_when_file_is_missing \
  test_env_loader_sources_and_exports_shared_values \
  test_env_loader_preserves_existing_allexport_mode \
  test_env_loader_does_not_override_non_secret_script_state \
  test_env_loader_does_not_fall_back_to_ambient_secrets \
  test_all_ugoos_entry_points_require_the_shared_environment_file \
  test_addon_cli_loads_the_repository_environment_file
