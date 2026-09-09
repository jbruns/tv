# Arctic Fuse 3 Kodi Date Playlist Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two Kodi Omega-incompatible date playlists with a live-validated rolling episode playlist and a provisioning-year movie playlist, then complete acceptance on `coreelec-theater`.

**Architecture:** Keep both widgets as native Kodi smart playlists managed by the existing transactional transformer. Use Kodi Omega's `airdate` date field for episodes, use its numeric `year` field with the device's current year for movies, migrate the movie filename transactionally, and require the remote verifier to enforce the exact generated state and removal of the obsolete file.

**Tech Stack:** Bash, embedded Python 3, Kodi Omega XSP XML, Kodi JSON-RPC, CoreELEC transactional provisioning tests.

**Spec:** `docs/superpowers/specs/2026-09-08-arctic-fuse-3-skin-integration-design.md`

## Global Constraints

- Use the existing atomic transformer, transaction, rollback, verifier, and report architecture.
- Manage only Kodi's primary profile.
- Preserve unrelated settings and files.
- Keep every generated playlist private at mode `0600`.
- Keep the six Home widgets in their existing order and at a 50-item maximum.
- Recently Aired Shows must cover the previous 30 days and exclude future dates.
- Recently Released Movies intentionally means the device's calendar year at provisioning time.
- Rerunning provisioning must update the literal movie year after a year boundary.
- The obsolete `RecentlyReleasedMovies90Days.xsp` must be removed transactionally and restored by rollback when it existed before a failed deployment.
- Do not execute any Power menu action during acceptance.

---

### Task 1: Converge Kodi-Compatible Playlist State

**Files:**
- Modify: `tests/test-coreelec-settings.sh:895-1090`
- Modify: `provision-coreelec.sh:350-380`
- Modify: `provision-coreelec.sh:700-785`
- Modify: `provision-coreelec.sh:825-850`

**Interfaces:**
- Consumes: `write_smart_playlist(path, name, media_type, rules, order, limit=50)`.
- Produces: `remove_managed_file(path)`, which removes an obsolete regular file and records its path in `WRITTEN_PATHS` so rollback restores the backup.
- Produces: `RecentlyAiredEpisodes30Days.xsp` with rules `airdate|inthelast|30 days` and `airdate|notinthelast|-1 days`, ordered by `year` descending.
- Produces: `RecentlyReleasedMoviesCurrentYear.xsp` with rule `year|is|<device current year>`, ordered by `year` descending.

- [ ] **Step 1: Strengthen the transformer playlist test before changing production**

Update `test_arctic_fuse_smart_playlists_have_exact_rules` to assert complete summaries rather than only type and name:

```bash
current_year="$(python3 -c 'import datetime; print(datetime.date.today().year)')"

summary="$(smart_playlist_summary "$(video_playlist_path "${root}" RecentlyAiredEpisodes30Days.xsp)")"
assert_eq \
  '{"limit":"50","match":"all","name":"Recently Aired Shows","order":["year","descending"],"rules":[["airdate","inthelast","30 days"],["airdate","notinthelast","-1 days"]],"type":"episodes"}' \
  "${summary}" \
  "Recently Aired Shows exact XSP"

summary="$(smart_playlist_summary "$(video_playlist_path "${root}" RecentlyReleasedMoviesCurrentYear.xsp)")"
assert_eq \
  "$(printf '{"limit":"50","match":"all","name":"Recently Released Movies","order":["year","descending"],"rules":[["year","is","%s"]],"type":"movies"}' "${current_year}")" \
  "${summary}" \
  "Recently Released Movies exact XSP"
```

Update `test_arctic_fuse_home_widgets_are_exact_and_ordered`, the managed-file mode loop, and managed-path assertions to require `RecentlyReleasedMoviesCurrentYear.xsp`.

- [ ] **Step 2: Add a failing migration and preservation test**

Create `test_arctic_fuse_replaces_obsolete_recently_released_playlist`:

