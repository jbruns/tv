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

### Two-phase workflow

Run the shared baseline first, then the separate post-deployment checks:

```bash
./provision-coreelec.sh --target <hostname-or-IP>
./configure-coreelec-addons.sh --target <hostname-or-IP>
./configure-coreelec-addons.sh --target <hostname-or-IP> --interactive \
  --addon script.plexmod \
  --addon plugin.video.youtube \
  --addon plugin.service.emby-next-gen
```

- `provision-coreelec.sh --target ...` is transactional and unattended: it
  either commits the verified baseline or rolls it back as one remote unit.
- `configure-coreelec-addons.sh --target ...` is a separate post-deployment
  helper. Its default run is read-only and never rolls back a valid baseline.
- `--interactive` is opt-in for guided account flows. It may wait while you
  finish a browser/device-code step elsewhere, but a timeout or
  `manual-required` result still leaves the already provisioned baseline in
  place.
- `--dry-run`, including together with `--interactive`, validates locally and
  writes `status=dry-run` for every selected add-on. It makes zero SSH, device,
  or remote service calls and transmits no secrets.
- Provisioning itself cannot sign Emby in. Use the post-deployment helper if
  you want guarded Emby, PM4K account-mode, or YouTube assistance.

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

### Post-deployment unattended service validation

After step 3 has finalized, validate the shared add-ons from the Mac without rewriting any add-on settings:

```bash
./configure-coreelec-addons.sh --target <hostname-or-IP>
```

The helper authenticates to Kodi with the web password that
`provision-coreelec.sh` stored in the macOS Keychain service
`coreelec-kodi-ha-<target>`; export `KODI_WEB_PASSWORD` first if you need to
override that value or if provisioning did not run on this Mac.

The command still writes a redacted `key=value` report, but for the fully
unattended add-ons it now also performs read-only service checks from the
CoreELEC device itself before reporting success:

- **Home Assistant Weather** (`weather.ha`): requests `/api/config`, then `/api/states/<HOME_ASSISTANT_WEATHER_ENTITY>` with the configured bearer token, and executes `weather.ha` once only after both responses succeed.
- **NextPVR** (`pvr.nextpvr`): performs `session.initiate`, calculates the add-on's lower-case MD5 login digest from `NEXTPVR_PIN`, requires a successful `session.login`, and records `PVR.GetChannelGroups` as an advisory Kodi-side observation.
  `PVR.GetChannelGroups` is intentionally not a globally required capability;
  an unavailable or failed observation cannot override a successful backend
  login.
- **PM4K local mode** (`script.plexmod`): requires HTTP 200 from Plex `/identity`, then requires the configured `PLEX_TOKEN` to receive HTTP 200 from `/`, and executes `script.plexmod` only after both checks succeed.

Across both non-interactive and `--interactive` runs, expect:

- `dry-run` for every selected add-on when `--dry-run` is present; no add-on
  workflow is dispatched.
- `already-configured` when a guided workflow finds a persisted token/session
  before sending any GUI input.
- `configured` when a configured service answers correctly and the required
  Kodi launch/advisory check succeeds, or when a guided workflow finishes and
  the persisted state appears.
- `authorization-required` when a stored token or PIN is rejected
  (`401`/`403`, failed NextPVR session login), or when a non-interactive run
  defers a guided-only add-on to the operator.
- `manual-required` when the guided helper refuses to continue because the
  pinned version, English-US GUI labels, dialog flow, certificate state, or
  timeout does not match the guarded expectations.
- `failed` on transport errors, malformed payloads, or a Plex/Home Assistant
  identity mismatch.
- `skipped` when no unattended service configuration was supplied for that
  add-on.

These checks are intentionally read-only: re-run `provision-coreelec.sh` with corrected values if a status shows that the stored configuration is wrong.

### Guided account authorization after deployment

Provisioning itself still cannot complete Emby, PM4K account-mode, or YouTube
account authorization. Use the separate helper only after the baseline has
been provisioned successfully:

```bash
./configure-coreelec-addons.sh --target <hostname-or-IP> --interactive \
  --addon script.plexmod \
  --addon plugin.video.youtube \
  --addon plugin.service.emby-next-gen
```

- **PM4K account mode** (`script.plexmod` `1.14.1-beta1`): launches PM4K,
  waits for the pinned English-US `Sign In` control, selects it, and tells you
  to finish the displayed code at `https://plex.tv/link`. It only reports
  boolean token presence; it never prints the token itself.
- **YouTube** (`plugin.video.youtube` `7.4.4`): opens
  `plugin://plugin.video.youtube/sign/in/` in Kodi's Videos window, dismisses
  only the pinned introductory `OK` dialog, then leaves Google's device-code
  creation, polling, and token storage inside the add-on. Version `7.4.4` may
  ask you to approve more than one Google code.
- **Emby for Kodi Next Gen** (`plugin.service.emby-next-gen` `12.4.23`):
  requires `EMBY_SERVER_URL` and `EMBY_USERNAME` in the selected config file,
  plus `EMBY_PASSWORD` from the environment or a no-echo prompt in an
  interactive terminal. The helper launches Emby, selects `Manually add
  server`, submits the URL, username, and password through the pinned
  English-US dialogs, and then waits for Emby's handshake database to appear.
  It never prints or reports the password itself.
