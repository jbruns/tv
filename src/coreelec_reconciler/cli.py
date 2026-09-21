"""The command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from . import config, reconcile
from .device import DeviceError

DESCRIPTION = "Reconcile a CoreELEC Device with its declared Desired State."


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coreelec-reconciler", description=DESCRIPTION
    )
    parser.add_argument(
        "command",
        choices=("plan", "apply"),
        help="plan reports the Changes and mutates nothing; apply converges",
    )
    parser.add_argument(
        "--room",
        required=True,
        help="the room whose Room Overlay names the Device",
    )
    parser.add_argument(
        "--config-root",
        default="config",
        type=Path,
        help="the configuration tree to read (default: config)",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        type=Path,
        help=(
            "the shared .env holding values a Profile names but does not "
            "carry, read only when one is named (default: .env)"
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Runs one Run. Returns 0 when the Device is at its Desired State."""

    arguments = _parser().parse_args(argv)
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    try:
        desired = config.load(arguments.config_root, arguments.room, arguments.env_file)
        reconcile.run(desired, apply=arguments.command == "apply", out=out)
    except config.ConfigError as error:
        print(f"error: {error}", file=err)
        return 1
    except DeviceError as error:
        print(f"error: {error}", file=err)
        if arguments.command == "apply":
            print(
                "error: the Device did not converge. Nothing was left "
                "half-written; run apply again to finish.",
                file=err,
            )
        return 1
    return 0
