import errno
import os
import pty
import subprocess
import sys
import termios
from collections.abc import Iterator
from pathlib import Path

import pydantic
import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
COMPOSITION_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "cli"
DEPENDENCY_SITE_PACKAGES = Path(pydantic.__file__).parents[1]
VERIFY_DOCUMENT = (
    b'{"kind":"CoreElecReconcilerRunReport","run_id":"verify-85",'
    b'"status":"converged"}\n'
)


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
    environment = _environment(scenario, extra_environment)
    return subprocess.run(
        [str(executable), *arguments],
        cwd=executable.parent,
        env=environment,
        check=False,
        capture_output=True,
    )


def _run_production(
    executable: Path,
    home: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.pop("COREELEC_RECONCILER_TEST_COMPOSITION", None)
    environment.pop("CLI_SCENARIO", None)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (
                environment.get("PYTHONPATH"),
                str(DEPENDENCY_SITE_PACKAGES),
            ),
        )
    )
    environment.update(
        {
            "HOME": str(home),
            "LC_ALL": "C",
            "PYTHONHASHSEED": "73",
            "TERM": "dumb",
            "TZ": "UTC",
        }
    )
    return subprocess.run(
        [str(executable), *arguments],
        cwd=executable.parent,
        env=environment,
        check=False,
        capture_output=True,
    )


