# M3 build-issue graph and handoff

## Status

Accepted decision record for generating the CoreELEC Reconciler M3 build
backlog.

This record specifies the complete dependency-ordered route from the accepted
M2 source to an accepted offline M3. It generates no build issue, implements
no production capability, contacts no Device, and authorizes no ownership
transfer.

## Destination

M3 ends with a production-quality offline managed-file execution and recovery
system that:

- preserves the public `Reconciler.execute(command)` interface;
- places one private deep execution module behind it with `start`, `inspect`,
  and `recover` operations;
- persists canonical immutable Run revisions rather than exposing a public
  event-stream interface;
- supports least-authority Device sessions, durable local and remote Run
  Infrastructure, atomic managed-file mutation, independent Verification,
  verified rollback, and computed recovery;
- exposes deterministic installed-CLI journeys with canonical JSON-only
  stdout and human stderr;
- passes the complete accepted issue-42/43 offline matrix on Linux and macOS;
- produces a deterministic pilot-harness dry run and independently verified
  evidence bundle;
- still leaves `SKIN-025` shell-owned and performs no live Device mutation.

## Controlling records

Generated build issues must cite:

- `docs/architecture/coreelec-reconciler.md`;
- `CONTEXT.md`;
- `docs/research/2026-09-18-core-module-resource-type-contracts.md`;
- `docs/research/2026-09-18-first-managed-file-test-contract.md`;
- `docs/research/2026-09-18-run-workspace-recovery-effect-contracts.md`;
- `docs/research/2026-09-18-disposable-pilot-acceptance-procedure.md`;
- `docs/research/2026-09-18-build-issue-decomposition-handoff.md`;
- `docs/research/2026-09-18-implementation-milestones-documentation-transitions.md`;
- `docs/research/2026-09-19-m3-obligation-audit.md`;
- the accepted M3 execution-spine and operator-journey prototype branches;
- `docs/implementation/milestones/m2-exit.md`.

The accepted contracts remain fixed. A generated issue may not weaken them to
make implementation or timing easier. Concrete contradiction reopens the
owning decision or predecessor; it does not become an undocumented local
exception.

## Graph

```text
M3.1 Persist canonical execution Runs and local Run Infrastructure
  |
  v
M3.2 Acquire Device authority and prepare managed files
  |
  v
M3.3 Execute, verify, and recover managed files with fake Adapters
  |\
  | \
  v  v
M3.4 Implement production SSH/SFTP Adapters
M3.5 Implement installed execution and recovery CLI journeys
  \  /
   vv
M3.6 Integrate M3 offline and build the pilot harness
  |
  v
M3.7 Seal the offline execution and recovery milestone
```

There are six implementation issues and one seal issue.

The graph is serial through the complete fake-Device lifecycle. Only M3.4 and
M3.5 may run in parallel, after M3.3 merges, because their owned paths are
disjoint. M3.6 is the sole integration owner for shared bootstrap, packaging,
workflow, selector, and cohesive documentation surfaces.

## Cross-issue rules

### Delivery

Every generated issue follows the accepted build handoff:

- branch `build/<issue-number>-<slug>`;
- worktree `.worktrees/<issue-number>-<slug>`;
- branch starts from merged current `main` after every blocker closes;
- one merge-commit pull request with `Closes #<issue-number>`;
- no stacked unmerged build branches;
- no production deployment;
- issue closes only after merge and source-bound evidence.

Only M3.1 receives `ready-for-agent` when the backlog is generated. Every
later issue remains blocked and unlabeled until its dependencies are merged,
its references resolve on `main`, its owned paths are disjoint from another
ready issue, and no new decision changes its interface or write set.

### Device and ownership

Every M3 issue declares:

```text
Device access: none
Declared Device write set: none
Inventory transfer: none
```

`SKIN-025` remains shell-owned through the M3 exit. Production Adapters,
installed commands, and the pilot harness may be implemented and tested
offline, but no command may contact the pilot or any real Device during M3
acceptance.

### Evidence

Each implementation issue:

- runs its targeted contract tests;
- runs the unchanged M2 regression selectors relevant to touched code;
- runs Ruff, formatting, strict mypy, inventory validation, shell-permission
  audit, Markdown validation when documentation changes, and `git diff
  --check`;
- records exact commands, source commit/tree, results, timing, and produced
  fixture/golden digests in its pull request or committed evidence record.

