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
uv run python scripts/check_inventory_milestones.py
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

`--print-shell-write-set` exits before any Device contact. Provisioning and
lifecycle mutation run the same checker before their first Device call. The
add-on assistant performs its existing read-only capability preflight first,
then checks permission before any guided mutation. A mapped inventory row
owned by Python, or marked `frozen` or `retired`, rejects the operation.
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

## `NewShows.xsp` handoff freeze

`SKIN-025` is
`special://profile/playlists/video/NewShows.xsp`. The legacy transformer writes
it through `write_xml_atomic(..., mode=0o600)` and does not verify its mode.
The accepted Python Resource requires `0644`. Equal XML semantics therefore
do not make shell resumption safe.

After the ownership ledger transfers `SKIN-025` to Python or marks its shell
write set frozen, every operation whose audited effective IDs contain
`SKIN-025` is rejected before Device contact. Today that includes `skin` and
`baseline`; the decision follows the audited write set, not those names.
Cross-component `addons` execution remains allowed only while its actual
write set is disjoint from every Python-owned ID.

There is no shell ownership handback after the first successful pilot
handoff. Any unknown target or newly discovered indirect write blocks the
affected pilot operation until the audit and ledger are reviewed together.
