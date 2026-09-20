---
status: accepted
---

# Restart the Reconciler from a walking skeleton

Milestones M0 through M3 produced 29,582 lines of production Python and 20,627
lines of tests that manage one Resource Type, offline, having never contacted a
Device — roughly 2.6 times the 11,390-line shell provisioner that does the
whole job today. Around 18,000 of those lines are machinery: run evidence,
canonical persistence codecs, device authority, recovery authorisation, and
content-addressed remote mutation. The domain logic underneath is only 4,000 to
5,000 lines and is sound. The cause was sequencing and specification, not
agents or language: four milestones ran before anything touched hardware, so
every mechanism was justified by an imagined failure, and "done" was defined as
evidence rather than behaviour.

That implementation is therefore archived at the `m3-archive` tag and removed
from the working tree; git history, not a parallel package, preserves it, and
the shell remains a working example of every Resource Type. The replacement
begins as a walking skeleton that changes one real setting on the real Device —
read configuration, observe, diff, write atomically, re-read, report — with no
run store, no persisted Plans, no authority, no recovery subsystem, and no
evidence bundles. Work then proceeds as vertical slices, one Resource Type at a
time, each working end-to-end on hardware, and machinery arrives only inside
the slice that needs it.