- All three guided flows are version-gated against the add-on versions pinned
  in `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf`. If the
  installed version or expected English-US GUI label does not match, if Emby
  surfaces certificate/ambiguity/database-resync prompts, or if the deadline
  expires, the helper returns `manual-required` and you must continue from the
  TV yourself.

### Optional: PM4K, NextPVR, HA Weather, and TMDb Helper

These are deployed either way, and are reported `configured` only when their values were supplied (as config keys plus the matching secret environment variable) before the run — otherwise they are `installed-unconfigured` and a `manual_action` line explains what to set, either in the add-on itself or by re-running with the missing values:

- **PM4K** (`script.plexmod`): `PLEX_SERVER_HOST`/`PLEX_SERVER_PORT`/`PLEX_SERVER_NAME`/`PLEX_PROFILE_IDS` plus `PLEX_TOKEN`. Local-mode PM4K is written with `allow_insecure=always`, a deliberate relaxation required to reach a plain-HTTP LAN Plex server; use a token-authorized remote/account link instead if that relaxation is unacceptable for a given room.
- **NextPVR** (`pvr.nextpvr`): `NEXTPVR_HOST`/`NEXTPVR_PORT`/`NEXTPVR_PROTOCOL`/`NEXTPVR_INSTANCE_NAME` plus `NEXTPVR_PIN`. Without them, provisioning creates a disabled, credential-free placeholder client instance when none exists, so Kodi can keep the add-on installed and enabled without repeatedly trying its generated `127.0.0.1:8866` default. Existing instances are preserved when those values are omitted on a later run.
- **Home Assistant Weather** (`weather.ha`): `HOME_ASSISTANT_URL`/`HOME_ASSISTANT_WEATHER_ENTITY`/`HOME_ASSISTANT_SUN_ENTITY` plus `HOME_ASSISTANT_TOKEN`.
- **TMDb Helper** (`plugin.video.themoviedb.helper`): `OMDB_API_KEY` and/or `MDBLIST_API_KEY` populate metadata keys; Trakt and TMDb user-account linking remain interactive and optional either way.

### Arctic Fuse 3 activation

`skin.arctic.fuse.3` is deployed and set active (`lookandfeel.skin`) by the same run, alongside the regional baseline (`videoplayer.adjustrefreshrate`=On start/stop, `videoplayer.usedisplayasclock`=Off) — no separate manual skin-activation step remains.

### Regional verification

The device verifies its own Pacific/English-US baseline over localhost and reports it in the audit file rather than requiring a manual on-screen check:

- `regional.localtime.status` compares `/etc/localtime` against the requested zone, accepting either a symlink into zoneinfo or a byte-identical copy (`regional.localtime.match`) — both CoreELEC layouts are recognized.
- `regional.date_offset.status` compares the device's reported UTC offset against the expected one from `date +%Z%z`. `/etc/localtime`, its zoneinfo content, and Kodi's own timezone setting are checked strictly first (above); `date +%Z%z` is only a BusyBox capability question on top of that. A malformed or unavailable `date +%Z%z` output is advisory only and reads `unavailable` — it never fails a deployment by itself (BusyBox `date` formatting is not guaranteed). But once the output is well-formed, a genuine offset mismatch (`regional.date_offset.status=mismatch`) **is** a verification failure that counts toward `verification_failures` and triggers rollback like any other failed check. Confirm the displayed date/time on screen if this reads `unavailable`.

### Add-on enabling

Add-ons are unzipped while Kodi is stopped, so Kodi decides on its own start which of them it will enable. The device asks Kodi over localhost JSON-RPC to enable every add-on it reports installed-but-disabled, then asks Kodi again, and repeats while the answer keeps changing — one pass is not enough, because Kodi leaves an add-on disabled when a module it depends on is not enabled yet, and the deployment manifest lists primary add-ons before those modules.

- `addon.<id>.enable_attempted=1` means this run asked Kodi to enable that add-on in at least one pass; `addon.<id>.enabled` is what Kodi reported afterwards, never what was asked.
- `addon_enable_unresolved=<ids>` appears only when Kodi still reported an add-on disabled after the passes stopped changing anything. Those add-ons are already counted in `verification_failures` and the run rolls back; the line names them so the failure is actionable. Check the add-on's dependencies on the device (**Settings → Add-ons → My add-ons**) and re-run `--target`.

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
3. Complete any Emby, PM4K account-mode, or YouTube items that still report `authorization-required` or `manual-required`; the helper above can assist, but you may still need to finish on the TV or in another browser.
4. Complete any PM4K/NextPVR/HA Weather/TMDb Helper items still listed as `installed-unconfigured` in the provisioning audit report, or `skipped`/`failed` in the post-deployment report, by supplying the missing values and re-running the appropriate command.

Record room-specific integration choices alongside the relevant device.

During Home Assistant setup, finish the network guide's [reachability checks](network/pfsense-plus-26.07-onboarding.md#6-validate-home-assistant-reachability) using each device's recorded endpoint.

## Reuse across rooms

Keep reusable scripts in [code](../code/README.md) and deployable settings in [config](../config/README.md). [`provision-coreelec.sh`](../provision-coreelec.sh) applies the shared configuration to any matching device; room and device-specific values (target address, room video/audio settings, hardware validation) stay outside it and are supplied per device, as described above.
