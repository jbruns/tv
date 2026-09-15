# Arctic Fuse 3 Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision native Arctic Fuse 3 TV and Movies hubs, deterministic playlists and utility settings, conditional Live TV state, and the pinned From Ashes sound theme on Ugoos devices.

**Architecture:** Extend the existing `provision-coreelec.sh` Python transformer and verification probe rather than importing Arctic Fuse 2 state. Keep Home and the AF3 built-in PVR hub, manage custom slots `1101` through `1104` explicitly, generate exact AF3 skinvariables JSON and Kodi smart playlists, and verify every managed surface through the existing transactional report.

**Tech Stack:** POSIX shell/Bash test harnesses, embedded Python 3 (`xml.etree.ElementTree`, JSON), Kodi 21 smart playlists, Arctic Fuse 3.2.16 skinvariables nodes, CoreELEC artifact locking.

**Spec:** `docs/superpowers/specs/2026-09-13-arctic-fuse-3-provisioning-design.md`

## Global Constraints

- CoreELEC remains locked to 21.3 Omega `Amlogic-ng.arm`.
- Arctic Fuse remains locked to `skin.arctic.fuse.3` 3.2.16.
- Stable Emby remains `repository.emby.kodi` 1.0.8 and `plugin.service.emby-next-gen` 11.1.27; do not change manual Emby onboarding or persist Emby database state.
- Do not reintroduce YouTube artifacts, settings, workflows, or navigation.
- Home retains its six existing widgets; focused TV and Movies hubs are additive.
- Custom slot order is `1101` TV Shows, `1102` Movies, `1103` Plex, and disabled `1104`; use built-in `1107` PVR and `1108` Add-ons.
- PVR state is enabled only when both `NEXTPVR_HOST` and `NEXTPVR_PIN` are configured.
- Emby/server metadata owns the `trakt-popular` and `trakt-weekend-box-office` tags; provisioning owns only the XSP definitions and widget references.
- Use absence, never the string `"false"`, to disable AF3 switcher toggles.
- Preserve unrelated XML settings and unrelated sibling skinvariables nodes.
- Every new managed path must participate in snapshot and rollback before remote mutation.
- Do not copy from, stage, or commit any file under `2h2025/`.
- Use only pinned HTTPS artifacts with exact ID, version, and lowercase SHA-256.

---

### Task 1: Protect the backup and pin From Ashes

**Files:**
- Modify: `.gitignore`
- Modify: `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf:108-180`
- Modify: `tests/test-coreelec-config.sh:405-590`

**Interfaces:**
- Consumes: the existing `ADDON_ARTIFACT=id|version|https-url|sha256` lock format and `reviewed_artifact_ids`.
- Produces: locked artifact `resource.uisounds.fromashes|3.0.01|https://mirrors.kodi.tv/addons/omega/resource.uisounds.fromashes/resource.uisounds.fromashes-3.0.01.zip|63fb3d37196cecf617eabde5f3c1a4b3795ee4f48ee15a242d43dbe65915d5a7`; root ignore rule `/2h2025/`.

- [ ] **Step 1: Write failing artifact-lock tests**

Add `resource.uisounds.fromashes` to `reviewed_artifact_ids`, assert its exact
version with the other AF3 resources, and change the expected lock count from
40 to 41:

```bash
test_production_config_locks_arctic_fuse_supported_optional_addons() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  assert_artifact_version "resource.uisounds.fromashes" "3.0.01"
  # Keep the existing assertions in this function.
}

test_production_config_records_each_artifact_exactly_once() {
  coreelec_config_defaults
  coreelec_config_load "${PRODUCTION_CONFIG}"
  local duplicates
  duplicates="$(artifact_id_versions | cut -f1 | LC_ALL=C sort | uniq -d)"
  assert_eq "" "${duplicates}" "no artifact ID appears twice"
  assert_eq "41" "${#ADDON_ARTIFACTS[@]}" "locked artifact count"
}
```

- [ ] **Step 2: Run the config suite and verify the new expectations fail**

Run:

```bash
./tests/test-coreelec-config.sh
```

Expected: FAIL because `resource.uisounds.fromashes` is absent and the lock
still has 40 records.

- [ ] **Step 3: Add the ignore rule and locked artifact**

