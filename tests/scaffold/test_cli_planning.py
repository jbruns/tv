import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.unit.planning_support import FIXTURE_ROOT, desired_xml, supplied_document


def _run(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = "37"
    environment["TZ"] = "Pacific/Honolulu"
    environment["LC_ALL"] = "C"
    return subprocess.run(
        [sys.executable, "-m", "coreelec_reconciler.cli.main", *arguments],
        cwd=Path(__file__).parent,
        env=environment,
        check=False,
        capture_output=True,
    )


def test_plan_cli_emits_canonical_json_plus_exactly_one_newline(
    tmp_path: Path,
) -> None:
    supplied = tmp_path / "observations.json"
    supplied.write_bytes(supplied_document(desired_xml()))

    result = _run(
        "--repository-root",
        str(FIXTURE_ROOT),
        "plan",
        "living-room.ugoos-am6b-plus",
        "--observations",
        str(supplied),
    )

    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout.endswith(b"}\n")
    assert not result.stdout.endswith(b"}\n\n")
    assert b'"kind":"CoreElecReconcilerPlan"' in result.stdout


def test_validate_cli_accepts_the_same_offline_observation(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURE_ROOT, repository)
    source_ledger = Path(__file__).parents[2] / "inventory" / "ownership-ledger.json"
    shutil.copy2(source_ledger, repository / "inventory" / "ownership-ledger.json")
    supplied = tmp_path / "observations.json"
    supplied.write_bytes(supplied_document(desired_xml()))

    result = _run(
        "--repository-root",
        str(repository),
        "validate",
        "--device-id",
        "living-room.ugoos-am6b-plus",
        "--observations",
        str(supplied),
    )

    assert result.returncode == 0
    assert result.stdout.startswith(b"inventory ledger valid:")
    assert result.stdout.endswith(b"\n")
    assert result.stderr == b""


def test_plan_cli_can_emit_the_nonmutating_run_report(tmp_path: Path) -> None:
    supplied = tmp_path / "observations.json"
    supplied.write_bytes(supplied_document(desired_xml()))

    result = _run(
        "--repository-root",
        str(FIXTURE_ROOT),
        "plan",
        "living-room.ugoos-am6b-plus",
        "--observations",
        str(supplied),
        "--document",
        "run",
    )

    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout.endswith(b"}\n")
    assert b'"kind":"CoreElecReconcilerRunReport"' in result.stdout


def test_blocked_plan_cli_emits_document_and_returns_three(tmp_path: Path) -> None:
    supplied = tmp_path / "observations.json"
    supplied.write_bytes(supplied_document(None, kind="symlink", mode="0777"))

    result = _run(
        "--repository-root",
        str(FIXTURE_ROOT),
        "plan",
        "living-room.ugoos-am6b-plus",
        "--observations",
        str(supplied),
    )

    assert result.returncode == 3
    assert result.stderr == b""
    assert result.stdout.endswith(b"}\n")
    assert b'"disposition":"blocked"' in result.stdout
