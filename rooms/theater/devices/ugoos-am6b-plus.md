# Theater: Ugoos AM6B+

Install using the [shared CoreELEC 21.3 guide](../../../docs/devices/ugoos-am6b-plus/coreelec-21.3.md). Apply the following room-specific choices alongside that procedure.

## Connections and identity

- HDMI output connects directly to **Sony HDMI IN 4**; video does not pass through the receiver or extender.
- Use wired Ethernet and the supplied power adapter.
- Proposed hostname: `ugoos-theater`. Confirm and record the actual hostname, wired MAC, and DHCP reservation in the [room record](../README.md#installation-record).
- Onboard through [pfSense Plus 26.07](../../../docs/network/pfsense-plus-26.07-onboarding.md), leaving CoreELEC on DHCP. Add the guide's device network record here once this unit's MAC and mapping are known.
- Network: LAN, `172.16.0.0/16` and `2001:db8:1::/64`; individual addresses remain to be recorded.
- Remote model and use of Bluetooth remain to be confirmed. Use the shared guide's matching `remote.conf` or UR-01 Bluetooth steps where applicable.

## Video

Set Dolby Vision mode to **TV-led / display-led** after applying the [Sony settings](sony-xr-65a90j.md). Add all available 2160p modes reported by the Sony to Kodi's resolution whitelist; do not add unreported modes.

Keep custom EDID overrides and Dolby Vision colorimetry startup scripts unset. They are unnecessary for the baseline with the Ugoos directly connected to a correctly configured A90J.

## Audio during the ARC-only interim

While the original AVPro T/R pair remains installed, do not treat a failed TrueHD/Atmos test as a CoreELEC defect. ARC is the limiting link.

After the T2/R2 extender is installed and the television reports an active eARC audio system, configure Kodi for HDMI passthrough and enable the codecs supported by the Denon, including Dolby Digital, Dolby Digital Plus, DTS, Dolby TrueHD, DTS-HD, and Atmos carried within the source bitstream. Keep `Sync playback to display` off because it conflicts with passthrough.

## Validation and follow-on setup

For Home Assistant wake control from IoT, follow the [shared WoL procedure](../../../docs/network/wake-on-lan.md) using destination `172.16.99.99` and this unit's real wired MAC. Record the tested power state and UDP port here; wake support has not yet been validated for this unit.

Complete both the shared guide's validation checklist and the [theater checklist](../README.md#room-validation) before eMMC migration. After a backup, follow the [remaining room-specific service work](../../../docs/runbook.md#7-remaining-room-specific-service-work); the shared add-ons are already installed and configured by [`provision-coreelec.sh`](../../../docs/runbook.md#3-provision-the-shared-coreelec-baseline). Home Assistant power behavior and additional applications remain follow-on work.
