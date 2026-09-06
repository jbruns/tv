# CoreELEC Post-Deployment Add-on Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Minimize TV-remote work after CoreELEC provisioning by validating declarative add-on configuration and launching or assisting the remaining account authorization workflows from the Mac.

**Architecture:** Keep the existing install/settings transaction in `provision-coreelec.sh` unchanged and add a separate `configure-coreelec-addons.sh` post-deployment command. The new command will use SSH to call Kodi's authenticated localhost JSON-RPC endpoint, classify each add-on by interaction level, run supported service checks directly, and use guarded GUI automation only for account flows that cannot be configured declaratively.

**Tech Stack:** Bash 3.2-compatible shell, OpenSSH, CoreELEC Python 3 and `curl`, Kodi 21.2 JSON-RPC 13.5, add-on XML/JSON state, Emby REST API, Plex PIN linking, Google OAuth device authorization.

**Spec:** `docs/superpowers/specs/2026-09-05-coreelec-provisioning-design.md`

## Global Constraints

- Target CoreELEC `21.3` on Amlogic-ng and Kodi `21.2`/JSON-RPC `13.5`.
- Do not extend the existing deployment transaction across human authorization; the transaction must still finalize or roll back before post-deployment configuration starts.
- Keep declarative settings in `provision-coreelec.sh`; do not duplicate its settings transformer in the post-deployment script.
- Use Kodi JSON-RPC through SSH against `127.0.0.1`; do not broaden the Kodi web server's LAN exposure.
- Discover the live JSON-RPC schema with `JSONRPC.Introspect` before attempting GUI automation.
- Secrets come only from environment variables or an interactive no-echo prompt and never appear in config, process arguments, logs, reports, or JSON-RPC request IDs.
- Use `Addons.ExecuteAddon`, `GUI.ActivateWindow`, `GUI.GetProperties`, `Input.ExecuteAction`, and `Input.SendText` only when the live schema confirms them.
- Every GUI step must assert the expected window and focused-control label before sending input; fail closed on an unexpected state.
- Never scrape secrets or authorization codes from screenshots, logs, or Kodi's VFS endpoint.
- Version-gate private add-on routes and state formats to the versions pinned in `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf`.
- Preserve an explicit `manual-required` outcome whenever a supported API cannot safely complete a step.
- Preserve unrelated worktree changes; stage and commit only files named by each task.

## Research Findings

### Kodi Web and JSON-RPC

- Kodi's web server exposes JSON-RPC at `/jsonrpc`; Chorus is a web client over the same control surfaces, not a richer add-on configuration API.
- Kodi 21 exposes `Addons.ExecuteAddon`, `GUI.ActivateWindow`, `GUI.GetProperties`, `Input.ExecuteAction`, and `Input.SendText`. `Input.SendText` can close an open input dialog with `done=true`.
- `GUI.GetProperties` reports `currentwindow` with ID/label and `currentcontrol` with a label. It does not expose arbitrary dialog contents or the device code rendered inside an add-on window.
- JSON-RPC therefore supports guarded navigation and text injection, but it cannot reliably discover an unknown form or extract a Plex/Google device code for display on the Mac.
- The target's own `JSONRPC.Introspect` response is authoritative and should be captured in a redacted capability report before a workflow runs.

### Add-on Capability Matrix

| Add-on | Current state | Additional feasible automation | Recommended level |
| --- | --- | --- | --- |
| Home Assistant Weather `0.0.6.6` | `provision-coreelec.sh` already writes URL, token, weather entity, sun entity, and selects the provider | Call the Home Assistant REST API from the device and execute the weather add-on once to prove the token/entity work | Fully unattended |
| NextPVR `21.3.2.1` | The provisioner already writes host, protocol, port, PIN, name, and enables instance 1 | Validate the backend handshake and confirm Kodi exposes PVR channel groups after restart | Fully unattended |
| PM4K `1.14.1-beta1` local mode | The provisioner already writes `local_servers_json`, `local_profiles_json`, `local_mode`, and `allow_insecure` | Probe `/identity` and authenticated server root, then launch PM4K | Fully unattended when `PLEX_TOKEN` is supplied |
| PM4K account mode | PM4K creates and polls a Plex PIN internally and displays it in a custom Kodi window | Launch PM4K and select Sign In after checking the expected control; the operator completes `plex.tv/link` on another device | Guided; no TV typing |
| YouTube `7.4.4` | API credentials are seeded, but account tokens are not | Open `plugin://plugin.video.youtube/sign/in/`, dismiss the introductory dialog after checking it, and let the add-on own Google's device-code polling and token storage | Guided; no TV typing, but Google may present multiple codes |
| Emby Next Gen `12.4.23` | The service opens custom first-run dialogs and stores credentials in `servers_<server-id>.json` | Guardedly enter server URL, user, and password through Kodi input dialogs; separately evaluate direct state seeding against the pinned schema | Guided first; direct seeding experimental |

