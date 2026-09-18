# Provision a Ugoos CoreELEC system

Use this workflow after the device has been prepared with the shared CoreELEC
image and first-boot wizard. For media preparation and bootstrapping, use the
[shared device guide](../devices/ugoos-am6b-plus/coreelec-21.3.md). For the
platform boundary and migration constraint, read the
[Ugoos AM6B+ CoreELEC 21.3 system decision](../decisions/ugoos-coreelec-21.3-system.md).
For unique settings, use the selected room's Ugoos guide, such as the current
[Theater Ugoos guide](../../rooms/theater/devices/ugoos-am6b-plus.md).

## Full baseline and scoped maintenance

An invocation without `--component` applies the full shared baseline. This
remains true for the legacy `--addon ID` form: it filters the locked artifact
selection but does not narrow shared settings. Explicit components narrow
Kodi/add-on mutation, backup, verification, and reporting to the dependency-
expanded effective scope. `services` adds `addons`; `skin` adds `core` and
`addons`; `room` adds `core`; `core`, `cec`, and `addons` have no dependencies.
`baseline` expands to `core,cec,addons,services,skin`; it never includes
`room`. `room` is opt-in and must be requested explicitly with
`--component room --room NAME`.

The exact ownership and dependency tables are in
[the configuration contract](../../config/README.md#provisioning-component-contract).
Typical invocations are:

```bash
# Full baseline
./provision-coreelec.sh --target <hostname-or-IP>

# CEC settings only
./provision-coreelec.sh --target <hostname-or-IP> --component cec

# Skin plus its automatically added core and add-ons dependencies
./provision-coreelec.sh --target <hostname-or-IP> --component skin

# CEC plus one locked add-on; --addon implicitly requests addons
./provision-coreelec.sh --target <hostname-or-IP> \
  --component cec --addon script.plexmod
```

When the Home Assistant lifecycle package controls the target, turn on
`input_boolean.ugoos_theater_keep_kodi_running` and confirm Kodi is running
before provisioning maintenance. Keep the override on until the corrected
package has actually been installed, restarted, and live lifecycle validation
has reached its explicit disable step. Repository changes alone do not mean
the corrected package or CEC policy is live.

For the theater CEC-only rollout, use:

```bash
./provision-coreelec.sh \
  --target ugoos-theater \
  --component cec \
  --yes
```

The committed report must include:

```text
components.requested=cec
components.effective=cec
components.dependencies_added=none
deployment_state=committed
verification_result=pass
verification_failures=0
cec.tv_off_action.status=ok
cec.activate_source.status=ok
cec.wake_devices.status=ok
cec.standby_devices.status=ok
cec.standby_tv_on_pc_standby.status=ok
```

It must not contain Arctic Fuse, service, room, or add-on verdicts. The
provisioner retries complete device-local verification samples for up to 60
seconds (13 samples separated by 5 seconds) so selected runtime state can
converge; it commits only a complete passing sample.

### Applying a room's display and audio state

The `room` component writes the display and audio settings recorded in
`config/rooms/<room>/room.conf`. It is opt-in — never included by a bare
`--target` run or by `--component baseline` — and requires an explicit room
name.

**Before running this, the display must be powered on and switched to this
device's HDMI input.** The provisioner probes the running Kodi over JSON-RPC
immediately before it changes anything, to resolve the configured resolution
label and confirm the display still offers every whitelisted mode. If the
display is off or on another input, the probe fails and the run aborts with
nothing changed on the device except the administrator key — no backup taken,
no settings written.

```bash
./provision-coreelec.sh --target ugoos-theater --component room --room theater
```

Because `room` depends on `core` (the whitelist only takes effect once
`core`'s refresh-rate matching is in place), the effective plan is `core,room`,
not `room` alone. A committed report should show:

```text
components.requested=room
components.effective=core,room
components.dependencies_added=core
deployment_state=committed
verification_result=pass
verification_failures=0
room.display.whitelist.status=ok
room.display.resolution.status=ok
room.dolbyvision.status=ok
room.audio.passthrough.status=ok
room.audio.ac3.status=ok
room.audio.eac3.status=ok
room.audio.dts.status=ok
room.audio.truehd.status=ok
room.audio.dtshd.status=ok
```

Every `room.*.status` must read `ok`; any other value blocks the commit. A
`mismatch` means Kodi reports something other than what was written — check
for a manual UI change after the fact. `unsupported` on
`room.display.whitelist` means Kodi answered but reported an empty whitelist —
recheck that the display is still powered on and on the right input, then
re-run. `unobservable` means Kodi never answered for that setting at all, or,
for `room.display.resolution` specifically, that no resolution index was ever
resolved for this run. The full report vocabulary, the configuration keys, the
display mode string format, and the Dolby Vision inversion are documented in
the [room desired-state reference](../devices/ugoos-am6b-plus/room-desired-state.md).

Scoped maintenance uses the existing shared transaction process unchanged.
Persistent selected-scope failure triggers automatic rollback. If the report
shows `pending-verification` or `incomplete-rollback`, run its exact
`recovery.command`, which uses `--finalize-deployment` or
`--rollback-deployment`; do not manually remove the transaction pointer or
staging directory. Rollback restores and verifies only the paths captured for
the effective scope, while the dated backup remains on the device.

### Add-ons nobody locked

Any run whose effective scope includes `addons` inventories the add-ons
installed on the device that no `ADDON_ARTIFACT` record names, by reading the
device's user add-on directory rather than by asking Kodi about the IDs it was
already given. Asking only about locked IDs can never surface an add-on nobody
locked, which is how a stray repository sat on a device unnoticed.

```text
addon_inventory.metadata.generic.albums=unmanaged_allowed
addon_inventory.repository.kodinerds=unmanaged
addons_unmanaged=1
addons_unmanaged_ids=repository.kodinerds
addons_unmanaged_allowed=1
```

Kodi installs its own metadata scrapers on first boot, so an unmanaged add-on
is a normal state rather than a fault. `ADDON_UNMANAGED_ALLOWED` in the shared
profile acknowledges the add-ons expected on every device of that profile:
they are still inventoried, but they do not raise `addons_unmanaged`. The
count is meant to stay at zero, so that a non-zero value means something
arrived that nobody decided on.

The inventory observes and does not judge. An unmanaged add-on never raises
`verification_failures` and never rolls back a deployment; deciding what to do
about one is an operator's call. Add-ons bundled with the CoreELEC image are
out of scope, because they belong to the image rather than to the deployment.

### Shared library and file-list behavior

The `core` component owns the generic Kodi library and file-list preferences
that every device of a profile shares, independent of the skin and of the
room. Each preference is verified on its own report key against the value Kodi
reports over JSON-RPC, rather than against the file that was written:

```text
library.filelists.showparentdiritems.expected=false
library.filelists.showparentdiritems.observed=false
library.filelists.showparentdiritems.status=ok
library.videolibrary.tvshowsselectfirstunwatcheditem.status=ok
```

The managed set is `filelists.showparentdiritems`,
`filelists.showextensions`, `filelists.showaddsourcebuttons`,
`videolibrary.showallitems`, `videolibrary.tvshowsselectfirstunwatcheditem`,
`videolibrary.flattentvshows`, `videolibrary.ignorevideoextras`,
`videolibrary.ignorevideoversions`, and `input.enablemouse`.

Drift in any one of them fails verification, and the failing key names the
setting that drifted rather than collapsing nine checks into a single opaque
zero. `lookandfeel.soundskin` is deliberately not in this set: it is the one
Kodi default the skin owns, and `skin` continues to verify it.

### Where the TV Shows and Movies hubs land

The `skin` component owns where the two library hubs navigate. Selecting
TV Shows opens `videodb://tvshows/titles/` and selecting Movies opens
`videodb://movies/titles/` — the flat title lists, not the category roots.
Both hubs also carry `Shortcut.Target=videos`.

The target is not optional. Arctic Fuse builds
`ActivateWindow(target, path, return)` only when the target is set; with an
empty target it executes the path as a bare Kodi builtin, so a library path
with no target silently does nothing. Drift in either the path or the target
fails `arctic_fuse.tv_hub_configured` or `arctic_fuse.movies_hub_configured`.

### What "off" means for a skin setting

Arctic Fuse settings that the baseline disables are verified as absent *or*
present-but-empty, not as strictly absent.

This is not leniency. Kodi resolves an unset `Skin.String` to the empty
string, and the skin's own conditions are written as `String.IsEmpty(...)`, so
absent and empty are the same state to Arctic Fuse. Kodi also writes a node
for every skin string the skin merely references — empty, and with the id
lowercased — so `addon_data/skin.arctic.fuse.3/settings.xml` accumulates
entries like `homeswitcher.1103.shortcut.target` with no value. Requiring
literal absence asks for a state no running device can hold: the provisioner
removes the key, Kodi recreates it on the next skin load, and verification
fails on a difference that has no effect.

A non-empty value still fails. A stale Plex spotlight, a Weather tile aimed at
a previous destination, or a hub 1104 somebody actually enabled are all still
caught.

One consequence worth knowing when reading a report: `HomeSwitcher.1104.Name`,
`.Mode` and `.Icon` are not verified at all. Arctic Fuse writes them on every
skin load — `Name` from `$LOCALIZE[636]` ("Custom"), `Mode` as `Standard` from
its own `skinvariables-startup.json` — and they do nothing while
`HomeSwitcher.1104.Toggle` is empty, which is what actually keeps the hub off
the home screen.


   and the selected room's Ugoos guide.
2. Prepare and boot removable media using the
   [shared device guide](../devices/ugoos-am6b-plus/coreelec-21.3.md).
3. Complete the CoreELEC wizard with wired networking and SSH.
4. Create the pfSense DHCP reservation and local DNS record.
5. Copy [`.env.example`](../../.env.example) to `.env`, set mode `600`, and
   populate required secrets.

   ```bash
   cp .env.example .env
   chmod 600 .env
   ```

   Input rules and supported values are documented in
   [config/README.md](../../config/README.md).
6. Run:

   ```bash
   ./provision-coreelec.sh --check-config
   ```

7. Run:

   ```bash
   ./provision-coreelec.sh --check-artifacts
   ```

8. Run:

   ```bash
   ./provision-coreelec.sh --target <hostname-or-IP>
   ```

9. Review the redacted report and resolve any rollback before continuing.
   After Kodi JSON-RPC first becomes reachable, the provisioner allows up to
   60 seconds for skin and add-on startup state to converge. It commits only
   after a complete verification pass; a persistent mismatch still rolls the
   transaction back.
   When applying a reduced add-on baseline to an existing installation,
   uninstall add-ons no longer present in the artifact lock and remove their
   saved add-on data first. The provisioner installs and replaces selected
   artifacts but does not remove add-ons omitted from the lock.
10. Run these immediate Arctic Fuse 3 convergence checks:

    - Confirm Home, TV Shows, Movies, Plex, PVR (when configured), and
      Add-ons appear in order.
    - Confirm TV and Movies each show four managed widgets.
    - Confirm the redacted report shows `arctic_fuse.status=ok`.

    These checks do not depend on Emby. The Trakt widgets stay empty until
    the sign-in and sync in the next step complete.
11. Run:

    ```bash
    ./configure-coreelec-addons.sh --target <hostname-or-IP>
    ```

    Then invoke only the desired guarded interactive add-on workflows. For
    example, to run each currently supported guided flow:

    ```bash
    ./configure-coreelec-addons.sh --target <hostname-or-IP> --interactive \
      --addon script.plexmod \
      --addon plugin.service.emby-next-gen
    ```

    ### Reading the configuration report

    The report banner is `coreelec-addon-configuration-report-2`. Each
    selected add-on emits two independent status fields:

    - `addon.<id>.config_status` covers artifact and configuration work owned
      by provisioning: `configured`, `already-configured`, `skipped`,
      `failed`, `dry-run`.
    - `addon.<id>.onboarding_status` covers authentication and
      synchronization owned by the user: `not-required`, `complete`,
      `pending-authentication`, `pending-sync`, `manual-required`, `dry-run`,
      plus two reserved values currently emitted by nothing:
      `unobservable` and `failed`.

    Only `onboarding_status=complete` means an add-on is finished;
    `config_status=configured` on its own never does. The previous single
    `addon.<id>.status` field is gone. The mapping from it is in the
    [onboarding and restart contract's migration table](../superpowers/specs/2026-09-16-addon-onboarding-restart-sequencing-design.md#migration-from-coreelec-addon-configuration-report-1).
    The full per-add-on completion ladder, including which vocabulary values
    each add-on can actually produce, is in the
    [add-on onboarding and restart contract](../devices/ugoos-am6b-plus/addon-onboarding-contract.md#completion-signals).

12. Re-run `./configure-coreelec-addons.sh` and read
    `addon.plugin.service.emby-next-gen.onboarding_status`.

    `pending-sync` means the library sync has not finished, and the Trakt
    Popular TV Shows and Trakt Weekend Box Office widgets are expected to be
    empty. `complete` means every attempted library finished syncing.

    The stable Emby 11.1.27 client still requires manual sign-in, and the
    server/library metadata supplies the Trakt tags after synchronization. The
    onboarding order, restart checkpoints, and completion signals behind these
    states are defined in the
    [add-on onboarding and restart contract](../devices/ugoos-am6b-plus/addon-onboarding-contract.md).
13. Run `./configure-kodi-lifecycle.sh` with the Home Assistant controller
    public key and matching identity:

    ```bash
    ./configure-kodi-lifecycle.sh \
      --target <hostname-or-IP> \
      --controller-public-key "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519.pub" \
      --controller-identity "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519"
    ```

    Use the
    [Ugoos Kodi lifecycle guide](../home-assistant/ugoos-kodi-lifecycle.md)
    for key installation, verification, rollback, and recovery steps.
14. Add the room's native Home Assistant integrations and set the stable
    entity IDs required by the selected package before enabling that package.
    For theater this includes Sony BRAVIA and Kodi, with the exact IDs
    documented in the
    [lifecycle guide](../home-assistant/ugoos-kodi-lifecycle.md).
15. Install the SSH alias and room package in Home Assistant, following the
    file locations in the
    [lifecycle guide](../home-assistant/ugoos-kodi-lifecycle.md). Then restart
    Home Assistant and verify package state.

    ```bash
    ha core check
    ```

16. With the display powered on and switched to this device's HDMI input,
    apply the room's display and audio desired state (see
    [Applying a room's display and audio state](#applying-a-rooms-display-and-audio-state)
    above):

    ```bash
    ./provision-coreelec.sh --target <hostname-or-IP> --component room --room <room>
    ```

17. Verify room playback, device control, network reachability, and Home
    Assistant automations.
18. Create a CoreELEC backup before optional eMMC migration.

## Current rollout limits

Component scoping does not fix weather data or remux buffering. Provisioning
installs and replaces the add-ons the lock names, and reports the ones it does
not, but it never removes an add-on: clearing an unmanaged add-on is a
deliberate manual act. Emby sign-in
and the documented Trakt tag/library synchronization remain manual. The Sony
and Denon configuration boundary is unchanged: `room` configures the CoreELEC
playback host only. The onboarding order, restart checkpoints, and
completion signals are defined in the
[add-on onboarding and restart contract](../devices/ugoos-am6b-plus/addon-onboarding-contract.md).
