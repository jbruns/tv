"""Audit and enforce legacy shell Device write permissions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ShellMapAudit:
    valid: bool
    diagnostics: tuple[str, ...]
    shell_inventory_rows: int
    covered_shell_inventory_rows: int
    unknown_targets: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ShellPermission:
    allowed: bool
    inventory_ids: tuple[str, ...]
    effect_ids: tuple[str, ...]
    blocked_inventory_ids: tuple[str, ...]
    unknowns: tuple[str, ...]


def _load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def _ids(prefix: str, start: int, end: int) -> set[str]:
    return {f"{prefix}-{number:03d}" for number in range(start, end + 1)}


def audit_shell_map(map_path: Path, ledger_path: Path) -> ShellMapAudit:
    content = map_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    document = json.loads(content)
    ledger = _load(ledger_path)
    diagnostics: list[str] = []

    if document.get("schema_version") != 1:
        diagnostics.append("shell-map.unsupported-version")
    if document.get("catalog") != "accepted-managed-state-v1":
        diagnostics.append("shell-map.invalid-catalog")

    ledger_rows = {
        row["id"]: row
        for row in ledger.get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    shell_ids = {
        inventory_id
        for inventory_id, row in ledger_rows.items()
        if row.get("current_owner_or_executor") == "shell"
    }
    shell_capable_ids = {
        inventory_id
        for inventory_id, row in ledger_rows.items()
        if isinstance(row.get("shell_write_set"), dict)
        and row["shell_write_set"].get("status") in {"audited", "frozen", "retired"}
    }
    coverage = document.get("coverage", {})
    declared_coverage = {
        key: {value for value in coverage.get(key, []) if isinstance(value, str)}
        for key in ("writes", "effects", "observations")
    }
    covered = set().union(*declared_coverage.values())
    unknown_ids = sorted(covered - ledger_rows.keys())
    if unknown_ids:
        diagnostics.append("shell-map.unknown-inventory-id:" + ",".join(unknown_ids))
    missing = sorted(shell_ids - covered)
    if missing:
        diagnostics.append("shell-map.missing-shell-row:" + ",".join(missing))
    inventory_targets = document.get("inventory_targets")
    if not isinstance(inventory_targets, dict):
        diagnostics.append("shell-map.invalid-inventory-targets")
    else:
        target_ids = set(inventory_targets)
        if target_ids != declared_coverage["writes"]:
            diagnostics.append("shell-map.inventory-target-coverage-mismatch")
        if any(
            not isinstance(items, list)
            or not items
            or not all(isinstance(item, str) and item for item in items)
            for items in inventory_targets.values()
        ):
            diagnostics.append("shell-map.invalid-inventory-target")

    operations = document.get("entry_points")
    if not isinstance(operations, dict):
        diagnostics.append("shell-map.invalid-entry-points")
    else:
        referenced_inventory: set[str] = set()
        referenced_effects: set[str] = set()
        provision = operations.get("provision-coreelec.sh", {}).get("deploy", {})
        referenced_inventory.update(provision.get("always_inventory_ids", ()))
        referenced_inventory.update(
            provision.get("harden_ssh", {}).get("inventory_ids", ())
        )
        referenced_effects.update(provision.get("harden_ssh", {}).get("effect_ids", ()))
        for scope in provision.get("scopes", {}).values():
            referenced_inventory.update(scope.get("inventory_ids", ()))
            referenced_effects.update(scope.get("effect_ids", ()))
        referenced_inventory.update(document.get("artifact_inventory_ids", {}).values())
        for entry_name, entry in operations.items():
            if entry_name == "provision-coreelec.sh":
                continue
            for record in entry.values():
                referenced_inventory.update(record.get("inventory_ids", ()))
                referenced_effects.update(record.get("effect_ids", ()))
                referenced_inventory.update(record.get("observations", ()))
        referenced_shell = (
            referenced_inventory | referenced_effects
        ) & shell_capable_ids
        expected_coverage = {
            "effects": {
                inventory_id
                for inventory_id in referenced_shell
                if ledger_rows[inventory_id].get("role") == "effect"
            },
            "observations": {
                inventory_id
                for inventory_id in referenced_shell
                if ledger_rows[inventory_id].get("role") == "guard"
                or inventory_id == "ADDON-003"
            },
        }
        expected_coverage["writes"] = (
            referenced_shell
            - expected_coverage["effects"]
            - expected_coverage["observations"]
        )
        for key in ("writes", "effects", "observations"):
            if declared_coverage[key] != expected_coverage[key]:
                diagnostics.append(f"shell-map.coverage-mismatch:{key}")
    unknowns = document.get("unknowns")
    if not isinstance(unknowns, list):
        diagnostics.append("shell-map.invalid-unknowns")
        unknown_count = 0
    else:
        unknown_count = len(unknowns)
        declared_unknowns = {
            unknown.get("id")
            for unknown in unknowns
            if isinstance(unknown, dict) and isinstance(unknown.get("id"), str)
        }
        operation_unknowns = {
            unknown
            for entry in document.get("entry_points", {}).values()
            for record in entry.values()
            for unknown in record.get("unknowns", ())
            if isinstance(unknown, str)
        }
        primitive_unknowns = {
            primitive.get("unknown")
            for primitive in document.get("mutation_primitives", ())
            if isinstance(primitive, dict) and isinstance(primitive.get("unknown"), str)
        }
        if (
            len(declared_unknowns) != len(unknowns)
            or operation_unknowns != declared_unknowns
            or primitive_unknowns != declared_unknowns
        ):
            diagnostics.append("shell-map.unknown-operation-mismatch")

    for inventory_id in shell_ids:
        row = ledger_rows[inventory_id]
        for field in ("shell_write_set", "permitted_effects"):
            value = row.get(field)
            if not isinstance(value, dict) or value.get("status") != "audited":
                diagnostics.append(
                    f"shell-map.ledger-row-not-audited:{inventory_id}:{field}"
                )

    return ShellMapAudit(
        valid=not diagnostics,
        diagnostics=tuple(diagnostics),
        shell_inventory_rows=len(shell_ids),
        covered_shell_inventory_rows=len(shell_ids & covered),
        unknown_targets=unknown_count,
        sha256=digest,
    )


def _provision_ids(
    document: dict[str, Any],
    scopes: tuple[str, ...],
    selected_addons: tuple[str, ...],
    harden_ssh: bool,
    apply_kodi: bool,
) -> tuple[set[str], set[str]]:
    provision = document["entry_points"]["provision-coreelec.sh"]["deploy"]
    scope_map = provision["scopes"]
    dependencies = provision["dependencies"]
    requested = set(scopes or (("baseline",) if apply_kodi else ()))
    unknown_scopes = requested - scope_map.keys()
    if unknown_scopes:
        raise ValueError(f"unknown shell scope: {sorted(unknown_scopes)[0]}")

    effective: set[str] = set()

    def expand(scope: str, stack: tuple[str, ...] = ()) -> None:
        if scope in stack:
            raise ValueError(f"shell scope dependency cycle at {scope}")
        if scope in effective:
            return
        for dependency in dependencies.get(scope, []):
            expand(dependency, (*stack, scope))
        effective.add(scope)

    for scope in requested:
        expand(scope)

    inventory_ids = set(provision["always_inventory_ids"])
    effect_ids: set[str] = set()
    for scope in effective:
        scope_record = scope_map[scope]
        inventory_ids.update(scope_record["inventory_ids"])
        effect_ids.update(scope_record["effect_ids"])

    if "addons" in effective:
        artifacts = document["artifact_inventory_ids"]
        if selected_addons:
            unknown_addons = set(selected_addons) - artifacts.keys()
            if unknown_addons:
                raise ValueError(f"unknown locked add-on: {sorted(unknown_addons)[0]}")
            inventory_ids.update(artifacts[addon] for addon in selected_addons)
        else:
            inventory_ids.update(artifacts.values())
    if harden_ssh:
        inventory_ids.update(provision["harden_ssh"]["inventory_ids"])
        effect_ids.update(provision["harden_ssh"]["effect_ids"])
    return inventory_ids, effect_ids


def evaluate_shell_permission(
    map_path: Path,
    ledger_path: Path,
    *,
    entry_point: str,
    operation: str,
    scopes: tuple[str, ...],
    selected_addons: tuple[str, ...],
    harden_ssh: bool,
    apply_kodi: bool = True,
) -> ShellPermission:
    document = _load(map_path)
    ledger = _load(ledger_path)
    audit = audit_shell_map(map_path, ledger_path)
    if not audit.valid:
        return ShellPermission(False, (), (), (), audit.diagnostics)

    entry_points = document["entry_points"]
    if entry_point not in entry_points:
        raise ValueError(f"unknown shell entry point: {entry_point}")
    entry = entry_points[entry_point]
    if operation not in entry:
        raise ValueError(f"unknown shell operation: {entry_point}:{operation}")
    operation_record = entry[operation]

    unknowns = tuple(operation_record.get("unknowns", ()))
    if unknowns:
        return ShellPermission(False, (), (), (), unknowns)

    if entry_point == "provision-coreelec.sh" and operation == "deploy":
        inventory_ids, effect_ids = _provision_ids(
            document,
            scopes,
            selected_addons,
            harden_ssh,
            apply_kodi,
        )
    else:
        inventory_ids = set(operation_record.get("inventory_ids", ()))
        effect_ids = set(operation_record.get("effect_ids", ()))

    rows = {row["id"]: row for row in ledger["rows"]}
    blocked = sorted(
        inventory_id
        for inventory_id in inventory_ids | effect_ids
        if rows[inventory_id]["current_owner_or_executor"] == "python"
        or rows[inventory_id]["shell_write_set"]["status"] in {"frozen", "retired"}
        or rows[inventory_id]["permitted_effects"]["status"] in {"frozen", "retired"}
    )
    return ShellPermission(
        allowed=not blocked,
        inventory_ids=tuple(sorted(inventory_ids)),
        effect_ids=tuple(sorted(effect_ids)),
        blocked_inventory_ids=tuple(blocked),
        unknowns=(),
    )


__all__ = [
    "ShellMapAudit",
    "ShellPermission",
    "audit_shell_map",
    "evaluate_shell_permission",
]