Append this root-anchored rule to `.gitignore`:

```gitignore
/2h2025/
```

Add this record with the other AF3 supported optional resources:

```conf
ADDON_ARTIFACT=resource.uisounds.fromashes|3.0.01|https://mirrors.kodi.tv/addons/omega/resource.uisounds.fromashes/resource.uisounds.fromashes-3.0.01.zip|63fb3d37196cecf617eabde5f3c1a4b3795ee4f48ee15a242d43dbe65915d5a7
```

Do not copy the ZIP into the repository.

- [ ] **Step 4: Run lock and ignore verification**

Run:

```bash
./tests/test-coreelec-config.sh
git check-ignore -v 2h2025 2h2025/userdata/playlists/video/'Trakt Popular TV Shows.xsp'
git ls-files -- '2h2025' '2h2025/**'
```

Expected: all config tests PASS; both backup paths cite `.gitignore`; the
`git ls-files` command prints nothing.

- [ ] **Step 5: Commit the artifact and safety boundary**

```bash
git add .gitignore \
  config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf \
  tests/test-coreelec-config.sh
git commit -m "feat: pin Arctic Fuse sound theme" \
  -m "Protect the legacy Kodi backup and add the verified From Ashes Omega artifact to the reviewed lock.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Converge Kodi defaults, switcher slots, and option tiles

**Files:**
- Modify: `tests/test-coreelec-settings.sh:261-332`
- Modify: `tests/test-coreelec-settings.sh:1017-1130`
- Modify: `provision-coreelec.sh:535-715`

**Interfaces:**
- Consumes: transformer payload accessors `config(key)`, `have(key)`, existing `set_kodi_setting`, `set_skin_setting`, and `remove_skin_setting`.
- Produces: static Kodi defaults; `nextpvr_configured: bool`; canonical slot settings for TV `1101`, Movies `1102`, Plex `1103`, absent `1104`, conditional PVR `1107`, and Add-ons `1108`; deterministic option tiles.

- [ ] **Step 1: Add failing Kodi-default tests**

Extend `test_regional_settings_are_created` or add
`test_shared_kodi_media_defaults_are_created` with these exact assertions:

```bash
assert_eq "1" "$(xml_setting "${settings}" videolibrary.flattentvshows)" \
  "TV seasons are flattened"
assert_eq "true" "$(xml_setting "${settings}" videolibrary.ignorevideoextras)" \
  "video extras are ignored"
assert_eq "true" "$(xml_setting "${settings}" videolibrary.ignorevideoversions)" \
  "video versions are ignored"
assert_eq "false" "$(xml_setting "${settings}" input.enablemouse)" \
  "mouse input is disabled"
assert_eq "resource.uisounds.fromashes" \
  "$(xml_setting "${settings}" lookandfeel.soundskin)" \
  "From Ashes is the selected sound skin"
```

Seed conflicting duplicates in `test_duplicate_settings_are_collapsed`, and
seed unrelated settings in `test_existing_unmanaged_settings_are_preserved`.

- [ ] **Step 2: Add failing switcher and conditional-state tests**

Replace the old Plex-at-`1101` expectations in
`test_arctic_fuse_hubs_and_options_tray_are_converged` with:

```bash
assert_eq "TV Shows" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Name")"
assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1101.Toggle")"
assert_eq "Movies" "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Name")"
assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1102.Toggle")"
assert_eq "Plex" "$(xml_setting "${skin_file}" "HomeSwitcher.1103.Name")"
assert_eq "RunAddon(script.plexmod)" \
  "$(xml_setting "${skin_file}" "HomeSwitcher.1103.Shortcut.Path")"
