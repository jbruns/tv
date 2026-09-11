# Ugoos Network Keep-Alive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every managed Ugoos AM6B+ network-reachable while Home Assistant stops Kodi by default when its paired Sony display is off and powers off the Sony after verified Kodi inactivity.

**Architecture:** Provision Kodi's CEC TV-off action as Ignore, then expose only start, stop, and status for `kodi.service` through a forced-command Home Assistant SSH key. A versioned Home Assistant package uses the Sony Bravia entity as display authority, Kodi JSON-RPC as the input-idle authority, and a serialized reconciler as the sole desired-state owner.

**Tech Stack:** Bash 3.2-compatible shell, OpenSSH forced commands, CoreELEC 21.3 systemd, Kodi 21 Omega peripheral XML and JSON-RPC, Home Assistant packages/Jinja automations, Sony Bravia and Kodi integrations, pfSense Plus 26.07.

**Spec:** `docs/superpowers/specs/2026-09-11-ugoos-network-keep-alive-design.md`

## Global Constraints

- Target Ugoos AM6B+ devices running CoreELEC `21.3` Amlogic-ng and Kodi 21 Omega.
- Keep CoreELEC, wired Ethernet, and SSH awake continuously.
- Set Kodi **When the TV is switched off** to **Ignore**; CEC must never suspend or shut down CoreELEC.
- Enable stopping Kodi while the display is off for every managed Ugoos by default; permit an explicit per-device opt-out.
- Use the paired Sony Bravia Home Assistant entity as the display power authority.
- Stop Kodi only after a fresh, continuous 60-second definite Sony `off` interval.
- Start Kodi immediately for any definite non-off, `unknown`, or `unavailable` Sony state.
- Default idle timeout is 30 minutes; playing and paused media inhibit idle power-off.
- Prove idle from both continuous Home Assistant Kodi `idle` state and Kodi
  `System.IdleTime(idle_timeout_minutes * 60)`; the default query is
  `System.IdleTime(1800)`.
- Poll Kodi idle evidence every 15 seconds and expire it after two missed intervals.
- Idle powers off the Sony first; the normal 60-second Sony-off path then stops Kodi.
- **Keep Kodi running** suppresses Kodi stop but does not suppress idle-driven Sony power-off.
- Restricted SSH calls have a 15-second deadline; Sony off confirmation has a 30-second deadline; Kodi JSON-RPC readiness after start has a 90-second deadline.
- The Home Assistant key grants no shell, PTY, forwarding, file transfer, user RC execution, or non-Kodi service control.
- Never commit private keys, credentials, actual secret values, or generated audit reports.
- Do not add MQTT, a privileged HTTP daemon, a Bluetooth monitor, automatic pfSense mutation, suspend, shutdown, or WoL automation.
- Preserve unrelated worktree changes; stage and commit only files named by each task.

## File Structure

- Modify `provision-coreelec.sh`: add the fixed CEC Ignore payload, transactional peripheral XML transform, backup coverage, remote observation, and verification.
- Modify `tests/test-coreelec-settings.sh`: exercise CEC XML creation/update, preservation, idempotency, missing/ambiguous adapters, and backup coverage.
- Modify `tests/test-coreelec-report.sh`: verify CEC observation comparison, reporting, and rollback on mismatch.
- Create `lib/coreelec-ssh.sh`: shared administrator SSH option construction plus separate single-command and streamed-program helpers.
- Modify `provision-coreelec.sh`: consume the shared public-key normalizer after Task 1 instead of retaining a duplicate parser.
- Modify `lib/coreelec-addon-workflows.sh`: delegate its existing batch SSH transport to `lib/coreelec-ssh.sh` without changing behavior.
- Modify `configure-coreelec-addons.sh`: source the shared SSH transport before the add-on workflow library.
- Modify `tests/test-coreelec-addon-workflows.sh`: prove the SSH extraction preserves argv, stdin, authentication, and failure behavior.
- Create `lib/coreelec-lifecycle.sh`: render and validate the forced-command wrapper/key entry and provide pure status/transaction helpers.
- Create `configure-kodi-lifecycle.sh`: lifecycle gateway CLI, target checks, atomic deployment, restricted-key verification, rollback, and report.
- Create `tests/test-coreelec-lifecycle.sh`: fixture-driven wrapper, authorization, deployment, verification, rollback, and redaction tests.
- Create `home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml`: concrete theater helpers, sensors, shell commands, scripts, and automations.
- Create `home-assistant/ssh/ugoos-kodi-lifecycle.conf.example`: persistent key and known-host configuration used by the package.
- Create `tests/test-home-assistant-ugoos-package.sh`: static package contract and policy-precedence fixture tests without a new YAML dependency.
- Create `docs/home-assistant/ugoos-kodi-lifecycle.md`: package installation, entity naming, key placement, validation, operation, and recovery.
- Modify `config/README.md`: document controller inputs, package layout, defaults, and per-device opt-out.
- Modify `docs/runbook.md`: insert lifecycle deployment between baseline provisioning and room playback configuration.
- Modify `docs/devices/ugoos-am6b-plus/coreelec-21.3.md`: make CEC Ignore and always-awake behavior baseline requirements; move suspend/WoL to optional experiments.
- Modify `docs/network/pfsense-plus-26.07-onboarding.md`: document the HA-host-to-managed-Ugoos TCP/22 rule and verification.
- Modify `docs/network/wake-on-lan.md`: explicitly separate experimental WoL from production lifecycle control.
- Modify `rooms/theater/devices/sony-xr-65a90j.md`: retain Sony device auto power-off disabled and document HA ownership.
- Modify `rooms/theater/devices/ugoos-am6b-plus.md`: add theater package deployment and acceptance record fields.
- Modify `rooms/theater/README.md`: add lifecycle and idle acceptance checks.
- Modify `README.md`: link the Home Assistant lifecycle guide.

---

