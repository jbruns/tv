# Canonical Run evidence and local durability

## Scope

The Python implementation can now represent, validate, persist, reload, and
seal the complete M3 execution and recovery Run vocabulary offline. This
capability does not open a Device session, mutate a Device, deploy software,
or transfer ownership from the shell implementation.

`CoreElecReconcilerRunReport` remains the automation contract. Local workspace
files are private implementation data. A workspace is identified publicly
only by an opaque `workspace:<id>` value; controller paths, Device paths,
ownership tokens, secret values, raw attachments, stack traces, and transport
exception text are forbidden in canonical documents.

## Closed lifecycle vocabulary

The canonical statuses are:

| Status | Terminal | Meaning |
| --- | --- | --- |
| `planning` | no | Observation and Plan construction |
| `blocked` | yes | Planning could not produce executable work |
| `noop` | yes | Freshly observed state needs no Change |
| `awaiting_approval` | no | Exact Plan approval is incomplete |
| `ready` | no | Exact Plan is valid and approved |
| `executing` | no | Acquisition, preparation, mutation, Verification, Effect observation, rollback, or recovery |
| `interrupted` | no | Durable recovery point; invocation ended |
| `converged` | yes | Every required final observation matched |
| `failed_rolled_back` | yes | Failure remains recorded and before-state restoration was verified |
| `failed_partial` | yes | Final Device state is known and non-converged, including known unchanged |
| `failed_recovery_required` | yes | Device state or ownership safety is unknown/unsafe, or the Run was abandoned |

Per-Resource evidence keeps mutation, Verification, rollback, post-Effect
Verification, and final convergence separate. Attempts and failures are
append-only and carry closed phases, outcomes, stop scopes, retry
classifications, safe messages, and resolved evidence references.

### M3.1 execution-evidence schema amendment

Execution evidence schema version 1 is a closed discriminated union. The only
accepted payload kinds are:

- `ManagedFileObservation`;
- `ResourcePreparationCompleted`;
- `ResourcePrimitiveIntent`;
- `RemoteMarkerCheckpoint`;
- `ResourcePrimitiveOutcome`;
- `ResourceExecutionResult`;
- `ResourceVerificationResult`;
- `ResourceRollbackResult`;
- `ResourceSkipResult`;
- `RecoveryVerificationResult`;
- `ResourceCleanupReceipt`;
- `EffectIntent`, `EffectReadinessObservation`, and `EffectOutcome`;
- `AuthorityEvidence`; and
- `RunAbandonmentApproval`.

Each kind has one exact field set, observer code/version, subject kind, and
schema version. `ResourcePrimitiveIntent` is a closed primitive-discriminated
union: state primitives carry exact before/after and marker bindings, cleanup
carries the manifest object and terminal revision binding, and Effects use
their dedicated intent. Effect intent carries its operation ID, exact marker
generation/digest/phase/token tuple, approval and readiness references, and
the complete affected Resource/State Address set. Its immediately following
marker checkpoint must match that tuple. An Effect outcome requires that
checkpoint, fresh positive readiness, and exactly one correctly bound fresh
Observation for every affected Resource.

Unknown kinds, unregistered Resource Types, versions, observers, fields,
primitive combinations, unsafe content, unresolved or forward references,
duplicate IDs/operations, and out-of-order timestamps fail closed. Resource
Type membership comes from the immutable Resource Type registry; adding a
registered type does not require editing the domain evidence codec.

Every Resource-bound record carries `KodiSmartPlaylist`, Resource and Change
IDs, Run/workspace/Device/Plan/full-digest/binding identity, observer identity,
logical sorted State Addresses, attachment references, and attempt `1`.
Abandonment approval is Run/workspace/Device bound and carries a non-empty safe
reason. Attempts represent write-ahead state explicitly: `pending` has a
durable intent reference and no end time or outcome reference; completion
requires both.

The production codec and the independent invariant checker are separate
algorithms at the domain/reporting persistence boundary. They share only
immutable schema constants and domain types, preventing one validator defect
from making the other accept the same malformed record. Execution code can
construct and decode this vocabulary without importing reporting
implementations.

Recovery exposes `inspect`, `resume_verification`, `rollback`, and two
separate `finalize` variants: `normal` and `abandon`. Abandonment always
requires a distinct approval and reason. Allowed actions are computed solely
from stable typed evidence; elapsed time never expands authority.

## Revision and attachment invariants

