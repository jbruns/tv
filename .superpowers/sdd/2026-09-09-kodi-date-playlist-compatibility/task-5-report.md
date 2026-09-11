# Task 5 Report: Re-Accept on `coreelec-theater`

**Status: FINAL LIVE ACCEPTANCE COMPLETE — ACCEPTED**

## Environment

| Field | Value |
|---|---|
| Branch | `agents/arctic-fuse-3-skin-integration` |
| Accepted deployment HEAD | `09c784e` (`fix: remove Next Aired hub toggle entirely`) |
| Earlier deployment HEADs | `3b418af`, `8390d42` (both superseded) |
| Device | `CoreELEC-theater`, CoreELEC 21.3 Omega |
| SSH | Strict host-key checking; `root@coreelec-theater`; dedicated admin key |
| Kodi | `kodi.service` active; authenticated JSON-RPC through device localhost |
| Artifact directory | `/Users/jbruns/.copilot/session-state/32cb054d-cfb1-49e6-a64a-19e59adfcb6e/files/arctic-fuse-acceptance/` |

The required `OMDB_API_KEY` and `MDBLIST_API_KEY` environment variables were
present for both deployments. Their values were never printed or persisted.

## Step 1: Disposable candidate cleanup — PASS

Initial inspection found four present paths and one already absent:

- present: `CandidateRecentAirdate.xsp`
- present: `CandidateRecentPremiereYear.xsp`
- present: `CandidateRecentDateAdded.xsp`
- absent: `CandidateRecentlyReleasedMovies90Days.m3u`
- present: `CandidateExactReleasedMovies.xsp`

Only the five named Candidate paths were passed to `rm -f`. A subsequent
strict-SSH inspection verified all five absent before deployment.

## Step 2: First transactional deployment — PASS

| Evidence | Result |
|---|---|
| Report | `coreelec-theater-20260911T164651Z.txt` |
| Transaction | `/storage/backup/coreelec-provision/20260911T164556Z` |
| State | `committed` |
| Verification | `pass` |
| Metadata | `metadata.omdb.status=ok`; `metadata.mdblist.status=ok` |
| Arctic Fuse | every `arctic_fuse.*.status` is `ok` |
| Migration | `arctic_fuse.playlist_migration.observed=1`; status `ok` |

## Step 3: Corrected playlist validation — PASS

Both playlists were queried with authenticated `Files.GetDirectory` requests
against Kodi's device-local `127.0.0.1:8080/jsonrpc` endpoint.

Device date: **2026-09-11**.

| Playlist | Items | Live values | Result |
|---|---:|---|---|
| `RecentlyAiredEpisodes30Days.xsp` | 50 | air dates 2026-08-23 through 2026-09-09 | All dates are within the inclusive 2026-08-12 through 2026-09-11 rolling window; no future date; limit satisfied |
| `RecentlyReleasedMoviesCurrentYear.xsp` | 36 | years exactly `2026`; premiere dates 2026-01-05 through 2026-08-05 | Every movie matches the device year; limit satisfied |

Neither request returned `Invalid params` or another JSON-RPC error.

## Step 4: Arctic Fuse Home rendering — PASS

Authenticated device-local info-label observations on Home:

```text
Container(503).NumItems=50
Container(504).NumItems=36
Container(503).ListItem.Label=1x08. Spoiler: We're as Confused as You Are
Container(504).ListItem.Label=“Wuthering Heights”
```

Focusing the widget selector reported the exact controls:

```text
Recently Aired Shows
Recently Released Movies
```

Corrected screenshots:

- `screenshot-home-corrected-20260911.png`
- `screenshot-widget-recently-aired-20260911.png`
- `screenshot-widget-recently-released-20260911.png`

The screenshots visibly show both populated corrected widget tabs and their
media rows.

## Step 5: Second deployment and idempotence — PASS

