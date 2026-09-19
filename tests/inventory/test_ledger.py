import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from coreelec_reconciler.application.commands import ValidateCommand
from coreelec_reconciler.application.outcomes import ValidationOutcome
from coreelec_reconciler.bootstrap import BootstrapSettings, bootstrap
from coreelec_reconciler.inventory.ledger import validate_ledger

REPOSITORY_ROOT = Path(__file__).parents[2]
LEDGER_PATH = REPOSITORY_ROOT / "inventory" / "ownership-ledger.json"


def write_changed_ledger(
    tmp_path: Path,
    change: Callable[[dict[str, Any]], None],
) -> Path:
    document = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    change(document)
    path = tmp_path / "ownership-ledger.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def diagnostic_codes(path: Path) -> set[str]:
    return {diagnostic.code for diagnostic in validate_ledger(path).diagnostics}


def test_repository_ledger_has_the_accepted_catalog_and_totals() -> None:
    result = validate_ledger(LEDGER_PATH)
    document = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    rows_by_id = {row["id"]: row for row in document["rows"]}

    assert result.valid
    assert result.row_count == 169
    assert result.disposition_totals == {
        "migrate": 153,
        "outside": 11,
        "retire": 5,
    }
    assert result.role_totals == {
        "effect": 5,
        "guard": 5,
        "guided-action": 6,
        "resource": 128,
        "run-infrastructure": 4,
        "unmanaged-inventory-fact": 21,
    }
    assert rows_by_id["ADDON-003"]["closure"]["state"] == "open"
    assert rows_by_id["ADDON-003"]["current_owner_or_executor"] == "shell"
    assert rows_by_id["SVC-014"]["closure"]["state"] == "open"
    assert rows_by_id["SVC-014"]["current_owner_or_executor"] == "shell"


def test_bootstrapped_validate_command_checks_the_repository_ledger() -> None:
    outcome = bootstrap(BootstrapSettings(str(REPOSITORY_ROOT))).execute(
        ValidateCommand(repository_root=str(REPOSITORY_ROOT))
    )

    assert isinstance(outcome, ValidationOutcome)
    assert outcome.valid
    assert outcome.row_count == 169
    assert len(outcome.sha256) == 64


def test_ledger_validation_command_emits_a_sorted_audit() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_inventory_milestones.py"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.startswith(
        "id | role | disposition | milestone | current_owner | closure"
    )
    assert "validated rows=169 migrate=153 outside=11 retire=5 sha256=" in result.stdout


@pytest.mark.parametrize(
    ("change", "expected_code"),
    [
        (
            lambda document: document["rows"].append(document["rows"][0].copy()),
            "ledger.duplicate-id",
        ),
        (
            lambda document: document["rows"][0].update({"id": "UNKNOWN-001"}),
            "ledger.unknown-id",
        ),
        (
            lambda document: document["rows"].pop(),
            "ledger.missing-id",
        ),
        (
            lambda document: document["accepted_totals"]["dispositions"].update(
                {"migrate": 152}
            ),
            "ledger.bad-totals",
        ),
        (
            lambda document: document["rows"][0]["closure"].update(
                {"state": "retired"}
            ),
            "ledger.invalid-role-closure",
        ),
    ],
)
def test_ledger_rejects_invalid_catalog_state(
    tmp_path: Path,
    change: Callable[[dict[str, Any]], None],
    expected_code: str,
) -> None:
    assert expected_code in diagnostic_codes(write_changed_ledger(tmp_path, change))


def test_ledger_rejects_conflicting_transfers(tmp_path: Path) -> None:
    def add_conflicting_transfers(document: dict[str, Any]) -> None:
        row = document["rows"][0]
        row["transfers"] = [
            {
                "sequence": 1,
                "from": "shell",
                "to": "python",
                "milestone": "M8",
                "issue": 100,
                "pull_request": 101,
                "prestate_evidence": "evidence/prestate.json",
                "handoff_evidence": "evidence/handoff.json",
                "acceptance_evidence": "evidence/acceptance.json",
                "former_owner_freeze_evidence": "evidence/freeze.json",
                "documentation": "docs/operations/example.md",
            },
            {
                "sequence": 1,
                "from": "shell",
                "to": "repository",
                "milestone": "M8",
                "issue": 102,
                "pull_request": 103,
                "prestate_evidence": "evidence/prestate-2.json",
                "handoff_evidence": "evidence/handoff-2.json",
                "acceptance_evidence": "evidence/acceptance-2.json",
                "former_owner_freeze_evidence": "evidence/freeze-2.json",
                "documentation": "docs/operations/example-2.md",
            },
        ]

    assert "ledger.conflicting-transfer" in diagnostic_codes(
        write_changed_ledger(tmp_path, add_conflicting_transfers)
    )


def test_ledger_rejects_out_of_order_transfers(tmp_path: Path) -> None:
    def add_out_of_order_transfers(document: dict[str, Any]) -> None:
        row = document["rows"][0]
        transfer = {
            "from": "shell",
            "to": "python",
            "milestone": row["milestone"],
            "issue": 100,
            "pull_request": 101,
            "prestate_evidence": "evidence/prestate.json",
            "handoff_evidence": "evidence/handoff.json",
            "acceptance_evidence": "evidence/acceptance.json",
            "former_owner_freeze_evidence": "evidence/freeze.json",
            "documentation": "docs/operations/example.md",
        }
        row["current_owner_or_executor"] = "python"
        row["transfers"] = [
            {"sequence": 2, **transfer},
        ]

    assert "ledger.conflicting-transfer" in diagnostic_codes(
        write_changed_ledger(tmp_path, add_out_of_order_transfers)
    )


def test_ledger_rejects_transfer_for_the_wrong_milestone(tmp_path: Path) -> None:
    def add_wrong_milestone_transfer(document: dict[str, Any]) -> None:
        row = document["rows"][0]
        row["current_owner_or_executor"] = "python"
        row["transfers"] = [
            {
                "sequence": 1,
                "from": "shell",
                "to": "python",
                "milestone": "M4" if row["milestone"] != "M4" else "M5",
                "issue": 100,
                "pull_request": 101,
                "prestate_evidence": "evidence/prestate.json",
                "handoff_evidence": "evidence/handoff.json",
                "acceptance_evidence": "evidence/acceptance.json",
                "former_owner_freeze_evidence": "evidence/freeze.json",
                "documentation": "docs/operations/example.md",
            }
        ]

    assert "ledger.conflicting-transfer" in diagnostic_codes(
        write_changed_ledger(tmp_path, add_wrong_milestone_transfer)
    )
