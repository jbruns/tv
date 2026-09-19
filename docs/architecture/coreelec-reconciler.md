# CoreELEC Reconciler Architecture

## Status

Accepted for implementation planning.

## Purpose

Replace the current shell provisioning implementation with a maintainable
Python 3.14 Reconciler for the repository's CoreELEC/Kodi Device fleet.

The Reconciler manages Desired State declared in versioned configuration. It
must be able to:

- provision a Manageable Device from the post-first-boot boundary;
- install, update, remove, and configure add-ons;
- configure Kodi and CoreELEC settings;
- configure skin state;
- detect and repair drift;
- independently verify Convergence.

The canonical domain language is defined in
[`CONTEXT.md`](../../CONTEXT.md).

## Why Replace the Current Implementation

The existing implementation is functional but combines configuration parsing,
state discovery, transformation, remote execution, rollback, verification, and
reporting across large shell entry points and integration-heavy test suites.
The complete shell suite takes approximately seven minutes.

The replacement is justified only if it improves both change safety and the
cost of understanding the system. Reproducing the shell structure in Python is
not an acceptable outcome.

## Goals

- Keep every desired policy value outside Python code.
- Separate pure state comparison and planning from device communication.
- Model state according to how it can be observed, changed, and verified.
- Preserve Unmanaged State unless authority is explicitly broader.
- Produce a stable, reviewable Plan before mutation.
- Make partial convergence, blocked work, and recovery state explicit.
- Keep most tests pure, fast, and independent of subprocesses or Devices.
- Cover every currently managed State Address before shell retirement.

## Non-goals

- A general-purpose configuration management framework.
- Third-party Resource Type plugins.
- A long-running controller or continuous reconciliation service.
- A persistent on-device agent.
- Runtime Home Assistant/Kodi start-stop policy.
- Pretending interactive account linking is Desired State.
- Backward compatibility with indefinitely old Profile schemas.
- Whole-Run transactional guarantees.

## Product Boundary

The Reconciler is fleet-specific. It supports the real Device profiles managed
by this repository and generalizes only when another supported Device requires
it.

Python 3.14 runs on the administrator/controller machine. A Device is managed
over SSH/SFTP and Kodi JSON-RPC. Temporary remote helpers are allowed when they
make an operation safer or more atomic, but they must be:

- content-addressed and digest-verified;
- free of embedded Desired State;
- uploaded to a Run-scoped location;
- invoked with explicit arguments or standard input;
- removed during finalization.

The Reconciler does not install a persistent remote agent.

## Manageable Device Boundary

The Reconciler begins at a Manageable Device, not untouched hardware. Before a
Run, unavoidable local first-boot work must have established:

- a booted CoreELEC installation;
- network reachability;
- administrator SSH access using the expected key;
- completion of any local prompt that cannot be automated remotely.

The minimal human bootstrap belongs in an operations guide. Everything after
this boundary belongs in the Reconciler or an explicitly separate Guided
Action.

## Desired State

### Profiles

Profiles are authored in YAML and validated completely before the Reconciler
contacts a Device. Unknown keys, duplicate ownership, missing references,
dependency cycles, and unsupported schema versions are errors.

A Device resolves Desired State through a fixed composition pipeline:

1. platform and release profile;
2. room profile;
3. Device overrides.

Resources merge by stable Resource ID. Scalars replace. Lists replace by
default. Mapping fields merge only where the field schema explicitly allows
it. Arbitrary includes, inheritance graphs, and list-position merging are not
supported.

Code and Profiles move together in this repository. Profiles carry an explicit
schema version, and unsupported versions fail with a migration-oriented error.

### No Desired State in Code

After composition, the resolved Profile contains every enforced policy choice.
Python code may define:

- schemas and validation;
- normalization and canonicalization;
- capability discovery;
- state comparison;
- safety invariants;
- observation, application, rollback, and verification mechanics;
- operational defaults such as connection timeouts.

Python code must not silently supply Device policy, add-on selections, setting
values, managed file contents, or Artifact versions.

Shared desired values belong in an explicit base Profile. Large managed content
belongs in referenced files or templates. Remote Artifacts are pinned by
digest through a versioned Artifact catalog.