| Evidence | Result |
|---|---|
| Before hashes | `managed-hashes-before-second-deploy-20260911.txt` (9 files) |
| Second report | `coreelec-theater-20260911T165411Z.txt` |
| Transaction | `/storage/backup/coreelec-provision/20260911T165326Z` |
| State | `committed` |
| Verification | `pass` |
| After hashes | `managed-hashes-after-second-deploy-20260911.txt` (9 files) |

All eight standalone managed files were byte-identical across deployments.
Kodi changed the aggregate Arctic Fuse `settings.xml` file at runtime, as in
the historical acceptance, so its whole-file digest differed. The managed
subset remained idempotent:

```text
managed_skin_settings=14 exact=1 string_typed=1 duplicate_free=1
obsolete_movie_playlist_absent=1
```

The second report again has `deployment_state=committed`,
`verification_result=pass`, all metadata/Arctic Fuse statuses `ok`, and
`arctic_fuse.playlist_migration.observed=1`.

## Step 6: Unaffected live surfaces — PASS; Next Aired investigated

### Passing surfaces

- **Plex / PM4K:** Selecting the Plex Home entry reached window `11101` and
  started `script.plexmod` 1.14.1-beta1. Kodi logs show PM4K initialization,
  template rendering, and `script-plex-user_select.xml` loading. The GUI then
  exposed the existing `doogie` user selection.
- **YouTube:** Selecting the YouTube Home entry reached window `11102`, then
  opened Kodi Videos window `10025`. The root populated with 20 items,
  including the signed-out navigation surface.
- **PVR:** 21 TV channel groups were returned. `All channels` contains 589
  channels.
- **Hub order:** Home `10000` -> Plex `11101` -> YouTube `11102` -> Next Aired
  `11106` -> PVR `11107` -> Add-ons `11108`. PVR-to-Add-ons navigation was
  separately confirmed after safely cancelling the blocker dialog.
- **Power menu:** The managed node contains exactly the five approved actions
  and order. Arctic Fuse options/power overlay `11170` was opened, captured,
  and closed with `Input.Back`. No item was selected and no Power action was
  executed.
- **Power screenshot:** `screenshot-power-recheck-20260911.png` visibly shows
  Power off system, Custom shutdown timer, Suspend, Reboot, and Restart Kodi.

### Root cause: `library_nextaired` requests an end-user Trakt token

The provisioned setting is exact and duplicate-free:

```text
upnext_mode_count=1
upnext_mode_type=string
upnext_mode_value=library_nextaired
```

While navigating in the required hub order, entering Next Aired `11106`
started its local-library widgets. As navigation continued to PVR, Kodi opened
a modal over the PVR hub. Authenticated device-local JSON-RPC reported:

```text
currentwindow.id=10100
currentwindow.label=Yes / No dialog
currentcontrol.label=Cancel
Control.GetLabel(1)=Unauthorised 401 Error TraktAPI Token
Control.GetLabel(10)=Cancel
Control.GetLabel(11)=OK
Control.GetLabel(12)=Never
```

Kodi logged failures for the exact configured mode, not `trakt_calendar`:

```text
GetDirectory - Error getting plugin://plugin.video.themoviedb.helper/?info=library_nextaired&reload=9&startdate=-1&days=1&widget=True&tmdb_type=episode
GetDirectory - Error getting plugin://plugin.video.themoviedb.helper/?info=library_nextaired&reload=9&startdate=0&days=1&widget=True&tmdb_type=episode
GetDirectory - Error getting plugin://plugin.video.themoviedb.helper/?info=library_nextaired&reload=9&startdate=1&days=1&widget=True&tmdb_type=episode
GetDirectory - Error getting plugin://plugin.video.themoviedb.helper/?info=library_nextaired&reload=9&startdate=2&days=1&widget=True&tmdb_type=episode
GetDirectory - Error getting plugin://plugin.video.themoviedb.helper/?info=library_nextaired&reload=9&startdate=3&days=1&widget=True&tmdb_type=episode
GetDirectory - Error getting plugin://plugin.video.themoviedb.helper/?info=library_nextaired&reload=9&startdate=4&days=1&widget=True&tmdb_type=episode
GetDirectory - Error getting plugin://plugin.video.themoviedb.helper/?info=library_nextaired&reload=9&startdate=5&days=1&widget=True&tmdb_type=episode
```

