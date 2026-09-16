# Ugoos AM6B+ CoreELEC 21.3 System

## Status
Accepted.

## Context
- Ugoos AM6B+ is the shared playback platform.
- CoreELEC 21.3 Omega `Amlogic-ng.arm` is the locked platform.
- Profile 7 FEL support requires the matching CoreELEC image and `dovi.ko`.

## Decision
- Boot and validate on microSD before optional eMMC installation.
- Use wired LAN with DHCP plus a pfSense reservation and DNS name.
- Keep CoreELEC awake; do not use suspend, shutdown, CEC wake, or WoL in the normal lifecycle.
- Keep CEC navigation enabled, but do not let Kodi startup or shutdown power
  the display on or off.
- Use repository provisioning for shared Kodi, add-on, regional, CEC power isolation, SSH-hardening, and skin state.
- Use the restricted lifecycle SSH gateway and Home Assistant package for Kodi start/stop.

## Automated Baseline
- The shared [`provision.conf`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf) applies the locked regional defaults, pinned add-on baseline, update policy, shared Kodi/Home Assistant settings, and managed Arctic Fuse state.
- Exact add-on versions, artifact hashes, and non-secret configuration inputs are defined only in that shipped file.
- Provisioning is transactional and writes redacted reports.
- With no explicit component, provisioning applies that full baseline;
  legacy `--addon` still applies it while filtering only artifacts.
- Explicit `core`, `cec`, `addons`, `services`, or `skin` requests use the same
  transaction engine but limit Kodi/add-on mutation, backup, verification, and
  reporting to the dependency-expanded scope. `services` depends on `addons`;
  `skin` depends on `core` and `addons`.
- `room` is reserved and rejected as unimplemented. Room playback, whitelist,
  audio, library, hub, and view-state ownership requires a separate decision.
- A few pinned add-on artifacts receive compatibility patches applied to the
  expanded source during the transaction, before installation. Each patch
  asserts the add-on's exact identity, version, and source structure, and fails
  the transaction rather than installing an unreviewed artifact: `script.plexmod`
  1.3.19 and `plugin.video.themoviedb.helper` 6.17.1 receive shutdown fixes, and
  `weather.ha` 0.0.6.6 receives both a Kodi 21 settings-schema fix and a
  retry-loop fix that keeps an unreachable Home Assistant from crashing the
  add-on at boot.

## Rollout boundary

The repository contract permits CEC-only maintenance while the Home Assistant
keep-running override is enabled. It does not establish that the corrected CEC
policy or lifecycle package is installed on the theater device; live rollout
and Sony-off recovery validation remain separate required work. This decision
does not change Sony or Denon configuration and does not resolve buffering,
add-on sequencing, or room desired state. The `weather.ha` boot crash is fixed
in the provisioner but is only live on a device once an `addons`-scoped
transaction has redeployed that artifact.

## Manual Per-Room Configuration
- Hostname and reservation.
- HDMI topology.
- Display-specific Dolby Vision mode and reported resolution whitelist.
- Audio passthrough choices determined by the full room audio path.
- Native Home Assistant integrations and entity naming.

## Migration Constraint
- CoreELEC 22 `Amlogic-no` requires a fresh installation and a separate decision; no in-place platform migration.