M3.6 runs the complete named issue-42/43 offline matrix exactly once, the
installed-wheel workflows, deterministic harness dry run, independent bundle
verification, packaging checks, and the accepted 10/60-second budgets.

M3.7 repeats the complete clean-checkout acceptance on Linux x86_64 and macOS
arm64, binds hosted artifacts and digests to merged source, and commits the
authoritative M3 exit record.

### Canonical schema ownership

M3.1 owns the complete closed persisted vocabulary required by M3, including:

- execution and recovery Run statuses;
- approvals and failures;
- Resource mutation, Verification, rollback, and post-Effect outcomes;
- local/remote authority and cleanup evidence;
- recovery-required facts and allowed-action representations;
- complete revision-chain and attachment references;
- terminality and active-index intents.

Later issues populate these values but do not casually extend the persisted
schema. A missing value is a specification defect: reopen M3.1 or approve an
explicit amendment before changing another issue's schema.

### Documentation

Reference material moves with the capability that makes it true. M3.6 then
publishes the cohesive offline operator/development procedure and explicitly
states that Python has no live ownership. M3.7 records accepted evidence; it
does not perform a delayed documentation rewrite.

## M3.1 — Persist canonical execution Runs and local Run Infrastructure

### Outcome

Represent, persist, reload, and independently validate every canonical
execution/recovery Run state required by M3 without contacting a Device.

### Scope

- Expand the closed domain vocabulary from planning-only Runs to the complete
  accepted M3 execution/recovery lifecycle.
- Build canonical revision values, builders, decoders, digests, and revision
  chain verification for all accepted statuses and evidence combinations.
- Preserve existing M2 Plan and planning Run bytes exactly unless an explicit
  schema migration is required and approved.
- Implement filesystem `RunStore` with:
  - opaque workspace IDs;
  - Device and Run revision leases;
  - complete verified chains;
  - verified attachment write/read;
  - derived fail-closed active Device index and scan/rebuild;
  - compare-and-append with one bounded unchanged-CAS acknowledgement
    reconciliation;
  - explicit finalize/seal;
  - terminal/index intent separation.
- Implement private production and scripted `LocalDurability` Adapters for
  private write, file full-sync, atomic replacement, directory sync, and
  acknowledgement loss.
- Implement deterministic `RuntimeValues` and finite test queues for UTC
  instants, UUIDv7 values, and ownership tokens.
- Add the independent Run Report invariant checker and one negative fixture
  per accepted invariant.

### Out of scope

- Device sessions, remote markers, path resolution, Resource observation,
  managed mutation, CLI presentation, pilot harness, or live work.
- A public event store or event-stream interface.
- Effects handlers, retry, scheduler, heartbeat, or pruning.

### Dependencies

- M2 accepted through `docs/implementation/milestones/m2-exit.md`.

### Owned paths

- `src/coreelec_reconciler/domain/planning.py`
- `src/coreelec_reconciler/domain/execution.py`
- `src/coreelec_reconciler/reporting/planning_documents.py`
- `src/coreelec_reconciler/reporting/execution_documents.py`
- `src/coreelec_reconciler/execution/__init__.py`
- `src/coreelec_reconciler/execution/run_store.py`
- `src/coreelec_reconciler/execution/local_durability.py`
- `src/coreelec_reconciler/execution/runtime.py`
- `tests/fixtures/canonical/execution-*`
- `tests/fixtures/canonical/recovery-*`
- `tests/unit/reporting/`
- `tests/unit/execution/test_run_store.py`
- `tests/unit/execution/test_execution_documents.py`
- `tests/unit/execution/test_run_invariants.py`
- `docs/implementation/run-evidence.md`

The issue owns no CLI, transport, production bootstrap, workflow, dependency
manifest, or pilot-harness path.

### Acceptance

At minimum:

```bash
uv run pytest -q \
  tests/unit/reporting \
  tests/unit/execution/test_run_store.py \
  tests/unit/execution/test_execution_documents.py \
  tests/unit/execution/test_run_invariants.py
uv run pytest -q \
  tests/unit/planning \
  tests/unit/application/test_plan_offline.py \
  tests/scaffold/test_cli_planning.py
```

Required evidence includes all accepted status/revision/attachment/index
variants, deterministic canonical bytes and digests, local durability faults,
CAS acknowledgement reconciliation, corruption rejection, terminality/index
ordering, and unchanged M2 goldens.

