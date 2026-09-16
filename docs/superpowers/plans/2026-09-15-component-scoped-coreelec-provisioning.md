# Component-scoped CoreELEC Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add component-scoped CoreELEC transactions so a CEC-only maintenance run mutates and verifies only CEC state while legacy provisioning remains a full baseline.

**Architecture:** Keep `provision-coreelec.sh` as the only transaction coordinator. Add a deterministic component graph that drives scoped payload flags, artifact selection, device-side mutations, backup paths, verification verdicts, and report fields. Preserve the current full-baseline default and existing `--addon` behavior.

**Tech Stack:** Bash 3.2-compatible shell, embedded Python 3, POSIX remote shell, XML/JSON fixtures, CoreELEC systemd/SSH, Home Assistant YAML.

**Spec:** `docs/superpowers/specs/2026-09-15-component-scoped-coreelec-provisioning-design.md`

## Global Constraints

- Preserve all current uncommitted PM4K 1.3.19, CEC power-isolation, Home Assistant race, AF3 semantic-verification, convergence-retry, tests, and documentation changes.
- Do not revert or overwrite user changes in the dirty worktree.
- No `--component` must preserve the current full-baseline behavior.
- Legacy `--addon ID` without explicit components must continue applying the full shared settings baseline.
- Explicit `--addon ID` implicitly requests `addons`.
- Component dependencies are deterministic and cycle-checked.
- Unknown, unimplemented, contradictory, or empty plans fail before device contact.
- A CEC-only run must not mutate or judge Arctic Fuse, service, room, or add-on state.
- Full-baseline Arctic Fuse verification remains strict.
- Do not copy Kodi or add-on database rows.
- Keep Bash 3.2 compatibility; do not use associative arrays, `mapfile`, or Bash 4-only syntax.
- Reports remain strict `key=value` and must not expose secrets, key material, managed contents, or dynamic CEC adapter filenames.
- Keep the Home Assistant `input_boolean.ugoos_theater_keep_kodi_running` override on until the corrected package is installed and live validation reaches the explicit disable step.

---

## File Structure

**Primary implementation**

- Modify `provision-coreelec.sh`
  - Parse component requests.
  - Expand dependencies.
  - Render scoped payload flags.
  - Permit component transactions without artifacts.
  - Apply scoped transforms.
  - Render scoped observations, verdicts, and reports.

**Existing tests**

- Modify `tests/test-coreelec-config.sh`
  - Component names, aliases, dependency expansion, CLI conflicts, and legacy compatibility.
- Modify `tests/test-coreelec-settings.sh`
  - Device-side transform isolation and component combinations.
- Modify `tests/test-coreelec-artifacts.sh`
  - Scoped staging, empty artifact plans, backup/rollback, and remote plan validation.
- Modify `tests/test-coreelec-report.sh`
  - Scoped observation comparison, report fields, CEC-only behavior, and full-baseline strictness.
- Modify `tests/test-coreelec-addon-workflows.sh` only if an assertion assumes `--addon` cannot coexist with explicit components.

**Home Assistant regression already in progress**

- Preserve `home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml`.
- Preserve `tests/home-assistant-ugoos-fixture.py`.
- Preserve `tests/test-home-assistant-ugoos-package.sh`.

**Documentation**

- Modify `docs/operations/provision-ugoos.md`.
- Modify `docs/home-assistant/ugoos-kodi-lifecycle.md`.
- Modify `config/README.md`.
- Modify top-level CLI usage text in `provision-coreelec.sh`.

---

### Task 0: Checkpoint the verified in-progress safety fixes

**Files:**
- Modify: `provision-coreelec.sh`
- Modify: `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf`
- Modify: `home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml`
- Modify: `tests/home-assistant-ugoos-fixture.py`
- Modify: `tests/test-home-assistant-ugoos-package.sh`
- Modify: `tests/test-coreelec-settings.sh`
- Modify: `tests/test-coreelec-report.sh`
- Modify: `tests/test-coreelec-artifacts.sh`
- Modify: `tests/test-coreelec-config.sh`
- Modify: `tests/test-coreelec-addon-workflows.sh`
- Modify: `docs/home-assistant/ugoos-kodi-lifecycle.md`
- Modify: `docs/operations/provision-ugoos.md`
- Modify: `docs/decisions/ugoos-coreelec-21.3-system.md`
- Modify: `rooms/theater/devices/ugoos-am6b-plus.md`

