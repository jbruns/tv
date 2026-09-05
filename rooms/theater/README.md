# Theater

This room contains the original Ugoos/Sony pilot, assigned here based on the workspace context. Follow the [shared runbook](../../docs/runbook.md), then apply the device guides below. The original guide recorded **2026-09-05** as its verification date; completed test results have not yet been recorded here.

## Devices

| Device | Role | Room-specific guide |
|---|---|---|
| Ugoos AM6B+ | CoreELEC 21.3 Omega, Amlogic-ng playback | [Ugoos](devices/ugoos-am6b-plus.md) |
| Sony XR-65A90J | Display and audio return | [Sony](devices/sony-xr-65a90j.md) |
| Denon AVR-X4700H | Audio system | [Denon](devices/denon-avr-x4700h.md) |
| AVPro Edge AC-EX40-444-PLUS-T/R | Initial ARC-only extender | [AVPro](devices/avpro-ac-ex40-444-plus.md) |
| AVPro Edge AC-EX40-444-PLUS-T2/R2 | Planned eARC extender replacement | [AVPro](devices/avpro-ac-ex40-444-plus.md) |

## HDMI topology

```text
Ugoos AM6B+ HDMI OUT
    -> Sony HDMI IN 4 (Dolby Vision video and source audio)

Sony HDMI IN 3 (eARC/ARC)
    -> AVPro receiver at television
    -> Category cable
    -> AVPro transmitter at equipment rack
    -> Denon MONITOR 1 HDMI OUT (eARC)
```

The Ugoos video signal does not traverse the Denon or AVPro extender. The Sony receives the original video and returns audio to the Denon over eARC.

The existing AVPro `T/R` hardware supports ARC, not eARC. It can be used temporarily, but it cannot transport lossless Dolby TrueHD/Atmos from the television. Full validation of TrueHD/Atmos must wait for the `T2/R2` revision.

## Setup order

1. Prepare removable media with the [shared Ugoos guide](../../docs/devices/ugoos-am6b-plus/coreelec-21.3.md).
2. Wire the room as above and apply the [Sony settings](devices/sony-xr-65a90j.md), [Denon connection](devices/denon-avr-x4700h.md), and [AVPro stage requirements](devices/avpro-ac-ex40-444-plus.md).
3. Continue the shared Ugoos first boot and wizard, then apply the [theater Ugoos choices](devices/ugoos-am6b-plus.md).
4. Complete the shared Ugoos checklist and the room checks below before considering eMMC migration.
5. Back up and continue the shared runbook's service setup sequence.

## Room validation

- [ ] Sony-remote navigation works through HDMI-CEC, or the Ugoos remote works as intended.
- [ ] CoreELEC Dolby Vision controls appear while directly connected to the A90J.
- [ ] A known HDR10 title triggers the Sony's HDR picture mode.
- [ ] A known Dolby Vision Profile 5 title triggers Dolby Vision.
- [ ] A known Dolby Vision Profile 7 FEL title plays without purple/green video.
- [ ] SDR, HDR10, and Dolby Vision switch cleanly in both directions.
- [ ] After T2/R2 installation, the television reports an active eARC audio system and the Denon appears in the refreshed BRAVIA Sync list.
- [ ] After T2/R2 installation, the Denon identifies a known TrueHD/Atmos test track as Dolby Atmos/TrueHD rather than Dolby Digital Plus or Dolby Surround.

Lossless audio validation is blocked while the original T/R pair is installed. Keep that test pending until the T2/R2 replacement is installed; an ARC-only trial does not complete the final eARC validation.

## Installation record

| Field | Value |
|---|---|
| Installed extender revision | Confirm during installation; original guide lists T/R as initial and T2/R2 as planned. |
| Hostname | Proposed: `ugoos-theater`; confirm actual value. Original pilot example was `ugoos-pilot`. |
| Wired MAC / DHCP reservation | To be recorded from the device. |
| Test date, titles/tracks, and observed modes | To be recorded. |
| Backup location | To be recorded. |

Store future deployable room values using the [configuration layout](../../config/README.md).
