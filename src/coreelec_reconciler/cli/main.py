"""Installed command-line entry point."""

from collections.abc import Sequence

from coreelec_reconciler.application.outcomes import (
    PlanOutcome,
    UnsupportedOutcome,
    ValidationOutcome,
)
from coreelec_reconciler.bootstrap import BootstrapSettings, bootstrap
from coreelec_reconciler.cli.parser import parse_command


def main(argv: Sequence[str] | None = None) -> int:
    parsed = parse_command(argv)
    outcome = bootstrap(BootstrapSettings(parsed.repository_root)).execute(
        parsed.command
    )
    if isinstance(outcome, UnsupportedOutcome):
        import sys

        print(
            f"{outcome.command}: {outcome.reason} ({outcome.diagnostic_code})",
            file=sys.stderr,
        )
        return 2
    if isinstance(outcome, ValidationOutcome):
        if not outcome.valid:
            import sys

            for diagnostic in outcome.diagnostics:
                print(diagnostic, file=sys.stderr)
            return 2
        dispositions = " ".join(
            f"{name}={count}" for name, count in outcome.disposition_totals
        )
        print(
            f"inventory ledger valid: rows={outcome.row_count} "
            f"{dispositions} sha256={outcome.sha256}"
        )
    if isinstance(outcome, PlanOutcome):
        if outcome.plan is None:
            import sys

            for diagnostic in outcome.diagnostics:
                print(diagnostic, file=sys.stderr)
            return 3
        import sys

        sys.stdout.buffer.write(outcome.plan.canonical_bytes + b"\n")
        if outcome.disposition == "blocked":
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
