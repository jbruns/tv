# Legacy shell write-set and Effect audit

Date: 2026-09-19

Issue: [#56](https://github.com/jbruns/tv/issues/56)

Base: merged `origin/main` commit
`0bf9c749d78773d3a1f2f57364d7e7f25be7aaf6`.

This is an offline audit and permission-enforcement change. It made no Device
connection, deployment, mutation, ownership transfer, or Python Resource
implementation.

## Authoritative evidence

The authoritative deterministic map is
[`inventory/shell-write-sets.json`](../../inventory/shell-write-sets.json),
SHA-256
`7d7f777e359a38f7abdd60ab86227056d2b3d4b113a6194464c319a2fe5a01a7`.
The updated ownership ledger SHA-256 is
`7df92594c5d86ec29142d5a758729c0e89a3be1004f66a2a8ab869dfeb1928bc`.

Coverage is exactly 146 accepted shell-actor rows:

| Coverage class | Rows |
| --- | ---: |
| Device writes or indirect writes | 135 |
| Effects | 5 |
| Read-only Guards/inventory observations | 6 |
| **Total** | **146** |

The map records eight mutation primitive families and the reachable call paths
from all three shell entry points. It includes dependency expansion, selected
artifact directory swaps, add-on enablement, shared-document writes, dynamic
CEC discovery, `BuildSkinViews` output, lifecycle gateway files, service
Effects, bootstrap state, rollback/finalize paths, and shell Run
Infrastructure. All 146 ledger rows changed from `unaudited` to `audited`;
the other 23 rows remain `not-applicable`.

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

## `NewShows.xsp` conflict and freeze

`SKIN-025` maps to
`special://profile/playlists/video/NewShows.xsp`. The shell writes its physical
file with mode `0600` through the transformer's default
`write_xml_atomic(..., mode=0o600)` and verifies XML semantics without mode.
The accepted Python Desired State requires `0644`.

The permission test proves that both `skin` and `baseline` reach `SKIN-025`,
while an `addons`-only run reaches the indirect skin outputs
`SKIN-017`–`SKIN-018` but not `SKIN-025`. After the ledger transfers or freezes
`SKIN-025`, every operation whose actual IDs include it is rejected. There is
no post-handoff shell ownership return.

## Verification evidence

All commands ran offline on macOS arm64. No retry, rerun, quarantine, ignored
failure, or `xfail` was used.

| Command | Result | Timing |
| --- | --- | ---: |
| Targeted Python permission/ledger tests | 27 passed | 0.16 s pytest |
| `bash tests/test-shell-write-sets.sh` | 4/4 passed | included below |
| Complete `tests/test-*.sh` loop excluding `test-helper.sh` | 9 scripts, 614/614 passed | 475.948 s |
| Pure/unit/architecture budget command | 40 passed; 2.353 s selection/total, under 10 s | 2.41 s wall |
| Complete offline budget command | 14 passed; 0.900 s selection, 3.253 s aggregate, under 60 s | 0.95 s wall |
| Ruff lint and format check | passed; 29 files formatted | included in 1.24 s group |
| Strict mypy | passed; 29 source files | included in 1.24 s group |
| `uv run python scripts/check_inventory_milestones.py` | 169 ledger rows; shell audit 146/146; 2 unknowns | included in 1.24 s group |
| `uv run coreelec-reconciler validate` | passed | included in 1.24 s group |
| `python3 scripts/check_shell_permissions.py --audit` | map valid; digest above | included in 1.24 s group |
| `python3 scripts/check_markdown.py` | passed | included in 1.24 s group |
| `git diff --check` | passed | included in 1.24 s group |

The combined lint, format, type, ledger, installed validator, shell-map,
Markdown, and diff-check command completed in 1.24 seconds.

## Pilot-freeze semantics

The map and ledger are a pre-M4 gate, not a handoff. Shell remains the current
Device mutation actor and Python remains nonmutating. At a future accepted
handoff, the ledger and former-owner freeze evidence must change before any
later shell mutation. Only audited operations whose complete writes and
Effects are disjoint from every Python-owned address may continue.