### Task 1: Transactional Kodi CEC Ignore Baseline

**Files:**
- Modify: `provision-coreelec.sh`
- Modify: `tests/test-coreelec-settings.sh`
- Modify: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: the existing base64 settings payload, fixture transformer, remote backup transaction, observation file, comparator, and audit renderer in `provision-coreelec.sh`.
- Produces: payload key `CEC_TV_OFF_ACTION=36028`, observation `cec.tv_off_action=36028`, and fatal verification when the observed action differs.
- Produces no user-configurable CEC action; `36028` is the fixed Kodi localization value for Ignore.

- [ ] **Step 1: Write failing CEC transformer tests**

Extend `write_base_payload` in `tests/test-coreelec-settings.sh` with:

```bash
CEC_TV_OFF_ACTION=36028
```

Add fixture helpers and tests with these exact contracts:

```bash
cec_settings_path() {
  printf '%s/.kodi/userdata/peripheral_data/cec_CEC_Adapter.xml' "$1"
}

write_cec_settings() {
  local root="$1" value="$2"
  mkdir -p "${root}/.kodi/userdata/peripheral_data"
  printf '<settings><setting id="standby_pc_on_tv_standby">%s</setting></settings>\n' \
    "${value}" > "$(cec_settings_path "${root}")"
}

test_cec_tv_off_action_is_changed_to_ignore
test_cec_transform_preserves_unmanaged_peripheral_settings
test_duplicate_cec_tv_off_actions_are_collapsed
test_second_cec_transform_is_byte_identical
test_missing_cec_adapter_file_fails_loudly
test_multiple_cec_adapter_files_fail_loudly
test_cec_settings_file_mode_is_private
test_remote_backup_includes_peripheral_data
```

The first test must seed `13011` (Suspend), run `--transform-fixture`, and
assert `standby_pc_on_tv_standby` equals `36028`. The preservation test must
seed an unrelated `activate_source` setting and assert it remains unchanged.
The missing and multiple file tests must assert nonzero status and an error
that names `peripheral_data`.

- [ ] **Step 2: Run the settings tests to verify they fail**

Run:

```bash
bash tests/test-coreelec-settings.sh
```

Expected: FAIL because the payload transformer does not accept
`CEC_TV_OFF_ACTION`, does not update a CEC peripheral file, and does not back
up `peripheral_data`.

- [ ] **Step 3: Add the CEC peripheral transform and backup**

In the settings payload built by `provision-coreelec.sh`, always append:

```bash
append_settings_payload_entry "CEC_TV_OFF_ACTION" "36028"
```

Extend the remote Python transformer with one focused function:

```python
def set_cec_tv_off_action(storage_root, value):
    peripheral_dir = os.path.join(
        storage_root, ".kodi", "userdata", "peripheral_data"
    )
    paths = sorted(glob.glob(os.path.join(peripheral_dir, "*CEC*.xml")))
    if len(paths) != 1:
        fail("expected exactly one Kodi CEC peripheral settings file in %s; found %d"
             % (peripheral_dir, len(paths)))
    tree = ET.parse(paths[0])
    _set_xml_setting(
        tree.getroot(), "standby_pc_on_tv_standby", value, flat=False
    )
    write_xml_atomic(paths[0], tree)
```

Use the transformer's existing atomic XML writer, duplicate collapse, mode
normalization, and error path. Reject a value other than `36028`. Extend the
remote backup program with:

```sh
for cec_path in "${storage_root}"/.kodi/userdata/peripheral_data/*CEC*.xml; do
  [ -f "${cec_path}" ] || continue
  copy_one "${cec_path}"
done
```

This backs up every candidate CEC XML before the transformer enforces the
exactly-one rule and preserves unrelated peripheral files without copying an
unbounded directory tree.

- [ ] **Step 4: Run the settings tests to verify they pass**

Run:

```bash
bash tests/test-coreelec-settings.sh
bash -n provision-coreelec.sh tests/test-coreelec-settings.sh
```

Expected: all settings tests PASS and both shell files pass syntax checking.

- [ ] **Step 5: Write failing observation, report, and rollback tests**

In `tests/test-coreelec-report.sh`, add
`cec.tv_off_action=36028` to the passing observation fixture and add:

```bash
test_remote_probe_reports_cec_ignore
test_cec_ignore_mismatch_fails_verification
test_cec_ignore_mismatch_triggers_rollback
test_audit_report_records_cec_ignore_without_adapter_filename
```

The mismatch fixture must report `cec.tv_off_action=13011`. Assert that the
comparator names the CEC action, the conclusion fixture invokes rollback
rather than finalize, and the report contains:

```text
cec.tv_off_action.expected=36028
cec.tv_off_action.observed=13011
cec.tv_off_action.status=mismatch
```

- [ ] **Step 6: Run the report tests to verify they fail**

Run:

```bash
bash tests/test-coreelec-report.sh
```

Expected: FAIL because the remote probe, comparator, and report do not know
the CEC observation.

- [ ] **Step 7: Implement CEC observation and fatal verification**

Extend the remote observation script to:

1. locate exactly one `*CEC*.xml` below
   `/storage/.kodi/userdata/peripheral_data`;
2. parse `standby_pc_on_tv_standby` without reporting the dynamic filename;
3. print `cec.tv_off_action=${value}`; and
4. fail observation if the file or setting is missing or ambiguous.

Extend comparison and reporting with fixed expected value `36028`. Treat
missing, malformed, or mismatched CEC action as a fatal baseline verification
failure so the existing conclusion path rolls the transaction back.

- [ ] **Step 8: Run focused provisioning tests**

Run:

```bash
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-report.sh
bash tests/test-coreelec-config.sh
bash -n provision-coreelec.sh tests/test-coreelec-settings.sh tests/test-coreelec-report.sh
```

Expected: all commands PASS.

- [ ] **Step 9: Commit the CEC baseline**

