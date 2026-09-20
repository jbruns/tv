"""Stable CLI stream framing and exit-code policy."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from coreelec_reconciler.application.commands import Command, RecoverCommand
from coreelec_reconciler.application.outcomes import (
    ActionOutcome,
    ApplyOutcome,
    CanonicalPlanOutcome,
    InventoryOutcome,
    ObservationOutcome,
    Outcome,
    PlanningFailureOutcome,
    ReconcileOutcome,
    RecoverOutcome,
    RecoveryInspectionOutcome,
    ReportOutcome,
    UnsupportedOutcome,
    ValidationOutcome,
    VerifyOutcome,
)

_RESET = b"\x1b[0m"
_COLORS = {
    "error": b"\x1b[31;1m",
    "next": b"\x1b[33;1m",
    "status": b"\x1b[36m",
}


@dataclass(frozen=True, slots=True)
class Presentation:
    exit_code: int
    document: bytes | None = None
    status_lines: tuple[str, ...] = ()
    required_lines: tuple[str, ...] = ()


class _Status(Protocol):
    @property
    def value(self) -> str: ...


class _RunReport(Protocol):
    @property
    def canonical_bytes(self) -> bytes: ...

    @property
    def status(self) -> _Status: ...

    @property
    def run_id(self) -> str: ...


class _RecoveryAction(Protocol):
    @property
    def code(self) -> _Status: ...

    @property
    def finalize_mode(self) -> _Status | None: ...

    @property
    def allowed(self) -> bool: ...


def present(
    outcome: Outcome,
    command: Command,
    *,
    quiet: bool,
    stdout: BinaryIO,
    stderr: BinaryIO,
    plan_document: str = "plan",
) -> int:
    presentation = presentation_for(outcome, command, plan_document=plan_document)
    if presentation.document is not None:
        stdout.write(presentation.document + b"\n")
        stdout.flush()
    if not quiet:
        for line in presentation.status_lines:
            _write_line(stderr, line, "status")
    for line in presentation.required_lines:
        _write_line(stderr, line, "next" if line.startswith("NEXT:") else "error")
    stderr.flush()
    return presentation.exit_code


def presentation_for(
    outcome: Outcome,
    command: Command,
    *,
    plan_document: str = "plan",
) -> Presentation:
    if isinstance(outcome, UnsupportedOutcome):
        return Presentation(
            3,
            required_lines=(
                f"{outcome.command}: {outcome.reason} ({outcome.diagnostic_code})",
            ),
        )
    if isinstance(outcome, ValidationOutcome):
        if outcome.valid:
            totals = " ".join(
                f"{name}={count}" for name, count in outcome.disposition_totals
            )
            return Presentation(
                0,
                status_lines=(
                    f"inventory ledger valid: rows={outcome.row_count} "
                    f"{totals} sha256={outcome.sha256}",
                ),
            )
        return Presentation(2, required_lines=outcome.diagnostics)
    if isinstance(outcome, PlanningFailureOutcome):
        return Presentation(3, required_lines=outcome.diagnostics)
    if isinstance(outcome, CanonicalPlanOutcome):
        document = (
            outcome.run_report.canonical_bytes
            if plan_document == "run"
            else outcome.plan.canonical_bytes
        )
        return Presentation(
            _status_exit(outcome.run_report.status),
            document,
            (f"status: {outcome.run_report.status.value}",),
        )
    if isinstance(outcome, ObservationOutcome):
        return _run_presentation(outcome.run_report, None)
    if isinstance(outcome, ApplyOutcome):
        return _run_presentation(outcome.run_report, outcome.cleanup_complete)
    if isinstance(outcome, ReconcileOutcome):
        required: tuple[str, ...] = ()
        if (
            outcome.approval is not None
            and not outcome.approval.sufficient
            and outcome.plan is not None
        ):
            required = (_approval_command(outcome),)
        return _run_presentation(
            outcome.run_report,
            outcome.cleanup_complete,
            required=required,
        )
    if isinstance(outcome, VerifyOutcome):
        return _run_presentation(outcome.run_report, None)
    if isinstance(outcome, RecoveryInspectionOutcome):
        commands = tuple(
            _recovery_command(outcome.run_id.value, action)
            for action in outcome.actions
            if action.allowed and action.code.value != "inspect"
        )
        return Presentation(
            0,
            outcome.run_report.canonical_bytes,
            required_lines=commands,
        )
    if isinstance(outcome, RecoverOutcome):
        if (
            isinstance(command, RecoverCommand)
            and command.action == "finalize:abandon"
            and outcome.cleanup_complete
        ):
            return Presentation(
                0,
                outcome.run_report.canonical_bytes,
                (f"status: {outcome.run_report.status.value}",),
            )
        return _run_presentation(outcome.run_report, outcome.cleanup_complete)
    if isinstance(outcome, ReportOutcome):
        return Presentation(
            0,
            outcome.run_report.canonical_bytes,
            (f"status: {outcome.run_report.status.value}",),
        )
    if isinstance(outcome, InventoryOutcome):
        return Presentation(
            0,
            status_lines=tuple(device.value for device in outcome.device_ids),
        )
    if isinstance(outcome, ActionOutcome):
        return Presentation(0, status_lines=(f"status: {outcome.status}",))
    raise TypeError(f"unsupported outcome type: {type(outcome).__name__}")


def _run_presentation(
    report: _RunReport,
    cleanup_complete: bool | None,
    *,
    required: tuple[str, ...] = (),
) -> Presentation:
    exit_code = _status_exit(report.status)
    if cleanup_complete is False:
        exit_code = 5
    if exit_code == 5 and not required:
        required = (
            f"NEXT: coreelec-reconciler recover {shlex.quote(report.run_id)} inspect",
        )
    return Presentation(
        exit_code,
        report.canonical_bytes,
        (f"status: {report.status.value}",),
        required,
    )


def _status_exit(status: _Status) -> int:
    value = status.value
    if value == "blocked":
        return 3
    if value in {"failed_rolled_back", "failed_partial"}:
        return 4
    if value in {"interrupted", "executing", "failed_recovery_required"}:
        return 5
    return 0


def _approval_command(outcome: ReconcileOutcome) -> str:
    assert outcome.plan is not None
    assert outcome.approval is not None
    arguments = [
        "coreelec-reconciler",
        "apply",
        outcome.plan.plan_id,
    ]
    for scope in outcome.approval.required_scopes:
        arguments.extend(("--approve", scope))
    return "NEXT: " + shlex.join(arguments)


def _recovery_command(run_id: str, action: _RecoveryAction) -> str:
    arguments = ["coreelec-reconciler", "recover", run_id]
    code = action.code.value
    mode = action.finalize_mode
    if code == "resume_verification":
        arguments.append("resume-verification")
    elif code == "rollback":
        arguments.append("rollback")
    elif code == "finalize":
        if mode is None:
            raise ValueError("finalize recovery action omitted its mode")
        arguments.extend(("--mode", mode.value))
        arguments.insert(3, "finalize")
        if mode.value == "abandon":
            arguments.extend(("--approve", "recover.abandon", "--reason", "REASON"))
    else:
        arguments.append("inspect")
    return "NEXT: " + shlex.join(arguments)


def _write_line(stream: BinaryIO, line: str, tone: str) -> None:
    content = line.encode("utf-8", errors="replace")
    if _color_enabled(stream):
        content = _COLORS[tone] + content + _RESET
    stream.write(content + b"\n")


def _color_enabled(stream: BinaryIO) -> bool:
    return (
        bool(getattr(stream, "isatty", lambda: False)())
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM") != "dumb"
    )