### Why Emby Direct Seeding Is Not Phase 1

Emby exposes a supported `Users/AuthenticateByName` API and the add-on's pinned source shows the resulting token in `ServerData`. However, the add-on also creates a device ID, discovers server addresses, performs a handshake, sets `WizardCompleted`, creates `servers_<server-id>.json`, and initializes `emby_<server-id>.db`. Writing only a token would bypass lifecycle logic and could leave a success-shaped but unusable installation. The first implementation should drive the add-on's own workflow; direct seeding should proceed only after a disposable-device test proves the complete minimum state and restart behavior.

## File Structure

- Create `configure-coreelec-addons.sh`: post-deployment CLI, orchestration, status reporting, and add-on workflow dispatch.
- Create `lib/coreelec-addon-workflows.sh`: pure workflow definitions, expected GUI states, version gates, and status classification.
- Create `tests/test-coreelec-addon-workflows.sh`: fixture-driven tests for capability parsing, state guards, workflow decisions, redaction, and reports.
- Modify `lib/coreelec-config.sh`: add only the new non-secret Emby endpoint/user/transport keys and validate their secret companions.
- Modify `tests/test-coreelec-config.sh`: cover the new keys and secret-pairing rules.
- Modify `provision-coreelec.sh`: add `EMBY_PASSWORD` to audit redaction and help text because it shares the configuration library; do not add interactive orchestration.
- Modify `config/README.md`: document post-deployment keys, secrets, and the separation from baseline deployment.
- Modify `docs/runbook.md`: replace generic manual steps with commands and expected post-deployment statuses.

---

### Task 1: Post-Deployment CLI and Fail-Closed JSON-RPC Driver

**Files:**
- Create: `configure-coreelec-addons.sh`
- Create: `lib/coreelec-addon-workflows.sh`
- Create: `tests/test-coreelec-addon-workflows.sh`

**Interfaces:**
- Consumes: `coreelec_config_defaults`, `coreelec_config_load FILE`, and `coreelec_config_validate` from `lib/coreelec-config.sh`.
- Produces: `kodi_rpc METHOD PARAMS_JSON`, `kodi_capabilities`, `kodi_gui_state`, `require_gui_state WINDOW_LABEL CONTROL_LABEL`, and `run_addon_workflow ADDON_ID`.
- Produces statuses: `already-configured`, `configured`, `authorization-required`, `manual-required`, `skipped`, and `failed`.

- [ ] **Step 1: Write failing CLI, capability, and redaction tests**

Add fixture tests named:

```bash
test_help_lists_supported_addons_and_interaction_levels
test_default_run_never_starts_account_authorization
test_requested_addon_must_be_in_the_pinned_manifest
test_introspection_rejects_a_missing_required_method
test_gui_guard_accepts_expected_window_and_control
test_gui_guard_rejects_an_unexpected_window_without_sending_input
test_rpc_request_ids_never_contain_secret_values
test_report_contains_statuses_but_no_secret_values
```

Stub SSH with a fixture executable that records stdin separately from argv and returns saved JSON-RPC responses.

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
bash tests/test-coreelec-addon-workflows.sh
```

Expected: FAIL because the post-deployment script and workflow library do not exist.

- [ ] **Step 3: Implement the CLI and transport**

Support:

```text
configure-coreelec-addons.sh --target HOST [--config PATH]
  [--addon ID ...] [--interactive] [--dry-run] [--report-dir PATH]
```

The default run performs non-interactive checks only. `--interactive` is required before PM4K account, YouTube, or Emby GUI actions. Send JSON-RPC bodies on SSH stdin to a remote `curl --config` invocation against `http://127.0.0.1:<port>/jsonrpc`; create and remove the remote mode-0600 curl config with traps.

