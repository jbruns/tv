# Shared room setup runbook

Use this workflow for every room. Device models, wiring, display formats, audio capabilities, network identity, and control behavior are selected in each [room overview](../README.md), not assumed to match the theater.

## 1. Record the room

Before installation, document:

- Playback device, display, audio equipment, remotes, and any HDMI extenders.
- HDMI ports and the complete video and audio paths.
- Supported video formats and the capabilities of every link in the audio path.
- A unique hostname, wired MAC address, DHCP reservation, and control method.
- Temporary limitations and the tests needed after planned hardware changes.

Place the room overview in `rooms/<room>/README.md` and device-specific instructions in `rooms/<room>/devices/`. Unrecorded equipment and settings remain pending.

All rooms use **pfSense Plus 26.07** for edge routing. Use the [shared network onboarding guide](network/pfsense-plus-26.07-onboarding.md) to record the existing subnet, DHCP pools, DNS, and Home Assistant network before assigning addresses.

Streaming devices join LAN (`172.16.0.0/16`); Home Assistant is on IoT (`192.168.10.0/24`). Follow the [shared Wake-on-LAN guide](network/wake-on-lan.md) for the existing static ARP wake destination `172.16.99.99`. The network guide records both IPv6 prefixes.

## 2. Prepare the playback device

Follow the shared guide matching the installed device:

- [Ugoos AM6B+: CoreELEC 21.3 on removable media](devices/ugoos-am6b-plus/coreelec-21.3.md).

For the Ugoos pilot, preserve Android and internal eMMC during initial testing. Keep a known working removable installation available before migrating to internal storage.

Once a device can join its intended network, complete network onboarding through address and DNS validation. Keep the client on DHCP and create its static mapping in pfSense before configuring any address-based integrations. Record deferred Home Assistant checks for the service setup stage.

## 3. Provision the shared CoreELEC baseline

Once the device has completed the CoreELEC wizard with wired networking and SSH enabled (end of step 2), and **before** any room-specific playback configuration (step 4), run [`provision-coreelec.sh`](../provision-coreelec.sh) from a Mac. It applies the room-independent baseline: the pinned add-on set, Pacific/English-US regional settings, and any optional service values supplied through configuration or secret environment variables. See [`config/README.md`](../config/README.md) for every configuration key, the strict `KEY=value` grammar, and the secret environment variables.

### Validate first, without touching the device

```bash
./provision-coreelec.sh --check-config
./provision-coreelec.sh --check-artifacts
```

Both exit 0 without `--target`. `--check-artifacts` downloads all 34 pinned add-on artifacts, verifies their SHA-256 checksums, and confirms each is a safe, correctly identified ZIP. Run these after any configuration edit and before the first real deployment.

### Provision the device

```bash
./provision-coreelec.sh --target <hostname-or-IP>
```

- **Interactive prompts on first use:** SSH will prompt for the device's temporary CoreELEC root password while installing the administrator key; if no key exists yet at `~/.ssh/coreelec_admin_ed25519`, `ssh-keygen` also prompts for a new passphrase (macOS Keychain can retain it so later runs don't re-prompt).
- **If the run stops at *"Could not complete the read-only platform check"***, no administrator key was accepted yet, so this is the password branch: either the device never answered the read-only SSH call, or it answered but the temporary root password entered at the prompt was wrong. Nothing on it was changed either way. Confirm the device is powered on and booted into CoreELEC, that its wired address still matches the hostname or IP passed to `--target`, that **Settings → CoreELEC → Services → Enable SSH** is on, and that the temporary root password shown in CoreELEC's first-boot wizard (or set under **Settings → CoreELEC → System**) is what was typed; then re-run the same command.
- **If the run stops at *"Could not install the SSH public key"***, the device answered but the key install did not complete — most often the temporary root password was wrong, or SSH is not enabled. Nothing on the device was changed: the key is written to a candidate file first and appended to `/storage/.ssh/authorized_keys` only after it validates. Re-run the same command. If instead the run stops at *"Could not build the SSH public key installation program"*, the failure is local: `~/.ssh/coreelec_admin_ed25519.pub` is missing, empty, holds more than one key, or is not a well-formed OpenSSH public key line — regenerate it with `ssh-keygen -y -f ~/.ssh/coreelec_admin_ed25519 > ~/.ssh/coreelec_admin_ed25519.pub` and re-run.
- **If the run stops at *"Could not read the platform from ... using `<identity-file>`"***, the administrator key was already accepted (no password prompt appears in this branch), but the read-only identity call still failed — the device most likely went offline or the key was removed from `authorized_keys` between the key check and the read. Nothing on it was changed. Confirm the device is still reachable and that the named key file is still listed in the device's `/storage/.ssh/authorized_keys`; then re-run the same command.
- The run stages and installs the pinned add-ons and settings as one remote transaction, verifies the result over the device's own localhost JSON-RPC (never over the LAN from the Mac), and then automatically finalizes or rolls back depending on what it observes — nothing is left half-applied.

