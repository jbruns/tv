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
uv run ruff format --check .
uv run mypy
uv run pytest tests/scaffold
uv build
```

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
