# M2 exit: authored configuration contribution

Date: 2026-09-19

Status: **Issue #57 contribution only. M2 is not exited by this record.**

## Scope

Issue #57 implements the restricted authored YAML boundary, strict Pydantic
input validation, fixed platform to room to Device composition, frozen domain
values, selector/dependency resolution, opaque secret references, minimal
Artifact and `KodiSmartPlaylist` forms, stable diagnostics, and canonical
round trips.

It does not implement SSH/SFTP, RuntimeValues resolution, Device observation or
mutation, add-on automation, plugins, Plan/Run behavior owned by issue #58, or
live acceptance.

## Accepted-schema differences

None for the implemented `skin.playlist.new-shows` slice. Artifact support is
intentionally limited to the empty catalog and stable direct-origin GitHub
release-asset form; prerelease, patched, repacked, build, attestation, and
download behavior remain unimplemented rather than being approximated.

## Evidence

Local evidence was produced on macOS arm64 with Python 3.14.2, uv 0.12.3,
Ruff 0.16.8, mypy 2.3.1, and pytest 9.1.1.

| Exact command | Result | Elapsed |
| --- | --- | ---: |
| `uv run pytest -q tests/unit/config` | 37 passed | 0.35 s |
| `uv run ruff check .` and the documented `ruff format --check` paths | Passed; 50 files formatted | 0.04 s |
| `uv run mypy` | No issues in 50 source files | 0.10 s |
| Pure/unit/architecture budget command from `docs/development.md` | 95 passed; 2.173 s measured selection, below 10 s | 2.22 s |
| Complete-offline budget command from `docs/development.md` | 14 passed; 3.027 s aggregate, below 60 s | 0.90 s |
| `uv run pytest -q` | 109 passed | 2.94 s |
| `uv build` | Source distribution and wheel built | 0.40 s |
| Documented wheel inspection and installed-wheel smoke | Passed; 47 wheel entries; version/help passed | 0.03 s inspection |
| `python3 scripts/check_markdown.py` | 55 Markdown files passed | 0.20 s |
| `uv run python scripts/check_inventory_milestones.py` | Passed | 0.04 s |
| `python3 scripts/check_shell_permissions.py --audit` | Passed | 0.15 s |
| `git diff --check origin/main...HEAD` | Passed | not timed |

Fixture SHA-256 digests:

| Fixture | SHA-256 |
| --- | --- |
| `tests/fixtures/repository/artifacts/catalog.yaml` | `6fb54bd9af401c37a6561c0f0fd50016afe1f60f963c8b133e1cfc4879ccc41b` |
| `tests/fixtures/repository/inventory/living-room.yaml` | `dc7254c419dad27b485c5eb49839b443ef004c036aa0758f449e011f9bd5d6e4` |
| `tests/fixtures/repository/profiles/device/living-room-ugoos.yaml` | `fa7e88dbd4d9b9b6fb89d614185da3a815e43b274c92a25e3bb2ae5db7004414` |
| `tests/fixtures/repository/profiles/platform/coreelec-21-amlogic-ng.yaml` | `80844bea73be67b1aaee46db2c6611681878a08c700885538e6c6e0f39648185` |
| `tests/fixtures/repository/profiles/room/living-room.yaml` | `69f5a358afc38a0284ea1ab45e789461d561b44f54974f90e1e6e536fcc2faff` |
| `tests/fixtures/repository/secret-providers/controller-environment.yaml` | `d0e1c065c89bb1f45f3d7a123b5dac0e3912dfea2ce380a54b72ec79cdcf84c8` |

The canonical resolved configuration is 1,818 bytes with SHA-256
`004d7e8c39e512fae99572a8e912d6eecd6b3fe0f9088584acae41f61da2208b`.
The built wheel SHA-256 is
`8da0e53ead050fad2b8bc46ed2e6f98a48b66dddfd661cc18f45024de0da10ad`;
the source distribution SHA-256 is
`421f2aa8131bfc21e710194f5f818068695e93bad34516a219de8e21e5fee7a7`.

The mandatory two-axis code review found configuration-boundary ownership and
three fail-closed gaps. The implementation was revised to add the immutable
Resource Type registry and type-owned codecs/address resolution, isolate
composition, validate every layer before merge, reject unapproved playlist
values, reject incomplete nested Intent with diagnostics, validate unknown
types in unselected Profiles, and reject unsupported Artifact dependency
constraints.

