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
  src scripts/run_test_budget.py scripts/check_inventory_milestones.py \
  tests/scaffold tests/inventory tests/ci \
  tests/conftest.py tests/support
uv run mypy
uv run python scripts/check_inventory_milestones.py
uv run python scripts/run_test_budget.py \
  --label pure-unit-architecture \
  --budget-seconds 10 \
  --timeout-seconds 300 \
  --result .ci-evidence/pure.json \
  -- \
  .venv/bin/python -m pytest -q \
  tests/scaffold/test_application.py \
  tests/scaffold/test_architecture.py tests/inventory tests/ci
uv run python scripts/run_test_budget.py \
  --label complete-offline \
  --budget-seconds 60 \
  --timeout-seconds 300 \
  --include-result .ci-evidence/pure.json \
  --result .ci-evidence/offline.json \
  -- \
  .venv/bin/python -m pytest -q tests/scaffold/test_cli.py
uv build
uv run python - <<'PY'
import hashlib
from pathlib import Path
from zipfile import ZipFile

wheels = list(Path("dist").glob("*.whl"))
assert len(wheels) == 1, wheels
with ZipFile(wheels[0]) as archive:
    names = archive.namelist()
    entry_point_paths = [
        name for name in names if name.endswith(".dist-info/entry_points.txt")
    ]
    assert len(entry_point_paths) == 1, entry_point_paths
    entry_points = archive.read(entry_point_paths[0]).decode()
assert all(
    name.startswith(("coreelec_reconciler/", "coreelec_reconciler-"))
    for name in names
), names
assert "coreelec-reconciler = coreelec_reconciler.cli.main:main" in entry_points
evidence_directory = Path(".ci-evidence")
evidence_directory.mkdir(exist_ok=True)
(evidence_directory / "wheel-contents.txt").write_text(
    "\n".join(names) + "\n",
    encoding="utf-8",
)
digests = []
artifacts = [
    *Path("dist").glob("*.whl"),
    *Path("dist").glob("*.tar.gz"),
]
for artifact in sorted(artifacts):
    with artifact.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    digests.append(f"{digest}  {artifact}")
(evidence_directory / "artifacts.sha256").write_text(
    "\n".join(digests) + "\n",
    encoding="utf-8",
)
print(f"wheel inspection passed: {wheels[0]} ({len(names)} files)")
print("\n".join(digests))
PY
uv venv --python 3.14 --clear .wheel-venv
uv pip install --python .wheel-venv/bin/python --no-deps dist/*.whl
mkdir -p .wheel-smoke
(cd .wheel-smoke && \
  ../.wheel-venv/bin/coreelec-reconciler --version && \
  ../.wheel-venv/bin/coreelec-reconciler --help >/dev/null)
```

The first selection contains pure, unit, architecture, and CI-helper tests and
must finish in under 10 seconds. The second command runs the remaining offline
tests exactly once and adds the first result, enforcing a complete offline
total under 60 seconds. Each command has a 300-second hang watchdog; it does
not waive either budget. Each test command starts in its own POSIX process
session. On timeout the runner signals the complete process group, waits a
bounded grace period, and escalates to `SIGKILL` so descendants cannot outlive
the gate. The runner writes source, platform, command, status, and monotonic
timing evidence under `.ci-evidence/`.

`tests/conftest.py` installs the offline socket guard before test collection
and passes it to Python subprocesses. Any socket creation fails with
`UnexpectedSocketError`; live Device and network-dependent tests therefore do
not belong in these selectors.

The [offline CI workflow](../.github/workflows/offline-ci.yml) runs the same
frozen sync, Ruff, strict mypy, exact pytest selectors, budgets, and package
build on Linux x86_64 and macOS arm64. Its least-privilege token grants only
read access to repository contents. Pull-request jobs explicitly check out the
head `SOURCE_SHA`, verify `HEAD` matches it, and use that SHA in evidence
artifact names. `workflow_sha` separately records GitHub's workflow context,
which may be a synthetic pull-request merge commit. The existing shell tests
remain visible as the separate macOS `Shell transition suite` job through M11,
use the same frozen environment for their Python fixture dependencies, and are
not charged to Python's budgets.

The installed command is `coreelec-reconciler`. Its version and help paths are
local metadata operations: they do not load Desired State, create a Device
session, or make network calls.

```console
uv run coreelec-reconciler --version
uv run coreelec-reconciler --help
uv run coreelec-reconciler validate
```

The command surface is present so later vertical slices can implement behavior
through the typed `Reconciler.execute` boundary. `validate` currently performs
the deterministic, offline inventory-ledger gate. Other operational commands
return an explicit `not_implemented` diagnostic and exit with status 2.

`provision` is command-line sugar for `reconcile`; it is not a separate
application command. Building with `uv build` packages only
`src/coreelec_reconciler` and project metadata. Repository research,
prototypes, Profiles, inventory, templates, and other repository data remain
outside the wheel.
