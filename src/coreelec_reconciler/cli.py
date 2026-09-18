"""Evidence-only argparse command and presentation split."""

import argparse
from collections.abc import Sequence

from coreelec_reconciler.progress import (
    ProgressEvent,
    ProgressKind,
    present_progress,
)
from coreelec_reconciler.reporting import JsonValue, canonical_json_bytes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coreelec-reconciler")
    parser.add_argument("--output", choices=("human", "json"), default="human")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    present_progress(
        ProgressEvent(ProgressKind.MILESTONE, "validation started"), quiet=args.quiet
    )
    present_progress(
        ProgressEvent(ProgressKind.HEARTBEAT, "validation remains active"),
        quiet=args.quiet,
    )
    result: JsonValue = {"schema_version": 1, "status": "proof_complete"}
    if args.output == "json":
        import sys

        sys.stdout.buffer.write(canonical_json_bytes(result))
    else:
        print("Toolchain proof complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