def _environment(
    scenario: str = "",
    extra_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("NO_COLOR", None)
    environment.update(
        {
            "COREELEC_RECONCILER_TEST_COMPOSITION": "1",
            "LC_ALL": "C",
            "PYTHONHASHSEED": "73",
            "PYTHONPATH": os.pathsep.join(
                (str(COMPOSITION_ROOT), str(DEPENDENCY_SITE_PACKAGES))
            ),
            "TERM": "dumb",
            "TZ": "Pacific/Honolulu",
        }
    )
    if scenario:
        environment["CLI_SCENARIO"] = scenario
    if extra_environment:
        environment.update(extra_environment)
    return environment


def _run_with_stderr_pty(
    executable: Path,
    *arguments: str,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    master, slave = pty.openpty()
    attributes = termios.tcgetattr(slave)
    attributes[1] &= ~termios.ONLCR
    termios.tcsetattr(slave, termios.TCSANOW, attributes)
    process = subprocess.Popen(
        [str(executable), *arguments],
        cwd=executable.parent,
        env=_environment(extra_environment=extra_environment),
        stdout=subprocess.PIPE,
        stderr=slave,
    )
    os.close(slave)
    stderr_parts: list[bytes] = []
    try:
        while part := os.read(master, 4096):
            stderr_parts.append(part)
    except OSError as error:
        if error.errno != errno.EIO:
            raise
    finally:
        os.close(master)
    stdout, _ = process.communicate()
    return subprocess.CompletedProcess(
        process.args,
        process.returncode,
        stdout,
        b"".join(stderr_parts),
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
        extra_environment={
            "LC_ALL": "C",
            "PYTHONHASHSEED": "1",
            "TZ": "UTC",
        },
    )
    second = _run(
        installed_cli,
        "--quiet",
        "verify",
        "device",
        extra_environment={
            "LC_ALL": "C.UTF-8",
            "PYTHONHASHSEED": "991",
            "TZ": "Pacific/Honolulu",
        },
    )

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout == VERIFY_DOCUMENT
    assert first.stderr == second.stderr == b""


@pytest.mark.parametrize(
    ("arguments", "diagnostic"),
    [
        (("observe", "living-room.ugoos-am6b-plus"), b"observation-unavailable"),
        (("apply", "plan.missing"), b"saved-plan-rejected"),
        (("reconcile", "living-room.ugoos-am6b-plus"), b"device.session-unavailable"),
        (("verify", "living-room.ugoos-am6b-plus"), b"verification-unavailable"),
        (("recover", "run.missing", "inspect"), b"inspect-unavailable"),
        (("report", "run.missing"), b"run-not-found"),
    ],
)
def test_installed_wheel_uses_genuine_production_composition_offline(
    installed_cli: Path,
    tmp_path: Path,
    arguments: tuple[str, ...],
    diagnostic: bytes,
) -> None:
    result = _run_production(
        installed_cli,
        tmp_path,
        "--repository-root",
        str(REPOSITORY_ROOT / "tests" / "fixtures" / "repository"),
        *arguments,
    )

    assert result.returncode == 3
    assert result.stdout == b""
    assert diagnostic in result.stderr
    assert b"not_implemented" not in result.stderr


def test_installed_wheel_runs_real_production_graph_with_adapter_seams(
    installed_cli: Path,
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("COREELEC_RECONCILER_TEST_COMPOSITION", None)
    environment["PYTHONPATH"] = str(DEPENDENCY_SITE_PACKAGES)
    script = """
import socket
import sys
from pathlib import Path

import coreelec_reconciler

installed = Path(coreelec_reconciler.__file__).resolve()
assert "site-packages" in str(installed), installed
sys.path.insert(0, sys.argv[1])
from tests.integration.test_production_composition import (
    test_bootstrap_composes_all_workflows_and_restart_recovery,
)

def forbidden_socket(*args, **kwargs):
    raise AssertionError("installed production scenario attempted a socket")

socket.socket = forbidden_socket
test_bootstrap_composes_all_workflows_and_restart_recovery(Path(sys.argv[2]))
print("installed production composition: passed")
"""

    result = subprocess.run(
        [
            str(installed_cli.parent / "python"),
            "-c",
            script,
            str(REPOSITORY_ROOT),
            str(tmp_path / "scenario"),
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"installed production composition: passed\n"
    assert b"Traceback" not in result.stderr


def test_installed_non_tty_disables_color_with_normal_term(
    installed_cli: Path,
) -> None:
    result = _run(
        installed_cli,
        "verify",
        "device",
        extra_environment={"TERM": "xterm-256color"},
    )

    assert result.returncode == 0
    assert result.stdout == VERIFY_DOCUMENT
    assert result.stderr == (
        b"progress: observed caf\xc3\xa9 Resource\nstatus: converged\n"
    )
    assert b"\x1b[" not in result.stderr


@pytest.mark.parametrize(
    ("extra_environment", "color_enabled"),
    [
        ({"TERM": "xterm-256color"}, True),
        ({"TERM": "xterm-256color", "NO_COLOR": "1"}, False),
        ({"TERM": "dumb"}, False),
    ],
)
def test_installed_tty_color_contract(
    installed_cli: Path,
    extra_environment: dict[str, str],
    color_enabled: bool,
) -> None:
    result = _run_with_stderr_pty(
        installed_cli,
        "verify",
        "device",
        extra_environment=extra_environment,
    )

    assert result.returncode == 0
    assert result.stdout == VERIFY_DOCUMENT
    assert result.stderr.startswith(b"progress: observed caf\xc3\xa9 Resource\n")
    assert result.stderr.endswith(b"status: converged\x1b[0m\n") is color_enabled
    assert (b"\x1b[" in result.stderr) is color_enabled


def test_installed_modeled_blocked_outcome_is_exit_three_with_document(
    installed_cli: Path,
) -> None:
    result = _run(
        installed_cli,
        "verify",
        "device",
        scenario="blocked",
        extra_environment={"TERM": "xterm-256color"},
    )

    assert result.returncode == 3
    assert result.stdout == (
        b'{"kind":"CoreElecReconcilerRunReport","run_id":"verify-85",'
        b'"status":"blocked"}\n'
    )
    assert result.stderr == (
        b"progress: observed caf\xc3\xa9 Resource\nstatus: blocked\n"
    )
    assert b"\x1b[" not in result.stdout + result.stderr


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
            "PYTHONPATH": os.pathsep.join(
                (str(COMPOSITION_ROOT), str(DEPENDENCY_SITE_PACKAGES))
            ),
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