```bash
git add provision-coreelec.sh tests/test-coreelec-settings.sh tests/test-coreelec-report.sh
git commit -m "feat: keep CoreELEC awake after TV standby"
```

---

### Task 2: Restricted Kodi Lifecycle Command Contract

**Files:**
- Create: `lib/coreelec-ssh.sh`
- Modify: `provision-coreelec.sh`
- Modify: `lib/coreelec-addon-workflows.sh`
- Modify: `configure-coreelec-addons.sh`
- Create: `lib/coreelec-lifecycle.sh`
- Create: `tests/test-coreelec-lifecycle.sh`
- Modify: `tests/test-coreelec-addon-workflows.sh`

**Interfaces:**
- Consumes: global `TARGET`, `SSH_PORT`, and optional `IDENTITY_FILE`.
- Produces: `coreelec_public_key_line FILE`, `coreelec_ssh_command COMMAND` with the current post-deployment single-command behavior, and `coreelec_ssh_batch SCRIPT` for streamed lifecycle programs.
- Produces: `coreelec_lifecycle_render_wrapper SYSTEMCTL_PATH`, `coreelec_lifecycle_key_entry PUBLIC_KEY`, and `coreelec_lifecycle_validate_public_key FILE`.
- The rendered wrapper consumes only `SSH_ORIGINAL_COMMAND` values `start`, `stop`, or `status`.

- [ ] **Step 1: Write failing shared SSH extraction tests**

In `tests/test-coreelec-addon-workflows.sh`, add:

```bash
test_shared_ssh_command_preserves_one_remote_argv_word
test_shared_ssh_batch_streams_the_remote_program_on_stdin
test_shared_ssh_helpers_use_only_the_selected_identity
test_shared_ssh_helpers_disable_password_and_interactive_auth
test_shared_ssh_helpers_preserve_remote_failure_status
```

Stub `ssh` using the test's existing fixture-bin pattern. Assert that the
helper passes:

```text
-o BatchMode=yes
-o StrictHostKeyChecking=accept-new
-o IdentitiesOnly=yes
-o PreferredAuthentications=publickey
-o PasswordAuthentication=no
-o KbdInteractiveAuthentication=no
```

Assert that `coreelec_ssh_command` ends in exactly
`root@ugoos-theater '<remote-command>'`, matching the current add-on
transport, while `coreelec_ssh_batch` ends in
`root@ugoos-theater sh -s` and carries the program only on stdin.

- [ ] **Step 2: Run the add-on workflow tests to verify they fail**

Run:

```bash
bash tests/test-coreelec-addon-workflows.sh
```

Expected: FAIL because `lib/coreelec-ssh.sh` and `coreelec_ssh_batch` do not
exist.

- [ ] **Step 3: Extract the shared batch SSH helper**

Create `lib/coreelec-ssh.sh` with one option builder and these two public
helpers:

```bash
coreelec_ssh_command() {
  local remote_command="$1"
  local identity_file="${IDENTITY_FILE:-${HOME}/.ssh/coreelec_admin_ed25519}"
  [[ "$#" -eq 1 ]] || die "coreelec_ssh_command requires one remote command"
  ssh \
    -p "${SSH_PORT}" \
    -o BatchMode=yes \
    -o ConnectTimeout=12 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    -i "${identity_file}" \
    -o IdentitiesOnly=yes \
    -o PreferredAuthentications=publickey \
    -o PasswordAuthentication=no \
    -o KbdInteractiveAuthentication=no \
    "root@${TARGET}" \
    "${remote_command}"
}

coreelec_ssh_batch() {
  local remote_script="$1"
  [[ "$#" -eq 1 ]] || die "coreelec_ssh_batch requires one remote script"
  printf '%s\n' "${remote_script}" |
    coreelec_ssh_command 'sh -s'
}
```

Factor the repeated validation and SSH options into a private helper so both
public functions validate `TARGET`, `SSH_PORT`, and identity consistently
without duplicating the option list. Keep `die` owned by the calling CLI,
matching the existing library pattern. Source this file before
`lib/coreelec-addon-workflows.sh`, replace
`coreelec_postdeploy_ssh_batch` calls with `coreelec_ssh_command`, and remove
the duplicate transport implementation. Do not change remote command quoting,
stdin, JSON-RPC, or failure behavior.

Move the existing `coreelec_public_key_line` implementation unchanged from
`provision-coreelec.sh` into `lib/coreelec-ssh.sh`, source the library from
the provisioner, and keep all existing provisioning key tests passing. The
lifecycle library must call this shared normalizer rather than copying its
regular expression.

- [ ] **Step 4: Run the add-on workflow tests to verify they pass**

Run:

```bash
bash tests/test-coreelec-addon-workflows.sh
bash -n configure-coreelec-addons.sh lib/coreelec-ssh.sh lib/coreelec-addon-workflows.sh
```

Expected: all tests PASS with unchanged add-on behavior.

- [ ] **Step 5: Write failing lifecycle wrapper tests**

Create `tests/test-coreelec-lifecycle.sh`, source `tests/test-helper.sh` and
`lib/coreelec-lifecycle.sh`, and add:

```bash
test_public_key_validation_accepts_one_ed25519_key
test_public_key_validation_rejects_multiple_or_malformed_keys
test_key_entry_uses_restrict_and_forced_command
test_key_entry_fallback_disables_forwarding_pty_x11_and_user_rc
test_wrapper_start_is_idempotent
test_wrapper_stop_is_idempotent
test_wrapper_status_maps_active_inactive_and_failed
test_wrapper_rejects_transitional_and_unknown_states
test_wrapper_rejects_empty_unknown_compound_and_extra_argument_commands
test_wrapper_never_accepts_a_caller_supplied_unit
test_wrapper_never_uses_eval
```

Render the wrapper with an absolute fixture `systemctl` path. The fixture
must record every argv word separately and return configured values for
`is-active` and `is-failed`. Exercise commands by setting, for example:

```bash
SSH_ORIGINAL_COMMAND=start sh "${wrapper}"
SSH_ORIGINAL_COMMAND='start kodi.service' sh "${wrapper}"
SSH_ORIGINAL_COMMAND='start; id' sh "${wrapper}"
```

Assert only the first succeeds and every successful systemd call names
exactly `kodi.service`.

- [ ] **Step 6: Run lifecycle tests to verify they fail**

Run:

```bash
bash tests/test-coreelec-lifecycle.sh
```

Expected: FAIL because `lib/coreelec-lifecycle.sh` does not exist.

- [ ] **Step 7: Implement wrapper rendering and key authorization**

Create `lib/coreelec-lifecycle.sh`. Call the shared
`coreelec_public_key_line` from `lib/coreelec-ssh.sh`. Produce a normalized
single public-key line and a stable marker comment:

```text
homeassistant-ugoos-kodi-lifecycle
```

Render a wrapper equivalent to:

```sh
#!/bin/sh
set -eu

SYSTEMCTL="/usr/bin/systemctl"
UNIT="kodi.service"

status() {
  state="$("${SYSTEMCTL}" is-active "${UNIT}" 2>/dev/null || true)"
  case "${state}" in
    active) printf 'running\n' ;;
    inactive)
      if "${SYSTEMCTL}" is-failed --quiet "${UNIT}"; then
        printf 'failed\n'
      else
        printf 'stopped\n'
      fi
      ;;
    failed) printf 'failed\n' ;;
    *)
      printf 'Unsupported kodi.service state: %s\n' "${state}" >&2
      return 3
      ;;
  esac
}

case "${SSH_ORIGINAL_COMMAND:-}" in
  start)
    "${SYSTEMCTL}" is-active --quiet "${UNIT}" || "${SYSTEMCTL}" start "${UNIT}"
    status
    ;;
  stop)
    "${SYSTEMCTL}" is-active --quiet "${UNIT}" && "${SYSTEMCTL}" stop "${UNIT}"
    status
    ;;
  status) status ;;
  *)
    printf 'Allowed commands: start, stop, status\n' >&2
    exit 2
    ;;
esac
```

Correct the stopped branch so `systemctl is-failed --quiet` is checked before
printing `stopped`. The renderer takes the absolute systemctl path solely so
tests can supply a fixture; production always passes `/usr/bin/systemctl`.

Render the preferred key entry:

```text
restrict,command="/storage/.config/kodi-lifecycle" ${normalized_public_key}
```

and an explicit fallback with
`no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc,no-X11-forwarding`.
Never add `permitopen`, `environment`, or an unrestricted command.

- [ ] **Step 8: Run lifecycle and regression tests**

Run:

```bash
bash tests/test-coreelec-lifecycle.sh
bash tests/test-coreelec-addon-workflows.sh
bash -n provision-coreelec.sh lib/coreelec-ssh.sh lib/coreelec-lifecycle.sh \
  configure-coreelec-addons.sh
```

Expected: all commands PASS.

- [ ] **Step 9: Commit the lifecycle command contract**

```bash
git add provision-coreelec.sh lib/coreelec-ssh.sh lib/coreelec-lifecycle.sh \
  lib/coreelec-addon-workflows.sh configure-coreelec-addons.sh \
  tests/test-coreelec-lifecycle.sh tests/test-coreelec-addon-workflows.sh
git commit -m "feat: define restricted Kodi lifecycle commands"
```

---

### Task 3: Transactional Lifecycle Gateway Deployment

**Files:**
- Create: `configure-kodi-lifecycle.sh`
- Modify: `lib/coreelec-lifecycle.sh`
- Modify: `tests/test-coreelec-lifecycle.sh`

**Interfaces:**
- Consumes: `coreelec_ssh_batch`, wrapper/key renderers from Task 2, the administrator identity, a controller public key, and its matching controller private identity.
- Produces CLI:
  `configure-kodi-lifecycle.sh --target HOST --controller-public-key FILE --controller-identity FILE [--identity-file FILE] [--ssh-port PORT] [--dry-run] [--report-dir DIR]`.
- Produces target files `/storage/.config/kodi-lifecycle` and one uniquely marked `/storage/.ssh/authorized_keys` entry.
- Produces report fields `deployment_state`, `wrapper_status`, `restricted_start`, `restricted_stop`, `restored_state`, and key-presence booleans; never key bytes.

- [ ] **Step 1: Write failing CLI and transaction tests**

Extend `tests/test-coreelec-lifecycle.sh` with:

```bash
test_help_documents_both_controller_key_inputs_and_recovery
test_dry_run_makes_no_ssh_calls
test_target_and_key_arguments_are_required
test_platform_check_requires_coreelec_21_3_amlogic_ng
test_deploy_creates_private_directories_and_atomic_candidates
test_deploy_preserves_unrelated_authorized_keys
test_rerun_replaces_only_the_marked_controller_key
test_deploy_prefers_restrict_when_sshd_supports_it
test_deploy_uses_explicit_restrictions_when_restrict_is_unsupported
test_restricted_identity_can_run_status_start_and_stop
test_restricted_identity_cannot_run_an_arbitrary_command
test_verification_restores_initial_running_state
test_verification_restores_initial_stopped_state
test_failed_verification_rolls_back_wrapper_and_authorized_keys
test_failed_rollback_retains_recovery_material_and_instructions
test_report_never_contains_public_or_private_key_material
```

Stub administrator SSH separately from controller SSH. Require controller
calls to use:

```text
-o BatchMode=yes
-o ConnectTimeout=12
-o ConnectionAttempts=1
-o StrictHostKeyChecking=yes
-o UserKnownHostsFile=<explicit-file>
-o IdentitiesOnly=yes
```

and a 15-second outer deadline where the local platform provides `timeout`.
On macOS, implement the deadline with the script's existing portable
background/wait helper rather than depending on GNU `timeout`.