Secrets are typed references only. Secret values do not appear in Profiles,
Plans, reports, or canonical fixtures.

### Intent

Profiles express stable Intent rather than unstable device representation.
Resource Types resolve Intent using observed capabilities. Examples include:

- resolving a display label to a Kodi-internal numeric index;
- translating a positive Desired State to a negatively named Kodi flag;
- resolving audio choices against the Device's reported enumeration.

Plans retain evidence of the resolution so the mapping remains auditable.

### Presence and Authority

Omitting a Resource means its State Address is unmanaged. Omission never
implies deletion.

Removal requires explicit `desired: absent` state and verifies absence after
application.

Unowned state is ignored and preserved by default. Inventory and audit commands
may discover it without turning it into drift. A Resource may claim
whole-collection or whole-document authority only when that authority is
explicit in the Profile and its destructive impact is visible in the Plan.

## Device Inventory and Guards

Each Device has a stable logical ID. Connection endpoints are mutable inventory
attributes, not identity.

Before mutation, the Reconciler observes hardware, CoreELEC, Kodi, and other
Profile guards. A guard mismatch blocks mutation and has no ordinary force
bypass. Supporting a new platform or release requires an updated Profile and
acceptance evidence.

## Resource Model

A Resource is the smallest cohesive state boundary that can be independently
observed, applied, verified, and, where supported, rolled back. Typical
boundaries include:

- one managed file;
- one service;
- one add-on;
- one cohesive Kodi or add-on settings section.

Individual settings are data within a Resource unless they have genuinely
independent execution and verification semantics.

Every managed State Address has exactly one owning Resource. Duplicate
ownership is a Profile validation error; precedence never resolves ownership
conflicts.

Each Resource has:

- a stable Resource ID;
- a Resource Type;
- Desired State or explicit absence;
- a management mode of `enforce` or `observe_only`;
- one or more owned State Addresses;
- declared dependencies;
- impact classification;
- optional Artifact and secret references.

### Resource Type Contract

A Resource Type owns domain-specific reconciliation semantics:

1. validate and canonicalize Desired State;
2. observe raw state and capabilities;
3. canonicalize the Observation;
4. compare Desired State with the Observation;
5. produce domain-level Changes;
6. apply a Change through typed transport interfaces;
7. independently verify the resulting state;
8. optionally create and verify rollback state;
9. declare required Effects.

Configuration declares domain Resources, not generic remote commands,
JSON-RPC calls, XML edits, or an imperative action DSL.

Resource Types are registered explicitly in the repository. Dynamic imports
and third-party plugin compatibility are out of scope.

### Dependencies

Resources form a validated directed acyclic graph.

Resource Types contribute invariant dependencies. Configuration contributes
dependencies implied by references, such as add-on settings requiring the
add-on Resource.

Selecting a Component or Resource expands its upstream dependency closure.
Downstream dependents are not included automatically. Configuration order does
not control execution.

## Changes, Plans, and Effects

Planning is pure and has no mutation side effects. A Plan is canonical,
serializable JSON containing:

- Device ID and observed platform guards;
- resolved Profile and schema digests;
- code and Plan schema versions;
- Artifact digests;
- stable Resource IDs and dependency graph;
- redacted Desired State and Observations;
- typed `create`, `update`, `remove`, or `blocked` Changes;
- observation fingerprints and apply preconditions;
- impact classifications;
- required Effects.

Low-level commands are implementation details, not the primary Plan contract.

Saved Plans may be reviewed and applied later, but apply revalidates every
binding and precondition. A changed Profile, Artifact, graph, guard, or
Observation invalidates affected Changes and requires re-planning. Elapsed time
alone does not invalidate a Plan when its preconditions still hold.

Operators select Resources before planning. Apply may filter a Plan by stable
Resource ID only after dependency closure and all Plan bindings are revalidated.
Arbitrary editing of individual low-level actions is not supported.

### Effects

Resource Types declare Effects such as Kodi restart, service reload, or Device
reboot. The planner coalesces compatible Effects at safe dependency barriers.
A Resource does not restart Kodi immediately merely because its own Change
requires it.

