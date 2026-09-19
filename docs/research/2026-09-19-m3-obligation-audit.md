# M3 obligation audit against the M2 implementation

## Status

Accepted audit input for the M3 execution-spine and operator-journey
prototypes.

This record maps the accepted M3 roadmap and issue-42/43 contracts onto merged
M2 source commit `e3a32acbda3109251a36a4765bf0d94e12aab9fc`. It does not choose the M3
build-issue graph and does not authorize Device access or mutation.

## Conclusion

No accepted-contract contradiction requires a new human decision before the
two M3 prototypes begin.

M2 established the intended pure core and public application boundary, but it
did not partially implement the execution engine. The M3 work is therefore a
coherent extension around reusable configuration, planning, serialization,
and packaging seams rather than completion of hidden execution machinery.

The most important coupling is:

1. execution Run revisions and their invariant-preserving codec;
2. durable `RunStore` state and recovery evidence;
3. Device observation and mutation traces;
4. application workflow outcomes and installed-CLI rendering.

Those four concerns must be designed together at the public-contract level.
They must not become one module or one implementation issue, but an issue
cannot invent one of their persisted values without accounting for the other
three.

## Accepted source of obligations

The audit treats these records as normative:

- `docs/research/2026-09-18-implementation-milestones-documentation-transitions.md`,
  M3;
- `docs/research/2026-09-18-first-managed-file-test-contract.md`, especially
  the workflow, fake Device, fault, RunStore, adapter, report, CLI, architecture,
  budget, tracer-bullet, and issue-boundary sections;
- `docs/research/2026-09-18-run-workspace-recovery-effect-contracts.md`,
  especially the planned Python refinements, first-slice boundary, and exact
  issue-42 test refinements;
- `docs/research/2026-09-18-core-module-resource-type-contracts.md`;
- `docs/implementation/milestones/m2-exit.md`.

The M3 boundary remains offline. `SKIN-025` remains shell-owned, and Python is
not authorized to mutate the pilot until M4.

## Current M2 shape

### Reusable foundations

M2 already provides:

- one typed `Reconciler.execute(command)` protocol and a closed command union
  in `application/reconciler.py` and `application/commands.py`;
- a single production composition root in `bootstrap.py`;
- strict authored inventory, Profile, Artifact, and secret-reference parsing
  in `config/`;
- pure Profile composition, dependency ordering, Resource selection, and
  ownership validation;
- a pure `KodiSmartPlaylist` Intent, semantic XML parser/renderer, observation
  assessment, and typed create/update/remove planning behavior;
- canonical JSON, Plan construction, Plan decoding, planning Run construction,
  planning Run decoding, and committed M2 goldens;
- architecture tests that keep network libraries behind adapter boundaries
  and keep the CLI behind application/bootstrap boundaries;
- frozen Paramiko and typing dependencies without any production Paramiko
  import yet;
- offline socket enforcement, Linux/macOS CI, installed-wheel smoke coverage,
  and the accepted 10/60-second budgets;
- an audited shell write-set and ownership ledger that keep M3 offline and M4
  ownership transfer explicit.

These are real foundations. M3 must extend them rather than introduce a second
configuration path, a second CLI application path, an imperative Resource
action DSL, or a test-only execution engine.

### Deliberately absent M3 capabilities

There is no current production module for:

- Device sessions, SSH, SFTP, secret resolution, host-key verification, or
  transport capability negotiation;
- `special://profile/` resolution to a normalized safe Device path;
- fresh Device observation;
- managed-file stage, chmod, atomic replace, remove, restore, or cleanup;
- mutation receipts or ordered mutation traces;
- runtime values or progress events;
- filesystem `RunStore`, leases, attachments, active Device index, local
  durability, remote ownership, marker durability, quarantine, or recovery;
- saved Plan loading, binding/freshness validation, approval validation, or
  apply;
- execution Run revisions, execution status computation, Verification,
  rollback, or finalization;
- a stateful fake Device, independent inspector, scripted local durability, or
  production/fake shared adapter contracts;
- the offline pilot harness or independent evidence-bundle verifier.

`apply`, `reconcile`, `verify`, `recover`, and `report` currently reach the
typed `not_implemented` outcome.

## Obligation-to-code map

