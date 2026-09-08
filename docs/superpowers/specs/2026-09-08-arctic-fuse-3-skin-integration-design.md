# Arctic Fuse 3 Skin Integration Design

**Date:** 2026-09-08

## Goal

Extend the existing CoreELEC provisioning transaction so Arctic Fuse 3 is
fully configured as the shared Kodi interface, including metadata keys,
supported optional dependencies, Home hubs and widgets, local-library Next
Aired data, and a CoreELEC-appropriate Power menu.

The result must be deterministic, idempotent, reversible, secret-safe, and
verified on the disposable `coreelec-theater` device.

## Scope

This work will:

- Require and provision personal OMDb and MDbList API keys for real device
  deployments.
- Document why Arctic Fuse 3's selected Next Aired mode requires neither a
  personal Trakt developer credential nor Trakt user authorization.
- Install and enable every add-on listed in Arctic Fuse 3's supported optional
  dependency catalog.
- Add a first-class Plex Home entry that launches or restores PM4K.
- Enable the Arctic Fuse 3 Next Aired, PVR, and Add-ons Home hubs.
- Keep Settings available in the native Home options tray.
- Replace the default Home widgets with the approved local-library widgets.
- Replace the Arctic Fuse 3 Power menu with the approved CoreELEC actions.
- Manage only Kodi's primary profile.
- Extend automated verification, reporting, rollback coverage, documentation,
  and live acceptance.

This work will not:

- Add or support multiple Kodi profiles.
- Add a Trakt account workflow or accept a user-provided "Trakt API key."
- Add external PM4K content widgets.
- Fork or repackage Arctic Fuse 3.
- Automate clicks through the skin settings UI.
- Execute destructive Power menu actions during acceptance.

## Existing Architecture

`provision-coreelec.sh` already:

- Locks all deployed add-on artifacts and their transitive dependencies.
- Stages artifacts before transmitting secrets.
- Applies add-ons and settings as one remote transaction.
- Uses a Python settings transformer to write Kodi and add-on state atomically.
- Activates `skin.arctic.fuse.3`.
- Accepts `OMDB_API_KEY` and `MDBLIST_API_KEY` only as environment variables.
- Writes those keys to TMDb Helper's `omdb_apikey` and `mdblist_apikey`
  settings.
- Verifies the resulting device state before committing or rolling back.
- Produces a redacted audit report.

`configure-coreelec-addons.sh` is intentionally separate. It performs
post-deployment service checks and guided account flows that cannot be safely
declared. Skin configuration belongs in the transactional provisioner, not in
that post-deployment helper.

## Research Findings

### Arctic Fuse 3 Next Aired

Arctic Fuse 3 version 3.2.16 exposes a native Next Aired Home hub. Its widgets
call TMDb Helper with the mode stored in
`HomeSwitcher.1106.UpNextMode`. The two supported values are:

- `library_nextaired`: derives the schedule from TV shows in Kodi's local
  library.
- `trakt_calendar`: derives a personalized calendar from Trakt.

The skin defaults to `library_nextaired`. No separate TV Show Next Aired
add-on is involved.

TMDb Helper bundles its own Trakt OAuth application client credentials. Trakt
uses the application client ID as the `trakt-api-key` HTTP header, which
explains the misleading "API key" terminology. User-specific Trakt endpoints
also require an OAuth access token obtained through an authorization flow.
Because this design selects `library_nextaired`, neither a personal Trakt
application credential nor Trakt OAuth authorization is required.

### Arctic Fuse 3 Supported Optional Dependencies

In addition to required dependencies, Arctic Fuse 3's Manage Dependencies UI
lists these supported optional add-ons:

- `script.artistslideshow`
- `resource.images.arctic.waves`
- `resource.images.weatherfanart.multi`
- `resource.images.moviecountryicons.maps`
- `resource.images.studios.white`
- `service.upnext`

All six will become pinned, installed, enabled, and verified baseline
dependencies. Their complete transitive artifact closure will also be locked.

### Kodi Smart Playlist Constraints

Kodi smart playlists cannot mix movies and TV content in one dynamic video
playlist. The requested In-Progress content therefore requires separate movie
and TV-show playlists and adjacent Home widgets.

Kodi's native TV-show `inprogress` calculation is accepted for this baseline.
No custom season-level database query or plug-in will be introduced.

### PM4K Home Integration

Arctic Fuse 3 provides four native configurable top-level Home slots,
`HomeSwitcher.1101` through `HomeSwitcher.1104`. A slot can act as a direct
shortcut when its `Shortcut.Path` is a Kodi action and its `Shortcut.Target`
is empty.

