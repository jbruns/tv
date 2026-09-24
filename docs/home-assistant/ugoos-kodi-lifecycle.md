# Kodi Lifecycle in Home Assistant

This guide deploys and operates the Kodi Lifecycle: Home Assistant starting
Kodi on a Device while its Display is on and stopping it once the Display has
been off for a while
([ADR 0020](../adr/0020-kodi-lifecycle-is-event-driven-home-assistant-blueprints.md)).
CoreELEC stays awake on wired LAN throughout. Wake-on-LAN, suspend, shutdown,
reboot, and power-cycling are outside the lifecycle.

The logic is one blueprint, instantiated per Device:

| File in this repository | Deployed to |
|---|---|
| `home-assistant/blueprints/automation/jbruns/kodi_lifecycle.yaml` | `/config/blueprints/automation/jbruns/kodi_lifecycle.yaml` |
| `home-assistant/packages/kodi_lifecycle.yaml` | `/config/packages/kodi_lifecycle.yaml` |
| `home-assistant/packages/kodi_lifecycle_ugoos_theater.yaml` | `/config/packages/kodi_lifecycle_ugoos_theater.yaml` |
| `home-assistant/ssh/ugoos-kodi-lifecycle.conf.example` | `/config/.ssh/ugoos-kodi-lifecycle.conf` |

`kodi_lifecycle.yaml` holds the one templated `shell_command.kodi_lifecycle`
every Device shares. Each Device then has its own instance package: the
automation built from the blueprint, its Keep-Running Hold, and its Restart
Kodi script.

To provision the Device, use
[Provision a Device](../operations/provision-a-device.md). For
Sony BRAVIA setup and the theater integration prerequisites, follow the
[Theater Sony guide](../../rooms/theater/devices/sony-xr-65a90j.md).

