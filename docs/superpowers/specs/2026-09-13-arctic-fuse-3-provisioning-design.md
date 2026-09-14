# Arctic Fuse 3 Provisioning Design

## Status

Approved for implementation planning, but implementation is blocked until the
separate YouTube-removal work is merged and its effect on provisioning is
reviewed.

## Context

The previous known-good Kodi profile used Arctic Fuse 2 with focused TV,
Movies, Music, and Live TV navigation. Current Ugoos provisioning installs
Arctic Fuse 3 and manages a reliable baseline, but its content navigation is
limited to a six-widget Home feed, direct Plex and YouTube entries, the
built-in PVR and Add-ons hubs, and a power menu.

This design restores the useful content discovery behavior through Arctic
Fuse 3's native hub and widget contracts. It does not import or translate the
old Arctic Fuse 2 profile.

## Goals

- Retain the current broad Home widget feed.
- Add focused TV Shows and Movies hubs using native Arctic Fuse 3 custom slots.
- Keep Plex as a direct custom hub entry.
- Use Arctic Fuse 3's built-in PVR hub only when NextPVR is configured.
- Restore the two useful Trakt-tag playlists.
- Replace calendar-based recent-movie behavior with a rolling 12-month window.
- Manage useful option tiles and shared Kodi library/input preferences.
- Pin and provision a Kodi 21-compatible From Ashes UI sound add-on.
- Preserve transactional deployment, rollback, idempotence, and exact
  verification.
- Prevent the local `2h2025/` backup from being staged or committed.

## Non-goals

- Copying or transforming Arctic Fuse 2 settings or shortcut files.
- Copying `sources.xml`, Emby credentials or runtime state, Kodi databases,
  favourites, keymaps, or `advancedsettings.xml`.
- Enabling unknown add-on sources.
- Proving that Emby has populated the Trakt tags at provisioning time.
- Retaining YouTube in Kodi provisioning. Its removal is owned by a separate
  change and is a prerequisite for this work.
- Adding the unused Arctic Fuse 2 Top Rated Unplayed playlist.
- Restoring the disabled Arctic Fuse 2 Music hub.

## Execution Prerequisite

Implementation must not begin until the separate YouTube-removal change has:

1. merged into the implementation branch;
2. removed or revised the existing YouTube artifact, settings, workflow, and
   Home-switcher behavior; and
3. been reviewed to establish the new baseline that this work will modify.

The implementation plan must be written against that merged baseline rather
than assuming the current YouTube behavior can simply be overwritten.

## Navigation Architecture

Provisioning will manage the Arctic Fuse 3 switcher in this order:

1. **Home** remains the root and retains its current six widgets:
   In-Progress Movies, In-Progress Shows, Recently Aired Shows, Recently
   Released Movies, New Shows, and New Movies.
2. **TV Shows (`1101`)** is a native custom hub.
3. **Movies (`1102`)** is a native custom hub.
4. **Plex (`1103`)** directly runs `script.plexmod`.
5. **Custom slot `1104`** is disabled.
6. **PVR (`1107`)** remains Arctic Fuse 3's built-in Live TV hub.
7. **Add-ons (`1108`)** remains enabled.

Disabled custom slots are represented by an absent toggle. Provisioning will
remove stale name, icon, shortcut, target, mode, and spotlight settings for
`1104`. It will also remove stale fields left by the preconditioned YouTube
configuration wherever the merged YouTube-removal baseline has not already
done so. It must not write the string `"false"` for a disabled switcher toggle,
because Arctic Fuse treats any non-empty toggle value as enabled.

### TV Shows hub

The TV Shows hub uses Arctic Fuse 3's supported
`skinvariables-shortcut-1101widgets.json` node with this ordered content:

1. In-Progress Shows (previous 90 days)
2. Recently Aired Shows (previous 30 days, excluding future air dates)
3. Trakt Popular TV Shows
4. New Shows

Its spotlight uses the Arctic Fuse 3 bundled random-TV playlist. The hub's
name, icon, toggle, mode, and spotlight settings are managed explicitly.

### Movies hub

The Movies hub uses Arctic Fuse 3's supported
`skinvariables-shortcut-1102widgets.json` node with this ordered content:

1. In-Progress Movies (previous 90 days)
2. Recently Released Movies (rolling previous 12 months)
3. Trakt Weekend Box Office
4. New Movies

