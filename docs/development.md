# Python development

The Reconciler is `coreelec-reconciler`, a `src/` package imported as
`coreelec_reconciler`. Milestones M0 through M3 built an implementation that
never contacted a Device; it is archived at the `m3-archive` tag and removed
from the working tree. See
[ADR 0008](adr/0008-restart-from-a-walking-skeleton.md) for what went wrong and
[ADR 0007](adr/0007-trusted-home-appliance-bar.md) for the bar that replaces
it. Today it manages one Resource on one Device: see
[reconciling the theater Ugoos](operations/reconcile-theater.md).

The rest of Device provisioning is still the shell provisioner. See
[the Ugoos provisioning operations guide](operations/provision-ugoos.md).

## What else remains

Two standard-library helpers outside the package:

- `scripts/check_shell_permissions.py` and `scripts/shell_permissions.py` —
  the fail-closed write-set permission guard the shell provisioner calls
  before it mutates a Device. `provision-coreelec.sh`,
  `configure-coreelec-addons.sh`, and `configure-kodi-lifecycle.sh` depend on
  this at runtime. It reads `inventory/shell-write-sets.json` and
  `inventory/ownership-ledger.json`.
- `scripts/check_markdown.py` — repository Markdown and link validation.

## Setup

```console
uv sync --frozen
```

## Checks

These are exactly what CI runs:

```console
uv run ruff check .
uv run ruff format --check src tests/unit scripts
uv run mypy
uv run pytest -q
python3 scripts/check_shell_permissions.py --audit
python3 scripts/check_markdown.py
git diff --check
```

Install the pre-commit hook so the same checks run before each commit. CI is
Linux-only per [ADR 0011](adr/0011-linux-only-ci-and-boundary-tests.md), so on
macOS this hook is the only thing exercising the code locally:

```console
git config core.hooksPath .githooks
```

Bypass it with `git commit --no-verify` when you need to.

## Rules for new code

- **Weigh every edge case.** Before writing a mechanism that exists only to
  handle a failure, name the failure, how likely it is, and what recovery costs
  without it. Disaster recovery is reprovisioning from scratch.
- **No mechanism before a slice needs it.** No upfront design documents
  specifying machinery, and no infrastructure for failures that have not
  happened.
- **Test at the boundary.** Tests live in `tests/unit/` and may not import
  from the package except through its public entry point, `main`. Tests that
  reach inside modules weld the implementation in place.
- **No platform-specific code.** Where behaviour differs, choose the option
  that works everywhere and accept the weaker guarantee.

## Legacy shell tests

Retained as manual reference evidence. They are not part of CI. Run them when
investigating legacy shell behavior:

```console
for test_script in tests/test-*.sh; do
  case "$test_script" in
    *test-helper.sh) continue ;;
  esac
  bash "$test_script"
done
```