**Interfaces:**
- Consumes: the existing dirty worktree described in the session handoff.
- Produces: a clean, reviewable checkpoint before component-scoping edits
  begin.

- [ ] **Step 1: Inventory without altering the worktree**

Run:

```bash
git status --short
git diff --stat
git diff --check
```

Confirm the diff contains only the recorded PM4K stable patch, CEC power
isolation, HA stale-sensor race fix, AF3 inert-default semantics, verification
retry, associated tests, and related documentation. Stop and ask if unrelated
or conflicting changes appear.

- [ ] **Step 2: Re-run the existing verification**

The test scripts do not support a focused selector, so run their full suites:

```bash
bash -n provision-coreelec.sh
./tests/test-coreelec-config.sh
./tests/test-coreelec-settings.sh
./tests/test-coreelec-artifacts.sh
./tests/test-coreelec-report.sh
./tests/test-coreelec-addon-workflows.sh
./tests/test-home-assistant-ugoos-package.sh
./provision-coreelec.sh --check-config
./provision-coreelec.sh --check-artifacts
```

Expected: all commands exit zero.

- [ ] **Step 3: Commit the verified prerequisite changes**

Stage only the files enumerated in this task:

```bash
git add \
  provision-coreelec.sh \
  config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf \
  home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml \
  tests/home-assistant-ugoos-fixture.py \
  tests/test-home-assistant-ugoos-package.sh \
  tests/test-coreelec-settings.sh \
  tests/test-coreelec-report.sh \
  tests/test-coreelec-artifacts.sh \
  tests/test-coreelec-config.sh \
  tests/test-coreelec-addon-workflows.sh \
  docs/home-assistant/ugoos-kodi-lifecycle.md \
  docs/operations/provision-ugoos.md \
  docs/decisions/ugoos-coreelec-21.3-system.md \
  rooms/theater/devices/ugoos-am6b-plus.md
git commit -m "fix: harden Ugoos provisioning lifecycle" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Do not stage the component plan file in this checkpoint.

---

### Task 1: Component graph and CLI plan

**Files:**
- Modify: `provision-coreelec.sh`
- Test: `tests/test-coreelec-config.sh`

**Interfaces:**
- Consumes: existing `parse_args`, `ADDONS`, `APPLY_KODI`, and configuration validation.
- Produces:
  - `REQUESTED_COMPONENTS`: indexed Bash array of normalized explicit requests.
  - `EFFECTIVE_COMPONENTS`: indexed Bash array in stable dependency order.
  - `COMPONENTS_EXPLICIT`: `"0"` or `"1"`.
  - `coreelec_component_requested NAME`: boolean shell function.
  - `coreelec_component_effective NAME`: boolean shell function.
  - Internal `--print-component-plan` output for deterministic tests.

- [ ] **Step 1: Add failing graph and compatibility tests**

Add tests that invoke the real CLI parser through a new internal
`--print-component-plan` entry point:

```bash
test_default_component_plan_is_full_baseline() {
  local output
  output="$(bash "${PROVISIONER}" --print-component-plan)"
  assert_contains "${output}" "components.requested=baseline"
  assert_contains "${output}" "components.effective=core,cec,addons,services,skin"
  assert_contains "${output}" "components.dependencies_added=none"
}

test_explicit_cec_plan_is_isolated() {
  local output
  output="$(bash "${PROVISIONER}" --component cec --print-component-plan)"
  assert_contains "${output}" "components.requested=cec"
  assert_contains "${output}" "components.effective=cec"
}