- [ ] **Step 2: Run lifecycle tests to verify they fail**

Run:

```bash
bash tests/test-coreelec-lifecycle.sh
```

Expected: FAIL because the deployment CLI and transaction functions do not
exist.

- [ ] **Step 3: Implement CLI parsing and local validation**

Create `configure-kodi-lifecycle.sh` with the repository's standard
`set -Eeuo pipefail`, timestamped `info`/`warn`/`die`, strict host/port/path
validation, `--help`, `--version`, and `--dry-run`.

Defaults:

```bash
SSH_PORT=22
IDENTITY_FILE="${HOME}/.ssh/coreelec_admin_ed25519"
REPORT_DIR="${PWD}/coreelec-lifecycle-reports"
KNOWN_HOSTS_FILE="${HOME}/.ssh/known_hosts"
```

Require both controller files. Validate that:

```bash
ssh-keygen -y -f "${CONTROLLER_IDENTITY}"
```

normalizes to the same key type/blob as
`CONTROLLER_PUBLIC_KEY`. Reject mismatch before contacting the target. Dry
run renders and validates the wrapper/key entry and writes a redacted plan
without invoking SSH.

- [ ] **Step 4: Implement remote staging, backup, and atomic install**

Use a dedicated namespace:

```text
/storage/backup/kodi-lifecycle/<UTC timestamp>/
/storage/.cache/kodi-lifecycle/current-transaction
```

The streamed administrator program must:

1. verify `/etc/os-release` reports CoreELEC 21.3 and the platform reports
   Amlogic-ng;
2. create backup and cache parents at mode `0700`;
3. copy the existing wrapper and authorized keys into `rollback/` at mode
   `0600`, recording absence explicitly;
4. write candidates with Python `os.open(..., O_CREAT | O_EXCL, 0o600)`,
   never
   following a planted symlink/hard link;
5. replace only the line carrying marker
   `homeassistant-ugoos-kodi-lifecycle`;
6. validate the preferred `restrict` candidate with the target's
   `ssh-keygen -l -f`; if that parser rejects the option, render and validate
   the explicit no-forwarding fallback instead;
7. atomically rename candidates;
8. set the wrapper to `0700`, `.ssh` to `0700`, and `authorized_keys` to
   `0600`; and
9. retain rollback material until restricted-key verification succeeds.

Do not copy transaction mechanics from the add-on deployment verbatim. Reuse
its state names and safety invariants, but keep the lifecycle transaction
small and independently recoverable.

- [ ] **Step 5: Implement restricted-key verification and restoration**

Before deployment, record whether `kodi.service` is `running`, `stopped`, or
`failed` through administrator SSH. Refuse automatic mutation from `failed`;
report it for operator repair.

After install, invoke the forced-command key in this order:

```text
status
start
status
stop
status
start when the initial state was running, otherwise stop
status
```

Require exact stdout and empty unexpected output. Also attempt `id` and
require nonzero status to prove arbitrary commands are denied. Use
`StrictHostKeyChecking=yes`; never learn a new target host key during
controller verification.

Finalize only after the restored status matches the initial status. On any
failure, run the administrator rollback program and verify both target files
match their pre-run digest or absence.

- [ ] **Step 6: Implement redacted reporting and recovery commands**

Write reports at mode `0600`. Include:

```text
deployment_state=committed|rolled-back|pending-verification|incomplete-rollback
target=ugoos-theater
wrapper_path=/storage/.config/kodi-lifecycle
controller_key_supplied=1
controller_identity_supplied=1
restricted.status=pass|fail
restricted.start=pass|fail
restricted.stop=pass|fail
restricted.arbitrary_command_denied=pass|fail
restored_state=running|stopped|failed
```

Do not include fingerprints if doing so would require logging raw key
commands. Scan the finished report for the normalized key blob and the
private-key file's first nonempty line; fail and remove the report if either
appears.

For incomplete rollback, print exact `--rollback-transaction` and
`--inspect-transaction` commands and leave the pointer plus rollback
directory intact.

- [ ] **Step 7: Run focused lifecycle deployment tests**

Run:

```bash
bash tests/test-coreelec-lifecycle.sh
bash tests/test-coreelec-addon-workflows.sh
bash -n configure-kodi-lifecycle.sh lib/coreelec-lifecycle.sh lib/coreelec-ssh.sh
```

Expected: all commands PASS.

- [ ] **Step 8: Commit lifecycle deployment**

```bash
git add configure-kodi-lifecycle.sh lib/coreelec-lifecycle.sh \
  tests/test-coreelec-lifecycle.sh
git commit -m "feat: deploy Home Assistant Kodi control"
```

---

### Task 4: Theater Home Assistant Package and State Machine

**Files:**
- Create: `home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml`
- Create: `home-assistant/ssh/ugoos-kodi-lifecycle.conf.example`
- Create: `tests/test-home-assistant-ugoos-package.sh`

**Interfaces:**
- Consumes Home Assistant entities `media_player.sony_xr_65a90j` and `media_player.kodi_theater`, DNS name `ugoos-theater`, key `/config/.ssh/ugoos_kodi_lifecycle_ed25519`, and known hosts `/config/.ssh/known_hosts`.
- Produces helpers `input_boolean.ugoos_theater_keep_kodi_running`, `input_boolean.ugoos_theater_idle_poweroff_sent`, `input_boolean.ugoos_theater_input_idle`, `input_datetime.ugoos_theater_idle_probe_updated`, and `input_text.ugoos_theater_kodi_lifecycle_state`.
- Produces configuration/health entities `input_number.ugoos_theater_idle_timeout_minutes`, `input_boolean.ugoos_theater_host_reachable`, `input_text.ugoos_theater_last_lifecycle_command`, `input_datetime.ugoos_theater_last_reconciliation`, `input_text.ugoos_theater_last_lifecycle_error`, and `sensor.ugoos_theater_desired_kodi_state`.
- Produces shell commands `ugoos_theater_kodi_start`, `ugoos_theater_kodi_stop`, and `ugoos_theater_kodi_status`.
- Produces scripts `ugoos_theater_reconcile_kodi` and `ugoos_theater_power_off_idle_sony`.
- Produces no suspend, shutdown, reboot, WoL, or arbitrary remote command.

