---
status: accepted
---

# Fail forward and converge on re-run, under exclusive execution ownership

Verified rollback is retired. When a Run fails partway it stops, reports
exactly what was and was not changed, and leaves the Device recoverable by
running the same command again; Convergence on re-run is the safety property,
and rollback was a second, less-tested path attempting what convergence already
does. Two cheap obligations replace it: a mutation must never leave a Device
file broken — content is staged and then atomically renamed, so an interrupted
write cannot truncate a file Kodi needs — and re-running after an interruption
must be proven on hardware, not assumed.

Exclusive ownership survives but is narrowed to execution: exactly one engine
may write a given State Address, while both the shell and the Reconciler may
declare it. Overlapping declarations are expected rather than a validation
error, so no ledger is required to prove they are disjoint; the only thing
needing enforcement is that the shell does not execute a Resource the
Reconciler owns. This supersedes ADR 0003, whose broader reading of ownership
justified a 169-row ownership ledger and 1,617 lines of validation.
