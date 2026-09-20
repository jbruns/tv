# M3 exit: offline execution and recovery

Date: 2026-09-20

Status: **Accepted candidate for merge through issue
[#87](https://github.com/jbruns/tv/issues/87).** This record seals the M3
implementation already merged through pull request
[#94](https://github.com/jbruns/tv/pull/94). It does not authorize Device
access, deployment, pilot mutation, shell freeze or retirement, ownership
transfer, an Effect change, or M4 work.

## Bound source

The verified merged source is `main` commit
`02eea6376aa40b35de1ac07ed75dfe4e9bec3bb3`, tree
`a758833e6395d7aab391df7342282617555aac6c`. The merge commit has the same
tree as reviewed M3.6 head
`c101036328d042bcf1bda81aeb597007b0408cc9`, so the hosted M3.6 artifacts
verify the exact bytes merged to `main`, not a synthetic pull-request merge
tree.

The clean local seal worktree was created directly from that merge commit on
branch `build/87-seal-m3`. It was clean before acceptance outputs were written
under ignored `.ci-evidence/`.

## Issue and pull-request chain

All implementation issues are closed. Issue #87 remains open until this
record's pull request merges.

| Issue | Pull request | Reviewed head | Merge commit |
| --- | --- | --- | --- |
| [#81](https://github.com/jbruns/tv/issues/81) | [#88](https://github.com/jbruns/tv/pull/88) | `e572bdda758f5b8bfa1a85ade7718e6acfaedb81` | `dc44a61e1093b461af09a824935e069fd4c63e45` |
| [#82](https://github.com/jbruns/tv/issues/82) | [#89](https://github.com/jbruns/tv/pull/89) | `16bd4f214133757022003a39d4e549dc60809302` | `4bab72067bf82ea0d05cf2b18958ad7b2613f2f8` |
| [#83](https://github.com/jbruns/tv/issues/83) | [#90](https://github.com/jbruns/tv/pull/90) | `409cc4751574813983935d70f455d6bef21fd7ce` | `4989429fbbdefb211450cd53234fd1f6429a0f2e` |
| #84 | [#91](https://github.com/jbruns/tv/pull/91) | `7fe0049df7654976c86eb1fb8ce653fee8fac2d1` | `13b7c843e0beb99f1606c677a5f2de42d95d301e` |
| #83 amendment | [#92](https://github.com/jbruns/tv/pull/92) | `b6e8c3bce51949f14e500fc020eac93a7668db56` | `55ac64eafbd41abcf8a78600848a866833beb486` |
| [#85](https://github.com/jbruns/tv/issues/85) | [#93](https://github.com/jbruns/tv/pull/93) | `d5bf700c608562f4fe81d43260bf9d6a265bceec` | `363e6a1de5ed5f58042063af19f5f7669c89de6e` |
| #81 amendment | [#96](https://github.com/jbruns/tv/pull/96) | `457f97a3ee7941c71b9f4d44964c752315fba8f3` | `92ba295a7fbc9da1dece1c6dc43a2c00e08c5a03` |
| #81 amendment | [#97](https://github.com/jbruns/tv/pull/97) | `f9c6598b98b5724e8336201b6323e52329e4fc8e` | `6994fa0ef9e5db01a2eaaec41eacac37695e40d6` |
| #83 amendment | [#95](https://github.com/jbruns/tv/pull/95) | `4f904113c68621b501c7e1fcf92854d236311cd7` | `2b14974c7f9bb1b9c09fb82dbf0b18db5c23b12c` |
| #81 amendment | [#98](https://github.com/jbruns/tv/pull/98) | `a7e395833019deb78fc6389ee3929a6cb7a6e215` | `aec87a6851e0a7e698d5fb7d2d561d4acb762d68` |
| #83 amendment | [#99](https://github.com/jbruns/tv/pull/99) | `a27125585bbfb29547139c68c9027d6294493596` | `d900d1b6f485f918f27c7fe7a9bd94904adce029` |
| #84 amendment | [#100](https://github.com/jbruns/tv/pull/100) | `451b2cc8e56c87ded38a6efe1ec2bbdbb75e78c1` | `ac2691052c56c76790eee594d94b397f03fc8492` |
| #81 amendment | [#101](https://github.com/jbruns/tv/pull/101) | `e665eab96f142982ce3ac7c14dba961375161a46` | `4ce876c5ce8b8a8688fab98d183bcf46a8417a33` |
| #83 amendment | [#102](https://github.com/jbruns/tv/pull/102) | `3e9632e3866c59da916ec90e7467f4f2d9d3306d` | `c10bad209d71122e77717530fa20b72d6d4072bb` |
| [#86](https://github.com/jbruns/tv/issues/86) | [#94](https://github.com/jbruns/tv/pull/94) | `c101036328d042bcf1bda81aeb597007b0408cc9` | `02eea6376aa40b35de1ac07ed75dfe4e9bec3bb3` |

Every listed pull request has successful Ubuntu 24.04 and macOS 15 Offline CI
checks. GitHub records no formal review objects on these pull requests; no
dedicated security-review workflow or check is configured. Security status is
therefore represented by the explicit offline, least-authority, no-socket,
redaction, hostile-bundle, package-boundary, and shell-ownership gates below,
all of which passed.

## Hosted Linux and macOS evidence

[Offline CI run
35499175972](https://github.com/jbruns/tv/actions/runs/35499175972)
checked out reviewed head
`c101036328d042bcf1bda81aeb597007b0408cc9`, verified that exact checkout,
and produced tree
`a758833e6395d7aab391df7342282617555aac6c`, which is the merged M3 tree.

| Job | Platform and tools | Budgets | Result |
| --- | --- | --- | --- |
| [Ubuntu job](https://github.com/jbruns/tv/actions/runs/35499175972/job/106047725430) | Ubuntu 24.04, Linux x86_64; Python 3.14.7; uv 0.12.3; Ruff 0.16.8; mypy 2.3.1; pytest 9.1.1 | Pure 7.478 s; remaining 31.526 s; complete 39.004 s | Passed |
| [macOS job](https://github.com/jbruns/tv/actions/runs/35499175972/job/106047725142) | macOS 15 arm64; Python 3.14.7; uv 0.12.3; Ruff 0.16.8; mypy 2.3.1; pytest 9.1.1 | Pure 5.475 s; remaining 25.612 s; complete 31.087 s | Passed |

Both jobs ran frozen synchronization, Ruff lint and exact formatting paths,
strict mypy, inventory validation, shell permission audit, the exact
non-overlapping selectors, package build and inspection, installed-wheel
smoke workflows, two byte-identical harness generations, and the independent
verifier. Their source-bound artifact names are:

- `offline-ci-Linux-X64-c101036328d042bcf1bda81aeb597007b0408cc9`
- `offline-ci-macOS-ARM64-c101036328d042bcf1bda81aeb597007b0408cc9`

The two platforms produced identical package, wheel-content, inventory,
shell-permission, lock, source-tree, and pilot-bundle bytes.

## Clean-checkout macOS acceptance

The complete acceptance was repeated from the isolated source worktree on
macOS 26.6.2 arm64 with Python 3.14.2, uv 0.12.3, Ruff 0.16.8, mypy 2.3.1,
and pytest 9.1.1.

| Exact gate | Result | Timing |
| --- | --- | ---: |
| `uv sync --frozen` | Passed; 29 locked packages installed | 0.40 s |
| `uv run ruff check .` | All checks passed | 0.42 s |
| Exact Ruff format command below | 154 files already formatted | 0.26 s |
| `uv run mypy` | No issues in 154 source files | 3.62 s |
| `uv run python scripts/check_inventory_milestones.py` | 169 valid rows | 0.04 s |
| `python3 scripts/check_shell_permissions.py --audit` | Valid; 146/146 shell rows covered | 0.15 s |
| Pure budget command below | 595 passed; 4.768 s | Under 10 s |
| Remaining budget command below | 236 passed; 26.740 s; 31.509 s cumulative | Under 60 s |
| `uv build` | Wheel and source distribution built | 0.28 s |
| Installed execution/recovery workflows | 32 passed | 10.28 s |
| Canonical suite, environment variant 1 | 272 passed | 2.24 s |
| Canonical suite, environment variant 2 | 272 passed | 2.30 s |
| Pilot harness rejection matrix | 28 passed | 4.84 s |
| Harness generation | Passed | 0.15 s |
| Independent bundle verification | Passed | 0.11 s |

The exact format command was:

```bash
uv run ruff format --check \
  src scripts/run_test_budget.py scripts/check_inventory_milestones.py \
  scripts/check_shell_permissions.py scripts/run_m3_pilot_harness.py \
  scripts/verify_m3_evidence_bundle.py \
  tests/scaffold tests/inventory tests/ci tests/unit tests/adapters \
  tests/contracts tests/integration tests/conftest.py tests/support
```

The exact selector commands were:

```bash
uv run python scripts/run_test_budget.py \
  --label pure-unit-architecture \
  --budget-seconds 10 \
  --timeout-seconds 300 \
  --result .ci-evidence/pure.json \
  -- \
  .venv/bin/python -m pytest -q \
  tests/scaffold/test_application.py \
  tests/scaffold/test_architecture.py tests/inventory tests/ci tests/unit \
  --ignore=tests/unit/execution/test_run_adapters.py
uv run python scripts/run_test_budget.py \
  --label complete-offline \
  --budget-seconds 60 \
  --timeout-seconds 300 \
  --include-result .ci-evidence/pure.json \
  --result .ci-evidence/offline.json \
  -- \
  .venv/bin/python -m pytest -q \
  tests/adapters tests/contracts \
  tests/scaffold/test_cli.py tests/scaffold/test_cli_planning.py \
  tests/scaffold/test_cli_execution.py tests/integration \
  tests/unit/execution/test_run_adapters.py
```

Selector-contract tests enumerate all Python `test_*.py` files and prove the
two sets are complete and disjoint. The pure selection excludes exactly
`tests/unit/execution/test_run_adapters.py`; the remaining selection includes
it exactly once. No legacy shell test was run.

## Determinism and installed package

The canonical reporting, execution-document, configuration, and playlist
Resource Type suites passed with identical expectations under:

- `PYTHONHASHSEED=991`, `TZ=Pacific/Honolulu`, `LC_ALL=C.UTF-8`;
- `PYTHONHASHSEED=37`, `TZ=Europe/Berlin`, `LC_ALL=C`.

The complete installed CLI workflow additionally compares exact output under
`PYTHONHASHSEED=1`, `TZ=UTC`, `LC_ALL=C` and
`PYTHONHASHSEED=991`, `TZ=Pacific/Honolulu`, `LC_ALL=C.UTF-8`.

The wheel was built from the clean checkout, installed into an environment
outside the checkout, and invoked from a separate working directory.
`--version`, `--help`, `validate`, and the expected rejected `apply` workflow
passed. The complete installed workflow test built and installed another
wheel away from the checkout and exercised observe, plan/apply, reconcile,
verify, report, recovery inspection, resume Verification, rollback, normal
finalization, abandonment finalization, cleanup uncertainty, real production
bootstrap with adapter seams, restart recovery, PTY/color variants, modeled
exit codes, UTF-8, broken pipes, and contamination redaction.

The installed wheel contained 105 entries, all beneath
`coreelec_reconciler/` or its distribution metadata. Tests, scripts,
workflows, Profiles, and inventory were absent. Required bootstrap,
production adapter, execution, recovery, observation, persistence, and
transport modules were present.

## Pilot bundle and rejection evidence

The harness command and independent verifier were:

```bash
uv run python scripts/run_m3_pilot_harness.py \
  --dry-run --output .ci-evidence/m3-pilot-dry-run
uv run python scripts/verify_m3_evidence_bundle.py \
  .ci-evidence/m3-pilot-dry-run
```

Three generations under the default environment and both varied environments
above were byte-identical. The manifest binds:

- source commit `02eea6376aa40b35de1ac07ed75dfe4e9bec3bb3`;
- source tree `a758833e6395d7aab391df7342282617555aac6c`;
- configuration SHA-256
  `bad8048786c36e7defaf4bea2cecd909927fe676bd18f1b4959ca7b6fea5140c`;
- lock SHA-256
  `0ab5562d697c8d88a3bbf3a3b47bc8b5a010b26f72bf0a3f23d9eac224464d8d`.

The independent verifier rejection matrix passed all 28 tests, including
missing or unexpected content, duplicate scenarios, stitching, source/tree,
configuration and lock mismatch, working-byte substitution, artifact and
bundle digest corruption, secret-bearing content, private paths, real Device
identity, raw exceptions, and semantic mutation.

## Digests

| Artifact or evidence | SHA-256 |
| --- | --- |
| Wheel | `a26c86cb1258c8ce3a9d0aea63b7e81830700b2fac0439764ad289659c05a7be` |
| Source distribution | `40cfd751ebe2b7c2fa1bf2bd885320cfd85a51dd1b0a07eacb095a93c6b21b62` |
| `uv.lock` | `0ab5562d697c8d88a3bbf3a3b47bc8b5a010b26f72bf0a3f23d9eac224464d8d` |
| Ownership ledger | `7df92594c5d86ec29142d5a758729c0e89a3be1004f66a2a8ab869dfeb1928bc` |
| Shell write-set map | `a3895b96b64fecfbeeb89dff5c4e19ab86f6209ff19b2b4a40d65764582246c2` |
| Sorted canonical-fixture digest set | `1bbfb18e2f0729f6f781a3410e0bada0ea698c3985b103e35b2d1db12c995015` |
| Pilot core-sequence fixture | `56fc34753047c961803b99c47834d874096338822bc254f7430e9696f54fb6dd` |
| Pilot `manifest.json` | `9c5b084d3d76c294c1afd9d8d15291080ccce2a25a2735f9b4f6a761eba86ac2` |
| Pilot `sequence.json` | `7393651d6b0d27cdbb623fb3d176ce031c2571267cad9676b3cd5eba62f0f1af` |
| Pilot `digests.json` and verified bundle digest | `21f191f35fcdbd3e1af2592afb9add68428c3caa0ccff77c98e4f76e39bac3c6` |
| Pilot `bundle.sha256` file | `2510fee59a21cd681e564bbca0b6a7ee4595732d1f6b2e247bdac77b6a3daa47` |

The hosted M3.6 bundle digest differs because its manifest binds the reviewed
head commit rather than the merge commit. Both hosted platforms produced
verified bundle digest
`dbb7b54ee859a180701b631a227671c7caefeedd8bfdf5d15e18eef8896bc14e`
with the same merged tree, configuration, lock, and sequence bytes.

## Inventory, documentation, and no-live boundary

Inventory validation recorded 169 rows: 153 `migrate`, 11 `outside`, and 5
`retire`. The shell audit covered all 146 shell inventory rows and retained
the two explicitly documented unknown targets. `SKIN-025` remains owned by
the shell implementation.

M3.6 made the cohesive documentation transition in
`docs/development.md`, `docs/implementation/offline-execution.md`, and
`docs/implementation/pilot-readiness.md`. This seal does not rewrite those
procedures. They remain authoritative for the exact selectors, production
composition, package boundary, dry-run harness, and no-live rules.

All acceptance used synthetic data and an early session-wide socket guard.
The harness accepts no endpoint or credential and records
`device_contact=false`, `secret_resolution=false`,
`live_use_authorized=false`, `ownership_transfer_authorized=false`, and
`skin_025_owner=shell`. No Device session, real secret resolution, deployment,
production restart, ownership transfer, shell freeze, pilot mutation, M4 issue
generation, or legacy shell suite occurred.

## Known failures and decision

Known acceptance failures: **none**.

There was no selector omission or duplication, budget overrun,
nondeterministic byte, package mismatch, verifier gap, secret/privacy
contamination, real Device access, or unresolved predecessor defect. No
acceptance fix or capability change was required. M3 is accepted for merge of
this record only, subject to the same passing hosted checks on its pull
request.

## Reproduction

From a genuinely clean checkout of
`02eea6376aa40b35de1ac07ed75dfe4e9bec3bb3`, run the commands in
`docs/development.md` exactly, including the two selector commands reproduced
above, the wheel inspection and external installation, and the pilot commands
above. Then run:

```bash
env PYTHONHASHSEED=991 TZ=Pacific/Honolulu LC_ALL=C.UTF-8 \
  uv run pytest -q \
  tests/unit/reporting tests/unit/execution/test_execution_documents.py \
  tests/unit/config tests/unit/resource_types/kodi_smart_playlist
env PYTHONHASHSEED=37 TZ=Europe/Berlin LC_ALL=C \
  uv run pytest -q \
  tests/unit/reporting tests/unit/execution/test_execution_documents.py \
  tests/unit/config tests/unit/resource_types/kodi_smart_playlist
uv run pytest -q tests/scaffold/test_cli_execution.py
uv run pytest -q tests/integration/test_m3_pilot_harness.py
python3 scripts/check_markdown.py
git diff --check
```

Compare the resulting source/tree/configuration/lock, package, fixture, and
bundle digests with this record. Do not run the legacy shell suite or contact
a Device.
