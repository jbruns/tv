---
status: accepted
---

# Shadow the shell, retire it wholesale, and track progress in the ledger

ADR 0010 retired the shell by attrition: the Reconciler took a Resource Type
and the shell shrank as an outcome. Working the first real candidate — the
`guisettings.xml` cohort — priced that outcome. Removing one State Address
from `provision-coreelec.sh` means removing it from six places: the write in
`main()`, its `coreelec_settings_payload_entry`, its
`coreelec_report_comparison` row, the config fingerprint, the `provision.conf`
key, and the default in `lib/coreelec-config.sh` — and only then the write set
and the ledger. Leaving the comparison row behind makes a fresh-Device shell
run report a `verification_failure` for a setting the shell deliberately no
longer writes, so the row cannot simply be skipped. None of that surgery
changes what a Device does. Applied honestly to the candidate slice it shrank
the slice from 41 addresses to 10 while the cost stayed flat.

So the shell stops being edited. It stays intact as the Recovery Baseline and
as the settings reference. The Reconciler **shadows** it one Resource Type at
a time, with both engines writing the same State Addresses and holding the
same values, and the shell is deleted **wholesale, once**, when a
factory-fresh Device can be provisioned from a Profile alone. Shadowing is a
deliberate, bounded exception to the exclusive-ownership rule of
[ADR 0009](0009-fail-forward-and-exclusive-execution-ownership.md), held safe
by the parity invariant below rather than by arbitration.

That end state is a cutover, which [ADR 0004](0004-disposable-pilot-cutover.md)
proposed and ADR 0010 superseded, so what is different must be stated plainly.
ADR 0004 scoped the work by an inventory: every managed State Address was to be
classified migrated, retired, or a Guided Action, and the shell removed once
the complete inventory passed. M0–M3 chased that parity and never contacted a
Device. Here a slice is scoped by the capability it builds, not by a count of
addresses, and it is accepted on real hardware before it merges. The inventory
is the checklist that shows what remains, never the definition of a slice.

## Standing rules for every shadowing slice

Three consequences hold for all shadowing work:

1. **Inject drift the first time a file or execution capability is
   exercised** — per capability, not per address. While the shell still writes
   an address, it masks a Reconciler that does nothing, so a slice that only
   observes convergence proves nothing.
2. **No declared address may plan as `create` on a provisioned Device.**
   `kodi_settings.rewrite` creates a node for an unknown id, so a typo'd
   setting id plans a `create`, writes a node Kodi ignores, and verifies as
   converged. A slice that declares addresses in a shared document must turn
   that silent pass into a loud failure.
3. **Run the shell after `apply`, then re-plan and expect no changes.** This
   is the value-parity invariant. One mismatched literal — `true` against `1`
   — gives two engines that revert each other forever, and nothing else would
   catch it.

### Rule 2 does not reach a Cleared Address

Rule 2 catches a typo because a wrong id has no node, so it plans a `create`.
A Cleared Address inverts that. Its Desired State is that the Device resolves
no value, and a typo'd id resolves no value either — so it observes as
converged, plans nothing, writes nothing, and reports success forever. The
rule cannot fire, because there is no write for it to fire on.

Reading the add-on's `resources/settings.xml` to check the id against its
definition was considered and rejected for the reasons in
[ADR 0013](0013-a-settings-document-always-takes-the-kodi-stop.md): the check
does not generalise, since `guisettings.xml` is Kodi core's and has no
definition file, and it proves only that an id is *defined* rather than that
it is the id the document's consumer actually reads.

The net is therefore an obligation on acceptance rather than a code path. **A
slice that declares a Cleared Address must, at acceptance, set every one of
them to a junk value and show `apply` clearing all of them.** That is a
stronger proof than a definition-file lookup and it needs no machinery, but it
is a manual step, and it is written down here because nothing in the code will
ever remind anyone to do it.

## The retirement test

The shell is deleted when the `CONTEXT.md` definition of Pilot Phase is met: a
factory-fresh Device provisioned from a Profile alone. The ledger records
state, not sequence, so it is not the finish line — ordering, bootstrap, and
transaction handling appear nowhere in it. A bare box simply fails if anything
unrecorded is missing, which is why the retirement test is a Device and not a
count of ledger rows.

## Tracking progress in the ledger

The ownership ledger is the inventory of what the shell does and therefore the
natural checklist. Progress cannot be tracked in `current_owner_or_executor`:
`scripts/shell_permissions.py` denies the shell any ID owned by `python`, so
marking progress there would switch the shell off and destroy the Recovery
Baseline the slice depends on. The ledger therefore gains a `reconciler_status`
field alongside it, valued `none`, `deferred`, `retired`, or `accepted`, where
`accepted` means converged on the Device and evidenced in a merged pull request,
and `retired` means the Reconciler will never own the address because a
factory-fresh Device does not have the state in the first place. The
Python-owner guard is left intact and unused. `current_owner_or_executor` does
not change under shadowing; it changes only when the shell is deleted.

The field is carried by the 138 rows the Reconciler can own — 128 `resource`,
5 `effect`, and 5 `guard`. Operator-owned `guided-action` rows,
repository-owned `run-infrastructure` rows, and `external` or
`unmanaged-inventory-fact` rows do not get it. The field is additive and no
reader changes behaviour, so `schema_version` is not bumped.

## The twelve deferred addresses

Twelve addresses are `deferred` rather than `none`, because they are blocked on
a mechanism rather than waiting their turn:

