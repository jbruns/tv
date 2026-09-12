# Ugoos Kodi lifecycle Home Assistant operations

This guide deploys and operates the theater's always-awake CoreELEC lifecycle.
CoreELEC stays awake on wired LAN; Home Assistant starts and stops Kodi,
powers off the Sony when idle, and leaves the host awake on failure. Wake-on-
LAN, suspend, shutdown, reboot, and power-cycling are outside the lifecycle.

For the platform boundary, read the
[Ugoos AM6B+ CoreELEC 21.3 system decision](../decisions/ugoos-coreelec-21.3-system.md).
For shared provisioning order, use
[Provision a Ugoos CoreELEC system](../operations/provision-ugoos.md). For
Sony BRAVIA setup and the theater integration prerequisites, follow the
[Theater Sony guide](../../rooms/theater/devices/sony-xr-65a90j.md).

## Deployment order

```text
CoreELEC wizard
-> DHCP reservation and DNS
-> shared baseline provisioning (CEC Ignore)
-> restricted lifecycle gateway deployment
-> Sony BRAVIA and Kodi integrations
-> theater Home Assistant package
-> room-specific playback configuration
```

## Exact package contract

| Value | Exact ID/path |
|---|---|
| Sony entity | `media_player.sony_xr_65a90j` |
| Kodi entity | `media_player.kodi_theater` |
| Ugoos lifecycle host | `ugoos-theater` via SSH alias `ugoos-theater-lifecycle` |
| Home Assistant private key | `/config/.ssh/ugoos_kodi_lifecycle_ed25519` |
| Home Assistant known hosts | `/config/.ssh/known_hosts` |
| Home Assistant SSH config | `/config/.ssh/ugoos-kodi-lifecycle.conf` |
| Package file | `/config/packages/ugoos_theater_kodi_lifecycle.yaml` |
| Keep-running helper | `input_boolean.ugoos_theater_keep_kodi_running` |
| Idle timeout helper | `input_number.ugoos_theater_idle_timeout_minutes` |
| Lifecycle state helper | `input_text.ugoos_theater_kodi_lifecycle_state` |
| Last command helper | `input_text.ugoos_theater_last_lifecycle_command` |
| Last reconciliation helper | `input_datetime.ugoos_theater_last_reconciliation` |
| Observation epoch helper | `input_datetime.ugoos_theater_observation_started` |
| Observation-ready helper | `input_boolean.ugoos_theater_observation_ready` |
| Error summary helper | `input_text.ugoos_theater_last_lifecycle_error` |
| Reconciler script | `script.ugoos_theater_reconcile_kodi` |
| Idle Sony script | `script.ugoos_theater_power_off_idle_sony` |
| Restricted commands | `shell_command.ugoos_theater_kodi_start`, `shell_command.ugoos_theater_kodi_stop`, `shell_command.ugoos_theater_kodi_status` |

## 1. Confirm the CoreELEC baseline

Run shared baseline provisioning first:

```bash
./provision-coreelec.sh --target ugoos-theater
```

Review the generated report under `coreelec-provision-reports/`. The required
CEC Ignore result is:

```text
cec.tv_off_action.expected=36028
cec.tv_off_action.observed=36028
cec.tv_off_action.status=ok
```

Kodi peripheral XML must contain a direct child
`<setting id="standby_pc_on_tv_standby" value="36028" />`.

## 2. Create the Home Assistant controller identity

In Home Assistant Terminal & SSH, create the dedicated unattended controller
key. Do not overwrite an existing controller identity:

```bash
mkdir -p /config/.ssh
chmod 700 /config/.ssh
ssh-keygen -t ed25519 -N '' \
  -f /config/.ssh/ugoos_kodi_lifecycle_ed25519 \
  -C homeassistant-ugoos-kodi-lifecycle
chmod 600 /config/.ssh/ugoos_kodi_lifecycle_ed25519
```

Keep both controller key files out of this repository. The private key stays on
Home Assistant except for the brief deployment option below.

### Authenticate the Ugoos server key before trusting it

Obtain the Ugoos **server** Ed25519 fingerprint through its local console, an
independently verified asset record, or an already fingerprint-verified
administrator connection. On that trusted CoreELEC channel:

```bash
ssh-keygen -l -E sha256 -f /storage/.cache/ssh/ssh_host_ed25519_key.pub
```

On Home Assistant, replace the placeholder below with that independently
authenticated fingerprint. Only a matching candidate may enter
`/config/.ssh/known_hosts`:

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

Install the same authenticated host entry in the deploying user's
`$HOME/.ssh/known_hosts` for the exact hostname or address passed to `--target`.

## 3. Deploy the restricted lifecycle gateway

Either securely make the controller identity available to the Mac only for
gateway deployment, or run the command from a trusted checkout that can read
both controller key files:

```bash
./configure-kodi-lifecycle.sh \
  --target ugoos-theater \
  --controller-public-key "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519.pub" \
  --controller-identity "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519"
```

Neither file belongs in the repository. If you temporarily copy the Home
Assistant private or public key to the Mac, remove that copy immediately after
deployment.

The command installs `/storage/.config/kodi-lifecycle`, replaces only the
marked `homeassistant-ugoos-kodi-lifecycle` entry in
`/storage/.ssh/authorized_keys`, verifies restricted `status`, `start`, `stop`,
and arbitrary-command denial, restores the original Kodi state, and writes a
redacted report under `coreelec-lifecycle-reports/`.

Controller denial verification passes only with exit `2`, empty stdout, and
exactly `Allowed commands: start, stop, status` on stderr.

## 4. Install the Home Assistant package