skin_setting_absent "${root}" "HomeSwitcher.1104.Toggle"
assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1107.Toggle")"
assert_eq "true" "$(xml_setting "${skin_file}" "HomeSwitcher.1108.Toggle")"
assert_eq "NowPlaying" "$(xml_setting "${skin_file}" "optionstiles.01.include")"
assert_eq "Settings" "$(xml_setting "${skin_file}" "optionstiles.02.include")"
assert_eq "Weather" "$(xml_setting "${skin_file}" "optionstiles.03.include")"
assert_eq "SystemInfo" "$(xml_setting "${skin_file}" "optionstiles.04.include")"
```

Seed stale YouTube values in `1102` and stale values in every `1104` field.
Assert that TV and Movies have no direct `Shortcut.Path` or `Shortcut.Target`,
Plex has no shortcut target or spotlight fields, and every managed value is a
single direct root child.

Add one test that appends these payload overrides:

```bash
append_payload_entry "${payload}" "NEXTPVR_HOST" ""
append_payload_entry "${payload}" "HAVE_NEXTPVR_PIN" "0"
append_payload_entry "${payload}" "HOME_ASSISTANT_URL" ""
append_payload_entry "${payload}" "HOME_ASSISTANT_WEATHER_ENTITY" ""
append_payload_entry "${payload}" "HAVE_HOME_ASSISTANT_TOKEN" "0"
```

After transformation, assert `HomeSwitcher.1107.Toggle` and every
`optionstiles.03.{include,path,target}` setting are absent while all other
slots and tiles remain configured.

- [ ] **Step 3: Run the settings suite and verify the tests fail**

Run:

```bash
./tests/test-coreelec-settings.sh
```

Expected: FAIL on the new defaults, slot assignments, PVR conditional, and
option-tile assertions.

- [ ] **Step 4: Add the Kodi defaults**

Extend `kodi_values` in the transformer with:

```python
"input.enablemouse": "false",
"lookandfeel.soundskin": "resource.uisounds.fromashes",
"videolibrary.flattentvshows": "1",
"videolibrary.ignorevideoextras": "true",
"videolibrary.ignorevideoversions": "true",
```

Keep the existing merge loop so duplicate managed settings collapse and
unmanaged values survive.

- [ ] **Step 5: Implement canonical switcher ownership**

Compute `nextpvr_configured` once from the existing validated payload. Manage:

```python
# 1101: TV Shows native custom hub
set_skin_setting("HomeSwitcher.1101.Name", "TV Shows")
set_skin_setting("HomeSwitcher.1101.Toggle", "true")
set_skin_setting("HomeSwitcher.1101.Icon",
                 "special://skin/extras/icons/tv.png")
set_skin_setting("HomeSwitcher.1101.Mode", "Standard")
set_skin_setting("HomeSwitcher.1101.Spotlight.Label", "Random TV Shows")
set_skin_setting("HomeSwitcher.1101.Spotlight.Path",
                 "special://skin/extras/playlists/RandomTvShows.xsp")
set_skin_setting("HomeSwitcher.1101.Spotlight.Target", "videos")
remove_skin_setting("HomeSwitcher.1101.Shortcut.Path")
remove_skin_setting("HomeSwitcher.1101.Shortcut.Target")

# 1102: Movies native custom hub; this overwrites stale YouTube-era state.
set_skin_setting("HomeSwitcher.1102.Name", "Movies")
set_skin_setting("HomeSwitcher.1102.Toggle", "true")
set_skin_setting("HomeSwitcher.1102.Icon",
                 "special://skin/extras/icons/film.png")
set_skin_setting("HomeSwitcher.1102.Mode", "Standard")
set_skin_setting("HomeSwitcher.1102.Spotlight.Label", "Random Movies")
set_skin_setting("HomeSwitcher.1102.Spotlight.Path",
                 "special://skin/extras/playlists/RandomMovies.xsp")
set_skin_setting("HomeSwitcher.1102.Spotlight.Target", "videos")
remove_skin_setting("HomeSwitcher.1102.Shortcut.Path")
remove_skin_setting("HomeSwitcher.1102.Shortcut.Target")

# 1103: Plex direct entry
set_skin_setting("HomeSwitcher.1103.Name", "Plex")
set_skin_setting("HomeSwitcher.1103.Toggle", "true")
set_skin_setting("HomeSwitcher.1103.Icon",
                 "special://home/addons/script.plexmod/icon2.png")
set_skin_setting("HomeSwitcher.1103.Shortcut.Path",
                 "RunAddon(script.plexmod)")
for suffix in ("Shortcut.Target", "Spotlight.Label", "Spotlight.Path",
               "Spotlight.Target"):
    remove_skin_setting("HomeSwitcher.1103." + suffix)