Kodi keeps CEC enabled for navigation, but the Profile declares the CEC
adapter settings so Kodi neither claims the active source nor powers the
Display on or off when it starts or stops. See the
[Profile reference](../reference/profile.md#naming-a-document-the-profile-cannot-know).

## Deployment order

```text
CoreELEC wizard
-> DHCP reservation and DNS
-> Home Assistant controller identity (section 1)
-> Reconciler bootstrap and apply, which installs the gateway (section 2)
-> Display and Kodi integrations
-> blueprint and instance package (section 3)
```

## 1. Create the Home Assistant controller identity

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

## 2. Install the restricted lifecycle gateway

The Reconciler installs the gateway. Put the one-line contents of
`/config/.ssh/ugoos_kodi_lifecycle_ed25519.pub` into the controller's `.env` as
`COREELEC_LIFECYCLE_PUBLIC_KEY`, then run `apply` as in
[Provision a Device](../operations/provision-a-device.md).

`apply` ships `/storage/.config/kodi-lifecycle` and writes the
`homeassistant-ugoos-kodi-lifecycle` entry into
`/storage/.ssh/authorized_keys` behind a forced command that runs only that
gateway. The gateway accepts `start`, `stop` and `status`; anything else exits
`2` with `Allowed commands: start, stop, status` on stderr.

## 3. Install the blueprint and the theater instance

1. Copy `home-assistant/ssh/ugoos-kodi-lifecycle.conf.example` to
   `/config/.ssh/ugoos-kodi-lifecycle.conf`. It needs one `Host` block per
   Device.
2. Import the blueprint from Settings -> Automations & scenes -> Blueprints ->
   Import Blueprint, using
   `https://github.com/jbruns/tv/blob/main/home-assistant/blueprints/automation/jbruns/kodi_lifecycle.yaml`.
   Re-import it the same way after it changes.
3. Copy `home-assistant/packages/kodi_lifecycle.yaml` and
   `home-assistant/packages/kodi_lifecycle_ugoos_theater.yaml` into
   `/config/packages/`. Delete `/config/packages/ugoos_theater_kodi_lifecycle.yaml`
   if it is still there: it is the retired polling package, and it must not
   run beside the blueprint. Enable packages in `/config/configuration.yaml` if
   needed:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

4. Configure the Display and Kodi integrations and confirm the entity IDs in
   the instance package exist. For the theater those are
   `media_player.sony_theater` and `media_player.ugoos_theater`.
5. Run `ha core check`, then restart Home Assistant Core.

CI runs Home Assistant's `check_config` against these same files; run
`scripts/check_home_assistant.sh` to do the same locally.

From Developer Tools -> Actions, check the gateway with:

```yaml
action: shell_command.kodi_lifecycle
data:
  host: ugoos-theater-lifecycle
  command: status
```

It runs `timeout 15s ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf
ugoos-theater-lifecycle status`. The reply's stdout is exactly `running`,
`stopped`, or `failed`.

## 4. Behaviour

The automation acts only on transitions:

- The Display turning on from `off` starts Kodi and selects the Device's input
  once. Switching input afterwards is left alone.
- The Display turning `off` for the stop delay stops Kodi, unless the
  Keep-Running Hold is on. Only the Display coming on ends the delay early;
  dropping to `unavailable` in standby does not.
- Only `off` counts as off. Changes to or from `unavailable` or `unknown` do
  nothing.
- On Home Assistant start, a Display that is on starts Kodi without selecting
  the input. A Display that is off restarts the stop delay; Kodi is never
  stopped straight away.
- Idle Power-Off: once the Kodi media player has been `idle` for the idle
  timeout while Viewing, the Display is turned off, and the stop delay then
  stops Kodi. Viewing means the Display is on with its `source` set to the
  Device's input. Kodi being idle and Viewing must both hold for the whole
  timeout, so playback, pause, or switching the Display to another input or
  its own apps starts the countdown again. If Home Assistant restarts, or the
  automation is reloaded, while Kodi is idle and Viewing, there is no
  countdown until one of those breaks it and it holds again.

It never polls. A Kodi stopped by hand, or by the Reconciler during a Run,
stays stopped until the next Display transition, so provisioning needs no
Hold. Lifting the Keep-Running Hold does not stop Kodi by itself. systemd, not
Home Assistant, restarts a Kodi that crashes. The automation never suspends,
shuts down, reboots, power-cycles, or sends Wake-on-LAN to the Device.

### Inputs

| Input | Meaning | Theater value |
|---|---|---|
| Display | The Display's media player | `media_player.sony_theater` |
| Display source | The Device's input, exactly as in the Display's `source_list` | `HDMI 4` |
| Kodi media player | The Kodi integration's media player | `media_player.ugoos_theater` |
| SSH host alias | The Device's `Host` in the SSH config | `ugoos-theater-lifecycle` |
| Keep-Running Hold | An `input_boolean`; while on, Kodi is never stopped | `input_boolean.ugoos_theater_keep_running_hold` |
| Stop delay | How long the Display must stay off before Kodi stops | 10 minutes (default) |
| Idle timeout | How long Kodi must be idle while Viewing before the Display turns off | 30 minutes (default) |

## 5. Add a Device

1. Provision the Device and let `apply` install its gateway, as in sections 1
   and 2. The same controller key serves every Device.
2. Add a `Host` block for it to `/config/.ssh/ugoos-kodi-lifecycle.conf`, and
   authenticate its host key into `/config/.ssh/known_hosts` as in section 1.
3. Copy `kodi_lifecycle_ugoos_theater.yaml` to
   `kodi_lifecycle_<device>.yaml`. Give the automation, the Hold, and the
   Restart Kodi script new IDs and names, and set the Device's Display,
   Display source, Kodi media player, and SSH host alias.
4. Run `scripts/check_home_assistant.sh`, deploy the package, run
   `ha core check`, and restart Home Assistant Core.

## 6. Operations and diagnostics

### Restart Kodi

`script.ugoos_theater_restart_kodi` (`Theater - Restart Kodi`) runs the
gateway's `stop`, then `start`. A failed `stop` still goes on to `start`. It
never reboots the Device. Run it from the script's page in Settings ->
Automations & scenes -> Scripts, or add it to a dashboard.

### Automation traces

Each run of `Theater - Kodi Lifecycle` records its trigger, the command it
chose, the stop-delay wait, and the gateway's reply. Open the automation in
Settings -> Automations & scenes and choose Traces. A run that ended early
names why in its `stop` step, for example "The Keep-Running Hold is on." or
"The Display came on before the stop delay ended." The Restart Kodi script has
traces too.

A failed `start` or `stop` raises one persistent notification per Device,
`kodi_lifecycle_<ssh host alias>`, naming the gateway's exit code and output.
The next successful command clears it; the next Display transition tries
again.

### From a shell

From Home Assistant, ask the gateway directly:

```bash
timeout 15s ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf ugoos-theater-lifecycle status
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

## 7. Key rotation

Create a new Home Assistant controller key, update
`/config/.ssh/ugoos-kodi-lifecycle.conf` if the filename changes, put the new
public key in `.env` as `COREELEC_LIFECYCLE_PUBLIC_KEY`, and run `apply`. The
Reconciler replaces the marked entry, so the old key stops working in the same
Run. Remove the old key from Home Assistant afterwards.