test_skin_expands_dependencies_in_stable_order() {
  local output
  output="$(bash "${PROVISIONER}" --component skin --print-component-plan)"
  assert_contains "${output}" "components.effective=core,addons,skin"
  assert_contains "${output}" "components.dependencies_added=core,addons"
}

test_explicit_addon_implies_addons_component() {
  local output
  output="$(bash "${PROVISIONER}" --component cec --addon script.plexmod \
    --print-component-plan)"
  assert_contains "${output}" "components.effective=cec,addons"
}
```

Also test duplicate requests, `baseline`, `services`, unknown names,
unimplemented `room`, `--no-kodi` conflicts, and an empty effective plan.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
./tests/test-coreelec-config.sh
```

Expected: failures because `--component` and `--print-component-plan` do not
exist.

- [ ] **Step 3: Implement the component registry and dependency expansion**

Use indexed arrays and newline membership checks:

```bash
REQUESTED_COMPONENTS=()
EFFECTIVE_COMPONENTS=()
COMPONENTS_EXPLICIT="0"
PRINT_COMPONENT_PLAN="0"

coreelec_component_known() {
  case "$1" in
    baseline|core|cec|addons|services|skin|room) return 0 ;;
    *) return 1 ;;
  esac
}

coreelec_component_implemented() {
  case "$1" in
    baseline|core|cec|addons|services|skin) return 0 ;;
    *) return 1 ;;
  esac
}

coreelec_component_dependencies() {
  case "$1" in
    services) printf '%s\n' addons ;;
    skin) printf '%s\n' core addons ;;
    room) printf '%s\n' core ;;
  esac
}
```

Expand `baseline` to `core cec addons services skin`, recursively add
dependencies, reject cycles, then normalize effective order as:

```text
core,cec,addons,services,skin,room
```

When no component is explicit, set requested to `baseline` even if legacy
`--addon` filters exist. When components are explicit and `--addon` values
exist, add `addons` to the request before expansion.

- [ ] **Step 4: Implement pre-contact validation**

Before any SSH/DNS/device call:

- reject unknown components;
- reject `room` as unimplemented;
- reject `--no-kodi` with any explicit component;
- reject empty effective plans;
- preserve legacy no-component `--addon` behavior.

- [ ] **Step 5: Run focused and full config tests**

Run:

```bash
./tests/test-coreelec-config.sh
```

Expected: focused tests and the full suite pass.

- [ ] **Step 6: Commit the component graph**

```bash
git add provision-coreelec.sh tests/test-coreelec-config.sh
git commit -m "feat: add CoreELEC component planning" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Scoped device-side settings transformation

**Files:**
- Modify: `provision-coreelec.sh`
- Test: `tests/test-coreelec-settings.sh`

**Interfaces:**
- Consumes: `EFFECTIVE_COMPONENTS` from Task 1.
- Produces payload booleans:
  - `APPLY_COMPONENT_CORE`
  - `APPLY_COMPONENT_CEC`
  - `APPLY_COMPONENT_ADDONS`
  - `APPLY_COMPONENT_SERVICES`
  - `APPLY_COMPONENT_SKIN`
- Produces transformer output containing only paths changed by effective
  components.

- [ ] **Step 1: Add failing CEC isolation tests**

Create a fixture containing distinct sentinels in every current settings
surface. Record hashes before the transform, run with only
`APPLY_COMPONENT_CEC=1`, then assert:

```bash
assert_eq "0" "$(xml_setting "${cec_path}" activate_source)"
assert_eq "231" "$(xml_setting "${cec_path}" wake_devices)"
assert_eq "231" "$(xml_setting "${cec_path}" standby_devices)"
assert_eq "0" "$(xml_setting "${cec_path}" standby_tv_on_pc_standby)"
assert_eq "36028" "$(xml_setting "${cec_path}" standby_pc_on_tv_standby)"
assert_eq "${guisettings_before}" "$(sha256sum "${guisettings}")"
assert_eq "${skin_before}" "$(sha256sum "${skin_settings}")"
assert_eq "${weather_before}" "$(sha256sum "${weather_settings}")"
assert_eq "${playlist_before}" "$(sha256sum "${playlist}")"
```

Add a second test combining `core,cec` and proving both owned surfaces change
once while skin/services remain byte-identical.

- [ ] **Step 2: Run isolation tests and confirm RED**

Run:

```bash
./tests/test-coreelec-settings.sh
```

Expected: CEC values change, but unrelated files also change because the
transformer ignores scope.

- [ ] **Step 3: Add scoped payload keys**

Add the five `APPLY_COMPONENT_*` keys to the embedded Python payload allowlist
and require each to decode to `"0"` or `"1"`.

Render them from the effective component plan:

```bash
coreelec_settings_payload_entry APPLY_COMPONENT_CORE \
  "$(coreelec_component_effective core && printf 1 || printf 0)"