```

Remove `Name`, `Toggle`, `Icon`, `Mode`, `Shortcut.Path`,
`Shortcut.Target`, `Spotlight.Label`, `Spotlight.Path`, and
`Spotlight.Target` for `1104`.

Set `HomeSwitcher.1107.Toggle` only when `nextpvr_configured`; otherwise remove
it. When configured, remove `Hub.1107.DisableSearch`,
`Hub.1107.DisableChannels`, `Hub.1107.DisableGroups`, and
`Hub.1107.DisableRecordings`. Keep `HomeSwitcher.1108.Toggle=true`.

- [ ] **Step 6: Implement deterministic option tiles**

Set:

```python
set_skin_setting("optionstiles.01.include", "NowPlaying")
set_skin_setting("optionstiles.02.include", "Settings")
set_skin_setting("optionstiles.04.include", "SystemInfo")
```

If `weather_configured`, set `optionstiles.03.include` to `Weather`;
otherwise remove `optionstiles.03.include`, `optionstiles.03.path`, and
`optionstiles.03.target`.

- [ ] **Step 7: Run settings tests**

Run:

```bash
./tests/test-coreelec-settings.sh
```

Expected: PASS, including the pre-existing idempotence, root-promotion, and
unmanaged-setting preservation tests.

- [ ] **Step 8: Commit settings convergence**

```bash
git add provision-coreelec.sh tests/test-coreelec-settings.sh
git commit -m "feat: configure Arctic Fuse content hubs" \
  -m "Assign native TV and Movies hubs, move Plex to the third custom slot, gate PVR and Weather by configuration, and apply shared Kodi media defaults.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Generate focused widgets and smart playlists

**Files:**
- Modify: `tests/test-coreelec-settings.sh:1135-1430`
- Modify: `provision-coreelec.sh:715-915`

**Interfaces:**
- Consumes: `write_json_atomic`, `write_smart_playlist`, `remove_managed_file`, and the switcher assignments from Task 2.
- Produces: `skinvariables-shortcut-1101widgets.json`, `skinvariables-shortcut-1102widgets.json`, `TraktPopularTVShows.xsp`, `TraktWeekendBoxOffice.xsp`, and `RecentlyReleasedMoviesCurrentAndPreviousYear.xsp`; updated Home reference; removal of both superseded recent-movie playlists.

- [ ] **Step 1: Add failing per-hub widget tests**

Add exact ordered JSON assertions for:

```python
[
    {"guid": "coreelec-tv-inprogress", "icon": "",
     "label": "In-Progress Shows",
     "path": "special://profile/playlists/video/InProgressShows90Days.xsp",
     "target": "videos"},
    {"guid": "coreelec-tv-recently-aired", "icon": "",
     "label": "Recently Aired Shows",
     "path": "special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp",
     "target": "videos"},
    {"guid": "coreelec-tv-trakt-popular", "icon": "",
     "label": "Trakt Popular TV Shows",
     "path": "special://profile/playlists/video/TraktPopularTVShows.xsp",
     "target": "videos"},
    {"guid": "coreelec-tv-new", "icon": "", "label": "New Shows",
     "path": "special://profile/playlists/video/NewShows.xsp",
     "target": "videos"},
]
```

and:

```python
[
    {"guid": "coreelec-movies-inprogress", "icon": "",
     "label": "In-Progress Movies",
     "path": "special://profile/playlists/video/InProgressMovies90Days.xsp",
     "target": "videos"},
    {"guid": "coreelec-movies-recently-released", "icon": "",
     "label": "Recently Released Movies",
     "path": "special://profile/playlists/video/RecentlyReleasedMoviesCurrentAndPreviousYear.xsp",
     "target": "videos"},
    {"guid": "coreelec-movies-trakt-box-office", "icon": "",
     "label": "Trakt Weekend Box Office",
     "path": "special://profile/playlists/video/TraktWeekendBoxOffice.xsp",
     "target": "videos"},
    {"guid": "coreelec-movies-new", "icon": "", "label": "New Movies",
     "path": "special://profile/playlists/video/NewMovies.xsp",
     "target": "videos"},
]
```

Update the Home widget expectation so its Recently Released Movies item points
to `RecentlyReleasedMoviesCurrentAndPreviousYear.xsp`.

