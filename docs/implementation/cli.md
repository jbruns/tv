# Installed execution and recovery CLI

The installed `coreelec-reconciler` command presents the canonical application
outcomes implemented through `Reconciler.execute`. It always enters through
the single production bootstrap. The CLI and application do not construct
production transports; the bootstrap owns their lazy composition. Constructing
the command never resolves a secret or contacts a Device.

## Commands

Use `--repository-root PATH` before the command when the authored repository is
not the current directory. Use `--quiet` before the command to suppress
ordinary progress and status text.

```text
coreelec-reconciler plan DEVICE_ID --observations FILE [--document plan|run]
coreelec-reconciler apply PLAN_ID [--approve SCOPE ...]
coreelec-reconciler reconcile DEVICE_ID [--approve SCOPE ...]
coreelec-reconciler provision DEVICE_ID [--approve SCOPE ...]
coreelec-reconciler verify DEVICE_ID
coreelec-reconciler report RUN_ID
coreelec-reconciler recover RUN_ID inspect
coreelec-reconciler recover RUN_ID resume-verification
coreelec-reconciler recover RUN_ID rollback
coreelec-reconciler recover RUN_ID finalize --mode normal
coreelec-reconciler recover RUN_ID finalize --mode abandon \
  --approve recover.abandon --reason "OPERATOR REASON"
```

`provision` is only syntax sugar for `reconcile`. It has no separate
application workflow.

Reconciliation without all required approval scopes stops before execution,
prints the canonical `awaiting_approval` planning Run, and writes a complete,
copyable `apply PLAN_ID --approve ...` command to stderr. The command uses the
application's authoritative `ApprovalResolution`, including all scopes needed
by a new `apply` invocation.

## Output contract

When an application outcome contains a canonical Plan or Run Report, stdout is
exactly its canonical UTF-8 bytes followed by one line feed. This remains true
for modeled nonzero exits. Progress, status, warnings, diagnostics, and
next-safe commands are stderr-only. Human stderr wording is not a stable
automation interface.

`--quiet` removes ordinary progress and status, but never removes required
safety diagnostics or next-safe commands. Color is used only when stderr is a
TTY and neither `NO_COLOR` nor `TERM=dumb` disables it. Stdout never contains
terminal escapes. Locale, timezone, and `PYTHONHASHSEED` do not affect
canonical output.

The stable exit codes are:

| Code | Meaning |
|---:|---|
| `0` | Successful command, including no-op, report, inspection, or approved abandonment |
| `2` | CLI usage or authored validation failure |
| `3` | Blocked, unsupported, not implemented, or unavailable without mutation |
| `4` | Execution failure with a fully known final Device state |
| `5` | Interrupted, recovery-required, or unresolved Run Infrastructure |
| `1` | Internal or unclassified defect |

Broken stdout pipes terminate without a traceback. Internal failures emit only
a generic stderr diagnostic; raw exception text, credentials, controller
paths, private temporary names, and secret values are not rendered.

## Recovery safety

A recovery-required result always points first to:

```text
coreelec-reconciler recover RUN_ID inspect
```

Inspection is read-only. After inspection, stderr contains only action commands
computed as legal by the application. The CLI never invents recovery authority
and never retries forward mutation.

Abandonment is noninteractive and cannot use a generic confirmation flag. It
requires both the exact `recover.abandon` approval and a non-empty operator
reason. Abandonment preserves `failed_recovery_required` truth and durable
quarantine even though the requested recovery command itself completed.

M3 acceptance is offline only. These command spellings are not authorization
for live use, deployment, or an ownership handoff. `SKIN-025` remains
shell-owned.