```

Repeat for every implemented component.

- [ ] **Step 4: Gate each transformer block**

Restructure the embedded transformer without changing existing mutations:

```python
apply_core = config("APPLY_COMPONENT_CORE") == "1"
apply_cec = config("APPLY_COMPONENT_CEC") == "1"
apply_services = config("APPLY_COMPONENT_SERVICES") == "1"
apply_skin = config("APPLY_COMPONENT_SKIN") == "1"

if apply_core:
    # regional, timezone, web access, update policy, shared defaults

if apply_cec:
    set_cec_power_policy(storage_root, cec_tv_off_action)

if apply_services:
    # TMDb, NextPVR, Weather, PM4K settings

if apply_skin:
    # active skin, AF3 settings, JSON nodes, playlists
```

Load and write `guisettings.xml` only when `core` or `skin` is effective.
Split the current `kodi_values` dictionary so each key has one owner.

- [ ] **Step 5: Preserve strict CEC behavior**

Only require exactly one CEC peripheral file when `cec` is effective. A
CEC-unselected transaction must neither read nor validate that file.

- [ ] **Step 6: Run settings tests**

Run:

```bash
./tests/test-coreelec-settings.sh
```

Expected: all tests pass; a second CEC-only transform is byte-identical.

- [ ] **Step 7: Commit scoped transforms**

```bash
git add provision-coreelec.sh tests/test-coreelec-settings.sh
git commit -m "feat: scope CoreELEC settings transforms" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Scoped artifact plans, backup, and rollback

**Files:**
- Modify: `provision-coreelec.sh`
- Test: `tests/test-coreelec-artifacts.sh`

**Interfaces:**
- Consumes: `coreelec_component_effective addons`.
- Produces:
  - a valid empty deploy manifest when `addons` is not effective;
  - a component list in the remote deployment plan;
  - backup entries only for effective mutable paths.

- [ ] **Step 1: Add failing empty-artifact CEC transaction test**

Render a remote transaction with `APPLY_COMPONENT_CEC=1` and an empty
`deploy.tsv`. Assert it:

- accepts zero artifacts;
- validates and backs up the one CEC peripheral file;
- never references `.kodi/addons`;
- never writes `guisettings.xml`, AF3 settings, nodes, playlists, or service
  settings;
- restores the CEC file after an injected post-transform failure.

- [ ] **Step 2: Add failing mixed-plan test**

Render `cec,addons` with one selected PM4K artifact. Assert the transaction
changes CEC plus that add-on directory and no other settings domain.

- [ ] **Step 3: Run focused tests and confirm RED**

Run:

```bash
./tests/test-coreelec-artifacts.sh
```

Expected: failure because the remote transaction assumes a settings-wide plan
and artifact staging.

- [ ] **Step 4: Make artifact staging conditional**

If `addons` is not effective:

- create a private empty deploy manifest;
- skip artifact download/upload/staging;
- do not emit the reduced-selection dependency warning.

If `addons` is effective, preserve the current lock, checksum, source-shape,
PM4K patch, and selection behavior exactly.

- [ ] **Step 5: Scope remote mutation and rollback material**

Include component flags in the remote plan and revalidate them before
mutation. Build backup/applied lists from:

- paths emitted by the scoped transformer;
- selected add-on directories;
- component-required fixed files.

Do not make an unselected path a precondition for commit or rollback.

- [ ] **Step 6: Run artifact suites**

Run:

```bash
./tests/test-coreelec-artifacts.sh
```

Expected: all tests pass, including existing transaction rollback cases.

- [ ] **Step 7: Commit scoped transactions**

```bash
git add provision-coreelec.sh tests/test-coreelec-artifacts.sh
git commit -m "feat: scope CoreELEC deployment transactions" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Scoped verification and audit reports

**Files:**
- Modify: `provision-coreelec.sh`
- Test: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: requested/effective component plan and scoped payload flags.
- Produces report fields:
  - `components.requested`
  - `components.effective`
  - `components.dependencies_added`
- Produces verdicts only for effective components.

- [ ] **Step 1: Add failing CEC-only comparator test**

Create observations with correct CEC values and deliberately invalid AF3,
service, regional, and add-on values. Verify:

```bash
output="$(run_verify_components cec "${config}" "${observations}" "${manifest}")"
assert_contains "${output}" "cec.activate_source.status=ok"
assert_not_contains "${output}" "arctic_fuse."
assert_not_contains "${output}" "addon.weather.ha."
assert_not_contains "${output}" "regional.locale."
```

- [ ] **Step 2: Add failing full-baseline compatibility test**

Use the same invalid AF3 observation under default `baseline`; require
`arctic_fuse.status=mismatch` and a nonzero result.

- [ ] **Step 3: Add failing report-plan tests**

Assert deterministic fields:

```text
components.requested=skin
components.effective=core,addons,skin
components.dependencies_added=core,addons
```

Assert a CEC-only report omits unselected component verdicts and still passes
the existing redaction guard.

- [ ] **Step 4: Run focused tests and confirm RED**

Run:

```bash
./tests/test-coreelec-report.sh
```

Expected: failure because the comparator always renders every current
baseline verdict.

- [ ] **Step 5: Pass component scope into verification**

Add encoded effective-component data to the verification request. Parse it as
a validated list on the device. Observation collection may read common
non-secret facts, but must not require files that belong only to unselected
components.

For `cec`, emit only:

- observation format/platform integrity;
- Kodi restart/readiness evidence;
- the five CEC values.

- [ ] **Step 6: Gate host-side comparisons**

Wrap existing comparison groups:

```bash
if coreelec_component_effective core; then
  # regional, timezone, shared Kodi checks
fi
if coreelec_component_effective cec; then
  # five CEC comparisons
fi
if coreelec_component_effective addons; then
  # selected artifact state
fi
if coreelec_component_effective services; then
  # TMDb, Weather, NextPVR, PM4K settings
fi
if coreelec_component_effective skin; then
  # AF3 semantic checks
fi
```

Keep the existing 60-second complete-sample retry. Do not treat a passing
subset as a full-baseline pass.

- [ ] **Step 7: Render component report fields**

Add requested/effective/dependency fields near transaction metadata. Ensure
comma-separated values cannot contain whitespace, newlines, or user-provided
text.

- [ ] **Step 8: Run report tests**

Run:

```bash
./tests/test-coreelec-report.sh
```

Expected: all tests pass, including persistent mismatch rollback and secret
redaction.

- [ ] **Step 9: Commit scoped verification**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "feat: verify CoreELEC components independently" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Integrate CEC and Home Assistant lifecycle fixes

**Files:**
- Modify: `provision-coreelec.sh`
- Modify: `home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml`
- Modify: `tests/home-assistant-ugoos-fixture.py`
- Modify: `tests/test-home-assistant-ugoos-package.sh`
- Test: `tests/test-coreelec-settings.sh`
- Test: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: `--component cec` transaction from Tasks 1-4.
- Produces:
  - CEC navigation without Kodi-to-TV power coupling;
  - status polling that does not reset an observation epoch for an ordinary
    actual/desired mismatch.

- [ ] **Step 1: Confirm the existing regressions remain present**

Review the checkpointed tests and retain these regression names:

```text
test_cec_navigation_remains_enabled_without_tv_power_coupling
test_stale_desired_sensor_never_restarts_an_intentionally_stopped_kodi
test_cec_power_coupling_mismatch_fails_verification
```

Do not revert production code to recreate historical failures. The red phase
already occurred during the preceding investigation. Do not delete or weaken
these regressions while integrating component scope.

- [ ] **Step 2: Keep the CEC policy under the `cec` component**

The scoped transformer must converge:

```text
enabled remains unchanged
activate_source=0
wake_devices=231
standby_devices=231
standby_tv_on_pc_standby=0
standby_pc_on_tv_standby=36028
```

- [ ] **Step 3: Keep the Home Assistant race fix**

The status-poll recovery condition must remain:

```jinja2
{{ poll_stdout in ['running', 'stopped']
   and (not previous_host_reachable
     or not is_state('input_boolean.ugoos_theater_observation_ready', 'on')
     or (previous_lifecycle_state in ['stopped', 'failed']
       and poll_stdout == 'running')) }}
