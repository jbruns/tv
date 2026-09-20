---
status: accepted
---

# Retire the shell by attrition, not on a schedule

Shell retirement remains the endgame, but it is no longer a dated cutover.
The Reconciler takes one Resource Type at a time, and only when it is
demonstrably better at that Resource; the shell shrinks as an outcome rather
than to a deadline. A scheduled cutover is what forced parity-chasing and
produced the machinery that ADR 0008 removes. The shell is feature-frozen by
degree: a State Address the shell does not already manage goes to the
Reconciler, while extensions and fixes to Resources the shell already owns are
made in the shell, and the shell may always be fixed when that is what it takes
to get a working Device.

Shell configuration is left intact when the Reconciler takes over a Resource,
so the shell retains its ability to restore a Device to a working state from
scratch. Its declaration becomes a Recovery Baseline: deliberately allowed to
lag current Desired State, since desired-state changes for a migrated Resource
are made only in the Reconciler's configuration. Restoring a Device is
therefore two steps — run the shell baseline, then converge with the
Reconciler — and a Device is briefly at old values in between. This supersedes
ADR 0004.