The asynchronous requests had to settle before selecting the explicitly
focused **Cancel** button would close the dialog. The underlying PVR hub was
then observable at window `11107`.

This disproved the original design assumption that `library_nextaired`
operates without Trakt user authorization. TMDb Helper 6.17.1 uses Trakt's
public calendar for this route but still enforces end-user OAuth. The bundled
Trakt application client ID is valid, so this is not a missing API key.

### Disposable alternative test: `library_airingnext` rejected

The token-free-looking `library_airingnext` route was disposable-live-tested.
It uses local Kodi/TMDb data, but on `coreelec-theater` it timed out against
OMDb. TMDb Helper's per-library fanout then logged:

```text
ParallelThread: RUNTIME ERROR: UNABLE TO SPAWN 82 THREAD 460
can't start new thread
```

This is not a configuration gap and is not reliable enough for managed
automation on this device class.

### Approved ruling

The user approved dropping Next Aired. The bounded correction now:

- converges `HomeSwitcher.1106.Toggle=false`;
- removes every case-insensitive `HomeSwitcher.1106.UpNextMode` setting before
  Kodi starts;
- accepts live runtime state only when the mode is absent or every
  case-insensitive matching value is empty;
- leaves managed navigation after Home as Plex, YouTube, PVR, Add-ons;
- preserves the one-profile limitation; and
- leaves all Power actions unexecuted.

## Step 7: First Next Aired removal deployment — FAILED VERIFICATION; AUTOMATIC ROLLBACK PASS

The first deployment of `3b418af` produced
`coreelec-provision-reports/coreelec-theater-20260911T180528Z.txt`. Every
reported verification surface passed except:

```text
arctic_fuse.hubs.expected=1
arctic_fuse.hubs.observed=0
arctic_fuse.hubs.status=mismatch
verification_failures=1
```

The transaction recorded `deployment_state=rolled-back` and
`verification_result=fail`; automatic rollback completed successfully.

Controlled backup/restore reproduction isolated the false negative. Before
Kodi startup, transformed XML had `HomeSwitcher.1106.Toggle=false` and no
case-insensitive `UpNextMode`. After Kodi and Arctic Fuse startup, the toggle
remained false and Arctic Fuse recreated exactly:

```xml
<setting id="homeswitcher.1106.upnextmode" type="string" />
```

This is deterministic Arctic Fuse runtime normalization, not missing
credentials or incomplete transformation. The transformer contract remains
strict absence before startup. The live verifier must accept absence or
empty-only case-insensitive matches while rejecting every non-empty value.

## Step 8: Superseded deployments of `8390d42` — NOT ACCEPTED

Two deployments of `8390d42` committed and passed verification
(`coreelec-theater-20260911T200447Z.txt`,
`coreelec-theater-20260911T200808Z.txt`; all `metadata.*` and `arctic_fuse.*`
statuses `ok`, `arctic_fuse.playlist_migration.observed=1`,
`verification_failures=0`), and all eight standalone managed files were
byte-identical between them.

Live inspection of the deployed result nevertheless failed the Home navigation
requirement. `Container(399)` — the control whose
`ListItem(±1).Property(action)` drives Left/Right hub movement from Home — still
contained:

```text
ListItem(1)=Plex        ReplaceWindow(1101)
ListItem(2)=YouTube     ReplaceWindow(1102)
ListItem(3)=Next Aired  ReplaceWindow(1106)
ListItem(4)=PVR         ReplaceWindow(1107)
ListItem(5)=Addons      ReplaceWindow(1108)
```

Root cause, read from the deployed skin: Arctic Fuse gates every hub on

```xml
<param name="enabled">!String.IsEmpty(Skin.String(HomeSwitcher.1106.Toggle))</param>
```