### Documentation and security

Document canonical Run evidence, workspace opacity, retention, and the
difference between Device-state truth and cleanup state. No private path,
ownership token, secret value, raw attachment, or unsafe exception text may
enter canonical documents or diagnostics.

## M3.2 — Acquire Device authority and prepare managed files

### Outcome

Reach a durable, inspectable, fully prepared managed-file Run without
performing a managed-address mutation.

### Scope

- Retain validated endpoint, SSH username, pinned host-key reference, secret
  reference, and Profile-root capability in a typed resolved Device value.
- Resolve secret references only at the production composition seam; secret
  values never enter domain values or evidence.
- Add typed least-authority Device/session and managed-file capability
  interfaces.
- Add typed `special://profile/` resolution that preserves the logical State
  Address and produces a normalized safe Device path while rejecting unknown
  schemes, missing capability, traversal, and root escape.
- Build the stateful case-sensitive POSIX fake Device and independent
  read-only inspector with no call history.
- Implement local authority acquisition, token-before-acquire, active-index
  behavior, durable remote ownership acquisition/CAS/checkpoint/release/
  quarantine semantics against fake Adapters.
- Implement stable recovery inspection and pure total allowed-action
  computation.
- Implement fresh typed lstat/read observation, regular-file safety, read
  bounds, capability discovery, complete before-state capture, preparation
  manifest, rollback attachment, and final stale-precondition recheck.
- Expose read-only inspect/report facts without controller-local paths,
  tokens, or temporary remote names.

### Out of scope

- Stage write, chmod, replace, remove, rollback restoration, or any managed
  mutation.
- Production Paramiko Adapters.
- Installed CLI rendering.
- Effects, retries, takeover, forward recovery, or quarantine clearing.

### Dependencies

- M3.1 merged and its schema frozen.

### Owned paths

- `src/coreelec_reconciler/domain/configuration.py`
- `src/coreelec_reconciler/config/load.py`
- `src/coreelec_reconciler/config/device.py`
- `src/coreelec_reconciler/transports/__init__.py`
- `src/coreelec_reconciler/transports/interfaces.py`
- `src/coreelec_reconciler/execution/authority.py`
- `src/coreelec_reconciler/execution/recovery.py`
- `src/coreelec_reconciler/resource_types/managed_file/__init__.py`
- `src/coreelec_reconciler/resource_types/managed_file/paths.py`
- `src/coreelec_reconciler/resource_types/managed_file/observation.py`
- `src/coreelec_reconciler/resource_types/managed_file/preparation.py`
- `tests/fakes/device.py`
- `tests/fakes/run_infrastructure.py`
- `tests/unit/config/test_device_resolution.py`
- `tests/unit/execution/test_authority.py`
- `tests/unit/execution/test_recovery_actions.py`
- `tests/unit/resource_types/managed_file/test_paths.py`
- `tests/unit/resource_types/managed_file/test_observation.py`
- `tests/unit/resource_types/managed_file/test_preparation.py`
- `docs/implementation/recovery.md`

M3.2 may consume but not extend M3.1 canonical schema files.

### Acceptance

At minimum:

```bash
uv run pytest -q \
  tests/unit/config/test_device_resolution.py \
  tests/unit/execution/test_authority.py \
  tests/unit/execution/test_recovery_actions.py \
  tests/unit/resource_types/managed_file
uv run pytest -q tests/unit/config tests/unit/planning
```

Required evidence includes token crash points, active-index over-report/rebuild,
remote marker absence/races/foreign/malformed/symlink/nonregular states,
durability failures, every identity/phase/generation CAS mismatch, stable
inspection, allowed-action variants, path safety, unreadable/unsafe state,
complete preparation, attachment corruption, and stale preconditions.

### Documentation and security

Document authority scopes, inspect/recover semantics, safe path resolution,
and why elapsed time or process absence never authorizes takeover. Fixtures use
synthetic Device identities and secret references only.

## M3.3 — Execute, verify, and recover managed files with fake Adapters

### Outcome

Complete the full managed-file execution and recovery lifecycle through
`Reconciler.execute` using stateful fake Adapters.

### Scope

- Implement the private deep execution module with:
  - `start(approved_plan)`;
  - `inspect(run_id)`;
  - `recover(run_id, allowed_action)`.