PM4K exposes both script and plugin-source extension points, but its
`plugin://script.plexmod/` implementation is only a launcher shim. It returns
no Kodi directory items and delegates to the main PM4K script. It therefore
does not provide stable external directory paths suitable for Arctic Fuse
widgets.

The baseline will use custom slot `1101` as a launch-only Plex entry. Its
action will be `RunAddon(script.plexmod)`, which starts PM4K or asks an already
running instance to restore itself.

## Selected Approach

Extend the existing transactional provisioner with declarative, version-gated
Arctic Fuse 3 managed state.

This is preferred over GUI automation because the generated state is
deterministic, directly testable, and fail-closed. It is preferred over a skin
fork because local policy remains separate from upstream add-on code and does
not create a permanent repackaging burden.

The provisioner will continue to install the upstream pinned skin artifact
unchanged.

## Managed State

The remote settings transformer will atomically converge these additional
primary-profile resources:

- Arctic Fuse 3 settings in
  `special://profile/addon_data/skin.arctic.fuse.3/settings.xml`.
- Skin Variables Home widget node JSON in
  `special://profile/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/`.
- Skin Variables Power menu node JSON in the same node directory.
- Six smart playlists under `special://profile/playlists/video/`.

Every managed file will:

- Be written through an exclusive private temporary file and atomic rename.
- Be included in the transaction's backup, applied-state, and rollback
  manifests.
- Have deterministic ordering and formatting.
- Produce byte-identical output on an unchanged second run.
- Replace the corresponding managed menu or playlist on every run.

Unmanaged skin and add-on settings will be preserved. The provisioner will not
replace the entire Arctic Fuse settings file or the entire Skin Variables data
directory.

Generated menu entries will use stable deterministic GUIDs so Skin Variables
does not treat an idempotent deployment as a new set of shortcuts.

## Home Configuration

The following native Home features will be enabled:

- Plex custom hub:
  - `HomeSwitcher.1101.Name=Plex`
  - `HomeSwitcher.1101.Toggle=true`
  - `HomeSwitcher.1101.Icon=special://home/addons/script.plexmod/icon2.png`
  - `HomeSwitcher.1101.Shortcut.Path=RunAddon(script.plexmod)`
  - `HomeSwitcher.1101.Shortcut.Target` is empty
- Next Aired: `HomeSwitcher.1106.Toggle=true`
- Next Aired data mode:
  `HomeSwitcher.1106.UpNextMode=library_nextaired`
- PVR / Live TV: `HomeSwitcher.1107.Toggle=true`
- Add-ons: `HomeSwitcher.1108.Toggle=true`
- Settings options-tray tile:
  `optionstiles.02.include=Settings`

Arctic Fuse 3 itself additionally requires `System.HasPVRAddon` and
`PVR.HasTVChannels` before it displays the PVR hub. Provisioning will enable
the hub setting, while device verification will continue to require a working
PVR add-on and observable channel groups for full PVR acceptance.

No custom top-level Settings hub will be created.

The fixed Arctic Fuse Home control order places custom slot `1101` immediately
after Home and before the remaining enabled native hubs. Selecting Plex will
launch PM4K directly rather than open an empty custom hub window. No Plex
widgets, spotlight content, submenu, or PM4K plugin-directory URLs will be
configured.

### Home Widget Order

The Home widget node will contain exactly:

1. In-Progress Movies
2. In-Progress Shows
3. Recently Aired Shows
4. Recently Released Movies
5. New Shows
6. New Movies

The previous On Deck, generic In-Progress, Recent Shows, random, Top 250, and
other default Home widgets will not remain in the managed node.

## Smart Playlists

All six playlists will have a maximum of 50 items.

| Widget | Managed playlist filename |
| --- | --- |
| In-Progress Movies | `InProgressMovies90Days.xsp` |
| In-Progress Shows | `InProgressShows90Days.xsp` |
| Recently Aired Shows | `RecentlyAiredEpisodes30Days.xsp` |
| Recently Released Movies | `RecentlyReleasedMovies90Days.xsp` |
| New Shows | `NewShows.xsp` |
| New Movies | `NewMovies.xsp` |

Home widget paths will use
`special://profile/playlists/video/<managed-filename>`, with target `videos`.

### In-Progress Movies

- Type: movies
- Rules:
  - Kodi native `inprogress` is true.
  - `lastplayed` is within the previous 90 days.
- Order: `lastplayed` descending.

