"""Evidence-only progress and canonical stdout tests."""

import io
import subprocess
import sys

from coreelec_reconciler.progress import (
    ProgressEvent,
    ProgressKind,
    present_progress,
)


def test_human_progress_has_milestone_and_heartbeat() -> None:
    stream = io.StringIO()
    present_progress(ProgressEvent(ProgressKind.MILESTONE, "connected"), stream=stream)
    present_progress(ProgressEvent(ProgressKind.HEARTBEAT, "waiting"), stream=stream)
    assert stream.getvalue() == "[milestone] connected\n[heartbeat] waiting\n"


def test_json_mode_keeps_stdout_canonical_and_progress_on_stderr() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "coreelec_reconciler.cli", "--output", "json"],
        check=True,
        capture_output=True,
    )
    assert result.stdout == b'{"schema_version":1,"status":"proof_complete"}\n'
    assert b"[milestone]" in result.stderr
    assert b"[heartbeat]" in result.stderr


def test_json_quiet_mode_has_no_diagnostics() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "coreelec_reconciler.cli",
            "--output",
            "json",
            "--quiet",
        ],
        check=True,
        capture_output=True,
    )
    assert result.stderr == b""
