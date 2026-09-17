# Ugoos AM6B+ add-on onboarding and restart contract

This is the evidence-based contract for add-on onboarding order, Kodi restart
checkpoints, and completion signals on Ugoos AM6B+ CoreELEC systems. It governs
what `configure-coreelec-addons.sh` is allowed to claim in its configuration
report. The full evidence capture and rationale are recorded in the
[add-on onboarding and restart sequencing design](../../superpowers/specs/2026-09-16-addon-onboarding-restart-sequencing-design.md);
this document restates the operator-facing parts of it.

## Onboarding order

Six phases. Each states why it cannot move.

1. **Artifacts installed.** Dependency order is enforced by Kodi's resolver
   from `addon.xml`, not by provisioning.
2. **Kodi stopped, then Kodi-owned configuration written.** Required by the
   file-ownership evidence below; a live write would be discarded.
3. **Kodi started.** Add-ons initialize. Emby begins synchronizing unprompted.
4. **Unattended verification.** weather.ha, NextPVR, the TMDb Helper keys, and
   the Arctic Fuse 3 hubs and widgets. Depends on no human action.
5. **Guided and manual onboarding.** PM4K and Emby. Both need Kodi running and
   a human at the UI, so neither can precede phase 3.
6. **Synchronization completion observed.** Emby `LibrarySynced`. Only
   meaningful once phase 5 has authenticated the client.

Phase 6 cannot be collapsed into phase 4. Arctic Fuse 3's Trakt widgets are
populated from Emby library tags, so they remain empty until phase 6 finishes.
A phase-4 report that claims success would be the false confidence this
contract exists to remove.

## Restart checkpoints

Two classes of provisioning write, from the file-ownership evidence:

| Class | Files | Rule |
| --- | --- | --- |
| K, Kodi-owned | `guisettings.xml`, the skin `settings.xml`, and any `addon_data/*/settings.xml` that Kodi has loaded | Must be written while `kodi.service` is stopped |
| P, provisioner-owned | The `script.skinvariables` JSON nodes | Safe to write while Kodi runs; a restart is needed only for them to take effect |

Rules:

1. A provisioning transaction takes exactly one `kodi.service` stop/start
   pair, unconditionally, regardless of which classes it writes. This is the
   provisioner's current behavior and the evidence justifies it.
2. Class K files are written only while Kodi is stopped. This is mandatory: a
   live write is discarded.
3. Add-on-owned settings files are never written by provisioning at all; they
   belong to the add-on.

The single restart is deliberately unconditional: it is the safer option
because it does not try to skip a restart it might get away with. With the
file-ownership evidence in hand, the single existing restart is necessary and
there are no unnecessary restarts to remove.

## Completion signals

The configuration report separates two orthogonal axes for every selected
add-on: `addon.<id>.config_status` (artifact and configuration work owned by
provisioning) and `addon.<id>.onboarding_status` (authentication and
synchronization owned by the user). Only `onboarding_status=complete` means an
add-on is finished; `config_status=configured` on its own never does.

| Add-on | Interaction | `onboarding_status` |
| --- | --- | --- |
| `weather.ha` | fully-unattended | `not-required` |
| `pvr.nextpvr` | fully-unattended | `not-required` |
| `plugin.video.themoviedb.helper` | fully-unattended | `not-required` |
| `skin.arctic.fuse.3` | fully-unattended | `not-required` |
| `script.plexmod` | guided | see PM4K ladder below |
| `plugin.service.emby-next-gen` | manual | see Emby ladder below |

**Emby ladder** (`plugin.service.emby-next-gen`), evaluated in order. This is
observed behavior of the wired-in code path
(`coreelec_postdeploy_emby_account_program` / `_account_state` /
`_onboarding_status`), which is a local filesystem glob and JSON parse only —
it never performs network I/O:

- `servers_*.json` absent or incomplete (missing `ServerId`, `AccessToken`, or
  `UserId`): `pending-authentication`.
- `servers_*.json` ambiguous (more than one file) or invalid (unparseable
  JSON): `manual-required`, with observation
  `service.plugin.service.emby-next-gen.account_state=<ambiguous|invalid>`.
- `emby_<ServerId>.db` absent: `pending-sync`.
- `LibrarySynced` empty: `pending-sync`.
- `LibrarySynced` not equal to `LibrarySyncedMirrow`: `pending-sync`, with
  observation `service.plugin.service.emby-next-gen.libraries_synced=<n>` and
  `libraries_attempted=<m>`.
- `LibrarySynced` non-empty and equal to `LibrarySyncedMirrow`: `complete`.

**PM4K server-binding predicate** (`script.plexmod`):

- `myplex.MyPlexAccount.authToken` absent or empty: `pending-authentication`.
- token present, but `lastServerId.<accountID>` unset or its value absent from
  `PlexServerManager.servers[].uuid`: `manual-required`, with observation
  `service.script.plexmod.server_bound=0`.
- token present and server bound: `complete`, with `server_bound=1`.
- settings unreadable or malformed: `manual-required`, with the existing
  `token-state-unreadable` observation.

A Plex account that has authenticated but never selected a server is **not**
complete; it reports `manual-required`.