```bash
old_playlist="$(video_playlist_path "${root}" RecentlyReleasedMovies90Days.xsp)"
new_playlist="$(video_playlist_path "${root}" RecentlyReleasedMoviesCurrentYear.xsp)"
mkdir -p "$(dirname "${old_playlist}")"
printf 'obsolete managed content\n' > "${old_playlist}"

written="$(run_transform "${root}" "${payload}")"

[[ ! -e "${old_playlist}" ]] || {
  printf 'obsolete movie playlist still exists\n' >&2
  return 1
}
[[ -f "${new_playlist}" ]] || {
  printf 'current-year movie playlist was not created\n' >&2
  return 1
}
assert_contains "${written}" "${old_playlist}" \
  "obsolete playlist deletion is recorded for rollback"
assert_contains "${written}" "${new_playlist}" \
  "replacement playlist write is recorded for rollback"
```

Also assert that an unrelated playlist beside these files survives unchanged.

Extend `test_automatic_rollback_restores_skin_managed_paths` in
`tests/test-coreelec-artifacts.sh` by pre-seeding
`RecentlyReleasedMovies90Days.xsp` with recognizable old content before the
forced transformer failure. After automatic rollback, assert that the exact
old content has been restored. This proves that recording the deletion in
`WRITTEN_PATHS` is sufficient for the existing `APPLIED.txt` rollback path.

- [ ] **Step 3: Run the settings suite and verify RED**

Run:

```bash
bash tests/test-coreelec-settings.sh
```

Expected: failures show the Home widget still references `RecentlyReleasedMovies90Days.xsp`, the old file is not removed, the replacement is absent, and the current XSP rules still use `firstaired`/`premiered`.

- [ ] **Step 4: Implement the minimal transformer migration**

Import `datetime` in the embedded transformer and add:

```python
def remove_managed_file(path):
    if not os.path.lexists(path):
        return
    if not os.path.isfile(path) or os.path.islink(path):
        fail("refusing to remove a non-regular managed file: %s" % path)
    os.unlink(path)
    WRITTEN_PATHS.append(path)
```

Change the Home widget path to:

```python
"special://profile/playlists/video/RecentlyReleasedMoviesCurrentYear.xsp"
```

Replace the two playlist definitions with:

```python
write_smart_playlist(
    os.path.join(playlists_dir, "RecentlyAiredEpisodes30Days.xsp"),
    "Recently Aired Shows", "episodes",
    [("airdate", "inthelast", "30 days"),
     ("airdate", "notinthelast", "-1 days")],
    ("year", "descending"))

remove_managed_file(
    os.path.join(playlists_dir, "RecentlyReleasedMovies90Days.xsp"))
write_smart_playlist(
    os.path.join(playlists_dir, "RecentlyReleasedMoviesCurrentYear.xsp"),
    "Recently Released Movies", "movies",
    [("year", "is", str(datetime.date.today().year))],
    ("year", "descending"))
```

Keep both the obsolete and replacement paths in `managed_settings_paths()` so backup and rollback cover the migration.

- [ ] **Step 5: Run targeted settings and rollback tests**

Run:

```bash
bash tests/test-coreelec-settings.sh
bash tests/test-coreelec-artifacts.sh
```

Expected: both suites pass, including deletion recording and failed-transaction restoration behavior.

- [ ] **Step 6: Commit the transformer change**

