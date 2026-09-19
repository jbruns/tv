# Inventory ownership ledger

The machine-readable ledger is
[`inventory/ownership-ledger.json`](../../inventory/ownership-ledger.json).
It contains exactly the 169 IDs accepted by the
[managed-state classification](../research/2026-09-18-managed-state-classification.md)
and the
[milestone mapping](../research/2026-09-18-implementation-milestones-documentation-transitions.md):
153 `migrate`, 5 `retire`, and 11 `outside`.

Validate it without network or Device access:

```console
uv run python scripts/check_inventory_milestones.py
uv run coreelec-reconciler validate
```

Both commands fail closed. The script prints the required sorted audit table
and a SHA-256 digest of the exact ledger bytes. The installed command reaches
the same validator through the application and bootstrap boundary.

## Schema

The top-level object has no optional or extension fields:

| Field | Contract |
|---|---|
| `schema_version` | Integer `1` |
| `catalog` | `accepted-managed-state-v1` |
| `accepted_totals` | Exact grand, role, and disposition totals |
| `rows` | Exactly one object for every accepted inventory ID |

Every row contains:

| Field | Contract |
|---|---|
| `id` | Accepted catalog ID, exactly once |
| `state_address` | Non-secret logical or represented State Address from the factual inventory |
| `role` | `resource`, `guard`, `effect`, `guided-action`, `run-infrastructure`, or `unmanaged-inventory-fact` |
| `disposition` | `migrate`, `retire`, or `outside` |
| `milestone` | The accepted unique assignment from `M4` through `M8` |
| `current_owner_or_executor` | `shell`, `python`, `repository`, `operator`, `external`, or `none` |
| `closure` | State plus nullable closing issue and pull request |
| `evidence` | Test, retained evidence, and documentation paths |
| `shell_write_set` | Audit status and exact shell-owned State Addresses when #56 supplies them |
| `permitted_effects` | Audit status and exact shell Effects still permitted when #56 supplies them |
| `recovery` | `none`, `unresolved`, `quarantined`, or `resolved`, with evidence when not `none` |
| `transfers` | Ordered append-only ownership-transfer evidence |

Unknown fields, unknown IDs, duplicate JSON keys or IDs, missing IDs, changed
role/disposition/milestone assignments, unsupported values, blank evidence
fields, and incorrect totals are errors.

## Role-aware closure

`migrate` rows remain `open` until their assigned milestone has an accepted
exit record. Current M1 ownership is role-specific: Device Resources, Guards,
Effects, and derived shell evidence remain `shell`; Guided Actions remain
`operator`; repository Artifact provenance remains `repository`; external
health dependencies remain `external`.

Closure is not one generic Device-actor state:

| Disposition or role | Closed state | Owner/executor |
|---|---|---|
| Pre-retirement unmanaged fact | `open` | `shell` |
| Accepted `retire` unmanaged fact | `retired` | `none` |
| `outside` unmanaged fact | `outside` | `operator`, `external`, or `none` |
| Migrated Resource, Guard, or Effect | `transferred` | `python` |
| Migrated Guided Action | `accepted` | `operator` |
| Migrated Run Infrastructure | `accepted` | `repository` |
| Migrated evidence or Health Check fact | `evidence-integrated` | `python` or `external` |

A closed row requires positive `closing_issue` and `closing_pr` values.
Migrated closure before the assigned milestone exit record exists is rejected.
`transferred` closure also requires transfer evidence.

## Transfer representation

`transfers` is an append-only sequence. Each entry records:

- `sequence`, `from`, `to`, and `milestone`;
- implementation `issue` and `pull_request`;
- `prestate_evidence`, `handoff_evidence`, and `acceptance_evidence`;
- `former_owner_freeze_evidence`; and
- replacement operator `documentation`.

Sequences must be unique, ownership must form one chain, source and target
must differ, each milestone must match the row, sequence numbers must be
contiguous in array order, and the row's current owner must equal the final
target. Parallel or conflicting transfers fail validation.

This issue does not perform the shell write-set audit assigned to issue #56.
Rows that still have a shell actor therefore use `status: unaudited` with no
invented addresses or Effects. Non-shell rows use `not-applicable`. Issue #56
must replace those placeholders with its reviewed exact audit; an unaudited
state never grants permission to run a shell command.

## Per-issue update obligation

An issue that changes ownership or closes an inventory row must update, in the
same pull request:

1. the row's current owner/executor and role-valid closure;
2. the append-only transfer record when ownership changes;
3. focused tests;
4. source-bound acceptance evidence; and
5. replacement or retained operator documentation.

The issue must preserve the accepted ID, role, disposition, and milestone.
Changing any of those requires a separately reviewed planning amendment rather
than a local ledger edit. The ledger contains no credentials, host secrets,
controller-local paths, or sensitive Device observations.