`unobservable` and `failed` are **reserved** and currently emitted by nothing
in the shipped `onboarding_status` vocabulary. `unobservable` exists only for
an add-on with a real onboarding step whose completion has no reliable
observable. `failed` exists for a future wired failure path: a network- and
TLS-aware Emby state check (`coreelec_postdeploy_emby_state`, the source of
the `server-unavailable`, `certificate-error`, and `identity-mismatch` states)
is implemented but has no production caller — `run_addon_workflow` never
invokes it, only `assist_emby_login` can reach it, and nothing calls that
either. No add-on currently selected is in either reserved state. Introducing
an add-on that needs one requires documenting in this contract why no signal
exists, or wiring the dormant Emby network check into the live workflow; a
reserved value must never be used to paper over a signal that was merely
inconvenient to read.

## Evidence

All findings below were captured on `ugoos-theater` on 2026-09-16 across two
observed Kodi restarts (09:53:15 and 09:58:12).

### File ownership across a restart

Hashes and mtimes were taken before a stop, after the stop, and after the
following start.

| File | At shutdown | At startup | Class |
| --- | --- | --- | --- |
| `userdata/guisettings.xml` | rewritten, hash changed `87f76e60`→`616f45d2` | rewritten | Kodi-owned |
| `addon_data/skin.arctic.fuse.3/settings.xml` | rewritten, hash unchanged | rewritten, hash changed `5212e6ca`→`8db54b9d` | Kodi-owned |
| `addon_data/plugin.service.emby-next-gen/settings.xml` | untouched | untouched | add-on-owned |
| `addon_data/plugin.video.themoviedb.helper/settings.xml` | untouched | untouched | add-on-owned |
| `addon_data/script.plexmod/settings.xml` | untouched | untouched | add-on-owned |
| `script.skinvariables/nodes/skin.arctic.fuse.3/*.json` | untouched | untouched | provisioner-owned |

Kodi flushes its in-memory settings over the Kodi-owned files at both edges of
its lifecycle. A provisioning write to those paths while Kodi runs is silently
discarded.

### Emby completion ladder

From `plugin.service.emby-next-gen/database/library.py` as installed on the
device:

- line 676 calls `add_LibrarySyncedMirrow(...)` *before* the per-library
  content sync loop;
- the content loop runs, and every interrupt path returns early;
- line 712 calls `add_LibrarySynced(...)` *only after* that loop completes.

Therefore `LibrarySyncedMirrow` records that a library sync was attempted and
`LibrarySynced` records that it finished. A populated `LibrarySyncedMirrow`
with a smaller `LibrarySynced` means a sync is in progress or was interrupted.

`emby_<ServerId>.db` is created at handshake, before either table is written.

Observed healthy baseline: `LibrarySynced` 16 rows, `LibrarySyncedMirrow` 16
rows, and `UpdateItems`, `RemoveItems`, `UserdataItems`, `LibraryAdd`,
`LibraryRemove` all zero.

`LastIncrementalSync` is **not** a session-completion signal. After the
09:58:12 restart it remained `2026-09-16T16:54:42Z`: the sync walked all 16
library/type pairs, found no changes, and so never advanced the stamp. Treating
it as "synced this session" would report a stale success.

Startup sync durations: 09:53:20 to 09:54:42 (about 82 seconds, changes found),
and 09:58:18 to 09:58:19 (about 1 second, no changes).

### PM4K completion gap

`coreelec_postdeploy_pm4k_account_token_present` returns 1 when
`myplex.MyPlexAccount.authToken` is non-empty, which proves account
authentication only. `script.plexmod/settings.xml` separately holds:

- `None.PlexServerManager`, a JSON object whose `servers` list held 7 entries,
  each with `name`, `uuid`, `owned`, and `connections`;
- `lastServerId.<accountID>`, the selected server UUID;
- `<uuid-suffix>.PlexServerPrefs`, preferences for the selected server.

An authenticated account with no selected server leaves the add-on unusable at
the TV while the report says `configured`.

### Arctic Fuse 3 ordering

`Addons.GetAddons` reports `skin.arctic.fuse.3` 3.2.16 declaring hard
dependencies on `script.skinvariables`, `script.texturemaker`,
`plugin.video.themoviedb.helper`, `resource.images.weathericons.white`,
`resource.images.studios.coloured`, and `resource.font.robotocjksc`. Kodi's own
resolver enforces this order at install and enable time, so provisioning does
not sequence it by hand. The contract records the dependency rather than
implementing it.

### TMDb Helper has no onboarding

`addon_data/plugin.video.themoviedb.helper/settings.xml` contained exactly two
settings, `mdblist_apikey` and `omdb_apikey`, both written by the provisioner.
There is no authentication or first-run step. The `database_07/` contents
(`ItemDetails.db` at 114 MB, `ItemQueries.db`, `MDbList.db`, `OMDb.db`) are
caches warmed automatically on use.

## Security constraint

`PlexServerManager.servers[].connections[].token` contains live Plex connection
tokens. `report_redaction_check` only scans for the values of the names in
`coreelec_postdeploy_secret_names`, so a Plex connection token written into a
report would not be caught and the report would not be deleted.

Every observation this contract defines emits booleans, counts, or fixed
enumerated states. No raw add-on settings value is ever placed in the report.