| M3 obligation | Existing M2 seam | Required M3 delta | Coupling and constraint |
| --- | --- | --- | --- |
| Preserve one application boundary | `Reconciler` overloads and `ApplicationReconciler.execute` already cover every command | Replace callback-only validate/plan wiring with a production application object whose workflows share the same execution services | Keep command dispatch shallow; orchestration must not move into the CLI or Resource Type |
| Load validated Device connection data | Authored `DeviceInput` validates endpoint, SSH username, pinned host-key reference, and secret reference | Return a typed resolved Device connection/inventory value for bootstrap and transport creation | `ResolvedConfiguration` currently retains only `device_id`; M3 must not keep using supplied planning runtime data as transport authority |
| Preserve pure planning | `assess_playlist` and `build_plan_and_run` are pure and covered by behavior/golden tests | Feed fresh typed observation and injected runtime values into the same planning semantics | Observation transport and Run persistence remain outside pure assessment |
| Resolve the managed path safely | The logical State Address is preserved in Resources, Plans, and evidence | Add typed profile-root capability resolution, normalized Device path evidence, and rejection of unsupported schemes/root escape | Logical ownership stays `special://profile/...`; temporary stage/backup paths remain private |
| Introduce Resource execution semantics | `ResourceDescriptor` currently owns authored Intent parsing/address/codecs only | Add the accepted private typed Resource execution contract for observe, assess, prepare/apply, verify, and rollback capability | Do not turn the public descriptor into a generic command bag or expose third-party plugins |
| Device/session least authority | Architecture tests reserve `adapters` as the network boundary; Paramiko is locked | Add typed session/capability ports and a Paramiko adapter with host-key, byte-preserving command, close, timeout, and ambiguity contracts | Production and fake adapters must pass shared public contract cases |
| Atomic managed-file behavior | Pure assessment already distinguishes create, semantic/mode update, remove, no-op, and unsafe state | Add typed lstat/read, same-directory stage, chmod, `posix_rename`, remove, restore, fresh re-observation, and cleanup | Capability absence blocks before managed-address mutation; no remove-plus-rename fallback |
| Truthful mutation outcomes | No execution outcome model exists | Add applied/definitely-not-applied/ambiguous receipts and ordered traces for every primitive | Identical client-visible lost-ack signals must be distinguished only by fresh observation |
| Durable Run workspace | Planning documents are returned in memory only | Add filesystem `RunStore`, opaque workspaces, Device/revision leases, verified revision chains, attachments, active index, compare-and-append, and seal | Persisted canonical revisions and RunStore intents must evolve together |
| Local durability | No filesystem persistence adapter exists | Add private production and scripted `LocalDurability` implementations | Tests assert public RunStore truth, not syscall order or private paths |
| Remote ownership | No remote Run Infrastructure exists | Add token-before-acquire, exclusive durable marker, closed phases, per-primitive reread, release, and quarantine | Full token remains local and private; remote state carries only its digest and bound identity |
| Preparation and rollback | Plans declare verified rollback capability but no before-state attachment exists | Capture complete controller-side rollback material, validate it before mutation, restore conditionally, and independently verify restoration | Incomplete/corrupt preparation cannot advertise rollback |
| Recovery | CLI has a free-form `recover RUN_ID ACTION` scaffold only | Add stable inspection, pure total allowed-action computation, resume-verification, rollback, normal finalize, and approved/reasoned abandon | No forward recovery, automatic Device retry, time-based takeover, or automatic prune |
| Effects schema support | M2 Plans correctly declare no playlist Effect; planning reports carry a post-Effect field | Persist the accepted first-slice Effect states/fixtures and recovery invariants only | M3 must not build a production Effect registry or handler; the playlist remains no-Effect pending M4 evidence |
| Canonical execution reports | `planning_documents.py` builds and decodes only one-Resource planning Runs at revisions 1/2 and four statuses | Extend the canonical report model/codec for execution, failures, approvals, mutation, Verification, rollback, recovery, cleanup, and arbitrary revision chains accepted by issue 39/43 | The current decoder is intentionally hard-coded to planning Runs and cannot be reused unchanged as an execution decoder |
| Saved Plan apply | Canonical Plan bytes, full/semantic digests, bindings, preconditions, expiry values, and approval requirements already exist | Persist/load exact Plans, revalidate all bindings and observations, validate approvals, and execute only the saved Change set | `apply` and `reconcile` must share the same preparation/execution machinery |
| Installed CLI | Parser already exposes every workflow and aliases `provision` to `ReconcileCommand` | Implement typed rendering, canonical stdout, progress stderr, quiet/color/broken-pipe behavior, and exit codes 0/2/3/4/5 | M2 documentation says unsupported commands exit 2; M3 must intentionally transition unsupported/blocked/capability-unavailable to accepted exit 3 |
| Offline pilot readiness | Packaging, installed-wheel smoke, socket guard, budgets, and exact-source CI evidence already exist | Add deterministic harness dry run and independent offline bundle verification | No live host, credentials, Device mutation, or ownership transfer enters M3 |
| Documentation | M2 documents authored configuration and pure planning, and explicitly says execution is unavailable | Add recovery/report reference material, installed execution workflow documentation, and an explicit no-live-ownership statement | Shell operator documentation is not switched to Python ownership until M4 |