Each workspace contains one Run and one linear immutable revision chain:

- revision numbers begin at 1 and increase by one;
- revision 1 has a null predecessor;
- every later predecessor digest equals the prior revision digest;
- `current_digest` is SHA-256 over canonical bytes with that field omitted;
- immutable Run, Plan, Device, and workspace bindings do not change;
- terminal truth permits only cleanup-progress successors (write-ahead cleanup
  intent, its exact marker checkpoint, and its receipt) that preserve the
  terminal status and every non-cleanup fact;
- a complete verified chain is returned, never an unchecked head alone.

The workspace identity persists schema and Run kind, producer, Run ID,
workspace ID, Device ID, originating planning Run ID, exact Plan ID and full
digest, creation time, Device binding digest, boot identity, and ownership
token digest. Every loaded or proposed revision must match that complete
projection.

Attachments are immutable and content-addressed. Reads verify bytes, digest,
kind, and codec. The full random ownership token is a private mode-`0600`
object; canonical evidence contains only its SHA-256 digest.

## Local workspace and active Device index

The filesystem store creates its root and directories mode `0700` and files
mode `0600`. It rejects symlink and nonregular objects at trust boundaries.
Publication uses private same-directory writes, file full-sync, atomic
replacement, parent-directory sync, reread verification, and explicit
acknowledgement through the private `LocalDurability` seam.
Reads and durability operations walk directories with open-relative,
no-follow descriptors where supported and reject symlinked or non-directory
parents and symlinked/nonregular final objects.

Device and Run revision leases are independent. The derived Device-active
index contains stable identifiers, revision/digest, status, authority phase,
and opaque workspace ID only. A verified workspace scan must exactly agree
with the cache. Corruption or disagreement fails closed until an explicit
scan/rebuild succeeds.

Compare-and-append uses the held Run lease plus expected revision and digest.
A lost append acknowledgement receives one bounded reconciliation: accept the
matching durable successor only after head, state, and index agree, or resume
the same idempotent publication once when the head is unchanged. An identical
orphan revision file is never success by itself. It never retries Device work
or creates a branch.

## Terminal truth, cleanup, and retention

Canonical terminal status describes Device-state truth. Cleanup state
describes controller/remote Run Infrastructure housekeeping. They are not the
same fact:

- terminal truth is durable before cleanup;
- post-terminal revisions may append only the bound write-ahead
  intent/checkpoint/receipt sequence and monotonic cleanup/authority truth;
  they cannot revise terminal status or prior evidence;
- each preparation manifest declares its required cleanup objects; a complete
  summary requires a matching non-ambiguous receipt proving no leftover for
  every object;
- cleanup failure cannot change `converged` or a terminal failure status;
- the active index is removed only after terminal truth and verified ownership
  release or quarantine are durable;
- sealing requires complete zero-leftover cleanup plus durable release or
  quarantine evidence whose marker/token tuple matches the summary;
- abandonment records `failed_recovery_required` and remains blocking through
  quarantine.

## Session and transport close outcomes

Session/transport teardown is neither managed-Resource cleanup nor Device
authority release. A close result therefore never enters the Run revision
chain and cannot change terminal status, cleanup truth, authority truth, the
active index, or seal eligibility.

`CoreElecReconcilerSessionClose` is a separate canonical, append-only
workspace record. Version 1 binds execution Runs; version 2 additionally binds
the Run document kind and permits observation Runs to state that mutation
authority is `not_applicable`. It binds:

- one UUIDv7 record/idempotency identity and one safe session identity;
- Device, Run, and opaque workspace identity;
- the first immutable terminal revision/digest;
- the terminal head revision/digest and authority state observed at recording;
- the exact seal digest when recorded after sealing, or explicit `null` when
  recorded before sealing;
- an RFC 3339 UTC observation time; and
- `complete`, `failed`, or `unknown` disposition.

`failed` and `unknown` require a closed failure category plus a sanitized safe
code. Raw exceptions, transport text, credentials, and secrets are forbidden.
Repeating the same record identity and values is idempotent. A differing value
for that identity, or a second identity for the same session, conflicts.

RunStore may record close outcomes after terminal truth both before and after
release/seal. Sealed bytes remain immutable. Strict loading verifies canonical
bytes, digest, identity, Run kind, terminal/head/authority binding, and
optional seal binding. Observation close records cannot carry a seal and
cannot imply cleanup or release. Inspection treats a missing or corrupt close
record as `unknown` without invalidating an otherwise verified canonical Run
result.