- [ ] **Step 2: Add failing exact playlist and migration tests**

Using `smart_playlist_summary`, assert:

```bash
current_year="$(python3 -c 'import datetime; print(datetime.date.today().year)')"
lower_bound="$((current_year - 2))"
upper_bound="$((current_year + 1))"

expected_recent="$(printf \
  '{"limit":"50","match":"all","name":"Recently Released Movies","order":["year","descending"],"rules":[["year","greaterthan","%s"],["year","lessthan","%s"]],"type":"movies"}' \
  "${lower_bound}" "${upper_bound}")"
```

Assert these additional signatures:

```json
{"limit":"25","match":"all","name":"Trakt Popular TV Shows","order":["dateadded","descending"],"rules":[["tag","contains","trakt-popular"]],"type":"tvshows"}
{"limit":"25","match":"all","name":"Trakt Weekend Box Office","order":["dateadded","descending"],"rules":[["tag","contains","trakt-weekend-box-office"]],"type":"movies"}
```

Seed both `RecentlyReleasedMoviesCurrentYear.xsp` and
`RecentlyReleasedMovies90Days.xsp`; assert both are absent after transformation.
Extend mode-600, managed-path, failed-write cleanup, unrelated-node
preservation, and byte-identical second-run assertions to cover all new files.

- [ ] **Step 3: Run settings tests and verify the new file expectations fail**

Run:

```bash
./tests/test-coreelec-settings.sh
```

Expected: FAIL because the hub nodes and three new playlists do not exist and
Home still references the current-year playlist.

- [ ] **Step 4: Write native AF3 hub widget nodes**

Write the two exact arrays from Step 1 with:

```python
write_json_atomic(
    os.path.join(nodes_dir, "skinvariables-shortcut-1101widgets.json"),
    tv_widgets)
write_json_atomic(
    os.path.join(nodes_dir, "skinvariables-shortcut-1102widgets.json"),
    movie_widgets)
```

Keep the six Home items and power menu unchanged except for the Home recent
movie path.

- [ ] **Step 5: Generate the three playlist definitions and migrations**

Use:

```python
current_year = datetime.date.today().year

remove_managed_file(
    os.path.join(playlists_dir, "RecentlyReleasedMovies90Days.xsp"))
remove_managed_file(
    os.path.join(playlists_dir, "RecentlyReleasedMoviesCurrentYear.xsp"))

write_smart_playlist(
    os.path.join(
        playlists_dir,
        "RecentlyReleasedMoviesCurrentAndPreviousYear.xsp"),
    "Recently Released Movies", "movies",
    [("year", "greaterthan", str(current_year - 2)),
     ("year", "lessthan", str(current_year + 1))],
    ("year", "descending"))

write_smart_playlist(
    os.path.join(playlists_dir, "TraktPopularTVShows.xsp"),
    "Trakt Popular TV Shows", "tvshows",
    [("tag", "contains", "trakt-popular")],
    ("dateadded", "descending"), limit=25)

write_smart_playlist(
    os.path.join(playlists_dir, "TraktWeekendBoxOffice.xsp"),
    "Trakt Weekend Box Office", "movies",
    [("tag", "contains", "trakt-weekend-box-office")],
    ("dateadded", "descending"), limit=25)
```

- [ ] **Step 6: Extend the managed path contract**

Add both hub JSON nodes, all three new playlists, and both removed migration
paths to `managed_settings_paths`. Keep removed paths listed because rollback
must restore a pre-existing file that provisioning deletes.

- [ ] **Step 7: Run settings tests**

Run:

```bash
./tests/test-coreelec-settings.sh
```

Expected: PASS with exact JSON order, XSP signatures, migration removal,
private modes, idempotence, and managed-path coverage.

- [ ] **Step 8: Commit widgets and playlists**

