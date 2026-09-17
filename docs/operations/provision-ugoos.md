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
`addons`; `core`, `cec`, and `addons` have no dependencies. `baseline` expands
to all five implemented components. `room` is reserved and currently fails as
unimplemented rather than applying an empty room plan.

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

Scoped maintenance uses the existing shared transaction process unchanged.
Persistent selected-scope failure triggers automatic rollback. If the report
shows `pending-verification` or `incomplete-rollback`, run its exact
`recovery.command`, which uses `--finalize-deployment` or
`--rollback-deployment`; do not manually remove the transaction pointer or
staging directory. Rollback restores and verifies only the paths captured for
the effective scope, while the dated backup remains on the device.

## Order of operations

1. Read the
   [CoreELEC system decision](../decisions/ugoos-coreelec-21.3-system.md)
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

16. Apply only the room-specific Dolby Vision, whitelist, and audio settings.
17. Verify room playback, device control, network reachability, and Home
    Assistant automations.
18. Create a CoreELEC backup before optional eMMC migration.

## Current rollout limits

Component scoping does not configure the reserved room desired state and does
not fix weather data or remux buffering. Emby sign-in and the documented Trakt
tag/library synchronization remain manual. The Sony and Denon configuration
boundary is unchanged. The onboarding order, restart checkpoints, and
completion signals are defined in the
[add-on onboarding and restart contract](../devices/ugoos-am6b-plus/addon-onboarding-contract.md).
