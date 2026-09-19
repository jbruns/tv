# Implementation milestones and documentation transitions

Date: 2026-09-18

Ticket: [Choose implementation milestones and documentation transitions](https://github.com/jbruns/tv/issues/45)

Status: **Accepted autonomous contract-level decision**

## 0. Shell-test CI amendment (2026-09-19)

Legacy shell tests remain in the repository as manually runnable reference
evidence, but they are no longer part of routine CI, readiness, milestone
acceptance, or Python budgets. This amendment supersedes every prospective
requirement below to keep a shell transition job green. It does not transfer
Device ownership: shell remains the authorized actor for each State Address
until the accepted Python ownership handoff for that address.

## 1. Decision

Implementation proceeds through milestones M0–M11 plus a parallel supply-chain
lane for [issue #47](https://github.com/jbruns/tv/issues/47). This is an
implementation roadmap, not implementation and not a speculative design for
later Resource Types.

The critical path is:

```text
M0 -> M1 -> M2 -> M3 -> M4 -> M5 -> M6 -> M7 -> M8 -> M9 -> M10 -> M11
             \
              +-> #47 supply-chain lane -> M6 live add-on acceptance -> M11
```

The route has these fixed properties:

1. M0 first preserves accepted foundational files that currently exist only
   as untracked main-worktree content, then integrates every accepted
   committed planning source into one authoritative history. Acceptance
   cannot remain bound to untracked state, but the reviewed preservation
   commit is a valid and required first integration commit.
2. The superseded plan/spec tree is removed in M0, in the same reviewed change
   set that proves its unique facts are preserved and repairs every inbound
   link. Git history is the archive.
3. M1 creates the production Python 3.14 scaffold and Linux x86_64/macOS arm64
   CI. Legacy shell suites remain manually runnable reference evidence and do
   not count against Python's budgets or milestone acceptance.
4. M2 is pure configuration, domain, planning, and reporting. M3 adds offline
   managed-file execution and recovery. M4 alone performs the first live
   `NewShows.xsp` pilot.
5. Later Resource Type milestones fix outcomes, evidence, inventory coverage,
   ownership transfer, documentation, and prerequisite decisions. They do not
   predeclare interfaces that have not yet been learned from the predecessor.
6. All 169 classified inventory IDs are assigned exactly once in section 6.
   The accepted totals remain 153 migrate, 5 retire, and 11 outside.
7. Live mutation windows on the disposable pilot are serialized. There is one
   current executor or owner and one active ownership ledger for every
   inventory row.
8. M10 requires an evidence-based Python-only observation window of at least
   24 hours and one complete Kodi/TV lifecycle cycle. It is an additional
   normal-use observation, not a substitute for tests or pilot cases, and
   judges explained convergence rather than requiring zero physical writes.
9. M11 removes active shell, shell tests, and final shell-facing documentation
   in one coordinated merge train. Git history and exact reimage/bootstrap
   instructions preserve recovery knowledge; shell is not retained as a
   second active owner.
10. This roadmap authorizes no production fleet deployment.

## 2. Authoritative inputs and G0 integration

### 2.1 Accepted inputs

M0 must integrate the following accepted records. The first group has no
prior commit provenance and must be preserved in its first reviewed commit:

- root `CONTEXT.md`, `AGENTS.md`, and `docs/agents/`;
- `docs/architecture/coreelec-reconciler.md`;
- ADRs 0001–0004;
- any other accepted untracked foundation found during the pre-integration
  inspection.

That first commit records issue/map attribution and the exact accepted file
set without claiming a nonexistent earlier commit. M0 then integrates these
committed branch records with their real commit and issue provenance:

- ADRs 0005–0006;
- [current managed State Address inventory](2026-09-18-current-managed-state-inventory.md);
- [managed-state classification](2026-09-18-managed-state-classification.md);
- [authored configuration schema](2026-09-18-authored-configuration-schema.md);
- [canonical Plan and Run Report schema](2026-09-18-canonical-plan-run-report-schema.md);
- [core module and Resource Type contracts](2026-09-18-core-module-resource-type-contracts.md);
- [first managed-file test contract](2026-09-18-first-managed-file-test-contract.md);
- [Run workspace, recovery, and Effect contracts](2026-09-18-run-workspace-recovery-effect-contracts.md);
- [disposable-pilot acceptance procedure](2026-09-18-disposable-pilot-acceptance-procedure.md);
- the accepted Python 3.14 foundation research and toolchain proof;
- the accepted issue decisions through issue #44 and proof issue #48.

The integration commit series is the **G0 planning baseline**. M0 records its
final commit and tree digest. M1 and M2 build issues, tests, fixtures, and
acceptance manifests bind to that integrated source. A commit from a
pre-integration decision branch is provenance, not the implementation
acceptance source.

### 2.2 Integration rules

- Before branch integration, inspect dirty main without reverting, cleaning,
  overwriting, or silently absorbing unrelated files. Create the reviewed
  foundational preservation commit described above.
- Preserve actual branch commit provenance by merging or cherry-picking the
  accepted commits with their issue references; do not copy only their final
  text into an unattributed squash.
- Resolve conflicting refinements in dependency order: issue 43 refinements
  supersede the earlier recovery sketches, and issue 44 refinements supersede
  earlier live-pilot wording.
- Rewrite cross-document, map, and issue-comment links after integration to
  stable repository paths on the authoritative branch. Branch URLs may remain
  only as historical provenance links.
- Do not bind acceptance to untracked files. Accepted untracked foundations
  become integrated only through the reviewed first commit.
- Run repository-wide Markdown link, fence, and table validation after the
  paths stabilize.
- Record the integrated commit and tree digest in the M1 scaffold and in the
  first-slice acceptance manifest.

## 3. Milestone operating rules

### 3.1 Entry and exit

A milestone begins only when all predecessor exits are accepted and any
listed just-in-time (JIT) design issues are resolved. A milestone exits only
with:

- passing required automated commands on Linux x86_64 and macOS arm64 where
  specified;
- canonical retained evidence for every in-scope Resource, Guard, Effect,
  Guided Action, and inventory fact;
- updated inventory and actor-ownership ledgers;
- replacement operator documentation for every ownership transfer;
- no unexplained Run, remote marker, lease, quarantine, or rollback state;
- independent review of its contract and evidence.

Failure never permits a milestone to be marked partially complete by deleting
evidence or narrowing acceptance after the fact. Correct the implementation,
recover or reimage under the accepted rules, and produce a fresh attempt.

Roadmap-wide, no sharding, quarantine, retry, threshold change, or selection
change may hide a performance or correctness regression. Amending a test
budget requires retained evidence and a reviewed architecture decision; a
milestone or build issue cannot weaken the budget locally.

### 3.2 Test budgets

The accepted Python budgets are exact:

- pure/unit/architecture selection: **under 10 seconds**;
- complete offline suite, including the first selection exactly once:
  **under 60 seconds**;
- a 300-second outer watchdog detects hangs but never waives either budget.

Each Linux and macOS job runs `uv sync --frozen`, then measures only pytest
execution with `time.monotonic_ns()`. Dependency synchronization, environment
creation, wheel build, and live Device work are outside the measured interval.
No retry, rerun, quarantine, ignored failure, or `xfail` can satisfy a gate.

Legacy shell tests remain available as a manual reference command. Their
approximately seven-minute runtime is not part of routine CI, milestone
acceptance, or the Python 10/60-second budgets.

### 3.3 Ownership ledger

The repository gains a machine-readable and human-readable ownership ledger
in M1. Its schema supports Device and non-Device rows. For each inventory row
it records:

- inventory ID and logical State Address;
- accepted role and disposition;
- current executor or owner: `shell`, `python`, `repository`, `operator`,
  `external`, or `none`;
- closure state, assigned milestone, and the evidence bundle that authorizes
  the current state;
- precise shell write set and Effects still permitted, if any;
- replacement or retained documentation;
- unresolved recovery or quarantine state.

A Device address cannot have both shell and Python as mutation actors.
Repository-owned build/provenance rows, operator Guided Actions, external
health dependencies, and ownerless retired rows use their precise closure
semantics rather than a forced shell/Python actor. Transfer is append-only
evidence: prestate, handoff, Python acceptance, and shell-write-set freeze or
retirement. Shell is permitted only where its audited complete write set,
including conditional/shared writes and side effects, is proven disjoint from
every Python-owned address.

At each handoff, update both the guard and ledger before any later mutation.
After explicit reimage and Device-identity review, and only before a Python
handoff, one recorded shell full-provisioning run may establish a new
baseline. That exception invalidates all old live acceptance evidence and
requires fresh Python ownership evidence. No shell overlap is permitted after
the handoff.

### 3.4 JIT design rule

During predecessor implementation, JIT design issues may be opened for the
next milestone's declared Resource Type, Effect, Guard, Guided Action, or
health needs. This enables pipeline work, but those issues cannot become
accepted build instructions and implementation cannot begin until predecessor
exit evidence is accepted. They may refine transport capabilities and
recovery semantics only with an explicit compatibility decision against the
accepted core contracts.

Build issues for M3 and later are generated only after the predecessor exit
and the required JIT decisions are accepted. M0, M1, and M2 are the only
implementation issues that may be generated together at plan handoff.

## 4. Milestones

### M0 — Integrate authoritative planning and remove superseded plans

**Objective.** Establish one authoritative planning baseline and remove the
superseded plan/spec tree without losing durable facts.

**Prerequisites / entry.**

- Issues #34–#44 and #48 are accepted.
- Their source commits and branch tips are recorded.
- Issue #46 is accepted and authorizes the initial M0/M1/M2 build issues.
- The target branch and dirty main worktree have been inspected; unrelated
  edits are identified and protected from reversion or accidental inclusion.

**In scope.**

- Create the first reviewed commit for accepted untracked `CONTEXT.md`,
  `AGENTS.md`, `docs/agents/`, `docs/architecture/coreelec-reconciler.md`,
  ADRs 0001–0004, and any other accepted untracked foundation, with issue/map
  attribution and no false prior-commit claim.
- Then integrate every committed source in section 2.1, including ADRs
  0005–0006, inventory/classification, and research contracts #38–#44.
- Reconcile refinements and rewrite internal links to stable repository paths.
- Verify the unique-fact preservation table in the current inventory.
- Remove the complete superseded plan/spec tree.
- Repair the three content links into that tree from:
  `docs/devices/ugoos-am6b-plus/room-desired-state.md`,
  `docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md`, and
  `docs/operations/provision-ugoos.md`.
- Update `docs/decisions/repository-documentation-architecture.md` to describe
  git history, accepted ADRs, accepted research, and durable operational docs
  as the surviving record classes.
- Record the G0 commit and tree digest.

**Inventory IDs.** None transfer ownership. M0 preserves the classification
source against which all 169 IDs are later audited.

**JIT decisions required.** None.

**Explicitly deferred.** Production Python code, CI, shell behavior changes,
Device contact, and operator ownership transfer.

**Exit commands / evidence.**

- repository Markdown link, fence, and table validators;
- an inbound-link search proving no live reference to the deleted tree;
- a unique-fact preservation checklist tied to section 6 of the inventory;
- `git diff --check`;
- recorded G0 commit/tree digest and provenance map.

**Ownership state.** Shell remains the sole Device mutation actor. Non-Device
rows retain their classified repository/operator/external/none owner; Python
owns nothing.

**Documentation changes.** Planning records become authoritative in their
stable locations. Durable README, runbook, Device, room, audio, add-on,
lifecycle, system, and network documentation remains current.

**Failure / recovery.** Revert or correct the integration before M1. Missing
facts or broken links block M0; restoring the superseded tree as an active
documentation layer is not the remedy.

**Dependencies.** First build milestone after issue #46; blocks every later
implementation milestone.

### M1 — Production scaffold, CI, transition coverage, and issue foundation

**Objective.** Create the supported Python 3.14 project and enforcement
surface without implementing Device mutation.

**Prerequisites / entry.** M0 accepted; G0 commit/tree digest recorded.

**In scope.**

- Create the PEP 621 `src/` package `coreelec-reconciler` with import package
  `coreelec_reconciler`, bounded `uv_build`, `.python-version`, committed
  `uv.lock`, and the accepted dependency bounds.
- Add one production `bootstrap` composition root and installed console-script
  shell with unimplemented commands failing explicitly.
- Add Ruff, strict mypy, pytest, architecture checks, wheel-content checks,
  canonical JSON golden infrastructure, and installed-wheel smoke tests.
- Add Python 3.14 CI for Linux x86_64 and macOS arm64 with frozen sync,
  10/60-second budgets, and the 300-second hang watchdog.
- At M1, add a separate current-shell transition job that runs the existing
  shell suites without charging their time to Python budgets. The 2026-09-19
  amendment removes this job after M2 while retaining the command as manual
  reference evidence.
- Add inventory coverage and ownership-ledger schemas/checkers.
- Audit actual shell behavior into a machine-readable write-set/Effect map,
  including conditional writes, shared-document writes, dependencies that
  expand execution, service changes, and other side effects. Component and
  selector names are descriptive only; allowed shell operations are computed
  from disjoint write sets.
- Add automated Markdown links, fences, tables, command examples, and
  documented-path validation.
- Bind generated acceptance manifests to G0 and current implementation source
  commits/tree digests.
- Establish the issue #46 build-issue labels and readiness hooks.

**Inventory IDs.** None transfer ownership.

**JIT decisions required.** None. Issue #46 is a prerequisite to M0 and plan
handoff, not an M1 JIT decision.

**Explicitly deferred.** Profile semantics, real Resource behavior, Device
sessions, mutation, recovery, and live acceptance.

**Exit commands / evidence.**

- `uv sync --frozen`;
- Ruff format/lint, strict mypy, pytest architecture/unit/offline selections,
  and wheel build/inspection on both supported platforms;
- installed CLI import and `--help` outside the checkout;
- historical M1 shell transition evidence, without making it an ongoing gate;
- inventory checker proves 169 unique classified IDs, accepted
  role/disposition, exactly one assigned milestone, and the correct current
  executor or owner without demanding future milestone closure;
- audited shell write-set/Effect map covers every current mutation path and
  demonstrates that later freeze decisions can be based on actual behavior,
  never selector labels;
- documentation validators and `git diff --check`.

**Ownership state.** Shell remains the sole Device mutation actor. M1 records
the precise current owner for every non-Device row. Python CLI is non-mutating.

**Documentation changes.** Add contributor/build/CI instructions, record the
historical shell transition evidence, and document the manual reference
command. Operator instructions remain shell-current.

**Failure / recovery.** A failed platform job blocks M2. Dependency or budget
failure reopens the relevant foundation decision; it is not waived locally.

**Dependencies.** Requires M0. Enables M2 and the parallel #47 lane.

### M2 — Pure configuration, domain, planning, and reporting tracer

**Objective.** Implement the pure contract core and non-mutating CLI tracer
for the first Resource without Device mutation.

**Prerequisites / entry.** M1 accepted; G0/source binding enforced.

**In scope.**

- Restricted, versioned YAML parsing for `DeviceInventory`, `Profile`,
  `ArtifactCatalog`, and `SecretProviderCatalog`.
- Fixed platform → optional room → optional Device composition, strict IDs,
  secret references, dependency/ownership validation, and selected dependency
  closure.
- Frozen typed domain models and strict codecs for accepted Intent,
  Observation, Change, Plan, and Run Report data.
- Canonical Plan and Run Report serialization, digests, revision invariants,
  statuses, approvals, exit-code vocabulary, and progress separation.
- Pure `KodiSmartPlaylist` resolution, safe
  `special://profile/...` logical-path binding, XML parse/render,
  normalization, assessment, planning, and no-Effect default.
- `validate` and `plan` installed-CLI paths using fakes only. They must contact
  no Device and perform no mutation.
- The issue-42 authored YAML/composition, canonical JSON, invariant-checker,
  CLI stream, contamination, packaging, and architecture matrices applicable
  to a pure slice.

**Inventory IDs.** No actor transfer. `SKIN-025` is represented in fixtures
but remains shell-owned until M4 acceptance.

**JIT decisions required.** None beyond accepted #38–#42 contracts.

**Explicitly deferred.** Device adapters, RunStore mutation leases, apply,
verification against a Device, rollback, recovery, and live pilot.

**Exit commands / evidence.**

- exact Python 10/60-second gates on Linux and macOS;
- installed `validate` rejection before transport construction;
- installed `plan` canonical golden cases for create/update/remove/no-op/
  blocked;
- socket guard and architecture imports prove the pure core cannot contact a
  Device;
- independent Plan/Run invariant checker passes every fixture;
- documentation validators remain green.

**Ownership state.** Shell remains the sole Device mutation actor. Python can
validate and plan only; non-Device ownership remains as recorded at M1.

**Documentation changes.** Add authored configuration and non-mutating
`validate`/`plan` operator references, clearly marked preview/non-owning.

**Failure / recovery.** No Device state can require recovery. Canonical schema
or source-binding failures block M3 and require corrected fixtures/contracts.

**Dependencies.** Requires M1; blocks M3.

### M3 — Managed-file execution and recovery offline

**Objective.** Complete the production managed-file execution engine and the
full issue-42 offline/contract matrix without contacting the pilot.

**Prerequisites / entry.** M2 accepted.

**In scope.**

- Least-authority Device sessions, Paramiko SSH/SFTP adapters, typed lstat/read
  results, explicit atomic replace-over-existing capability, and shared
  production/fake adapter contracts.
- Deep managed-file behavior for stage, mode, unconditional atomic replace,
  remove, fresh re-observation, strict Verification, and verified rollback.
- Full RunStore, local Device lease, workspace lease, derived active index,
  durable remote ownership, token-before-acquire, per-primitive durable intent,
  mutation traces, attachments, revision chain, Effect records, finalization,
  quarantine, and allowed recovery actions.
- `apply`, `reconcile`, `verify`, `recover`, and `report` for the managed-file
  slice through the installed CLI.
- Every issue-42 semantic, fault/interleaving, stale race, ambiguity,
  interruption, recovery, RunStore durability, CLI, adapter, packaging, and
  invariant test applicable offline.
- A pilot harness and independent offline bundle verifier, but no live run.

**Inventory IDs.** No actor transfer. `SKIN-025` remains shell-owned.

**JIT decisions required.** None; issue #43 is controlling.

**Explicitly deferred.** Pilot mutation, shell `skin` freeze, Kodi live
usability decision, and all later Resource Types.

**Exit commands / evidence.**

- exact Linux/macOS Python gates and budgets;
- full named issue-42 offline/contract matrix exactly once;
- shared fake and production-adapter contracts;
- installed-wheel CLI behavior away from the checkout;
- deterministic pilot harness dry run and independent bundle verification;
- shell ownership and permission-ledger invariants remain valid.

**Ownership state.** Shell remains the sole live Device mutation actor. Python
mutation exists but is not authorized on the pilot; non-Device ownership is
unchanged.

**Documentation changes.** Add recovery/report reference material and
explicitly state that live ownership has not transferred.

**Failure / recovery.** Ambiguous fixtures must end in the accepted
recovery-required state; tests may not hide them with retries. No live cleanup
is needed because M3 is offline.

**Dependencies.** Requires M2; blocks M4.

### M4 — Live `NewShows.xsp` pilot and permanent shell `skin` freeze

**Objective.** Accept the first live Resource and transfer its ownership to
Python using the complete issue-44 procedure.

**Prerequisites / entry.**

- M3 accepted on Linux and macOS for the exact source commit/tree digest.
- Disposable pilot identity, host key, platform, boot identity, path safety,
  lifecycle quiet window, and no-unresolved-work checks pass.
- One clean, committed wheel, configuration, source-code subtree digest, and
  G0 contract baseline are selected; evidence from any other bound digest
  cannot satisfy this milestone. Documentation-only commits after sealing do
  not invalidate the bundle when wheel, code, configuration, and lock digests
  are unchanged. Any relevant code, configuration, or lock change does.
- The eventual acceptance commit must be an ancestor of cutover `main`.

**In scope.**

- Inventory ID `SKIN-025`, Resource `skin.playlist.new-shows`, including
  present/absent state, strict semantics, mode `0644`, path safety, atomic
  replacement, rollback/recovery, reporting, and no-Effect decision.
- One unstitched core evidence bundle covering absent-to-create, semantic
  formatting no-op, semantic drift, mode-only drift, malformed regular XML,
  explicit absence, recreation/Kodi usability, and immediate second-Run
  no-op.
- Genuine first-use Run Infrastructure creation and independent offline
  evidence-bundle verification.
- Append-only shell-to-Python handoff and ownership seal.
- Immediate operator warning and CI/check guard that prevents
  `provision-coreelec.sh` from running on the pilot when its audited effective
  write set intersects `SKIN-025`.
- The issue-44 permanent pilot freeze for shell `skin` scope remains as a
  coarse warning, while enforcement uses actual write sets. Shell remains
  allowed only for recorded operations whose complete writes and Effects are
  proven disjoint from `SKIN-025` and every other Python-owned address.

**JIT decisions required.** Only a narrow Effect decision if live evidence
disproves the accepted no-Effect default. Acceptance must be rerun from a new
bundle after that decision.

**Explicitly deferred.** Other playlists, skin settings/generated state,
shared Kodi settings, add-ons, and fleet rollout.

**Exit commands / evidence.**

- the exact issue-44 conceptual harness sequence for the bound source;
- sealed, unstitched core bundle and independent verifier;
- canonical final playlist at `0644`, no leaked subtree, restored lifecycle
  state, and no unresolved recovery;
- CI/check proof that shell operations whose write set intersects `SKIN-025`
  are rejected, with the immediate frozen-`skin` operator warning present;
- Python 10/60-second jobs remain green.

**Ownership state.** Python owns `SKIN-025`. Shell may not regain `skin`
ownership on the pilot, even when playlist content is semantically equal.

**Documentation changes.** Update `docs/operations/provision-ugoos.md`,
README/runbook entry points, and the ownership ledger with the pilot warning,
frozen-scope rule, and Python operator commands for `NewShows.xsp`.

**Failure / recovery.** Preserve the failed bundle. Use computed recovery;
reimage only under issue-44 triggers. Any new attempt gets a new bundle and
handoff. Never resume shell `skin` to repair the Resource.

**Dependencies.** Requires M3; blocks M5.

### M5 — Shared Kodi settings, room Intent, and timezone

**Objective.** Transfer the shared Kodi/CoreELEC settings documents and their
coalesced Effects without recreating shell component ownership. One
`KodiGuiSettings` Resource owns every managed `guisettings.xml` address.

**Prerequisites / entry.** M4 accepted and the pilot shell `skin` freeze is
enforced.

**In scope.**

- `CORE-001–CORE-029`, including `KodiGuiSettings`, `CoreElecTimezone`,
  secret-safe web settings, audio Intent resolution, and derived timezone
  evidence `CORE-007`;
- `ROOM-001–ROOM-011`;
- `SVC-001`, because `weather.addon` is another address in the same shared
  `guisettings.xml` ownership boundary;
- `SKIN-001–SKIN-002`, because they are addresses in the shared
  `guisettings.xml` ownership boundary;
- `EFFECT-001–EFFECT-002`, with coalesced Kodi and timezone barriers,
  readiness, fresh post-Effect observations, and truthful no-Effect cases;
- exact per-setting Changes while preserving one shared-document Resource
  boundary and all unowned siblings;
- missing legacy verification for `CORE-008`, `CORE-018–CORE-020`, and related
  indirect-only settings;
- serialized live pilot fresh convergence, representative drift repair, and
  second-Run no-op for every migrated address.

**JIT decisions required.**

- `KodiGuiSettings` canonicalization and exact observation strategy;
- timezone accepted representations and Effect/rollback behavior;
- audio/display Intent resolvers and capability ambiguity;
- secret-safe evidence for web settings;
- Weather selector dependency and Health-versus-Verification boundary;
- Kodi readiness and shared-document rollback boundaries.

**Explicitly deferred.** Add-on ownership/settings, CEC, SSH hardening, skin
documents outside `guisettings.xml`, Guided Actions, and generic inventory.

**Exit commands / evidence.**

- Linux/macOS contract suites and exact budgets;
- document-preservation and duplicate/case canonicalization fixtures;
- live full in-scope profile convergence, per-address drift repair, post-Effect
  Verification, and no-op;
- independent comparison against the M5 inventory list;
- no concurrent or overlapping shell mutation window.

**Ownership state.** Python owns all M5 IDs on the pilot. The shell ledger
freezes every actual write set that can touch the shared GUI/timezone
documents, even when that orphans a later selector/component label. Only
audited, proven-disjoint shell write sets remain allowed. Required add-on and
service state scheduled for M6 remains frozen and stable on the dedicated
pilot until transfer; shell cannot repair it. A pre-handoff reimage may use
the single recorded re-baseline exception in section 3.3, invalidating old
live acceptance and requiring fresh Python evidence.

**Documentation changes.** Add Python settings/timezone/room procedures.
Narrow shell provisioning documentation and examples to its remaining
ownership; preserve room documents as installed-system truth, not acceptance
history.

**Failure / recovery.** Shared-document rollback is Resource-scoped and must
preserve unrelated settings. Effect failure follows accepted barrier recovery.
Unresolved state blocks later mutation and the next milestone.

**Dependencies.** Requires M4; blocks M6.

### M6 — Add-ons, Artifact supply chain, and add-on settings

**Objective.** Transfer pinned add-on installation/enabled/content ownership
and add-on settings using accepted Artifact provenance.

**Prerequisites / entry.**

- M5 accepted.
- The #47 lane has resolved the decision and delivered reproducible Artifact
  build/provenance/catalog-validation capabilities for every live add-on case
  in this milestone.

**In scope.**

- `ART-001–ART-041`, one `KodiAddon` Resource per explicit roster entry;
- `ADDON-001–ADDON-003`, including migrated per-add-on enablement,
  outside/unmanaged discovery, and retirement of
  `ADDON_UNMANAGED_ALLOWED`;
- `PATCH-001–PATCH-004`, replacing Device runtime transforms with
  reproducibly prebuilt Artifacts;
- `SVC-002–SVC-017`, including Weather, NextPVR, and TMDb Helper settings,
  explicit dependency/presence semantics, and the already accepted
  retirement of the four PM4K cleanup mutations;
- stable-first policy, digest pins, prerelease exception evidence, dependency
  expansion, final installed-content Verification, and secret redaction;
- serialized live pilot fresh convergence, drift repair, and second-Run no-op.

**JIT decisions required.**

- `KodiAddon` registry observation, atomic install/remove, enabled-state,
  rollback, dependency, and final-content verification;
- each add-on settings document boundary and absence behavior;
- Weather/NextPVR/TMDb secret-safe evidence;
- no conditional reopening of `SVC-014–SVC-017`: any future absorption
  requires an explicit classification amendment, count/checker update, and
  reviewed milestone-contract change.

**Explicitly deferred.** Release-discovery/update-PR automation may remain
incomplete here if live accepted Artifacts can already be built and validated
reproducibly. It must be complete before M10 starts. Guided onboarding remains
M8.

**Exit commands / evidence.**

- Artifact/catalog schema and dependency validation;
- reproducible build proving upstream, patch-set, and final digests;
- stable/prerelease policy fixtures and ZIP/content safety contracts;
- Linux/macOS Python gates and budgets;
- serialized live add-on/settings acceptance with final content, version,
  enabled state, settings, drift repair, and no-op evidence;
- explicit retirement evidence for `ADDON-003` and `SVC-014–SVC-017`.

**Ownership state.** Python owns migrated M6 addresses. Undeclared add-ons
remain unmanaged; retired cleanup mutations have no actor.

**Documentation changes.** Replace shell add-on install/settings procedures
incrementally with Python Artifact/catalog/operator docs. Preserve the durable
add-on onboarding contract for Guided Actions, while removing obsolete links
or commands only where ownership has transferred.

**Failure / recovery.** A digest, provenance, dependency, or prerelease-policy
failure blocks before Device mutation. Failed live install uses tested
Resource rollback/recovery; no Device-side patch retry is allowed.

M6 may be executed as dependency-ordered submilestones or batches after its
JIT decisions. Every split preserves this one JIT contract, the exact M6
mapping and counts, serialized live mutation, and one final M6 completion
gate; no batch is an independently accepted milestone.

**Dependencies.** Requires M5 and the live-acceptance portion of #47; blocks
M7.

### M7 — Remaining skin settings, generated state, and playlists

**Objective.** Transfer the remaining Arctic Fuse settings, generated state,
and playlist ownership while retaining one authoritative source for derived
outputs.

**Prerequisites / entry.** M6 accepted.

**In scope.**

- `SKIN-003–SKIN-024` and `SKIN-026–SKIN-028`;
- partial `ArcticFuseSettings`, authoritative widget JSON files,
  authoritative viewtype source, derived compiled evidence, all remaining
  playlists, dynamic clock binding, and explicit absent playlists;
- `EFFECT-004` `BuildSkinViews`, including deterministic invocation, skin
  readiness/reload, source re-observation, and compiled-expression evidence;
- serialized live fresh convergence, representative drift repair, and
  second-Run no-op.

`SKIN-025` remains covered by M4 and must not be counted again.

**JIT decisions required.**

- Arctic Fuse canonicalization and equivalent-empty handling;
- widget JSON schemas and ordering;
- viewtype source template, compiled predicate, and `BuildSkinViews` barrier;
- remaining smart-playlist templates, dynamic year/clock binding, and
  runtime-health distinctions.

**Explicitly deferred.** CEC, SSH hardening, lifecycle gateway, Guided
Actions, and general inventory/health presentation.

**Exit commands / evidence.**

- exact source-versus-derived ownership tests;
- canonical/digest tests for whole-file Resources;
- Effect barrier and post-Effect evidence contracts;
- Linux/macOS gates and budgets;
- serialized live convergence/drift/no-op evidence for every M7 ID.

**Ownership state.** Python owns all skin addresses after M7. Shell `skin`
remains frozen and its skin writer/verifier is now removable at final cutover,
but is not deleted before M11.

**Documentation changes.** Add Python skin/generated-state operator docs and
narrow shell documentation to non-skin remaining ownership.

**Failure / recovery.** A generated-output failure never creates a second
owner. Recover or roll back the authoritative source under the accepted Effect
rules, retaining derived evidence and ambiguity.

**Dependencies.** Requires M6; blocks M8.

### M8 — Remaining Resources, Guards, Guided Actions, health, and inventory

**Objective.** Complete the remaining classified behavior without converting
outside facts or human-mediated work into Desired State.

**Prerequisites / entry.** M7 accepted.

**In scope.**

- `PLAT-001–PLAT-005`: unified platform/model/release/OpenSSH Guards and the
  outside kernel/hostname fact;
- `SSH-001–SSH-004`: outside bootstrap/key-installation documentation,
  managed SSH hardening, and pinned host-identity Guard;
- `CEC-001–CEC-005`;
- `GUIDE-001–GUIDE-008`: PM4K and Emby Guided Actions plus Weather/NextPVR
  Health Checks;
- `LIFE-001–LIFE-003`: lifecycle gateway Resource and temporary service-state
  restoration Effect;
- `EFFECT-003` and outside `EFFECT-005`;
- `FACT-001–FACT-006`: purpose-driven inventory/audit and diagnostics;
- serialized live acceptance for migrated Device state and objective Guided
  Action/health evidence without claiming false Convergence.

This milestone may be split into dependency-ordered submilestones after its
JIT decisions, but its inventory list and final exit remain one M8 contract.
Any split must preserve exactly-once mapping and serialized pilot mutation.

**JIT decisions required.**

- Guard evidence and transport binding;
- SSH hardening document/service rollback;
- CEC discovery ambiguity and canonicalization;
- lifecycle gateway partial-file ownership and restoration Effect;
- Guided Action states/redaction;
- Health Check status/freshness;
- purpose-driven inventory/report fields.

**Explicitly deferred.** Full-profile audit, observation window, cutover, and
fleet deployment.

**Exit commands / evidence.**

- Guard refusal and no-force-bypass tests;
- lifecycle allowed/denied command and restoration tests;
- CEC exactly-one-file preservation tests;
- Guided Action false-success and redaction matrices;
- Health-versus-Verification tests;
- inventory purpose/freshness and outside-state non-drift tests;
- Linux/macOS budgets and serialized live migrated-state acceptance.

**Ownership state.** Python owns all inventory rows with migrated Device state.
Bootstrap and outside facts remain outside; Guided Actions remain
operator-assisted; retired behavior has no actor.

**Documentation changes.** Add final Python bootstrap boundary, SSH, CEC,
lifecycle gateway, Guided Action, health, and inventory procedures. Retain
Home Assistant lifecycle policy documentation because runtime policy remains
outside the Reconciler.

**Failure / recovery.** Guard failures block mutation. Health failures do not
roll back converged settings. Guided Action incompleteness remains explicit
and cannot be relabeled Resource drift. Resource failures use accepted
recovery.

**Dependencies.** Requires M7; blocks M9.

### M9 — Complete inventory audit and full-profile pilot

**Objective.** Prove every classified row is closed and the complete resolved
Profile converges as one Python-owned system.

**Prerequisites / entry.** M8 accepted; all JIT decisions and migrations
complete.

**In scope.**

- Mechanically reconcile factual inventory, classification, milestone map,
  ownership ledger, tests, docs, and live evidence.
- Prove every one of 169 IDs appears exactly once with its accepted role and
  disposition; totals are 128 Resources, 5 Guards, 5 Effects, 6 Guided
  Actions, 4 Run Infrastructure, 21 Unmanaged/Inventory Facts and 153 migrate,
  5 retire, 11 outside.
- Run the full resolved Profile on the disposable pilot: fresh convergence
  from the Manageable Device boundary, representative drift repair across
  every Resource Type, and immediate complete no-op.
- Prove no shell mutation occurs during the full-profile evidence window.
- Close every documentation and ownership-ledger gap.

**Inventory IDs.** Audit-only; M9 does not remap or recount an ID.

**JIT decisions required.** Only concrete gaps discovered by the audit.
Unresolved gaps block exit; they are not accepted as roadmap exceptions.

**Explicitly deferred.** The 24-hour observation window, shell deletion, final
documentation switch, and production fleet deployment.

**Exit commands / evidence.**

- `scripts/check_inventory_milestones.py` against inventory,
  classification, milestone map, and ownership ledger;
- all Linux/macOS Python gates;
- all documentation validators;
- sealed full-profile fresh/drift/no-op pilot bundle with independent
  verification;
- proof of zero missing, duplicate, or disposition-mismatched IDs.

**Ownership state.** Python owns every migrated Device Resource and executes
its accepted Guards and Effects on the pilot. Repository, operator, external,
and none remain the precise owners for build/provenance, Guided Action,
health/inventory, and retired rows. Shell has no authorized mutation scope on
the pilot, but remains present and tested until M11.

**Documentation changes.** Complete Python operator documentation and mark
shell docs historical-pending-retirement without removing recovery/bootstrap
facts.

**Failure / recovery.** Any ID, evidence, ownership, documentation, or no-op
gap returns work to the owning milestone. Full-profile failure follows normal
Run recovery and requires a fresh acceptance attempt.

**Dependencies.** Requires M8; blocks M10.

### M10 — Python-only normal-use observation and cutover authorization

**Objective.** Establish evidence that the accepted full Profile remains
operable through normal use before authorizing shell retirement.

**Prerequisites / entry.** M9 accepted; pilot is canonical, fully Python-owned,
has no unresolved Run or recovery state, and #47 release-discovery/update-PR
automation is accepted. No #47 merge is permitted during the bound window.

**In scope.**

- One continuous observation window of at least 24 hours.
- At least one complete Kodi/TV lifecycle cycle under normal Home Assistant
  policy.
- No shell mutation, unexplained divergence, manual repair, or unresolved
  recovery.
- Every runtime write either normalizes to Desired State or is explicitly
  classified as allowed unmanaged or runtime-owned state. Physical writes are
  not forbidden merely because a no-op logical Plan remains converged.
- Python verification/report evidence, Health Checks, and ownership-ledger
  snapshots sampled before and after at least one complete Kodi/TV lifecycle
  cycle.
- Final cutover authorization review.
- Record the last shell-capable commit/tag and exact Manageable Device
  reimage/bootstrap instructions as historical recovery sources.

**Inventory IDs.** Observation-only; no remapping.

**JIT decisions required.** None. Any discovered issue returns to its owning
milestone.

**Explicitly deferred.** Shell deletion and final doc removal until M11.

**Exit commands / evidence.**

- timestamped start/end verification and canonical no-op;
- lifecycle cycle evidence and health results;
- audit proving no shell mutation and no unresolved recovery;
- evidence that every observed runtime write/divergence is normalized or
  explicitly classified;
- repeated full offline/CI gates;
- signed cutover authorization.

Any managed divergence requires a fix, new acceptance evidence, and a restart
of the full window. Any unexplained divergence, manual repair, unresolved
recovery, or prohibited merge also restarts it. Time elapsed before the issue
does not count toward a later attempt.

**Ownership state.** Python remains sole pilot mutation actor. Shell is present
only as inactive code under CI.

**Documentation changes.** Add exact historical commit/tag and reimage/
bootstrap recovery instructions. Do not document shell as an active fallback.

**Failure / recovery.** Fix Python or reimage under the preserved bootstrap
instructions, rerun the required tests/pilot acceptance, and restart the
window. Do not restore dual ownership.

**Dependencies.** Requires M9 and completion of #47's release-discovery/
update-PR automation before the observation starts; blocks M11.

### M11 — Coordinated documentation transition and shell retirement

**Objective.** Publish one Python-only operating model with no active shell
fallback or release gap.

**Prerequisites / entry.**

- M10 cutover authorization accepted.
- #47 is fully resolved, including release discovery and evidence-rich
  update-PR automation.
- Full inventory, operator docs, recovery docs, and ownership ledger are
  complete.

**In scope.**

- One merge train containing two isolated, reviewable commits:
  1. final Python-only documentation switch, removal of remaining shell
     examples/instructions, and authoritative navigation updates;
  2. deletion of active shell provisioning/configuration code, shell-only
     libraries, fixture hooks, and shell tests.
- No release, deployment, or operator handoff may occur between the commits.
- Keep the already-manual legacy shell tests only as historical reference
  until the shell-removal commit deletes them.
- Preserve the last shell-capable commit/tag and exact reimage/bootstrap
  instructions as historical recovery, not an executable fallback.
- Re-run the M0 unique-fact preservation and inbound-link checks before shell
  deletion.
- Explicitly disposition the shell-authored `config/` tree and `rooms` values:
  migrated desired values move into accepted Profiles/Artifact catalog;
  retained room files remain installed-system facts; shell-only configuration
  is removed with shell. No second source of Desired State remains.
- Run the complete Python, documentation, inventory, package, and clean-tree
  gates against the final combined tree.

**Inventory IDs.** Audit-only; all active ownership remains Python/outside/
retired exactly as M9 proved.

**JIT decisions required.** None.

**Explicitly deferred.** Production fleet deployment, which requires a
separate authorization and rollout plan.

**Exit commands / evidence.**

- final Linux/macOS Python gates and budgets;
- final inventory/ownership checker;
- Markdown links/fences/tables/command-example validation;
- searches proving no active shell provisioning entry point, shell test, or
  operator example remains;
- repeated unique-fact/link validation and proof that `config/`/`rooms`
  contain no competing Desired State source;
- wheel/install/CLI smoke tests and `git diff --check`;
- one release artifact built only from the combined final tree.

**Ownership state.** Python is the sole active Reconciler. Outside and retired
rows remain outside/retired. No shell fallback exists.

**Documentation changes.** Final README, runbook, operations, Device, room,
audio, add-on, lifecycle, and network navigation points to Python workflows.
Accepted ADRs and research remain engineering records; room documents remain
installed-system truth, not acceptance journals.

**Failure / recovery.** Before release, revert the isolated shell-removal
commit if a combined-tree gate fails, keeping both commits in the same merge
train with no release gap. After release, fix Python or reimage/bootstrap from
the documented boundary; do not restore shell ownership or dual ownership.
This preserves ADR 0004.

**Dependencies.** Requires M10 and complete #47; final roadmap milestone.

## 5. Parallel issue #47 supply-chain lane

### 5.1 Issue #47 refinement — 2026-09-18

The accepted [supply-chain contract](2026-09-18-addon-update-patch-supply-chain.md)
adds exact gates without changing the milestone order:

- after M1, source adapters, candidate-manifest dependency closure, Kodi
  version ordering, deterministic build, mirror publication, and proposal
  automation may proceed in parallel;
- before M6 live add-on acceptance, origin/distribution separation,
  repository-owned mirrors for every mutable/generated/repacked/patched input,
  required build attestations, catalog validation, and scheduled plus
  Reconciler prerelease-expiry preflight are complete;
- before M10, immutable per-candidate branches, per-Artifact concurrency,
  exact-rerun reuse, human-commit protection, and evidence-rich PR automation
  are accepted;
- issue #47 is resolved and handed to issue #46 before implementation-plan
  issue generation; resolving #47 does not itself start #46.

ART-009 `weather.ha` is deterministically repacked, patched, attested, and
published as a repository-owned content-addressed Release asset. It is never
consumed as codeload distribution bytes.

The decision in issue #47 should be resolved before issue #46 and plan handoff
when possible. Its implementation lane begins in parallel after M1 because it
needs the production toolchain, CI, schema validation, and issue foundation,
but it is not a prerequisite for M2–M5 settings work.

Its integration points are:

| Point | Required #47 capability |
|---|---|
| After M1 | Decision work and prototype may begin against the authoritative schemas and CI |
| Before M6 live add-on acceptance | Reproducible Artifact build; upstream, patch-set, and final provenance digests; catalog/dependency validation; stable/prerelease policy enforcement |
| During M6 | `KodiAddon` consumes only validated, digest-pinned final Artifacts; no runtime Device patching |
| Before M10 starts | Eligible-release discovery and evidence-rich update-PR automation complete; never auto-merge or deploy |
| During a bound M10 window | No #47 merge; a required change ends the window and a new one starts after acceptance |
| Before issue #46 plan handoff, when possible | The decision ticket is resolved and its implementation lane is represented in the issue graph |

The `KodiAddon` Resource may be coded before release-discovery automation is
complete, but no live add-on acceptance may use an Artifact whose reproducible
build/provenance/catalog gates are absent.

## 6. Exact inventory-to-milestone mapping

### 6.1 Authoritative mapping

Every explicit ID below maps to exactly one implementation milestone or to an
explicit retirement/outside audit within that milestone. Ranges are inclusive.
No ID is implied by prose.

| Milestone | Exact IDs | Rows | Migrate | Retire | Outside | Closure |
|---|---|---:|---:|---:|---:|---|
| M4 | `SKIN-025` | 1 | 1 | 0 | 0 | First live managed-file ownership transfer |
| M5 | `CORE-001–CORE-029`; `ROOM-001–ROOM-011`; `SVC-001`; `SKIN-001–SKIN-002`; `EFFECT-001–EFFECT-002` | 45 | 45 | 0 | 0 | Complete shared Kodi/CoreELEC GUI settings boundary, room Intent, timezone, and Effects |
| M6 | `ART-001–ART-041`; `ADDON-001–ADDON-003`; `PATCH-001–PATCH-004`; `SVC-002–SVC-017` | 64 | 58 | 5 | 1 | Add-ons/Artifacts/settings; accepted retirement of `ADDON-003` and `SVC-014–SVC-017`; audit outside `ADDON-002` |
| M7 | `SKIN-003–SKIN-024`; `SKIN-026–SKIN-028`; `EFFECT-004` | 26 | 26 | 0 | 0 | Remaining skin/settings/generated state |
| M8 | `PLAT-001–PLAT-005`; `SSH-001–SSH-004`; `CEC-001–CEC-005`; `GUIDE-001–GUIDE-008`; `LIFE-001–LIFE-003`; `EFFECT-003`; `EFFECT-005`; `FACT-001–FACT-006` | 33 | 23 | 0 | 10 | Remaining Resources/Guards/Actions/health/inventory; outside `PLAT-003`, `SSH-001–SSH-002`, `EFFECT-005`, `FACT-001–FACT-006` |
| **Total** | **All classified IDs** | **169** | **153** | **5** | **11** | **Exactly once** |

`CORE-007`, `GUIDE-007–GUIDE-008`, and `SKIN-017–SKIN-018` retain their
accepted `Unmanaged/Inventory Fact` role with `Migrate` disposition because
they are required evidence/health surfaces, not separately owned Resources.
`PATCH-001–PATCH-004` retain their `Run Infrastructure` role. Mapping a row to
a milestone does not change its role.

### 6.2 Mechanical audit contract

M1 adds `scripts/check_inventory_milestones.py`. It must:

1. parse every factual inventory ID from the contiguous ranges in the
   inventory;
2. expand every classification range and reject overlap or omission;
3. expand every section 6.1 milestone range and reject overlap or omission;
4. join by ID and require classification role/disposition to remain unchanged;
5. compare the ownership ledger, tests, docs, and evidence index with
   phase-aware rules: at M1 every row has a current executor/owner and exactly
   one assigned milestone, but closure/evidence/replacement-doc requirements
   apply only once that assigned milestone is accepted;
6. assert the exact role totals `128/5/5/6/4/21`, disposition totals
   `153/5/11`, and grand total `169`;
7. emit a sorted audit table:

```text
id | role | disposition | milestone | current_owner | closure | test | evidence | doc
```

CI fails on a missing ID, duplicate ID, changed role/disposition, unknown ID,
an invalid current owner for the row's role/disposition/phase, premature
closure, or an accepted ownership transfer without evidence and replacement
operator documentation. Future `migrate` rows remain open and explicitly
shell-owned, or use the correct current non-Device owner, until their assigned
milestone is accepted; there is no unconditional “unclosed migrate” failure.

M9 runs the same checker against the complete implementation and evidence;
M11 runs it against the final Python-only tree.

## 7. Documentation transition matrix

| Documentation surface | M0 | M1–M3 | M4–M8 ownership transfers | M9–M10 | M11 |
|---|---|---|---|---|---|
| `README.md` and `docs/runbook.md` | Retain; repair navigation | Add build/CI and non-mutating Python entry points | Add Python workflows as accepted; show shell frozen/narrowed scopes | Python primary; shell marked inactive pending retirement | Remove final shell examples; Python-only navigation |
| `docs/operations/provision-ugoos.md` | Retain current shell truth; replace three superpowers links with durable facts | Retain shell procedure | M4 adds prominent pilot `skin` prohibition and ownership ledger; narrow commands after each handoff | Historical-pending-retirement, no authorized pilot mutation | Remove shell procedure/examples; retain Manageable Device/reimage facts in Python operations docs |
| `docs/devices/ugoos-am6b-plus/coreelec-21.3.md` and system decision | Retain durable platform/installed-system truth | Add supported-controller and Guard references | Update observed ownership/results, not acceptance chronology | Confirm full-profile installed truth | Retain |
| `room-desired-state.md`, room READMEs, and room Device records | Retain; replace superpowers link | No acceptance history | Update current installed Desired State and Python procedure as ownership moves | Confirm final installed truth | Retain; rooms remain system truth |
| `audio-output.md` | Retain stable Intent/capability facts | Link pure Intent contract | Replace shell execution steps at M5 | Confirm final resolver behavior | Retain |
| `addon-onboarding-contract.md` | Retain; replace superpowers link | No premature Resource claims | M6 updates installed add-on/settings ownership; M8 adds Guided Action commands | Confirm Action/health truth | Retain |
| `docs/home-assistant/ugoos-kodi-lifecycle.md` and HA assets | Retain because runtime policy is outside Reconciler | Validate examples in transition CI | M8 replaces Device gateway installation steps while retaining HA runtime policy | Exercise one lifecycle cycle | Retain |
| `docs/network/` | Retain bootstrap/network truth | Validate links/examples | Update only if connection/host-key workflow changes | Confirm reimage/bootstrap path | Retain |
| `docs/decisions/` and accepted ADRs/research | Retain engineering records | Add stable links from implementation docs | Append superseding decisions rather than rewriting history | Retain | Retain |
| Superseded plan/spec tree | Preserve unique facts, repair inbound links, delete in same M0 change set | Absent | Absent | Absent | Absent |
| Python operator reference | Not yet | Add validate/plan, then recovery/report reference | Add per-Resource workflows with every ownership transfer | Complete full-profile and cutover/reimage docs | Authoritative |
| Shell source/tests/examples | Retain | Run separate transition CI | Freeze/narrow by ownership ledger; never silently overlap | Present but inactive on pilot | Delete in isolated commit in coordinated merge train |

Documentation validation is automated from M1:

- internal and repository-relative Markdown links;
- balanced fenced code blocks and parseable Markdown tables;
- documented file paths and executable names;
- shell/Python command examples in controlled dry-run/help modes;
- generated CLI help snippets where used;
- ownership-ledger references and inventory IDs;
- a deny-list preventing links to deleted superseded documents;
- after M11, a deny-list for active shell provisioning examples.

Acceptance bundles and dated pilot results remain evidence, not room or Device
truth. Durable docs state the current supported system and recovery boundary.

## 8. Build-issue relationship

Issue #45 decides this milestone contract. Issue #46 must be accepted before
any build issue is created; it decides maximum issue size, acceptance format,
ownership boundaries, readiness labels, predecessor evidence, documentation
obligations, and anti-speculation rules.

After #46 is accepted, the plan handoff may generate initial issues only for:

- M0 authoritative integration and superseded-document removal;
- M1 production scaffold/CI/shell-transition foundation;
- M2 pure configuration/domain/planning/reporting tracer;
- the independent #47 implementation lane, only if its decision is already
  accepted and its own graph permits it.

M3 is generated after M2 exit. M4 is generated after M3 exit. During
predecessor implementation, the next milestone's JIT design issues may be
opened, but they cannot become accepted build instructions or start
implementation before predecessor exit evidence. M5–M8 implementation issues
are generated only after those decisions and predecessor exit. M9–M11 issues
are generated after the preceding evidence exposes their concrete inputs.

No issue may turn the later milestone outcomes in this record into invented
method signatures, filenames, schemas, transport capabilities, or Effect
semantics. A later issue is ready only when its accepted predecessors and JIT
decisions make those details concrete.

This record creates no build issues and changes no issue state or map.

### Issue #46 refinement

Issue #46 defines the build handoff in
`docs/research/2026-09-18-build-issue-decomposition-handoff.md`.

- M0 is split into preservation, decision integration, and G0
  documentation-removal/sealing issues.
- M1 is split into production scaffold, CI/budgets, ledger/validators, and an
  exit-evidence issue.
- The shell write-set and Effect audit is a parallel pre-M4 gate and does not
  block M2.
- Milestone exits are committed under
  `docs/implementation/milestones/m<N>-exit.md`.
- Build branches start from merged `main`, use one issue and merge-commit PR
  each, and are never stacked on unmerged siblings.
- Only the M0-M2 initial backlog is created at plan handoff. The #47
  implementation lane follows M1; M3 and later remain just in time.

## 9. Cutover invariants

- The pilot is disposable acceptance infrastructure, but reimage is a
  controlled recovery path, not a way to erase failed evidence.
- Shell and Python never mutate concurrently.
- After M4, shell effective `skin` scope is permanently frozen on the pilot.
- After each later transfer, the audited write-set guard and ownership ledger
  expand before another shell command is allowed. Permission is based on
  disjoint actual writes and Effects, never component/selector labels.
- One recorded full shell provisioning run is permitted only after explicit
  reimage/identity review and before a new Python handoff. It establishes a
  new baseline, invalidates old live acceptance, and requires fresh Python
  evidence; no shell overlap is allowed after handoff.
- M9 full-profile acceptance precedes M10 observation.
- M10 lasts at least 24 hours and includes one complete Kodi/TV lifecycle
  cycle, sampled before and after. It passes only with no unexplained
  divergence, manual repair, or unresolved recovery and with every runtime
  write normalized or explicitly classified. Any managed divergence requires
  a fix/new evidence and restarts it; zero physical writes is not required.
- The last shell-capable commit/tag and exact reimage/bootstrap steps are
  retained as history/reimage source. Shell is not retained as a runtime
  fallback.
- Before the final release, the isolated shell-removal commit may be reverted
  if combined-tree gates fail. After release, recover by fixing Python or
  reimaging to the Manageable Device boundary, never by restoring shell
  ownership.
- M11 has no release gap between final documentation and shell deletion.
- No #47 merge may occur during a bound M10 observation window.
- No milestone authorizes production fleet deployment.

## 10. Acceptance checklist

- [ ] M0 integrates every accepted source with stable links and provenance.
- [ ] The superseded plan/spec tree is removed with unique-fact proof and all
      inbound links repaired.
- [ ] M1 enforces Linux x86_64/macOS arm64 Python 3.14 CI and exact
      10/60-second budgets; legacy shell tests remain manual reference
      evidence rather than a gate.
- [ ] M2 and M3 preserve the accepted pure/execution split.
- [ ] M4 binds evidence to the post-integration source and permanently freezes
      effective shell `skin` scope on the pilot.
- [ ] M5 transfers the complete shared `guisettings.xml` boundary, including
      `SVC-001`, and every shell permission is based on audited disjoint
      write sets.
- [ ] M5–M8 pipeline prerequisite designs JIT without allowing implementation
      before predecessor exit, and serialize live mutation.
- [ ] #47 gates M6 live Artifact acceptance and is complete before cutover.
- [ ] All 169 IDs map exactly once with totals 153 migrate, 5 retire, and
      11 outside.
- [ ] Every ownership transfer updates tests, evidence, ledger, and operator
      documentation together.
- [ ] M9 proves complete inventory and full-profile pilot acceptance.
- [ ] M10 proves at least 24 hours plus one complete normal lifecycle without
      shell mutation, unexplained divergence, unresolved recovery, or manual
      repair, with runtime writes normalized or explicitly classified.
- [ ] M11 uses isolated documentation and shell-removal commits in one merge
      train, revalidates fact/link preservation, dispositions `config/` and
      `rooms`, and leaves no active shell fallback.
- [ ] Issue #45 and the Wayfinder map record this accepted decision and issue
      #46 is the first implementation prerequisite.
