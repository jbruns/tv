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
- Use repository provisioning for shared Kodi, add-on, regional, CEC Ignore, SSH-hardening, and skin state.
- Use the restricted lifecycle SSH gateway and Home Assistant package for Kodi start/stop.

## Automated Baseline
- The shared [`provision.conf`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf) applies the locked regional defaults, pinned add-on baseline, update policy, shared Kodi/Home Assistant settings, and managed Arctic Fuse state.
- Exact add-on versions, artifact hashes, and non-secret configuration inputs are defined only in that shipped file.
- Provisioning is transactional and writes redacted reports.

## Manual Per-Room Configuration
- Hostname and reservation.
- HDMI topology.
- Display-specific Dolby Vision mode and reported resolution whitelist.
- Audio passthrough choices determined by the full room audio path.
- Native Home Assistant integrations and entity naming.

## Migration Constraint
- CoreELEC 22 `Amlogic-no` requires a fresh installation and a separate decision; no in-place platform migration.