```

An ordinary mismatch with the minute-refreshed desired sensor must not begin a
fresh observation.

- [ ] **Step 4: Run focused tests**

Run:

```bash
./tests/test-coreelec-settings.sh
./tests/test-home-assistant-ugoos-package.sh
./tests/test-coreelec-report.sh
```

Expected: all three pass.

- [ ] **Step 5: Inspect the integration diff**

Run:

```bash
git diff --check
git status --short
```

The safety fixes were checkpointed in Task 0. Any component-integration
changes should already be part of Tasks 1-4; do not create an empty commit.

---

### Task 6: Documentation and complete regression validation

**Files:**
- Modify: `provision-coreelec.sh`
- Modify: `docs/superpowers/plans/2026-09-15-component-scoped-coreelec-provisioning.md`
- Modify: `config/README.md`
- Modify: `docs/operations/provision-ugoos.md`
- Modify: `docs/home-assistant/ugoos-kodi-lifecycle.md`
- Modify: `docs/decisions/ugoos-coreelec-21.3-system.md`
- Modify: `rooms/theater/devices/ugoos-am6b-plus.md`

**Interfaces:**
- Consumes: final CLI and report contract.
- Produces: operator instructions for full, component-scoped, maintenance, and
  rollback workflows.

- [ ] **Step 1: Update CLI help**

Document:

```text
--component NAME
--component cec
--component skin
--component cec --addon script.plexmod
```

State that no component preserves the full baseline and that explicit
dependencies are expanded and reported.

- [ ] **Step 2: Update configuration and operations docs**

Add:

- component ownership table;
- dependency table;
- legacy `--addon` behavior;
- maintenance override requirement when HA lifecycle control is active;
- CEC-only command and expected report fields;
- 60-second verification convergence behavior;
- rollback instructions unchanged from the shared transaction workflow.

- [ ] **Step 3: Run every affected existing suite**

Run:

```bash
bash -n provision-coreelec.sh
./tests/test-coreelec-config.sh
./tests/test-coreelec-settings.sh
./tests/test-coreelec-artifacts.sh
./tests/test-coreelec-report.sh
./tests/test-coreelec-addon-workflows.sh
bash ./tests/test-coreelec-lifecycle.sh
./tests/test-home-assistant-ugoos-package.sh
./provision-coreelec.sh --check-config
./provision-coreelec.sh --check-artifacts
git diff --check
```

Expected: every command exits zero; artifact validation reports 41 locked
artifacts.

- [ ] **Step 4: Request code review**

Use the repository code-review workflow against all implementation changes.
Resolve only high-confidence issues tied to component scope, CEC safety, HA
reconciliation, or regressions.

- [ ] **Step 5: Commit documentation and review fixes**

```bash
git add \
  provision-coreelec.sh \
  docs/superpowers/plans/2026-09-15-component-scoped-coreelec-provisioning.md \
  config/README.md \
  docs/operations/provision-ugoos.md \
  docs/home-assistant/ugoos-kodi-lifecycle.md \
  docs/decisions/ugoos-coreelec-21.3-system.md \
  rooms/theater/devices/ugoos-am6b-plus.md \
  tests