- [ ] **Step 1: Write failing static package contract tests**

Create `tests/test-home-assistant-ugoos-package.sh` using
`tests/test-helper.sh`. Add:

```bash
test_package_uses_expected_theater_entities_and_host
test_package_defaults_keep_running_override_to_off
test_package_defaults_idle_timeout_to_thirty_minutes
test_package_contains_only_static_start_stop_status_ssh_commands
test_ssh_commands_require_batch_mode_strict_host_key_and_persistent_paths
test_unknown_and_unavailable_sony_states_demand_running
test_sony_off_requires_sixty_continuous_seconds
test_keep_running_and_policy_opt_out_precede_sony_off
test_idle_requires_kodi_idle_duration_and_fresh_input_idle
test_playing_and_paused_do_not_trigger_idle_poweroff
test_idle_probe_calls_exact_kodi_boolean
test_idle_evidence_expires_after_thirty_seconds
test_idle_powers_off_sony_before_normal_kodi_stop_flow
test_package_has_no_suspend_shutdown_reboot_wol_or_toggle_command
test_errors_create_persistent_notifications
```

Use exact-text section extraction rather than a YAML parser. Add a local
policy fixture function to the test file:

```bash
desired_kodi_state() {
  local policy="$1" keep="$2" sony="$3" off_seconds="$4"
  if [[ "${policy}" != "on" || "${keep}" == "on" ]]; then
    printf 'running\n'
  elif [[ "${sony}" == "off" && "${off_seconds}" -ge 60 ]]; then
    printf 'stopped\n'
  else
    printf 'running\n'
  fi
}
```

Drive the full precedence matrix and require package templates to contain
the same ordered conditions. This test is a static contract check; live Home
Assistant `check_config` remains the YAML/Jinja authority.

- [ ] **Step 2: Run package tests to verify they fail**

Run:

```bash
bash tests/test-home-assistant-ugoos-package.sh
```

Expected: FAIL because the package and SSH example do not exist.

- [ ] **Step 3: Add persistent helpers and static SSH commands**

Create the package with these defaults:

```yaml
input_boolean:
  ugoos_theater_keep_kodi_running:
    name: Theater - Keep Kodi running
  ugoos_theater_host_reachable:
    name: Theater - Ugoos host reachable
    initial: false
  ugoos_theater_idle_poweroff_sent:
    name: Theater - Idle power-off sent
    initial: false
  ugoos_theater_input_idle:
    name: Theater - Kodi input idle
    initial: false

input_number:
  ugoos_theater_idle_timeout_minutes:
    name: Theater - Kodi idle timeout
    min: 5
    max: 120
    step: 5
    unit_of_measurement: min
    mode: box
    initial: 30

input_datetime:
  ugoos_theater_idle_probe_updated:
    name: Theater - Kodi idle probe updated
    has_date: true
    has_time: true
  ugoos_theater_last_reconciliation:
    name: Theater - Last Kodi reconciliation
    has_date: true
    has_time: true

input_text:
  ugoos_theater_kodi_lifecycle_state:
    name: Theater - Kodi lifecycle state
    initial: running
    max: 16
  ugoos_theater_last_lifecycle_command:
    name: Theater - Last Kodi lifecycle command
    max: 16
  ugoos_theater_last_lifecycle_error:
    name: Theater - Last Kodi lifecycle error
    max: 255
```

Home Assistant restores helper state unless `initial` is present. Deliberately
omit `initial` from `ugoos_theater_keep_kodi_running`: a newly created
`input_boolean` defaults off, then its state persists across restart. The
other internal helpers may reset and reconcile on startup. The idle timeout
is declarative per-device configuration: its `initial` value defaults to 30
and is the one literal changed in a copied package to configure another
timeout.

Define three non-templated command actions:

```yaml
shell_command:
  ugoos_theater_kodi_start: >-
    ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf
    ugoos-theater-lifecycle start
  ugoos_theater_kodi_stop: >-
    ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf
    ugoos-theater-lifecycle stop
  ugoos_theater_kodi_status: >-
    ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf
    ugoos-theater-lifecycle status
```

Create `home-assistant/ssh/ugoos-kodi-lifecycle.conf.example`:

```sshconfig
Host ugoos-theater-lifecycle
  HostName ugoos-theater
  User root
  Port 22
  IdentityFile /config/.ssh/ugoos_kodi_lifecycle_ed25519
  UserKnownHostsFile /config/.ssh/known_hosts
  IdentitiesOnly yes
  BatchMode yes
  StrictHostKeyChecking yes
  ConnectTimeout 12
  ConnectionAttempts 1
  RequestTTY no
  ClearAllForwardings yes
```

- [ ] **Step 4: Add lifecycle status and serialized reconciliation**

Implement `script.ugoos_theater_reconcile_kodi` with `mode: queued`,
`max_exceeded: silent`, and:

```yaml
variables:
  stop_when_display_off: true
```

Compute desired state in this order:

```jinja2
{% if not stop_when_display_off %}
  running
{% elif is_state('input_boolean.ugoos_theater_keep_kodi_running', 'on') %}
  running
{% elif is_state('media_player.sony_xr_65a90j', 'off') %}
  stopped
{% else %}
  running
{% endif %}
```

Set `stop_when_display_off` to literal `true` in the theater package. This is
the concrete enabled-by-default package; a device opts out by changing only
that literal to `false`.

