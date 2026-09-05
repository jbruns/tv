# CoreELEC Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a first-boot CoreELEC 21.3 Ugoos AM6B-family device into a verified, room-independent Kodi baseline using a strict configuration file and deterministic add-on deployment.

**Architecture:** Keep `provision-coreelec.sh` as the macOS entry point, but move pure configuration and artifact logic into sourceable shell libraries so it can be tested without a device. The entry point will validate and stage all inputs locally, then perform one backed-up remote transaction while Kodi is stopped, restart Kodi, verify state through remote JSON-RPC and filesystem checks, and write a redacted audit report.

**Tech Stack:** Bash 3.2-compatible shell, macOS `curl`/`shasum`/`unzip`/`xmllint`, OpenSSH, CoreELEC BusyBox shell, CoreELEC Python 3, Kodi 21 JSON-RPC, XML and JSON settings files.

**Spec:** `docs/superpowers/specs/2026-09-05-coreelec-provisioning-design.md`

## Global Constraints

- Target CoreELEC `21.3` on Amlogic-ng and a Ugoos AM6-family device.
- Default timezone is `America/Los_Angeles`; default language/region is English/US.
- The configuration file is declarative `KEY=value` data and must never be sourced or evaluated as shell.
- `--target` remains required for provisioning; explicit CLI options override config values.
- Secrets come only from environment variables and never appear in config, logs, command arguments, reports, or world-readable files.
- Every add-on artifact and transitive dependency is pinned by ID, version, HTTPS URL, and SHA-256.
- All downloads and ZIP metadata are validated before Kodi is stopped.
- Kodi is restarted on every exit path after it has been stopped.
- Display, audio, HDMI, EDID, Dolby Vision, remote, hostname, and room network choices remain out of scope.
- Do not use Kodi's modal `InstallAddon` or `EnableAddon` builtins for unattended work.
- Preserve unrelated worktree changes; stage and commit only files named by each task.

## File Structure

- Modify `provision-coreelec.sh`: CLI parsing, orchestration, SSH operations, remote transaction, verification, and report generation.
- Create `lib/coreelec-config.sh`: defaults, strict config parser, CLI override application, and semantic validation.
- Create `lib/coreelec-artifacts.sh`: artifact record parsing, download, checksum, ZIP safety, and add-on metadata validation.
- Create `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf`: reviewed shared defaults and pinned artifact manifest.
- Create `tests/test-helper.sh`: isolated shell-test assertions and command runner.
- Create `tests/test-coreelec-config.sh`: parser, precedence, and secret validation tests.
- Create `tests/test-coreelec-artifacts.sh`: checksum, ZIP traversal, metadata, and artifact-record tests.
- Create `tests/test-coreelec-settings.sh`: offline tests of the generated remote Python settings transformer.
- Create `tests/test-coreelec-report.sh`: status classification and secret-redaction tests.
- Modify `config/README.md`: describe the implemented config format and shared/device boundary.
- Modify `docs/runbook.md`: describe running the provisioner and its remaining manual steps.
- Modify `docs/devices/ugoos-am6b-plus/coreelec-21.3.md`: replace manual shared regional/add-on setup with the provision-and-verify workflow.

---

### Task 1: Strict Configuration Parser

**Files:**
- Create: `lib/coreelec-config.sh`
- Create: `tests/test-helper.sh`
- Create: `tests/test-coreelec-config.sh`
- Modify: `provision-coreelec.sh:14-238`

