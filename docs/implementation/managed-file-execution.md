# Managed-file execution and recovery

M3.3 adds a private execution module behind the overloaded
`Reconciler.execute(command)` boundary. Application composition supplies typed
workflow dependencies; `inventory` and `action` remain explicit
`not_implemented` results, and `provision` remains CLI-only syntax for
`reconcile`.

Managed-file execution uses least-authority fake capabilities. Every
state-changing primitive has a durable, operation-specific intent containing
the immediately checked remote marker before it runs. Receipts retain ordered
`applied`, `definitely_not_applied`, and `ambiguous` truth. Receipts never
claim convergence: execution freshly observes the complete Resource and
independently verifies it after possible mutation.

Rollback is conditional. It requires approval, verified preparation, and a
fresh state equal to the before-state, desired post-image, or an enumerated
Run-produced intermediate. Third-party state is never overwritten. Recovery
can inspect, resume observation and Verification, run an already-authorized
rollback, finalize known truth, or perform separately approved, reasoned
abandonment. It never resumes forward work.

Canonical terminal Device-state truth is persisted before cleanup. Cleanup
failure remains visible but cannot rewrite convergence or failure truth.
Progress events are deterministic presentation data; a failing sink adds only
a sanitized presentation diagnostic and cannot affect canonical evidence,
scheduling, or fake Device state.
