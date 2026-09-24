# Ugoos Kodi lifecycle Home Assistant operations

This guide deploys and operates the theater's always-awake CoreELEC lifecycle.
CoreELEC stays awake on wired LAN; Home Assistant starts and stops Kodi,
powers off the Sony when idle, and leaves the host awake on failure. Wake-on-
LAN, suspend, shutdown, reboot, and power-cycling are outside the lifecycle.

To provision the Device, use
[Provision a Device](../operations/provision-a-device.md). For
Sony BRAVIA setup and the theater integration prerequisites, follow the
[Theater Sony guide](../../rooms/theater/devices/sony-xr-65a90j.md).

## Deployment order

```text
CoreELEC wizard
-> DHCP reservation and DNS
-> Home Assistant controller identity (section 2)
-> Reconciler bootstrap and apply, which installs the gateway (section 3)
-> Sony BRAVIA and Kodi integrations
-> theater Home Assistant package
```

## Exact package contract

| Value | Exact ID/path |
|---|---|
| Sony entity | `media_player.bravia_xr_65a90j` |
| Kodi entity | `media_player.theater_kodi_theater` |
| Ugoos lifecycle host | `ugoos-theater.lan.wavebe.am` via SSH alias `ugoos-theater-lifecycle` |
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

## 1. CEC power isolation

The Profile declares the CEC adapter's settings, so every `apply` holds them.
Kodi keeps CEC enabled for navigation, but it neither claims the active source
nor sends TV power-on or standby commands when Kodi starts or stops. See the
[Profile reference](../reference/profile.md#naming-a-document-the-profile-cannot-know).

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

Keep both controller key files out of this repository. The private key never
leaves Home Assistant.

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
ssh-keyscan -T 5 -t ed25519 -H ugoos-theater.lan.wavebe.am > /config/.ssh/ugoos-theater.candidate
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

## 3. Install the restricted lifecycle gateway

The Reconciler installs the gateway. Put the one-line contents of
`/config/.ssh/ugoos_kodi_lifecycle_ed25519.pub` into the controller's `.env` as
`COREELEC_LIFECYCLE_PUBLIC_KEY`, then run `apply` as in
[Provision a Device](../operations/provision-a-device.md).

`apply` ships `/storage/.config/kodi-lifecycle` and writes the
`homeassistant-ugoos-kodi-lifecycle` entry into
`/storage/.ssh/authorized_keys` behind a forced command that runs only that
gateway. The gateway accepts `start`, `stop` and `status`; anything else exits
`2` with `Allowed commands: start, stop, status` on stderr.

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

4. Configure the Sony BRAVIA and Kodi integrations, then confirm Home Assistant
   exposes `media_player.bravia_xr_65a90j` and
   `media_player.theater_kodi_theater`. Update a room-specific package if the
   integration-generated IDs differ before enabling automations.

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
- A normal difference between the polled Kodi service state and the
  minute-refreshed desired-state sensor does not reset the observation epoch.
  Reconciliation computes the desired state again from current inputs, so a
  stale sensor cannot restart Kodi immediately after a confirmed Sony-off stop.
- `input_number.ugoos_theater_idle_timeout_minutes` defaults to **30 minutes**.
- Kodi input-idle probing runs every 15 seconds while the Kodi entity is
  reachable. Idle evidence expires after 30 seconds, so stale positive evidence
  cannot survive two missed probe intervals.
- `input_boolean.ugoos_theater_keep_kodi_running` is a persistent operational
  override. Turning it on keeps Kodi running after Sony-off or idle-driven Sony
  power-off until an operator turns it off.
- When a reconciliation wants Kodi `running`, the package waits up to
  **90 seconds** for `media_player.theater_kodi_theater` to become JSON-RPC
  available.
- Sony idle power-off is latched once per episode, including on a
  **30-second** confirmation timeout or action exception. Only genuine
  playback/input activity or an explicit operator retry rearms it.
- Missing or stale input-idle evidence inhibits Sony power-off.
- A configured Sony in `unknown` or `unavailable` demands `running`; those
  states alone are not configuration errors.
- Lifecycle failures leave CoreELEC awake and notify; failed SSH cannot promise
  that Kodi started. Sony power-off failure leaves Kodi running without
  repeated off requests.
- A start or stop command can exceed the 15-second SSH client deadline after
  the device has already converged. When the 30-second status poll then reads
  the currently desired state authoritatively, it clears that one operation's
  stale diagnostic and dismisses its notification. `running` also requires
  JSON-RPC readiness before it counts as start convergence. Observed states
  that differ from the desired state, `failed` results, unreachable hosts, and
  unrelated operation errors are all preserved.
- The package never suspends, shuts down, reboots, power-cycles, or sends
  Wake-on-LAN to the Ugoos.
- Kodi CEC remains available for remote navigation but is provisioned not to
  power the Sony on or off. Deliberate Sony power-off remains owned by Home
  Assistant and the user.

## 6. Operations and diagnostics

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

## 7. Key rotation

Create a new Home Assistant controller key, update
`/config/.ssh/ugoos-kodi-lifecycle.conf` if the filename changes, put the new
public key in `.env` as `COREELEC_LIFECYCLE_PUBLIC_KEY`, and run `apply`. The
Reconciler replaces the marked entry, so the old key stops working in the same
Run. Remove the old key from Home Assistant afterwards.
