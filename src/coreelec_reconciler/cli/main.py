"""Installed command-line entry point."""

import contextlib
import io
import logging
import os
import sys
from collections.abc import Callable, Sequence
from typing import Protocol, cast

from coreelec_reconciler.application.commands import Command
from coreelec_reconciler.application.outcomes import Outcome
from coreelec_reconciler.bootstrap import BootstrapSettings, bootstrap
from coreelec_reconciler.cli.parser import parse_command

from .presentation import present


class Application(Protocol):
    def execute(self, command: Command) -> Outcome: ...


ApplicationFactory = Callable[[BootstrapSettings], Application]
application_factory = cast(ApplicationFactory, bootstrap)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parsed = parse_command(argv)
        previous_logging_level = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            stderr_context = (
                contextlib.redirect_stderr(io.StringIO())
                if parsed.quiet
                else contextlib.nullcontext()
            )
            with contextlib.redirect_stdout(io.StringIO()), stderr_context:
                application = application_factory(
                    BootstrapSettings(parsed.repository_root)
                )
                outcome = application.execute(parsed.command)
        finally:
            logging.disable(previous_logging_level)
        return present(
            outcome,
            parsed.command,
            quiet=parsed.quiet,
            stdout=sys.stdout.buffer,
            stderr=sys.stderr.buffer,
            plan_document=parsed.output_document,
        )
    except BrokenPipeError:
        _silence_broken_stdout()
        return 0
    except Exception:
        try:
            sys.stderr.buffer.write(
                b"coreelec-reconciler: internal error; no unsafe details emitted\n"
            )
            sys.stderr.buffer.flush()
        except BrokenPipeError:
            pass
        return 1


def _silence_broken_stdout() -> None:
    try:
        descriptor = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(descriptor, sys.stdout.fileno())
        finally:
            os.close(descriptor)
    except AttributeError, OSError, io.UnsupportedOperation:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
