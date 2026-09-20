# Legacy shell write-set permissions

The authoritative machine-readable audit is
[`inventory/shell-write-sets.json`](../../inventory/shell-write-sets.json).
It traces the three legacy shell entry points through their reachable
mutation primitives to accepted inventory IDs and Effects. Component names
are selectors only: permission is decided from the expanded inventory IDs,
never from the component name.

Validate the map and ownership ledger together without Device access:

```console
python3 scripts/check_shell_permissions.py --audit
```

Inspect the exact effective write set of a provisioning command locally:

```console
UGOOS_ENV_FILE=.env ./provision-coreelec.sh \
  --target offline.invalid \
  --component addons \
  --addon script.plexmod \
  --no-harden \
  --print-shell-write-set
```

`--print-shell-write-set` exits before any Device contact. Provisioning,
lifecycle mutation, and the add-on assistant run the same checker before their
first Device call, including password preparation and read-only capability
discovery. A mapped inventory row owned by Python, or marked `frozen` or
`retired`, rejects the operation.

The audit validates each operation and scope independently. Its declared call
paths must match the reachable primitive topology, and every primitive's
inventory IDs must match the authoritative per-ID targets. Aggregate catalog
coverage cannot hide a missing, wrong, or swapped local binding.
Unknown entry points, operations, selectors, add-ons, map fields, and dynamic
targets reject rather than granting permission.

## Audited behavior

`provision-coreelec.sh` expands dependencies before checking permission:

- `services` also writes the selected add-on directories and enabled flags;
- `skin` also writes `core` and selected add-on state;
- `room` also writes `core`;
- any `addons`-effective run invokes `BuildSkinViews`, which can rewrite the
  compiled outputs `SKIN-017` and `SKIN-018` even when `skin` was not named;
- every Kodi deployment stops/starts Kodi (`EFFECT-001`) and currently
  restarts `tz-data.service` (`EFFECT-002`);
- optional SSH hardening writes `SSH-003` and restarts sshd (`EFFECT-003`).

The map also records administrator bootstrap, transaction/backup paths,
lifecycle gateway writes, lifecycle service restoration, and observation-only
entry points. These are explicit rather than hidden behind a component label.

Two dynamic mutation surfaces remain deliberately unknown and fail closed:

1. `provision-coreelec.sh --rollback-deployment`, because the pre-existing
   transaction's recorded scope is not available to the local permission
   check before Device contact.
2. `configure-coreelec-addons.sh --interactive`, because the launched add-on
   and GUI workflow can persist add-on-owned state whose complete targets are
   not statically traceable.

They are pilot blockers. Do not bypass the checker or guess their targets.
Finalize and inspect operations remain available because they do not restore
managed Device state. Lifecycle rollback is exact: its transaction can only
restore `LIFE-001` and `LIFE-002` and the temporary `LIFE-003` service state.

## `NewShows.xsp`: the first completed handoff

`SKIN-025` is `special://profile/playlists/video/NewShows.xsp`, and it is
Python-owned. It is the worked example of
[retiring the shell by attrition](../adr/0010-retire-the-shell-by-attrition.md).

The handoff was done in one direction, and the order is the whole point. The
permission decision is per-operation, not per-ID: an operation is rejected when
*any* ID it would reach is Python-owned or frozen. Transferring the ledger row
while the shell still wrote the file would therefore have rejected every `skin`
and `baseline` run, which is the Recovery Baseline. So the shell stopped
writing the address first, `SKIN-025` left its write set, and only then did the
ledger record Python as the owner. `skin` and `baseline` still run; they simply
no longer produce that file.

The cost is that the Recovery Baseline now lags Desired State by exactly this
address. A device provisioned by `provision-coreelec.sh` alone has a "New Shows"
menu entry pointing at a playlist that does not exist yet; `reconcile apply`
creates it. That lag is expected to grow with each handoff.

There is no handback. Any unknown target or newly discovered indirect write
blocks the affected operation until the map and ledger are reviewed together.