```bash
git add provision-coreelec.sh tests/test-coreelec-settings.sh
git commit -m "feat: add focused Arctic Fuse widgets" \
  -m "Provision native TV and Movies widget nodes, Trakt tag playlists, and a Kodi-compatible two-year release playlist with guarded migrations.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Verify every managed Arctic Fuse surface

**Files:**
- Modify: `tests/test-coreelec-report.sh:2250-3260`
- Modify: `provision-coreelec.sh:2280-2505`
- Modify: `provision-coreelec.sh:3140-3265`

**Interfaces:**
- Consumes: exact settings, JSON arrays, playlists, payload flags, and artifact manifest from Tasks 1-3.
- Produces: specific `arctic_fuse.*` observations and comparator failures for TV, Movies, Plex, disabled `1104`, conditional PVR, Add-ons, option tiles, Kodi defaults, three widget nodes, all playlists, migrations, and From Ashes.

- [ ] **Step 1: Update the valid report fixture**

Change `make_arctic_fuse_fixture_root` to write:

- the Task 2 switcher and option settings;
- the five new Kodi settings;
- Home, `1101widgets`, `1102widgets`, and power JSON;
- all eight retained/new playlists; and
- neither superseded recent-movie playlist.

Pass NextPVR configuration and `HAVE_NEXTPVR_PIN=1` in
`run_arctic_fuse_probe`, because the valid fixture expects PVR enabled.

- [ ] **Step 2: Add failing positive and negative probe tests**

The valid baseline must emit `=1` for:

```text
arctic_fuse.tv_hub_configured
arctic_fuse.movies_hub_configured
arctic_fuse.plex_entry_configured
arctic_fuse.custom_1104_disabled
arctic_fuse.pvr_hub_configured
arctic_fuse.pvr_surfaces_configured
arctic_fuse.addons_hub_configured
arctic_fuse.option_tiles_configured
arctic_fuse.kodi_defaults_configured
arctic_fuse.home_widgets_configured
arctic_fuse.tv_widgets_configured
arctic_fuse.movie_widgets_configured
arctic_fuse.playlist.TraktPopularTVShows.configured
arctic_fuse.playlist.TraktWeekendBoxOffice.configured
arctic_fuse.playlist.RecentlyReleasedMoviesCurrentAndPreviousYear.configured
arctic_fuse.playlist.RecentlyReleasedMoviesCurrentYear.absent
arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent
```

Add focused negative tests by changing one field at a time: stale YouTube
shortcut on `1102`, enabled `1104`, wrong Plex slot, PVR present when
unconfigured, a PVR disable flag, missing conditional Weather, unexpected
Weather when unconfigured, wrong widget order, extra widget, wrong Trakt tag,
wrong year bound, present migration file, wrong sound skin, and absent
`resource.uisounds.fromashes` manifest entry.

- [ ] **Step 3: Run report tests and verify the expanded contract fails**

Run:

```bash
./tests/test-coreelec-report.sh
```

Expected: FAIL because the probe and comparator do not yet emit or enforce the
new observations.

- [ ] **Step 4: Expand the remote verification probe**

In `coreelec_remote_verify_probe_source`:

1. Load `guisettings.xml` and verify the five Task 2 settings.
2. Derive `nextpvr_expected` from non-empty `NEXTPVR_HOST` plus
   `HAVE_NEXTPVR_PIN=1`.
3. Derive `weather_expected` from the same conditions the transformer uses.
4. Verify every managed skin setting case-insensitively at the root.
5. For disabled settings, require all case variants to be absent.
6. Compare Home, TV, Movies, and power JSON to exact ordered arrays.
7. Replace the current playlist signature map with all eight expected
   signatures.
8. Observe both superseded playlist paths as absent.

Use separate observations before the aggregate:

```python
observe("arctic_fuse.tv_hub_configured", 1 if tv_hub_ok else 0)
observe("arctic_fuse.movies_hub_configured", 1 if movies_hub_ok else 0)
observe("arctic_fuse.plex_entry_configured", 1 if plex_ok else 0)
observe("arctic_fuse.custom_1104_disabled",
        1 if custom_1104_disabled else 0)
observe("arctic_fuse.pvr_hub_configured", 1 if pvr_hub_ok else 0)
observe("arctic_fuse.pvr_surfaces_configured",
        1 if pvr_surfaces_ok else 0)
observe("arctic_fuse.addons_hub_configured", 1 if addons_hub_ok else 0)
observe("arctic_fuse.hubs_configured", 1 if all((
    tv_hub_ok, movies_hub_ok, plex_ok, custom_1104_disabled,
    pvr_hub_ok, pvr_surfaces_ok, addons_hub_ok)) else 0)