- [ ] **Step 4: Implement capability and GUI guards**

Call:

```json
{"jsonrpc":"2.0","id":"introspect","method":"JSONRPC.Introspect","params":{"getdescriptions":false,"getmetadata":false}}
```

Before every UI action, call:

```json
{"jsonrpc":"2.0","id":"gui-state","method":"GUI.GetProperties","params":{"properties":["currentwindow","currentcontrol"]}}
```

Compare labels exactly after normalizing only surrounding whitespace. On mismatch, report `manual-required`; do not guess, loop navigation, or send text.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
bash tests/test-coreelec-addon-workflows.sh
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-report.sh
```

Expected: all tests PASS.

Commit:

```bash
git add configure-coreelec-addons.sh lib/coreelec-addon-workflows.sh tests/test-coreelec-addon-workflows.sh
git commit -m "feat: add post-deployment addon workflow driver"
```

### Task 2: Unattended Service Validation

**Files:**
- Modify: `lib/coreelec-addon-workflows.sh`
- Modify: `tests/test-coreelec-addon-workflows.sh`
- Modify: `docs/runbook.md`

**Interfaces:**
- Produces: `check_home_assistant_weather`, `check_nextpvr`, and `check_pm4k_local`.
- Each function returns one defined status and emits only redacted `key=value` observations.

- [ ] **Step 1: Write failing service-check tests**

Add:

```bash
test_weather_check_accepts_config_and_entity_responses
test_weather_check_reports_unauthorized_without_echoing_token
test_nextpvr_check_uses_the_configured_protocol_host_port_and_pin
test_nextpvr_check_requires_a_successful_session_login
test_pm4k_local_check_requires_identity_and_token_authorized_root
test_service_checks_do_not_modify_addon_settings
```

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
bash tests/test-coreelec-addon-workflows.sh
```

Expected: FAIL on the first missing service-check function.

- [ ] **Step 3: Implement checks in dependency order**

1. Home Assistant: request `/api/config` and `/api/states/<weather-entity>` with `Authorization: Bearer <token>`, then execute `weather.ha` once through `Addons.ExecuteAddon`.
2. NextPVR: perform `session.initiate`, calculate the same lower-case MD5 combination used by pinned `pvr.nextpvr`, complete `session.login`, and require a success response; then call `PVR.GetChannelGroups` as an advisory Kodi-side observation.
3. PM4K local: require HTTP 200 from `/identity`, then require the configured token to receive HTTP 200 from `/`; launch `script.plexmod` only when the checks pass.

Treat transport failures, 401/403, malformed payloads, and identity mismatches as distinct failures. Do not rewrite settings in this phase.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
bash tests/test-coreelec-addon-workflows.sh
```

Expected: all tests PASS.

Commit:

```bash
git add lib/coreelec-addon-workflows.sh tests/test-coreelec-addon-workflows.sh docs/runbook.md
git commit -m "feat: validate configured CoreELEC addon services"
```

### Task 3: Guided PM4K and YouTube Authorization

**Files:**
- Modify: `lib/coreelec-addon-workflows.sh`
- Modify: `tests/test-coreelec-addon-workflows.sh`
- Modify: `docs/runbook.md`

**Interfaces:**
- Produces: `authorize_pm4k_account` and `authorize_youtube`.
- Consumes the fail-closed JSON-RPC and GUI-state interfaces from Task 1.

- [ ] **Step 1: Write failing guided-flow tests**

Add:

```bash
test_pm4k_launch_uses_addons_executeaddon
test_pm4k_selects_sign_in_only_when_expected_control_is_focused
test_youtube_launch_uses_the_pinned_sign_in_plugin_route
test_youtube_dismisses_only_the_expected_intro_dialog
test_guided_flow_times_out_as_manual_required
test_guided_flow_detects_persisted_tokens_without_printing_them
```

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
bash tests/test-coreelec-addon-workflows.sh
```

Expected: FAIL on the first missing guided-flow function.

- [ ] **Step 3: Implement PM4K account launch**

Execute `script.plexmod`, wait with a fixed deadline, and inspect `currentwindow`/`currentcontrol`. Send `Input.Select` only when the English-US label matches the pinned PM4K Sign In control. Tell the operator to complete the displayed code at `https://plex.tv/link`; poll only for PM4K's persisted non-empty account token presence and report the boolean result.