```bash
git add provision-coreelec.sh tests/test-coreelec-settings.sh tests/test-coreelec-artifacts.sh
git commit -m "fix: use Kodi-compatible date playlists" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Enforce the New Playlist Contract Remotely

**Files:**
- Modify: `tests/test-coreelec-report.sh:290-325`
- Modify: `tests/test-coreelec-report.sh:2070-2140`
- Modify: `tests/test-coreelec-report.sh:2200-2390`
- Modify: `provision-coreelec.sh:2235-2305`
- Modify: `provision-coreelec.sh:3065-3085`

**Interfaces:**
- Consumes: the exact XSP contracts produced by Task 1.
- Produces: observation `arctic_fuse.playlist.RecentlyReleasedMoviesCurrentYear.configured`.
- Produces: observation `arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent`.
- The verifier must treat a wrong literal year, a present obsolete playlist, or either malformed XSP as an Arctic Fuse mismatch.

- [ ] **Step 1: Update valid remote-probe fixtures first**

Compute the expected year dynamically in `make_arctic_fuse_fixture_root`:

```bash
local current_year
current_year="$(python3 -c 'import datetime; print(datetime.date.today().year)')"
```

Write the valid fixtures as:

```bash
write_fixture_xsp "${playlists_dir}/RecentlyAiredEpisodes30Days.xsp" episodes \
  "Recently Aired Shows" "all" 50 "year" "descending" \
  "airdate|inthelast|30 days" "airdate|notinthelast|-1 days"
write_fixture_xsp "${playlists_dir}/RecentlyReleasedMoviesCurrentYear.xsp" movies \
  "Recently Released Movies" "all" 50 "year" "descending" \
  "year|is|${current_year}"
```

Update the exact Home widget JSON and complete-state observation fixtures to use the replacement filename and observation key.

- [ ] **Step 2: Add failing probe tests for year drift and stale-file migration**

Add:

```bash
test_probe_previous_year_movie_playlist_emits_zero()
test_probe_obsolete_movie_playlist_emits_absent_zero()
```

The first rewrites `RecentlyReleasedMoviesCurrentYear.xsp` with
`year|is|$((current_year - 1))` and expects configured `0`.

The second creates `RecentlyReleasedMovies90Days.xsp` beside the valid fixture
and expects:

```text
arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent=0
```

- [ ] **Step 3: Run the report suite and verify RED**

Run:

```bash
bash tests/test-coreelec-report.sh
```

Expected: fixture and observation failures show the production probe still expects the obsolete filenames and invalid fields and does not reject a stale obsolete file.

- [ ] **Step 4: Update the remote probe and comparator**

Import `datetime` in the remote probe, then use:

```python
"RecentlyAiredEpisodes30Days": {
    "type": "episodes",
    "name": "Recently Aired Shows",
    "match": "all",
    "limit": "50",
    "rules": [("airdate", "inthelast", "30 days"),
              ("airdate", "notinthelast", "-1 days")],
    "order": ("year", "descending"),
},
"RecentlyReleasedMoviesCurrentYear": {
    "type": "movies",
    "name": "Recently Released Movies",
    "match": "all",
    "limit": "50",
    "rules": [("year", "is", str(datetime.date.today().year))],
    "order": ("year", "descending"),
},
```

Observe obsolete-file absence separately:

```python
observe(
    "arctic_fuse.playlist.RecentlyReleasedMovies90Days.absent",
    0 if os.path.lexists(os.path.join(
        playlists_dir, "RecentlyReleasedMovies90Days.xsp")) else 1)
```

Add `RecentlyReleasedMoviesCurrentYear` to the configured-playlist comparator loop and verify the obsolete absence observation as `arctic_fuse.playlist_migration`.

- [ ] **Step 5: Run targeted report and transaction suites**

Run:

```bash
bash tests/test-coreelec-report.sh
bash tests/test-coreelec-artifacts.sh
```

Expected: both suites pass and malformed, wrong-year, reordered, duplicate, unexpected, and stale-file fixtures remain fatal.

- [ ] **Step 6: Commit strict remote verification**

```bash
git add provision-coreelec.sh tests/test-coreelec-report.sh
git commit -m "fix: verify Kodi-compatible date playlists" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Document the Calendar-Year Compatibility Decision

**Files:**
- Modify: `docs/runbook.md:250-275`
- Modify: `config/README.md` where managed playlist semantics are described
- Modify: `rooms/theater/devices/ugoos-am6b-plus.md:35-60`