and `Home_ControlList_Item` maps that parameter straight to `<visible>`. The
skin's own toggle disables a hub with
`Skin.Reset(HomeSwitcher.1106.Toggle)` (`Dialog_DialogShortcuts.xml:829`), so
the disabled state is an **absent or empty** toggle string. The literal value
`false` is non-empty and therefore still rendered the hub. Evidence:
`screenshot-home-hubbar-defect-20260911.png`,
`screenshot-youtube-hubbar-nextaired-defect-20260911.png`, and
`live-skin-settings-analysis-20260911.txt`.

## Step 9: Fix round 2 — remove the toggle entirely

Tests were changed before production code.

- `tests/test-coreelec-settings.sh` now seeds a canonical **and** a
  case-variant `HomeSwitcher.1106.Toggle` and requires both absent after
  transformation; the toggle was removed from the managed `type="string"` list.
- `tests/test-coreelec-report.sh` drops the toggle from the valid baseline
  fixture and adds `false`-value rejection, empty-placeholder acceptance, and
  an empty-cannot-mask-a-stale-variant case.

RED: `1106.Toggle must be absent` (settings, 32/33) and four report failures
(79/83). GREEN after changing the transformer to
`remove_skin_setting("HomeSwitcher.1106.Toggle")` and making live verification
accept absent or empty-only case-insensitive toggle **and** mode matches while
rejecting any non-empty value: 33/33 settings, 83/83 report, 52/52 artifacts,
34/34 add-on workflows, 27/27 config.

Commit: `09c784e` (`fix: remove Next Aired hub toggle entirely`).

## Step 10: Final live acceptance of `09c784e` — PASS

| Evidence | Result |
|---|---|
| First report | `coreelec-theater-20260911T202453Z.txt` — transaction `/storage/backup/coreelec-provision/20260911T202351Z`, `committed`, `pass`, `verification_failures=0` |
| Second report | `coreelec-theater-20260911T202711Z.txt` — transaction `/storage/backup/coreelec-provision/20260911T202624Z`, `committed`, `pass`, `verification_failures=0` |
| Metadata | `metadata.omdb.status=ok`; `metadata.mdblist.status=ok` in both |
| Arctic Fuse | every `arctic_fuse.*.status=ok` in both; `arctic_fuse.status=ok` |
| Migration | `arctic_fuse.playlist_migration.observed=1`, status `ok` in both |
| Idempotence | `managed-hashes-before-fixround2-second-deploy-20260911.txt` vs `managed-hashes-after-fixround2-second-deploy-20260911.txt` — 8/8 byte-identical; obsolete `RecentlyReleasedMovies90Days.xsp` absent |

### Live skin settings

```text
total_settings=245
next_aired_toggle_count=1 all_empty=True   (homeswitcher.1106.toggle type=string value='')
upnext_mode_count=0 all_empty=True
managed_skin_settings=12 exact=1 string_typed=1 duplicate_free=1
HomeSwitcher.1107.Toggle=true  HomeSwitcher.1108.Toggle=true
```

Arctic Fuse recreated exactly one empty string-typed toggle placeholder after
startup — the same normalization it applies to every hub the operator never
enabled — and recreated no `UpNextMode` node at all. The three stale managed
IDs (`1101.Shortcut.Target`, `1101.Spotlight.Path`, `1102.Spotlight.Path`)
remain absent.

### Home navigation

`Container(399)` now lists exactly Home, Plex `1101`, YouTube `1102`, PVR
`1107`, Addons `1108`, then the options entry. Walking Right from Home
reached `10000 → 11101 → 11102 → 11107 → 11108`. No Next Aired entry, and no
Trakt/OAuth dialog: the Kodi log written since the final restart contains zero
matches for `Unauthorised`, `TraktAPI`, `library_nextaired`, or
`trakt_calendar`.

- **Plex**: selecting the hub started `script.plexmod` 1.14.1-beta1, which
  loaded `script-plex-user_select.xml` with the existing `doogie` user.
- **YouTube**: opened Videos window `10025` at `plugin://plugin.video.youtube/`
  with 20 items.
- **PVR**: opened TV channels window `10700` with 589 channels
  (first `KOMO (ABC 4)`); 21 TV channel groups; `alltv` totals 589.