For each shell action, capture `response_variable`. Require `returncode == 0`
and trimmed stdout exactly `running`, `stopped`, or `failed`. Start waits up
to 90 seconds for `media_player.kodi_theater` to leave `off` and
`unavailable`. Stop requires exact `stopped`; Kodi becoming unavailable is
expected. Store verified state in
`input_text.ugoos_theater_kodi_lifecycle_state`.

On invalid output, nonzero return, `failed`, or timeout, create a namespaced
`persistent_notification` with the operation and sanitized stderr. Do not
include command lines or key paths in notification text.

On every successful status/start/stop response:

- set `ugoos_theater_host_reachable` on;
- update the lifecycle-state and last-command helpers;
- stamp `ugoos_theater_last_reconciliation`;
- clear `ugoos_theater_last_lifecycle_error`; and
- dismiss the matching persistent notification.

On transport failure, set host reachable off and store a bounded,
credential-free error. Add a 30-second status poll so host reachability and
actual lifecycle state remain observable even without a Sony transition.
Expose a template sensor named **Theater - Desired Kodi state** using the
same ordered policy conditions as the reconciler.

- [ ] **Step 5: Add Sony state triggers and startup reconciliation**

Add automations:

```yaml
- id: ugoos_theater_kodi_start_for_sony
  triggers:
    - trigger: state
      entity_id: media_player.sony_xr_65a90j
      not_to: "off"
  actions:
    - action: script.ugoos_theater_reconcile_kodi

- id: ugoos_theater_kodi_stop_for_sony
  triggers:
    - trigger: state
      entity_id: media_player.sony_xr_65a90j
      to: "off"
      for: "00:01:00"
  actions:
    - action: script.ugoos_theater_reconcile_kodi
```

Add triggers for **Keep Kodi running** changes and Home Assistant start.
Startup must call start/reconcile for non-off, unknown, and unavailable Sony
states. A startup Sony `off` state must use a separate 60-second delay with a
final `off` condition before reconciliation; do not reuse pre-restart state
duration.

- [ ] **Step 6: Add Kodi idle probe and fresh evidence handling**

Every 15 seconds while `media_player.kodi_theater` is not `off`,
`unknown`, or `unavailable`, call:

```yaml
action: kodi.call_method
target:
  entity_id: media_player.kodi_theater
data:
  method: XBMC.GetInfoBooleans
  booleans:
    - >-
      System.IdleTime({{
        states('input_number.ugoos_theater_idle_timeout_minutes') | int(30)
        * 60
      }})
```

Consume only `kodi_call_method_result` events whose entity, method, and exact
boolean list match the value generated from the current timeout helper. Set
`input_boolean.ugoos_theater_input_idle` from the returned string value and stamp
`input_datetime.ugoos_theater_idle_probe_updated`.

A 15-second freshness automation turns the input-idle helper off when the
timestamp is more than 30 seconds old. On Home Assistant start, Kodi
unavailability, malformed result, or failed result, immediately clear the
helper rather than retaining stale positive evidence.

- [ ] **Step 7: Add idle Sony power-off and episode reset**

Every 15 seconds, power off the Sony only when all are true:

```jinja2
{% set idle_seconds =
  states('input_number.ugoos_theater_idle_timeout_minutes') | int(30) * 60 %}
{{ is_state('media_player.kodi_theater', 'idle')
and as_timestamp(now()) - as_timestamp(
      states.media_player.kodi_theater.last_changed
    ) >= idle_seconds
and is_state('input_boolean.ugoos_theater_input_idle', 'on')
and as_timestamp(now()) - as_timestamp(
      states('input_datetime.ugoos_theater_idle_probe_updated')
    ) <= 30
and is_state('input_boolean.ugoos_theater_idle_poweroff_sent', 'off') }}
```

Set `ugoos_theater_idle_poweroff_sent` before issuing Sony power-off so
parallel ticks cannot duplicate the command. Wait up to 30 seconds for Sony
`off`. On failure, clear the sent helper, notify, and leave Kodi running. On
success, do not stop Kodi directly; the normal 60-second Sony-off automation
owns that transition.

Reset the sent helper only after Kodi leaves `idle` or fresh input-idle
evidence becomes false. **Keep Kodi running** and the static stop-policy
literal must not appear in the Sony idle-power conditions.

- [ ] **Step 8: Run package contract and shell tests**

Run:

```bash
bash tests/test-home-assistant-ugoos-package.sh
bash tests/test-coreelec-lifecycle.sh
bash -n tests/test-home-assistant-ugoos-package.sh
```

Expected: all commands PASS.

If a Home Assistant deployment environment is available, copy the package
and SSH configuration into a disposable configuration checkout and run its
existing:

```bash
ha core check
```

Expected: configuration valid. If no HA environment is available, record
this as device acceptance work; do not install a new local validator.

- [ ] **Step 9: Commit the Home Assistant package**

```bash
git add home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml \
  home-assistant/ssh/ugoos-kodi-lifecycle.conf.example \
  tests/test-home-assistant-ugoos-package.sh
git commit -m "feat: coordinate Kodi with Sony display state"
```

---

### Task 5: Operations Documentation and Integrated Verification

**Files:**
- Create: `docs/home-assistant/ugoos-kodi-lifecycle.md`
- Modify: `README.md`
- Modify: `config/README.md`
- Modify: `docs/runbook.md`
- Modify: `docs/devices/ugoos-am6b-plus/coreelec-21.3.md`
- Modify: `docs/network/pfsense-plus-26.07-onboarding.md`
- Modify: `docs/network/wake-on-lan.md`
- Modify: `rooms/theater/devices/sony-xr-65a90j.md`
- Modify: `rooms/theater/devices/ugoos-am6b-plus.md`
- Modify: `rooms/theater/README.md`

**Interfaces:**
- Consumes the CLI, package, exact defaults, state names, paths, timeouts, and report fields implemented in Tasks 1-4.
- Produces one operator sequence from key creation through theater acceptance and later room rollout.