**Interfaces:**
- Consumes: the final filenames and semantics from Tasks 1 and 2.
- Produces: operator documentation that says rerunning provisioning updates the movie year and does not claim a rolling 90-day movie window.

- [ ] **Step 1: Update operator-facing documentation**

Document:

```text
Recently Aired Shows (RecentlyAiredEpisodes30Days.xsp)
- rolling previous 30 days
- future dates excluded
- Kodi Omega XSP field: airdate

Recently Released Movies (RecentlyReleasedMoviesCurrentYear.xsp)
- premiere year equals the device year captured during provisioning
- rerun provisioning after a year boundary to update the literal year
- calendar-year behavior was selected because Kodi Omega exposes premiered
  through a numeric XSP field that cannot perform day-level relative filtering
```

Remove claims that `RecentlyReleasedMovies90Days.xsp` remains managed or that the movie widget is a 90-day rolling window.

- [ ] **Step 2: Update the acceptance record's pending expectation**

Keep the prior defect evidence as historical context, but state that the next acceptance run must demonstrate:

```text
RecentlyAiredEpisodes30Days: loads successfully and returns current candidates
RecentlyReleasedMoviesCurrentYear: loads successfully and returns current-year candidates
RecentlyReleasedMovies90Days: absent
```

- [ ] **Step 3: Review documentation consistency**

Run:

```bash
rg -n 'RecentlyReleasedMovies90Days|premiered.*90 days|firstaired.*30 days' \
  docs config rooms provision-coreelec.sh tests
git diff --check
```

Expected: the old filename appears only in migration/removal tests, managed-path rollback coverage, and historical acceptance explanation.

- [ ] **Step 4: Commit documentation**

```bash
git add config/README.md docs/runbook.md rooms/theater/devices/ugoos-am6b-plus.md
git commit -m "docs: explain Kodi playlist compatibility" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Verify Locally and Review the Fix

**Files:**
- Review: all changes since `7153eae`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: a reviewed, locally passing change set ready for live deployment.

- [ ] **Step 1: Run every existing test suite with ratings keys present**

Run with the operator's existing non-empty values:

```bash
for test_script in tests/test-*.sh; do
  bash "${test_script}"
done
```

Expected: every suite passes.

- [ ] **Step 2: Run every existing test suite with ratings keys absent**

Run:

```bash
env -u OMDB_API_KEY -u MDBLIST_API_KEY bash -c '
  for test_script in tests/test-*.sh; do
    bash "${test_script}"
  done
'
```

Expected: every suite passes.

- [ ] **Step 3: Run static configuration and artifact checks**

Run:

```bash
env -u OMDB_API_KEY -u MDBLIST_API_KEY ./provision-coreelec.sh --check-config
env -u OMDB_API_KEY -u MDBLIST_API_KEY ./provision-coreelec.sh --check-artifacts
git diff --check
```

Expected: configuration passes, all 42 artifacts verify, and no whitespace errors exist.

- [ ] **Step 4: Request an independent code review**

Review the diff from `7153eae` through `HEAD`, explicitly checking:

- the undocumented but source-confirmed `notinthelast -1 days` behavior;
- year-boundary behavior;
- obsolete-file rollback;
- strict verifier/report naming;
- test fixture completeness.

- [ ] **Step 5: Apply any high-confidence review fixes test-first**

For every accepted defect, add or adjust a failing test, watch it fail, make the minimal production change, rerun the targeted suite, then rerun all suites.

---

### Task 5: Re-Accept on `coreelec-theater`

**Files:**
- Modify: `rooms/theater/devices/ugoos-am6b-plus.md`
- Store screenshots and reports only under:
  `/Users/jbruns/.copilot/session-state/32cb054d-cfb1-49e6-a64a-19e59adfcb6e/files/arctic-fuse-acceptance/`

**Interfaces:**
- Consumes: a reviewed, locally passing implementation.
- Produces: two committed device transactions, populated Home widget containers, updated screenshots, and a final acceptance record.

- [ ] **Step 1: Remove disposable candidate files from the device**

Delete only:

```text
/storage/.kodi/userdata/playlists/video/CandidateRecentAirdate.xsp
/storage/.kodi/userdata/playlists/video/CandidateRecentPremiereYear.xsp
/storage/.kodi/userdata/playlists/video/CandidateRecentDateAdded.xsp
/storage/.kodi/userdata/playlists/video/CandidateRecentlyReleasedMovies90Days.m3u
/storage/.kodi/userdata/playlists/video/CandidateExactReleasedMovies.xsp
```

Verify each named path is absent before deployment.

- [ ] **Step 2: Run the first transactional deployment**

Run:

```bash
./provision-coreelec.sh \
  --target coreelec-theater \
  --yes \
  --report-dir /Users/jbruns/.copilot/session-state/32cb054d-cfb1-49e6-a64a-19e59adfcb6e/files/arctic-fuse-acceptance
