# Managed-file execution and recovery

M3.3 adds a private execution module behind the overloaded
`Reconciler.execute(command)` boundary. Application composition supplies typed
workflow dependencies; `inventory` and `action` remain explicit
`not_implemented` results, and `provision` remains CLI-only syntax for
`reconcile`.

Modeled application outcomes carry the authoritative `CanonicalRunReport`
rather than asking presentation code to reconstruct a document from IDs and
status strings. Reconcile retains both its planning Run and Plan and, when
execution occurs, its execution Run; this preserves the `awaiting_approval`
planning document. Recovery inspection returns the stable `RecoveryEvidence`
internally but exposes only the current Run report, cleanup completion, and the
complete computed `AllowedRecoveryAction` tuple. Mutating recovery returns the
resulting current terminal Run report. Cleanup completion remains separate
metadata, so cleanup uncertainty cannot change Device convergence or failure
truth.

Planning results are classified at the application boundary into
report-bearing canonical outcomes or typed pre-report failures. Reconcile uses
a typed approval resolution containing required, granted, and missing scopes.
Insufficient approval returns the canonical Plan and `awaiting_approval`
planning Run without starting execution, allowing presentation to render a
copyable command without duplicating approval logic. Inconsistent or
mismatched canonical documents fail at the application boundary instead of
being fabricated by presentation code.

Managed-file execution uses least-authority fake capabilities. Every
state-changing primitive follows the same durable boundary: persist its typed
intent, reread and match the remote marker, invoke the primitive once, freshly
observe the affected managed or staged address, and persist the cumulative
ordered trace before scheduling another primitive. Receipts retain
`applied`, `definitely_not_applied`, and `ambiguous` truth. Receipts never
claim convergence. Playlist Verification freshly observes and invokes the
same pure semantic assessment used by planning.

Rollback is conditional. It requires approval, verified preparation, and a
fresh state equal to the before-state, desired post-image, or an enumerated
Run-produced intermediate. Third-party state is never overwritten. Recovery
can inspect, resume observation and Verification, run an already-authorized
rollback, finalize known truth, or perform separately approved, reasoned
abandonment. The concrete recovery coordinator reloads the verified Run chain,
recomputes allowed actions from a stable double-read inspection, and uses the
bound M3.2 authority coordinator for release or quarantine. It never resumes
forward work. An already-restored before-state produces an empty rollback
trace and is freshly verified without another Device mutation.

Canonical terminal Device-state truth is persisted before cleanup. Cleanup
and its receipt are then persisted as a separate release prerequisite. Only
definitively complete cleanup permits authority release, and the release-pending
checkpoint and removal remain bound to the canonical terminal or abandonment
revision digest—not the cleanup receipt digest. Cleanup failure remains visible
but cannot rewrite convergence or failure truth.
Progress events are deterministic presentation data; a failing sink adds only
a sanitized presentation diagnostic and cannot affect canonical evidence,
scheduling, or fake Device state.

Execution follows deterministic Plan order. A known Resource failure skips
its dependents while safe independent, non-disruptive Changes continue.
Ambiguity and disruptive failure stop further mutation.

## Restart-safe production contracts

`PlanStore` durably stores the exact canonical Plan beside its originating
planning Run. Every load reruns the reporting decoders and verifies the Plan
ID, full and semantic digests, Device and originating-Run binding, approval
requirements, and input/source digests. A partial, changed, noncanonical, or
unsafe saved entry fails closed.

`RunStoreExecutionPersistence` is the concrete `ExecutionJournal`,
`RecoveryPersistence`, and bound `AttachmentStore` adapter. Preparation
documents are content-addressed attachments referenced by canonical Run
evidence. Intent, primitive outcome, Verification, rollback, and terminal
transitions append validated canonical revisions with RunStore CAS ordering.
Cleanup receipts are operational evidence written only after terminal truth;
they are digest-verified across restart and never become a successor to the
terminal canonical revision. Sealing still follows verified cleanup and
authority release or quarantine.

Playlist preparation has a strict canonical codec. It reconstructs
`PreparedPlaylistChange` and `PreparedManagedFile` from the manifest and
verified content-addressed attachments, rejects altered bindings or missing
attachments, and persists no controller-local path, lease, or ownership token.

Built-in Resource Type descriptors expose a lazy execution factory instead of
a process-bound execution instance. `ConfigurationResourceContexts` supplies
the resolved Device capability, per-Run binding, attachment store, lifecycle,
and clock without reversing the Resource Type dependency. Composition binds
each lifecycle's intent and freshly observed primitive-outcome checkpoints to
the same RunStore journal before reconstructing any prepared Resource.
Recovery rebuilds
all prepared Resources in persisted Plan/dependency order, observes each
freshly, rolls back in reverse order, and performs terminal cleanup in Plan
order. `ProductionExecutionFactory` binds these concrete stores and authority
adapters for one Run without opening a Device session itself.