### Backup and rollback locations on the device

- `/storage/backup/coreelec-provision/<UTC-timestamp>/` — one dated transaction directory per run, containing `MANIFEST.txt`, `DEPLOYED.txt`, `APPLIED.txt`, `STATE`, and (until finalized) `rollback/`.
- `/storage/.cache/coreelec-provision/current-transaction` — pointer naming the transaction still pending finalize/rollback, if any.
- `/storage/.cache/coreelec-provision/stage` — uploaded add-on ZIPs staged before installation.

### Review the audit report

Each run writes a redacted, `key=value` report to `<REPORT_DIR>/<target>-<UTC-timestamp>.txt` (default `REPORT_DIR`: `./coreelec-provision-reports/`). It never contains secret values. Review it for:

- `deployment_state` (`committed`, `rolled-back`, `pending-verification`, or `incomplete-rollback` — see restoration/retry below).
- Per-add-on status: `configured` (this run wrote its settings), `installed-unconfigured` (deployed but nothing supplied to configure), or `installed-manual` (always true for Emby and YouTube — see below).
- `regional.localtime.status` and `regional.date_offset.status` (regional verification, below).
- The numbered `manual_action.*` lines — the interactive steps left for you, in a fixed order.

### Emby and YouTube: manual authorization required

Emby for Kodi and the official Kodi YouTube add-on are always reported `installed-manual`, regardless of any credentials supplied:

- **Emby** stores its server and user session in its own database; open Kodi and select/sign in to the Emby server from the add-on itself.
- **YouTube** requires completing Google's device (OAuth) authorization inside the add-on; `YOUTUBE_API_KEY`/`YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET` seed the API keys file but cannot sign an account in.

### Optional: PM4K, NextPVR, HA Weather, and TMDb Helper

These are deployed either way, and are reported `configured` only when their values were supplied (as config keys plus the matching secret environment variable) before the run — otherwise they are `installed-unconfigured` and a `manual_action` line explains what to set, either in the add-on itself or by re-running with the missing values:

- **PM4K** (`script.plexmod`): `PLEX_SERVER_HOST`/`PLEX_SERVER_PORT`/`PLEX_SERVER_NAME`/`PLEX_PROFILE_IDS` plus `PLEX_TOKEN`. Local-mode PM4K is written with `allow_insecure=always`, a deliberate relaxation required to reach a plain-HTTP LAN Plex server; use a token-authorized remote/account link instead if that relaxation is unacceptable for a given room.
- **NextPVR** (`pvr.nextpvr`): `NEXTPVR_HOST`/`NEXTPVR_PORT`/`NEXTPVR_PROTOCOL`/`NEXTPVR_INSTANCE_NAME` plus `NEXTPVR_PIN`.
- **Home Assistant Weather** (`weather.ha`): `HOME_ASSISTANT_URL`/`HOME_ASSISTANT_WEATHER_ENTITY`/`HOME_ASSISTANT_SUN_ENTITY` plus `HOME_ASSISTANT_TOKEN`.
- **TMDb Helper** (`plugin.video.themoviedb.helper`): `OMDB_API_KEY` and/or `MDBLIST_API_KEY` populate metadata keys; Trakt and TMDb user-account linking remain interactive and optional either way.

