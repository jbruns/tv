# M3 pilot readiness

## Dry-run-only harness

Run:

```console
uv run python scripts/run_m3_pilot_harness.py \
  --dry-run --output .ci-evidence/m3-pilot-dry-run
uv run python scripts/verify_m3_evidence_bundle.py \
  .ci-evidence/m3-pilot-dry-run
```

The M3 harness is deliberately incapable of live operation. It opens no
socket, resolves no secret, accepts no endpoint or credential, and performs no
Device mutation. It binds the synthetic bundle to the exact Git commit, Git
tree, authored configuration digest, and `uv.lock` digest. Configuration and
lock bytes are read from the committed Git object, not the working tree. A
dirty tracked checkout or any untracked effective configuration beneath
`artifacts/`, `inventory/`, `profiles/`, or `secret-providers/` is rejected.
Untracked files outside that effective configuration boundary do not affect
the bundle.

The harness executes the issue-44 core sequence through the installed
production bootstrap and public application commands: absent/create,
formatting no-op, semantic repair, mode-only repair, malformed XML repair,
approved removal, recreate with Kodi attestation, and immediate no-op. It also
executes the approval-required reconcile branch and restart recovery
inspection. Deterministic stateful transport, session, authority, host-key,
clock, and identity seams replace only the live boundaries; the application,
composition root, planning, execution, observation, verification, reporting,
RunStore, PlanStore, and recovery implementations are production code.

The bundle contains sanitized canonical Plan and Run revision artifacts,
attachments, session-close records, authority and cleanup evidence, compact
public-command receipts, recovery action derivation, and the final synthetic
Device state. It records actual command exit statuses. It contains no raw
exceptions, controller paths, secret values, or live Device identifiers.

## Independent verification

The verifier is independent: it uses standard JSON and Git-object reads, and
does not call harness generation or production validators to decide semantic
acceptance. It separately checks commit/tree correspondence and recomputes
configuration and lock bytes from the claimed commit object. It then checks:

- missing or unexpected files;
- duplicate scenarios or ordinals;
- stitched core/supplemental evidence or multiple attempts;
- source commit, tree, configuration, or lock mismatch;
- noncanonical JSON or bad artifact/bundle digests;
- secret-bearing fields, private controller paths, real Device identity, or
  raw exception/traceback content;
- canonical Plan/Run identities, revision links, cross-document references,
  attachments, command results, operation ordering, recovery actions, final
  state, safety boundaries, and other semantic consistency;
- resealed evidence whose JSON and outer digests are valid but whose claimed
  execution is inconsistent.

Generate the bundle twice and compare all bytes before accepting it. The
installed-wheel workflow repeats the same real harness path from an unrelated
working directory. The core bundle is a single unstitched attempt.

## Authorization boundary

A passing dry run means only that the exact source is ready for the separately
reviewed disposable-pilot procedure. It is not live evidence and does not
authorize Device access, deployment, shell freeze or retirement, ownership
transfer, an Effect change, or M4 work.

`SKIN-025` remains shell-owned. No Python live use or ownership transfer is
authorized by M3.