The incremental correction review found no standards issue. Its one remaining
spec finding identified canonical string values that still needed schema
validation; Artifact IDs, dependency IDs, versions, platforms, and secret
provider/key IDs now reject invalid values before domain construction.

Hosted Linux/macOS and shell-transition evidence is linked from the pull
request. No Device was accessed and no deployment occurred.

## Issue #58 pure planning contribution

Date: 2026-09-19

Status: **Issue #58 contribution only. M2 remains open and is not sealed by
this record.**

### Scope and acceptance mapping

Issue #58 adds strict semantic Kodi Smart Playlist XML parsing/rendering,
typed bounded supplied Observations, pure assessment, exact Changes and
preconditions, canonical immutable Plan values, canonical nonmutating planning
Run values, strict codecs/digests, and offline `validate`/`plan` application
and CLI paths for `skin.playlist.new-shows`.

The accepted behavior matrix passed:

| Case | Relation and Change | Plan / planning Run |
| --- | --- | --- |
| absent, desired present | divergent; `smart_playlist.create`; reason `playlist.absent` | `actionable` / `awaiting_approval` |
| semantic equivalent, including whitespace, CRLF, BOM, and attribute order | satisfied; no Change | `noop` / `noop` |
| semantic drift | divergent; `smart_playlist.update`; reason `playlist.semantic-drift` | `actionable` / `awaiting_approval` |
| mode-only `0600` | divergent; `smart_playlist.update`; reason `managed-file.mode-drift` | `actionable` / `awaiting_approval` |
| malformed safe regular XML | divergent; `smart_playlist.update`; reason `playlist.malformed-current` | `actionable` / `awaiting_approval` |
| present, desired absent | divergent; `smart_playlist.remove`; reason `playlist.desired-absent` | `actionable` / `awaiting_approval` |
| absent, desired absent | satisfied; no Change | `noop` / `noop` |
| unsafe non-regular state | unverifiable; typed blocker; no Change | `blocked` / `blocked` |

All Changes retain the logical State Address
`special://profile/playlists/video/NewShows.xsp`, a normalized before-state
digest precondition, safe before/desired summaries, verified rollback
capability, and no Effects. Removal additionally carries the ordered
`removal` impact and approval scope. Observe-only divergence is blocked and
cannot produce a Change.

Sanitized test inputs use only the synthetic endpoint
`coreelec-living-room.example.test`, an example pinned-host-key fingerprint,
fixed UUIDv7 values, fixed UTC times, fixed SHA-256 placeholders, and the
public playlist semantics `New Shows`, `tvshows`, `playcount is 0`, limit 50,
date-added descending, mode `0644`. Raw XML is bounded input and is absent
from canonical Plan/Run evidence.

### Canonical and golden evidence

Canonical JSON is UTF-8 with sorted object keys, no insignificant whitespace,
and no trailing newline. CLI framing adds exactly one LF. Plan full digests
omit only `full_digest`; semantic digests omit exactly the accepted six event
metadata fields. Run revision digests omit only `current_digest` and revision
2 links to the nonpersisted revision-1 planning digest. Duplicate/unknown
fields, invalid UUIDv7/logical IDs, non-UTC or impossible timestamp ordering,
unknown or contradictory codes/status/lifecycle combinations, invalid
references, malformed nested digests, inconsistent Plan references and Run
revisions, noncanonical bytes, and full/semantic/current digest projection
tampering are rejected with controlled codec errors.

| Golden | SHA-256 |
| --- | --- |
| `tests/fixtures/canonical/plan-actionable.json` | `199869844c10597b82fb3af8f990f31a9825e2f36a51b292ee4c891fda1bccc2` |
| `tests/fixtures/canonical/plan-noop.json` | `cc44e657e307e6c0e1d7f87ffdba183e2b5e6ebf63ba9de35652b5e638911520` |
| `tests/fixtures/canonical/run-awaiting-approval.json` | `09429d8de421e8e51e3f44c235779abf25d8b7f75d3121b9056cb9c5a4421551` |
| `tests/fixtures/canonical/run-noop.json` | `c030a7f2496db63cad2c3566691cd937a655f513ee6a00d25b79ab3f8ea1bbb4` |

### Local verification