```

For unconfigured NextPVR, `pvr_hub_ok` means no `1107.Toggle` case variant
exists. For configured NextPVR, it means exactly one canonical root string
setting equals `true`.

- [ ] **Step 5: Expand host-side comparator and report output**

Add one `coreelec_verify_boolean_observation` call per observation. Increment
both `failures` and `arctic_fuse_failures` for every applicable mismatch.
Iterate the updated configured and absent playlist names explicitly. Preserve:

```bash
if (( arctic_fuse_failures == 0 )); then
  printf 'arctic_fuse.status=ok\n'
else
  printf 'arctic_fuse.status=mismatch\n'
fi
```

Do not collapse specific failures into only the aggregate status.

- [ ] **Step 6: Run report tests**

Run:

```bash
./tests/test-coreelec-report.sh
```

Expected: PASS for configured and unconfigured conditional fixtures and every
single-field mismatch test.

- [ ] **Step 7: Commit convergence verification**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "feat: verify Arctic Fuse provisioning" \
  -m "Report exact hub, widget, playlist, option, Kodi default, migration, and conditional PVR convergence.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Prove artifact deployment and transactional rollback

**Files:**
- Modify: `tests/test-coreelec-artifacts.sh:2020-2115`
- Modify: `tests/test-coreelec-report.sh` where generic deployed add-on fixtures enumerate the reviewed manifest
- Modify: `provision-coreelec.sh` only if the failing tests expose missing generic artifact/report wiring

**Interfaces:**
- Consumes: the 41-record artifact lock and managed-path list from Tasks 1 and 3.
- Produces: proof that From Ashes is selected/validated by the existing generic artifact pipeline and all newly created or deleted managed files roll back exactly.

- [ ] **Step 1: Extend failing deployment and rollback fixtures**

Add `resource.uisounds.fromashes` 3.0.01 to reviewed manifest fixtures that
assert every locked artifact is deployed and reported.

Extend `test_automatic_rollback_restores_skin_managed_paths`:

- pre-seed `skinvariables-shortcut-1101widgets.json` and assert exact restore;
- leave `skinvariables-shortcut-1102widgets.json` absent and assert rollback
  removes the newly created file;
- pre-seed `RecentlyReleasedMoviesCurrentYear.xsp` and assert exact restore
  after migration deletion;
- leave `TraktPopularTVShows.xsp` absent and assert rollback removes it; and
- retain the existing obsolete 90-day restore assertion.

- [ ] **Step 2: Run artifact and report tests and verify fixtures fail**

Run:

```bash
./tests/test-coreelec-artifacts.sh
./tests/test-coreelec-report.sh
```

Expected: FAIL wherever fixture manifests or rollback expectations still
describe the old paths or 40-artifact set.

- [ ] **Step 3: Complete generic wiring only where tests identify a gap**

The existing artifact parser, ZIP validator, selection, transfer, device-side
checksum validation, add-on enablement, and generic report inventory should
accept From Ashes without a special-case branch. If a test fails, update the
reviewed fixture/manifest list first. Change production logic only when the
generic pipeline demonstrably omits the valid locked resource add-on.

Ensure `managed_settings_paths` lists all new and removed paths before the
backup program snapshots them.

- [ ] **Step 4: Run artifact download validation**

Run:

```bash
./provision-coreelec.sh --check-artifacts
```

Expected: all 41 HTTPS artifacts download and pass checksum, single-root,
add-on ID, and version validation; From Ashes reports version 3.0.01.

- [ ] **Step 5: Run rollback and report tests**

Run:

```bash
./tests/test-coreelec-artifacts.sh
./tests/test-coreelec-report.sh
```

Expected: PASS, including exact restoration/removal for every new widget and
playlist path.

- [ ] **Step 6: Commit transaction coverage**

```bash
git add provision-coreelec.sh \
  tests/test-coreelec-artifacts.sh \
  tests/test-coreelec-report.sh
git commit -m "test: cover AF3 artifact rollback" \
  -m "Verify From Ashes deployment and exact rollback of the new managed widget and playlist paths.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Document the final managed contract

