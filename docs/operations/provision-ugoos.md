# Provision a Ugoos CoreELEC system

Use this workflow after the device has been prepared with the shared CoreELEC
image and first-boot wizard. For media preparation and bootstrapping, use the
[shared device guide](../devices/ugoos-am6b-plus/coreelec-21.3.md). For the
platform boundary and migration constraint, read the
[Ugoos AM6B+ CoreELEC 21.3 system decision](../decisions/ugoos-coreelec-21.3-system.md).
For unique settings, use the selected room's Ugoos guide, such as the current
[Theater Ugoos guide](../../rooms/theater/devices/ugoos-am6b-plus.md).

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

12. After the manual Emby sign-in completes and the library sync finishes,
    confirm the Trakt Popular TV Shows and Trakt Weekend Box Office widgets
    populate.

    The stable Emby 11.1.27 client still requires manual sign-in, and the
    server/library metadata supplies the Trakt tags after synchronization. An
    empty Trakt widget after a successful configuration report is an Emby
    tag/sync issue, not playlist-definition convergence.
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
