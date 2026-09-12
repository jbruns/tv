# Ugoos Kodi lifecycle Home Assistant operations

This guide deploys the reviewed always-awake CoreELEC/Ethernet/SSH lifecycle for the theater Ugoos and Sony pair, then records the checks needed before rolling the pattern to other rooms. CoreELEC stays awake; Home Assistant owns Sony idle power-off and Kodi start/stop; Wake-on-LAN is outside the normal lifecycle path.

## Operator sequence

Use this order for each managed room:

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

The concrete theater package currently targets:

| Value | Exact ID/path |
|---|---|
| Sony entity | `media_player.sony_xr_65a90j` |
| Kodi entity | `media_player.kodi_theater` |
| Ugoos lifecycle host | `ugoos-theater` via SSH alias `ugoos-theater-lifecycle` |
| HA private key path | `/config/.ssh/ugoos_kodi_lifecycle_ed25519` |
| HA known-hosts path | `/config/.ssh/known_hosts` |
| HA SSH config path | `/config/.ssh/ugoos-kodi-lifecycle.conf` |
| Package file | `/config/packages/ugoos_theater_kodi_lifecycle.yaml` |
| Keep-running helper | `input_boolean.ugoos_theater_keep_kodi_running` |
| Idle timeout helper | `input_number.ugoos_theater_idle_timeout_minutes` |
| Lifecycle state helper | `input_text.ugoos_theater_kodi_lifecycle_state` |
| Last command helper | `input_text.ugoos_theater_last_lifecycle_command` |
| Last verified reconciliation | `input_datetime.ugoos_theater_last_reconciliation` |
| Last status observation (not convergence) | `input_datetime.ugoos_theater_last_status_observation` |
| Fresh observation epoch | `input_datetime.ugoos_theater_observation_started` |
| Observation initialized | `input_boolean.ugoos_theater_observation_ready` |
| Unresolved error summary | `input_text.ugoos_theater_last_lifecycle_error` |
| Per-operation errors | `input_text.ugoos_theater_{status,start,stop,idle_probe,idle_poweroff,configuration}_error` (six helpers) |
| Reconciler script | `script.ugoos_theater_reconcile_kodi` |
| Idle Sony script | `script.ugoos_theater_power_off_idle_sony` |
| Restricted commands | `shell_command.ugoos_theater_kodi_start`, `shell_command.ugoos_theater_kodi_stop`, `shell_command.ugoos_theater_kodi_status` |

## 1. Confirm the CoreELEC baseline

Run shared baseline provisioning first:

```bash
./provision-coreelec.sh --target ugoos-theater
```

Review the generated file under `coreelec-provision-reports/`. The authoritative matching report fields are:

```text
cec.tv_off_action.expected=36028
cec.tv_off_action.observed=36028
cec.tv_off_action.status=ok
```

The report uses `ok` for a match and `mismatch` for a failing comparison.
Kodi peripheral XML must contain a direct child
`<setting id="standby_pc_on_tv_standby" value="36028" />`.
Unlike `guisettings.xml`, Kodi does **not** read element text here. The
provisioner repairs earlier text-only settings and refuses to certify
text-only, nested, empty, or duplicate observed values.

## 2. Create the Home Assistant controller identity

In Home Assistant's Terminal & SSH app, create a dedicated unattended
controller key. Do not overwrite an existing controller identity:

```bash
mkdir -p /config/.ssh
chmod 700 /config/.ssh
ssh-keygen -t ed25519 -N '' \
  -f /config/.ssh/ugoos_kodi_lifecycle_ed25519 \
  -C homeassistant-ugoos-kodi-lifecycle
chmod 600 /config/.ssh/ugoos_kodi_lifecycle_ed25519
```

Keep both controller key files out of this repository. The private key stays on Home Assistant except for the brief deployment option below.

### Authenticate the Ugoos server key before trusting it