- Preserve the public overloaded `Reconciler.execute(command)` interface.
- Replace the temporary callback-only `ApplicationReconciler` wiring with
  explicit injected execution dependencies.
- Add private typed Resource Type execution erasure while keeping playlist
  Intent, Observation, Change, and Verification values inside the Resource
  module.
- Implement same-directory stage write, chmod, unconditional atomic
  replace-over-existing, remove, cleanup, and restoration against fake
  managed-file capabilities.
- Persist operation-specific intent and an immediate marker checkpoint before
  every primitive.
- Persist ordered applied/definitely-not-applied/ambiguous traces.
- Freshly observe and independently Verify after every possible mutation.
- Implement conditional verified rollback, rollback ambiguity, no-forward-work
  resume Verification, normal finalization, approved/reasoned abandonment,
  quarantine, and terminal-truth-before-cleanup.
- Implement all application workflows through the public seam:
  `observe`, `plan`, `apply`, `reconcile`, `verify`, `recover`, and `report`;
  preserve typed `not_implemented` for `inventory` and `action`; preserve
  `provision` as a CLI alias only.
- Add deterministic typed progress events and failing-sink invariance.
- Complete the fake-Device fault/interleaving and interruption matrices.

### Out of scope

- Paramiko, production SSH/SFTP, installed CLI presentation, workflow files,
  pilot harness, live Device work, production Effects, retries, or pruning.

### Dependencies

- M3.2 merged.

### Owned paths

- `src/coreelec_reconciler/application/commands.py`
- `src/coreelec_reconciler/application/outcomes.py`
- `src/coreelec_reconciler/application/reconciler.py`
- `src/coreelec_reconciler/execution/engine.py`
- `src/coreelec_reconciler/execution/progress.py`
- `src/coreelec_reconciler/execution/managed_file.py`
- `src/coreelec_reconciler/resource_types/descriptor.py`
- `src/coreelec_reconciler/resource_types/kodi_smart_playlist/execution.py`
- `tests/fakes/runtime.py`
- `tests/fakes/progress.py`
- `tests/unit/application/test_execution_workflows.py`
- `tests/unit/execution/test_managed_file_lifecycle.py`
- `tests/unit/execution/test_fault_matrix.py`
- `tests/unit/execution/test_interruption_recovery.py`
- `tests/unit/execution/test_progress.py`
- `tests/unit/resource_types/kodi_smart_playlist/test_execution.py`
- `docs/implementation/managed-file-execution.md`

It owns no `bootstrap.py`, `cli/`, production Adapter, dependency manifest,
workflow, or pilot-harness path.

### Acceptance

At minimum:

```bash
uv run pytest -q \
  tests/unit/application/test_execution_workflows.py \
  tests/unit/execution/test_managed_file_lifecycle.py \
  tests/unit/execution/test_fault_matrix.py \
  tests/unit/execution/test_interruption_recovery.py \
  tests/unit/execution/test_progress.py \
  tests/unit/resource_types/kodi_smart_playlist/test_execution.py
uv run pytest -q tests/unit tests/scaffold/test_application.py
```

Required scenarios include create, semantic update, mode-only update, malformed
repair, remove, no-op, observe-only, stale Plan, residual race, every
per-primitive lost-ack twin, ordered partial traces, interruption at every
durable boundary, successful and ambiguous rollback, third-party state,
cleanup failure, corrupt evidence, and every allowed recovery action.

### Documentation and security

Document the deep execution module, public application seam, fresh
Verification rule, conditional rollback, and no-forward-recovery rule.
Progress failure may add a sanitized presentation diagnostic only; it cannot
change canonical bytes, Device scheduling, or final Device state.

## M3.4 — Implement production SSH/SFTP Adapters

### Outcome

Make every M3 Device/session and managed-file capability available through
production Paramiko-based Adapters that pass the same public contracts as the
fakes, without wiring them into the production bootstrap.

### Scope

- Implement pinned-host-key Paramiko session construction and typed secret
  resolution.
- Preserve stdout/stderr bytes and typed timeout/disconnect/command outcomes.
- Close command channels, SFTP sessions, and SSH clients deterministically.
- Implement typed lstat/read with no symlink following and bounded complete
  reads.
- Implement staged write, chmod, `SFTPClient.posix_rename`, remove, and
  restoration receipts with applied/definitely-not-applied/ambiguous
  semantics.