**Interfaces:**
- Produces: `coreelec_config_defaults`, `coreelec_config_load FILE`, `coreelec_config_apply_cli NAME VALUE`, `coreelec_config_add_cli_addon ID`, and `coreelec_config_validate`.
- Produces globals used by later tasks: existing scalar names plus `CONFIG_FILE`, `TIMEZONE_COUNTRY`, `TIMEZONE`, `LOCALE_LANGUAGE`, `LOCALE_COUNTRY`, `KEYBOARD_LAYOUT`, `ADDON_UPDATE_MODE`, `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_WEATHER_ENTITY`, `HOME_ASSISTANT_SUN_ENTITY`, `NEXTPVR_HOST`, `NEXTPVR_PORT`, `NEXTPVR_PROTOCOL`, `NEXTPVR_INSTANCE_NAME`, `PLEX_SERVER_HOST`, `PLEX_SERVER_PORT`, `PLEX_SERVER_NAME`, `PLEX_PROFILE_IDS`, and indexed `ADDON_ARTIFACTS`.
- Consumes secret environment variables only during semantic validation; it does not copy their values into diagnostic strings.

- [ ] **Step 1: Write parser and precedence tests**

Create a test runner that executes named functions in subshells and provides
`assert_eq`, `assert_contains`, `assert_not_contains`, `assert_success`, and
`assert_failure`. Add cases proving:

```bash
test_defaults_are_pacific_english_us
test_comments_blank_lines_and_values_are_parsed
test_repeated_addon_artifacts_preserve_order
test_duplicate_scalar_key_is_rejected
test_unknown_key_is_rejected
test_malformed_line_is_rejected
test_shell_syntax_is_data_not_executed
test_secret_key_in_config_is_rejected
test_cli_value_overrides_config_value
test_target_is_not_loaded_from_shared_config
test_partial_youtube_credentials_are_rejected
test_service_secret_without_endpoint_is_rejected
test_missing_optional_secrets_are_allowed
```

The shell-syntax test must use a value such as
`REPORT_DIR=$(touch "$sentinel")`, verify the sentinel is absent, and verify
the literal value is retained or rejected without execution.

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
bash tests/test-coreelec-config.sh
```

Expected: FAIL because `lib/coreelec-config.sh` and its functions do not
exist.

- [ ] **Step 3: Implement the strict parser**

Implement Bash 3.2-compatible parsing without associative arrays:

```bash
coreelec_config_load() {
  local file="$1" line line_number=0 key value
  [[ -r "${file}" ]] || die "Configuration file is not readable: ${file}"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line_number=$((line_number + 1))
    case "${line}" in
      ''|[[:space:]]'#'*) continue ;;
      *=*) key="${line%%=*}"; value="${line#*=}" ;;
      *) die "${file}:${line_number}: expected KEY=value" ;;
    esac
    coreelec_config_assign "${file}" "${line_number}" "${key}" "${value}"
  done < "${file}"
}
```

Use an explicit `case` allowlist in `coreelec_config_assign`; never use
`eval`, `source`, indirect expansion, or generated variable names. Track seen
scalar keys in a newline-delimited string and permit repeats only for
`ADDON_ARTIFACT`. Reject these secret names if they occur in the file:

```text
OMDB_API_KEY
MDBLIST_API_KEY
YOUTUBE_API_KEY
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
HOME_ASSISTANT_TOKEN
NEXTPVR_PIN
PLEX_TOKEN
TMDB_API_KEY
```

Validate booleans as `0|1`, ports as decimal `1..65535`, IDs with the existing
identifier validation, URLs as `https://...`, timezone as a relative zoneinfo
path without `..`, and the three YouTube credentials as all-present or
all-absent. Reject `HOME_ASSISTANT_TOKEN`, `NEXTPVR_PIN`, or `PLEX_TOKEN` when
their required endpoint values are absent.

Parse `--config` in an initial lightweight CLI pass, load defaults and the
file, then perform the existing full CLI pass so explicit options win. Add
`--check-config` and `--check-artifacts`; neither requires `--target`.

- [ ] **Step 4: Run parser tests and syntax validation**

Run:

```bash
bash tests/test-coreelec-config.sh
bash -n provision-coreelec.sh lib/coreelec-config.sh tests/test-helper.sh tests/test-coreelec-config.sh
```

Expected: all tests pass and `bash -n` exits zero.

- [ ] **Step 5: Commit the parser**

```bash
git add provision-coreelec.sh lib/coreelec-config.sh tests/test-helper.sh tests/test-coreelec-config.sh
git commit -m "feat: add strict CoreELEC provisioning config"
```

