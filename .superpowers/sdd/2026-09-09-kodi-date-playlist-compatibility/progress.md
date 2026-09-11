# SDD ledger — plan: docs/superpowers/plans/2026-09-09-kodi-date-playlist-compatibility.md

Spec: docs/superpowers/specs/2026-09-08-arctic-fuse-3-skin-integration-design.md

## Pre-flight consistency scan

| Scope | Producer / consumer | Finding |
|---|---|---|
| Task 1 | Tests require exact XSPs; transformer produces those XSPs and records obsolete-file deletion | Consistent |
| Task 2 | Task 1 produces filenames/rules; remote probe and comparator consume the same filenames/rules | Consistent |
| Task 3 | Tasks 1-2 produce final behavior and report names; docs describe those exact contracts | Consistent |
| Task 4 | Tasks 1-3 produce the reviewed diff; local verification consumes existing repository test commands | Consistent |
| Task 5 | Task 4 produces reviewed code; live acceptance consumes the committed provisioner and report contract | Consistent |
| Task 6 | Task 5 produces final live evidence; whole-branch review consumes origin/main...HEAD | Consistent |
| Tasks 1 / 2 | Both modify provision-coreelec.sh; Task 2 depends on Task 1 and uses its exact interfaces | Consistent |
| Tasks 1 / 2 | Both modify tests around playlist names; Task 2 changes report fixtures only after transformer tests pass | Consistent |
| Tasks 3 / 5 | Both modify rooms/theater/devices/ugoos-am6b-plus.md; Task 3 records the pending contract and Task 5 replaces the active blocker with results | Consistent |
| Tasks 4 / 6 | Both review changes; Task 4 is compatibility-fix scoped while Task 6 is whole-branch scoped | Consistent |

Ruling: the current isolated worktree satisfies the plan's workspace
requirement; no additional nested worktree will be created — if wrong, the
cost is reduced isolation, but the branch is already separate from main and
all implementation agents share this deliberate task workspace.

