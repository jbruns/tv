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
| Last error helper | `input_text.ugoos_theater_last_lifecycle_error` |
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

The Task 5 checklist phrase `cec.tv_off_action.status=match` means this same match condition; the implemented report value for a match is `ok`, while a nonmatching observed value reports `cec.tv_off_action.status=mismatch` and fails verification.

## 2. Create the Home Assistant controller identity

In Home Assistant's Terminal & SSH app, create the controller key and known-hosts entry:

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

Keep both controller key files out of this repository. The private key stays on Home Assistant except for the brief deployment option below.

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

Then reload shell commands if your Home Assistant version exposes that reload action, otherwise restart Home Assistant Core. Test all three restricted commands from Developer Tools -> Actions:

```text
shell_command.ugoos_theater_kodi_status
shell_command.ugoos_theater_kodi_start
shell_command.ugoos_theater_kodi_stop
```

Each command has the static form `timeout 15s ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf ugoos-theater-lifecycle <start|stop|status>`. Valid lifecycle stdout is exactly `running`, `stopped`, or `failed`.

## 5. Runtime policy

- Stop Kodi while display is off is enabled by default for the theater package (`stop_when_display_off: true`). A future room package must make opt-out explicit; absence of an opt-out means enabled.
- The Sony must be continuously `off` for 60 seconds before Home Assistant stops Kodi.
- The idle timeout defaults to 30 minutes through `input_number.ugoos_theater_idle_timeout_minutes`.
- Kodi input-idle probing runs every 15 seconds while the Kodi entity is reachable and calls `XBMC.GetInfoBooleans` with `System.IdleTime(<timeout-seconds>)`.
- Idle evidence expires after 30 seconds, so two missed 15-second probes cannot leave stale positive evidence.
- `input_boolean.ugoos_theater_keep_kodi_running` is a persistent operational override. Turning it on keeps Kodi running after Sony-off or idle-driven Sony power-off until an operator turns it off.
- Explicit stop-policy opt-out and keep-running affect only Kodi stop. They do not suppress idle-driven Sony power-off.
- Fail-awake rules are binding: Sony `unknown`/`unavailable`, missing/stale idle evidence, start/stop/status transport failures, malformed lifecycle status, or Sony power-off failure leave or request Kodi running and raise a persistent notification.
- The package never suspends, shuts down, reboots, power-cycles, or sends Wake-on-LAN to the Ugoos.

## 6. Diagnostics

Review lifecycle deployment reports on the Mac:

```bash
grep -E '^(deployment_state|key_mode|transaction|restricted\.|restored_state|file_rollback_state|service_restore_state|wrapper_path)=' \
  coreelec-lifecycle-reports/ugoos-theater-*.txt
```

Check Kodi service state over the administrator identity, not the restricted controller key:

```bash
ssh -i "$HOME/.ssh/coreelec_admin_ed25519" root@ugoos-theater \
  '/usr/bin/systemctl status kodi.service --no-pager'
```

Confirm the marked authorized-key entry without editing the file:

```bash
ssh -i "$HOME/.ssh/coreelec_admin_ed25519" root@ugoos-theater \
  "grep -F 'homeassistant-ugoos-kodi-lifecycle' /storage/.ssh/authorized_keys"
```

From Home Assistant, inspect command behavior and logs:

```bash
timeout 15s ssh -F /config/.ssh/ugoos-kodi-lifecycle.conf ugoos-theater-lifecycle status
ha core logs | grep -E 'ugoos_theater|Kodi lifecycle|Kodi idle|Sony idle' || true
```

In the UI, check the package helpers listed above and persistent notifications with IDs beginning `ugoos_theater_kodi_lifecycle` or `ugoos_theater_kodi_idle_poweroff`.

## 7. Recovery, rollback, and key rotation

Use lifecycle CLI recovery commands for an unresolved transaction; do not manually delete broad sections of `/storage/.ssh/authorized_keys`.

```bash
./configure-kodi-lifecycle.sh --target ugoos-theater --inspect-transaction
./configure-kodi-lifecycle.sh --target ugoos-theater --rollback-transaction
./configure-kodi-lifecycle.sh --target ugoos-theater --finalize-transaction
```

If the report names a transaction directory, pass that directory exactly, for example:

```bash
./configure-kodi-lifecycle.sh --target ugoos-theater --inspect-transaction /storage/backup/kodi-lifecycle/20260911T210000Z
./configure-kodi-lifecycle.sh --target ugoos-theater --rollback-transaction /storage/backup/kodi-lifecycle/20260911T210000Z
```

For key revocation by rotation, create a new Home Assistant controller key, update `/config/.ssh/ugoos-kodi-lifecycle.conf` if the filename changes, then rerun `./configure-kodi-lifecycle.sh` with the new `--controller-public-key` and matching `--controller-identity`. The CLI replaces only the marked lifecycle authorized-key entry and preserves administrator and unrelated keys. Remove the old private/public key files from Home Assistant and any temporary Mac copy after the replacement report shows `deployment_state=committed`.

A complete committed-key removal with no replacement is not implemented by the lifecycle CLI; record that as an operational limitation rather than performing a broad manual `authorized_keys` deletion.

## 8. Acceptance record

Record live-device results in the room's acceptance table. Do not mark hardware-dependent behavior passed without a live device/HA test and date. Local shell tests prove syntax and contract behavior only; they do not prove the theater pair accepted the lifecycle.