- [ ] **Step 4: Implement YouTube sign-in launch**

Activate:

```text
plugin://plugin.video.youtube/sign/in/
```

through `GUI.ActivateWindow` using the video window. Dismiss the pinned add-on's introductory OK dialog only after its label matches. Leave device-code creation, polling cadence, token exchange, refresh-token storage, and error handling inside the YouTube add-on. Report that more than one Google code may be requested by version `7.4.4`.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
bash tests/test-coreelec-addon-workflows.sh
```

Expected: all tests PASS.

Commit:

```bash
git add lib/coreelec-addon-workflows.sh tests/test-coreelec-addon-workflows.sh docs/runbook.md
git commit -m "feat: guide PM4K and YouTube authorization"
```

### Task 4: Guarded Emby First-Run Assistance

**Files:**
- Modify: `lib/coreelec-config.sh`
- Modify: `provision-coreelec.sh`
- Modify: `configure-coreelec-addons.sh`
- Modify: `lib/coreelec-addon-workflows.sh`
- Modify: `tests/test-coreelec-config.sh`
- Modify: `tests/test-coreelec-addon-workflows.sh`

**Interfaces:**
- Adds non-secret keys: `EMBY_SERVER_URL`, `EMBY_USERNAME`, and `EMBY_ALLOW_LOCAL_HTTP`.
- Adds secret environment variable: `EMBY_PASSWORD`.
- Produces: `assist_emby_login`.

- [ ] **Step 1: Write failing configuration and secret-safety tests**

Add:

```bash
test_emby_url_requires_https_unless_local_http_is_explicitly_allowed
test_emby_password_requires_server_and_username
test_emby_password_is_rejected_in_config
test_emby_password_never_appears_in_argv_log_or_report
test_emby_assistant_stops_on_each_unexpected_dialog
```

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-addon-workflows.sh
```

Expected: FAIL because the Emby keys and assistant do not exist.

- [ ] **Step 3: Add validated Emby inputs**

Accept `EMBY_SERVER_URL` and `EMBY_USERNAME` from the strict config file. Accept `EMBY_PASSWORD` only from the environment or a no-echo interactive prompt. Permit plain HTTP only for an RFC1918/loopback host behind an explicit `EMBY_ALLOW_LOCAL_HTTP=1` setting; otherwise require HTTPS.

- [ ] **Step 4: Implement the guarded dialog workflow**

Require pinned Emby `12.4.23`, English-US locale, and the known first-run window/control labels. Send the manual server URL, username, and password with `Input.SendText` only after each matching input dialog appears. After submission, require:

```text
servers_<server-id>.json exists
AccessToken is non-empty
UserId is non-empty
ServerId matches /System/Info
emby_<server-id>.db exists after the add-on handshake
```

Return `manual-required` on server selection ambiguity, multiple public users, password retry, certificate error, database-resync prompt, or any unknown control.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-addon-workflows.sh
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-report.sh
```

Expected: all tests PASS.

Commit:

```bash
git add lib/coreelec-config.sh provision-coreelec.sh configure-coreelec-addons.sh lib/coreelec-addon-workflows.sh tests/test-coreelec-config.sh tests/test-coreelec-addon-workflows.sh
git commit -m "feat: assist Emby first-run authentication"
```

### Task 5: Version-Gated Emby Direct-Seeding Experiment

**Files:**
- Modify: `configure-coreelec-addons.sh`
- Modify: `lib/coreelec-addon-workflows.sh`
- Modify: `tests/test-coreelec-addon-workflows.sh`
- Modify: `docs/runbook.md`

**Interfaces:**
- Produces experimental command: `--emby-seed-state`.
- The command is unavailable unless the installed add-on is exactly `12.4.23`.

- [ ] **Step 1: Write failing fixture tests for complete state construction**

Use sanitized `/System/Info`, `/Users/AuthenticateByName`, and generated `servers_<id>.json` fixtures. Add:

```bash
test_emby_seed_builds_every_serverdata_field_used_at_startup
test_emby_seed_preserves_a_stable_device_id
test_emby_seed_sets_wizard_completed
test_emby_seed_refuses_an_unknown_addon_version
test_emby_seed_rolls_back_when_handshake_or_database_creation_fails
```

- [ ] **Step 2: Validate on a disposable CoreELEC profile before implementation**

Run the pinned add-on once manually, capture a redacted field-name-only inventory of `servers_<id>.json`, and compare it with the source-defined `ServerData` keys. Restart Kodi twice and verify reconnection and database creation. If either restart needs a dialog or the minimum state cannot be derived without copying opaque add-on data, mark this task rejected and retain Task 4 as the supported path.

- [ ] **Step 3: Implement only if the device validation passes**

Authenticate through Emby's supported `/Users/AuthenticateByName`, obtain server identity from `/System/Info`, construct the full pinned `ServerData` document, set `WizardCompleted`, and install the state while Kodi is stopped. Back up both the settings file and all `servers_*.json`; restart Kodi and require successful handshake plus `emby_<server-id>.db` creation before releasing rollback material.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
bash tests/test-coreelec-addon-workflows.sh
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-report.sh
```

