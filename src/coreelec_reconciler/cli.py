"""The command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from . import artifact, config, lock, proposal, reconcile
from .device import DeviceError

DESCRIPTION = "Reconcile a CoreELEC Device with its declared Desired State."


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coreelec-reconciler", description=DESCRIPTION
    )
    parser.add_argument(
        "command",
        choices=(
            "plan",
            "apply",
            "bootstrap",
            "survey",
            "record-patches",
            "propose-updates",
        ),
        help=(
            "plan reports the Changes and mutates nothing; apply converges; "
            "bootstrap makes First Contact with a Device that has no "
            "administrator key yet; survey reports how the Device differs "
            "from the Profile, mutates nothing, and needs Kodi stopped; "
            "record-patches runs the artifact "
            "pipeline and writes what each Artifact Patch produces back into "
            "the Artifact Lock, touching no Device; propose-updates writes an "
            "Update Proposal for every newer Stable Release every Artifact "
            "Lock's Release Channels offer, touching no Device and no GitHub"
        ),
    )
    parser.add_argument(
        "--room",
        help=(
            "the room whose Room Overlay names the Device; every command but "
            "propose-updates needs one"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        help=(
            "propose-updates only: an empty directory to write one "
            "subdirectory per Update Proposal into"
        ),
    )
    parser.add_argument(
        "--declined",
        action="append",
        default=[],
        metavar="PROFILE/ID@VERSION",
        help=(
            "propose-updates only: a version whose proposal was closed "
            "unmerged, which is not proposed again; repeatable"
        ),
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

    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "propose-updates":
        if arguments.out is None:
            parser.error("propose-updates needs --out")
    elif arguments.room is None:
        parser.error(f"{arguments.command} needs --room")
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    try:
        if arguments.command == "propose-updates":
            # A channel that could not be reached was skipped and named, and
            # the run fails at the end so next week's run is the recovery.
            proposed = proposal.propose(
                arguments.config_root,
                arguments.out,
                arguments.declined,
                stdout=out,
                err=err,
            )
            return 0 if proposed else 1
        if arguments.command == "record-patches":
            # It resolves only as far as the Artifact Lock, because that and
            # the patches beside it are all it reads.
            document, addons = config.lock(arguments.config_root, arguments.room)
            lock.record(document, addons, out=out)
            return 0
        desired = config.load(arguments.config_root, arguments.room, arguments.env_file)
        if arguments.command == "bootstrap":
            reconcile.bootstrap(desired, out=out)
        elif arguments.command == "survey":
            reconcile.survey(desired, out=out)
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