- `CORE-020`–`CORE-027` are blocked on the decision of how the Reconciler
  speaks to a running Kodi. They are the Kodi remote-control service cohort —
  EventServer and the web server — and they were first deferred on a secrets
  mechanism, because they contain `services.webserverpassword`, which no
  Profile may carry in plaintext. [ADR 0014](0014-desired-state-names-a-value-it-may-not-hold.md)
  settled that, and the cohort stayed deferred for a second reason that
  outlived the first: these eight addresses configure the channel Kodi is
  talked to *through*. The shell's own JSON-RPC runs over authenticated HTTP
  on `KODI_WEB_PORT` and Home Assistant's Kodi lifecycle package waits on that
  same endpoint. Managing the port, the credentials and the enable flags
  before the Reconciler has decided whether it depends on that channel would
  configure the channel from a Run that may be about to need it, so the cohort
  waits until that decision is made — which is now the add-on artifact slice's
  to make. `services.esenabled` once belonged in this list too, because it
  gated the Skinvariables buildviews probe;
  [ADR 0015](0015-trigger-the-view-rebuild-the-way-the-skin-does.md) removed
  that dependency and the flag is deferred only for the reason the other seven
  are.
- `CORE-028`, `CORE-029`, `ROOM-001`, and `ROOM-011` are blocked on Intent
  resolution. Audio device, passthrough device, screen resolution, and channel
  count cannot be known without observing a live Device's capabilities, so
  they are Intents to resolve rather than literals to declare.

## The retired addresses

`SKIN-027` and `SKIN-028` are `retired`. Both are Managed Absences: the shell
deletes `RecentlyReleasedMovies90Days.xsp` and
`RecentlyReleasedMoviesCurrentYear.xsp` because a newer playlist superseded
them. A factory-fresh Device has never had either file, so the only Device that
needs the deletion is the one we already own, and the retirement test — a bare
box provisioned from a Profile alone — is indifferent to them.

The shell recreates and re-deletes them on every Recovery Baseline run, so they
cannot be deleted by hand until the shell is gone; at that point they are
deleted once, by hand, and never thought about again. This does not close the
door on Managed Absence as a Reconciler capability. It says only that two
superseded playlists on a single Device do not justify building it, and that
the first address that genuinely needs absence on a fresh Device is the one
that should pay for the mechanism.

`PLAT-002` is `retired` for a different reason: the check does not earn its
place. The shell warns when `/proc/device-tree/model` does not match
`Ugoos.*AM6`, and unlike its three sibling checks it does not set `failed`
(provision-coreelec.sh:6053-6055) — the Recovery Baseline's own author did not
treat it as load-bearing.

Name the failure it would prevent: a Run aimed at a different Amlogic-ng
CoreELEC Device that also answers to the managed Device's hostname. The
hostname Guard fires first, `PLAT-001` pins the operating system, its version
and the SoC family, and nothing the Reconciler declares is Ugoos-specific —
`dolby_vision_mode` sits unused in `TRANSFORMS`, and the CEC document is found
by a glob that refuses unknown hardware loudly. Getting there requires
deliberately renaming a second Device, and recovery is reprovisioning.

Everything the model would distinguish is settled before a Run exists: the
operating system image and the device tree are chosen at install. A guard over
a fact no Run can change, protecting against a mistake no Run can make, is
machinery this bar does not buy.

`PLAT-004` and `PLAT-005` are not the Reconciler's to shadow yet. They guard
`LIFE-001`–`LIFE-003` from `lib/coreelec-lifecycle.sh`, not from the
provisioner, and they stay `none` until the lifecycle cohort is taken.

## The CEC slice narrows the glob it shadows

`CEC-001`–`CEC-005` live in a document whose name the Profile cannot know.
Kodi derives a peripheral's settings filename from the hardware's own
identity, so the file on the theater Ugoos is `cec_CEC_Adapter.xml`: a `cec_`
bus prefix Kodi controls, and a `CEC_Adapter` name the adapter reports. The
shell finds it with `*CEC*.xml` and requires exactly one match
(provision-coreelec.sh:588-597).

The Reconciler declares `cec_*.xml` instead. This is a deliberate departure
from the shell, and the reason is that the shell's glob works by coincidence:
it matches on the *name*, so an adapter calling itself anything else — a
Pulse-Eight, say — produces zero matches rather than the file it is standing
in front of. Anchoring to the bus prefix anchors to the part Kodi writes.
Both globs resolve the same file on the Device we own, so the value-parity
invariant is unaffected.

Two properties of this cohort are worth writing down because neither is
visible from the Profile:

Standing rule 2 fires a Run late here. `CPeripheral::PersistSettings` rebuilds
the document from memory when Kodi exits, so a mistyped setting ID is written
by the Reconciler, survives Verification, and is erased at the next Kodi exit
— and only the Run after that re-plans it as a `create`. Verification
immediately after `apply` is therefore not evidence for this cohort, and its
acceptance requires a full Kodi stop and start before the final re-plan.

`standby_pc_on_tv_standby` is `36028`, Kodi's localisation ID for the "Ignore"
action. The shell reads it from `CEC_TV_OFF_ACTION` and then rejects every
value except that one (provision-coreelec.sh:778-781) — a knob with a domain
of one. The Profile declares `ignore` through a transform instead, which
expresses the shell's validation as the schema rather than as a check, and the
payload entry retires with the shell. It is not a secret and does not become a
Named Value: routing a constant through `.env` would hide it from review for
no gain.