git commit -m "docs: document scoped CoreELEC maintenance" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: Live CEC rollout and Home Assistant recovery validation

**Files:**
- Runtime target: `ugoos-theater`
- Runtime target: `/config/packages/ugoos_theater_kodi_lifecycle.yaml` on Home Assistant
- Generated report: `coreelec-provision-reports/ugoos-theater-*.txt`
- Generated evidence: session artifact logs only

**Interfaces:**
- Consumes: completed Tasks 1-6 and the enabled HA maintenance override.
- Produces: committed CEC-only transaction, corrected HA package, disabled
  override, and verified Sony-off/reboot recovery.

- [ ] **Step 1: Confirm maintenance preconditions**

Read-only checks:

```text
input_boolean.ugoos_theater_keep_kodi_running=on
input_text.ugoos_theater_kodi_lifecycle_state=running
media_player.theater_kodi_theater not unavailable
```

Do not issue Sony or Denon service calls.

- [ ] **Step 2: Deploy only CEC**

Run:

```bash
./provision-coreelec.sh \
  --target ugoos-theater \
  --component cec \
  --yes
```

Capture the complete log in the session artifact directory.

- [ ] **Step 3: Audit the CEC report**

Require:

```text
components.requested=cec
components.effective=cec
deployment_state=committed
verification_result=pass
verification_failures=0
cec.activate_source.status=ok
cec.wake_devices.status=ok
cec.standby_devices.status=ok
cec.standby_tv_on_pc_standby.status=ok
cec.tv_off_action.status=ok
```

Reject any report containing an Arctic Fuse verdict in this CEC-only run.

- [ ] **Step 4: Install the corrected Home Assistant package**

Have the operator copy the repository package to:

```text
/config/packages/ugoos_theater_kodi_lifecycle.yaml
```

Then run in Home Assistant Terminal:

```bash
ha core check
ha core restart
```

Wait for `/api/config`, `/api/states`, and the three lifecycle shell commands
to return.

- [ ] **Step 5: Disable the maintenance override**

Call:

```text
input_boolean.turn_off
entity_id=input_boolean.ugoos_theater_keep_kodi_running
```

Verify the helper is `off`.

- [ ] **Step 6: Validate the confirmed HA race**

Have the operator power the Sony off manually. Observe:

- Sony remains `off`;
- Kodi stops after at least 60 continuous seconds;
- later 30-second status polls do not restart Kodi;
- lifecycle state remains `stopped`;
- lifecycle error helpers remain empty.

- [ ] **Step 7: Validate CEC power isolation**

While Sony remains off:

1. Start Kodi through the restricted lifecycle command.
2. Confirm Sony remains off.
3. Reboot Ugoos through the administrator channel.
4. Wait for SSH, lifecycle status, and Kodi integration recovery.
5. Confirm Sony remains off.

Then have the operator turn Sony on manually and confirm Kodi reconciliation
and CEC navigation.

- [ ] **Step 8: Restore final state and record evidence**

Require:

```text
input_boolean.ugoos_theater_keep_kodi_running=off
input_boolean.ugoos_theater_host_reachable=on
input_boolean.ugoos_theater_observation_ready=on
input_text.ugoos_theater_kodi_lifecycle_state=running
all lifecycle error helpers empty
```

Update the session defect ledger:

- mark HA unexpected Sony power-on fixed;
- mark CEC Kodi-to-TV power coupling fixed;
- retain add-on sequencing, room desired state, weather, and remux buffering
  as separate pending subprojects.

- [ ] **Step 9: Commit any report-independent final adjustments**

Do not commit generated reports or session logs unless repository policy
already tracks them. If live validation required a code correction, repeat its
focused and full tests before committing that correction.