1. Copy `home-assistant/ssh/ugoos-kodi-lifecycle.conf.example` to
   `/config/.ssh/ugoos-kodi-lifecycle.conf`.
2. Copy `home-assistant/packages/ugoos_theater_kodi_lifecycle.yaml` to
   `/config/packages/ugoos_theater_kodi_lifecycle.yaml`.
3. Enable packages in `/config/configuration.yaml` if needed:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

4. Configure the Sony BRAVIA and Kodi integrations so Home Assistant exposes
   the exact package IDs `media_player.sony_xr_65a90j` and
   `media_player.kodi_theater`. Rename entities or duplicate the package for a
   different room before enabling automations.

Run validation and restart/reload:

```bash
ha core check
```

Restart Home Assistant Core after installing or updating this package so the
helpers, scripts, automations, and shell commands load together. For later
supported YAML reloads use `homeassistant.reload_all`. Test all three
restricted commands from Developer Tools -> Actions:

```text
shell_command.ugoos_theater_kodi_status
shell_command.ugoos_theater_kodi_start
shell_command.ugoos_theater_kodi_stop
```

Each command has the static form:

```text
timeout 15s ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf ugoos-theater-lifecycle <start|stop|status>
```

Valid lifecycle stdout is exactly `running`, `stopped`, or `failed`.

## 5. Runtime contract

- Stop-Kodi-while-display-off is enabled by default.
- The Sony must be continuously `off` for **60 seconds within the current
  observation epoch** before Home Assistant stops Kodi. Home Assistant start,
  package reload, observed SSH recovery, unexpected stopped or failed to
  running service recovery, and Kodi availability recovery reset that epoch.
- `input_number.ugoos_theater_idle_timeout_minutes` defaults to **30 minutes**.
- Kodi input-idle probing runs every 15 seconds while the Kodi entity is
  reachable. Idle evidence expires after 30 seconds, so stale positive evidence
  cannot survive two missed probe intervals.
- `input_boolean.ugoos_theater_keep_kodi_running` is a persistent operational
  override. Turning it on keeps Kodi running after Sony-off or idle-driven Sony
  power-off until an operator turns it off.
- When a reconciliation wants Kodi `running`, the package waits up to
  **90 seconds** for `media_player.kodi_theater` to become JSON-RPC available.
- Sony idle power-off is latched once per episode, including on a
  **30-second** confirmation timeout or action exception. Only genuine
  playback/input activity or an explicit operator retry rearms it.
- Missing or stale input-idle evidence inhibits Sony power-off.
- A configured Sony in `unknown` or `unavailable` demands `running`; those
  states alone are not configuration errors.
- Lifecycle failures leave CoreELEC awake and notify; failed SSH cannot promise
  that Kodi started. Sony power-off failure leaves Kodi running without
  repeated off requests.
- The package never suspends, shuts down, reboots, power-cycles, or sends
  Wake-on-LAN to the Ugoos.

## 6. Operations and diagnostics

Review lifecycle deployment reports on the Mac:

```bash
grep -E '^(deployment_state|key_mode|transaction|restored_state|file_rollback_state|service_restore_state|wrapper_path)=|^restricted\.' \
  coreelec-lifecycle-reports/ugoos-theater-*.txt
```

Check Kodi service state over the administrator identity, not the restricted
controller key:

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

In the UI, inspect the package helpers and persistent notifications beginning
`ugoos_theater_kodi_lifecycle`, plus `ugoos_theater_kodi_idle_probe`,
`ugoos_theater_kodi_idle_poweroff`, and `ugoos_theater_kodi_configuration`.

To retry lifecycle convergence, run `script.ugoos_theater_reconcile_kodi`.
To retry a failed Sony idle episode, first turn off
`input_boolean.ugoos_theater_idle_poweroff_sent`, then run
`script.ugoos_theater_power_off_idle_sony`.

## 7. Transaction recovery and key rotation

Use lifecycle CLI recovery commands for an unresolved transaction; do not
manually delete broad sections of `/storage/.ssh/authorized_keys`.

```bash
./configure-kodi-lifecycle.sh --target ugoos-theater --inspect-transaction
./configure-kodi-lifecycle.sh --target ugoos-theater --rollback-transaction
./configure-kodi-lifecycle.sh --target ugoos-theater --finalize-transaction
```

If the report names a transaction directory, pass that directory **exactly**:

```bash
./configure-kodi-lifecycle.sh --target ugoos-theater --inspect-transaction <transaction-dir-from-report>
./configure-kodi-lifecycle.sh --target ugoos-theater --rollback-transaction <transaction-dir-from-report>
./configure-kodi-lifecycle.sh --target ugoos-theater --finalize-transaction <transaction-dir-from-report>
```

Recovery modes reject `--dry-run` before any SSH call. `--inspect-transaction`
is read-only but does connect.

Use `--finalize-transaction [EXACT_DIR]` only for an already verified
installation reported as `committed-cleanup-pending`. It retries cleanup, not
verification or rollback. Verified rollback cleanup can similarly report
`cleanup-pending` until the pointer is removed, then `completed`.

Rollback restores and verifies both files and Kodi service state. If restoring
Kodi fails, repair the service over the administrator channel and retry the
same rollback; a healthy file rollback alone is not completion.

For key rotation, create a new Home Assistant controller key, update
`/config/.ssh/ugoos-kodi-lifecycle.conf` if the filename changes, then rerun
`./configure-kodi-lifecycle.sh` with the new `--controller-public-key` and
matching `--controller-identity`. Remove the old Home Assistant and temporary
Mac key copies only after the replacement report shows
`deployment_state=committed`.

A complete committed-key removal with no replacement is not implemented by the
lifecycle CLI.
