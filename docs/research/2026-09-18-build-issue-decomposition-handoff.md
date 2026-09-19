# Build issue decomposition and handoff

Status: Accepted

Issue: [#46](https://github.com/jbruns/tv/issues/46)

## Decision

Implementation work is delivered as dependency-ordered vertical issues. Each
issue produces one reviewable capability through an accepted interface,
including its tests, evidence, and directly affected documentation. Issues are
not split into horizontal "models", "adapters", or "tests" layers.

Only the initial M0-M2 backlog is created at planning handoff. M3 and later
build issues are created just in time after their predecessor exit record and
required design decisions are accepted.

## Issue contract

Every build issue uses these sections:

```markdown
## Outcome
## Stable contract references after M0
## Provenance
## Scope
## Out of scope
## Dependencies
## Milestone and inventory
## Device access
## Owned paths
## Declared Device write set
## Acceptance criteria
## Verification commands
## Evidence handoff
## Milestone exit record
## Documentation
## Security and privacy
## Delivery
## Discovery and escalation
```

Requirements:

- `Outcome` is one independently reviewable behavior or repository change.
- Contract references are repository-relative paths expected on `main` after
  M0. Before M0, SHA-pinned links may appear only under `Provenance`.
- `Inventory IDs` is an exact list/range or `None`.
- `Device access` is exactly `none` or `pilot`.
- `Owned paths` is an exclusive expected write set. Two ready issues in the
  same lane may not overlap it.
- `Declared Device write set` is `none` for M0-M3. Later issues list exact
  State Addresses and Run Infrastructure.
- Acceptance is observable through supported interfaces and independently
  checkable evidence. It never asserts private call order.
- Commands run from the repository root. A command introduced by the issue may
  be an acceptance command only when creating it is explicitly in scope.
- CI links alone are not retained evidence.

Split an issue when it crosses milestones, transfers more than one
independently verifiable ownership boundary, has independently useful
outcomes, or cannot be accepted and reverted coherently. Merge issues only
when their outcomes, blockers, write sets, and evidence are inseparable.

## Dependencies and readiness

GitHub native dependencies are preferred when available. The body always
retains a portable fallback:

```markdown
Blocked by:
- #123 - Title

Blocks:
- #124 - Title
```

Use `Blocked by: None` for an unblocked issue.

Exactly one canonical readiness/disposition label applies when appropriate:

- `needs-triage`
- `needs-info`
- `ready-for-agent`
- `ready-for-human`
- `wontfix`

Assignment is a claim, not readiness. A blocked issue has no readiness label.
An issue receives `ready-for-agent` only when:

1. every blocker is closed;
2. every predecessor milestone exit record is present on `main`;
3. non-provenance references resolve on `main`;
4. its inventory assignment is valid;
5. its owned paths do not overlap another ready issue;
6. its acceptance commands exist or are explicitly created by the issue;
7. its Device access declaration is valid; and
8. no unresolved design issue changes its interface or write set.

There is at most one ready issue per implementation lane. Readiness is removed
when a new blocker invalidates the specification.

## Milestones and exit records

GitHub milestones `M0` through `M11` group work according to the accepted
roadmap. A milestone is complete only when this committed record exists:

```text
docs/implementation/milestones/m<N>-exit.md
```

The exit record contains:

- accepted source commit and tree digest;
- closing issue and pull request;
- evidence index and artifact digests;
- exact commands, platforms, results, and timing;
- inventory-ledger and ownership changes;
- documentation transitions;
- known failures, or `none`.

Comments and labels are not milestone authority. Readiness checks consume the
committed exit record.

## Branches, worktrees, and delivery

One build issue normally produces one pull request:

```text
branch:   build/<issue-number>-<slug>
worktree: .worktrees/<issue-number>-<slug>
```

Build branches start from merged current `main` after blockers close. They are
never stacked on unmerged sibling build branches. Use a merge commit, not a
squash or rebase merge, and include `Closes #<issue>` in the pull request.

Parallel work is allowed only for dependency-ready issues with disjoint owned
paths. One issue owns shared manifests, lockfiles, and workflow files at a
time. There is one integration owner and one live Device mutation actor.

An issue closes only after its pull request is merged, required evidence is
bound to the merged commit, tests and documentation pass, and ownership
ledgers contain the merged truth. No issue authorizes production deployment.

## M0 preservation rules

The first build issue reserves exactly these currently untracked accepted
Reconciler foundation paths:

```text
CONTEXT.md
docs/architecture/coreelec-reconciler.md
docs/adr/0001-controller-only-on-demand-reconciler.md
docs/adr/0002-declarative-domain-resources.md
docs/adr/0003-exclusive-resource-ownership-and-verified-rollback.md
docs/adr/0004-disposable-pilot-cutover.md
```

It copies those reviewed files into an isolated worktree and commits them
there. It must not commit from, clean, reset, or otherwise alter the dirty main
worktree.

The following untracked paths are explicitly excluded:

```text
.agents/
AGENTS.md
docs/agents/
skills-lock.json
```

Every other unlisted untracked path is also excluded and reported.

M0 integrates:

1. the preservation commit above;
2. the linear accepted Wayfinder decision history through issue #47;
3. ADR 0006 from its accepted research branch; and
4. only the toolchain proof research record from the proof branch.

The proof branch's `src/`, tests, `pyproject.toml`, `uv.lock`,
`.python-version`, and `.gitignore` changes remain prototype evidence and are
not production input. G0 must contain no production `src/`, `pyproject.toml`,
or `uv.lock`.

M0 also creates the dependency-free `scripts/check_markdown.py`, preserves
unique historical facts, repairs links, removes the superseded plan/spec tree,
converts temporary branch references to stable repository paths or SHA
provenance, and records `docs/implementation/milestones/m0-exit.md`.

Wayfinder branches remain until M0 merges and the provenance map is verified.
They may then be deleted.

## Tests, evidence, and security

Every implementation issue:

- tests behavior through accepted seams;
- keeps the pure/unit suite below 10 seconds and complete offline suite below
  60 seconds;
- does not shard, quarantine, retry, rerun, or `xfail` to hide a regression;
- updates directly affected documentation in the same pull request;
- records source-bound evidence rather than relying only on CI links;
- prevents secrets, credentials, controller-local paths, and sensitive
  payloads from entering canonical output or retained public evidence;
- fails closed on ambiguity; and
- does not deploy or mutate production Devices.

`device: none` issues enforce the offline socket guard. `device: pilot` issues
name the exact allowlisted Device and accepted predecessor evidence.

Current shell tests run in a separate transition CI job until shell
retirement. They are not included in Python's 10/60-second budgets.

## Inventory and ownership

Every issue declares its inventory IDs. The ledger records:

```text
id
role
disposition
milestone
current_owner_or_executor
closure
closing_issue
closing_pr
test
evidence
documentation
```

Owner/executor values include `shell`, `python`, `repository`, `operator`,
`external`, and `none`. Closure rules are role-aware: repository provenance,
Guided Actions, Health Checks, inventory facts, retired rows, and managed
Resources do not pretend to share one Device actor model.

An inventory ID cannot appear in competing ownership-transfer issues.
Ownership, shell permissions, evidence, and documentation update together.

## Just-in-time design

Later milestone design issues may open while their predecessor is being
implemented, but they use only `wayfinder:*` labels and begin with:

> Design question only - not implementable.

They specify no final module filename, signature, schema, or transport
capability before the design is accepted. Later build issues are generated
only after predecessor exit and design acceptance.

If implementation reveals an architecture change, affected work stops,
failing evidence is retained, readiness is removed, and a linked decision
issue becomes a blocker. Safety contracts are never weakened locally to close
an implementation issue.

## Reopening and retirement

Reopen an issue when merged behavior fails, evidence is stale or invalid,
ownership is wrong, or an acceptance criterion was not met. A new complete
evidence attempt replaces no historical evidence.

`wontfix` is an explicit terminal disposition with rationale, never silent
scope reduction. Shell retirement follows M11; git history and the recorded
last shell-capable tag are historical recovery sources, not a runtime fallback.

## Initial issue graph

Only M0-M2 and the pre-M4 shell audit are created now:

```text
A Preserve untracked foundation
└─ B Integrate accepted decisions
   └─ C Remove superseded docs and seal G0
      └─ D Create production scaffold
         ├─ E Add CI and budgets
         ├─ F Add inventory/ownership ledger and validators
         │  └─ H Audit shell write sets (parallel; gates M4, not M2)
         └─ G Seal M1 (blocked by E and F)
            └─ I Implement authored configuration and validate
               └─ J Implement pure playlist planning/reporting
                  └─ K Seal M2
```

Only A is initially `ready-for-agent`. The #47 implementation lane is created
after M1 exit. M3 and later build issues remain just in time.

## Rejected alternatives

- Ten public workflow methods: mirrors the CLI and creates a shallow surface.
- Horizontal layer issues: produce no independently usable behavior.
- Stacked build branches: invalidate predecessor and evidence bindings.
- Squash-only history: loses accepted decision and issue provenance.
- Branch-name links as contracts: become stale when planning branches retire.
- Readiness labels on blocked work: advertise work that cannot safely start.
- Creating all later issues now: freezes speculative Resource Type internals.
- Untracked foundation as authority: unavailable to other clones and CI.
- Integrating proof implementation as production: confuses evidence with the
  clean implementation scaffold.
- Automatic production deployment: outside the roadmap and user authorization.