---

### Task 2: Pinned Artifact Validation

**Files:**
- Create: `lib/coreelec-artifacts.sh`
- Create: `tests/test-coreelec-artifacts.sh`
- Modify: `provision-coreelec.sh:87-107`

**Interfaces:**
- Consumes: `ADDON_ARTIFACTS`, `TASK_TEMP_DIR`, `info`, and `die`.
- Produces: `coreelec_artifact_parse RECORD`, setting
  `ARTIFACT_ID`, `ARTIFACT_VERSION`, `ARTIFACT_URL`, and
  `ARTIFACT_SHA256`.
- Produces: `coreelec_artifacts_download_and_validate DESTINATION`, with
  validated ZIPs named by a stable numeric index and a generated
  `manifest.tsv` containing index, ID, version, and filename.

- [ ] **Step 1: Write artifact security tests**

Generate small fixture ZIPs inside the test temporary directory and add:

```bash
test_artifact_record_requires_four_fields
test_artifact_record_rejects_non_https_url
test_artifact_record_rejects_invalid_sha256
test_matching_checksum_id_and_version_pass
test_checksum_mismatch_fails
test_addon_id_mismatch_fails
test_addon_version_mismatch_fails
test_multiple_top_level_directories_fail
test_parent_traversal_entry_fails
test_absolute_path_entry_fails
test_duplicate_artifact_id_fails
```

Fixture `addon.xml` content must be minimal and valid:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<addon id="plugin.video.fixture" name="Fixture" version="1.2.3"
       provider-name="Tests">
  <extension point="xbmc.python.pluginsource" library="default.py"/>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">Fixture</summary>
    <platform>all</platform>
  </extension>
</addon>
```

- [ ] **Step 2: Run artifact tests and verify failure**

Run:

```bash
bash tests/test-coreelec-artifacts.sh
```

Expected: FAIL because artifact functions do not exist.

- [ ] **Step 3: Implement artifact validation**

Require `shasum`, `unzip`, and `xmllint`. Download with:

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  --retry 3 --retry-all-errors --connect-timeout 15 \
  --output "${zip_path}" "${ARTIFACT_URL}"
```

Compare `shasum -a 256` output case-insensitively. Use `unzip -Z1` to reject
empty names, absolute paths, backslashes, `.`/`..` segments, and more than one
top-level directory. Read only the discovered top-level `addon.xml` with
`unzip -p`, then
extract `/addon/@id` and `/addon/@version` with `xmllint --xpath 'string(...)'`.
Reject duplicate IDs and any metadata mismatch. Do not extract ZIPs locally.

- [ ] **Step 4: Run artifact tests and syntax validation**

Run:

```bash
bash tests/test-coreelec-artifacts.sh
bash -n lib/coreelec-artifacts.sh tests/test-coreelec-artifacts.sh
```

Expected: all tests pass.

- [ ] **Step 5: Commit artifact validation**

```bash
git add lib/coreelec-artifacts.sh tests/test-coreelec-artifacts.sh provision-coreelec.sh
git commit -m "feat: validate pinned Kodi add-on artifacts"
```

---

### Task 3: Shared Configuration and Locked Add-on Set

**Files:**
- Create: `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf`
- Modify: `tests/test-coreelec-config.sh`
- Modify: `tests/test-coreelec-artifacts.sh`

**Interfaces:**
- Consumes: the parser and artifact validator from Tasks 1 and 2.
- Produces: the default production configuration loaded by
  `provision-coreelec.sh`.

- [ ] **Step 1: Add a failing production-config test**

Add tests that load the production config and assert:

```text
EXPECTED_RELEASE=21.3
TIMEZONE_COUNTRY=United States
TIMEZONE=America/Los_Angeles
LOCALE_LANGUAGE=resource.language.en_us
LOCALE_COUNTRY=USA (12h)
KEYBOARD_LAYOUT=English QWERTY
ADDON_UPDATE_MODE=notify
```

