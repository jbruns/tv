"""The command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from . import artifact, config, lock, reconcile
from .device import DeviceError

DESCRIPTION = "Reconcile a CoreELEC Device with its declared Desired State."


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coreelec-reconciler", description=DESCRIPTION
    )
    parser.add_argument(
        "command",
        choices=("plan", "apply", "bootstrap", "record-patches"),
        help=(
            "plan reports the Changes and mutates nothing; apply converges; "
            "bootstrap makes First Contact with a Device that has no "
            "administrator key yet; record-patches runs the artifact "
            "pipeline and writes what each Artifact Patch produces back into "
            "the Artifact Lock, touching no Device"
        ),
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
        if arguments.command == "bootstrap":
            reconcile.bootstrap(desired, out=out)
        elif arguments.command == "record-patches":
            lock.record(desired, out=out)
        else:
            reconcile.run(desired, apply=arguments.command == "apply", out=out)
    except config.ConfigError as error:
        print(f"error: {error}", file=err)
        return 1
    except artifact.ArtifactError as error:
        # Every Artifact is fetched and proven before the Run takes an
        # Effect, so a failure here left the Device untouched and running.
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
