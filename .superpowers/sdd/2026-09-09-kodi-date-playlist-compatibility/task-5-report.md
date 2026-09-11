# Task 5 Report: Re-Accept on `coreelec-theater`

**Status: CORRECTED PLAYLISTS ACCEPTED; NEXT AIRED REMOVAL FIRST DEPLOYMENT ROLLED BACK; TWO SUCCESSFUL DEPLOYMENTS PENDING**

## Environment

| Field | Value |
|---|---|
| Branch | `agents/arctic-fuse-3-skin-integration` |
| Deployment HEAD | `3b418af` (`fix: disable unreliable Next Aired hub`) |
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

## Step 8: Final live acceptance — TWO SUCCESSFUL DEPLOYMENTS PENDING

The corrected-playlist acceptance is successful and is now recorded in
`rooms/theater/devices/ugoos-am6b-plus.md`. Final live acceptance still
requires two successful corrected deployments, verifying
`HomeSwitcher.1106.Toggle=false`, verifying every case-insensitive live
`UpNextMode` value is empty if a placeholder exists, and confirming navigation
proceeds Home → Plex → YouTube → PVR → Add-ons without the authorization
dialog.

The device was left at Home with `kodi.service` active. No Power action was
executed at any point.