### In-Progress Shows

- Type: TV shows
- Rules:
  - Kodi native `inprogress` is true.
  - `lastplayed` is within the previous 90 days.
- Order: `lastplayed` descending.

This intentionally uses Kodi's show-level calculation rather than requiring
an exact partially watched season.

### Recently Aired Shows

- Type: episodes
- Rules:
  - `firstaired` is within the previous 30 days.
  - `firstaired` is not in the future.
- Order: `firstaired` descending.

The widget presents individual episode cards. Entries without `firstaired`
metadata are excluded.

### Recently Released Movies

- Type: movies
- Rules:
  - `premiered` is within the previous 90 days.
  - `premiered` is not in the future.
- Order: `premiered` descending.

Entries without `premiered` metadata are excluded.

### New Shows

- Type: TV shows
- Rule: `playcount` is zero.
- Order: `dateadded` descending.

### New Movies

- Type: movies
- Rule: `playcount` is zero.
- Order: `dateadded` descending.

## Power Menu

The Skin Variables Power menu node will contain exactly:

1. `$LOCALIZE[13016]` (Power off) — Kodi `Powerdown()`
2. `$LOCALIZE[20150]` (Shutdown timer) — Kodi
   `AlarmClock(shutdowntimer,Shutdown())`
3. `$LOCALIZE[13011]` (Suspend) — Kodi `Suspend()`
4. `$LOCALIZE[13013]` (Reboot) — Kodi `Reset()`
5. `Restart Kodi` — Kodi `RestartApp()`

The menu will not contain:

- Favourites
- File manager
- Profiles or logoff
- Quit
- Hibernate
- Reboot from eMMC/NAND
- Master-mode or lock actions

The approved list intentionally resembles the useful subset of the default
CoreELEC Estuary Power menu without exposing profile features or
platform-specific recovery actions.

## Credentials and Secret Handling

### Required Inputs

Real device provisioning requires both:

- `OMDB_API_KEY`
- `MDBLIST_API_KEY`

They remain environment-only inputs. They cannot be set in the configuration
file or supplied as CLI arguments.

Local validation modes that do not contact or mutate a device, including
configuration and artifact checks, may omit the keys. A real deployment must
fail before staging or mutation if either key is absent or empty.

### Transport and Storage

The keys will continue to:

- Enter only through the existing private settings payload.
- Be transmitted after artifact staging, immediately before consumption.
- Be written only to TMDb Helper's primary-profile settings file.
- Be omitted from local and remote process arguments.
- Be removed with payload cleanup on every success and failure path.

The secret-name registry and report redaction check will continue to include
both keys.

Verification will send only key-presence expectations after deployment. The
remote verifier will compare the settings locally and return booleans, never
the stored values.

## Artifact Lock

The shared CoreELEC 21.3 artifact manifest will add the six optional
dependencies and every dependency not already present in the closure.

Each record will continue to include:

- Add-on ID
- Exact version
- HTTPS source URL
- SHA-256 checksum

Artifact checks must prove that every ZIP is safe, matches its declared add-on
ID and version, and that the final lock is a complete dependency closure for
the selected baseline.

Arctic Fuse 3's supported-dependency catalog is version-sensitive. Tests will
record the catalog expected by the pinned skin version so an upstream version
change cannot silently change the baseline.

## Transaction and Failure Handling

The new files and settings are part of the same transaction as the active
skin, add-ons, regional settings, and existing service configuration.

The deployment fails closed and rolls back when any of these occur:

- Either required metadata key is absent for a real deployment.
- An optional artifact or dependency is absent, unsafe, or mismatched.
- A managed XML or JSON source is malformed.
- A managed file cannot be created privately or atomically replaced.
- Kodi does not restart or expose localhost JSON-RPC in time.
- The active skin, enabled add-ons, skin settings, menu nodes, playlists, or
  metadata-key presence do not match the expected state.
- The Plex Home entry does not resolve to the pinned and enabled PM4K add-on.
- The verification response is malformed or incomplete.

Rollback must restore pre-existing versions of every managed file and remove
files that did not exist before the failed deployment.

No broad error suppression or success-shaped fallback will be added.

## Verification and Reporting

The remote observation step will verify:

- Arctic Fuse 3 is installed, enabled, and active.
- All supported optional dependencies are installed at their pinned versions
  and enabled.
- OMDb and MDbList settings are present when required, without returning their
  values.
- The Plex custom entry has the exact approved label, icon, launch action,
  empty target, and position after Home.
