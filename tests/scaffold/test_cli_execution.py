import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
COMPOSITION_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "cli"


@pytest.fixture(scope="module")
def installed_cli(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("installed-cli")
    dist = root / "dist"
    environment = os.environ.copy()
    environment.update(
        {
            "LC_ALL": "C",
            "PYTHONHASHSEED": "73",
            "TZ": "Pacific/Honolulu",
        }
    )
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )
    environment_path = root / "environment"
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(environment_path)],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
    )
    wheel = next(dist.glob("*.whl"))
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(environment_path / "bin" / "python"),
            "--no-deps",
            str(wheel),
        ],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
    )
    yield environment_path / "bin" / "coreelec-reconciler"


def _run(
    executable: Path,
    *arguments: str,
    scenario: str = "",
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.update(
        {
            "COREELEC_RECONCILER_TEST_COMPOSITION": "1",
            "LC_ALL": "C",
            "PYTHONHASHSEED": "73",
            "PYTHONPATH": str(COMPOSITION_ROOT),
            "TERM": "dumb",
            "TZ": "Pacific/Honolulu",
        }
    )
    if scenario:
        environment["CLI_SCENARIO"] = scenario
    if extra_environment:
        environment.update(extra_environment)
    return subprocess.run(
        [str(executable), *arguments],
        cwd=executable.parent,
        env=environment,
        check=False,
        capture_output=True,
    )


@pytest.mark.parametrize(
    ("arguments", "scenario", "exit_code", "run_id"),
    [
        (("observe", "device"), "", 0, "observe-85"),
        (("apply", "plan-85", "--approve", "apply"), "", 0, "apply-85"),
        (
            ("reconcile", "device", "--approve", "apply"),
            "known-failure",
            4,
            "execution-85",
        ),
        (
            ("reconcile", "device", "--approve", "apply"),
            "recovery-required",
            5,
            "execution-85",
        ),
        (("verify", "device"), "", 0, "verify-85"),
        (("report", "execution-85"), "", 0, "execution-85"),
        (
            ("recover", "execution-85", "resume-verification"),
            "",
            0,
            "execution-85",
        ),
        (
            ("recover", "execution-85", "rollback"),
            "rollback",
            4,
            "execution-85",
        ),
        (
            ("recover", "execution-85", "finalize", "--mode", "normal"),
            "",
            0,
            "execution-85",
        ),
        (
            (
                "recover",
                "execution-85",
                "finalize",
                "--mode",
                "abandon",
                "--approve",
                "recover.abandon",
                "--reason",
                "Device reimage scheduled",
            ),
            "",
            0,
            "execution-85",
        ),
    ],
)
def test_installed_wheel_execution_journeys(
    installed_cli: Path,
    arguments: tuple[str, ...],
    scenario: str,
    exit_code: int,
    run_id: str,
) -> None:
    result = _run(installed_cli, *arguments, scenario=scenario)

    assert result.returncode == exit_code
    assert f'"run_id":"{run_id}"'.encode() in result.stdout
    assert result.stdout.endswith(b"}\n")
    assert not result.stdout.endswith(b"\n\n")
    assert b"\x1b[" not in result.stdout
    assert b"Traceback" not in result.stderr
    if exit_code == 5:
        assert result.stderr.endswith(
            b"NEXT: coreelec-reconciler recover execution-85 inspect\n"
        )


def test_installed_reconcile_without_approval_emits_handoff(
    installed_cli: Path,
) -> None:
    result = _run(installed_cli, "--quiet", "reconcile", "device")

    assert result.returncode == 0
    assert result.stdout.endswith(b"}\n")
    assert b'"status":"awaiting_approval"' in result.stdout
    assert result.stderr == (
        b"NEXT: coreelec-reconciler apply plan-85 "
        b"--approve apply --approve impact.restart\n"
    )


def test_installed_inspection_prints_only_computed_legal_actions(
    installed_cli: Path,
) -> None:
    result = _run(
        installed_cli,
        "--quiet",
        "recover",
        "execution-85",
        "inspect",
    )

    assert result.returncode == 0
    assert result.stdout.endswith(b"}\n")
    assert result.stderr == (
        b"NEXT: coreelec-reconciler recover execution-85 resume-verification\n"
        b"NEXT: coreelec-reconciler recover execution-85 finalize --mode abandon "
        b"--approve recover.abandon --reason REASON\n"
    )
    assert b"rollback" not in result.stderr


def test_installed_cleanup_uncertainty_preserves_converged_truth(
    installed_cli: Path,
) -> None:
    result = _run(
        installed_cli,
        "--quiet",
        "reconcile",
        "device",
        "--approve",
        "apply",
        scenario="cleanup-unresolved",
    )

    assert result.returncode == 5
    assert b'"status":"converged"' in result.stdout
    assert result.stderr == (
        b"NEXT: coreelec-reconciler recover execution-85 inspect\n"
    )


def test_installed_quiet_color_environment_and_contamination(
    installed_cli: Path,
) -> None:
    result = _run(
        installed_cli,
        "--quiet",
        "verify",
        "device",
        extra_environment={
            "NO_COLOR": "1",
            "CLI_SECRET_SENTINEL": "secret-never-render",
        },
    )

    assert result.returncode == 0
    assert result.stderr == b""
    assert b"\x1b[" not in result.stdout
    assert b"secret-never-render" not in result.stdout


def test_installed_output_is_environment_deterministic(installed_cli: Path) -> None:
    first = _run(
        installed_cli,
        "--quiet",
        "verify",
        "device",
        extra_environment={"PYTHONHASHSEED": "1", "TZ": "UTC"},
    )
    second = _run(
        installed_cli,
        "--quiet",
        "verify",
        "device",
        extra_environment={"PYTHONHASHSEED": "991", "TZ": "Pacific/Honolulu"},
    )

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert first.stderr == second.stderr == b""


def test_installed_progress_and_status_are_utf8_stderr(
    installed_cli: Path,
) -> None:
    result = _run(installed_cli, "verify", "device")

    assert result.returncode == 0
    assert result.stdout.endswith(b"}\n")
    assert result.stderr == (
        b"progress: observed caf\xc3\xa9 Resource\nstatus: converged\n"
    )


def test_installed_broken_pipe_has_no_traceback(installed_cli: Path) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "COREELEC_RECONCILER_TEST_COMPOSITION": "1",
            "PYTHONPATH": str(COMPOSITION_ROOT),
            "TERM": "dumb",
        }
    )
    process = subprocess.Popen(
        [str(installed_cli), "--quiet", "verify", "device"],
        cwd=installed_cli.parent,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    process.stdout.close()
    stderr = process.stderr.read() if process.stderr is not None else b""
    return_code = process.wait()

    assert return_code == 0
    assert b"Traceback" not in stderr


def test_installed_defect_is_exit_one_and_redacted(installed_cli: Path) -> None:
    result = _run(
        installed_cli,
        "verify",
        "device",
        scenario="defect",
        extra_environment={"CLI_SECRET_SENTINEL": "secret-never-render"},
    )

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr.endswith(
        b"coreelec-reconciler: internal error; no unsafe details emitted\n"
    )
    assert b"secret-never-render" not in result.stderr
    assert b"/private/controller/path" not in result.stderr
    assert b"Traceback" not in result.stderr


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
def test_installed_abandon_requires_dedicated_approval_and_reason(
    installed_cli: Path,
    arguments: tuple[str, ...],
) -> None:
    result = _run(installed_cli, *arguments)

    assert result.returncode == 2
    assert result.stdout == b""
    assert b"error:" in result.stderr
    assert b"Traceback" not in result.stderr