- **Add-ons**: opened Add-on browser window `10040`.

### Home widgets and corrected playlists

| # | Widget | Container | Items | First item |
|---|---|---|---:|---|
| 1 | In-Progress Movies | 501 | 1 | Charlie and the Chocolate Factory |
| 2 | In-Progress Shows | 502 | 15 | Motorheads |
| 3 | Recently Aired Shows | 503 | 50 | 1x08. Spoiler: We're as Confused as You Are |
| 4 | Recently Released Movies | 504 | 36 | “Wuthering Heights” |
| 5 | New Shows | 505 | 50 | Wonder Man |
| 6 | New Movies | 506 | 50 | Strange World |

`Files.GetDirectory` on the corrected playlists returned 50 episodes with air
dates 2026-08-23 through 2026-09-09 — inside the inclusive 2026-08-12 through
2026-09-11 window with no future date — and 36 movies, all year `2026`,
premiered 2026-01-05 through 2026-08-05. Device date: 2026-09-11.

### Power overlay — inspected, never executed

Window `11170` was opened and its focus walked with `Input.Down` only:
Power off system → Custom shutdown timer → Suspend → Reboot → Restart Kodi,
after which focus left the list; there is no sixth item. The managed JSON
holds the same five actions (`Powerdown()`,
`AlarmClock(shutdowntimer,Shutdown())`, `Suspend()`, `Reset()`,
`RestartApp()`). The overlay was closed with `Input.Back`. **No Power item was
selected or executed at any point.**

Screenshots: `screenshot-home-final-accepted-20260911.png`,
`screenshot-power-final-accepted-20260911.png`,
`screenshot-power-overlay-final-20260911.png`,
`screenshot-plex-pm4k-final-20260911.png`,
`screenshot-youtube-final-20260911.png`,
`screenshot-pvr-channels-final-20260911.png`,
`screenshot-hub-addons-final-20260911.png`,
`screenshot-addonbrowser-final-20260911.png`. Full transcript:
`live-acceptance-evidence-final-20260911.txt`.

The device was left at Home with `kodi.service` active, no active player, and
no Power action executed. Multiple profiles remain out of scope.

## Step 11: Review fix round 3 — type-aware runtime normalization

Review identified that the live verifier was type-blind: it reduced every
case-insensitive Next Aired XML match to a value string. Kodi may persist a
disabled `HomeSwitcher.1106.Toggle` as a `type="bool"` node with value
`false`, which the previous empty-only check rejected even though
`Skin.String` has no functional non-empty toggle.

Ruling: transformation remains strict and removes every matching toggle and
mode before Kodi starts. Live verification preserves every matching node's id,
type, and value. Toggle matches are valid only when each is either an empty
string-typed placeholder or bool-typed `false`; `UpNextMode` matches remain
valid only as empty string-typed placeholders. No matches remain valid for
both IDs. If wrong, the cost is either rolling back a correctly disabled
runtime state or accepting stale functional Next Aired state; per-node
type/value checks prevent valid placeholders from masking invalid siblings.

TDD RED was captured at 83/84 report tests for a mixed-case bool-false toggle
plus an empty string placeholder. Adding an empty bool-typed `UpNextMode`
rejection fixture produced 83/85 before production changed. The focused report
suite then passed 85/85. Existing fixtures continue rejecting string-typed
`false`; the bool-true fixture, arbitrary-string mixed fixture, and true
duplicate/case-variant fixture all fail closed.

Targeted verification passed: settings 33/33, report 85/85, and artifacts
52/52. The complete five-suite run passed 231/231 with both ratings keys
present and again with both keys unset. Keyless `--check-config` passed, and
`--check-artifacts` validated all 42 artifacts.

## Step 12: Final review fix wave — verification, transformer, and docs

Final review returned READY with one important and eight minor findings. All
were resolved in one commit, test-first, with no device contact: every change
is verification, transformer scope, report shape, test isolation, or
documentation.

### Important: case-sensitive managed settings comparison

