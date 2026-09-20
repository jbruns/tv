import json
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
BUDGET_RUNNER = REPOSITORY_ROOT / "scripts" / "run_test_budget.py"


@pytest.fixture
def scratch_directory() -> Iterator[Path]:
    path = REPOSITORY_ROOT / f".ci-test.{uuid4().hex}"
    path.mkdir(mode=0o700)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def run_budget(
    result_path: Path,
    *command: str,
    budget_seconds: str = "10",
    include_result: Path | None = None,
    timeout_seconds: str = "5",
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["SOURCE_SHA"] = "test-source-sha"
    arguments = [
        sys.executable,
        str(BUDGET_RUNNER),
        "--label",
        "test-suite",
        "--budget-seconds",
        budget_seconds,
        "--timeout-seconds",
        timeout_seconds,
        "--result",
        str(result_path),
    ]
    if include_result is not None:
        arguments.extend(["--include-result", str(include_result)])
    arguments.extend(["--", *command])
    return subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_runner_records_a_successful_command(scratch_directory: Path) -> None:
    result_path = scratch_directory / "result.json"

    result = run_budget(result_path, sys.executable, "-c", "print('passed')")

    assert result.returncode == 0
    assert result.stdout.startswith("passed\n")
    evidence = json.loads(result_path.read_text(encoding="utf-8"))
    assert evidence["label"] == "test-suite"
    assert evidence["command"] == [sys.executable, "-c", "print('passed')"]
    assert evidence["command_exit_code"] == 0
    assert evidence["budget_seconds"] == 10.0
    assert evidence["elapsed_seconds"] >= 0
    assert evidence["source_sha"] == "test-source-sha"
    assert evidence["total_elapsed_seconds"] == evidence["elapsed_seconds"]
    assert evidence["budget_passed"] is True


def test_runner_propagates_the_test_process_exit_status(
    scratch_directory: Path,
) -> None:
    result_path = scratch_directory / "result.json"

    result = run_budget(
        result_path,
        sys.executable,
        "-c",
        "raise SystemExit(7)",
    )

    assert result.returncode == 7
    evidence = json.loads(result_path.read_text(encoding="utf-8"))
    assert evidence["command_exit_code"] == 7
    assert evidence["budget_passed"] is True


def test_runner_rejects_an_exceeded_aggregate_budget(
    scratch_directory: Path,
) -> None:
    prior_path = scratch_directory / "prior.json"
    prior_path.write_text('{"total_elapsed_seconds": 1.0}\n', encoding="utf-8")
    result_path = scratch_directory / "result.json"

    result = run_budget(
        result_path,
        sys.executable,
        "-c",
        "pass",
        budget_seconds="0.5",
        include_result=prior_path,
    )

    assert result.returncode == 1
    assert "budget exceeded" in result.stderr
    evidence = json.loads(result_path.read_text(encoding="utf-8"))
    assert evidence["prior_elapsed_seconds"] == 1.0
    assert evidence["total_elapsed_seconds"] >= 1.0
    assert evidence["budget_passed"] is False


@pytest.mark.parametrize("ignore_sigterm", [False, True])
def test_runner_cleans_up_descendants_on_timeout(
    scratch_directory: Path,
    *,
    ignore_sigterm: bool,
) -> None:
    result_path = scratch_directory / "result.json"
    ready_path = scratch_directory / "descendant.pid"
    process_group_path = scratch_directory / "process-group.pid"
    terminated_path = scratch_directory / "descendant-terminated"
    signal_setup = (
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)"
        if ignore_sigterm
        else "signal.signal(signal.SIGTERM, terminate)"
    )
    descendant_code = f"""
import os
import signal
from pathlib import Path

ready = Path({str(ready_path)!r})
terminated = Path({str(terminated_path)!r})

def terminate(signum, frame):
    del signum, frame
    terminated.write_text("terminated")
    raise SystemExit(0)

{signal_setup}
ready.write_text(str(os.getpid()))
signal.pause()
"""
    parent_code = (
        "import os, signal, subprocess, sys; from pathlib import Path; "
        f"Path({str(process_group_path)!r}).write_text(str(os.getpgrp())); "
        f"subprocess.Popen([sys.executable, '-c', {descendant_code!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL); "
        "signal.pause()"
    )

    try:
        result = run_budget(
            result_path,
            sys.executable,
            "-c",
            parent_code,
            timeout_seconds="0.1",
        )

        assert result.returncode == 124
        if ignore_sigterm:
            assert not terminated_path.exists()
        else:
            assert terminated_path.read_text(encoding="utf-8") == "terminated"
        process_group_id = int(process_group_path.read_text(encoding="utf-8"))
        with pytest.raises((PermissionError, ProcessLookupError)):
            os.killpg(process_group_id, 0)
        evidence = json.loads(result_path.read_text(encoding="utf-8"))
        assert evidence["timed_out"] is True
        assert evidence["command_exit_code"] == 124
    finally:
        if ready_path.exists():
            descendant_pid = int(ready_path.read_text(encoding="utf-8"))
            with suppress(ProcessLookupError):
                os.kill(descendant_pid, signal.SIGKILL)
