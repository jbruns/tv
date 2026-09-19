import json
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
BUDGET_RUNNER = REPOSITORY_ROOT / "scripts" / "run_test_budget.py"


def run_budget(
    result_path: Path,
    *command: str,
    budget_seconds: str = "10",
    include_result: Path | None = None,
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
        "5",
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


def test_runner_records_a_successful_command(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"

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


def test_runner_propagates_the_test_process_exit_status(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"

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


def test_runner_rejects_an_exceeded_aggregate_budget(tmp_path: Path) -> None:
    prior_path = tmp_path / "prior.json"
    prior_path.write_text('{"total_elapsed_seconds": 1.0}\n', encoding="utf-8")
    result_path = tmp_path / "result.json"

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
