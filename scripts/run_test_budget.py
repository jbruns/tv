#!/usr/bin/env python3

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one test selection once and enforce its elapsed-time budget."
    )
    parser.add_argument("--label", required=True)
    parser.add_argument("--budget-seconds", required=True, type=float)
    parser.add_argument("--timeout-seconds", required=True, type=float)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--include-result", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if arguments.command[:1] == ["--"]:
        arguments.command = arguments.command[1:]
    if not arguments.command:
        parser.error("a command is required after --")
    return arguments


def prior_elapsed(path: Path | None) -> float:
    if path is None:
        return 0.0
    value = json.loads(path.read_text(encoding="utf-8"))["total_elapsed_seconds"]
    if not isinstance(value, int | float):
        raise TypeError("included result has a non-numeric total_elapsed_seconds")
    return float(value)


def append_job_summary(evidence: dict[str, Any]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path is None:
        return
    status = "PASS" if evidence["budget_passed"] else "FAIL"
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write(
            f"- **{evidence['label']}**: {status}; "
            f"{evidence['elapsed_seconds']:.3f}s this selection, "
            f"{evidence['total_elapsed_seconds']:.3f}s total "
            f"(budget < {evidence['budget_seconds']:.3f}s)\n"
        )


def main() -> int:
    arguments = parse_args()
    included_elapsed = prior_elapsed(arguments.include_result)
    started = time.monotonic_ns()
    timed_out = False
    try:
        completed = subprocess.run(
            arguments.command,
            check=False,
            timeout=arguments.timeout_seconds,
        )
        command_exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        command_exit_code = 124
        print(
            f"{arguments.label}: command exceeded "
            f"{arguments.timeout_seconds:g}s hang watchdog",
            file=sys.stderr,
        )
    elapsed = (time.monotonic_ns() - started) / 1_000_000_000
    total_elapsed = included_elapsed + elapsed
    budget_passed = total_elapsed < arguments.budget_seconds
    evidence: dict[str, Any] = {
        "budget_passed": budget_passed,
        "budget_seconds": arguments.budget_seconds,
        "command": arguments.command,
        "command_exit_code": command_exit_code,
        "elapsed_seconds": elapsed,
        "label": arguments.label,
        "platform": platform.platform(),
        "prior_elapsed_seconds": included_elapsed,
        "python": platform.python_version(),
        "source_sha": os.environ.get("GITHUB_SHA") or os.environ.get("SOURCE_SHA"),
        "timed_out": timed_out,
        "timeout_seconds": arguments.timeout_seconds,
        "total_elapsed_seconds": total_elapsed,
    }
    arguments.result.parent.mkdir(parents=True, exist_ok=True)
    arguments.result.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    append_job_summary(evidence)
    print(
        f"{arguments.label}: {elapsed:.3f}s selection, "
        f"{total_elapsed:.3f}s total (budget < {arguments.budget_seconds:.3f}s)"
    )
    if command_exit_code != 0:
        return command_exit_code
    if not budget_passed:
        print(
            f"{arguments.label}: budget exceeded "
            f"({total_elapsed:.3f}s >= {arguments.budget_seconds:.3f}s)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