Assert the artifact IDs include exactly one copy of every selected add-on,
repository, and transitive dependency. At minimum, assert these primary IDs
and versions:

```text
plugin.service.emby-next-gen=12.4.23
script.plexmod=1.14.1-beta1
plugin.video.youtube=7.4.4
skin.arctic.fuse.3=3.2.16
plugin.video.themoviedb.helper=6.17.1
pvr.nextpvr=21.3.2
weather.ha=0.0.6.6
resource.language.en_us=11.0.82
```

- [ ] **Step 2: Run the production-config test and verify failure**

Run:

```bash
bash tests/test-coreelec-config.sh
```

Expected: FAIL because the default config does not exist.

- [ ] **Step 3: Build and record the complete artifact lock**

Resolve the exact dependency closure from each pinned add-on's `addon.xml`,
using the official Kodi Omega mirror, CoreELEC 21 binary-add-on index, and
the Emby, Don't Panic, and Jurialmunkey repository indexes. For every selected
ZIP:

```bash
artifact_zip="$(mktemp "${TMPDIR:-/tmp}/coreelec-artifact.XXXXXX")"
curl --fail --location --proto '=https' --tlsv1.2 \
  -o "${artifact_zip}" "${artifact_url}"
shasum -a 256 "${artifact_zip}"
unzip -p "${artifact_zip}" '*/addon.xml' | xmllint --xpath \
  'concat(string(/addon/@id), " ", string(/addon/@version))' -
rm -f -- "${artifact_zip}"
```

For each selected artifact, assign `artifact_url` to the exact versioned URL
from its repository index before running the commands. Record each observed
ID, version, URL, and lowercase checksum as one `ADDON_ARTIFACT` line. Include
repository add-ons for Emby, Don't Panic, and Jurialmunkey, but do not
substitute repository-driven installation for the locked dependency closure.

- [ ] **Step 4: Validate the complete production config and downloads**

Run:

```bash
./provision-coreelec.sh --check-config
./provision-coreelec.sh --check-artifacts
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-artifacts.sh
```

Expected: config validation passes; every production artifact downloads and
passes checksum, ZIP safety, ID, and version validation.

- [ ] **Step 5: Commit the locked configuration**

```bash
git add config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf tests/test-coreelec-config.sh tests/test-coreelec-artifacts.sh
git commit -m "feat: lock CoreELEC baseline add-ons"
```

---

### Task 4: Idempotent Kodi and Add-on Settings Transformer

**Files:**
- Modify: `provision-coreelec.sh:487-584`
- Create: `tests/test-coreelec-settings.sh`

**Interfaces:**
- Consumes: validated non-secret config and optional secret environment
  variables.
- Produces: a mode-`0600` remote payload file and a Python transformer invoked
  while Kodi is stopped.
- Produces/updates:
  `/storage/.kodi/userdata/guisettings.xml`,
  `/storage/.cache/timezone`,
  `addon_data/plugin.video.youtube/settings.xml`,
  `addon_data/plugin.video.youtube/api_keys.json`,
  `addon_data/plugin.video.themoviedb.helper/settings.xml`,
  `addon_data/script.plexmod/settings.xml`,
  `addon_data/pvr.nextpvr/instance-settings-1.xml`, and
  `addon_data/weather.ha/settings.xml`.

- [ ] **Step 1: Extract and test the settings transformer**

Add a `--transform-fixture ROOT PAYLOAD` internal test mode that runs the same
Python transformer against a temporary directory instead of `/storage`.
Tests must prove:

```bash
test_regional_settings_are_created
test_duplicate_settings_are_collapsed
test_existing_unmanaged_settings_are_preserved
test_second_run_is_byte_identical
test_tmdb_helper_keys_go_to_tmdb_helper_only
test_youtube_credentials_require_all_three_values
test_youtube_api_keys_json_has_expected_shape
test_nextpvr_uses_instance_settings_format
test_home_assistant_weather_uses_flat_settings_format
test_weather_provider_changes_only_when_configured
test_pm4k_local_mode_json_is_valid
test_absent_optional_secrets_do_not_create_secret_settings
```

