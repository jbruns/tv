import subprocess
import sys
from pathlib import Path

import pytest

from coreelec_reconciler import __version__

SCAFFOLD_TEST_DIRECTORY = Path(__file__).parent
REPOSITORY_ROOT = Path(__file__).parents[2]


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "coreelec_reconciler.cli.main", *arguments],
        cwd=SCAFFOLD_TEST_DIRECTORY,
        check=False,
        capture_output=True,
        text=True,
    )


def test_version_needs_no_device_or_desired_configuration() -> None:
    result = run_cli("--version")

    assert result.returncode == 0
    assert result.stdout == f"coreelec-reconciler {__version__}\n"
    assert result.stderr == ""


def test_help_needs_no_device_or_desired_configuration() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert result.stdout.startswith("usage: coreelec-reconciler")
    assert "Reconcile CoreELEC Device Desired State." in result.stdout
    assert result.stderr == ""


def test_validate_fails_closed_when_the_ledger_is_missing() -> None:
    result = run_cli("--repository-root", "/missing", "validate")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "ledger.unreadable" in result.stderr


def test_validate_checks_the_inventory_ledger() -> None:
    result = run_cli(
        "--repository-root",
        str(REPOSITORY_ROOT),
        "validate",
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr.startswith(
        "inventory ledger valid: rows=169 migrate=153 outside=11 retire=5 sha256="
    )


@pytest.mark.parametrize(
    ("arguments", "command_name"),
    [
        (("inventory",), "inventory"),
        (("action", "example"), "action"),
    ],
)
def test_closed_cli_commands_fail_explicitly(
    arguments: tuple[str, ...],
    command_name: str,
) -> None:
    result = run_cli(*arguments)

    assert result.returncode == 3
    assert result.stdout == ""
    assert result.stderr == (
        f"{command_name}: not_implemented (application.command-not-implemented)\n"
    )
