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
- symbolic managed-device hostnames, network roles, and integrations;
- backup and recovery notes that belong to the installed room.

Keep real MAC addresses and reserved host addresses in pfSense or a private
inventory, not in repository room documentation.

## 2. Wire and configure device and network prerequisites

Install the hardware according to the room documents. For Ugoos/CoreELEC rooms,
use the
[shared Ugoos setup guide](devices/ugoos-am6b-plus/coreelec-21.3.md) for media
preparation, first boot, and shared device validation. Configure the display,
receiver, remote, and control prerequisites needed for the installed signal
path and integrations. Defer room-specific playback settings until after the
room package is installed.

Use wired Ethernet for every network-managed device.

Use the [shared network onboarding guide](network/pfsense-plus-26.07-onboarding.md)
for DHCP reservations, local DNS, and the required firewall rules.

- Streaming devices such as Ugoos use LAN.
- Home Assistant, Sony displays, and Denon receivers use IoT.
- Use the [shared Wake-on-LAN guide](network/wake-on-lan.md) only for optional
  wake workflows outside the always-awake Ugoos lifecycle.

## 3. Provision the Ugoos baseline, add-ons, and restricted gateway

For Ugoos/CoreELEC rooms, follow
[Provision a Ugoos CoreELEC system](operations/provision-ugoos.md). That guide
covers the shared order: CoreELEC wizard, DHCP reservation and DNS, `.env`
preparation, baseline provisioning, post-deployment add-on checks, and
restricted lifecycle gateway deployment before Home Assistant integrations and
package installation.

## 4. Configure native Home Assistant integrations and stable IDs

Add the room's native integrations after the devices have their managed network
identities. For theater this includes Sony BRAVIA, Kodi, and Denon as
applicable. Confirm the exact entity IDs expected by the room package before
enabling automations.

## 5. Install any room package

Copy the required SSH/config assets and package YAML into Home Assistant, enable
packages if needed, run `ha core check`, then restart or reload Home Assistant
as required by the selected guide. For the theater lifecycle package, follow
[Ugoos Kodi lifecycle Home Assistant operations](home-assistant/ugoos-kodi-lifecycle.md).

## 6. Apply room playback settings, verify, and back up device state

Apply the room-specific display, Dolby Vision, resolution whitelist, and audio
playback settings. Then verify the installed room behaves as documented:
playback, device control, network reachability, and Home Assistant automations
all match the selected guides. Create backups and copy them to another system.
For Ugoos devices, keep the proven removable media as recovery media until any
optional migration is complete.
