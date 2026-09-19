# Run workspace, recovery, and Effect contracts

Date: 2026-09-18

Ticket: [Define Run workspace, recovery, and Effect contracts](https://github.com/jbruns/tv/issues/43)

Status: **Draft autonomous implementation contract; pending independent review**

## 1. Decision

The Reconciler uses three distinct ownership mechanisms:

1. a controller-local **Device lease**, keyed by logical Device ID, excludes
   concurrent mutating work by this controller;
2. a controller-local **Run workspace revision lease** serializes one Run's
   append-only evidence chain;
3. a persistent remote **Device ownership marker** under
   `/storage/.coreelec-reconciler/` excludes mutating work by other
   controllers.

Absence of remote ownership is not authority. Only successful atomic,
exclusive creation grants it. Existing, malformed, symlinked, nonregular, or
otherwise unverifiable Run Infrastructure blocks mutation. No time, PID,
hostname, heartbeat, or local-only observation permits takeover.

Before any managed-state mutation, the Reconciler durably stores:

- the execution Run workspace and initial revision;
- remote ownership bound to Device, Run, workspace, Plan, Device binding, and
  boot identity;
- a complete controller-side, content-addressed before-state attachment;
- a verified complete preparation manifest; and
- a mutation-intent revision for the exact state-changing primitive.

After the primitive, it append-revises the ordered mutation trace and any
ambiguity. Intent without a durable outcome is ambiguous. A lost append
acknowledgement is resolved by reloading and compare-and-append; it never
creates a second history.

Recovery never resumes forward mutation. `resume_verification` may only
observe, assess, resolve ambiguity, finish pending Verification or post-Effect
observation, and route to an already approved rollback. A new forward Change
requires a new Plan and execution Run.

Automatic rollback remains enabled only when the exact Change declared it,
the original approval granted it, complete verified before-state exists, the
evidence chain and Device binding remain valid, and fresh current state equals
an exact known post-image or allowed intermediate produced by this Run. It
never overwrites third-party drift.

Version 1 has no automatic retries, no `Delay` port, no heartbeat authority,
no automatic pruning, and no Effect implementation for the playlist slice.
It retains retry classifications and reserves complete Effect states and
tests without scaffolding unused production handlers.

## 2. Relationship to accepted decisions

This contract refines, but does not replace:

- the accepted CoreELEC Reconciler architecture (tracked integration pending
  on this planning branch);
- ADR 0001's controller-only, on-demand model;
- ADR 0002's domain Resource model;
- ADR 0003's exclusive State Address ownership and verified
  Resource-scoped rollback;
- the [canonical Plan and Run Report contract](2026-09-18-canonical-plan-run-report-schema.md);
- the [core module and Resource Type contracts](2026-09-18-core-module-resource-type-contracts.md);
- the [first managed-file test contract](2026-09-18-first-managed-file-test-contract.md).

The architecture documents are authoritative for product semantics. This
record supplies the previously deferred operational implementation contract.
If older wording suggests automatic transient retries, remote backup
authority, forward recovery, cleanup-driven status, or age-based pruning,
this narrower and later decision controls.

The legacy lifecycle transaction demonstrates useful safety evidence:
complete-before-mutate manifests, verified pre-images, explicit phases,
identity-matched receipts, safe path resolution, retained evidence after
incomplete rollback, and read-only inspection. Its remote-first transaction,
cache-pointer authority, recursive cleanup, and path-shaped public identity
are not carried forward.

## 3. Authority model

### 3.1 Separate scopes

| Mechanism | Scope | Authority | Never means |
|---|---|---|---|
| Device lease | logical Device ID on one controller | same-controller mutating exclusion and local liveness | cross-controller exclusion |
| Run revision lease | one Run workspace | right to compare-and-append that Run's next revision | permission to mutate a Device |
| remote Device marker | logical Device on the Device | cross-controller mutating exclusion | proof that its owning controller is alive |
| helper operation lock | one future long-lived remote helper | helper-process exclusion | Run ownership or stale takeover |

The Device lease and Run revision lease are deliberately not one token. A
read-only planning Run may own its workspace while another invocation inspects
an interrupted Run. Neither may mutate while a Device lease, nonterminal Run,
or remote marker blocks new execution.

### 3.2 Device-scoped nonterminal index

`RunStore` maintains an index from logical Device ID to all nonterminal Runs.
The index is updated transactionally with the revision that changes terminal
membership. Its entries contain only stable IDs, revision/digest, status, and
workspace ID—not filesystem paths.

Before a new Plan is considered executable, planning reads:

- the local Device lease;
- the nonterminal index; and
- the remote Device marker, with present/absent/unknown distinguished.

Any existing nonterminal Run or remote marker makes the Plan blocked for
mutation. Planning may still return a complete read-only Plan with the
blocker. `validate`, `inventory`, and `report` are unaffected. `observe`,
`verify`, and `recover inspect` may read active state but must not alter the
active Run, marker, helper lock, staged objects, or managed state.

Applying the exact saved Plan may recognize its own originating planning Run;
that expected entry does not by itself block creation of the execution Run.
Any other nonterminal Run does. A newly computed Plan receives no such
exception.

### 3.3 Acquisition order

New execution uses this order:

1. validate local inputs and saved Plan binding;
2. acquire the controller-local Device lease atomically;
3. re-read the Device nonterminal index;
4. create the execution workspace, append its first revision, and add it to
   the Device nonterminal index;
5. connect and revalidate Device identity and boot identity;
6. inspect the remote infrastructure root without following symlinks;
7. atomically and exclusively create remote Device ownership;
8. publish the remote marker metadata by generation-checked replacement;
9. begin observation/preparation.

The local workspace therefore exists before remote acquisition. If remote
exclusive creation succeeds but its acknowledgement is lost, the local Run
remains nonterminal and inspection treats ownership as present or unknown,
never absent. An independently created foreign marker still cannot be
imported or stolen in v1.

Recovery acquires the existing Run revision lease, then the Device lease, then
validates that the remote marker still binds to the same Run/workspace/token
digest before any action beyond inspection.

## 4. Local workspace and durability

### 4.1 Filesystem shape

The concrete adapter may choose its controller application-data root, but the
shape beneath it is fixed conceptually:

```text
root/                                      0700
  device-leases/                           0700
    <opaque-device-key>.lease              0600
  device-index/                            0700
    <opaque-device-key>.json               0600
  runs/                                    0700
    <opaque-workspace-id>/                 0700
      identity.json                        0600
      lease                                0600
      head.json                            0600
      revisions/                           0700
        00000001.json                      0600
      attachments/                         0700
        sha256/
          <digest>                         0600
      manifests/                           0700
        preparation.json                   0600
      receipts/                            0700
        <operation-id>.json                0600
      diagnostics/                         0700
```

Names derived from Device ID are fixed-length digests or encoded opaque IDs.
No Device endpoint, username, State Address, managed Device path, or secret
appears in a local filename. Public outcomes expose only `workspace_id`.

`identity.json` binds schema version, Run ID, workspace ID, logical Device ID,
Run kind, originating planning Run, Plan ID/full digest, and creation time.
The full remote ownership token is local-only, stored mode `0600`, and never
enters canonical Plan/Run documents, progress, logs, or remote files.

### 4.2 Safe local I/O

Every local operation:

- validates each path component and rejects symlinks/non-directories;
- uses no-follow/open-relative behavior where the platform supports it;
- creates directories `0700` and files `0600`;
- writes a same-directory temporary file;
- flushes file bytes and metadata;
- uses `F_FULLFSYNC` on macOS where supported and otherwise `fsync`;
- atomically replaces the destination;
- fsyncs the parent directory;
- treats inability to provide required durability as a blocker before Device
  mutation.

Attachments are immutable and content-addressed. Writing an existing digest
must byte-verify it; mismatch is corruption. Revision files are immutable
after publication.

### 4.3 Revision chain

One workspace exists per Run. Revisions begin at 1 and obey:

- `revision == previous.revision + 1`;
- `previous_revision_digest == previous.current_digest`;
- `current_digest` is the digest of canonical revision bytes with only
  `current_digest` omitted;
- Run ID, workspace ID, and immutable identity bindings never change;
- exactly one head exists;
- compare-and-append succeeds only for the current lease token, expected
  revision, and expected digest;
- a terminal canonical revision is never rewritten.

Append protocol:

1. encode and validate the proposed canonical revision;
2. durably publish its immutable revision file;
3. durably replace `head.json`;
4. transactionally update terminal membership in the Device index;
5. return acknowledgement.

If acknowledgement is lost, the caller reloads head. Matching revision bytes
mean success; an unchanged head permits the same append; a different valid
successor is a compare conflict. The caller never forks, renumbers, or writes
an alternate branch.

Canonical terminal truth and operational cleanup are separate. Cleanup
receipts may advance after a terminal revision without changing canonical
status.

## 5. Remote Run Infrastructure

### 5.1 Root and object policy

The fixed root is:

```text
/storage/.coreelec-reconciler/
```

It is Run Infrastructure, never Managed State, never a State Address, and
never canonical Plan/Run path data. The root and child directories are mode
`0700`; files are `0600`. Every component is validated with lstat-like,
no-follow semantics. A symlink, non-directory root/component, unexpected
hard-link condition where detectable, malformed ownership object, or
unreadable infrastructure blocks mutation.

Conceptual layout:

```text
/storage/.coreelec-reconciler/
  devices/
    <opaque-device-key>/
      ownership/                exclusive directory
        marker.json
  runs/
    <opaque-run-key>/
      stage/
      helpers/
      receipts/
```

Only exact manifest-owned leaf paths may be changed or deleted. Wildcards,
recursive root deletion, path discovery followed by deletion, and
operator-supplied remote paths are forbidden.

### 5.2 Exclusive acquisition and marker

The `ownership/` directory is acquired with a single atomic exclusive
directory/create operation. A preflight absence result does not grant
authority. Successful exclusive creation does.

The marker contains no full token. It includes:

```json
{
  "binding_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "boot_id": "opaque-observed-boot-id",
  "device_id": "living-room-tv",
  "generation": 3,
  "manifest_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "phase": "prepared",
  "plan_full_digest": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "plan_id": "019950f8-4c00-7000-8000-000000000101",
  "run_id": "019950f8-4c00-7000-8000-000000000501",
  "schema_version": 1,
  "token_digest": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "updated_at": "2026-09-19T01:30:00Z",
  "workspace_id": "workspace:019950f8-4c00-7000-8000-000000000501"
}
```

`device_id` is logical identity, not an endpoint. `binding_digest` covers the
accepted Device binding, including pinned host key and platform identity.
Timestamps are diagnostic only.

Marker update is compare-and-swap over token digest, current generation,
current marker digest, and expected phase. The replacement is written
privately, durably where the Device filesystem supports it, then atomically
renamed. The generation increments by one. A mismatch or unverifiable result
blocks.

Existing ownership always blocks a new mutating Run. A foreign marker may be
inspected but never deleted or modified. V1 cannot import another controller's
workspace and cannot recover a foreign marker; it requires the original
workspace/controller or a separately designed future import procedure.

### 5.3 Remote operation helper lock

The schema reserves a helper operation lock only for a command/helper that can
outlive its client channel. It is acquired atomically and binds:

- Run and operation ID;
- operation token digest;
- Device boot ID;
- helper PID;
- process start identity from the Device, not PID alone;
- helper content digest and expected role.

It may be cleared only when the process is definitively absent or the boot ID
changed. Unknown process state blocks. The SFTP-only first slice creates no
persistent helper and therefore creates no helper lock.

## 6. Preparation and authoritative rollback data

Controller-side content-addressed attachments are the authoritative rollback
source. A Device-side stage or backup is only a transient mutation aid.

For a managed file, the before-state attachment records, through closed
versioned codecs:

- `absent`, or exact bytes;
- entry kind;
- exact managed mode;
- content digest and size;
- logical State Address and normalized managed Device path binding;
- logical Device ID and binding digest;
- Resource/Change/Run IDs;
- codec and attachment schema versions.

The adapter byte-verifies the attachment after durable publication. The
preparation manifest then references every attachment, desired post-image,
allowed intermediate state, staged object, and cleanup object by digest and
exact binding.

Preparation becomes rollback-capable only after:

1. complete fresh before-state observation;
2. durable attachment publication and reread verification;
3. Device-side stage publication, if needed;
4. immediate precondition recheck;
5. durable complete preparation manifest;
6. a revision that records the manifest as complete; and
7. a generation-checked remote marker update to `prepared`.

Incomplete preparation never claims rollback capability. The Plan declares
rollback capability only when the Resource Type can capture the complete
before-state required by this contract.

## 7. Write-ahead mutation protocol

Every state-changing primitive—stage write when it affects retained remote
infrastructure, chmod, atomic replace, remove, restore, Effect execute, or
manifest-owned cleanup—has a stable operation ID.

Before issuing it, execution append-revises a `MutationIntent` containing:

- operation ID and kind;
- Run/Resource/Change binding;
- exact logical address and safe managed Device path where schema-approved;
- pre-image, expected post-image, and allowed-intermediate digests;
- preparation-manifest digest;
- expected remote marker generation/digest;
- attempt number, which is always 1 in v1.

Only after that revision is durable may the primitive begin. Afterwards,
execution records its typed receipt and ordered `MutationTrace`, then
append-revises. `applied`, `definitely_not_applied`, and `ambiguous` retain
their issue-42 meanings.

Intent with no durable outcome is treated exactly as `ambiguous`. If the
Device may have changed but the outcome cannot be durably recorded, execution
stops. It uses the last durable revision plus a sanitized stderr fallback to
expose `interrupted` or `failed_recovery_required`; it never continues on
in-memory knowledge.

V1 performs no automatic retry of observation, download, mutation, Effect,
rollback, marker update, or cleanup. Reports retain the accepted
`retry_classification` vocabulary for operator and future policy. Ambiguity is
resolved by observation, never by retry. Adding retry later requires a
separate decision, evidence, attempt limits, idempotency proof, and an
injected delay seam.

## 8. Conditional automatic rollback

Rollback is allowed only when all conditions hold:

- the original Plan/Change declared rollback capability;
- the original approval granted the rollback impact scope;
- the workspace/revision chain and preparation manifest are valid;
- every required attachment exists and matches its digest/codec/binding;
- Device identity, pinned host key, platform binding, and applicable boot
  constraints match;
- no live helper can still mutate the subject;
- fresh complete current state is available; and
- current state equals the exact known post-image or an explicitly enumerated
  intermediate produced by this Run.

If current state equals the before-state, rollback performs no mutation and
freshly verifies `restored_or_unchanged`. If it equals neither before-state
nor an allowed Run-produced state, rollback blocks to avoid overwriting
third-party drift.

For future multi-Resource support, rollback follows reverse dependency order.
Each restore primitive receives its own durable intent and ordered trace,
followed by fresh rollback Verification against the before-state contract.
The original failure remains authoritative and visible even after verified
restoration.

## 9. Workspace and revision state machines

### 9.1 Workspace state

```text
planning
  -> blocked | noop | awaiting_approval

awaiting_approval
  -> ready

ready
  -> ownership_acquired
  -> interrupted

ownership_acquired
  -> preparing
  -> interrupted

preparing
  -> prepared
  -> failed_known_unchanged
  -> interrupted

prepared
  -> mutating
  -> interrupted

mutating
  -> verifying
  -> interrupted

verifying
  -> effect_barrier
  -> rolling_back
  -> terminal
  -> interrupted

effect_barrier
  -> rolling_back
  -> terminal
  -> interrupted

rolling_back
  -> rollback_verifying
  -> interrupted

rollback_verifying
  -> terminal
  -> interrupted

interrupted
  -> inspecting
  -> verifying
  -> rolling_back
  -> terminal

terminal
  -> cleanup_pending
  -> cleanup_complete
```

`cleanup_pending` and `cleanup_complete` are operational states, not new
canonical Run statuses. No transition leaves terminal canonical truth.

### 9.2 Exact invariants

- One workspace belongs to exactly one Run.
- Planning and execution of a saved Plan are different Runs/workspaces.
- A workspace has one linear revision chain and at most one terminal
  canonical revision.
- Mutation is impossible before local/remote ownership, complete preparation,
  and durable intent.
- An Effect is impossible before contributor preverification and durable
  Effect intent.
- `converged` requires final post-Effect observations where applicable.
- Unknown final state cannot permit independent continuation or convergence.
- A marker may be released only after terminal or abandonment truth is
  durable and required cleanup receipts are durable.
- Cleanup failure cannot change canonical convergence/failure status.

## 10. Inspection and recovery action computation

### 10.1 Stable inspection snapshot

`inspect` is nonmutating. It:

1. reads remote marker generation/digest;
2. validates the complete local revision chain, head, index entry, workspace
   identity, codecs, and every attachment digest;
3. reports local Device/revision lease state and diagnostic PID metadata;
4. validates remote root/marker/helper lock and manifest-owned objects;
5. rechecks Device binding and boot identity when safely reachable;
6. performs fresh Resource observations when safe;
7. rereads marker generation/digest.

If the two marker reads differ, the snapshot is unstable and allowed actions
are conservatively recomputed as inspect-only. Transport failure is `unknown`,
never `absent`. Every fact is `present`, `absent`, or `unknown` with typed
evidence.

Allowed actions are a pure deterministic function of the inspection evidence.
Presentation may show authorized local/remote operational paths, but canonical
automation fields retain only opaque IDs and approved logical/safe managed
paths.

### 10.2 Actions

| Action | Allowed when | Behavior |
|---|---|---|
| `inspect` | enough identity exists to avoid probing an arbitrary Device/path | read-only stable snapshot |
| `resume_verification` | valid chain/binding, no live helper, no unperformed forward work required | observe/assess, resolve ambiguity, finish Verification/post-Effect observation, optionally route to approved rollback |
| `rollback` | all section 8 conditions hold | conditional reverse restoration and fresh rollback Verification |
| normal `finalize` | no mutation remains possible and final state is fully known, or terminal truth is already durable | preserve truth; clean exact manifest-owned objects with receipts |
| recovery abandon/finalize | explicit recovery approval and safe binding sufficient to release ownership | append abandonment receipt and terminal `failed_recovery_required`, quarantine useful evidence, then release marker |

Plan expiry does not block observation, ambiguity resolution, or a rollback
already approved by the original exact Plan. It blocks new forward execution.

`resume_verification` never finishes an interrupted write/chmod/replace,
reruns an Effect, or starts an unperformed Change. If known state is divergent,
it may route to rollback; otherwise it records recovery-required truth.

Normal `finalize` never claims Convergence or erases unknown state. It cannot
delete the only rollback evidence while managed state is unknown.

A corrupt workspace, revision, manifest, codec, or attachment permits
`inspect` and an explicitly approved finalize-as-recovery-required/abandon
only. It never permits resume or rollback.

Before any action beyond inspect, Device binding is rechecked. Mismatch blocks
resume and rollback. Only the narrow safe abandonment/finalization path may
proceed, and only when it can identify and release this Run's ownership
without touching managed state or foreign infrastructure.

## 11. Effects

An Effect handler descriptor declares:

- stable Effect code;
- required capabilities;
- expected-disconnect policy;
- a positively observable readiness condition;
- contributing Changes and affected Resources;
- whether restored state requires a distinct `restore_effect`;
- exact post-Effect observation set.

The barrier state machine is:

```text
contributor_preverification
  -> effect_intent
  -> effect_execution
  -> readiness_observation
  -> post_effect_resource_observations
  -> complete | rollback_route | recovery_required
```

Effect intent is durable before execute. A command receipt never establishes
Effect success. Expected disconnect changes failure classification only; it
does not establish success. Readiness requires positive observation, followed
by fresh observation of every affected Resource. Pre-Effect observations are
never final.

Recovery never reruns an interrupted Effect. It reconnects and observes the
readiness condition and post-Effect Resources. If success/failure cannot be
proved, the Run requires recovery.

The normal failure rollback path may execute the same underlying disruptive
mechanism once more only as a distinct, preplanned `restore_effect`, after
reverse rollback, when required to activate restored state. This is not a
retry. It requires original approval, durable intent, and complete
post-Effect re-observation. Failure becomes `failed_recovery_required`.

The playlist first slice declares no Effect and implements no Effect handler.
Its domain/state/test fixtures reserve the transition vocabulary so a later
Effect cannot bypass these invariants.

## 12. Partial continuation

Under `continue_safe_independent`, execution may continue unrelated work only
after the failed Resource is:

- freshly verified unchanged;
- freshly verified restored; or
- fully observed as a known partial state.

Dependents are skipped. Work cannot cross a failed barrier. Disruptive work
does not begin after another Resource fails unless the accepted Plan proves
the barrier independent and all contributor states are known. Unknown state,
transport failure, ownership/lease loss, identity mismatch, helper uncertainty,
or infrastructure corruption stops the Run. `fail_fast` promotes every
failure to Run scope.

## 13. Finalization, cleanup, and retention

Canonical terminal truth is durable before cleanup begins. Cleanup:

- changes no canonical status;
- deletes only exact manifest-owned temporary objects;
- records intent and identity-bound receipts;
- re-inspects after ambiguous remote deletion;
- reports every leftover explicitly;
- never uses recursive or wildcard deletion.

Sensitive temporary material is prioritized for deletion, but not by
destroying evidence required to prevent unsafe rollback or establish final
truth. The implementation must classify attachment/diagnostic sensitivity and
state which retained artifacts are necessary.

V1 automatically prunes nothing. Workspaces, attachments, revisions, remote
markers, and retained evidence persist until an explicit prune/finalize
operation. Active, interrupted, unsealed, failed, recovery-required, corrupt,
or ownership-bearing Runs are never prunable. A future retention policy
requires a separate decision and tests.

An explicit abandonment:

1. requires a specific recovery approval bound to Run/workspace/Device;
2. appends a durable abandonment receipt;
3. appends terminal `failed_recovery_required`;
4. quarantines useful local backup/evidence rather than deleting it;
5. records remote cleanup/release intent and receipt; and
6. releases this Run's marker only after the durable local receipt.

Age alone never authorizes abandonment, marker removal, or evidence deletion.

## 14. Crash and concurrency matrix

| Point | Controller crash / SSH disconnect | Device reboot | Concurrent controller | Required recovery truth |
|---|---|---|---|---|
| before remote marker | no Device authority acquired | none | exclusive acquire decides winner | local incomplete Run may finalize known-unchanged |
| after local workspace/index, before marker | local nonterminal blocks this controller | none | remote exclusive acquisition still decides winner | finalize known-unchanged or continue exact Run |
| after marker, before preparation | marker and local Run remain blocking | marker persists or becomes unknown | blocked | inspect, then finalize known-unchanged or abandon |
| during incomplete preparation | no rollback promise | stage may remain | blocked | inspect; clean exact stage only after known-unchanged proof |
| after complete prep, before intent | rollback data valid; no managed mutation | rebind before action | blocked | finalize known-unchanged or approved rollback no-op |
| after durable intent, before request | outcome ambiguous by contract | reobserve | blocked | resume Verification/observation; never issue forward primitive |
| after request, before outcome | ambiguous | reobserve boot/state | blocked | resolve by fresh complete observation |
| after outcome, before revision | last durable intent makes it ambiguous | reobserve | blocked | reload, inspect, append observed truth |
| revision append acknowledgement lost | reload/CAS; never branch | unchanged | blocked | accept matching durable successor or retry same append |
| before Verification | mutation known/ambiguous, convergence unknown | reobserve | blocked | `resume_verification` |
| during Verification | read unknown, not absent | reobserve | blocked | repeat observation only |
| Effect intent/execution disconnect | never rerun Effect | readiness/boot observation | blocked | observe readiness and affected Resources |
| rollback intent/request disconnect | conditional state comparison first | rebind and observe | blocked | never blindly repeat restore |
| terminal revision before cleanup | terminal truth immutable | cleanup may remain | new mutation blocked until marker release | cleanup receipts only |
| ambiguous cleanup delete | re-inspect exact object | re-inspect | marker still blocks | present/absent/unknown retained |
| local lease owner process dies | kernel/advisory lock releases | n/a | remote marker still blocks others | PID metadata alone has no authority |

Local kernel/advisory locking is the same-controller liveness authority. PID,
hostname, start time, and timestamps are diagnostic only. A local lease file
that exists without a live held lock remains evidence to inspect; it is not
proof of a live owner and is never removed merely by age.

## 15. Planned Python refinements to issue 41

These sketches are normative shape refinements. Concrete module filenames may
vary only while preserving the seams and invariants.

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DeviceId:
    value: str


@dataclass(frozen=True, slots=True)
class RunId:
    value: str


@dataclass(frozen=True, slots=True)
class WorkspaceId:
    value: str


@dataclass(frozen=True, slots=True)
class DeviceLease:
    device_id: DeviceId
    token: str


@dataclass(frozen=True, slots=True)
class RevisionLease:
    run_id: RunId
    workspace_id: WorkspaceId
    token: str


@dataclass(frozen=True, slots=True)
class NonterminalRun:
    run_id: RunId
    workspace_id: WorkspaceId
    revision: int
    revision_digest: str
    status: str


@dataclass(frozen=True, slots=True)
class StoredRevision:
    revision: int
    digest: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    digest: str
    kind: str
    codec: str


class RunStore(Protocol):
    def acquire_device(self, device_id: DeviceId) -> DeviceLease: ...
    def list_nonterminal(self, device_id: DeviceId) -> tuple[NonterminalRun, ...]: ...
    def create_run(
        self,
        device_lease: DeviceLease,
        run_id: RunId,
        device_id: DeviceId,
    ) -> tuple[RevisionLease, WorkspaceId]: ...
    def acquire_run(self, run_id: RunId) -> RevisionLease: ...
    def load(self, run_id: RunId) -> StoredRevision: ...
    def compare_and_append(
        self,
        lease: RevisionLease,
        expected_revision: int,
        expected_digest: str,
        payload: bytes,
    ) -> StoredRevision: ...
    def attach(
        self,
        lease: RevisionLease,
        kind: str,
        codec: str,
        payload: bytes,
    ) -> AttachmentRef: ...
    def release_run(self, lease: RevisionLease) -> None: ...
    def release_device(self, lease: DeviceLease) -> None: ...
```

`AttachmentRef` remains the closed digest-bearing value accepted in issue 41.
The Device lease is required to create an execution Run, but planning may
create a local-only workspace through a separate internal path that cannot
obtain remote mutation authority.

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class MutationDisposition(StrEnum):
    APPLIED = "applied"
    DEFINITELY_NOT_APPLIED = "definitely_not_applied"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class MutationReceipt:
    operation_id: str
    disposition: MutationDisposition


class Presence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RemoteOwnershipIdentity:
    device_id: DeviceId
    run_id: RunId
    workspace_id: WorkspaceId
    plan_id: str
    plan_full_digest: str
    binding_digest: str
    boot_id: str


@dataclass(frozen=True, slots=True)
class RemoteOwnershipSnapshot:
    presence: Presence
    generation: int | None
    marker_digest: str | None
    token_digest: str | None
    identity: RemoteOwnershipIdentity | None
    phase: str | None
    manifest_digest: str | None


@dataclass(frozen=True, slots=True)
class RemoteOwnership:
    identity: RemoteOwnershipIdentity
    token: str
    generation: int
    marker_digest: str


class RemoteRunOwnership(Protocol):
    def inspect(self, device_id: DeviceId) -> RemoteOwnershipSnapshot: ...
    def acquire_exclusive(
        self,
        identity: RemoteOwnershipIdentity,
        token_digest: str,
    ) -> RemoteOwnership: ...
    def compare_and_update(
        self,
        ownership: RemoteOwnership,
        expected_phase: str,
        next_phase: str,
        manifest_digest: str | None,
    ) -> RemoteOwnership: ...
    def release(
        self,
        ownership: RemoteOwnership,
        abandonment_receipt_digest: str | None,
    ) -> MutationReceipt: ...
```

The full token appears only in `RemoteOwnership` held in local sensitive
storage. `release` is permitted only after the application proves the
appropriate durable terminal/abandonment receipt.

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class MutationTrace:
    receipts: tuple[MutationReceipt, ...]


class PrimitiveKind(StrEnum):
    STAGE_WRITE = "stage_write"
    CHMOD = "chmod"
    ATOMIC_REPLACE = "atomic_replace"
    REMOVE = "remove"
    RESTORE = "restore"
    EFFECT = "effect"
    RESTORE_EFFECT = "restore_effect"
    CLEANUP = "cleanup"


@dataclass(frozen=True, slots=True)
class MutationIntent:
    operation_id: str
    primitive: PrimitiveKind
    resource_id: str | None
    change_id: str | None
    preparation_manifest_digest: str
    expected_before_digest: str
    expected_after_digest: str
    allowed_intermediate_digests: tuple[str, ...]
    marker_generation: int
    marker_digest: str
    attempt: int


@dataclass(frozen=True, slots=True)
class MutationOutcomeRecord:
    intent_operation_id: str
    trace: MutationTrace
    observed_state_digest: str | None
```

`attempt` is fixed to `1` in v1. An intent without a matching durable outcome
is interpreted as ambiguous.

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FactState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class RecoveryActionCode(StrEnum):
    INSPECT = "inspect"
    RESUME_VERIFICATION = "resume_verification"
    ROLLBACK = "rollback"
    FINALIZE = "finalize"


@dataclass(frozen=True, slots=True)
class RecoveryFact:
    code: str
    state: FactState
    evidence_digest: str | None


@dataclass(frozen=True, slots=True)
class RecoveryEvidence:
    run_id: RunId
    workspace_id: WorkspaceId
    stable_snapshot: bool
    binding_matches: bool | None
    chain_valid: bool
    attachments_valid: bool
    preparation_complete: bool
    live_helper: bool | None
    forward_work_unperformed: bool
    current_state_digest: str | None
    before_state_digest: str | None
    known_run_state_digests: tuple[str, ...]
    facts: tuple[RecoveryFact, ...]


@dataclass(frozen=True, slots=True)
class AllowedRecoveryAction:
    code: RecoveryActionCode
    allowed: bool
    reason_code: str


def compute_recovery_actions(
    evidence: RecoveryEvidence,
) -> tuple[AllowedRecoveryAction, ...]:
    ...
```

`compute_recovery_actions` is pure and total over validated evidence. It
performs no I/O and does not accept wall-clock age.

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class EffectCode:
    value: str


class ExpectedDisconnectPolicy(StrEnum):
    NEVER = "never"
    ALLOWED = "allowed"
    REQUIRED = "required"


class EffectPhase(StrEnum):
    CONTRIBUTOR_PREVERIFICATION = "contributor_preverification"
    INTENT_DURABLE = "intent_durable"
    EXECUTING = "executing"
    READINESS_PENDING = "readiness_pending"
    POST_EFFECT_OBSERVATION = "post_effect_observation"
    COMPLETE = "complete"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class ReadinessCondition:
    code: str
    positive_observation_kind: str


@dataclass(frozen=True, slots=True)
class EffectHandlerDescriptor:
    code: EffectCode
    required_capabilities: frozenset[str]
    expected_disconnect: ExpectedDisconnectPolicy
    readiness: ReadinessCondition
    post_effect_resource_ids: tuple[str, ...]
    restore_effect_code: EffectCode | None
```

The first slice persists/tests these values where needed by the closed report
model but does not construct a production Effect registry or handler.

## 16. Required first-slice implementation boundary

Implement in the first managed-file slice:

- filesystem `RunStore` with Device index, Device lease, Run revision lease,
  opaque workspace, attachments, linear compare-and-append, safe durability,
  and terminal/cleanup separation;
- remote infrastructure validation, exclusive Device ownership, marker CAS,
  and exact manifest-owned cleanup;
- one-Resource complete preparation and controller-side rollback attachment;
- durable intent and outcome/ambiguity revisions for each mutation primitive;
- stable inspection and pure allowed-action computation;
- no-forward-work `resume_verification`;
- strict conditional rollback and rollback Verification;
- normal finalize and explicitly approved abandonment/finalize;
- interruption tests across every durable boundary.

Defer:

- cross-controller workspace import or marker takeover;
- automatic retry, scheduler, delay seam, or heartbeat;
- Effects/reboot and production Effect handlers;
- multi-Resource rollback execution, while preserving reverse-order semantics;
- scheduled/automatic pruning;
- persistent helper implementation until a command can outlive its channel.

Do not scaffold unused production handlers or generic recovery plugin systems.

## 17. Exact refinement of issue 42 tests

The issue-42 matrices remain mandatory and gain these exact cases:

1. Device lease excludes a second mutating Run on the same controller while a
   separate Run revision lease remains independently testable.
2. Any local nonterminal index entry blocks a new executable Plan.
3. An existing remote marker, including foreign/malformed/symlink/nonregular,
   blocks; absent-then-exclusive-create races have one winner.
4. Marker CAS rejects wrong token digest, generation, marker digest, phase,
   Device, Run, workspace, Plan, binding, or boot identity.
5. Every mutation has durable intent first; intent without outcome recovers as
   ambiguous.
6. Append acknowledgement loss reloads one linear successor and never forks.
7. Incomplete preparation cannot advertise or perform rollback.
8. Attachment byte/kind/mode/codec/binding corruption blocks rollback.
9. Recovery never completes a pending forward primitive or starts a pending
   Change.
10. Conditional rollback handles exact post-image, each allowed intermediate,
    already-before-state, third-party drift, unreadable state, and binding
    mismatch.
11. Stable inspection distinguishes absent from unknown and rejects a marker
    generation change during inspection.
12. Corrupt workspaces expose inspect plus approved abandon/finalize only.
13. Plan expiry permits observation and preapproved rollback but no new
    forward mutation.
14. Terminal truth precedes cleanup; cleanup failure/ambiguity leaves
    canonical status byte-identical and reports leftovers.
15. No automatic retry, sleep, Delay port, heartbeat authority, or automatic
    prune is observed.
16. Effect state fixtures prove durable intent, expected-disconnect
    non-success, no recovery rerun, readiness, post-Effect observation, and
    distinct approved `restore_effect`.
17. Crash cases cover marker, preparation, intent, request/outcome,
    Verification, append acknowledgement, Effect, rollback, and cleanup
    boundaries for controller crash, SSH disconnect, Device reboot, and a
    concurrent controller.

These tests assert the `Reconciler.execute` interface, canonical revisions,
RunStore public behavior, computed allowed actions, and independent Device
state. They do not assert private filesystem paths or orchestration call order.

## 18. Relationship to issue 44 pilot

[Issue 44](https://github.com/jbruns/tv/issues/44) must turn this contract into
an operator-safe disposable-pilot procedure. Its reset and acceptance steps
must:

- verify `/storage/.coreelec-reconciler/` root safety before the first live
  mutation;
- confirm Device identity, pinned host key, boot identity, and atomic
  exclusive-create/rename behavior;
- begin with no unexplained marker and never delete one merely to make the
  pilot proceed;
- collect every local revision, attachment digest, remote marker generation,
  preparation manifest, intent/trace, Verification, rollback, and cleanup
  receipt;
- exercise interruption/recovery at pilot-approved safe points;
- prove the final exact-subtree leak/leftover result;
- preserve evidence by exact source commit/tree digest.

Issue 44 chooses which destructive or acknowledgement-loss injections are
operationally safe. It may not weaken the production adapter contracts,
conditional rollback rules, no-forward-recovery rule, or live convergence,
drift-repair, second-Run no-op, and reset gates already required by issue 42.

## 19. Rejected alternatives

### Local-only locking

Rejected because two controllers can both believe they own a Device. The
remote exclusive marker is the cross-controller authority.

### Time-based stale takeover

Rejected because clocks, pauses, partitions, and long recovery work make age
non-authoritative. There is no automatic steal.

### Heartbeat authority

Rejected because heartbeat loss is indistinguishable from partition or
controller pause. A future heartbeat may be diagnostic, never sole authority.

### Resume forward mutation

Rejected because an interrupted primitive's exact server state may be
ambiguous and a saved Plan may no longer be fresh. Recovery observes,
verifies, or conditionally restores; new forward work replans.

### Unconditional rollback

Rejected because it can overwrite third-party changes. Rollback requires an
exact known Run-produced current state.

### Remote backup authority

Rejected because remote stage/backup can be lost, corrupted, or coupled to the
failure being recovered. The durable controller attachment is authoritative.

### Automatic retry

Rejected in v1 because transport ambiguity and non-idempotent mutation make
blind retries unsafe, and no evidence yet justifies a scheduler or Delay seam.

### Blind Effect rerun

Rejected because a disconnect may follow successful disruption. Recovery
observes readiness and state; only a distinct planned `restore_effect` may run
after rollback.

### Automatic prune

Rejected because age cannot prove evidence is unnecessary or ownership stale.
V1 retention is explicit.

### Cleanup before terminal truth

Rejected because losing evidence can make an otherwise diagnosable Run
unknowable. Terminal truth is durable first.

### Exposing workspace or infrastructure paths

Rejected because paths leak controller/device layout and become accidental
automation contracts. Public recovery identity is opaque.

## 20. Acceptance checklist

This decision is implementation-ready when independent review confirms:

- [ ] the three ownership scopes and acquisition order cannot be conflated;
- [ ] remote absence never grants ownership without exclusive acquisition;
- [ ] local and remote path/permission/durability rules fail closed;
- [ ] the Device nonterminal index and marker block new mutation;
- [ ] preparation and intent are durably ordered before mutation;
- [ ] append acknowledgement loss cannot fork history;
- [ ] rollback authority is controller-side, complete, bound, and conditional;
- [ ] recovery performs no forward mutation and never reruns an Effect;
- [ ] allowed actions are pure consequences of stable evidence;
- [ ] corrupt/foreign/unknown cases reduce authority rather than expanding it;
- [ ] terminal truth precedes cleanup and survives cleanup failure;
- [ ] no retry, delay, heartbeat takeover, import, Effect handler, or prune
      implementation enters the first slice;
- [ ] issue-42 tests and issue-44 pilot responsibilities are explicit;
- [ ] Python and JSON sketches validate and contain no `Any` or pickle;
- [ ] canonical automation fields expose no local workspace or remote
      infrastructure paths.