## Existing seams that need deliberate deepening

### Validated Device data

`DeviceInput` validates endpoint and SSH policy, but `load_configuration`
returns a `ResolvedConfiguration` that drops endpoint, username, host-key
reference, and credential reference. M2 planning fills endpoint and
fingerprint fields from a supplied offline runtime document.

M3 needs one typed validated Device value at the configuration/application
boundary. It should contain connection policy references, not resolved secret
values. The production composition root can then resolve the secret and create
least-authority capabilities. Re-reading YAML inside an adapter or continuing
to trust supplied planning observations would create a second authority path.

### Resource Type boundary

The current `ResourceDescriptor` is an authored-configuration descriptor. It
parses playlist Intent and supplies State Addresses/codecs, but it has no
observation or execution behavior. That is appropriate for M2.

The execution prototype must preserve the accepted private typed-erasure
design: playlist-specific values stay typed within the Resource module, while
application orchestration sees the closed operations and capabilities it
needs. Expanding `ResourceDescriptor` into a public generic callback registry
would make the module shallower and conflict with the accepted contract.

### Canonical Run reports

The existing Run codec is intentionally a planning-only codec:

- `RunStatus` contains only `planning`, `blocked`, `noop`, and
  `awaiting_approval`;
- planning and originating Run IDs must be equal;
- only revisions 1 and 2 are accepted;
- approvals and failures must be empty;
- exactly one playlist Resource result is accepted;
- mutation is limited to `not_required`, `blocked`, or `pending`;
- rollback must be `not_attempted`.

Execution cannot be represented by adding opaque status strings to the
application outcomes. M3 needs the accepted closed execution/recovery values
and an invariant-preserving revision builder/decoder before `RunStore` can
persist meaningful execution truth.

The Plan codec may remain playlist-specific for the first slice where the
accepted schema permits it, but execution report code should not duplicate
canonical JSON, digest, evidence-reference, or binding rules.

### Application outcomes

The public command union and overloads are good seams. The concrete outcome
dataclasses are M1/M2 placeholders: several expose only a string `status` or a
revision number. The application should return typed canonical documents and
closed presentation facts sufficient for the CLI; it should not expose
workspace paths, tokens, temporary names, raw exceptions, or transport
objects.

`ApplicationReconciler` currently accepts two optional callbacks. M3 should
replace this temporary shape with explicit injected application services or a
single engine dependency while preserving `execute(command)` as the public
surface.

### CLI surface

The parser already reserves the accepted workflow names, but several argument
contracts are only scaffolding:

- `verify` identifies a Device but does not express how a persisted execution
  Run is selected or created;
- `recover` accepts an arbitrary action string and cannot represent separate
  normal/abandon finalization approval and reason requirements;
- `report` has no revision selector or rendering mode;
- `apply` accepts a Plan ID, but there is no persisted Plan lookup;
- only `reconcile`/`provision` currently accept approval scopes;
- `--quiet`, presentation mode, and safety diagnostics are absent.

The operator-journey prototype must settle the smallest CLI expression that
meets the accepted behavior without adding an interactive normal workflow.
It may refine command arguments while preserving the accepted command names
and the `provision` alias.

## Required test assets not present in M2

The following are new M3 assets rather than extensions of the current
repository fixture tree:

1. A stateful case-sensitive POSIX fake Device with typed entry state,
   same-directory staging, atomic-overwrite capability, separate server
   application and client acknowledgement, and an independent read-only
   inspector with no call log.
2. Shared fake/production session, SSH, lstat/read, SFTP mutation, close, and
   ambiguity contract cases.
3. `FakeRuntimeValues` finite UUIDv7/time/token queues and a typed
   `RecordingProgressSink` with selected emission failure.
4. A fake `RunStore` or semantic in-memory contract implementation for
   application fault/interleaving tests.
5. Filesystem `RunStore` fixtures covering complete chains, corruption,
   attachments, leases, active-index scan/rebuild, CAS acknowledgement loss,
   finalization, and permissions.
6. Production and scripted `LocalDurability` contract cases at semantic
   write/sync/replace/directory-sync/acknowledgement points.
