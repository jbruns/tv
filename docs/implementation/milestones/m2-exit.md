# M2 exit: pure configuration and planning

Date: 2026-09-19

Status: **Accepted candidate for merge through issue
[#59](https://github.com/jbruns/tv/issues/59) and pull request
[#70](https://github.com/jbruns/tv/pull/70).** This record seals the M2 source
already merged through pull requests
[#68](https://github.com/jbruns/tv/pull/68) and
[#69](https://github.com/jbruns/tv/pull/69). It authorizes M3 planning after
this record merges; it does not authorize Device access, mutation, or
deployment.

## Bound source and delivery

The verified source is merged `main` commit
`1d08fdeaadb3297f0c8b957386b085aa77e6027b`, tree
`a7e3cbae48a3f562365ec3d4b166d539b97a878e`.

| Capability | Issue and pull request | Reviewed source commit and tree | Merge commit and tree |
| --- | --- | --- | --- |
| Restricted authored configuration, composition, frozen domain, and codecs | [#57](https://github.com/jbruns/tv/issues/57), [#68](https://github.com/jbruns/tv/pull/68) | `f9d947e21756db72f9358c989dd3142ce5622981`, `e1b38f286529eeb996ddf1e7b747dbf1089c474a` | `fa6e8847da821618bd16fbbcacda3f01d37f627b`, `e1b38f286529eeb996ddf1e7b747dbf1089c474a` |
| Pure playlist assessment, Plan/Run documents, and offline CLI tracer | [#58](https://github.com/jbruns/tv/issues/58), [#69](https://github.com/jbruns/tv/pull/69) | `82708fb06f93dd90caabda597b17bf9c4a1fd434`, `a7e3cbae48a3f562365ec3d4b166d539b97a878e` | `1d08fdeaadb3297f0c8b957386b085aa77e6027b`, `a7e3cbae48a3f562365ec3d4b166d539b97a878e` |

Each reviewed head tree equals its merge tree. The M2 acceptance source is
therefore the exact reviewed implementation, not an unmerged branch or a
synthetic pull-request merge. Issue #59 changes only this exit record.

## Hosted Linux, macOS, and shell evidence

[Offline CI run 35438554432](https://github.com/jbruns/tv/actions/runs/35438554432)
checked out and verified source, checkout, and workflow SHA
`1d08fdeaadb3297f0c8b957386b085aa77e6027b`.

| Job | Platform and tools | Result and timing | Evidence |
| --- | --- | --- | --- |
| [Python offline (ubuntu-24.04)](https://github.com/jbruns/tv/actions/runs/35438554432/job/105885293508) | Linux x86_64; Python 3.14.7; uv 0.12.3; Ruff 0.16.8; mypy 2.3.1; pytest 9.1.1 | Passed. Pure/unit/architecture/CI: 5.274 s. Remaining offline: 3.771 s. Complete offline: 9.046 s. | Source-bound artifact `offline-ci-Linux-X64-1d08fdeaadb3297f0c8b957386b085aa77e6027b` |
| [Python offline (macos-15)](https://github.com/jbruns/tv/actions/runs/35438554432/job/105885293503) | macOS arm64; Python 3.14.7; uv 0.12.3; Ruff 0.16.8; mypy 2.3.1; pytest 9.1.1 | Passed. Pure/unit/architecture/CI: 5.223 s. Remaining offline: 5.163 s. Complete offline: 10.386 s. | Source-bound artifact `offline-ci-macOS-ARM64-1d08fdeaadb3297f0c8b957386b085aa77e6027b` |
| [Shell transition suite](https://github.com/jbruns/tv/actions/runs/35438554432/job/105885293413) | macOS arm64; frozen Python environment | Passed 9 scripts and 615 tests in 8 minutes 1 second, separately from Python budgets. | Hosted job log |

Both Python jobs ran the exact commands in `.github/workflows/offline-ci.yml`:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check \
  src scripts/run_test_budget.py scripts/check_inventory_milestones.py \
  scripts/check_shell_permissions.py \
  tests/scaffold tests/inventory tests/ci tests/unit \
  tests/conftest.py tests/support
uv run mypy
uv run python scripts/check_inventory_milestones.py
uv run python scripts/run_test_budget.py \
  --label pure-unit-architecture \
  --budget-seconds 10 \
  --timeout-seconds 300 \
  --result .ci-evidence/pure.json \
  -- \
  .venv/bin/python -m pytest -q \
  tests/scaffold/test_application.py \
  tests/scaffold/test_architecture.py tests/inventory tests/ci tests/unit
uv run python scripts/run_test_budget.py \
  --label complete-offline \
  --budget-seconds 60 \
  --timeout-seconds 300 \
  --include-result .ci-evidence/pure.json \
  --result .ci-evidence/offline.json \
  -- \
  .venv/bin/python -m pytest -q \
  tests/scaffold/test_cli.py tests/scaffold/test_cli_planning.py
uv build
```

Each job then ran the exact wheel-inspection Python block and isolated
`uv venv`, `uv pip install --no-deps`, installed `--version`, and installed
`--help` commands in `.github/workflows/offline-ci.yml`. The 10-second pure
and 60-second complete budgets passed without sharding, retry, rerun,
quarantine, ignored failure, or `xfail`.

The source-bound evidence-file SHA-256 values are:

| Evidence file | Linux x86_64 | macOS arm64 |
| --- | --- | --- |
| `environment.txt` | `11c8df49361ecf9f7dd7f27dcce1e090e09d4681af00e33fb3edb32a18087c7a` | `dc411730ae82ec9601d44c7de8ce6230eb1d9639e7d04c8986d09ba8639cb682` |
| `pure.json` | `3577b189cb9b457e924e71b6e1c598743b309cad0d72b1c9fedaa7f496923b96` | `f4455128952d0569a9eed9c8e3a465b3113793ddf59f7ddfdd14236c6fe0ed42` |
| `offline.json` | `e0ed0acdf5941651496f960c37b24446d9ed897b04cc56b0725b14597a5a2b87` | `177864e83549356e437e96f3aa0e425784862b2e6176ffdf3f876338f40e5283` |
| `inventory-ledger.txt` | `78a9a2fe268c6d4080637497c303f9623bc1399ff6d0e24920bb1f691f2dafe9` | same |
| `wheel-contents.txt` | `ab7b4a12feea2a7a48f427f167245a8a1bfbb7836c9811e81fc354dfb4056826` | same |
| `artifacts.sha256` | `b2981395e311dc581d8b45788c9206f86bbbef10aaf4d02c3b0c74a545c4b3c6` | same |

The predecessor source-bound runs also passed:

- [PR #68 run 35434647443](https://github.com/jbruns/tv/actions/runs/35434647443)
  for `f9d947e21756db72f9358c989dd3142ce5622981`;
- [PR #69 run 35438196274](https://github.com/jbruns/tv/actions/runs/35438196274)
  for `82708fb06f93dd90caabda597b17bf9c4a1fd434`.

Their downloaded environment records bind `source_sha` and `checked_out_sha`
to those heads. PR #68 produced identical Linux/macOS packages with wheel
`8da0e53ead050fad2b8bc46ed2e6f98a48b66dddfd661cc18f45024de0da10ad`
and source distribution
`421f2aa8131bfc21e710194f5f818068695e93bad34516a219de8e21e5fee7a7`.
PR #69 and merged `main` produced the final package digests below.

## Clean-checkout implementation acceptance

The complete acceptance was repeated from the clean isolated worktree at the
bound merged source before authoring this record. The platform was macOS arm64
with Python 3.14.2, uv 0.12.3, Ruff 0.16.8, mypy 2.3.1, and pytest 9.1.1.

| Exact command | Result | Timing |
| --- | --- | ---: |
| `uv sync --frozen` | Passed; 29 locked packages installed | 0.35 s |
| `uv run ruff check .` | All checks passed | 0.49 s |
| `uv run ruff format --check src scripts/run_test_budget.py scripts/check_inventory_milestones.py scripts/check_shell_permissions.py tests/scaffold tests/inventory tests/ci tests/unit tests/conftest.py tests/support` | 67 files already formatted | 0.02 s |
| `uv run mypy` | No issues in 67 source files | 3.15 s |
| `uv run python scripts/check_inventory_milestones.py` | 169 rows; 153 migrate, 11 outside, 5 retire; digest matched | 0.04 s |
| `python3 scripts/check_shell_permissions.py --audit` | 146/146 shell rows covered; valid; 2 explicitly unknown targets retained | 0.15 s |
| pure budget command printed below | 198 passed; 3.267 s measured | Under 10 s |
| complete-offline budget command printed below | 17 passed; 2.025 s selection; 5.291 s aggregate | Under 60 s |
| `uv run pytest -q tests/unit/config` | 37 passed | 0.22 s pytest; 0.35 s wall |
| `uv run pytest -q tests/unit/reporting/test_planning_documents.py tests/unit/resource_types/kodi_smart_playlist/test_planning_codecs.py tests/unit/resource_types/kodi_smart_playlist/test_xml_planning.py tests/unit/application/test_plan_offline.py` | 96 passed; canonical/golden/invariant/application gates | 0.48 s pytest; 0.62 s wall |
| `uv run pytest -q tests/scaffold/test_cli.py tests/scaffold/test_cli_planning.py` | 17 passed; installed-style validate/plan, Plan/Run framing, blocked exit | 1.92 s pytest; 2.03 s wall |
| `uv run pytest -q` | 215 passed | 4.44 s pytest; 4.59 s wall |
| `uv build` | Source distribution and wheel built | 0.45 s |
| wheel inspection Python block from `docs/development.md` | 57 wheel entries; exact package boundary and artifact digests passed | Not budgeted |
| `uv venv --python 3.14 --clear .wheel-venv` then `uv pip install --python .wheel-venv/bin/python --no-deps dist/*.whl` and installed `--version`/`--help` | Version `0.1.0`; help passed away from the checkout | Not budgeted |
| `uv pip install --python .wheel-venv/bin/python dist/*.whl` then the installed executable command pattern printed below | Create, semantic update, mode update, malformed repair, remove, no-op, absent no-op, blocked, and Run-document cases passed | Not budgeted |
| installed executable `validate --device-id ... --observations ...` against an invalid Profile | Exit 2; `schema.unknown-field`; empty stdout; no transport | Not budgeted |
| shell transition loop printed below | 9 scripts and 615 tests passed | 317.102 s |

The local budget commands were exactly:

```bash
uv run python scripts/run_test_budget.py \
  --label pure-unit-architecture \
  --budget-seconds 10 \
  --timeout-seconds 300 \
  --result .ci-evidence/pure.json \
  -- \
  .venv/bin/python -m pytest -q \
  tests/scaffold/test_application.py \
  tests/scaffold/test_architecture.py tests/inventory tests/ci tests/unit
uv run python scripts/run_test_budget.py \
  --label complete-offline \
  --budget-seconds 60 \
  --timeout-seconds 300 \
  --include-result .ci-evidence/pure.json \
  --result .ci-evidence/offline.json \
  -- \
  .venv/bin/python -m pytest -q \
  tests/scaffold/test_cli.py tests/scaffold/test_cli_planning.py
```

The local and hosted shell transition command was exactly:

```bash
set -euo pipefail
export PATH="$PWD/.venv/bin:$PATH"
for test_script in tests/test-*.sh; do
  case "$test_script" in
    *test-helper.sh) continue ;;
  esac
  bash "$test_script"
done
```

Installed-wheel planning used this command shape from an unrelated working
directory for each bounded synthetic Observation and both `plan` and `run`
documents:

```bash
(cd .wheel-smoke && \
  ../.wheel-venv/bin/coreelec-reconciler \
    --repository-root ../tests/fixtures/repository \
    plan living-room.ugoos-am6b-plus \
    --observations ../.ci-evidence/installed-observations.json \
    --document plan)
```

The desired-absence cases used a copied fixture repository whose three
playlist fragments retained only the accepted identity Intent and
`desired: absent`. The invalid installed validation used:

```bash
(cd .wheel-smoke && \
  ../.wheel-venv/bin/coreelec-reconciler \
    --repository-root ../.ci-evidence/invalid-installed-repository \
    validate \
    --device-id living-room.ugoos-am6b-plus \
    --observations ../.ci-evidence/invalid-installed-observations.json)
```

The budget wrapper used `time.monotonic_ns()`, ran every selector exactly
once, and did not fire its 300-second watchdog. Tests ran under the offline
socket guard. No Device or network-dependent test entered either budget.

## Exit-record candidate validation

After authoring this record, its uncommitted candidate was validated
separately from the bound implementation source:

| Exact command | Result | Timing |
| --- | --- | ---: |
| `python3 scripts/check_markdown.py` | 56 Markdown files passed | 0.19 s |
| `git diff --check` | Passed with no output | 0.01 s |

## Canonical, configuration, package, and repository digests

The resolved configuration canonical bytes are 1,818 bytes with SHA-256
`004d7e8c39e512fae99572a8e912d6eecd6b3fe0f9088584acae41f61da2208b`.

| Repository input | SHA-256 |
| --- | --- |
| `uv.lock` | `0ab5562d697c8d88a3bbf3a3b47bc8b5a010b26f72bf0a3f23d9eac224464d8d` |
| `inventory/ownership-ledger.json` | `7df92594c5d86ec29142d5a758729c0e89a3be1004f66a2a8ab869dfeb1928bc` |
| `inventory/shell-write-sets.json` | `a3895b96b64fecfbeeb89dff5c4e19ab86f6209ff19b2b4a40d65764582246c2` |
| Artifact catalog fixture | `6fb54bd9af401c37a6561c0f0fd50016afe1f60f963c8b133e1cfc4879ccc41b` |
| Device inventory fixture | `dc7254c419dad27b485c5eb49839b443ef004c036aa0758f449e011f9bd5d6e4` |
| Device Profile fixture | `fa7e88dbd4d9b9b6fb89d614185da3a815e43b274c92a25e3bb2ae5db7004414` |
| Platform Profile fixture | `80844bea73be67b1aaee46db2c6611681878a08c700885538e6c6e0f39648185` |
| Room Profile fixture | `69f5a358afc38a0284ea1ab45e789461d561b44f54974f90e1e6e536fcc2faff` |
| Secret-provider fixture | `d0e1c065c89bb1f45f3d7a123b5dac0e3912dfea2ce380a54b72ec79cdcf84c8` |
| Final wheel | `7df097ba1e2f05da6a47693646bb21f7a719d25c148fa4fa26b5c0bb6160d84f` |
| Final source distribution | `e34055ba5d9ef21a6f40746cab164a4fa6a3e01883e686f13c87c855e5f62537` |

The final Linux, hosted macOS, and local macOS package digests are identical.
The wheel contains only the 57 package and metadata entries allowed by the
packaging contract; no Profiles, inventory, catalogs, templates, tests,
fixtures, Device configuration, or fleet data are present.

## Canonical bytes and repeat determinism

Each no-op and actionable Plan/Run was generated five times with identical
input while varying `PYTHONHASHSEED`, timezone, and locale. Every repetition
was byte-identical to its committed golden. Canonical bytes have no trailing
newline; CLI framing adds exactly one LF.

| Golden | Bytes | SHA-256 |
| --- | ---: | --- |
| `plan-actionable.json` | 3,873 | `199869844c10597b82fb3af8f990f31a9825e2f36a51b292ee4c891fda1bccc2` |
| `plan-noop.json` | 2,413 | `cc44e657e307e6c0e1d7f87ffdba183e2b5e6ebf63ba9de35652b5e638911520` |
| `run-awaiting-approval.json` | 1,183 | `09429d8de421e8e51e3f44c235779abf25d8b7f75d3121b9056cb9c5a4421551` |
| `run-noop.json` | 1,182 | `c030a7f2496db63cad2c3566691cd937a655f513ee6a00d25b79ab3f8ea1bbb4` |

Embedded document digests also passed independent decoder and projection
checks:

- actionable Plan full/semantic:
  `433ae8a80060ebad20267fc3b3f4242f07346ebbc999357cd071043aee3a5289` /
  `f79abdda087530429a4e769aab379bef5a51b73f5aca8184210b035bd51ccb73`;
- no-op Plan full/semantic:
  `4e6bdf2aa6bf566e6dd945768bf86efb9e569d49256a482c7734aadd77daba30` /
  `9c602161a1cd48e28ad730aa52e89854baf913c73c862ee08ec0cd5a5684bfac`;
- awaiting-approval/no-op Run current:
  `4102952c147504d282e81033d76eb306075d9ebf85d0ef57dbc00e1e2cd7665f` /
  `ba7231950d284310f28303e4f94e35bff656f3c4396099b8ecf9fe1f8fd57c78`.

## Accepted behavior

| Observation and Desired State | Relation and Change | Plan / planning Run |
| --- | --- | --- |
| absent, desired present | divergent; `smart_playlist.create`; `playlist.absent` | `actionable` / `awaiting_approval` |
| semantic equivalent, including whitespace, CRLF, BOM, and attribute order | satisfied; no Change | `noop` / `noop` |
| semantic drift | divergent; `smart_playlist.update`; `playlist.semantic-drift` | `actionable` / `awaiting_approval` |
| mode-only drift | divergent; `smart_playlist.update`; `managed-file.mode-drift` | `actionable` / `awaiting_approval` |
| malformed safe regular XML | divergent; `smart_playlist.update`; `playlist.malformed-current` | `actionable` / `awaiting_approval` |
| present, desired absent | divergent; `smart_playlist.remove`; `playlist.desired-absent` | `actionable` / `awaiting_approval` |
| absent, desired absent | satisfied; no Change | `noop` / `noop` |
| unsafe non-regular state | unverifiable; typed blocker; no Change | `blocked` / `blocked` |
| observe-only divergence | visible but nonmutating; typed blocker; no Change | `blocked` / `blocked` |

Changes retain the logical State Address
`special://profile/playlists/video/NewShows.xsp`, exact evidence-digest
preconditions, normalized before/desired digests, verified rollback
capability, ordered impacts, and no Effects. Desired State is loaded only from
the resolved authored configuration.

## Inventory, ownership, and documentation

The ledger remains at exactly 169 unique accepted IDs: 153 migrate, 5 retire,
and 11 outside. No M2 actor transfer or closure occurred. `SKIN-025`
(`NewShows.xsp`) remains open for M4, shell-owned, with its audited shell write
set and Effects. Python may validate and plan only. Shell remains the sole
Device mutation actor.

M2 establishes:

- `docs/implementation/authored-configuration.md` as the supported restricted
  authored-input and composition reference;
- `docs/implementation/pure-playlist-planning.md` as the supported
  nonmutating playlist planning reference;
- `docs/development.md` commands for frozen validation, planning, quality,
  packaging, and the separate shell transition suite;
- this file as the authoritative replacement for the earlier
  contribution-only evidence.

Supported nonmutating workflows are `validate` with optional supplied
playlist Observation, and `plan` producing a canonical Plan or nonmutating
planning Run Report. Help and version are local metadata operations.

Device observation, transport, apply, reconcile mutation, Verification,
rollback, recovery, durable Run workspace, Effects, deployment, and live
Device workflows remain intentionally unavailable. Other operational command
variants retain explicit `not_implemented` outcomes. M3 must add execution
offline without weakening this pure boundary; M4 alone may perform the first
live `NewShows.xsp` pilot.

## Security and privacy review

- No Device was accessed; no deployment or Device mutation occurred.
- Offline socket guards covered Python tests and CLI subprocesses.
- Fixtures use only synthetic `.example.test` endpoints, example
  fingerprints, fixed UUIDv7/time values, placeholder digests, public
  playlist semantics, and environment-variable names rather than values.
- Secret references remain opaque provider/key pairs. No secret value is
  resolved by validation or planning.
- Canonical Plan/Run documents exclude raw XML, credentials, transport
  exception text, controller-local paths, and staging/helper names.
- Downloaded hosted evidence and committed fixtures/outputs were reviewed for
  credentials, private keys, real Device identifiers, private local paths,
  environment values, and sensitive payloads. Only normalized platform/tool
  facts, commands, timings, safe logical identifiers, and digests are retained
  here.
- Workflow permissions remain `contents: read`; third-party actions are
  commit-pinned.

## Exit decision

M2 satisfies the accepted issue #59 contract. The exact merged source passes
the complete configuration, composition, domain, playlist, Plan, Run, CLI,
quality, offline, timing, packaging, determinism, ledger, shell-map, shell
transition, documentation, and privacy acceptance.

Known failures: **none**.

Merge-blocking residual concerns: **none**.

This exit preserves the accepted pure/execution split. It does not implement
or authorize transport, Device mutation lifecycle, durable workspace,
shell-audit changes, deployment, live Device work, or any M3 feature.