Its spotlight uses the Arctic Fuse 3 bundled random-movies playlist. The hub's
name, icon, toggle, mode, and spotlight settings are managed explicitly.

### Plex entry

Plex moves to `1103` and retains the existing direct
`RunAddon(script.plexmod)` behavior and icon. It is a direct entry, not a
generated content hub.

### Live TV

PVR uses Arctic Fuse 3's native `1107` implementation rather than a custom
widget JSON file. The skin already implements:

- last-played channels;
- channels and channel groups; and
- active recordings.

When NextPVR is configured, provisioning enables `1107` and clears the skin
settings that disable those surfaces. When NextPVR is not configured,
provisioning removes the `1107` toggle and clears stale managed PVR state so an
empty Live TV entry cannot remain visible.

## Smart Playlists

Provisioning continues to generate smart playlists atomically and verify their
exact signatures.

### Existing playlists retained

- `InProgressMovies90Days.xsp`
- `InProgressShows90Days.xsp`
- `RecentlyAiredEpisodes30Days.xsp`
- `NewShows.xsp`
- `NewMovies.xsp`

### New playlists

#### `TraktPopularTVShows.xsp`

- Type: `tvshows`
- Match: all
- Rule: `tag contains trakt-popular`
- Limit: 25
- Order: `dateadded` descending

#### `TraktWeekendBoxOffice.xsp`

- Type: `movies`
- Match: all
- Rule: `tag contains trakt-weekend-box-office`
- Limit: 25
- Order: `dateadded` descending

#### `RecentlyReleasedMovies12Months.xsp`

- Type: `movies`
- Match: all
- Rule: premiere/release date is within the previous 12 months
- Rule: premiere/release date is not in the future
- Limit: 50
- Order: premiere/release date descending

The implementation must use the Kodi 21 smart-playlist field name and
operators that represent this behavior. Tests will lock the resulting XSP
signature.

### Playlist migrations

Provisioning removes these superseded managed files:

- `RecentlyReleasedMoviesCurrentYear.xsp`
- `RecentlyReleasedMovies90Days.xsp`

Removal uses the existing guarded managed-file behavior: symlinks and
non-regular files cause a failure rather than being unlinked.

### Trakt and Emby ownership

Provisioning owns the two Trakt playlist definitions and their widget
references. Emby owns creation and refresh of the Kodi library tags
`trakt-popular` and `trakt-weekend-box-office`.

File verification confirms configuration convergence only. It must not report
that the playlists contain items before an Emby library sync. The redacted
provisioning report and operational documentation will state the tag
dependency.

## Option Tiles

Provisioning manages this deterministic option-tile layout:

1. Now Playing
2. Settings
3. Weather, only when Home Assistant weather is fully configured
4. System Info

When Home Assistant weather is not configured, the Weather tile's include,
path, and target fields are removed rather than left as stale values. Other
managed tile positions remain stable.

## Shared Kodi Defaults

The existing surgical `guisettings.xml` merge gains:

- `videolibrary.flattentvshows = 1`
- `videolibrary.ignorevideoextras = true`
- `videolibrary.ignorevideoversions = true`
- `input.enablemouse = false`
- `lookandfeel.soundskin = resource.uisounds.fromashes`

Provisioning continues to preserve unrelated Kodi settings. It does not
replace `guisettings.xml` wholesale and does not enable unknown sources.

## From Ashes Sound Dependency

The implementation will identify the newest authoritative release of
`resource.uisounds.fromashes` that is explicitly compatible with Kodi 21.
That artifact will be added to the normal add-on lock with:

- exact add-on ID;
- exact version;
- authoritative HTTPS URL; and
- SHA-256 checksum.

The existing artifact validator must confirm the ZIP's top-level directory,
`addon.xml` ID, and version. If no authoritative Kodi 21-compatible artifact
can be established, implementation stops for review. It must not install an
unverified ZIP, copy the add-on from `2h2025/`, silently select an unrelated
sound theme, or write a setting that points to an unmanaged dependency.

Documentation that states a fixed artifact count must be updated to the actual
post-change count.

## Transformer and Managed State

The settings transformer remains the sole writer of managed Kodi and skin
state:

- XML settings are merged and normalized to one canonical root node per
  managed ID.
- Unrelated XML settings remain untouched.
- Managed widget JSON files are replaced atomically with exact ordered arrays.
- New widget and playlist paths are added to the managed-path list before
  remote deployment so snapshot and rollback coverage cannot drift.