- Implement remote Run Infrastructure durability, ownership, marker CAS,
  immediate checkpoint reread, release, quarantine, and exact manifest-owned
  cleanup through fixed repository-owned operations/helpers.
- Add scripted production-Adapter fault tests and shared fake/production
  contract suites.
- Prove no ordinary rename or remove-plus-rename fallback exists.

### Out of scope

- `bootstrap.py`, CLI, application workflow changes, canonical schema changes,
  workflow files, live Device access, persistent helpers, Effects, retries,
  or pilot evidence.

### Dependencies

- M3.3 merged.

### Owned paths

- `src/coreelec_reconciler/adapters/__init__.py`
- `src/coreelec_reconciler/adapters/secrets.py`
- `src/coreelec_reconciler/adapters/paramiko_session.py`
- `src/coreelec_reconciler/adapters/paramiko_managed_file.py`
- `src/coreelec_reconciler/adapters/remote_run_ownership.py`
- `src/coreelec_reconciler/adapters/remote_helpers.py`
- `tests/adapters/`
- `tests/contracts/test_device_session_contract.py`
- `tests/contracts/test_managed_file_adapter_contract.py`
- `tests/contracts/test_remote_ownership_contract.py`
- `docs/implementation/device-adapters.md`

### Parallelism

May run in parallel with M3.5 after M3.3 merges. It must not edit M3.5 or M3.6
owned paths.

### Acceptance

At minimum:

```bash
uv run pytest -q tests/adapters tests/contracts
uv run pytest -q tests/unit/execution tests/unit/resource_types/managed_file
```

Required evidence covers host-key rejection, secret redaction, close behavior,
byte preservation, typed failures, incomplete reads, atomic replacement over
absent/existing destinations, extension absence, every mutation ambiguity
twin, remote durability unsupported, marker races/CAS failures, cleanup
ambiguity, and shared contract parity.

### Documentation and security

Document supported production capabilities and fail-closed unsupported cases.
No credentials, secret values, raw transport exceptions, private controller
paths, or temporary Device names may enter reports, progress, test artifacts,
or retained evidence.

## M3.5 — Implement installed execution and recovery CLI journeys

### Outcome

Present every accepted M3 workflow through the installed CLI without owning
production transport construction.

### Scope

- Refine parser arguments for saved Plan apply, reconcile approvals, verify,
  report, inspect, resume Verification, rollback, normal finalization, and
  abandonment.
- Preserve `provision` as syntax sugar for `reconcile`.
- Emit exactly one canonical document plus one framing LF to stdout for every
  modeled outcome that has a document, including modeled non-zero outcomes.
- Keep stdout free of progress, summaries, warnings, prompts, logs, terminal
  escapes, and bootstrap noise.
- Emit chronological progress, concise status, and visually prominent
  copyable next-safe commands to stderr.
- Implement accepted exit codes 0/2/3/4/5, with 1 reserved for defects.
- Without sufficient approval, make `reconcile` stop at
  `awaiting_approval`, emit the planning Run, and print a copyable
  `apply PLAN_ID --approve ...` command.
- On recovery-required outcomes, point first to read-only
  `recover RUN_ID inspect`.
- Print only computed legal recovery commands after inspection.
- Require dedicated `recover.abandon` approval and a non-empty reason for
  abandonment; no interactive prompt or generic yes flag.
- Implement `--quiet`, non-TTY/`NO_COLOR`/`TERM=dumb`, UTF-8, locale/timezone,
  `PYTHONHASHSEED`, logging contamination, and broken-pipe behavior.
- Add installed-wheel tests from an unrelated working directory using the
  accepted application/composition replacement seam, not a second test-only
  application implementation.

### Out of scope

- Production Adapter construction, `bootstrap.py`, canonical schema changes,
  Device access, workflow files, pilot harness, or live acceptance.

### Dependencies

- M3.3 merged.

### Owned paths

- `src/coreelec_reconciler/cli/parser.py`
- `src/coreelec_reconciler/cli/main.py`
- `src/coreelec_reconciler/cli/presentation.py`
- `tests/scaffold/test_cli.py`
- `tests/scaffold/test_cli_planning.py`
- `tests/scaffold/test_cli_execution.py`
- `tests/unit/cli/`
- `tests/fixtures/cli/`
- `docs/implementation/cli.md`

### Parallelism