`ssh-keyscan` discovers keys; it does **not** authenticate the server.
[OpenSSH explicitly warns](https://man.openbsd.org/ssh-keyscan) that trusting
unverified scan output permits a man-in-the-middle attack. Strict checking
afterward cannot repair an unauthenticated first connection.

Obtain the Ugoos **server** Ed25519 fingerprint through its local console,
an independently verified asset record, or an already fingerprint-verified
administrator connection. On that trusted CoreELEC channel:

```bash
ssh-keygen -l -E sha256 -f /storage/.cache/ssh/ssh_host_ed25519_key.pub
```

Do not confuse this with the Home Assistant controller-key fingerprint.
If no independent trust channel is available, stop here; do not install
the controller authorization or accept an unknown host key.

On Home Assistant, replace the placeholder below with that independently
authenticated fingerprint. Only a matching candidate may enter `known_hosts`:

```bash
expected='SHA256:REPLACE_WITH_INDEPENDENTLY_VERIFIED_SERVER_FINGERPRINT'
ssh-keyscan -T 5 -t ed25519 -H ugoos-theater > /config/.ssh/ugoos-theater.candidate
observed="$(ssh-keygen -l -E sha256 -f /config/.ssh/ugoos-theater.candidate | awk '{print $2}' | sort -u)"
if [ "${observed}" = "${expected}" ] && [ -n "${observed}" ]; then
  cat /config/.ssh/ugoos-theater.candidate >> /config/.ssh/known_hosts
  chmod 600 /config/.ssh/known_hosts
  printf 'Verified server host key installed\n'
else
  printf 'REFUSED: independently verified host fingerprint did not match\n' >&2
fi
rm -f /config/.ssh/ugoos-theater.candidate
```

Proceed only after the comparison succeeds. Alternatively, install an
already authenticated `known_hosts` entry through a trusted transfer.
Before gateway deployment, install the same authenticated host entry in
the deploying user's `$HOME/.ssh/known_hosts`, for the exact hostname or
address passed to `--target`. The CLI uses that default file for controller
verification; it does not offer a known-hosts-path override. With a nondefault
SSH port, use the matching `[host]:port` entry and `ssh-keyscan -p PORT`.
Investigate mismatches; do not delete an old trusted entry just to make a
connection succeed.

## 3. Deploy the restricted lifecycle gateway

Either securely make the controller identity available to the Mac only for gateway deployment, or run the repository deployment command from a trusted checkout that can read both controller key files:

```bash
./configure-kodi-lifecycle.sh \
  --target ugoos-theater \
  --controller-public-key "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519.pub" \
  --controller-identity "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519"
```

Neither file belongs in the repository. If you temporarily copy the Home Assistant private key or public key to the Mac, remove the temporary copy immediately after deployment. The command installs `/storage/.config/kodi-lifecycle`, replaces only the uniquely marked `homeassistant-ugoos-kodi-lifecycle` entry in `/storage/.ssh/authorized_keys`, verifies restricted `status`, `start`, `stop`, and arbitrary-command denial, restores the original Kodi state, and writes a redacted report under `coreelec-lifecycle-reports/`.

## 4. Install the Home Assistant package

1. Copy `home-assistant/ssh/ugoos-kodi-lifecycle.conf.example` to `/config/.ssh/ugoos-kodi-lifecycle.conf`.
2. Copy `home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml` to `/config/packages/ugoos_theater_kodi_lifecycle.yaml`.
3. Enable packages in `/config/configuration.yaml` if not already enabled:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

4. Configure the Sony BRAVIA and Kodi integrations so Home Assistant exposes the exact package IDs `media_player.sony_xr_65a90j` and `media_player.kodi_theater`. Rename the entities or duplicate the package for a different room before enabling automations; do not let the package run against placeholder or suffixed entities.

Run validation and reload/restart:

```bash
ha core check
```

Restart Home Assistant Core after installing/updating this package, so the
new helpers, scripts, automations, and shell commands load together.
For subsequent supported YAML reloads use `homeassistant.reload_all`, not
only a shell-command or script reload. The package resets its observation
epoch on HA start, `automation_reloaded`, and re-registration of its changed
reconciler script. Test all three restricted commands from Developer Tools -> Actions:

```text
shell_command.ugoos_theater_kodi_status
shell_command.ugoos_theater_kodi_start
shell_command.ugoos_theater_kodi_stop
```

Each command has the static form `timeout 15s ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf ugoos-theater-lifecycle <start|stop|status>`. Valid lifecycle stdout is exactly `running`, `stopped`, or `failed`.

## 5. Runtime policy

- Stop Kodi while display is off is enabled by default. To opt out in a copied room package, set both the reconciler's `stop_when_display_off: true` and the desired-state sensor's `{% set stop_when_display_off = true %}` to `false`. Absence of an explicit opt-out means enabled.
- The Sony must be continuously `off` for 60 seconds **within the current observation epoch** before Home Assistant stops Kodi. HA start/package reload, observed SSH recovery, unexpected stopped/failed-to-running service recovery, and Kodi availability recovery reset that epoch and clear old idle evidence. A single maturity trigger reconciles after the new minute even if Sony never changes state.
- Queued reconciliations compute desired state after their status round trip and recheck stop eligibility immediately before sending `stop`.
- The idle timeout defaults to 30 minutes through `input_number.ugoos_theater_idle_timeout_minutes`.
- Kodi input-idle probing runs every 15 seconds while the Kodi entity is reachable and calls `XBMC.GetInfoBooleans` with `System.IdleTime(<timeout-seconds>)`.
- Idle evidence expires after 30 seconds, so two missed 15-second probes cannot leave stale positive evidence.
- Genuine `kodi_call_method_result` events identify the request under `input.method` and `input.params.booleans`; only `result_ok: true` with the matching boolean-valued result establishes evidence.
- Sony idle power-off is latched once per episode, including on a 30-second confirmation timeout or action exception. The sent latch survives HA restart. Only genuine playback/input activity or an explicit operator retry rearms it; stale, failed, or unavailable evidence does not.
- `input_boolean.ugoos_theater_keep_kodi_running` is a persistent operational override. Turning it on keeps Kodi running after Sony-off or idle-driven Sony power-off until an operator turns it off.
- Explicit stop-policy opt-out and keep-running affect only Kodi stop. They do not suppress idle-driven Sony power-off.
- A configured Sony in `unknown`/`unavailable` demands running; those states alone are not configuration errors. Missing configured entities raise a configuration notification.
- Missing/stale input-idle evidence inhibits Sony power-off. Staleness notifies only while SSH and Kodi are reachable, after the new epoch's 30-second grace period; a verified later probe clears that class of error.
- Status polls observe host/service health; they do not certify desired-state convergence or Kodi JSON-RPC readiness. Only reconciliation that verifies readiness (when running), a post-operation status, and current desired state stamps “last reconciliation.”
- Errors are retained per operation. A healthy status poll cannot clear a start/readiness, stop, Sony, or probe error. The summary helper joins unresolved errors (bounded to 255 characters); inspect the individual helpers and notifications for full per-class detail.
- Lifecycle failures leave CoreELEC awake and notify; failed SSH cannot promise that Kodi was started. The reconciler never retries indefinitely. Repair the cause, then use a later relevant state transition or an explicit reconciliation retry. Sony power-off failure leaves Kodi running without repeated off requests.
- The package never suspends, shuts down, reboots, power-cycles, or sends Wake-on-LAN to the Ugoos.

## 6. Diagnostics

Review lifecycle deployment reports on the Mac:

```bash
grep -E '^(deployment_state|key_mode|transaction|restored_state|file_rollback_state|service_restore_state|wrapper_path)=|^restricted\.' \
  coreelec-lifecycle-reports/ugoos-theater-*.txt
```

Check Kodi service state over the administrator identity, not the restricted controller key:

```bash
ssh -i "$HOME/.ssh/coreelec_admin_ed25519" root@ugoos-theater \
  '/usr/bin/systemctl status kodi.service --no-pager'
```

Confirm the marked authorized-key entry without printing key bytes:

```bash
ssh -i "$HOME/.ssh/coreelec_admin_ed25519" root@ugoos-theater \
  "grep -Fq 'homeassistant-ugoos-kodi-lifecycle' /storage/.ssh/authorized_keys && printf 'marker-present\n'"
```

From Home Assistant, inspect command behavior and logs:

```bash
timeout 15s ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf ugoos-theater-lifecycle status
ha core logs | grep -E 'ugoos_theater|Kodi lifecycle|Kodi idle|Sony idle' || true
```

In the UI, check the package helpers and persistent notifications beginning
`ugoos_theater_kodi_lifecycle`, plus `ugoos_theater_kodi_idle_probe`,
`ugoos_theater_kodi_idle_poweroff`, and `ugoos_theater_kodi_configuration`.
To retry lifecycle convergence, invoke `script.ugoos_theater_reconcile_kodi`.
To explicitly retry a failed Sony idle episode, first turn off
`input_boolean.ugoos_theater_idle_poweroff_sent`, then invoke
`script.ugoos_theater_power_off_idle_sony`. It still requires current idle
evidence; neither step dismisses the Sony error without verified off
confirmation.

## 7. Recovery, rollback, and key rotation

Use lifecycle CLI recovery commands for an unresolved transaction; do not manually delete broad sections of `/storage/.ssh/authorized_keys`.

```bash
./configure-kodi-lifecycle.sh --target ugoos-theater --inspect-transaction
./configure-kodi-lifecycle.sh --target ugoos-theater --rollback-transaction
./configure-kodi-lifecycle.sh --target ugoos-theater --finalize-transaction
```

If the report names a transaction directory, pass that directory **exactly**,
including its unique suffix; do not reconstruct it from the timestamp:

```bash
./configure-kodi-lifecycle.sh --target ugoos-theater --inspect-transaction /storage/backup/kodi-lifecycle/20260911T210000Z-EXACT_ID_FROM_REPORT
./configure-kodi-lifecycle.sh --target ugoos-theater --rollback-transaction /storage/backup/kodi-lifecycle/20260911T210000Z-EXACT_ID_FROM_REPORT
```

Recovery modes reject `--dry-run` before any SSH call. `--inspect-transaction`
is read-only but does connect.

The version-2 manifest persists the original `running`/`stopped` state and
the transaction phase. Backups are published only after a successful,
byte-verified copy. Rollback restores and verifies **both files and service
state**, retaining the pointer and recovery material until all restoration
succeeds. If restoring Kodi fails, repair that service problem over the
administrator channel and retry the same rollback; a healthy file rollback
alone is not completion. An incomplete backup is never restored. Inspect
and independently verify untouched originals before any manual cleanup of
an incomplete pre-install transaction. Old version-1 journals lack a
recoverable original service state and are refused rather than guessed.

Use `--finalize-transaction [EXACT_DIR]` only for an already-verified
installation reported as `committed-cleanup-pending`. It retries cleanup,
not verification or rollback. An identity-matched receipt outside the
transaction directory makes partial removal, failed pointer unlink, and a
lost finalize response retry-safe. A missing directory without such a
receipt is **not** proof of a committed deployment.

Verified rollback cleanup also has a durable receipt: if removing its
pointer fails after files and service were restored, retrying rollback
finishes cleanup without restoring missing pre-images. Inspection reports
`cleanup-pending` with the verified completion kind for these states, or
`completed` when the pointer is already gone.

Controller denial verification requires exit `2`, empty stdout, and exactly
`Allowed commands: start, stop, status` on stderr. Exit `255`, authentication
failure, disconnect, timeout, or arbitrary other errors do not pass.

For key revocation by rotation, create a new Home Assistant controller key, update `/config/.ssh/ugoos-kodi-lifecycle.conf` if the filename changes, then rerun `./configure-kodi-lifecycle.sh` with the new `--controller-public-key` and matching `--controller-identity`. The CLI replaces only the marked lifecycle authorized-key entry and preserves administrator and unrelated keys. Remove the old private/public key files from Home Assistant and any temporary Mac copy after the replacement report shows `deployment_state=committed`.

A complete committed-key removal with no replacement is not implemented by the lifecycle CLI; record that as an operational limitation rather than performing a broad manual `authorized_keys` deletion.

## 8. Acceptance record

Record live-device results in the room's acceptance table. Do not mark hardware-dependent behavior passed without a live device/HA test and date. Local shell tests prove syntax and contract behavior only; they do not prove the theater pair accepted the lifecycle.

The HA shell suite executes real package Jinja templates, event envelopes,
actions, and representative queue/recovery/failure scenarios using the
environment's existing Python `PyYAML` and `Jinja2` libraries. This fixture
is not HA's schema validator or a live scheduler/device test.
`ha core check`, repeated theater cycles, failure injection, and the
continuous 24-hour off-screen reachability test remain mandatory and pending.