Task 1: minor (deferred): rollback assertion uses bare `cat` without a
file-existence guard, matching an adjacent pre-existing assertion.
Task 1: minor (deferred): the test computes the year through Python rather
than `date +%Y`, matching the plan's exact example.
Task 1: reviewer warning resolved: the implementation report records 33/33
settings and 52/52 transaction tests passing.
Task 1: reviewer warning resolved: byte-identical second-run coverage passed
with the runtime year calculation.
Task 1: reviewer warning resolved: `airdate notinthelast -1 days` was already
source-traced and returned 50 valid items on Kodi Omega during the disposable
device probe; final acceptance will recheck it.
Task 1: complete (commits 5584d14..3d57a21, review clean)
Task 2: minor (deferred): the success-path report naming test does not
explicitly assert `arctic_fuse.playlist_migration.status=ok`; the failure
path and comparator behavior are covered.
Task 2: reviewer warning resolved: report records 75/75 report tests and
52/52 transaction tests passing.
Task 2: reviewer warning resolved: the runtime year calculation is
architecturally idempotent within the accepted provisioning model; final live
acceptance will verify the deployed literal.
Task 2: complete (commits 3d57a21..9207be1, review clean)
Task 3: minor (deferred): `config/README.md` names the obsolete file in an
active operator section, but clearly labels it obsolete and unmanaged; this
is useful migration context rather than a stale behavior claim.
Task 3: reviewer warning resolved: controller reran the exact ripgrep scan and
confirmed references are limited to migration/removal, tests, plans, and
historical/pending acceptance context.
Task 3: reviewer warning resolved: controller ran `git diff --check`
successfully.
Task 3: complete (commits 9207be1..2cebddc, review clean)
Task 4: Ruling: the controller's required SDD task-review gate fulfills the
plan's independent-review step; the Task 4 implementer will run verification
and report evidence but will not dispatch its own reviewer — duplicate review
would violate the SDD no-subagents contract — if wrong, the cost is one fewer
independent review layer before live deployment.
Task 4: verification complete: 221/221 tests passed with ratings keys present,
221/221 passed with both keys absent, config check passed, and 42/42 artifacts
validated.
Task 4: minor (deferred): passing report-surface enumeration does not
explicitly name `arctic_fuse.playlist_migration`.
Task 4: minor (deferred): `airdate notinthelast -1 days` is source-confirmed
and live-tested on Omega but should be revalidated on Kodi upgrades.
Task 4: minor (deferred): `config/README.md` says the obsolete file is not
managed, although it remains in the backup set solely for safe removal and
rollback.
Task 4: complete (commits 2cebddc..2cebddc, review clean)
Task 5: corrected-playlist acceptance passed on 2026-09-11. Both corrected
playlists returned valid live results, the obsolete playlist was absent, and
two committed provisioning runs passed verification and playlist
idempotence.
Task 5: unaffected Plex, YouTube, PVR, Add-ons, and Power-menu surfaces were
verified. The Power menu was inspected and closed without executing any
Power action.
Task 5: Next Aired investigation found that TMDb Helper 6.17.1's
`library_nextaired` route uses Trakt's public calendar but still enforces
end-user OAuth, producing `Unauthorised 401 Error TraktAPI Token` without a
token. The bundled Trakt client ID is valid; this is not a missing API key.
Task 5: disposable live testing of `library_airingnext` used local Kodi/TMDb
data but timed out against OMDb and exhausted TMDb Helper's per-library thread
fanout (`UNABLE TO SPAWN 82 THREAD 460` / `can't start new thread`). It is not
reliable enough for automation on this device class.
Task 5: approved ruling — drop Next Aired. The bounded correction converges
`HomeSwitcher.1106.Toggle=false`, removes every case-insensitive
`HomeSwitcher.1106.UpNextMode` before Kodi starts, and leaves managed
navigation after Home as Plex, YouTube, PVR, Add-ons.
Task 5: the first deployment of commit `3b418af` generated
`coreelec-theater-20260911T180528Z.txt` and automatically rolled back solely
because `arctic_fuse.hubs.observed=0`. Controlled backup/restore reproduction
proved Arctic Fuse recreates an empty string-typed `UpNextMode` placeholder
after startup even though transformed state is absent.
Ruling: transformed state must have no case-insensitive `UpNextMode` nodes,
while acceptable live runtime state is either absent or all matching values
empty; any non-empty match still fails — if wrong, the cost is falsely
accepting functional stale Next Aired state, bounded by checking every
case-insensitive match so an empty placeholder cannot mask a non-empty value.
Task 5: two successful final deployments remain pending after the verifier
correction.
Task 5: the two `8390d42` deployments `coreelec-theater-20260911T200447Z.txt`
and `coreelec-theater-20260911T200808Z.txt` both committed with
`verification_result=pass`, `verification_failures=0`, all `metadata.*` and
`arctic_fuse.*` statuses `ok`, and 8/8 byte-identical managed files, but final
live acceptance rejected them: `Container(399)` still listed
`Next Aired → ReplaceWindow(1106)` between YouTube and PVR.
Task 5: root cause of that rejection — Arctic Fuse gates every hub on
`!String.IsEmpty(Skin.String(HomeSwitcher.1106.Toggle))` and maps that
parameter to `<visible>`, while its own dialog disables a hub with
`Skin.Reset(HomeSwitcher.1106.Toggle)`. The literal string `false` is non-empty,
so `Toggle=false` still rendered and still navigated to the Next Aired hub.
Ruling: the disabled contract is removal, not a `false` value — transformed
state must contain no case-insensitive `HomeSwitcher.1106.Toggle` or
`HomeSwitcher.1106.UpNextMode` node, while acceptable live runtime state is
absent or all matching values empty, and any non-empty match fails — if wrong,
the cost is falsely accepting functional stale Next Aired state (or falsely
rejecting Arctic Fuse's own empty placeholder and rolling back a good
deployment); it is bounded by evaluating every case-insensitive match so an
empty placeholder cannot mask a non-empty value, and by the live
`Container(399)` navigation check that caught the original `false` defect.
Task 5: fix round 2 commit `09c784e` (`fix: remove Next Aired hub toggle
entirely`) followed TDD — RED `1106.Toggle must be absent` (32/33 settings) plus
four report failures (79/83), GREEN 33/33 settings and 83/83 report, and
229/229 across all five suites with ratings keys present and with both keys
unset; `--check-config` and 42/42 `--check-artifacts` also passed.
Task 5: final live acceptance of `09c784e` PASSED on 2026-09-11. Reports
`coreelec-theater-20260911T202453Z.txt` and
`coreelec-theater-20260911T202711Z.txt` are both committed and passing with all
statuses `ok` and `arctic_fuse.playlist_migration.observed=1`; 8/8 managed files
byte-identical; live state `next_aired_toggle_count=1 all_empty=True`
(`homeswitcher.1106.toggle` empty string-typed placeholder),
`upnext_mode_count=0`, `managed_skin_settings=12 exact=1 string_typed=1
duplicate_free=1`; navigation `10000 → 11101 → 11102 → 11107 → 11108` with no
Next Aired and zero Trakt/OAuth log matches; Plex started PM4K user select,
YouTube opened 20 root items, PVR showed 21 groups and 589 channels, Add-ons
opened the browser; six Home widgets returned 1/15/50/36/50/50 items matching
their playlists; corrected playlists returned 50 episodes (2026-08-23..
2026-09-09) and 36 movies (all year 2026).
Task 5: the Power overlay `11170` was opened, focus-walked with `Input.Down`
only (Power off system, Custom shutdown timer, Suspend, Reboot, Restart Kodi,
then out of the list), and closed with `Input.Back`. No Power item was selected
or executed at any point in this task.
Task 5: minor (deferred): an exact-same-case duplicate Next Aired toggle was
originally invisible to the dict-based check; fix round 2 replaced it with the
list-based `xml_setting_matches()` helper, so duplicates of any case are now
evaluated, but the verifier still does not assert a node *count*, so two
identical empty placeholders would pass.
Task 5: minor (deferred): the runtime verifier does not assert the Next Aired
toggle's `type` attribute; it only evaluates values.
Task 5: minor (deferred): the transformer's setting lookup searches the root
element and its direct `category` children only, not arbitrary nesting depth.
Task 5: complete (commits 2cebddc..09c784e, live acceptance passed).