May run in parallel with M3.4 after M3.3 merges. It must not edit M3.4 or M3.6
owned paths.

### Acceptance

At minimum:

```bash
uv run pytest -q \
  tests/unit/cli \
  tests/scaffold/test_cli.py \
  tests/scaffold/test_cli_planning.py \
  tests/scaffold/test_cli_execution.py
uv build
```

Required evidence covers every workflow/status/exit combination, approval
handoff, inspect-first recovery, resume Verification, rollback, both finalize
modes, standalone verify/report, cleanup uncertainty with converged Device
truth, exact stdout bytes, stderr separation, next commands, quiet/color/TTY,
broken pipe, contamination sentinels, and wheel execution away from checkout.

### Documentation and security

Document exact installed command forms, stable stdout/exit contracts, unstable
human stderr, approval scopes, recovery action discovery, and abandonment
requirements. No prompt may collect or reveal a secret.

## M3.6 — Integrate M3 offline and build the pilot harness

### Outcome

Wire the accepted production composition, prove the complete M3 offline system
as one installed package, and produce a deterministic source-bound pilot
harness and independent evidence-bundle verifier without contacting a Device.

### Scope

- Integrate M3.4 production Adapters and M3.5 CLI through the single production
  `bootstrap`.
- Keep dependency construction in the composition root; the CLI and
  application do not instantiate concrete Adapters.
- Finalize architecture/import guards and wheel-content checks.
- Finalize test selection so every issue-42/43 offline case runs exactly once
  across the pure and remaining-offline budget commands.
- Add production/fake shared contract execution to the correct selector
  without network access.
- Build a deterministic pilot harness that:
  - validates exact source/configuration/lock binding;
  - describes the issue-44 core sequence;
  - supports dry run only in M3;
  - writes a synthetic unstitched evidence bundle;
  - never resolves real secrets or opens a Device session in dry-run mode.
- Build an independent offline bundle verifier that rejects missing,
  duplicated, stitched, source-mismatched, digest-invalid, secret-bearing, or
  semantically invalid evidence.
- Run complete installed-wheel workflow acceptance from an unrelated working
  directory.
- Publish cohesive offline execution, recovery, reporting, development, and
  pilot-readiness documentation.
- State explicitly that `SKIN-025` remains shell-owned and that M3 does not
  authorize live use.

### Out of scope

- Live Device access, shell freeze, ownership transfer, pilot mutation,
  deployment, M4 issue generation, Effect reconsideration, or shell
  retirement.

### Dependencies

- M3.4 merged.
- M3.5 merged.

### Owned paths

- `src/coreelec_reconciler/bootstrap.py`
- `pyproject.toml`
- `uv.lock`
- `.github/workflows/offline-ci.yml`
- `scripts/run_test_budget.py`
- `scripts/run_m3_pilot_harness.py`
- `scripts/verify_m3_evidence_bundle.py`
- `tests/ci/`
- `tests/integration/`
- `tests/fixtures/pilot-harness/`
- `docs/development.md`
- `docs/implementation/offline-execution.md`
- `docs/implementation/pilot-readiness.md`
- directly related README/runbook references that must state the M3 no-live
  boundary

M3.6 is the only issue allowed to edit shared dependency, workflow,
production-composition, global selector, or cohesive M3 documentation
surfaces.

### Acceptance

The issue creates and runs exact commands for:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check <accepted Python paths>
uv run mypy
uv run python scripts/check_inventory_milestones.py
python3 scripts/check_shell_permissions.py --audit
uv run python scripts/run_test_budget.py \
  --label pure-unit-architecture \
  --budget-seconds 10 \
  --timeout-seconds 300 \
  --result .ci-evidence/pure.json \
  -- \
  .venv/bin/python -m pytest -q <accepted pure selectors>
uv run python scripts/run_test_budget.py \
  --label complete-offline \
  --budget-seconds 60 \
  --timeout-seconds 300 \
  --include-result .ci-evidence/pure.json \
  --result .ci-evidence/offline.json \
  -- \
  .venv/bin/python -m pytest -q <accepted remaining selectors>
uv build
uv run python scripts/run_m3_pilot_harness.py \
  --dry-run \
  --output .ci-evidence/m3-pilot-dry-run
uv run python scripts/verify_m3_evidence_bundle.py \
  .ci-evidence/m3-pilot-dry-run
