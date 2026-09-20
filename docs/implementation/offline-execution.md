# M3 offline execution, recovery, and reporting

## Boundary

M3 integrates the production composition and proves execution, recovery, and
reporting offline. It does not contact a Device, resolve a real secret, deploy
software, change Effects, retire the shell implementation, or transfer
ownership. `SKIN-025` remains shell-owned.

The installed CLI calls the single production `bootstrap`. That composition
root builds the real `ApplicationDependencies`,
`ExecutionApplicationWorkflows`, and `ExecutionEngine` graph. It alone owns
lazy production SSH/SFTP, host-key, secret, and filesystem RunStore
construction. CLI and application modules depend on typed seams and
instantiate no concrete adapter. Bootstrap construction itself has no socket,
secret-resolution, or local-state side effect. Missing approved Plans, Device
sessions, and Runs produce typed capability-unavailable outcomes, not
`not_implemented`.

## Exact offline partition

The under-10-second pure/unit/architecture selection is:

```text
tests/scaffold/test_application.py
tests/scaffold/test_architecture.py
tests/inventory
tests/ci
tests/unit
```

The remaining selection, whose elapsed time is added to the first and must
keep the complete total under 60 seconds, is:

```text
tests/adapters
tests/contracts
tests/scaffold/test_cli.py
tests/scaffold/test_cli_planning.py
tests/scaffold/test_cli_execution.py
tests/integration
```

The selector contract enumerates every Python `test_*.py` file, proves these
sets are disjoint and complete, and excludes every legacy shell test. Shared
fake/production Device-session, managed-file, ambiguity-twin, and remote
ownership contracts are in the remaining selection. A session-wide no-socket
guard is installed before collection and inherited by Python subprocesses.

## Execution and recovery truth

Canonical Run status records Device-state truth; cleanup is a separate fact.
Mutation acknowledgements never establish convergence. Fresh observation and
Verification decide the result, including ambiguous acknowledgements.
Recovery begins with read-only inspection and exposes only computed legal
actions. It never retries forward mutation. Abandonment requires its distinct
approval and reason and leaves durable blocking quarantine.

Canonical Plan and Run bytes, revision linkage, attachment bindings, terminal
immutability, active-index release order, and workspace opacity are tested
independently. Installed-wheel tests run the executable from an unrelated
working directory and cover execution, recovery, reporting, streams, exit
codes, environment determinism, broken pipes, and contamination redaction.

## Package and CI

The wheel contains the production package and metadata only. CI checks the
bootstrap, CLI, execution, RunStore, and production adapter modules are present
and that tests, scripts, workflows, Profiles, and inventory are absent. Linux
x86_64 and macOS arm64 jobs run the same frozen lock, exact selectors, package
build, installed-wheel workflows, deterministic harness, and independent
verification.

The legacy shell suite is manual reference evidence only. It is not run by M3
acceptance and its permission ledger remains unchanged.
