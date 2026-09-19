"""Installed command-line entry point."""

from collections.abc import Sequence

from coreelec_reconciler.application.outcomes import UnsupportedOutcome
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
