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
    document["coverage"]["writes"].remove("SKIN-025")
    path = tmp_path / "shell-write-sets.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = audit_shell_map(path, LEDGER_PATH)

    assert not result.valid
    assert "shell-map.coverage-mismatch:writes" in result.diagnostics


def test_audit_rejects_an_unknown_operation_that_is_not_fail_closed(
    tmp_path: Path,
) -> None:
    document = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    document["entry_points"]["provision-coreelec.sh"]["rollback"]["call_path_ids"] = []
    path = tmp_path / "shell-write-sets.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = audit_shell_map(path, LEDGER_PATH)

    assert not result.valid
    assert (
        "shell-map.operation-mismatch:provision-coreelec.sh:rollback"
        in result.diagnostics
    )


@pytest.mark.parametrize(
    "primitive_id",
    [
        "atomic-file-mutation",
        "addon-directory-replacement",
        "addon-registry-enablement",
        "service-state-effect",
        "skin-view-build",
        "lifecycle-gateway",
        "guided-addon-gui",
        "provision-rollback",
    ],
)
def test_audit_rejects_each_mutated_primitive_family(
    tmp_path: Path,
    primitive_id: str,
) -> None:
    document = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    primitive = next(
        item for item in document["primitive_families"] if item["id"] == primitive_id
    )
    primitive["call_paths"] = {}
    path = tmp_path / "shell-write-sets.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = audit_shell_map(path, LEDGER_PATH)

    assert not result.valid
    assert f"shell-map.primitive-mismatch:{primitive_id}" in result.diagnostics


@pytest.mark.parametrize(
    ("entry_point", "operation", "scope"),
    [
        ("provision-coreelec.sh", "deploy", "core"),
        ("provision-coreelec.sh", "deploy", "addons"),
        ("provision-coreelec.sh", "deploy", "skin"),
        ("configure-kodi-lifecycle.sh", "deploy", None),
    ],
)
def test_audit_rejects_a_locally_wrong_operation_call_path(
    tmp_path: Path,
    entry_point: str,
    operation: str,
    scope: str | None,
) -> None:
    document = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    record = document["entry_points"][entry_point][operation]
    if scope is not None:
        record = record["scopes"][scope]
    record["call_path_ids"] = []
    path = tmp_path / "shell-write-sets.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = audit_shell_map(path, LEDGER_PATH)

    key = f"{entry_point}:{operation}" + (f":{scope}" if scope else "")
    assert not result.valid
    assert f"shell-map.operation-mismatch:{key}" in result.diagnostics


def test_audit_rejects_a_swapped_selected_addon_inventory_id(
    tmp_path: Path,
) -> None:
    document = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    document["artifact_inventory_ids"]["script.plexmod"] = "ART-008"
    path = tmp_path / "shell-write-sets.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = audit_shell_map(path, LEDGER_PATH)

    assert not result.valid
    assert "shell-map.artifact-target-mismatch:script.plexmod" in result.diagnostics


def test_audit_rejects_a_missing_cross_component_scope_dependency(
    tmp_path: Path,
) -> None:
    document = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    document["entry_points"]["provision-coreelec.sh"]["deploy"]["dependencies"][
        "skin"
    ].remove("addons")
    path = tmp_path / "shell-write-sets.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    result = audit_shell_map(path, LEDGER_PATH)

    assert not result.valid
    assert "shell-map.scope-dependency-mismatch" in result.diagnostics


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
