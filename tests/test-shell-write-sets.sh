#!/bin/bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/test-helper.sh"

ROOT="${SCRIPT_DIR}/.."
CHECKER="${ROOT}/scripts/check_shell_permissions.py"

test_addons_scope_reports_indirect_skin_effect_without_new_shows() {
  local output
  output="$(python3 "${CHECKER}" \
    --entry-point provision-coreelec.sh \
    --operation deploy \
    --scope addons \
    --addon script.plexmod \
    --no-harden-ssh)"

  assert_contains "${output}" "permission=allowed"
  assert_contains "${output}" "ART-007"
  assert_contains "${output}" "SKIN-017"
  assert_contains "${output}" "SKIN-018"
  assert_not_contains "${output}" "SKIN-025"
  assert_contains "${output}" "effect_ids=EFFECT-001,EFFECT-002,EFFECT-004"
}

test_skin_handoff_is_rejected_before_device_contact() {
  local scratch ledger output status
  scratch="$(make_scratch_dir)"
  ledger="${scratch}/ledger.json"
  trap 'rm -rf -- "${scratch}"' RETURN
  python3 - "${ROOT}/inventory/ownership-ledger.json" "${ledger}" <<'PY'
import json
import sys

source, destination = sys.argv[1:]
document = json.load(open(source, encoding="utf-8"))
row = next(row for row in document["rows"] if row["id"] == "SKIN-025")
row["current_owner_or_executor"] = "python"
with open(destination, "w", encoding="utf-8") as handle:
    json.dump(document, handle)
PY

  set +e
  output="$(python3 "${CHECKER}" \
    --ledger "${ledger}" \
    --entry-point provision-coreelec.sh \
    --operation deploy \
    --scope skin \
    --addon script.plexmod \
    --no-harden-ssh 2>&1)"
  status=$?
  set -e

  assert_failure "${status}"
  assert_contains "${output}" "permission=blocked"
  assert_contains "${output}" "blocked_inventory_ids=SKIN-025"
}

test_dynamic_recovery_scope_fails_closed() {
  local output status
  set +e
  output="$(python3 "${CHECKER}" \
    --entry-point provision-coreelec.sh \
    --operation rollback 2>&1)"
  status=$?
  set -e

  assert_failure "${status}"
  assert_contains "${output}" "permission=blocked"
  assert_contains "${output}" "unknowns=provision-rollback-transaction-write-set"
}

test_provision_entry_point_uses_the_audited_effective_write_set() {
  local scratch env_file output
  scratch="$(make_scratch_dir)"
  env_file="${scratch}/empty.env"
  trap 'rm -rf -- "${scratch}"' RETURN
  printf 'KODI_WEB_PASSWORD=offline-test-password\n' > "${env_file}"

  output="$(UGOOS_ENV_FILE="${env_file}" bash "${ROOT}/provision-coreelec.sh" \
    --target offline.invalid \
    --component addons \
    --addon script.plexmod \
    --no-harden \
    --print-shell-write-set)"

  assert_contains "${output}" "permission=allowed"
  assert_contains "${output}" "ART-007"
  assert_contains "${output}" "SKIN-017"
  assert_not_contains "${output}" "SKIN-025"
}

run_all_tests \
  test_addons_scope_reports_indirect_skin_effect_without_new_shows \
  test_skin_handoff_is_rejected_before_device_contact \
  test_dynamic_recovery_scope_fails_closed \
  test_provision_entry_point_uses_the_audited_effective_write_set