Expected: all tests PASS, or Task 5 is explicitly recorded as rejected after Step 2 with no direct-seeding code retained.

Commit, only if implemented:

```bash
git add configure-coreelec-addons.sh lib/coreelec-addon-workflows.sh tests/test-coreelec-addon-workflows.sh docs/runbook.md
git commit -m "feat: seed pinned Emby connection state"
```

### Task 6: End-to-End Device Acceptance and Documentation

**Files:**
- Modify: `config/README.md`
- Modify: `docs/runbook.md`
- Modify: `docs/devices/ugoos-am6b-plus/coreelec-21.3.md`

**Interfaces:**
- Consumes all statuses and commands from Tasks 1-5.
- Produces the supported operator workflow and acceptance record.

- [ ] **Step 1: Document the two-phase workflow**

Document:

```bash
./provision-coreelec.sh --target <host>
./configure-coreelec-addons.sh --target <host>
./configure-coreelec-addons.sh --target <host> --interactive \
  --addon script.plexmod \
  --addon plugin.video.youtube \
  --addon plugin.service.emby-next-gen
```

State clearly that the first command is transactional and unattended, while the second command may wait for authorization on another browser but never rolls back a valid baseline.

- [ ] **Step 2: Run the local regression suite**

Run:

```bash
bash tests/test-coreelec-config.sh
bash tests/test-coreelec-artifacts.sh
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-report.sh
bash tests/test-coreelec-addon-workflows.sh
```

Expected: all tests PASS.

- [ ] **Step 3: Run acceptance checks on one disposable target**

Verify in order:

```text
Home Assistant Weather: configured and forecast request succeeds
NextPVR: configured, session login succeeds, and channel groups are visible
PM4K local mode: configured and the selected server opens
PM4K account mode: workflow opens and links without TV text entry
YouTube: sign-in route opens and authorization persists after Kodi restart
Emby: URL/user/password are entered without a TV remote and reconnection survives two restarts
```

Inspect the generated report and process list while each secret-bearing operation runs. Fail acceptance if any secret is present.

- [ ] **Step 4: Commit documentation**

```bash
git add config/README.md docs/runbook.md docs/devices/ugoos-am6b-plus/coreelec-21.3.md
git commit -m "docs: add post-deployment addon configuration workflow"
```

## Primary References

- Kodi JSON-RPC API 13.5: <https://kodi.wiki/view/JSON-RPC_API/v13.5>
- Kodi web server: <https://kodi.wiki/view/Webserver>
- Kodi 21.2 JSON-RPC schema: <https://github.com/xbmc/xbmc/tree/21.2-Omega/xbmc/interfaces/json-rpc/schema>
- Emby user authentication: <https://dev.emby.media/doc/restapi/User-Authentication.html>
- Emby Next Gen source: <https://github.com/MediaBrowser/plugin.video.emby>
- PM4K source at the pinned revision: <https://github.com/pannal/plex-for-kodi/tree/2707bbe72a7ea829b69bdd7ebb753c700552b4d0>
- Google limited-input OAuth: <https://developers.google.com/youtube/v3/guides/auth/devices>
- YouTube add-on source: <https://github.com/anxdpanic/plugin.video.youtube>
- NextPVR client source: <https://github.com/kodi-pvr/pvr.nextpvr>
- Home Assistant REST API: <https://developers.home-assistant.io/docs/api/rest/>
- Home Assistant Weather `0.0.6.6`: <https://github.com/Eugeniusz-Gienek/kodi_weather_ha/tree/0.0.6.6>
