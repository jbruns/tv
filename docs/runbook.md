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

Install the hardware according to the room documents. Configure the display,
receiver, remote, and control prerequisites needed for the installed signal
path and integrations.

Use wired Ethernet for every network-managed device.

Use the [shared network onboarding guide](network/pfsense-plus-26.07-onboarding.md)
for DHCP reservations, local DNS, and the required firewall rules.

- Streaming devices such as Ugoos use LAN.
- Home Assistant, Sony displays, and Denon receivers use IoT.
- Use the [shared Wake-on-LAN guide](network/wake-on-lan.md) only for optional
  wake workflows outside the always-awake Ugoos lifecycle.

## 3. Provision the Device

For Ugoos/CoreELEC rooms, add the room's Room Overlay and follow
[Provision a Device](operations/provision-a-device.md): card imaging, the
first-boot wizard, First Contact, `apply`, and the Guided Actions. The Room
Overlay carries the room's Display, Dolby Vision, resolution whitelist and
audio passthrough Desired State, so one `apply` provisions all of it; the
[Profile reference](reference/profile.md) describes how to declare them.

`.env` must hold Home Assistant's lifecycle public key before `apply`, so create
that key first, as section 2 of the
[lifecycle guide](home-assistant/ugoos-kodi-lifecycle.md) describes.

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

## 6. Verify and keep recovery media

Verify the installed room behaves as documented: playback, device control,
network reachability, and Home Assistant automations all match the selected
guides. Recovery is re-imaging the card and provisioning again, so keep the
proven removable media until any optional eMMC migration is complete.