**Files:**
- Modify: `config/README.md:100-170`
- Modify: `docs/operations/provision-ugoos.md:1-90`
- Modify: `docs/superpowers/specs/2026-09-13-arctic-fuse-3-provisioning-design.md` only if implementation required an approved design correction

**Interfaces:**
- Consumes: final exact artifact count, paths, conditional behavior, and report keys from Tasks 1-5.
- Produces: operator-facing description of the implemented AF3 baseline and the Trakt/Emby ownership boundary.

- [ ] **Step 1: Update the configuration reference**

In `config/README.md`:

- change the lock count from 40 to 41;
- list From Ashes among the AF3 resources;
- replace `Home, Plex, PVR, Add-ons` with
  `Home, TV Shows, Movies, Plex, conditional PVR, Add-ons`;
- list the Home, TV, and Movies widgets in order;
- document the current-and-previous-year numeric XSP semantics;
- document both removed recent-movie playlist paths;
- document conditional Weather and PVR state;
- list the five managed Kodi defaults; and
- state that stable Emby/server metadata supplies the two Trakt tags after
  manual Emby sign-in and library synchronization.

- [ ] **Step 2: Update the provisioning runbook**

In `docs/operations/provision-ugoos.md`, add post-provision checks:

```text
- Confirm Home, TV Shows, Movies, Plex, PVR (when configured), and Add-ons
  appear in order.
- Confirm TV and Movies each show four managed widgets.
- After Emby sign-in and library sync, confirm the Trakt Popular TV Shows and
  Trakt Weekend Box Office widgets populate.
- Confirm the redacted report shows arctic_fuse.status=ok.
```

Explain that an empty Trakt widget after a successful configuration report is
an Emby tag/sync issue, not playlist-definition convergence.

- [ ] **Step 3: Check documentation and repository safety**

Run:

```bash
rg -n "40 records|RecentlyReleasedMoviesCurrentYear|Home order after Home is Plex" \
  config/README.md docs/operations/provision-ugoos.md
git check-ignore -v 2h2025
git ls-files -- '2h2025' '2h2025/**'
git diff --check
```

Expected: the stale-documentation search returns no matches; `2h2025` is
ignored; no backup paths are tracked; `git diff --check` succeeds.

- [ ] **Step 4: Commit documentation**

```bash
git add config/README.md docs/operations/provision-ugoos.md
git commit -m "docs: describe Arctic Fuse content hubs" \
  -m "Document the focused hub layout, conditional utilities, playlist migrations, sound theme, and Emby tag ownership.

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 7: Run final verification

**Files:**
- Verify only; modify the owning task's files if a failure is directly caused by this implementation.

**Interfaces:**
- Consumes: all implementation commits.
- Produces: evidence that the exact spec is implemented and the worktree contains no backup content.

- [ ] **Step 1: Run all directly affected test suites**

Run:

```bash
./tests/test-coreelec-config.sh
./tests/test-coreelec-settings.sh
./tests/test-coreelec-report.sh
./tests/test-coreelec-artifacts.sh
```

Expected: every test passes.

- [ ] **Step 2: Re-run artifact validation**

Run:

```bash
./provision-coreelec.sh --check-artifacts
```

Expected: all 41 artifacts pass exact checksum, ID, version, and ZIP-structure
validation.

- [ ] **Step 3: Verify the measurable contract**

Run:

```bash
git diff origin/main...HEAD --check
git status --short
git check-ignore -v 2h2025 \
  2h2025/userdata/playlists/video/'Trakt Popular TV Shows.xsp'
git ls-files -- '2h2025' '2h2025/**'
rg -n "plugin.video.youtube|repository.beta.emby.kodi|/multi-repo/beta/" \
  config provision-coreelec.sh configure-coreelec-addons.sh
```

Expected:

- diff check succeeds;
- worktree is clean;
- both backup paths are ignored;
- no backup path is tracked; and
- the obsolete YouTube and beta Emby search returns no matches.

- [ ] **Step 4: Review the final diff against the spec**

Confirm every success criterion in
`docs/superpowers/specs/2026-09-13-arctic-fuse-3-provisioning-design.md` has a
corresponding passing test or explicit command result. Confirm no unrelated
file changed.