After an Effect, the Reconciler waits for health/readiness and re-observes every
Resource whose persisted state depends on that Effect. Pre-Effect command
success is not proof of Convergence.

Effects and Changes are classified as:

- `non_disruptive`;
- `service_disruptive`;
- `destructive`.

Disruptive and destructive work requires explicit non-interactive approval
through CLI flags or an approved Plan. Deletion is never hidden inside a
generic update.

## Run Lifecycle

An ordinary Run follows:

1. load and validate inventory, Profiles, Artifact catalog, and secret
   references;
2. acquire one mutating-Run lock for the Device;
3. establish a local immutable Run workspace and remote Run marker;
4. observe selected Resources and platform guards;
5. produce and present a Plan;
6. validate Plan bindings, approvals, and freshness;
7. apply ready Changes in dependency order;
8. execute coalesced Effects at safe barriers;
9. independently verify affected Resources;
10. perform verified Resource-scoped rollback where required and supported;
11. finalize remote state and emit structured results.

Observation and downloads may be parallelized later where proven safe.
Mutation is initially serialized.

## Failure and Recovery

The Reconciler never claims whole-Run atomicity.

After a Resource failure:

- dependent Resources are skipped;
- safe, independent, non-disruptive Resources may continue;
- platform, transport, lock, or uncertain-health failures stop further
  mutation;
- `--fail-fast` stops all remaining mutation after the first failure.

Automatic retries are limited to classified transient failures for idempotent
observation and download operations. Apply is not blindly retried. After an
ambiguous disconnect, the Reconciler re-observes and either recognizes
Convergence, safely re-plans, or blocks for recovery.

Automatic rollback occurs only when the Resource Type declares tested rollback
support and rollback can itself be verified. A rollback result never erases
the original failure.

If a shared Effect or post-Effect verification fails, affected rollback-capable
Resources are rolled back in reverse dependency order. The Effect may run once
more when required to verify restored state. Every original, rollback, and
verification result remains visible.

An abandoned lock, remote marker, backup, helper, or staged change blocks new
mutation until recovery resolves it. Recovery supports:

- inspect;
- resume verification;
- rollback;
- finalize.

Ambiguous recovery state is never silently deleted. A local stale lock is
cleared only when its owning process is definitively absent.

## Run Results and Evidence

Per-Resource statuses are:

- `converged`;
- `changed`;
- `blocked`;
- `failed`;
- `skipped`.

Run statuses are:

- `converged`;
- `partially_converged`;
- `blocked`;
- `failed`.

Stable exit codes and canonical JSON support automation. Human console output
is not a stable interface.

Each Run has a local immutable workspace keyed by Run ID. It stores redacted
Plans, Observations, results, Artifact digests, helper metadata, and recovery
evidence. Sensitive temporary material uses restrictive permissions and is
excluded from reports.

Remote backups and temporary content are Run-scoped. Successful finalization
removes them. Failed Runs retain the metadata required for explicit recovery.
Local reports remain until an operator uses an explicit prune command with
age or Run selectors.

## CLI

The CLI exposes one engine through these workflows:

- `validate`;
- `inventory`;
- `observe`;
- `plan`;
- `apply`;
- `reconcile`;
- `verify`;
- `recover`;
- `report`;
- `action`.

`provision` is a thin full-Profile workflow alias for a Manageable Device. It
does not invoke a separate provisioning implementation.

Normal commands are deterministic and non-interactive. Guided Actions may be
interactive because they represent operator-assisted work such as account
linking.

## Application Structure

The implementation is an on-demand CLI over a reusable application library.
It is synchronous initially.

Dependencies point inward:

- `domain`: immutable domain models and status vocabulary;
- `config`: YAML, inventory, composition, validation, and schema versions;
- `planning`: pure dependency resolution, comparison, Plan construction, and
  Effect scheduling;
- `resources`: built-in Resource Type implementations;
- `transports`: typed interfaces and concrete SSH/SFTP/Kodi clients;
- `execution`: locking, apply sequencing, Effects, rollback, and recovery;
- `reporting`: canonical JSON and human presentation;
- `cli`: argument handling and application wiring.

Pure domain and planning modules cannot import concrete network, filesystem,
subprocess, or CLI implementations.