Use fixture roots containing representative pre-existing settings and compare
parsed XML/JSON values, not formatting alone.

- [ ] **Step 2: Run transformer tests and verify failure**

Run:

```bash
bash tests/test-coreelec-settings.sh
```

Expected: FAIL because the fixture transformer mode does not exist.

- [ ] **Step 3: Implement the transformer and payload**

Replace the three-line ad hoc payload with a mode-`0600` file whose values are
base64-encoded before transport. Decode only inside the remote Python process
so whitespace and JSON cannot corrupt parsing. Pass a separate presence flag
for each optional secret.

Implement typed helpers:

```python
set_kodi_setting(root, setting_id, value)
set_addon_setting(path, setting_id, value, version=2)
write_json_atomic(path, value)
write_text_atomic(path, value, mode=0o600)
```

The transformer must:

- preserve unmanaged XML nodes;
- remove duplicate managed settings;
- sort or update managed entries deterministically;
- use XML version 2 for standard add-on settings;
- use the old flat format for `weather.ha`;
- write NextPVR `instance-settings-1.xml` with
  `kodi_addon_instance_name` and `kodi_addon_instance_enabled`;
- put OMDb/MDbList values only in TMDb Helper;
- set YouTube `youtube.language=en-US`, `youtube.region=US`, and
  `kodion.setup_wizard=false`;
- set `lookandfeel.skin=skin.arctic.fuse.3`;
- set `weather.addon=weather.ha` only when HA Weather is fully configured;
- set PVR manager enabled only when NextPVR is fully configured; and
- atomically write `TIMEZONE=${TIMEZONE}` to the fixture/remote cache.

- [ ] **Step 4: Run transformer and existing tests**

Run:

```bash
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-config.sh
bash -n provision-coreelec.sh tests/test-coreelec-settings.sh
```

Expected: all tests and syntax checks pass.

- [ ] **Step 5: Commit settings transformation**

```bash
git add provision-coreelec.sh tests/test-coreelec-settings.sh
git commit -m "feat: configure Kodi regional and add-on settings"
```

---

### Task 5: Transactional Remote Add-on Deployment

**Files:**
- Modify: `provision-coreelec.sh:394-460`
- Modify: `provision-coreelec.sh:618-643`
- Modify: `provision-coreelec.sh:752-785`
- Modify: `tests/test-coreelec-artifacts.sh`

**Interfaces:**
- Consumes: validated local artifact directory and `manifest.tsv` from Task 2.
- Produces: `upload_artifact_bundle`, `deploy_artifacts_and_settings`, and
  `rollback_remote_deployment`.
- Produces remote backup metadata under a UTC timestamped
  `/storage/backup/coreelec-provision/YYYYmmddTHHMMSSZ/MANIFEST.txt` path.

- [ ] **Step 1: Add remote-script fixture tests**

Introduce an internal `--render-remote-deploy-script` mode and assert its
generated script:

```bash
test_remote_deploy_stops_kodi_after_staging_validation
test_remote_deploy_traps_kodi_restart
test_remote_deploy_backs_up_each_replaced_path
test_remote_deploy_extracts_into_staging_before_replace
test_remote_deploy_records_manifest
test_remote_deploy_has_rollback_for_replaced_paths
test_remote_deploy_rejects_manifest_path_injection
```

The tests inspect the rendered script and execute it against a temporary fake
storage root with stubbed `systemctl` and `unzip` commands.

- [ ] **Step 2: Run remote deployment tests and verify failure**

Run:

```bash
bash tests/test-coreelec-artifacts.sh
```

Expected: FAIL because remote rendering and deployment functions do not
exist.

- [ ] **Step 3: Implement upload, deployment, and rollback**

Stream a tar archive over the existing authenticated SSH connection rather
than adding `scp`:

```bash
tar -C "${validated_dir}" -cf - . |
  ssh_keyed 'umask 077; mkdir -p "$1"; tar -C "$1" -xf -' sh "${remote_stage}"
```