python3 scripts/check_markdown.py
git diff --check
```

The final issue body must replace `<accepted ... selectors>` with exact
non-overlapping lists. Evidence proves every named issue-42/43 offline case
exactly once, shared Adapter contracts, installed-wheel behavior, no sockets,
no Device access, deterministic harness bytes, independent verifier
rejection cases, package contents, source/tree/config/lock digests, and
unchanged shell ownership and permission-ledger behavior without running the
legacy shell suite.

### Documentation and security

Documentation becomes the coherent M3 offline truth, while shell-oriented
live provisioning remains authoritative until M4. The dry-run bundle uses
synthetic identities and values only and is scanned for credentials, private
paths, real Device identifiers, secret values, and raw exception content.

## M3.7 — Seal the offline execution and recovery milestone

### Outcome

Verify merged M3 from clean checkouts and commit the authoritative M3 exit
record.

### Scope

- Verify the exact merged M3 source on Linux x86_64 and macOS arm64.
- Repeat every M3.6 acceptance command with exact selectors.
- Repeat canonical determinism under varied hash seed, timezone, and locale.
- Build/install the wheel away from checkout and repeat installed workflows.
- Repeat the deterministic pilot-harness dry run and independent verifier.
- Bind source commit/tree, pull requests, commands, platforms, timings,
  artifact/golden/bundle/package digests, inventory state, documentation
  transitions, security review, and known failures into
  `docs/implementation/milestones/m3-exit.md`.

### Allowed fixes

The seal issue may make only fixes required for already-specified acceptance.
It may not add a capability, invent a schema value, perform hidden integration,
weaken a test, alter a budget, quarantine a failure, or accept a known defect.
A substantive defect reopens its owning predecessor.

### Out of scope

- Device access, M4 issue generation, pilot mutation, ownership transfer,
  shell freeze, deployment, or new design.

### Dependencies

- M3.6 merged.

### Owned paths

- `docs/implementation/milestones/m3-exit.md`
- only narrowly necessary predecessor-owned fixes, explicitly identified and
  routed back to the owning issue contract

### Acceptance

The clean-checkout command list is exactly the accepted M3.6 list plus hosted
Linux/macOS source-bound evidence. The exit fails on any missing issue-42/43
case, selector duplication, budget overrun, non-deterministic byte, package
mismatch, evidence-verifier gap, secret/privacy contamination, real Device
access, or unresolved known failure.

## Build-issue generation handoff

After this record is accepted:

1. Generate the seven issues above in this exact order.
2. Add native blocking edges matching the graph.
3. Assign all seven to milestone M3.
4. Populate each body with its complete section from this record plus the
   cross-issue rules.
5. Label only M3.1 `ready-for-agent`.
6. Leave M3.2-M3.7 blocked and without readiness labels.
7. Do not create the M4 issue yet.

The issue generator must preserve names as written so humans can read the
graph without relying on issue numbers.

## M4 handoff

Only after M3.7 merges and the M3 exit record is accepted may the next
just-in-time issue be generated:

**M4 — Run the live `NewShows.xsp` pilot and permanently freeze shell `skin`
ownership**

That issue must bind to the accepted M3 source/tree and issue-44 procedure. It
owns:

- all Device access and pilot preflight;
- the unstitched live core evidence bundle;
- independent bundle verification against exact source;
- live fresh convergence, drift repair, absence/recreation, Kodi usability,
  and immediate no-op;
- `SKIN-025` transfer to Python;
- permanent shell `skin` warning and actual write-set enforcement;
- operator-document cutover for `NewShows.xsp`;
- a narrow no-Effect decision only if live evidence disproves the accepted
  default.

M3 evidence cannot satisfy M4 live acceptance, and M4 may not start early to
hide an M3 gap.

## Decision summary

- Six implementation issues plus one seal issue.
- Canonical execution Run truth and local durability land first.
- Fake execution remains serial through the complete managed-file lifecycle.
- Production Adapter and installed-CLI lanes may then run in parallel with
  strict disjoint ownership.
- One integration issue owns shared composition, workflows, selectors,
  packaging, full offline acceptance, harness, verifier, and cohesive docs.
- The seal records and verifies accepted work; it is not a hidden integration
  issue.
- Only the first generated issue is initially ready.
- All M3 work is offline and has no Device write set.
- M4 is generated only after the accepted M3 seal.
