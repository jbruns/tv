# Add-on Onboarding and Restart Sequencing Design

## Status

Approved for implementation planning. Evidence was gathered against the live
`ugoos-theater` device on 2026-09-16; every ordering and completion claim below
cites either that capture or add-on source read from the device.

## Context

Emby, PM4K, Arctic Fuse 3, and TMDb Helper have different first-run,
authentication, synchronization, and restart requirements.
`configure-coreelec-addons.sh` reports a single `addon.<id>.status` per add-on,
and its `configured` value conflates two unrelated facts: that provisioning
wrote the artifact and configuration, and that the add-on is actually onboarded
and usable.

The conflation is not theoretical, and for Emby it is currently latent rather
than active. `run_addon_workflow` dispatches
`plugin.service.emby-next-gen` to an unconditional `authorization-required`,
so the report is honest but useless: it can never signal that onboarding
finished, no matter how complete the library sync is. Meanwhile
`coreelec_postdeploy_emby_state` already implements a nine-value ladder that
returns `configured` as soon as `emby_<ServerId>.db` exists. That file is
created at handshake, before any library content is synchronized. The ladder
has no production caller today — it is reachable only from `assist_emby_login`,
which is itself uncalled — so wiring it up as written would introduce exactly
the false success this workstream exists to prevent.

`docs/operations/provision-ugoos.md` step 12 already tells the operator to
expect an empty Trakt widget after a successful configuration report, which is
an admission that the report vocabulary cannot express the distinction rather
than a fix for it.

This design defines the evidence-based contract: the onboarding order, the
required restart checkpoints, and the observable completion signals. It makes
the report distinguish the two axes. It deliberately does not automate the
manual steps.

## Goals

- Document the evidence-based installation and onboarding order for Emby, PM4K,
  Arctic Fuse 3, and TMDb Helper, with the reason each step cannot move.
- State which Kodi restarts are required, and why, in terms of file ownership.
- Separate artifact/configuration success from authentication and
  synchronization completion in the report vocabulary.
- Add fail-closed verification only where completion is reliably observable.
- Preserve `manual-required` states without reporting false success.

## Non-goals

- Automating the Emby sign-in or the Plex server selection. Both require a
  human at the UI. Automation may only follow once this contract is proven in
  use. In particular `assist_emby_login`, which drives the sign-in dialog over
  JSON-RPC, has no production caller today and this design does not give it
  one. Only the Emby *observation* path is wired up.
- Changing `provision-coreelec.sh`. The restart rules below describe its
  current behavior and justify it; the evidence implies no change to it.
- Removing or enabling add-ons found in a drifted state. See issues #12 and
  #13.
- Treating cache warmth as progress. See the TMDb Helper section.

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

## Onboarding Order

Six phases. Each states why it cannot move.

1. **Artifacts installed.** Dependency order is enforced by Kodi's resolver
   from `addon.xml`, not by provisioning.
2. **Kodi stopped, then Kodi-owned configuration written.** Required by the
   file-ownership evidence; a live write would be discarded.
3. **Kodi started.** Add-ons initialize. Emby begins synchronizing unprompted.
4. **Unattended verification.** weather.ha, NextPVR, the TMDb Helper keys, and
   the Arctic Fuse 3 hubs and widgets. Depends on no human action.
5. **Guided and manual onboarding.** PM4K and Emby. Both need Kodi running and
   a human at the UI, so neither can precede phase 3.
6. **Synchronization completion observed.** Emby `LibrarySynced`. Only
   meaningful once phase 5 has authenticated the client.

Phase 6 cannot be collapsed into phase 4. Arctic Fuse 3's Trakt widgets are
populated from Emby library tags, so they remain empty until phase 6 finishes.
A phase-4 report that claims success is the false confidence this workstream
exists to remove.

## Restart Contract

Two classes of provisioning write, from the file-ownership evidence:

- **Class K, Kodi-owned.** `guisettings.xml`, the skin `settings.xml`, and any
  `addon_data/*/settings.xml` that Kodi has loaded. Must be written while
  `kodi.service` is stopped.
