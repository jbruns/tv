# Shell write-set map and permission guard

`provision-coreelec.sh` is the Recovery Baseline. Before it touches a Device it
asks [`scripts/shell_permissions.py`](../../scripts/shell_permissions.py)
whether the operation is still shell-owned, and refuses to run if it is not.
This document records what that guard knows.

Two files drive it:

- [`inventory/shell-write-sets.json`](../../inventory/shell-write-sets.json)
  maps each shell entry point and component to the exact inventory IDs it
  writes, through eight mutation primitive families and their reachable call
  paths.
- [`inventory/ownership-ledger.json`](../../inventory/ownership-ledger.json)
  records, per ID, which engine owns it and how far the Reconciler has got
  with it (`reconciler_status`, which the guard does not read).

The validator checks every operation and scope against that exact topology,
checks each primitive's IDs against the authoritative per-ID targets, and
rejects local missing, wrong, or swapped bindings even when aggregate catalog
coverage is unchanged. It covers dependency expansion, selected artifact
directory swaps, add-on enablement, shared-document writes, dynamic CEC
discovery, `BuildSkinViews` output, lifecycle gateway files, service Effects,
bootstrap state, rollback/finalize paths, and shell Run Infrastructure.

Coverage is 146 shell-actor rows: 135 Device writes or indirect writes, 5
Effects, and 6 read-only Guards or inventory observations. The remaining ledger
rows are not shell-actor rows. `python3 scripts/check_shell_permissions.py
--audit` prints the live counts and the map digest.

## Exact effective boundaries

- `provision-coreelec.sh` `core`: `CORE-001`–`CORE-029`,
  `EFFECT-001`, and `EFFECT-002`.
- `cec`: `CEC-001`–`CEC-005`, `EFFECT-001`, and `EFFECT-002`.
- `addons`: the selected `ART-001`–`ART-041` rows, `ADDON-001`,
  report-only `ADDON-003`, indirect outputs `SKIN-017`–`SKIN-018`,
  and `EFFECT-001`, `EFFECT-002`, and `EFFECT-004`.
- `services`: `addons` plus `SVC-001`–`SVC-017`.
- `skin`: `core`, `addons`, and `SKIN-001`–`SKIN-028`.
- `room`: `core` plus `ROOM-001`–`ROOM-011`.
- `baseline`: `core`, `cec`, `addons`, `services`, and `skin`.
- optional SSH hardening: `SSH-003` and `EFFECT-003`.
- lifecycle deploy/rollback: `LIFE-001`, `LIFE-002`, and temporary
  `LIFE-003`, guarded by `PLAT-004` and `PLAT-005`.
- add-on observer: `GUIDE-001`–`GUIDE-008`, with no declared persistent
  shell write in non-interactive mode.

Permission is computed from these expanded IDs. A component name never grants
permission. The checker rejects a mapped ID once its ledger owner is Python or
its shell fields are frozen/retired.

Every entry point enforces that permission before its first Device contact.
For the add-on assistant this includes password preparation and read-only Kodi
capability discovery, so a denied or unknown interactive operation makes zero
SSH or JSON-RPC calls.

## Fail-closed unknowns and pilot blockers

Exactly two dynamic targets remain unknown:

1. `provision-rollback-transaction-write-set`: a pending transaction can
   restore the dynamically recorded prior scope, which cannot be proven
   locally before Device contact.
2. `addon-owned-state-mutated-by-guided-GUI-workflow`: interactive PM4K/Kodi
   GUI execution can persist add-on-owned state beyond a statically exact
   target set.

Both operations now fail closed. No target was guessed. They remain residual
pilot blockers until a separately reviewed exact scope/evidence mechanism
exists.

## `NewShows.xsp`: the first shadowed address

`SKIN-025` maps to `special://profile/playlists/video/NewShows.xsp`. Both
engines write it: the shell through its smart-playlist transformer, and the
Reconciler as its first working slice. That is a bounded exception to
[ADR 0009](../adr/0009-fail-forward-and-exclusive-execution-ownership.md), and
it is resolved by shadowing rather than by arbitration: both engines keep
writing the address and hold the same value, so neither reverts the other, and
the ledger hands nothing to Python until the shell is deleted wholesale.

Ownership could not be transferred early even if that were wanted, because the
guard is component-level and all-or-nothing. `evaluate_shell_permission`
refuses an operation when *any* ID it would reach is Python-owned or frozen.
Flipping `SKIN-025` to `python` while the shell still writes it would block
every `--component skin` run, not just the one write, and remove the Recovery
Baseline. The permission test proves the reach: both `skin` and `baseline`
reach `SKIN-025`, while an `addons`-only run reaches the indirect skin outputs
`SKIN-017`-`SKIN-018` but not `SKIN-025`.

Progress is recorded instead in the ledger's `reconciler_status` field, which
is `accepted` for `SKIN-025` and `CORE-013`. `current_owner_or_executor` stays
`shell` for every row, and the Python-owner guard stays intact and unused. See
[ADR 0012](../adr/0012-shadow-the-shell-and-retire-it-wholesale.md).

## Checking the map

```sh
python3 scripts/check_shell_permissions.py --audit
bash tests/test-shell-write-sets.sh
```

The first validates the map topology and prints its digest; the second proves
the guard denies unknown and unowned operations before any Device contact.
Neither makes a Device connection.