Local evidence used macOS arm64, Python 3.14.2, uv 0.12.3, Ruff 0.16.8, mypy
2.3.1, and pytest 9.1.1.

| Exact command | Result | Elapsed |
| --- | --- | ---: |
| `uv run pytest -q tests/unit/reporting/test_planning_documents.py tests/unit/resource_types/kodi_smart_playlist/test_planning_codecs.py tests/unit/resource_types/kodi_smart_playlist/test_xml_planning.py tests/unit/application/test_plan_offline.py` | 96 passed | 0.45 s |
| `uv run pytest -q tests/scaffold/test_cli.py tests/scaffold/test_cli_planning.py` | 17 passed under the offline socket guard | 1.95 s |
| `uv run pytest -q` | 215 passed | 4.46 s |
| `uv run ruff check .` | All checks passed | 0.02 s |
| documented `ruff format --check` paths | 67 files already formatted | 0.02 s |
| `uv run mypy` | No issues in 67 source files | 0.11 s |
| pure/unit/architecture budget command from `docs/development.md` | 198 passed; 2.740 s measured, below 10 s | 2.79 s |
| complete-offline budget command from `docs/development.md` | 17 passed; 4.639 s aggregate, below 60 s | 1.95 s |
| `uv build` | Source distribution and wheel built | 0.36 s |
| documented wheel inspection and isolated no-dependency version/help smoke | Passed; 57 wheel entries | not budgeted |
| `python3 scripts/check_markdown.py` | 56 Markdown files passed | 0.20 s |
| `uv run python scripts/check_inventory_milestones.py` | 169 rows; digest matched | 0.04 s |
| `python3 scripts/check_shell_permissions.py --audit` | 146/146 shell rows covered; valid | 0.15 s |
| documented `tests/test-*.sh` transition loop excluding `test-helper.sh` | 9 scripts passed | 1,208 s |
| `git diff --check` | Passed | not budgeted |

Built package digests:

- wheel:
  `7df097ba1e2f05da6a47693646bb21f7a719d25c148fa4fa26b5c0bb6160d84f`;
- source distribution:
  `e34055ba5d9ef21a6f40746cab164a4fa6a3e01883e686f13c87c855e5f62537`.

The mandatory two-axis review found strict-codec gaps, incomplete closed-code
validation, malformed-content precondition aliasing, invalid timestamp
acceptance, and missing CLI access to the planning Run Report. The fixes
centralize Observation validation, validate actual RFC 3339 UTC values and
closed report vocabularies/references, bind malformed preconditions to a safe
content digest, and add `plan --document run`.

The blocking strictness correction adds closed playlist semantic vocabulary
and cardinality, validates rendering intent, rejects contradictory Assessment
states before Change construction, enforces supplied-observation temporal
windows, and validates every canonical Plan/Run identity, timestamp, digest,
reference, status, lifecycle, revision, and projection invariant. Adversarial
tests cover each boundary, including exact Plan binding for Run references.
The incremental two-axis review additionally found unchecked playlist order
cardinality, a Run/Plan identity invariant, and duplicated Resource Type code
vocabulary. Those findings were fixed with adversarial tests and shared
type-owned validation. Observation identity syntax is now validated at the
codec boundary while exact configured binding retains its stable application
diagnostic.

### Security, exclusions, and differences

Mutation guards prove `validate` and `plan` do not write files. All Python
tests, including CLI subprocesses, run under the offline socket guard. Output
contains normalized semantics and safe digests only; raw XML, secrets,
transport diagnostics, controller-local paths, and staging names are excluded.

SSH/SFTP, live Device access, durable Run workspace, apply, Verification,
rollback, recovery, Effect execution, authored `RemoteFile`, mutable globals,
and hard-coded Desired State policy remain out of scope. No Device was
accessed and no deployment occurred.

Differences from the accepted issue #58 contract: **none**.

Hosted evidence is the required
[Offline CI check attached to PR #69's final head](https://github.com/jbruns/tv/pull/69/checks).
The workflow checks out the pull request head SHA explicitly and asserts that
the checked-out SHA equals `SOURCE_SHA` before running Linux, macOS, and shell
jobs. This moving PR-head link deliberately prevents this contribution-only
record from claiming an earlier green commit as evidence for later
corrections; exact final run/job permalinks are recorded in the PR.

This contribution makes the pure slice ready for later application/execution
work; it does not satisfy the live pilot gates and does not exit M2.