- [ ] **Step 1: Write the Home Assistant deployment and operations guide**

Create `docs/home-assistant/ugoos-kodi-lifecycle.md` with these exact
operator phases:

1. Confirm CoreELEC baseline provisioning reports
   `cec.tv_off_action.status=match`.
2. In Home Assistant's Terminal & SSH app, create:

   ```bash
   mkdir -p /config/.ssh
   chmod 700 /config/.ssh
   ssh-keygen -t ed25519 \
     -f /config/.ssh/ugoos_kodi_lifecycle_ed25519 \
     -C homeassistant-ugoos-kodi-lifecycle
   ssh-keyscan -H ugoos-theater >> /config/.ssh/known_hosts
   chmod 600 /config/.ssh/ugoos_kodi_lifecycle_ed25519 \
     /config/.ssh/known_hosts
   ```

3. Securely make the controller identity available to the Mac only for
   gateway deployment, or run the repository deployment command from a
   trusted checkout that can read both controller key files:

   ```bash
   ./configure-kodi-lifecycle.sh \
     --target ugoos-theater \
     --controller-public-key "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519.pub" \
     --controller-identity "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519"
   ```

   State explicitly that neither file belongs in the repository and any
   temporary Mac copy must be removed after deployment.

4. Install the example SSH config as
   `/config/.ssh/ugoos-kodi-lifecycle.conf`, copy the package under
   `/config/packages/`, enable `homeassistant: packages:`, and ensure the
   Sony/Kodi entities use the package's exact IDs.
5. Run `ha core check`, reload shell commands or restart HA, and test all
   three restricted commands from Developer Tools.
6. Describe the enabled stop policy, 60-second off interval, 30-minute idle,
   15-second probe, freshness, persistent override, explicit opt-out, and
   fail-awake rules.
7. Give diagnostic commands for the lifecycle report, systemd status,
   authorized-key marker, HA logs, and persistent notifications.
8. Give rollback and key-revocation steps using the lifecycle CLI, never
   manual broad deletion of `authorized_keys`.

- [ ] **Step 2: Update provisioning, network, and room workflow docs**

Make the documentation agree on this order:

```text
CoreELEC wizard
-> DHCP reservation and DNS
-> shared baseline provisioning (CEC Ignore)
-> restricted lifecycle gateway deployment
-> Sony and Kodi Home Assistant integrations
-> theater HA package
-> playback configuration
-> lifecycle/idle acceptance
```

Document a pfSense IoT ingress rule allowing only the actual HA host address
to each managed Ugoos reserved address on TCP/22. Require logging during
pilot validation and prohibit a broad IoT-to-LAN SSH rule.

In the Ugoos guide, replace baseline **Suspend and wake work repeatedly**
acceptance with:

```text
CoreELEC remains pingable and reachable over SSH for 24 hours while the
display is off; Kodi may be intentionally stopped.
```

Move suspend and WoL tests into an explicitly optional experimental section.
In the WoL guide, state that WoL is not invoked by the lifecycle package and
does not satisfy keep-alive acceptance.

Keep Sony **Device auto power off** and **TV auto power on** disabled. State
that HA owns display idle power-off and Kodi lifecycle; BRAVIA Sync remains
enabled only for discovery, remote navigation, and audio coordination.

- [ ] **Step 3: Add the exact theater acceptance record**

Add fields/checks for:

```text
Sony entity ID
Kodi entity ID
Ugoos lifecycle DNS alias/address
Controller public-key marker installed date
CEC TV-off action observed value
Stop-policy enabled/opt-out
Idle timeout
24-hour display-off reachability result
Sony-off -> Kodi-stop result and elapsed time
Sony-on -> Kodi-ready result and elapsed time
Idle -> Sony-off -> Kodi-stop result
Keep-running override result
HA restart result
Ugoos reboot result
Restricted-command denial result
```

Do not mark results passed without a live device/HA test and date.

- [ ] **Step 4: Run all local tests and syntax checks**

Run:

```bash
for test_file in tests/test-coreelec-config.sh \
  tests/test-coreelec-artifacts.sh \
  tests/test-coreelec-settings.sh \
  tests/test-coreelec-report.sh \
  tests/test-coreelec-addon-workflows.sh \
  tests/test-coreelec-lifecycle.sh \
  tests/test-home-assistant-ugoos-package.sh; do
  bash "${test_file}"
done

bash -n provision-coreelec.sh configure-coreelec-addons.sh \
  configure-kodi-lifecycle.sh \
  lib/coreelec-config.sh lib/coreelec-artifacts.sh \
  lib/coreelec-addon-workflows.sh lib/coreelec-ssh.sh \
  lib/coreelec-lifecycle.sh tests/test-*.sh

git diff --check
```

Expected: every test reports all tests passed, syntax checking exits 0, and
`git diff --check` prints nothing.

- [ ] **Step 5: Review implementation against every spec acceptance item**

Read
`docs/superpowers/specs/2026-09-11-ugoos-network-keep-alive-design.md` and
record whether each of its 13 device/HA acceptance items is:

- covered by an automated local test;
- documented as pending theater validation; or
- completed on the live theater pair with date and evidence.

Do not convert pending device work into a success-shaped local result. The
implementation is locally complete when all automatable items pass and every
hardware-dependent item has an exact runbook step and uncompleted record.

- [ ] **Step 6: Commit operations documentation**

```bash
git add README.md config/README.md docs/runbook.md \
  docs/home-assistant/ugoos-kodi-lifecycle.md \
  docs/devices/ugoos-am6b-plus/coreelec-21.3.md \
  docs/network/pfsense-plus-26.07-onboarding.md \
  docs/network/wake-on-lan.md \
  rooms/theater/README.md \
  rooms/theater/devices/sony-xr-65a90j.md \
  rooms/theater/devices/ugoos-am6b-plus.md
git commit -m "docs: add Ugoos lifecycle operations"
```
