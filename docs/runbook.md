# Shared room setup runbook

Use this workflow for every room. Shared guides define reusable procedures; the
room files under `rooms/<room>/` record only the installed equipment,
connections, settings, network placement, and Home Assistant follow-on work.

## 1. Document the room

Create or update `rooms/<room>/README.md` and the matching
`rooms/<room>/devices/` entries. Record:

- installed playback, display, audio, control, and transport hardware;
- physical HDMI, audio, and network connections;
- device-specific settings that matter for the installed room;
- managed-device hostnames, wired MACs, network placement, and integrations;
- backup and recovery notes that belong to the installed room.

## 2. Wire and configure the devices

Install the hardware according to the room documents. For Ugoos/CoreELEC rooms,
use the
[shared Ugoos setup guide](devices/ugoos-am6b-plus/coreelec-21.3.md) for media
preparation, first boot, and shared device validation. Apply only the
room-specific display, receiver, remote, Dolby Vision, whitelist, and audio
settings that the room documents require.

Use wired Ethernet for every network-managed device.

## 3. Onboard every network-managed device

Use the [shared network onboarding guide](network/pfsense-plus-26.07-onboarding.md)
for DHCP reservations, local DNS, and the required firewall rules.

- Streaming devices such as Ugoos use LAN.
- Home Assistant, Sony displays, and Denon receivers use IoT.
- Use the [shared Wake-on-LAN guide](network/wake-on-lan.md) only for optional
  wake workflows outside the always-awake Ugoos lifecycle.

## 4. Provision a Ugoos through `docs/operations/provision-ugoos.md`

For Ugoos/CoreELEC rooms, follow
[Provision a Ugoos CoreELEC system](operations/provision-ugoos.md). That guide
covers the shared order: CoreELEC wizard, DHCP reservation and DNS, `.env`
preparation, baseline provisioning, post-deployment add-on checks, and
restricted lifecycle gateway deployment before Home Assistant integrations and
package installation.

## 5. Configure native Home Assistant integrations

Add the room's native integrations after the devices have their managed network
identities. For theater this includes Sony BRAVIA, Kodi, and Denon as
applicable. Confirm the exact entity IDs expected by the room package before
enabling automations.

## 6. Install any room package

Copy the required SSH/config assets and package YAML into Home Assistant, enable
packages if needed, run `ha core check`, then restart or reload Home Assistant
as required by the selected guide. For the theater lifecycle package, follow
[Ugoos Kodi lifecycle Home Assistant operations](home-assistant/ugoos-kodi-lifecycle.md).

## 7. Verify operation and back up device state

Verify the installed room behaves as documented: playback, device control,
network reachability, and Home Assistant automations all match the selected
guides. Then create backups and copy them to another system. For Ugoos devices,
keep the proven removable media as recovery media until any optional migration
is complete.