```

Expected: transaction commits; all `arctic_fuse.*` and `metadata.*` statuses are `ok`; the obsolete playlist absence observation is `1`.

- [ ] **Step 3: Validate the two corrected playlists through Kodi**

Use authenticated device-local JSON-RPC `Files.GetDirectory`:

```text
special://profile/playlists/video/RecentlyAiredEpisodes30Days.xsp
special://profile/playlists/video/RecentlyReleasedMoviesCurrentYear.xsp
```

Expected:

- both calls return results rather than `Invalid params`;
- Recently Aired contains only air dates from the rolling 30-day window and no future date;
- Recently Released contains only movies whose premiere year equals the device year;
- each result count is at most 50.

- [ ] **Step 4: Validate Arctic Fuse Home rendering**

Confirm Home containers 503 and 504 both have non-zero items and the widget selector visibly includes:

```text
Recently Aired Shows
Recently Released Movies
```

Capture corrected Home/widget screenshots in the session artifact directory.

- [ ] **Step 5: Run the second deployment for idempotence**

Record the nine current managed-file digests, rerun the same provisioning command, and require another committed transaction with passing verification.

Confirm:

- all standalone managed files are byte-identical;
- all 14 managed skin settings remain exact, string-typed, and duplicate-free;
- the obsolete movie playlist remains absent.

- [ ] **Step 6: Recheck unaffected live surfaces without executing Power**

Confirm Plex launches PM4K, YouTube opens its Videos root, PVR remains populated, all six top-level hubs remain ordered, and the five-item Power menu remains exact. Open and close the Power menu without selecting an action.

- [ ] **Step 7: Update and commit the final acceptance record**

Replace the active XSP blocker with the successful report filenames, item counts, widget evidence, screenshots, idempotence result, and Power non-execution confirmation.

```bash
git add rooms/theater/devices/ugoos-am6b-plus.md
git commit -m "docs: complete Arctic Fuse live acceptance" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Complete Whole-Branch Review

**Files:**
- Review: `origin/main...HEAD`

**Interfaces:**
- Consumes: completed live acceptance.
- Produces: a branch ready for the finishing workflow.

- [ ] **Step 1: Request a whole-branch code review**

Include the previously deferred review points:

- inconsistent but valid `WRITTEN_PATHS` output indentation;
- suppressed `sed` failure when translating `applied.raw`;
- playlist assertion depth;
- test-local environment mutation;
- `xml_setting_type` missing-node contract.

- [ ] **Step 2: Apply any accepted findings test-first**

Use one final focused fix wave, rerun targeted tests, then repeat the full local verification from Task 4.

- [ ] **Step 3: Confirm repository state**

Run:

```bash
git status --short
git log --oneline origin/main..HEAD
git diff --check origin/main...HEAD
```

Expected: only intentional tracked changes remain, no temporary live evidence is committed, and the branch diff is clean.

- [ ] **Step 4: Use the branch-finishing workflow**

Invoke `superpowers:finishing-a-development-branch` and present the integration choices without deploying or restarting production services.
