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

The bundle describes, but does not execute, the issue-44 core sequence:
absent/create, formatting no-op, semantic repair, mode-only repair, malformed
XML repair, approved removal, recreate with Kodi attestation, and immediate
no-op. Every record is synthetic, description-only, and explicitly says that
Device contact and secret resolution did not occur.

## Independent verification

The verifier separately checks commit/tree correspondence and recomputes
configuration and lock bytes from the claimed commit object, plus artifact and
bundle digests. It rejects:

- missing or unexpected files;
- duplicate scenarios or ordinals;
- stitched core/supplemental evidence or multiple attempts;
- source commit, tree, configuration, or lock mismatch;
- noncanonical JSON or bad artifact/bundle digests;
- secret-bearing fields, private controller paths, real Device identity, or
  raw exception/traceback content;
- changed order, status, primitive trace, safety boundary, or other semantic
  invalidity.

Generate the bundle twice and compare all bytes before accepting it. The core
bundle is unstitched; supplemental recovery evidence, if ever authorized after
a live core seal, is always separate.

## Authorization boundary

A passing dry run means only that the exact source is ready for the separately
reviewed disposable-pilot procedure. It is not live evidence and does not
authorize Device access, deployment, shell freeze or retirement, ownership
transfer, an Effect change, or M4 work.

`SKIN-025` remains shell-owned. No Python live use or ownership transfer is
authorized by M3.