Quote fixed positional arguments and never interpolate IDs or paths into
remote shell source. Revalidate manifest IDs with the existing identifier
rules remotely. Expand each ZIP under remote staging, verify its top-level
directory matches its add-on ID, then:

1. stop Kodi and arm a restart trap;
2. copy affected add-on, add-on-data, `guisettings.xml`, and timezone paths
   into the dated backup;
3. move existing destinations into the transaction rollback area;
4. move staged add-on directories into `/storage/.kodi/addons`;
5. invoke the Task 4 settings transformer;
6. restart `tz-data.service`;
7. start Kodi and disarm only the emergency restart portion of the trap; and
8. retain rollback material until verification succeeds.

If deployment or verification fails, stop Kodi, remove newly deployed paths,
restore prior paths, restart timezone and Kodi services, and return nonzero.
If restoration fails, retain the backup/stage paths and print exact paths to
stderr.

- [ ] **Step 4: Replace modal installation and run tests**

Delete `install_requested_addons` and all use of `kodi-send
--action="InstallAddon(...)"`. Wire artifact validation before SSH mutation,
then deployment after the existing platform check and backup. Preserve
`--addon` only as a selection/filter for IDs already present in the locked
manifest; reject unknown IDs.

Run:

```bash
bash tests/test-coreelec-artifacts.sh
bash tests/test-coreelec-settings.sh
bash -n provision-coreelec.sh
```

Expected: all tests pass and no executable path contains `InstallAddon(` or
`EnableAddon(`.

- [ ] **Step 5: Commit remote deployment**

```bash
git add provision-coreelec.sh tests/test-coreelec-artifacts.sh
git commit -m "feat: deploy Kodi add-ons transactionally"
```

---

### Task 6: Remote Verification and Redacted Audit

**Files:**
- Modify: `provision-coreelec.sh:586-616`
- Modify: `provision-coreelec.sh:645-735`
- Create: `tests/test-coreelec-report.sh`

**Interfaces:**
- Consumes: requested config, deployed manifest, optional-secret presence
  flags, Kodi web credentials, and remote backup path.
- Produces: `verify_remote_baseline` with a nonzero result for state mismatch.
- Produces: `classify_addon_status ID` returning
  `configured`, `installed-manual`, or `installed-unconfigured`.
- Produces: a report containing no secret values.

- [ ] **Step 1: Write verification and report tests**

Add fixtures for JSON-RPC and remote inventory output. Test:

```bash
test_all_expected_addon_versions_are_verified
test_disabled_addon_is_failure
test_active_skin_is_verified
test_weather_provider_is_verified_only_when_configured
test_timezone_cache_and_zoneinfo_are_verified
test_english_us_values_are_verified
test_emby_and_youtube_are_classified_manual
test_configured_nextpvr_ha_and_pm4k_are_classified_configured
test_missing_optional_values_are_classified_unconfigured
test_report_lists_secret_presence_without_secret_values
test_report_redacts_all_supplied_secret_values
test_verification_mismatch_is_fatal
```

- [ ] **Step 2: Run report tests and verify failure**

Run:

```bash
bash tests/test-coreelec-report.sh
```

Expected: FAIL because the verification/classification helpers do not exist.

- [ ] **Step 3: Implement remote localhost JSON-RPC verification**

Create the Kodi curl config on the remote device with mode `0600`, call
`http://127.0.0.1:${KODI_PORT}/jsonrpc`, and remove it by trap. Batch JSON-RPC
requests for:

```text
JSONRPC.Version
Settings.GetSettingValue(locale.language)
Settings.GetSettingValue(locale.country)
Settings.GetSettingValue(locale.keyboardlayouts)
Settings.GetSettingValue(locale.timezonecountry)
Settings.GetSettingValue(locale.timezone)
Settings.GetSettingValue(lookandfeel.skin)
Settings.GetSettingValue(weather.addon)
Addons.GetAddonDetails for every selected artifact ID
```

