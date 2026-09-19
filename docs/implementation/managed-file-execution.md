# Managed-file execution and recovery

M3.3 adds a private execution module behind the overloaded
`Reconciler.execute(command)` boundary. Application composition supplies typed
workflow dependencies; `inventory` and `action` remain explicit
`not_implemented` results, and `provision` remains CLI-only syntax for
`reconcile`.

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