- Next Aired, PVR, and Add-ons toggles are enabled.
- Next Aired mode is `library_nextaired`.
- The Settings options-tray entry is enabled.
- The Home widget node has the exact labels, paths, targets, order, and stable
  GUIDs.
- The Power menu node has the exact labels, actions, order, and stable GUIDs.
- All six playlists exist and have the exact approved types, rules, limits,
  and ordering.
- Kodi exposes PVR channel groups after the existing NextPVR validation path.

The audit report will add non-secret status lines for:

- Arctic Fuse Home configuration.
- Plex Home entry configuration.
- Arctic Fuse Power menu configuration.
- Each managed playlist.
- Each optional supported dependency.
- OMDb and MDbList configured presence.
- Overall Arctic Fuse integration status.

No report field will contain an API key, token, complete settings file, or
other secret-bearing content.

## Automated Testing

Use the repository's existing Bash test suites and fixtures.

### Configuration Tests

Cover:

- Both metadata keys are required for real deployment.
- Keyless local checks remain valid.
- Secrets remain forbidden in config files and CLI inputs.
- Empty values fail before device mutation.

### Artifact Tests

Cover:

- Exact optional add-on IDs and versions.
- Complete dependency closure.
- ID, version, checksum, URL, and archive-safety validation.
- Catalog expectations for the pinned Arctic Fuse 3 version.

### Settings Transformer Tests

Cover:

- New-file and existing-file behavior.
- Exact Home and Power JSON.
- Exact Plex custom-slot settings, including an empty shortcut target.
- Exact playlist XML.
- Stable GUIDs and deterministic output.
- Idempotent second runs.
- Preservation of unrelated settings and files.
- Duplicate managed setting collapse.
- Private modes and atomic replacement.
- Cleanup of temporary files.
- Rollback restoration and removal behavior.

### Verification and Report Tests

Cover:

- Success only when every managed value matches.
- Failure for missing, malformed, reordered, duplicated, or unexpected menu
  entries.
- Failure for incorrect playlist rules or paths.
- Failure for an incorrect Plex label, icon, action, target, or PM4K state.
- Failure for missing, disabled, or wrong-version optional dependencies.
- Presence-only metadata-key verification.
- Literal secret redaction from reports and diagnostic output.

## Live Acceptance on `coreelec-theater`

`coreelec-theater` is the disposable CoreELEC 21.3 reference target.

Acceptance will:

1. Run all targeted local tests.
2. Run configuration and artifact checks without requiring secrets.
3. Export operator-provided `OMDB_API_KEY` and `MDBLIST_API_KEY`.
4. Run the real provisioner against `coreelec-theater`.
5. Confirm the transaction commits and the redacted report is complete.
6. Confirm Arctic Fuse 3 is the active skin after Kodi restarts.
7. Verify all optional supported add-ons and managed settings through the
   device's localhost JSON-RPC and SSH inspection paths.
8. Select the Plex Home entry and confirm PM4K starts or restores without
   exposing an intermediate empty hub.
9. Open or query each playlist against the Emby-synced Kodi library and prove
   that every returned item satisfies its type and date/progress rules.
10. Capture and visually inspect the Home and Power screens for labels, order,
   and availability.
11. Run the provisioner a second time and prove idempotent convergence.

Acceptance will not select Power off, Suspend, Reboot, Restart Kodi, or the
shutdown timer from the rendered menu. Their action strings will be verified
without execution.

If the target lacks representative media for one playlist, fixture tests will
remain the semantic proof and live acceptance will record the empty result
without inventing success. The playlist must still load without an error and
have the verified rule definition.

## Documentation

Update the directly related documentation to describe:

- Required OMDb and MDbList environment variables.
- The difference between Trakt's application client ID header and end-user
  OAuth authorization.
- Why local-library Next Aired needs neither.
- The installed optional supported dependencies.
- The launch-only Plex Home entry and why PM4K widgets are not configured.
- The authoritative Home widgets and Power menu.
- The one-profile scope.
- New verification report fields and live acceptance steps.

## References

- Arctic Fuse 3 forum thread:
  <https://forum.kodi.tv/showthread.php?tid=383722>
- Arctic Fuse 3 source:
  <https://github.com/jurialmunkey/skin.arctic.fuse.3>
- TMDb Helper source:
  <https://github.com/jurialmunkey/plugin.video.themoviedb.helper>
- Trakt OAuth documentation:
  <https://docs.trakt.tv/docs/authentication-oauth>
- Kodi smart playlist documentation:
  <https://kodi.wiki/view/Smart_playlists>