Use `Addons.SetAddonEnabled` only for installed add-ons that are disabled,
then query again. Verify configured add-on files with a remote Python script
that prints only booleans and non-secret expected values. Never return tokens
or keys to the Mac.

- [ ] **Step 4: Implement report classification and redaction**

Write report lines for requested/observed ID and version, enabled state,
regional expected/observed values, active skin/provider, config fingerprint,
and optional-secret presence. Build manual actions deterministically:

- Emby server and user login;
- YouTube Google device authorization;
- Plex linking/local setup unless PM4K local mode is configured;
- NextPVR host/PIN unless configured;
- Home Assistant Weather URL/token/entity unless configured; and
- optional Trakt/TMDb-user authorization.

Before closing the report file, compare it against every non-empty secret and
fail while deleting the report if any literal secret occurs.

- [ ] **Step 5: Run all local tests**

Run:

```bash
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-artifacts.sh
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-report.sh
bash -n provision-coreelec.sh lib/coreelec-config.sh lib/coreelec-artifacts.sh tests/*.sh
```

Expected: all tests and syntax checks pass.

- [ ] **Step 6: Commit verification and reporting**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "feat: verify and report CoreELEC baseline"
```

---

### Task 7: Documentation and Operator Workflow

**Files:**
- Modify: `config/README.md`
- Modify: `docs/runbook.md`
- Modify: `docs/devices/ugoos-am6b-plus/coreelec-21.3.md`
- Modify: `provision-coreelec.sh:33-67`

**Interfaces:**
- Consumes: final CLI, config keys, secret environment variables, status
  classifications, and manual actions from Tasks 1-6.
- Produces: an operator workflow that distinguishes shared automation from
  room-specific work.

- [ ] **Step 1: Update CLI help and configuration documentation**

Document:

```bash
./provision-coreelec.sh --check-config
./provision-coreelec.sh --check-artifacts
./provision-coreelec.sh --target coreelec-theater
./provision-coreelec.sh --config /path/to/device.conf --target 172.16.99.50
```

List every supported scalar key, repeated artifact grammar, precedence rule,
and secret environment variable. Include a safe example that exports only
placeholder names, never usable credentials. Explain that the config parser
does not support quoting, expansion, command substitution, or shell arrays.

- [ ] **Step 2: Update the shared runbook and device guide**

Place provisioning after first-boot wired networking/SSH and before
room-specific playback configuration. Document:

- validation-only commands;
- backup and rollback locations;
- expected interactive password prompt on first key installation;
- audit report review;
- Emby and YouTube manual authorization;
- optional PM4K, NextPVR, HA Weather, and TMDb Helper configuration;
- Arctic Fuse 3 activation;
- regional verification; and
- restoration/retry procedure after a failed run.

Retain the existing requirement that room-specific video/audio settings and
hardware validation happen separately.

- [ ] **Step 3: Check documentation consistency**

Run:

```bash
grep -R "InstallAddon\\|with-youtube\\|no deployment automation" \
  README.md config docs rooms provision-coreelec.sh
