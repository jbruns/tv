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
- terminal truth has no canonical successor;
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
- cleanup failure cannot change `converged` or a terminal failure status;
- the active index is removed only after terminal truth and verified ownership
  release or quarantine are durable;
- abandonment records `failed_recovery_required` and remains blocking through
  quarantine.

Version 1 automatically prunes nothing. Revisions, attachments, markers, and
evidence are retained until a future explicit retention procedure is accepted.
Active, interrupted, unsealed, corrupt, ownership-bearing, or
recovery-required Runs are never implicitly removable.

## Validation fixtures

Committed positive fixtures cover ready execution, converged execution, and
interrupted recovery. Negative fixtures independently exercise digest,
identity, terminal-time, cleanup-order, index-release, Resource-convergence,
abandonment-approval, and workspace-opacity invariants. M2 Plan and planning
Run fixtures remain byte-for-byte unchanged.
