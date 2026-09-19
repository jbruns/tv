import json
import subprocess
import sys
from pathlib import Path

import pytest

from coreelec_reconciler.inventory.shell_permissions import (
    audit_shell_map,
    evaluate_shell_permission,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
MAP_PATH = REPOSITORY_ROOT / "inventory" / "shell-write-sets.json"
LEDGER_PATH = REPOSITORY_ROOT / "inventory" / "ownership-ledger.json"


def changed_ledger(tmp_path: Path, inventory_id: str, owner: str) -> Path:
    document = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    row = next(row for row in document["rows"] if row["id"] == inventory_id)
    row["current_owner_or_executor"] = owner
    path = tmp_path / "ownership-ledger.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_repository_shell_map_covers_every_shell_row() -> None:
    result = audit_shell_map(MAP_PATH, LEDGER_PATH)

    assert result.valid
    assert result.shell_inventory_rows == 146
    assert result.covered_shell_inventory_rows == 146
    assert result.unknown_targets == 2
    assert len(result.sha256) == 64


def test_audit_rejects_a_scope_coverage_claim_not_reached_by_operations(
    tmp_path: Path,
) -> None:
    document = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    skin = document["entry_points"]["provision-coreelec.sh"]["deploy"]["scopes"]["skin"]
    skin["inventory_ids"].remove("SKIN-025")
    path = tmp_path / "shell-write-sets.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = audit_shell_map(path, LEDGER_PATH)

    assert not result.valid
    assert "shell-map.coverage-mismatch:writes" in result.diagnostics


def test_audit_rejects_an_unknown_operation_that_is_not_fail_closed(
    tmp_path: Path,
) -> None:
    document = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    document["entry_points"]["provision-coreelec.sh"]["rollback"]["unknowns"] = []
    path = tmp_path / "shell-write-sets.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = audit_shell_map(path, LEDGER_PATH)

    assert not result.valid
    assert "shell-map.unknown-operation-mismatch" in result.diagnostics


def test_inventory_validation_command_includes_shell_audit() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_inventory_milestones.py"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "shell-audit rows=146 covered=146 unknowns=2 sha256=" in result.stdout


def test_skin_scope_expands_to_actual_cross_component_writes() -> None:
    result = evaluate_shell_permission(
        MAP_PATH,
        LEDGER_PATH,
        entry_point="provision-coreelec.sh",
        operation="deploy",
        scopes=("skin",),
        selected_addons=("script.plexmod",),
        harden_ssh=False,
    )

    assert result.allowed
    assert "SKIN-025" in result.inventory_ids
    assert "CORE-001" in result.inventory_ids
    assert "ART-007" in result.inventory_ids
    assert {"SKIN-017", "SKIN-018"} <= set(result.inventory_ids)
    assert {"EFFECT-001", "EFFECT-002", "EFFECT-004"} <= set(result.effect_ids)


def test_addons_scope_reaches_generated_skin_output_but_not_new_shows() -> None:
    result = evaluate_shell_permission(
        MAP_PATH,
        LEDGER_PATH,
        entry_point="provision-coreelec.sh",
        operation="deploy",
        scopes=("addons",),
        selected_addons=("script.plexmod",),
        harden_ssh=False,
    )

    assert result.allowed
    assert "ART-007" in result.inventory_ids
    assert {"SKIN-017", "SKIN-018"} <= set(result.inventory_ids)
    assert "SKIN-025" not in result.inventory_ids


def test_handoff_blocks_every_scope_that_reaches_new_shows(tmp_path: Path) -> None:
    ledger = changed_ledger(tmp_path, "SKIN-025", "python")

    skin = evaluate_shell_permission(
        MAP_PATH,
        ledger,
        entry_point="provision-coreelec.sh",
        operation="deploy",
        scopes=("skin",),
        selected_addons=("script.plexmod",),
        harden_ssh=False,
    )
    baseline = evaluate_shell_permission(
        MAP_PATH,
        ledger,
        entry_point="provision-coreelec.sh",
        operation="deploy",
        scopes=("baseline",),
        selected_addons=(),
        harden_ssh=False,
    )
    addons = evaluate_shell_permission(
        MAP_PATH,
        ledger,
        entry_point="provision-coreelec.sh",
        operation="deploy",
        scopes=("addons",),
        selected_addons=("script.plexmod",),
        harden_ssh=False,
    )

    assert not skin.allowed
    assert not baseline.allowed
    assert skin.blocked_inventory_ids == ("SKIN-025",)
    assert baseline.blocked_inventory_ids == ("SKIN-025",)
    assert addons.allowed


def test_unknown_component_name_is_rejected_instead_of_granting_permission() -> None:
    with pytest.raises(ValueError, match="unknown shell scope"):
        evaluate_shell_permission(
            MAP_PATH,
            LEDGER_PATH,
            entry_point="provision-coreelec.sh",
            operation="deploy",
            scopes=("new-shows",),
            selected_addons=(),
            harden_ssh=False,
        )


@pytest.mark.parametrize(
    ("entry_point", "operation"),
    [
        ("provision-coreelec.sh", "rollback"),
        ("configure-coreelec-addons.sh", "interactive"),
    ],
)
def test_untraceable_dynamic_targets_fail_closed(
    entry_point: str,
    operation: str,
) -> None:
    result = evaluate_shell_permission(
        MAP_PATH,
        LEDGER_PATH,
        entry_point=entry_point,
        operation=operation,
        scopes=(),
        selected_addons=(),
        harden_ssh=False,
    )

    assert not result.allowed
    assert result.unknowns


def test_new_shows_mode_conflict_is_explicit() -> None:
    document = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    conflict = document["known_conflicts"]["SKIN-025"]

    assert document["inventory_targets"]["SKIN-025"] == [
        "special://profile/playlists/video/NewShows.xsp"
    ]
    assert conflict["shell_mode"] == "0600"
    assert conflict["python_mode"] == "0644"
    assert conflict["shell_verifies_mode"] is False
