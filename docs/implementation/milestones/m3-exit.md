# M3 exit: offline execution and recovery

Date: 2026-09-20

Status: **Accepted candidate for merge through issue
[#87](https://github.com/jbruns/tv/issues/87).** This record seals the M3
implementation merged through pull request
[#104](https://github.com/jbruns/tv/pull/104) under the owner-approved
trusted-appliance threat model. It does not authorize Device access,
deployment, pilot mutation, shell freeze or retirement, ownership transfer,
an Effect change, or M4 work.

## Threat model and evidence standard

M3 targets a trusted, single-user home streaming appliance. Acceptance
requires functional, reproducible evidence rather than enterprise or
adversarial audit evidence. The implementation protects against operator
mistakes, stale or interrupted Runs, malformed inputs, accidental path
escape, secret leakage, obvious injection, and normal failure modes.

Malicious concurrent processes on the CoreELEC Device, a compromised
root/SFTP server, and adversarial rewriting or resealing of evidence are out
of scope. The no-follow, parent-pinned compare-and-swap mutation fix from
PR #104 remains part of the accepted implementation.

The pilot harness is procedural and readiness evidence. It proves that a
deterministic bundle can be generated from and bound to source,
configuration, and lock bytes, and that ordinary contamination and malformed
bundles are rejected. It does **not** independently prove that its described
scenarios executed, or preserve semantic integrity against an adversary who
can rewrite and reseal the bundle. Functional execution evidence comes from
the production-bootstrap integration tests and installed-wheel workflows.
This separation is an accepted residual limitation, not a known acceptance
failure.

## Bound source

The verified merged M3 source is current `main` commit
`c2540ed5c9aa1b535e78fdef1ffebbb3d5da94e0`, tree
`ba9c633beaa4572ef8f53c67005983970f1b2e99`. This is the merge of PR #104
and includes its managed-mutation compare-and-swap fix.

The existing clean seal worktree on branch `build/87-seal-m3` merged that
commit without rewriting history. Acceptance ran at merge commit
`b3ca30c0d282591a1fe11ce8bb0bd137ada765e6`, tree
`1017e258f0899942bb1e562319aa2453517c9b41`. Relative to the bound M3
source, that tree contains only this exit record. Generated outputs remained
under ignored `.ci-evidence/`; the tracked worktree was clean before the
record was revised.

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
| #84 security amendment | [#104](https://github.com/jbruns/tv/pull/104) | `f95789f6377bc5404b85cc6dbf4e2c3d2b7d45cf` | `c2540ed5c9aa1b535e78fdef1ffebbb3d5da94e0` |

PR #105 was closed unmerged by the owner-approved threat-model decision and
is not part of the merge chain.

## Source-bound security review

The source-bound security review examined merged commit
`02eea6376aa40b35de1ac07ed75dfe4e9bec3bb3`, tree
`a758833e6395d7aab391df7342282617555aac6c`, using a read-only review of the
merged production mutation paths and the generated pilot evidence/verifier
contract. It identified two medium findings:

1. Managed-file mutation checked preconditions before later pathname-based
   SFTP mutation, leaving a TOCTOU window. PR #104 remediated this with a
   fixed server-side helper, no-follow parent pinning, exact expected-state
   validation, and atomic compare-and-swap mutation. PR #104's hosted run
   [35520422714](https://github.com/jbruns/tv/actions/runs/35520422714)
   passed on Ubuntu 24.04 and macOS 15.
2. The pilot harness and verifier compare deterministic scenario
   descriptions; they do not independently establish scenario execution.
   Under the revised threat model this is accepted as a documented residual.
   Production-bootstrap integration and installed-wheel workflows are the
   functional behavior evidence. PR #105 remains closed and unmerged.

## Functional acceptance

The exact M3.6 gates were repeated locally from the clean seal worktree on
macOS 26.6.2 arm64 with Python 3.14.2 and uv 0.12.3. No legacy shell test was
run.

| Exact gate | Result | Timing |
| --- | --- | ---: |
| `uv sync --frozen` | Passed; 29 locked packages checked | 0.01 s |
| `uv run ruff check .` | All checks passed | 0.05 s |
| Exact Ruff format command below | 156 files already formatted | 0.02 s |
| `uv run mypy` | No issues in 156 source files | 0.77 s |
| `uv run python scripts/check_inventory_milestones.py` | 169 valid rows | 0.04 s |
| `python3 scripts/check_shell_permissions.py --audit` | Valid; 146/146 shell rows covered | 0.14 s |
| Pure budget command below | 596 passed; 4.248 s | Under 10 s |
| Remaining budget command below | 258 passed, 12 platform skips; 31.151 s cumulative | Under 60 s |
| `uv build` | Wheel and source distribution built | 0.28 s |
| Installed production-bootstrap workflows | 32 passed | 10.70 s |
| Canonical suite, Honolulu environment | 272 passed | 1.52 s |
| Canonical suite, Berlin environment | 272 passed | 1.58 s |
| Pilot harness rejection matrix | 28 passed | 5.16 s |
| Each harness generation | Passed | 0.13 s |
| Each recursive byte comparison | Identical | 0.00 s |
| Independent bundle verification | Passed | 0.12 s |

The exact format command was:

```bash
uv run ruff format --check \
  src scripts/run_test_budget.py scripts/check_inventory_milestones.py \
  scripts/check_shell_permissions.py scripts/run_m3_pilot_harness.py \
  scripts/verify_m3_evidence_bundle.py \
  tests/scaffold tests/inventory tests/ci tests/unit tests/adapters \
  tests/contracts tests/integration tests/conftest.py tests/support
```

The accepted 10/60-second budget commands were unchanged:

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

Selector-contract tests enumerate every Python `test_*.py` file and prove the
two sets complete and disjoint. Linux-only managed-mutation helper contracts
account for the 12 expected local macOS skips.

The wheel was installed into a virtual environment under the session
workspace, outside the checkout, and invoked from a separate working
directory. Version, help, validation, and expected rejected apply workflows
passed. `tests/scaffold/test_cli_execution.py` independently built and
installed wheels outside the checkout and exercised production bootstrap,
observe, plan/apply, reconcile, verify, report, restart recovery, resume,
rollback, finalization, abandonment, cleanup uncertainty, PTY/color variants,
modeled exit codes, UTF-8, broken pipes, and contamination redaction.

## Hosted and varied-environment evidence

Ordinary hosted Linux/macOS CI plus local varied-environment determinism is
the accepted matrix. This record does not claim that the full varied hash,
timezone, and locale matrix ran on Linux.

PR #104 hosted source-bound CI passed for the code now merged to `main`:

- [Ubuntu 24.04](https://github.com/jbruns/tv/actions/runs/35520422714/job/106103423323):
  596 pure tests and 270 remaining tests; accepted budgets passed.
- [macOS 15](https://github.com/jbruns/tv/actions/runs/35520422714/job/106103423452):
  596 pure tests and 258 remaining tests with 12 Linux-only skips; accepted
  budgets passed.

PR #103's current head must also pass its ordinary Ubuntu 24.04 and macOS 15
Offline CI before merge. Those hosted checks repeat frozen sync, lint,
formatting, strict typing, inventory and shell audits, exact selectors and
budgets, package inspection and external installation, and two identical
harness generations.

Local canonical suites passed under:

- `PYTHONHASHSEED=991`, `TZ=Pacific/Honolulu`, `LC_ALL=C.UTF-8`;
- `PYTHONHASHSEED=37`, `TZ=Europe/Berlin`, `LC_ALL=C`.

## Pilot procedural bundle

The three exact generation commands were:

```bash
env PYTHONHASHSEED=0 TZ=UTC LC_ALL=C \
  uv run python scripts/run_m3_pilot_harness.py \
  --dry-run --output .ci-evidence/m3-pilot-default
env PYTHONHASHSEED=991 TZ=Pacific/Honolulu LC_ALL=C.UTF-8 \
  uv run python scripts/run_m3_pilot_harness.py \
  --dry-run --output .ci-evidence/m3-pilot-honolulu
env PYTHONHASHSEED=37 TZ=Europe/Berlin LC_ALL=C \
  uv run python scripts/run_m3_pilot_harness.py \
  --dry-run --output .ci-evidence/m3-pilot-berlin
```

The byte comparisons and independent verification were:

```bash
diff -r \
  .ci-evidence/m3-pilot-default \
  .ci-evidence/m3-pilot-honolulu
diff -r \
  .ci-evidence/m3-pilot-default \
  .ci-evidence/m3-pilot-berlin
uv run python scripts/verify_m3_evidence_bundle.py \
  .ci-evidence/m3-pilot-default
```

Both comparisons were empty. The verifier accepted bundle digest
`2e30f2d2b0586736012b8a7bcd378921b55b5aa1b56a39d71d3d1963c52a33b5`.
The manifest binds acceptance merge commit
`b3ca30c0d282591a1fe11ce8bb0bd137ada765e6`, tree
`1017e258f0899942bb1e562319aa2453517c9b41`, configuration SHA-256
`bad8048786c36e7defaf4bea2cecd909927fe676bd18f1b4959ca7b6fea5140c`,
and lock SHA-256
`0ab5562d697c8d88a3bbf3a3b47bc8b5a010b26f72bf0a3f23d9eac224464d8d`.

The 28-test rejection matrix covers missing and unexpected content,
duplicate scenarios, stitching, source/tree/configuration/lock mismatch,
working-byte substitution, artifact and bundle corruption, secret-bearing
content, private paths, real Device identity, raw exceptions, and mutation
without resealing. These are useful contamination and consistency checks,
not a claim of adversarial semantic integrity after resealing.

## Digests

| Artifact or evidence | SHA-256 |
| --- | --- |
| Wheel | `f49ea70319063f53e9a3b61aca5ce254021883a705b4aeb8a7ae4a85cc79c9dc` |
| Source distribution | `d48715df5c2e0bdd60c0a458d29872c4669df6aa759c67ba133cb91ccdf0ffe6` |
| `uv.lock` | `0ab5562d697c8d88a3bbf3a3b47bc8b5a010b26f72bf0a3f23d9eac224464d8d` |
| Ownership ledger | `7df92594c5d86ec29142d5a758729c0e89a3be1004f66a2a8ab869dfeb1928bc` |
| Shell write-set map | `a3895b96b64fecfbeeb89dff5c4e19ab86f6209ff19b2b4a40d65764582246c2` |
| Sorted canonical-fixture digest set | `1bbfb18e2f0729f6f781a3410e0bada0ea698c3985b103e35b2d1db12c995015` |
| Pilot core-sequence fixture | `56fc34753047c961803b99c47834d874096338822bc254f7430e9696f54fb6dd` |
| Pilot `manifest.json` | `9e872cdd5e52fd24a87d6ef4adc5f2b27cc66f392716c35571d0a72db2db2b51` |
| Pilot `sequence.json` | `7393651d6b0d27cdbb623fb3d176ce031c2571267cad9676b3cd5eba62f0f1af` |
| Pilot `digests.json` and verified bundle digest | `2e30f2d2b0586736012b8a7bcd378921b55b5aa1b56a39d71d3d1963c52a33b5` |
| Pilot `bundle.sha256` file | `fc2da175ff2ae810b7f6c3d84f26b8b889d51d26a3ac2e75208e66fbd9ed9bae` |

The package digests changed from the earlier seal because PR #104 added the
managed-mutation helper and its production integration. Configuration, lock,
ownership, shell-map, canonical fixtures, and scenario-description bytes did
not change.

## Inventory, documentation, and no-live boundary

Inventory validation recorded 169 rows: 153 `migrate`, 11 `outside`, and 5
`retire`. The shell audit covered all 146 shell inventory rows and retained
the two explicitly documented unknown targets. `SKIN-025` remains owned by
the shell implementation.

All acceptance used synthetic data and the offline socket guard. The harness
accepts no endpoint or credential and records `device_contact=false`,
`secret_resolution=false`, `live_use_authorized=false`,
`ownership_transfer_authorized=false`, and `skin_025_owner=shell`. No Device
session, real secret resolution, deployment, production restart, ownership
transfer, shell freeze, pilot mutation, M4 issue generation, or legacy shell
suite occurred.

## Decision and residual risks

Known ordinary functional acceptance failures: **none**.

Accepted residual risks and limitations:

- The description-only harness proves deterministic procedural packaging and
  contamination rejection, not that scenarios executed.
- A party able to rewrite and reseal evidence can change its semantics.
- Malicious concurrent Device processes and compromised root/SFTP servers are
  outside the trusted-appliance threat model.
- Unsupported Linux kernel or Profile-filesystem compare-and-swap primitives
  fail capability negotiation closed; they were not exercised against a live
  Device during M3.

M3 is accepted for merge of this record only, subject to passing PR #103
Ubuntu and macOS Offline CI. The accepted residuals above do not weaken any
ordinary functional gate or the 10/60-second budgets.

## Reproduction

From a genuinely clean checkout containing merged commit
`c2540ed5c9aa1b535e78fdef1ffebbb3d5da94e0`, run the commands in
`docs/development.md`, the exact selectors above, the installed-wheel
workflow, the two canonical environment variants, the three harness commands
and byte comparisons, and:

```bash
uv run pytest -q tests/scaffold/test_cli_execution.py
uv run pytest -q tests/integration/test_m3_pilot_harness.py
python3 scripts/check_markdown.py
git diff --check
```

Compare source/tree, package, fixture, configuration, lock, and procedural
bundle digests with this record. Do not run the legacy shell suite or contact
a Device.
