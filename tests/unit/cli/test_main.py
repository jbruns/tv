import logging
import sys
from collections.abc import Sequence

import pytest

from coreelec_reconciler.application.commands import Command
from coreelec_reconciler.application.outcomes import Outcome, VerifyOutcome
from coreelec_reconciler.cli import main as cli_main
from coreelec_reconciler.domain.execution import RunStatus
from coreelec_reconciler.domain.planning import CanonicalRunReport


class _Application:
    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome

    def execute(self, command: Command) -> Outcome:
        print("bootstrap-noise")
        logging.warning("log-noise")
        return self.outcome


class _FailingApplication:
    def execute(self, command: Command) -> Outcome:
        raise RuntimeError("secret-token /private/controller/path")


def _report() -> CanonicalRunReport:
    return CanonicalRunReport(
        b'{"kind":"CoreElecReconcilerRunReport"}',
        "run",
        "sha256:digest",
        1,
        RunStatus.CONVERGED,
    )


def test_main_contains_bootstrap_and_logging_stdout_contamination(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    handler = logging.StreamHandler(sys.stdout)
    logging.root.addHandler(handler)
    monkeypatch.setattr(
        cli_main,
        "application_factory",
        lambda settings: _Application(VerifyOutcome(_report())),
    )
    try:
        exit_code = cli_main.main(["--quiet", "verify", "device"])
    finally:
        logging.root.removeHandler(handler)

    captured = capsysbinary.readouterr()
    assert exit_code == 0
    assert captured.out == _report().canonical_bytes + b"\n"
    assert captured.err == b""


class _BrokenPipe:
    def write(self, content: bytes) -> int:
        raise BrokenPipeError

    def flush(self) -> None:
        pass


class _TextWithBrokenBuffer:
    buffer = _BrokenPipe()

    def write(self, content: str) -> int:
        return len(content)

    def flush(self) -> None:
        pass

    def fileno(self) -> int:
        raise OSError


def test_presentation_broken_pipe_returns_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main,
        "application_factory",
        lambda settings: _Application(VerifyOutcome(_report())),
    )
    monkeypatch.setattr(sys, "stdout", _TextWithBrokenBuffer())

    assert cli_main.main(["--quiet", "verify", "device"]) == 0


def test_defect_uses_exit_one_without_raw_exception_details(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    monkeypatch.setattr(
        cli_main,
        "application_factory",
        lambda settings: _FailingApplication(),
    )

    exit_code = cli_main.main(["verify", "device"])

    captured = capsysbinary.readouterr()
    assert exit_code == 1
    assert captured.out == b""
    assert captured.err == (
        b"coreelec-reconciler: internal error; no unsafe details emitted\n"
    )
    assert b"secret-token" not in captured.err


@pytest.mark.parametrize(
    "arguments",
    [
        ("recover", "run", "finalize", "--mode", "abandon"),
        (
            "recover",
            "run",
            "finalize",
            "--mode",
            "abandon",
            "--approve",
            "recover.abandon",
            "--reason",
            "",
        ),
    ],
)
def test_abandon_usage_failure_never_calls_application(
    monkeypatch: pytest.MonkeyPatch,
    arguments: Sequence[str],
) -> None:
    called = False

    def factory(settings: object) -> _Application:
        nonlocal called
        called = True
        return _Application(VerifyOutcome(_report()))

    monkeypatch.setattr(cli_main, "application_factory", factory)

    with pytest.raises(SystemExit) as raised:
        cli_main.main(arguments)

    assert raised.value.code == 2
    assert called is False