### Arctic Fuse 3 activation

`skin.arctic.fuse.3` is deployed and set active (`lookandfeel.skin`) by the same run, alongside the regional baseline (`videoplayer.adjustrefreshrate`=On start/stop, `videoplayer.usedisplayasclock`=Off) — no separate manual skin-activation step remains.

### Regional verification

The device verifies its own Pacific/English-US baseline over localhost and reports it in the audit file rather than requiring a manual on-screen check:

- `regional.localtime.status` compares `/etc/localtime` against the requested zone, accepting either a symlink into zoneinfo or a byte-identical copy (`regional.localtime.match`) — both CoreELEC layouts are recognized.
- `regional.date_offset.status` compares the device's reported UTC offset against the expected one from `date +%Z%z`. `/etc/localtime`, its zoneinfo content, and Kodi's own timezone setting are checked strictly first (above); `date +%Z%z` is only a BusyBox capability question on top of that. A malformed or unavailable `date +%Z%z` output is advisory only and reads `unavailable` — it never fails a deployment by itself (BusyBox `date` formatting is not guaranteed). But once the output is well-formed, a genuine offset mismatch (`regional.date_offset.status=mismatch`) **is** a verification failure that counts toward `verification_failures` and triggers rollback like any other failed check. Confirm the displayed date/time on screen if this reads `unavailable`.

### Restoration/retry after a failed run

- `deployment_state=rolled-back` means the device already restored itself; nothing further is required before retrying `--target`.
- `deployment_state=pending-verification` or a second run refusing with *"a deployment transaction from an earlier run is still pending and this run changed nothing"* means an earlier transaction was not resolved. Re-run with **exactly one** of:

  ```bash
  ./provision-coreelec.sh --target <hostname-or-IP> --finalize-deployment
  ./provision-coreelec.sh --target <hostname-or-IP> --rollback-deployment
  ```

- `deployment_state=incomplete-rollback` is fatal and has no automated recovery: the report's `recovery.*` lines name the retained transaction and staging paths and the exact `--rollback-deployment` command; inspect the device over SSH at `recovery.inspect` before retrying.
- A device that cannot answer the local verification probe (for example, because `curl` is missing on the device) is treated as a verification failure and rolled back automatically, not left half-committed.

## 4. Apply room-specific connections and settings

Follow the room's device documents before the first playback tests. Configure the display inputs, audio return path, receiver, and remote/control behavior for that installation. Select playback-device video and audio options according to the actual display and complete signal path.

## 5. Validate and record results

Complete both the shared device checklist and the room checklist. Record the date, installed versions, test titles/tracks, observed display and receiver modes, and any blocked checks in the room documentation. An unchecked item is not evidence of a pass.

Keep removable media in use while applicable tests remain unresolved. A temporary transport limitation must be recorded and retested after the limiting hardware is replaced.

## 6. Back up and optionally migrate

After validation, create a backup and copy it to another system. If using an Ugoos, follow the shared guide's optional eMMC migration procedure only after the applicable shared and room checks pass. Preserve the proven microSD card as recovery media.

## 7. Remaining room-specific service work

Step 3 already installed and, where values were supplied, configured every shared add-on. What remains is room-specific:

1. Final Kodi video and room audio settings.
2. Home Assistant network reachability, monitoring, suspend, and wake.
3. Complete Emby sign-in and YouTube Google authorization (always manual, above).
4. Complete any PM4K/NextPVR/HA Weather/TMDb Helper items still listed as `installed-unconfigured` in the audit report, either interactively or by supplying the missing values and re-running.

Record room-specific integration choices alongside the relevant device.

During Home Assistant setup, finish the network guide's [reachability checks](network/pfsense-plus-26.07-onboarding.md#6-validate-home-assistant-reachability) using each device's recorded endpoint.

## Reuse across rooms

Keep reusable scripts in [code](../code/README.md) and deployable settings in [config](../config/README.md). [`provision-coreelec.sh`](../provision-coreelec.sh) applies the shared configuration to any matching device; room and device-specific values (target address, room video/audio settings, hardware validation) stay outside it and are supplied per device, as described above.