The live probe read every managed skin setting except `HomeSwitcher.1106.*`
through `read_settings()`, a dictionary keyed by the exact id where the last
node wins. Kodi resolves `Skin.String` case-insensitively, so a lowercase or
mixed-case duplicate could mask or override the managed PVR, Add-ons, Plex,
YouTube, or settings-tile state while the verifier still reported `1`.

Ruling: a managed skin setting is correct only when every case-insensitive
match carries the intended value **and** at least one of those matches is a
direct child of the settings root, because Kodi parses only root children. A
removed managed setting is correct only when every case-insensitive match is
empty. The documented `1106` disabled representations (empty string-typed
placeholder, bool-typed `false`, empty string-typed `UpNextMode`) remain the
only accepted runtime normalization. If wrong, the cost is rolling back a
device whose duplicates were harmless, or accepting a hub the operator cannot
see; it is bounded by comparing every match instead of one dictionary entry,
and by requiring the value to exist where Kodi reads it.

### Minor: transformer source/runtime scope mismatch

`set_skin_setting()` could reuse a matching node nested under `<category>`,
which Kodi never parses while the recursive verifier does. Ruling: convergence
promotes each managed setting to one canonical root node and removes every
other case-insensitive match, preserving stale-variant removal, atomic
replacement, and idempotence. Unmanaged nested settings are untouched.

### Minor: failure-path applied list

`sed ... > APPLIED.txt 2>/dev/null || :` could truncate the list rollback uses
to delete files this run created and still report a complete restoration. The
rebuild now lands on a separate file and is promoted only on success; a failed
rebuild is reported and makes the rollback an explicit incomplete rollback
that retains the transaction, staging, and pointer.

### Minor: diagnostics, report shape, docs, and test isolation

- `arctic_fuse.next_aired_hub`, `arctic_fuse.pvr_hub`, and
  `arctic_fuse.addons_hub` are observed and compared independently;
  `arctic_fuse.hubs` remains the aggregate, fatal verdict.
- The Next Aired explanation is now the informational `next_aired_note` report
  field; `manual_action.N` and `manual_actions` count real steps only.
- The acceptance runbook requires the on-device Home hub walk — the
  report-only path passed while a Next Aired hub was still navigable — and
  still forbids selecting or activating any Power item.
- The Power label is the accepted `Custom shutdown timer`.
- The Dec 31 midnight boundary of the provisioning-time current-year playlist
  is documented: a deployment straddling the rollover fails closed and is
  rerun.
- `config/README.md` states that the obsolete movie playlist is not a managed
  widget playlist but is retained in the backup set for reversible removal.
- The theater record states that live acceptance was against `09c784e` and
  that the later verifier-only commits accept the recorded state, so no
  redeployment or reacceptance is claimed or required.
- Ratings-key test isolation stashes and restores the environment instead of
  unsetting it for the rest of the process.

### RED, GREEN, and validation

RED, before any production change:

- `tests/test-coreelec-settings.sh`: 33/34 —
  `test_arctic_fuse_managed_settings_are_promoted_to_root_nodes`,
  `1107.Toggle is one root node (expected=1 1 actual=1 0)`.
- `tests/test-coreelec-report.sh`: 85/95 — six case-variant duplicate/masking
  fixtures (PVR, Add-ons, Plex shortcut path, stale Plex shortcut target,
  YouTube name, settings tile), the category-only fixture, the split hub
  observation fixture, the split hub status comparator, and the manual-action
  count.
- `tests/test-coreelec-artifacts.sh`: 52/53 — the applied-list rebuild failure
  still printed `the device was restored to its pre-deployment state`.

GREEN: settings 34/34, report 95/95, artifacts 53/53. All five suites passed
243/243 with `OMDB_API_KEY` and `MDBLIST_API_KEY` present and again with both
unset through `env -u`; values were never printed. Keyless `--check-config`
passed and `--check-artifacts` validated all 42 artifacts.

No Power action, secret handling, artifact lock, playlist behavior, or
transformed Next Aired removal was changed, and no device was contacted.
