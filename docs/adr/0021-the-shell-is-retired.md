---
status: accepted
---

# The shell is retired

[ADR 0012](0012-shadow-the-shell-and-retire-it-wholesale.md) said the shell
provisioner would be deleted wholesale, once, when a factory-fresh Device
could be provisioned from a Profile alone. Retirement test run 2
(2026-09-24) met that bar: `apply` converged a freshly imaged card with no
manual step, a second `plan` was clean, and each difference from the Device in
service was either a per-Device fact, a deliberate retirement, or one of two
Profile gaps ([#156](https://github.com/jbruns/tv/issues/156)). Neither gap is
something the shell wrote, so neither one waits for this.

So the shell has been deleted, along with everything that existed only to
support it: its entry points and libraries, its configuration, its tests, the
ownership ledger, the write-set permission guard, and every operations,
device and decision document built around it. The Reconciler is the only
engine. The documentation was rewritten from scratch rather than edited, so
that no manual describes an engine that no longer exists.

That ends several things ADR 0012 set up:

- **Shadowing ends**, and with it ADR 0012's bounded exception to the
  exclusive-ownership rule of
  [ADR 0009](0009-fail-forward-and-exclusive-execution-ownership.md). Every
  State Address has one engine again.
- **The value-parity rule ends** (run the shell after `apply`, then re-plan
  and expect no Changes). So does the Divergent Address, which was defined
  against the shell: the `divergent` key is gone from the schema, so a
  leftover one is rejected as an unknown key. The two addresses that carried
  one, `general.addonupdates` and `services.esenabled`, are now ordinary
  declarations.
- **Recovery is re-imaging and provisioning again.** There is no Recovery
  Baseline to restore first.
- **Glossary terms that described only the shell are removed**: Recovery
  Baseline, Divergent Address, Managed Absence, Component, and Pilot Phase.
  The Pilot Phase ended when its own definition was met. Managed Absence can
  return when a slice genuinely needs absence on a fresh Device.

ADR 0012's standing rules 1 and 2, and its acceptance obligation for Cleared
Addresses, never depended on the shell. They carry on as acceptance guidance
in the [Profile reference](../reference/profile.md).

## Dropped knowingly

These rows in the ledger were the shell's and were never taken over. Run 2
showed that none of them is needed on a fresh Device, so they go with the
shell:

- `ADDON-003`: the shell's allowlist of nine add-ons it tolerated. Seven are
  metadata scrapers Kodi ships and enables itself (`ORIGIN_SYSTEM`); the two
  autocompletion add-ons are now in the Artifact Lock. The survey reports any
  add-on nobody declared.
- `CORE-007`: the shell's reading of `/etc/localtime`. The timezone Effect
  verifies the zone.
- `SKIN-017` and `SKIN-018`: the seasons and episodes expressions compiled into
  the Arctic Fuse view include. The view rebuild Effect regenerates the include
  ([ADR 0015](0015-trigger-the-view-rebuild-the-way-the-skin-does.md)).
- `SVC-014` to `SVC-017`: the shell stripped `allow_insecure`, `local_mode`,
  `local_servers_json` and `local_profiles_json` from PM4K's settings. A fresh
  Device does not have them.

## One-time cleanup on the Device in service

The operator does this once, by hand, on `ugoos-theater`. A re-imaged Device
has none of it:

- Delete the two superseded Smart Playlists,
  `RecentlyReleasedMovies90Days.xsp` and
  `RecentlyReleasedMoviesCurrentYear.xsp`, from
  `/storage/.kodi/userdata/playlists/video/`.
- Delete `/storage/.cache/coreelec-provision/` and
  `/storage/.cache/kodi-lifecycle/`, the shell's transaction state.
- Delete `/storage/backup/coreelec-provision/` and
  `/storage/backup/kodi-lifecycle/`, the shell's transaction backups.
