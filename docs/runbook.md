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

## 3. Apply room-specific connections and settings

Follow the room's device documents before the first playback tests. Configure the display inputs, audio return path, receiver, and remote/control behavior for that installation. Select playback-device video and audio options according to the actual display and complete signal path.

## 4. Validate and record results

Complete both the shared device checklist and the room checklist. Record the date, installed versions, test titles/tracks, observed display and receiver modes, and any blocked checks in the room documentation. An unchecked item is not evidence of a pass.

Keep removable media in use while applicable tests remain unresolved. A temporary transport limitation must be recorded and retested after the limiting hardware is replaced.

## 5. Back up and optionally migrate

After validation, create a backup and copy it to another system. If using an Ugoos, follow the shared guide's optional eMMC migration procedure only after the applicable shared and room checks pass. Preserve the proven microSD card as recovery media.

## 6. Add services and the interface

After the baseline passes, create a CoreELEC backup before installing additional software. Where these components are selected for the room, configure them in this order:

1. Final Kodi video and room audio settings.
2. Home Assistant network reachability, monitoring, suspend, and wake.
3. Emby for Kodi library integration.
4. Plex for on-demand browsing without Kodi-library synchronization.
5. YouTube playback and casting strategy.
6. Arctic Fuse 3 and its widgets.

Installing the skin last keeps hardware, EDID, Dolby Vision, and add-on problems separable. Record room-specific integration choices alongside the relevant device.

During Home Assistant setup, finish the network guide's [reachability checks](network/pfsense-plus-26.07-onboarding.md#6-validate-home-assistant-reachability) using each device's recorded endpoint.

## Reuse across rooms

Keep reusable scripts in [code](../code/README.md) and deployable settings in [config](../config/README.md). Share configuration by device model/platform, then supply explicit room and device values when deployment tooling is added. The documentation currently provides manual procedures; no deployment automation is implemented.