Session-close records automatically prune nothing. Revisions, attachments,
markers, and evidence are retained until a future explicit retention
procedure is accepted.
Active, interrupted, unsealed, corrupt, ownership-bearing, or
recovery-required Runs are never implicitly removable.

## Canonical observation-only Runs

`CoreElecReconcilerObservationRun` schema version 1 is separate from planning
and execution reports. It never contains a Plan, Change, approval, Desired
State, Verification, convergence, mutation, rollback, cleanup, or write
authority field.

The lifecycle is strictly `ready` to `observing`, then terminal `observed`
when every selected Resource was observed or `observed_partial` when any
selected Resource is unavailable or has an unknown result. A Run cannot move
directly from `ready` to a terminal state, including for a one-Resource scope.
A crash while work remains leaves the Run durably `observing`.

The immutable scope binds the Run, workspace, Device, creation time, ordered
selected Resources, Resource Types, State Addresses, dependency order, and
configuration, Profile, artifact-set, capability, and selector-input digests.
Each Resource also binds the exact registered observation payload kind,
version, and policy digest. Dependencies must reference earlier selected
Resources; duplicates, cycles, dangling references, and unstable ordering are
rejected.

Each successor adds at most one checkpoint in scope order. A checkpoint binds
the Resource, Resource Type, State Addresses, observer identity, timestamp,
closed Resource-Type-owned payload, disposition, and any content-addressed raw
attachment. A completed prefix is immutable and is not observed again after
restart. Terminal Runs contain the complete prefix and reject all successors.
The independent persistence oracle separately checks envelopes, payloads,
ordering, references, digests, and transitions. Resource-Type observation
oracles implement their own algorithms rather than calling production decoder
helpers. The persistence family requires both production decoding and oracle
acceptance.

Observation workspaces use Device and Run leases plus the existing CAS and
durability machinery, but never enter the active mutation index and never
persist an ownership token. Session-close schema version 2 can bind their
terminal result using `authority_state: not_applicable`; this does not assert
Resource cleanup, authority release, or sealing.

RunStore receives document-family operations through its registry seam and
stores canonical revisions opaquely. The family owns chain, transition,
identity, terminality, attachment, and session-close interpretation. A bounded
retry reconciles independently inspected revision, head, state, and
no-active-index facts after acknowledgement loss; only the byte-identical
candidate may complete publication.

## Standalone read-only observation

The observation document codec and RunStore API are the persistence seam for a
later standalone observation workflow. They create, resume, and inspect
canonical observation Runs without creating or saving a `CanonicalPlan`,
acquiring remote ownership, or receiving preparation, mutation, rollback,
cleanup, Verification, or Effect capabilities.

The codec records measured presence, readability, entry type, safety,
availability, unknown/unavailable failure code, content digest, mode, and raw
attachment reference as applicable. It does not assess Desired State or
translate an Observation into an execution result. Read-only workspaces never
enter the active Device mutation index.

## Durable close uncertainty

`DurableSessionClose` owns the post-result teardown seam. It accepts the
already-produced canonical Run report and recovery guidance, attempts close,
and records the outcome through `RunStore.record_session_close`. Its returned
value always preserves that exact report and guidance; close failure cannot
rewrite terminal Run truth.

Timeout, transport, and local-runtime exceptions are reduced to closed
categories and safe codes. Exception messages are never persisted. Explicit
`failed` and `unknown` outcomes receive equally bounded metadata. The same
record/session identity is idempotent and does not repeat teardown. The module
works with a still-held revision lease before release or can reacquire the Run
lease after release and sealing. Missing, corrupt, conflicting, or failed
recording is reported conservatively as close `unknown`, while the canonical
Run result remains available through both close and inspection.

## Validation fixtures

Committed positive fixtures cover ready execution, converged execution,
interrupted recovery, and a complete Resource/Effect execution sequence;
parameterized codec tests cover every accepted execution-evidence v1 kind.
The observation fixture covers a two-Resource dependency-ordered partial Run
with one readable raw attachment and one unavailable result.
Negative fixtures independently exercise digest, identity, terminal-time,
cleanup-order, index-release, Resource-convergence, abandonment-approval,
workspace-opacity, unknown evidence kinds/versions, and arbitrary evidence
fields. The amendment changes no prior canonical fixture bytes or digests; it
only closes validation for previously unspecified non-empty execution
evidence.