7. Remote ownership/durability fixtures for absence, foreign ownership,
   malformed/symlink/nonregular markers, create races, CAS identity/phase
   mismatches, reread failure, release, and quarantine.
8. Complete managed-file fault and interruption scenarios from issue 42/43,
   including every per-primitive identical-signal ambiguity pair.
9. Hand-authored canonical execution/recovery Run revision goldens and one
   independently implemented invariant checker with a negative fixture per
   invariant.
10. Installed-wheel CLI scenarios for all modeled exit codes, stdout/stderr
    separation, quiet/color/TTY/broken pipe, progress failure, and
    contamination sentinels.
11. A deterministic pilot-harness dry run and independent offline
    evidence-bundle verifier, with no live Device access.

Existing M2 configuration, playlist XML, planning behavior, Plan, planning
Run, CLI planning, packaging, architecture, and budget tests remain regression
assets and should not be rewritten into the new fakes.

## Coupling boundaries for the prototypes

The execution-spine prototype must make these seams concrete:

- validated Device inventory to secret resolution and session factory;
- application engine to private Resource Type execution;
- logical State Address to safe path capability;
- Resource observation to pure assessment and Plan;
- saved Plan to prepared execution;
- mutation primitive to durable intent, marker checkpoint, receipt/trace, and
  fresh observation;
- canonical revision builder to `RunStore.compare_and_append`;
- recovery inspection to pure allowed-action computation;
- production/fake adapter contract sharing without production imports in the
  pure core.

The operator-journey prototype must make these journeys concrete:

- converged no-op `reconcile`;
- actionable `reconcile` with explicit approval;
- saved `apply`;
- fresh `verify`;
- read-only `report`;
- interrupted/recovery-required result;
- `recover inspect`;
- allowed `resume_verification` or `rollback`;
- `finalize normal`;
- separately approved and reasoned `finalize abandon`;
- typed blocked/capability-unavailable and known-failed outcomes.

Both prototypes must use canonical outcomes and avoid controller-local or
remote temporary path exposure.

## Risks to carry into decomposition

### False layering

Creating transport, RunStore, reporting, recovery, and CLI as independent
horizontal projects would allow each to invent incompatible state. The build
graph should instead land executable capability increments through the public
application seam, while assigning one owner at a time to shared canonical
schemas and composition files.

### Playlist leakage

The current planner and report decoder contain deliberate
`KodiSmartPlaylist` and one-Resource constants. M3 may keep playlist-specific
domain semantics inside its Resource module, but Run Infrastructure,
transport, managed-file mutation mechanics, recovery, and canonical lifecycle
status must not depend on the playlist ID or XML model.

### Premature generalization

M3 has one Resource and no production Effect. Generic multi-Resource rollback
execution, Effect handlers, retries, scheduling, pruning, plugin discovery,
and persistent helpers remain deferred. The implementation should preserve
their accepted data/invariant seams only where required by the closed report
contract.

### Test-budget pressure

M2 uses roughly 9-10 seconds of the 60-second complete-offline budget but more
than half of the 10-second pure budget in hosted evidence. The large M3 fault
matrix must stay in-process and semantic. Installed-wheel, filesystem, and
adapter contracts should be isolated from the pure selection without
rerunning tests or weakening either budget.

### Documentation authority

M3 documentation may explain offline execution/recovery behavior and pilot
readiness, but it must continue to state that shell owns `SKIN-025` and Python
has not been authorized on the Device. Operator cutover wording belongs to M4.

## Questions cleared by this audit

- **Does M3 need a new architecture decision before prototyping?** No.
- **Can M3 reuse supplied offline observations as its production observation
  path?** No; they remain a pure planning/testing input only.
- **Can the planning Run decoder simply accept more status strings?** No; the
  accepted execution/recovery invariants require explicit models and revision
  validation.
- **Does M3 require a production Effect handler?** No.
- **Does M3 transfer `SKIN-025` or contact the pilot?** No.
- **Can the CLI or reports expose workspace paths to simplify recovery?** No.
- **Can later Resource Types drive generic abstractions now?** No; M3 deepens
  the managed-file capability and shared Run Infrastructure only.

## Handoff

The next frontier contains two parallel HITL prototypes:

- prototype the smallest complete M3 execution spine using the concrete seams
  and coupling boundaries above;
- prototype the installed M3 operator and recovery journey using the scaffold
  gaps and accepted CLI contract above.

After both are accepted, the final map ticket can choose dependency-ordered
build issues, owned paths, evidence gates, documentation transitions, and the
M4 handoff.