- **Class P, provisioner-owned.** The `script.skinvariables` JSON nodes. Kodi
  never rewrites them, and the skin reads them at startup. Safe to write while
  Kodi runs; a restart is needed only for them to take effect.

Rules:

1. A provisioning transaction takes exactly one `kodi.service` stop/start pair,
   unconditionally, regardless of which classes it writes. This is the
   provisioner's current behavior and the evidence justifies it.
2. Class K files are written only while Kodi is stopped. This is mandatory: a
   live write is discarded.
3. Add-on-owned settings files are never written by provisioning at all; they
   belong to the add-on.

The Class K/Class P distinction is documentation, not a branch. It explains why
the `script.skinvariables` nodes survive a restart while `guisettings.xml` does
not, and it tells a future contributor which files are safe to inspect on a
running system. It is deliberately not used to skip the restart.

A Class P-only transaction could in principle skip the restart, because Kodi
would not clobber those nodes. That optimization is rejected: the restart is
cheap, it is the only thing that makes a Class P write take effect, and
skipping it would introduce a "configured but not yet active" state that is
easy to misread as success. Preferring the safer option keeps the reported
state and the running state identical.

This answers the "eliminate unnecessary restarts" task in #6: with the file
ownership evidence in hand, the single existing restart is necessary and there
are no unnecessary restarts to remove.

## Report Vocabulary

The report format becomes `coreelec-addon-configuration-report-2`. Each add-on
emits `interaction_level` as today, plus two orthogonal status fields.

`addon.<id>.config_status` covers artifact and configuration work owned by
provisioning:

`configured | already-configured | skipped | failed | dry-run`

`addon.<id>.onboarding_status` covers authentication and synchronization:

`not-required | complete | pending-authentication | pending-sync |
manual-required | unobservable | failed | dry-run`

Detail stays in the existing `service.<id>.*` observation keys rather than
expanding either enum.

`unobservable` is reserved for an add-on that has a real onboarding step whose
completion has no reliable observable. No add-on currently selected is in that
state, so no predicate below emits it. Introducing an add-on that needs it
requires documenting in this contract why no signal exists; it must never be
used to paper over a signal that was merely inconvenient to read.

### Migration from `coreelec-addon-configuration-report-1`

Consumers of the single `addon.<id>.status` field map as follows. The mapping
is not one-to-one, which is the point of the change.

| report-1 `status` | report-2 `config_status` | report-2 `onboarding_status` |
| --- | --- | --- |
| `configured` (weather.ha, pvr.nextpvr) | `configured` | `not-required` |
| `configured` (script.plexmod, newly authorized) | `configured` | `complete` or `manual-required` per the server-binding check |
| `already-configured` (script.plexmod) | `already-configured` | `complete` or `manual-required` per the server-binding check |
| `authorization-required` | `configured` | `pending-authentication` |
| `manual-required` | `configured` | `manual-required` |
| `skipped` | `skipped` | `not-required` |
| `failed` | `failed` | `failed` |
| `dry-run` | `dry-run` | `dry-run` |

Note that `already-configured` in report-1 is an onboarding fact reported on
the configuration axis. In report-2 the configuration axis keeps
`already-configured` for configuration that already matched the desired state,
and the onboarding fact moves to `onboarding_status`.

### Per-add-on predicates

| Add-on | Interaction | `onboarding_status` |
| --- | --- | --- |
| `weather.ha` | fully-unattended | `not-required` |
| `pvr.nextpvr` | fully-unattended | `not-required` |
| `plugin.video.themoviedb.helper` | fully-unattended | `not-required` |
| `skin.arctic.fuse.3` | fully-unattended | `not-required` |
| `script.plexmod` | guided | see below |
| `plugin.service.emby-next-gen` | manual | see below |

`script.plexmod`:

- `myplex.MyPlexAccount.authToken` absent or empty: `pending-authentication`.
- token present, but `lastServerId.<accountID>` unset or its value absent from
  `PlexServerManager.servers[].uuid`: `manual-required`, with observation
  `service.script.plexmod.server_bound=0`.
- token present and server bound: `complete`, with `server_bound=1`.
- settings unreadable or malformed: `manual-required`, with the existing
  `token-state-unreadable` observation.

