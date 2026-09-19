# Python development and packaging

The production Reconciler is a Python 3.14 `src/` package managed with
[`uv`](https://docs.astral.sh/uv/). Create the locked development environment
from the repository root:

```console
uv sync --frozen
```

Run the scaffold quality checks and build the source distribution and wheel:

```console
uv run ruff check .
uv run ruff format --check \
  src scripts/run_test_budget.py tests/scaffold tests/ci \
  tests/conftest.py tests/support
uv run mypy
uv run python scripts/run_test_budget.py \
  --label pure-unit-architecture \
  --budget-seconds 10 \
  --timeout-seconds 300 \
  --result .ci-evidence/pure.json \
  -- \
  .venv/bin/python -m pytest -q \
  tests/scaffold/test_application.py \
  tests/scaffold/test_architecture.py tests/ci
uv run python scripts/run_test_budget.py \
  --label complete-offline \
  --budget-seconds 60 \
  --timeout-seconds 300 \
  --include-result .ci-evidence/pure.json \
  --result .ci-evidence/offline.json \
  -- \
  .venv/bin/python -m pytest -q tests/scaffold/test_cli.py
uv build
```

The first selection contains pure, unit, architecture, and CI-helper tests and
must finish in under 10 seconds. The second command runs the remaining offline
tests exactly once and adds the first result, enforcing a complete offline
total under 60 seconds. Each command has a 300-second hang watchdog; it does
not waive either budget. The runner writes source, platform, command, status,
and monotonic timing evidence under `.ci-evidence/`.

`tests/conftest.py` installs the offline socket guard before test collection
and passes it to Python subprocesses. Any socket creation fails with
`UnexpectedSocketError`; live Device and network-dependent tests therefore do
not belong in these selectors.

The [offline CI workflow](../.github/workflows/offline-ci.yml) runs the same
frozen sync, Ruff, strict mypy, exact pytest selectors, budgets, and package
build on Linux x86_64 and macOS arm64. Its least-privilege token grants only
read access to repository contents. The existing shell tests remain visible
as the separate `Shell transition suite` job through M11 and are not charged
to Python's budgets.

The installed command is `coreelec-reconciler`. Its version and help paths are
local metadata operations: they do not load Desired State, create a Device
session, or make network calls.

```console
uv run coreelec-reconciler --version
uv run coreelec-reconciler --help
```

The command surface is present so later vertical slices can implement behavior
through the typed `Reconciler.execute` boundary. Until then, operational
commands return an explicit `not_implemented` diagnostic and exit with status
2. For example:

```console
uv run coreelec-reconciler validate
```

`provision` is command-line sugar for `reconcile`; it is not a separate
application command. Building with `uv build` packages only
`src/coreelec_reconciler` and project metadata. Repository research,
prototypes, Profiles, inventory, templates, and other repository data remain
outside the wheel.
