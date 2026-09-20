from io import BytesIO

import pytest

from coreelec_reconciler.application.commands import (
    ApplyCommand,
    ReconcileCommand,
    RecoverCommand,
    ReportCommand,
    VerifyCommand,
)
from coreelec_reconciler.application.outcomes import (
    ApplyOutcome,
    ApprovalResolution,
    ReconcileOutcome,
    RecoverOutcome,
    RecoveryInspectionOutcome,
    ReportOutcome,
    UnsupportedOutcome,
    UnsupportedReason,
    VerifyOutcome,
)
from coreelec_reconciler.cli.presentation import present
from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    FinalizeMode,
    RecoveryActionCode,
    RunStatus,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.domain.planning import (
    CanonicalPlan,
    CanonicalRunReport,
    PlanDisposition,
)


class _TTY(BytesIO):
    def isatty(self) -> bool:
        return True


def _report(status: RunStatus, run_id: str = "run") -> CanonicalRunReport:
    content = (
        f'{{"kind":"CoreElecReconcilerRunReport","run_id":"{run_id}",'
        f'"status":"{status.value}","text":"caf\u00e9"}}'
    ).encode()
    return CanonicalRunReport(content, run_id, "sha256:digest", 1, status)


PLAN = CanonicalPlan(
    b'{"kind":"CoreElecReconcilerPlan","plan_id":"plan"}',
    "plan",
    "sha256:full",
    "sha256:semantic",
    PlanDisposition.ACTIONABLE,
)


@pytest.mark.parametrize(
    ("status", "cleanup_complete", "exit_code"),
    [
        (RunStatus.CONVERGED, True, 0),
        (RunStatus.NOOP, None, 0),
        (RunStatus.BLOCKED, None, 3),
        (RunStatus.FAILED_ROLLED_BACK, True, 4),
        (RunStatus.FAILED_PARTIAL, True, 4),
        (RunStatus.INTERRUPTED, False, 5),
        (RunStatus.FAILED_RECOVERY_REQUIRED, False, 5),
        (RunStatus.CONVERGED, False, 5),
    ],
)
def test_run_status_exit_and_exact_document_framing(
    status: RunStatus,
    cleanup_complete: bool | None,
    exit_code: int,
) -> None:
    report = _report(status)
    outcome = (
        VerifyOutcome(report)
        if cleanup_complete is None
        else ApplyOutcome(report, cleanup_complete)
    )
    stdout = BytesIO()
    stderr = BytesIO()

    actual = present(
        outcome,
        VerifyCommand(".", DeviceId("device")),
        quiet=False,
        stdout=stdout,
        stderr=stderr,
    )

    assert actual == exit_code
    assert stdout.getvalue() == report.canonical_bytes + b"\n"
    assert b"\n\n" not in stdout.getvalue()
    assert b"caf\xc3\xa9" in stdout.getvalue()
    assert b"\x1b[" not in stdout.getvalue()
    if exit_code == 5:
        assert stderr.getvalue().endswith(
            b"NEXT: coreelec-reconciler recover run inspect\n"
        )


def test_awaiting_approval_uses_authoritative_resolution() -> None:
    report = _report(RunStatus.AWAITING_APPROVAL, "planning")
    outcome = ReconcileOutcome(
        report,
        PLAN,
        None,
        None,
        ApprovalResolution(
            ("apply", "impact.removal"),
            ("apply",),
            ("impact.removal",),
        ),
    )
    stdout = BytesIO()
    stderr = BytesIO()

    exit_code = present(
        outcome,
        ReconcileCommand(".", DeviceId("device"), ("apply",)),
        quiet=True,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == report.canonical_bytes + b"\n"
    assert stderr.getvalue() == (
        b"NEXT: coreelec-reconciler apply plan "
        b"--approve apply --approve impact.removal\n"
    )


def test_inspection_prints_only_computed_legal_recovery_commands() -> None:
    report = _report(RunStatus.FAILED_RECOVERY_REQUIRED)
    actions = (
        AllowedRecoveryAction(
            RecoveryActionCode.RESUME_VERIFICATION,
            None,
            True,
            "allowed",
            False,
            False,
        ),
        AllowedRecoveryAction(
            RecoveryActionCode.ROLLBACK,
            None,
            False,
            "blocked",
            False,
            False,
        ),
        AllowedRecoveryAction(
            RecoveryActionCode.FINALIZE,
            FinalizeMode.NORMAL,
            True,
            "allowed",
            False,
            False,
        ),
        AllowedRecoveryAction(
            RecoveryActionCode.FINALIZE,
            FinalizeMode.ABANDON,
            True,
            "allowed",
            True,
            True,
        ),
    )
    stdout = BytesIO()
    stderr = BytesIO()

    exit_code = present(
        RecoveryInspectionOutcome(report, actions, False),
        RecoverCommand(".", RunId("run"), "inspect"),
        quiet=True,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == report.canonical_bytes + b"\n"
    assert stderr.getvalue() == (
        b"NEXT: coreelec-reconciler recover run resume-verification\n"
        b"NEXT: coreelec-reconciler recover run finalize --mode normal\n"
        b"NEXT: coreelec-reconciler recover run finalize --mode abandon "
        b"--approve recover.abandon --reason REASON\n"
    )
    assert b"rollback" not in stderr.getvalue()


def test_quiet_suppresses_status_but_not_safety_handoff() -> None:
    stdout = BytesIO()
    stderr = BytesIO()

    exit_code = present(
        RecoverOutcome(_report(RunStatus.FAILED_RECOVERY_REQUIRED), False),
        RecoverCommand(".", RunId("run"), "rollback"),
        quiet=True,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 5
    assert b"status:" not in stderr.getvalue()
    assert stderr.getvalue() == (b"NEXT: coreelec-reconciler recover run inspect\n")


@pytest.mark.parametrize(
    ("environment", "colored"),
    [
        ({}, True),
        ({"NO_COLOR": "1"}, False),
        ({"TERM": "dumb"}, False),
    ],
)
def test_color_requires_a_capable_tty(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    colored: bool,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    stderr = _TTY()

    present(
        VerifyOutcome(_report(RunStatus.CONVERGED)),
        VerifyCommand(".", DeviceId("device")),
        quiet=False,
        stdout=BytesIO(),
        stderr=stderr,
    )

    assert (b"\x1b[" in stderr.getvalue()) is colored


def test_non_tty_never_uses_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    stderr = BytesIO()

    present(
        ReportOutcome(_report(RunStatus.CONVERGED)),
        ReportCommand(".", RunId("run")),
        quiet=False,
        stdout=BytesIO(),
        stderr=stderr,
    )

    assert b"\x1b[" not in stderr.getvalue()


def test_unsupported_is_exit_three_with_empty_stdout() -> None:
    stdout = BytesIO()
    stderr = BytesIO()

    exit_code = present(
        UnsupportedOutcome(
            "apply",
            UnsupportedReason.CAPABILITY_UNAVAILABLE,
            "application.capability-unavailable",
        ),
        ApplyCommand(".", PlanId("plan"), ()),
        quiet=True,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 3
    assert stdout.getvalue() == b""
    assert stderr.getvalue() == (
        b"apply: capability_unavailable (application.capability-unavailable)\n"
    )