git --no-pager diff --check
```

Expected: any stale prose is either removed or explicitly describes behavior
that remains true; `git diff --check` exits zero.

- [ ] **Step 4: Commit documentation**

```bash
git add provision-coreelec.sh config/README.md docs/runbook.md docs/devices/ugoos-am6b-plus/coreelec-21.3.md
git commit -m "docs: add CoreELEC provisioning workflow"
```

---

### Task 8: Live CoreELEC 21.3 Acceptance Test

**Files:**
- Modify if defects are found: files from Tasks 1-7 that own the defect.
- Do not commit: generated audit reports or any credential-bearing temporary
  files.

**Interfaces:**
- Consumes: the available disposable target at `root@coreelec-theater`.
- Produces: a successful audit report and documented manual-action list.

- [ ] **Step 1: Run preflight without the target**

Run:

```bash
./provision-coreelec.sh --check-config
./provision-coreelec.sh --check-artifacts
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-artifacts.sh
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-report.sh
bash -n provision-coreelec.sh lib/coreelec-config.sh lib/coreelec-artifacts.sh tests/*.sh
```

Expected: every command exits zero.

- [ ] **Step 2: Record pristine target observations**

Use interactive SSH so the temporary/default password is never placed in a
command or process argument:

```bash
ssh root@coreelec-theater
```

Record CoreELEC release, model, current timezone, Kodi service state, and
existing add-on directories in the session output. Do not save the password
or other credentials in repository files.

- [ ] **Step 3: Run provisioning without optional service secrets**

Run:

```bash
./provision-coreelec.sh --target coreelec-theater
```

Enter the SSH password only at the interactive prompt. Expected:

- platform validation succeeds;
- the administrator key is installed before password authentication is
  disabled;
- all artifacts install at pinned versions;
- Arctic Fuse 3 becomes active;
- Pacific timezone and English/US settings verify;
- Kodi and SSH remain active; and
- the report lists Emby, YouTube, PM4K, NextPVR, HA Weather, and optional TMDb
  account work without exposing secrets.

- [ ] **Step 4: Verify idempotency**

Run the same command a second time:

```bash
./provision-coreelec.sh --target coreelec-theater --yes
```

Expected: no duplicate XML settings or PVR instances, matching add-on
versions are not replaced, verification succeeds, and a new audit report
records an idempotent run.

- [ ] **Step 5: Exercise supplied-secret paths with disposable credentials**

Only when disposable/non-production test credentials are available, export
them in the current interactive shell and run provisioning. Otherwise run
the transformer fixture tests as the acceptance evidence for these paths.
After the run:

```bash
unset OMDB_API_KEY MDBLIST_API_KEY YOUTUBE_API_KEY YOUTUBE_CLIENT_ID
unset YOUTUBE_CLIENT_SECRET HOME_ASSISTANT_TOKEN NEXTPVR_PIN PLEX_TOKEN
```

Expected: configured statuses match supplied values and no audit report
contains a literal secret.

- [ ] **Step 6: Inspect rollback and recovery**

Confirm the dated backup contains pre-run `guisettings.xml`, timezone state,
and every replaced add-on/add-on-data path. Trigger a safe pre-deployment
failure with a copied config containing one deliberately wrong checksum and
run `--check-artifacts`; expected behavior is failure before SSH mutation.
Do not deliberately corrupt the live Kodi installation merely to test
rollback.

- [ ] **Step 7: Fix live-only defects with focused regression tests**

For each defect, first add a local fixture reproducing it to the owning test
file, verify that test fails, make the smallest correction, and rerun all
local tests plus the affected live verification. Commit each coherent fix:

```bash
git add provision-coreelec.sh lib/coreelec-config.sh lib/coreelec-artifacts.sh
git add tests/test-coreelec-config.sh tests/test-coreelec-artifacts.sh
git add tests/test-coreelec-settings.sh tests/test-coreelec-report.sh
git commit -m "fix: correct CoreELEC provisioning behavior"
```

- [ ] **Step 8: Run final verification**

Run:

```bash
./provision-coreelec.sh --check-config
./provision-coreelec.sh --check-artifacts
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-artifacts.sh
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-report.sh
bash -n provision-coreelec.sh lib/coreelec-config.sh lib/coreelec-artifacts.sh tests/*.sh
git --no-pager diff --check
git --no-pager status --short
```

Expected: all validation passes; status contains only intentional source/docs
changes and ignored/generated reports; the latest live audit report records a
fully verified baseline plus explicit manual actions.

- [ ] **Step 9: Commit acceptance-driven corrections**

If Task 8 produced source or documentation corrections not already committed:

```bash
git add provision-coreelec.sh lib/coreelec-config.sh lib/coreelec-artifacts.sh
git add tests config/shared docs/runbook.md
git add docs/devices/ugoos-am6b-plus/coreelec-21.3.md
git commit -m "fix: validate CoreELEC provisioning on device"
```

Do not add audit reports, downloaded ZIPs, temporary configs, or secrets.