`plugin.service.emby-next-gen`, evaluated in order:

- `servers_*.json` absent, ambiguous, invalid, incomplete:
  `pending-authentication`.
- server unreachable, certificate error, or identity mismatch: `failed`.
- `emby_<ServerId>.db` absent: `pending-sync`.
- `LibrarySynced` empty: `pending-sync`.
- `LibrarySynced` not equal to `LibrarySyncedMirrow`: `pending-sync`, with
  observation `service.plugin.service.emby-next-gen.libraries_synced=<n>` and
  `libraries_attempted=<m>`.
- `LibrarySynced` non-empty and equal to `LibrarySyncedMirrow`: `complete`.

Emby's branch therefore stops returning an unconditional
`authorization-required` and instead reports the observed rung of the ladder:
`config_status=configured` with `onboarding_status=pending-sync` while the
library sync is incomplete, and `complete` once it finishes. The ladder's
existing `configured` rung, which fires on mere database existence, is
corrected as part of this work rather than wired up as written.

## Fail-Closed Rule

`complete` is emitted only on direct observation of the completion predicate.
Every other outcome degrades to a pending state, `manual-required`, or
`unobservable`. Unreadable, ambiguous, or malformed state is never success,
matching the posture of the existing `coreelec_postdeploy_emby_state` ladder.

`unobservable` is load-bearing but currently unused: it exists so that an
add-on with an unobservable onboarding step has a truthful state to report
instead of being forced into `complete`.

TMDb Helper cache warmth is a different case and is worth naming to avoid
confusion. It is readily observable and entirely meaningless as a completion
signal, so the contract records that it must not be reported as one. TMDb
Helper is `not-required`, not `unobservable`. The general rule is that a signal
must be both observable and load-bearing before it becomes a completion
criterion.

## Security Constraint

`PlexServerManager.servers[].connections[].token` contains live Plex connection
tokens. `report_redaction_check` only scans for the values of the names in
`coreelec_postdeploy_secret_names`, so a Plex connection token written into a
report would not be caught and the report would not be deleted.

Every new observation added by this design emits booleans, counts, or fixed
enumerated states. No raw add-on settings value is ever placed in the report.

## Verification

Tests live in `tests/test-coreelec-addon-workflows.sh`. Each must be added to
the trailing backslash-continued registration list or it will not run.

### Emby ladder tests

A fixture SQLite database exercises each branch: database absent;
`LibrarySynced` empty; `LibrarySynced` smaller than `LibrarySyncedMirrow`;
both non-empty and equal. Combined with the existing `servers_*.json` and
reachability fixtures, this covers every path to a status value.

### PM4K tests

Four states: no token; token with no `lastServerId`; token with a
`lastServerId` absent from the server list; token with a bound server. The
third case is the new check and must produce `manual-required`, not `complete`.

### Report tests

- Both status fields are emitted for every selected add-on.
- The format banner reads `coreelec-addon-configuration-report-2`.
- A redaction test asserts that no raw value from `script.plexmod/settings.xml`
  reaches the report, including connection tokens.
- `--dry-run` yields `dry-run` on both axes.

### Documentation tests

None exist in this repository, so the documentation changes are reviewed rather
than tested.

## Documentation

- New `docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md` holding the
  evidence, the six-phase order, the restart classes, and the completion
  signals.
- `docs/operations/provision-ugoos.md`: describe the two-axis report, and
  rewrite step 12 to reference the `pending-sync` state rather than telling the
  operator to expect an empty widget.
- `docs/operations/provision-ugoos.md` "Current rollout limits": drop
  post-install add-on sequencing, which this workstream defines.

## Follow-ups

- Issue #12, `pvr.nextpvr` installed but disabled.
- Issue #13, `repository.kodinerds` unmanaged and non-functional.

## Success Criteria

- The onboarding order, restart classes, and completion signals are documented
  with the evidence that establishes each.
- The report separates configuration from onboarding for every selected add-on.
- Emby reports `pending-sync` rather than `configured` while its library sync
  is incomplete.
- PM4K reports `manual-required` when authenticated with no bound server.
- No completion state is reported without direct observation.
- No raw add-on settings value can reach a report.
