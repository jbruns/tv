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

test_python_owned_id_in_a_shell_write_set_is_rejected_before_device_contact() {
  local scratch ledger output status
  scratch="$(make_scratch_dir)"
  ledger="${scratch}/ledger.json"
  trap 'rm -rf -- "${scratch}"' RETURN
  # SKIN-024 stands in for any address a future slice hands to the Reconciler
  # before the shell stops writing it. SKIN-025 cannot play this part any more:
  # it has completed the handoff and left the shell write set entirely.
  python3 - "${ROOT}/inventory/ownership-ledger.json" "${ledger}" <<'PY'
import json
import sys

source, destination = sys.argv[1:]
document = json.load(open(source, encoding="utf-8"))
row = next(row for row in document["rows"] if row["id"] == "SKIN-024")
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
  assert_contains "${output}" "blocked_inventory_ids=SKIN-024"
}

test_new_shows_has_left_the_shell_write_set() {
  local output
  # The handoff is complete, so the Recovery Baseline still runs; it simply no
  # longer reaches the address. A regression here means either the shell writes
  # NewShows.xsp again, or skin runs have started failing closed.
  output="$(python3 "${CHECKER}" \
    --entry-point provision-coreelec.sh \
    --operation deploy \
    --scope skin \
    --addon script.plexmod \
    --no-harden-ssh)"

  assert_contains "${output}" "permission=allowed"
  assert_contains "${output}" "SKIN-024"
  assert_contains "${output}" "SKIN-026"
  assert_not_contains "${output}" "SKIN-025"
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

test_interactive_addon_unknown_is_denied_before_device_contact() {
  local scratch env_file ssh_log output status bin_dir
  scratch="$(make_scratch_dir)"
  env_file="${scratch}/env"
  ssh_log="${scratch}/ssh.log"
  bin_dir="${scratch}/bin"
  trap 'rm -rf -- "${scratch}"' RETURN
  mkdir "${bin_dir}"
  printf 'KODI_WEB_PASSWORD=offline-test-password\n' > "${env_file}"
  cat > "${bin_dir}/ssh" <<'SH'
#!/bin/sh
printf 'contacted\n' >> "${SSH_CONTACT_LOG:?}"
exit 99
SH
  chmod +x "${bin_dir}/ssh"

  set +e
  output="$(PATH="${bin_dir}:${PATH}" SSH_CONTACT_LOG="${ssh_log}" \
    UGOOS_ENV_FILE="${env_file}" \
    bash "${ROOT}/configure-coreelec-addons.sh" \
      --target offline.invalid --addon script.plexmod --interactive 2>&1)"
  status=$?
  set -e

  assert_failure "${status}"
  assert_contains "${output}" "permission denied before Device contact"
  [[ ! -e "${ssh_log}" ]]
}

run_all_tests \
  test_addons_scope_reports_indirect_skin_effect_without_new_shows \
  test_python_owned_id_in_a_shell_write_set_is_rejected_before_device_contact \
  test_new_shows_has_left_the_shell_write_set \
  test_dynamic_recovery_scope_fails_closed \
  test_provision_entry_point_uses_the_audited_effective_write_set \
  test_interactive_addon_unknown_is_denied_before_device_contact
