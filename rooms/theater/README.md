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
3. Complete the CoreELEC first-boot wizard with wired networking and SSH enabled.
4. Create the DHCP reservation and DNS record for `ugoos-theater`; record the actual address below.
5. Run shared baseline provisioning and confirm CEC Ignore in the audit report.
6. Deploy the restricted lifecycle gateway with `configure-kodi-lifecycle.sh`.
7. Add Sony and Kodi Home Assistant integrations with the package entity IDs, then install the theater HA package.
8. Apply playback configuration.
9. Complete lifecycle/idle acceptance below before room rollout or eMMC migration.
10. Back up and continue any remaining service setup.

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


## Ugoos lifecycle acceptance record

Do not mark results passed without a live device/Home Assistant test and date. Local repository tests exercise package/CLI fixtures and syntax, not the live HA scheduler or theater devices.

| Field/check | Recorded value / result |
|---|---|
| Sony entity ID | Pending live HA setup; package expects `media_player.sony_xr_65a90j`. |
| Kodi entity ID | Pending live HA setup; package expects `media_player.kodi_theater`. |
| Ugoos lifecycle DNS alias/address | Pending DHCP/DNS record; package expects `ugoos-theater`. |
| Controller public-key marker installed date | Pending; marker is `homeassistant-ugoos-kodi-lifecycle`. |
| Server host-key authentication | Pending; record independent fingerprint provenance and date before controller authorization or known-host bootstrap. |
| CEC TV-off action observed value | Pending live baseline report; expected observed value `36028` and `cec.tv_off_action.status=ok`. |
| Stop-policy enabled/opt-out | Pending; theater package default is enabled with no opt-out (`stop_when_display_off: true`). |
| Idle timeout | Pending; package default is 30 minutes via `input_number.ugoos_theater_idle_timeout_minutes`. |
| 24-hour display-off reachability result | Pending; record ping and SSH result/date while the Sony is off and Kodi may be stopped. |
| Sony-off -> Kodi-stop result and elapsed time | Pending; expect stop only after a fresh continuous 60-second Sony-off interval. |
| Sony-on -> Kodi-ready result and elapsed time | Pending; expect `start`, lifecycle `running`, and Kodi JSON-RPC/UI ready within 90 seconds. |
| Idle -> Sony-off -> Kodi-stop result | Pending; expect 30 minutes idle, Sony off confirmation within 30 seconds, then normal 60-second Kodi stop path. |
| Keep-running override result | Pending; expect idle-driven Sony power-off but Kodi remains running while `input_boolean.ugoos_theater_keep_kodi_running` is on. |
| HA restart result | Pending; expect stale idle evidence cleared and fail-awake reconciliation. |
| Package reload result | Pending; reload all package components, observe a fresh epoch, and confirm no queued stop reuses the old off interval. |
| Ugoos reboot result | Pending; expect Kodi starts normally and HA applies a new post-restart 60-second off interval only if Sony is still off. |
| Restricted-command denial result | Pending; `id` must exit `2`, emit no stdout, and print exactly `Allowed commands: start, stop, status` on stderr. Separately verify no shell, file transfer, PTY, forwarding, or non-Kodi control; disconnect/authentication/deadline failures do not pass this check. |
| Sony failure episode | Pending; inject turn-off failure and confirmation timeout, verify one request and a retained notification/latch until genuine activity or explicit retry. |
| Health and stale-probe recovery | Pending; healthy status polls must not clear start/readiness or Sony failures. Reachable stale probes notify; valid probes clear only their own error. |

### Acceptance coverage against the design

| Design acceptance item | Local automated coverage | Theater record status |
|---|---|---|
| 1. Sony off no longer removes Ugoos ping/SSH reachability | CEC Ignore and package no-suspend/no-WoL checks; hardware reachability requires live test | Pending 24-hour/display-off record |
| 2. Repeated off/on cycles and 24-hour Sony-off reachability | Not automatable locally | Pending 24-hour/display-off record |
| 3. Sony off stops Kodi only after fresh 60-second interval | Package fixtures exercise continuous-off cancellation, queued state changes, fresh epochs, and one-shot maturity | Pending elapsed-time record |
| 4. Sony definite non-off starts Kodi and restores JSON-RPC/UI | Package tests cover desired running and 90-second readiness wait | Pending elapsed-time record |
| 5. Sony unknown/unavailable starts or preserves Kodi | Package tests cover fail-awake desired running | Pending HA restart/network observations |
| 6. Thirty minutes genuine Kodi inactivity powers off Sony then stops Kodi | Package tests cover HA idle state, `System.IdleTime`, freshness, and normal stop flow | Pending idle acceptance |
| 7. Active menu input resets input-idle condition | Genuine false Kodi results clear evidence/rearm episodes; stale/failed results cannot rearm a failed Sony episode | Pending idle acceptance |
| 8. Playing and paused media inhibit idle power-off | Package tests require exact Kodi `idle` and reject playing/paused triggers | Pending media playback observation |
| 9. Keep Kodi running allows idle Sony off but leaves Kodi running | Package tests cover precedence; live override required | Pending override record |
| 10. Stop-policy opt-out leaves Kodi running while preserving idle Sony off | Package tests cover policy precedence in template fixtures; per-room opt-out package not deployed | Pending future opt-out room or fixture decision |
| 11. HA restart, Ugoos reboot, command failure, network partition fail awake and notify | Fixtures exercise startup/reload, observed host/service/Kodi recovery, scoped failures and notifications; real reboot/network timing still requires live tests | Pending restart/reboot/failure injection |
| 12. Repeated cycles do not create Sony/Kodi CEC power loops | Static docs/settings keep Sony auto power disabled and CEC TV-off Ignore; loop absence requires live cycles | Pending repeated cycle observation |
| 13. Restricted SSH key cannot execute shell/transfer/PTY/forward/non-Kodi control | Lifecycle shell tests cover forced command/restrictions and arbitrary denial | Pending live restricted-command denial record |

## Installation record

| Field | Value |
|---|---|
| Installed extender revision | Confirm during installation; original guide lists T/R as initial and T2/R2 as planned. |
| Hostname | Proposed: `ugoos-theater`; confirm actual value. Original pilot example was `ugoos-pilot`. |
| Wired MAC / DHCP reservation | To be recorded from the device. |
| Test date, titles/tracks, and observed modes | To be recorded. |
| Backup location | To be recorded. |

Store future deployable room values using the [configuration layout](../../config/README.md).