- Removed playlists and disabled slots are treated as explicit migration
  state.
- Reapplying the same configuration produces byte-equivalent managed JSON and
  equivalent XML/playlist state.

The new managed paths are:

- the `1101widgets` node;
- the `1102widgets` node;
- the two Trakt playlists; and
- the rolling 12-month movie playlist.

The existing Home widget and power-menu nodes remain managed. The built-in PVR
hub does not require a new widget node.

## Error Handling

- Invalid existing managed XML or JSON remains a hard mismatch or transformer
  failure according to the current contract; it is not silently accepted.
- A non-regular path where a managed playlist must be replaced or removed is a
  hard failure.
- Missing or malformed widget files produce specific failed observations.
- Missing locked sound artifacts fail artifact selection or validation.
- Conditional PVR and Weather states are derived only from validated
  configuration inputs, not from best-effort runtime probing.
- Any partial remote mutation remains covered by the existing transaction
  report and rollback path.

## Verification

### Settings transformer tests

Tests will cover:

- exact switcher order and assignments for TV Shows, Movies, Plex, disabled
  `1104`, conditional PVR, and Add-ons;
- absence-based disable semantics;
- removal of stale YouTube and custom-slot settings against the merged
  prerequisite baseline;
- TV and Movies widget JSON paths, labels, targets, GUIDs, and ordering;
- preservation of the six Home widgets;
- random TV and random movie spotlight settings;
- conditional PVR enablement and enabled native PVR surfaces;
- exact option-tile layout with and without Home Assistant weather;
- all five Kodi defaults;
- exact signatures for every retained and new smart playlist;
- removal of both superseded recent-movie playlists;
- preservation of unrelated XML settings and unrelated sibling skinvariables
  nodes;
- managed-path coverage; and
- idempotent repeated transformation.

### Report and convergence tests

The report will expose specific observations for:

- TV hub;
- Movies hub;
- Plex entry;
- disabled `1104`;
- conditional PVR hub and native PVR surfaces;
- Add-ons hub;
- Home, TV, and Movies widget files;
- each managed playlist and each removed migration playlist;
- option tiles;
- Kodi defaults;
- selected sound skin; and
- From Ashes deployment.

The aggregate Arctic Fuse status is successful only when every applicable
specific observation converges. Conditional PVR and Weather observations use
the selected configuration as their expected state. Missing, malformed,
misordered, or extra managed content produces a mismatch.

### Artifact tests

Tests will confirm that the From Ashes artifact:

- is present in the lock and selected deployment;
- uses HTTPS;
- has the expected ID and version;
- passes SHA-256 validation; and
- has a valid single-root Kodi add-on ZIP structure.

### Targeted validation

Implementation validation will run the existing targeted suites that cover
CoreELEC settings, reporting, and artifacts. Full-suite validation is required
only if those changes expose broader coupling.

## Documentation

The Arctic Fuse managed contract and Ugoos provisioning documentation will be
updated to describe:

- switcher order and slot ownership;
- Home, TV, and Movies widget contents;
- conditional PVR behavior;
- playlist definitions and migrations;
- Trakt/Emby ownership;
- option tiles and Kodi defaults;
- the sound dependency and actual artifact count; and
- the YouTube-removal prerequisite.

## Backup Exclusion

The `2h2025/` backup is reference material only. Implementation will add a
root-anchored `/2h2025/` ignore rule before staging other changes and verify
that Git tracks no path beneath it. No file from the backup may be copied into
the repository, staged, or committed.

## Success Criteria

- A newly provisioned Ugoos presents Home, TV Shows, Movies, Plex, conditional
  PVR, and Add-ons in the designed order.
- Home retains its current six widgets.
- TV and Movies each present their four ordered focused widgets.
- PVR is absent without NextPVR and exposes native AF3 Live TV content when
  NextPVR is configured.
- Both Trakt playlists are provisioned and clearly document their Emby tag
  dependency.
- Recently Released Movies always means the rolling previous 12 months and
  excludes future releases.
- Option tiles and Kodi defaults converge exactly for both conditional
  configurations.
- From Ashes is installed from a pinned, validated Kodi 21-compatible artifact
  and selected as the sound skin.
- Reprovisioning is idempotent, verification is exact, and rollback includes
  every new managed path.
- The `2h2025/` backup remains untracked and cannot be staged by a normal
  repository-root `git add`.
