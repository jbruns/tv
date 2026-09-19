# M1 exit: production foundation

Date: 2026-09-18

Status: Accepted candidate for merge through issue
[#55](https://github.com/jbruns/tv/issues/55) and pull request
[#66](https://github.com/jbruns/tv/pull/66). This record does not authorize
deployment, Device access, or Device mutation.

## Bound source and delivery

The verified M1 source is merged `main` commit
`13ebf1a126a67de0f56fc408a5ba762e814cf2a9`, tree
`5b63881394f1cd9454ec1fb25390e86bcb4d6b8a`. It descends from the accepted M0
merge `907612571365f9b15cf5d756cc5962735746ca94`, tree
`7d73fd8c3c3ef09c991879b00adc6932a9d7a991`.

| Capability | Issue and pull request | Source commit and tree | Merge commit and tree |
| --- | --- | --- | --- |
| Python package and nonmutating application/CLI scaffold | [#52](https://github.com/jbruns/tv/issues/52), [#63](https://github.com/jbruns/tv/pull/63) | `863bbe8db6d0eaa72dbe2b061f95f4d04f97b8f7`, `0fa5c2ac40be6583fd79a64a0799ccde30a9b362` | `90c267b6832c2b5b5a6927803fc07ad23c8eee21`, `0fa5c2ac40be6583fd79a64a0799ccde30a9b362` |
| Offline CI, quality gates, budgets, and shell transition job | [#53](https://github.com/jbruns/tv/issues/53), [#64](https://github.com/jbruns/tv/pull/64) | `84a18a7758b6066e28993a3c7f48570bfc8a4aa7`, `7e27c7ddefe8822ba34d34cc95c7633ca1033fac` | `5177d83ff90dcfd2d543abe5700047ed51766260`, `7e27c7ddefe8822ba34d34cc95c7633ca1033fac` |
| Inventory ownership ledger and validators | [#54](https://github.com/jbruns/tv/issues/54), [#65](https://github.com/jbruns/tv/pull/65) | `809207ea699b310bf4f3552c589202545858672c`, `5b63881394f1cd9454ec1fb25390e86bcb4d6b8a` | `13ebf1a126a67de0f56fc408a5ba762e814cf2a9`, `5b63881394f1cd9454ec1fb25390e86bcb4d6b8a` |

The source trees equal their merge trees, proving that each reviewed PR head
is present unchanged in merged `main`. This exit record is delivered by
merge-commit-only PR [#66](https://github.com/jbruns/tv/pull/66), closing issue
#55. Its metadata commits add only this authoritative record; the verified
implementation source remains the commit and tree above.

## Hosted Linux and macOS evidence

[Offline CI run 35427030740](https://github.com/jbruns/tv/actions/runs/35427030740)
checked out and verified source, checkout, and workflow SHA
`13ebf1a126a67de0f56fc408a5ba762e814cf2a9`.

| Job | Platform and tools | Result and timing | Evidence |
| --- | --- | --- | --- |
| [Python offline (ubuntu-24.04)](https://github.com/jbruns/tv/actions/runs/35427030740/job/105854662578) | Linux x86_64; Python 3.14.7; uv 0.12.3; Ruff 0.16.8; mypy 2.3.1; pytest 9.1.1 | Passed. Pure/unit/architecture/CI helpers: 3.220 seconds, under 10. Complete offline total: 4.787 seconds, under 60. | [Source-bound artifact 10579276837](https://github.com/jbruns/tv/actions/runs/35427030740/artifacts/10579276837) |
| [Python offline (macos-15)](https://github.com/jbruns/tv/actions/runs/35427030740/job/105854662573) | macOS arm64; Python 3.14.7; uv 0.12.3; Ruff 0.16.8; mypy 2.3.1; pytest 9.1.1 | Passed. Pure/unit/architecture/CI helpers: 2.977 seconds, under 10. Complete offline total: 4.808 seconds, under 60. | [Source-bound artifact 10579501761](https://github.com/jbruns/tv/actions/runs/35427030740/artifacts/10579501761) |
| [Shell transition suite](https://github.com/jbruns/tv/actions/runs/35427030740/job/105854662505) | macOS arm64; frozen Python environment | Passed: 8 scripts and 610 tests; 7 minutes 46 seconds for the hosted job, separately from the Python budgets | Hosted job log |

Each Python job ran the frozen sync, lint, format, strict type check, ledger
validator, exact budget selectors, package build, wheel inspection, and
installed-wheel smoke. The evidence files contain the exact commands,
monotonic timings, source identity, platform, tool versions, wheel listing,
and artifact digests. CI links are supplemental; the values retained in this
record are the milestone authority.

The hosted Python jobs ran these exact commands on both platforms:

| Exact command | Linux x86_64 | macOS arm64 |
| --- | --- | --- |
| `uv sync --frozen` | Passed | Passed |
| `uv run ruff check .` | All checks passed | All checks passed |
| `uv run ruff format --check src scripts/run_test_budget.py scripts/check_inventory_milestones.py tests/scaffold tests/inventory tests/ci tests/conftest.py tests/support` | 26 files already formatted | 26 files already formatted |
| `uv run mypy` | No issues in 26 source files | No issues in 26 source files |
| `uv run python scripts/check_inventory_milestones.py` | 169 rows; 153 migrate, 11 outside, 5 retire; ledger digest matched | Same |
| `uv run python scripts/run_test_budget.py --label pure-unit-architecture --budget-seconds 10 --timeout-seconds 300 --result .ci-evidence/pure.json -- .venv/bin/python -m pytest -q tests/scaffold/test_application.py tests/scaffold/test_architecture.py tests/inventory tests/ci` | 30 passed; 3.220 s | 30 passed; 2.977 s |
| `uv run python scripts/run_test_budget.py --label complete-offline --budget-seconds 60 --timeout-seconds 300 --include-result .ci-evidence/pure.json --result .ci-evidence/offline.json -- .venv/bin/python -m pytest -q tests/scaffold/test_cli.py` | 14 passed; 1.567 s selection, 4.787 s total | 14 passed; 1.831 s selection, 4.808 s total |
| `uv build` | Built source distribution and wheel | Built source distribution and wheel |
| Wheel inspection and isolated `uv pip install --no-deps` smoke block in `.github/workflows/offline-ci.yml` | Passed; 23 wheel entries; `--version` and `--help` passed | Same |

The hosted shell job ran this exact transition command:

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

Its eight suites reported `46/46`, `92/92`, `65/65`, `8/8`, `63/63`,
`205/205`, `80/80`, and `51/51`: exactly 610 passing tests. The source-bound
job ran from 06:35:56Z through 06:43:42Z, including setup and teardown.

SHA-256 digests of the downloaded hosted evidence files were:

| Evidence file | Linux x86_64 | macOS arm64 |
| --- | --- | --- |
| `environment.txt` | `4a614b857fb7174414135bec6344b958010c8ba354774ad469fcf84b78cab7e0` | `5ecc77c9681270d3c751b5f6fb16d3039446cb52759d42336d74d9f269f6981c` |
| `pure.json` | `6464a8ffa7461c640e9cd80a563fcb01de7831864b0e36b2bdf2af6346ef8374` | `6c90951a71660999e3ec8e5d2456578448bc7d323f7a74d64f0b4f985771de45` |
| `offline.json` | `15a5c6473aadc15aee2cb2f9e7a6b8a040cef1f64a8961038b7e0fa80596f4ce` | `d74aad1c4a749713ab8243b985dfc5e5d8b5bb60eb93bb31b7ddbf9fb8dd2902` |
| `inventory-ledger.txt` | `2d58a6d6a920625841522220e74e54c65d58d82c6a08041e3de358dc4780ed4d` | `2d58a6d6a920625841522220e74e54c65d58d82c6a08041e3de358dc4780ed4d` |
| `wheel-contents.txt` | `005de7bdf50ff77e4255109145e9f845137da182b41a6c92bc7c8a9a12e8df28` | `005de7bdf50ff77e4255109145e9f845137da182b41a6c92bc7c8a9a12e8df28` |
| `artifacts.sha256` | `141da89499038c650106721ab831d25b69d009aefe708f1b3a3460a3ce990d86` | `141da89499038c650106721ab831d25b69d009aefe708f1b3a3460a3ce990d86` |

## Exact verification

The following commands were run from a clean worktree at the bound source on
macOS arm64 with Python 3.14.2 and uv 0.12.3. Ruff was 0.16.8, mypy 2.3.1,
and pytest 9.1.1.

| Exact command | Result | Elapsed |
| --- | --- | ---: |
| `uv sync --frozen` | Passed; 29 locked packages installed into a new environment | 0.55 s |
| `uv run ruff check .` | All checks passed | 0.03 s |
| `uv run ruff format --check src scripts/run_test_budget.py scripts/check_inventory_milestones.py tests/scaffold tests/inventory tests/ci tests/conftest.py tests/support` | 26 files already formatted | 0.02 s |
| `uv run mypy` | No issues in 26 source files | 1.10 s |
| `uv run python scripts/check_inventory_milestones.py` | 169 rows; 153 migrate, 11 outside, 5 retire; digest matched | 0.04 s |
| `uv run python scripts/run_test_budget.py --label pure-unit-architecture --budget-seconds 10 --timeout-seconds 300 --result .ci-evidence/pure.json -- .venv/bin/python -m pytest -q tests/scaffold/test_application.py tests/scaffold/test_architecture.py tests/inventory tests/ci` | Passed once; command exit 0; no timeout | 2.246 s |
| `uv run python scripts/run_test_budget.py --label complete-offline --budget-seconds 60 --timeout-seconds 300 --include-result .ci-evidence/pure.json --result .ci-evidence/offline.json -- .venv/bin/python -m pytest -q tests/scaffold/test_cli.py` | Passed once; command exit 0; 3.143 s aggregate | 0.897 s |
| `uv run pytest -q` | 44 passed | 2.61 s wall clock; pytest 2.49 s |
| `uv build` | Source distribution and wheel built | 0.26 s |
| Wheel inspection command documented in `docs/development.md` | Passed; one wheel, expected entry point, 23 package/metadata entries only | not budgeted |
| Isolated `uv pip install --no-deps`, `coreelec-reconciler --version`, and `--help` from `.wheel-smoke` | Passed; version `0.1.0` | not budgeted |
| `uv run coreelec-reconciler validate` | Passed with the ledger totals and digest below | not budgeted |
| `python3 scripts/check_markdown.py` | `Markdown validation passed for 50 file(s).` | 0.19 s |
| `git diff --check` | Passed with no output | not budgeted |
| Every `tests/test-*.sh` except `test-helper.sh`, run once in the documented loop | 8 scripts, 610 tests passed | 316.364 s |

The budget evidence uses `time.monotonic_ns()`. It ran each selector once,
with no sharding, retry, rerun, quarantine, ignored failure, or `xfail`, and
the 300-second watchdog did not fire.

## Package and lock evidence

| File | SHA-256 |
| --- | --- |
| `uv.lock` | `0ab5562d697c8d88a3bbf3a3b47bc8b5a010b26f72bf0a3f23d9eac224464d8d` |
| `dist/coreelec_reconciler-0.1.0-py3-none-any.whl` | `87051f67f391d7a1b42c2910b51a37cea0d82452bd15ab7730c57d3a321c6adb` |
| `dist/coreelec_reconciler-0.1.0.tar.gz` | `be93d91f4723d7dd89a8be3fc1b733a4718a1bc6b684840c908339b6ac96c15f` |

Linux, hosted macOS, and local macOS produced identical package digests. The
wheel contained:

```text
coreelec_reconciler/
coreelec_reconciler/__init__.py
coreelec_reconciler/application/
coreelec_reconciler/application/__init__.py
coreelec_reconciler/application/commands.py
coreelec_reconciler/application/outcomes.py
coreelec_reconciler/application/reconciler.py
coreelec_reconciler/bootstrap.py
coreelec_reconciler/cli/
coreelec_reconciler/cli/__init__.py
coreelec_reconciler/cli/main.py
coreelec_reconciler/cli/parser.py
coreelec_reconciler/domain/
coreelec_reconciler/domain/__init__.py
coreelec_reconciler/domain/identifiers.py
coreelec_reconciler/inventory/
coreelec_reconciler/inventory/__init__.py
coreelec_reconciler/inventory/ledger.py
coreelec_reconciler-0.1.0.dist-info/
coreelec_reconciler-0.1.0.dist-info/WHEEL
coreelec_reconciler-0.1.0.dist-info/entry_points.txt
coreelec_reconciler-0.1.0.dist-info/METADATA
coreelec_reconciler-0.1.0.dist-info/RECORD
```

No research, prototypes, Profiles, inventory data, templates, tests, Device
configuration, or fleet configuration entered the wheel. The console entry
point is `coreelec-reconciler = coreelec_reconciler.cli.main:main`.

## Inventory and ownership

The exact ledger bytes have SHA-256
`ace88aa43a05d19461f29a311c5eec0a736767cdcb690d38cd47b6766950792f`.
Validation found exactly 169 unique accepted IDs:

- roles: 128 Resources, 5 Guards, 5 Effects, 6 Guided Actions, 4 Run
  Infrastructure rows, and 21 unmanaged inventory facts;
- dispositions: 153 migrate, 5 retire, and 11 outside;
- milestones: M4 1, M5 45, M6 64, M7 26, and M8 33;
- current owner/executor: shell 146, external 10, operator 8, repository 4,
  and none 1;
- closure: 158 open and 11 outside;
- recovery: 169 `none`; ownership transfers: 0.

No inventory ID transfers or closes in M1. Shell remains the sole Device
mutation actor; the Python CLI remains nonmutating. For the 146 shell-actor
rows, `shell_write_set` and `permitted_effects` are explicitly `unaudited`.
The other 23 rows are `not-applicable`.

The accepted issue #46 refinement assigns the complete shell write-set and
Effect audit to issue #56 as a parallel pre-M4 gate rather than an M1-exit or
M2 blocker. This record does not invent audit results or grant shell
permission. It preserves that explicit unresolved inventory state and does no
work owned by #56.

## Documentation transition

M1 added and validated:

- `docs/development.md`, the supported frozen environment, quality, budget,
  package, installed-wheel, nonmutating CLI, and separate shell-transition
  commands;
- `docs/implementation/inventory-ownership-ledger.md`, the fail-closed ledger
  schema, role-aware closure, transfer rules, and per-issue obligations;
- README navigation to both documents and the Python package/inventory layout.

Operator documentation remains shell-current. No Python Device workflow,
authored configuration, Resource behavior, shell retirement, deployment, or
later-milestone documentation claim was added.

## Security and privacy review

- No Device was accessed and no deployment or Device mutation occurred.
- The tested Python selectors ran under the offline socket guard. No
  network-dependent or live-Device test is in either budget.
- The workflow grants only `contents: read`; its third-party actions are
  commit-pinned.
- The wheel contains code and required package metadata only.
- Ledger validation confirms no credential, host-secret, private path, or
  sensitive observed value is part of its schema or evidence.
- Retained evidence was reviewed for credentials, private local paths,
  environment dumps, and secret-bearing output. This record includes only
  source identity, normalized platform/tool versions, commands, results,
  timings, and digests.
- The shell transition tests use fixtures and dry-run/validation seams. No
  Device contact was made.

## Exit decision

M1 satisfies the accepted issue #55 contract: the merged Python foundation,
Linux/macOS offline CI, hard test budgets, package boundary, shell transition
coverage, inventory ledger, documentation, and security/privacy constraints
all pass from the exact merged source and tree bound above.

Known failures: **none**.

Merge-blocking residual concerns: **none**.

The intentionally unaudited shell write-set and Effect fields remain owned by
issue #56 and block the first live ownership transfer, not this accepted M1
exit. M1 authorizes M2 and the separately governed issue #47 lane; it does not
authorize Device access or deployment.