The project may use a small locked set of focused dependencies for safe YAML,
strict model validation, SSH/SFTP, and CLI behavior. Infrastructure libraries
remain behind narrow adapters. The package requires Python 3.14.

## Guided Actions

Objectively observable add-on installation and settings are Resources.
Interactive authentication, account linking, and other human-mediated
onboarding are Guided Actions.

The Reconciler may report that onboarding is required, but it does not report
interactive state as drift it can automatically repair.

Runtime Home Assistant policy and Kodi start/stop orchestration remain outside
the Reconciler. Files and services required to install a lifecycle gateway may
be ordinary Resources, but the gateway's runtime policy is not.

## Test Architecture and Budgets

Most tests exercise pure models, normalization, dependency resolution, and Plan
construction without subprocesses.

Each Resource Type has contract tests against typed fake clients covering:

- converged observation;
- create, update, and absence;
- unsupported and unobservable state;
- stale preconditions;
- apply failure;
- independent verification;
- rollback when supported;
- Effect declaration and post-Effect persistence.

A small suite covers CLI and serialization boundaries. SSH, Kodi, and real
Device acceptance tests are explicitly marked and opt-in.

Budgets:

- unit suite: under 10 seconds;
- complete offline suite: under 60 seconds;
- live Device acceptance: isolated from default CI.

CI records these budgets so regressions are visible.

## Pilot and Cutover

The existing pilot Device is disposable and is the live acceptance environment.
Complex shell/Python coexistence is unnecessary.

Before cutover, create a complete inventory of every State Address currently
owned by shell behavior. Each row is classified as:

- migrate to a Resource;
- retire deliberately;
- represent as a Guided Action.

The shell implementation is discovery and regression evidence, not the
authority when it conflicts with documented Intent.

Every migrated Resource Type must pass:

1. fresh convergence from the Manageable Device boundary;
2. repair of representative manually introduced drift;
3. a second Run that produces no Changes.

Plans, Observations, and verification results from these scenarios become
acceptance evidence and useful fixtures.

The first vertical slice is a managed-file Resource covering Profile loading,
observation, atomic apply, verification, rollback, reporting, and recovery.
Subsequent slices are:

1. Kodi JSON-RPC settings;
2. add-on installation and settings;
3. skin and generated skin state;
4. remaining services, CEC, room audio/video, Artifacts, and current managed
   concerns.

Cutover occurs only after the complete inventory has an accepted disposition
and the Python implementation passes the three pilot scenarios for all
migrated state.

After cutover, active shell provisioning commands, documentation, and tests
are removed promptly. Git history is the archive; no fallback engine remains
to drift.

## Stable Interfaces

The following are reviewed, versioned interfaces:

- authored YAML Profile schemas;
- Device inventory schema;
- Artifact catalog schema;
- canonical JSON Plan schema;
- canonical JSON Run report schema;
- stable Resource IDs, State Addresses, statuses, and exit codes.

Golden fixtures protect canonical serialization. Schema changes are deliberate
and visible in review.

## Acceptance Criteria

The rewrite is successful when:

1. all current managed state has an explicit migrate, retire, or Guided Action
   disposition;
2. no Desired State is silently supplied by Python code;
3. a simple settings change can be made through Profile data alone;
4. a new Resource Type requires one implementation and reusable contract
   tests, not edits across unrelated layers;
5. planning is pure, canonical, and free of Device mutation;
6. apply rejects stale Plans and independently verifies Convergence;
7. partial convergence and recovery state are machine-readable and explicit;
8. the unit and offline test suites remain within their budgets;
9. the pilot passes fresh convergence, drift repair, and second-Run no-op;
10. the shell provisioning path is removed after accepted cutover.

## Related Decisions

- [Controller-only, on-demand Reconciler](../adr/0001-controller-only-on-demand-reconciler.md)
- [Declarative domain Resources instead of an action DSL](../adr/0002-declarative-domain-resources.md)
- [Exclusive Resource ownership and verified rollback](../adr/0003-exclusive-resource-ownership-and-verified-rollback.md)
- [Disposable pilot cutover and shell retirement](../adr/0004-disposable-pilot-cutover.md)
