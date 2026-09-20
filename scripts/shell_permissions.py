"""Audit and enforce legacy shell Device write permissions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

type JsonObject = dict[str, Any]


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


def _range(prefix: str, start: int, end: int) -> list[str]:
    return [f"{prefix}-{number:03d}" for number in range(start, end + 1)]


def _binding(
    inventory_ids: list[str] | None = None,
    effect_ids: list[str] | None = None,
    observation_ids: list[str] | None = None,
    outside_inventory_ids: list[str] | None = None,
    *,
    selection: str | None = None,
    unknown: str | None = None,
) -> JsonObject:
    result: JsonObject = {
        "inventory_ids": inventory_ids or [],
        "effect_ids": effect_ids or [],
        "observation_ids": observation_ids or [],
        "outside_inventory_ids": outside_inventory_ids or [],
    }
    if selection is not None:
        result["selection"] = selection
    if unknown is not None:
        result["unknown"] = unknown
    return result


EXPECTED_PRIMITIVE_CALL_PATHS: Final[dict[str, dict[str, JsonObject]]] = {
    "atomic-file-mutation": {
        "provision.bootstrap-admin-key": _binding(outside_inventory_ids=["SSH-002"]),
        "provision.harden-ssh": _binding(["SSH-003"]),
        "provision.core-settings": _binding(
            _range("CORE", 1, 6) + _range("CORE", 8, 29)
        ),
        "provision.cec-settings": _binding(_range("CEC", 1, 5)),
        "provision.services-settings": _binding(_range("SVC", 1, 17)),
        "provision.skin-settings": _binding(
            _range("SKIN", 1, 16) + _range("SKIN", 19, 28)
        ),
        "provision.room-settings": _binding(_range("ROOM", 1, 11)),
    },
    "addon-directory-replacement": {
        "provision.selected-addon-directories": _binding(
            selection="artifact_inventory_ids"
        )
    },
    "addon-registry-enablement": {
        "provision.selected-addon-enablement": _binding(["ADDON-001"])
    },
    "service-state-effect": {
        "provision.kodi-timezone-effects": _binding(
            ["CORE-007"],
            ["EFFECT-001", "EFFECT-002"],
        ),
        "provision.sshd-effect": _binding(effect_ids=["EFFECT-003"]),
    },
    "skin-view-build": {
        "provision.buildviews": _binding(
            ["SKIN-017", "SKIN-018"],
            ["EFFECT-004"],
        )
    },
    "lifecycle-gateway": {
        "lifecycle.deploy": _binding(
            ["LIFE-001", "LIFE-002"],
            ["LIFE-003"],
        ),
        "lifecycle.rollback": _binding(
            ["LIFE-001", "LIFE-002"],
            ["LIFE-003"],
        ),
    },
    "guided-addon-gui": {
        "addons.interactive": _binding(
            unknown="addon-owned-state-mutated-by-guided-GUI-workflow"
        )
    },
    "provision-rollback": {
        "provision.rollback": _binding(
            unknown="provision-rollback-transaction-write-set"
        )
    },
}

EXPECTED_OBSERVATION_CALL_PATHS: Final[dict[str, JsonObject]] = {
    "provision.preflight": _binding(
        observation_ids=["PLAT-001", "PLAT-002", "SSH-004"]
    ),
    "provision.addon-inventory": _binding(observation_ids=["ADDON-003"]),
    "addons.observe": _binding(observation_ids=_range("GUIDE", 1, 8)),
    "lifecycle.preflight": _binding(observation_ids=["PLAT-004", "PLAT-005"]),
}

EXPECTED_OPERATION_CALL_PATHS: Final[dict[str, tuple[str, ...]]] = {
    "provision-coreelec.sh:deploy:always": (
        "provision.preflight",
        "provision.bootstrap-admin-key",
    ),
    "provision-coreelec.sh:deploy:baseline": (),
    "provision-coreelec.sh:deploy:core": (
        "provision.core-settings",
        "provision.kodi-timezone-effects",
    ),
    "provision-coreelec.sh:deploy:cec": (
        "provision.cec-settings",
        "provision.kodi-timezone-effects",
    ),
    "provision-coreelec.sh:deploy:addons": (
        "provision.selected-addon-directories",
        "provision.selected-addon-enablement",
        "provision.addon-inventory",
        "provision.kodi-timezone-effects",
        "provision.buildviews",
    ),
    "provision-coreelec.sh:deploy:services": (
        "provision.services-settings",
        "provision.kodi-timezone-effects",
    ),
    "provision-coreelec.sh:deploy:skin": (
        "provision.skin-settings",
        "provision.kodi-timezone-effects",
        "provision.buildviews",
    ),
    "provision-coreelec.sh:deploy:room": (
        "provision.room-settings",
        "provision.kodi-timezone-effects",
    ),
    "provision-coreelec.sh:deploy:harden-ssh": (
        "provision.harden-ssh",
        "provision.sshd-effect",
    ),
    "provision-coreelec.sh:finalize": (),
    "provision-coreelec.sh:rollback": ("provision.rollback",),
    "configure-coreelec-addons.sh:observe": ("addons.observe",),
    "configure-coreelec-addons.sh:interactive": (
        "addons.observe",
        "addons.interactive",
    ),
    "configure-kodi-lifecycle.sh:deploy": (
        "lifecycle.preflight",
        "lifecycle.deploy",
    ),
    "configure-kodi-lifecycle.sh:rollback": ("lifecycle.rollback",),
    "configure-kodi-lifecycle.sh:finalize": (),
    "configure-kodi-lifecycle.sh:inspect": (),
}

EXPECTED_SCOPE_DEPENDENCIES: Final[dict[str, tuple[str, ...]]] = {
    "baseline": ("core", "cec", "addons", "services", "skin"),
    "core": (),
    "cec": (),
    "addons": (),
    "services": ("addons",),
    "skin": ("core", "addons"),
    "room": ("core",),
}


def _load(path: Path) -> JsonObject:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def _operation_call_paths(document: JsonObject) -> dict[str, tuple[str, ...]]:
    entry_points = document["entry_points"]
    result: dict[str, tuple[str, ...]] = {}
    provision = entry_points["provision-coreelec.sh"]
    deploy = provision["deploy"]
    result["provision-coreelec.sh:deploy:always"] = tuple(
        deploy["always_call_path_ids"]
    )
    for scope, record in deploy["scopes"].items():
        result[f"provision-coreelec.sh:deploy:{scope}"] = tuple(record["call_path_ids"])
    result["provision-coreelec.sh:deploy:harden-ssh"] = tuple(
        deploy["harden_ssh"]["call_path_ids"]
    )
    for operation in ("finalize", "rollback"):
        result[f"provision-coreelec.sh:{operation}"] = tuple(
            provision[operation]["call_path_ids"]
        )
    for entry_point in (
        "configure-coreelec-addons.sh",
        "configure-kodi-lifecycle.sh",
    ):
        for operation, record in entry_points[entry_point].items():
            result[f"{entry_point}:{operation}"] = tuple(record["call_path_ids"])
    return result


def _primitive_registry(
    document: JsonObject,
    diagnostics: list[str],
) -> dict[str, JsonObject]:
    primitives = document.get("primitive_families")
    if not isinstance(primitives, list):
        diagnostics.append("shell-map.invalid-primitive-families")
        return {}
    by_id: dict[str, JsonObject] = {}
    call_paths: dict[str, JsonObject] = {}
    authoritative_targets = {
        **document.get("inventory_targets", {}),
        **document.get("outside_inventory_targets", {}),
    }
    for primitive in primitives:
        if not isinstance(primitive, dict) or not isinstance(primitive.get("id"), str):
            diagnostics.append("shell-map.invalid-primitive-family")
            continue
        primitive_id = primitive["id"]
        if primitive_id in by_id:
            diagnostics.append(f"shell-map.duplicate-primitive:{primitive_id}")
            continue
        by_id[primitive_id] = primitive
        expected_paths = EXPECTED_PRIMITIVE_CALL_PATHS.get(primitive_id)
        if primitive.get("call_paths") != expected_paths:
            diagnostics.append(f"shell-map.primitive-mismatch:{primitive_id}")
        for call_path_id, binding in primitive.get("call_paths", {}).items():
            if call_path_id in call_paths:
                diagnostics.append(f"shell-map.duplicate-call-path:{call_path_id}")
            call_paths[call_path_id] = binding
        declared_targets = primitive.get("inventory_targets")
        target_ids = {
            inventory_id
            for binding in primitive.get("call_paths", {}).values()
            for inventory_id in (
                binding.get("inventory_ids", [])
                + binding.get("outside_inventory_ids", [])
            )
        }
        if any(
            binding.get("selection") == "artifact_inventory_ids"
            for binding in primitive.get("call_paths", {}).values()
        ):
            target_ids.update(document.get("artifact_inventory_ids", {}).values())
        expected_targets = {
            inventory_id: authoritative_targets.get(inventory_id)
            for inventory_id in sorted(target_ids)
        }
        if declared_targets != expected_targets:
            diagnostics.append(f"shell-map.primitive-target-mismatch:{primitive_id}")
    missing_primitives = set(EXPECTED_PRIMITIVE_CALL_PATHS) - by_id.keys()
    for primitive_id in sorted(missing_primitives):
        diagnostics.append(f"shell-map.primitive-mismatch:{primitive_id}")
    extra_primitives = by_id.keys() - set(EXPECTED_PRIMITIVE_CALL_PATHS)
    for primitive_id in sorted(extra_primitives):
        diagnostics.append(f"shell-map.unexpected-primitive:{primitive_id}")
    return call_paths


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
        inventory_targets = {}
    else:
        if set(inventory_targets) != declared_coverage["writes"]:
            diagnostics.append("shell-map.inventory-target-coverage-mismatch")
        if any(
            not isinstance(items, list)
            or not items
            or not all(isinstance(item, str) and item for item in items)
            for items in inventory_targets.values()
        ):
            diagnostics.append("shell-map.invalid-inventory-target")
        for inventory_id, targets in inventory_targets.items():
            ledger_items = (
                ledger_rows.get(inventory_id, {})
                .get("shell_write_set", {})
                .get("items")
            )
            if targets != ledger_items:
                diagnostics.append(f"shell-map.ledger-target-mismatch:{inventory_id}")

    call_paths = _primitive_registry(document, diagnostics)
    observation_paths = document.get("call_paths")
    if observation_paths != EXPECTED_OBSERVATION_CALL_PATHS:
        diagnostics.append("shell-map.observation-call-path-mismatch")
    if isinstance(observation_paths, dict):
        for call_path_id, binding in observation_paths.items():
            if call_path_id in call_paths:
                diagnostics.append(f"shell-map.duplicate-call-path:{call_path_id}")
            call_paths[call_path_id] = binding

    try:
        actual_operations = _operation_call_paths(document)
    except KeyError, TypeError, AttributeError:
        diagnostics.append("shell-map.invalid-entry-points")
        actual_operations = {}
    for key, expected in EXPECTED_OPERATION_CALL_PATHS.items():
        if actual_operations.get(key) != expected:
            diagnostics.append(f"shell-map.operation-mismatch:{key}")
    for key in sorted(actual_operations.keys() - EXPECTED_OPERATION_CALL_PATHS.keys()):
        diagnostics.append(f"shell-map.unexpected-operation:{key}")
    try:
        actual_dependencies = {
            scope: tuple(dependencies)
            for scope, dependencies in document["entry_points"][
                "provision-coreelec.sh"
            ]["deploy"]["dependencies"].items()
        }
    except KeyError, TypeError, AttributeError:
        actual_dependencies = {}
    if actual_dependencies != EXPECTED_SCOPE_DEPENDENCIES:
        diagnostics.append("shell-map.scope-dependency-mismatch")

    artifact_ids = document.get("artifact_inventory_ids", {})
    if not isinstance(artifact_ids, dict):
        diagnostics.append("shell-map.invalid-artifact-inventory")
        artifact_ids = {}
    for addon_id, inventory_id in artifact_ids.items():
        expected_target = [f"/storage/.kodi/addons/{addon_id}/"]
        if inventory_targets.get(inventory_id) != expected_target:
            diagnostics.append(f"shell-map.artifact-target-mismatch:{addon_id}")

    referenced_inventory: set[str] = set()
    referenced_effects: set[str] = set()
    for binding in call_paths.values():
        referenced_inventory.update(binding.get("inventory_ids", ()))
        referenced_inventory.update(binding.get("observation_ids", ()))
        referenced_effects.update(binding.get("effect_ids", ()))
        if binding.get("selection") == "artifact_inventory_ids":
            referenced_inventory.update(artifact_ids.values())
    referenced_shell = (referenced_inventory | referenced_effects) & shell_capable_ids
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
        call_path_unknowns = {
            binding.get("unknown")
            for binding in call_paths.values()
            if isinstance(binding.get("unknown"), str)
        }
        if (
            len(declared_unknowns) != len(unknowns)
            or call_path_unknowns != declared_unknowns
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
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        shell_inventory_rows=len(shell_ids),
        covered_shell_inventory_rows=len(shell_ids & covered),
        unknown_targets=unknown_count,
        sha256=digest,
    )


def _call_path_registry(document: JsonObject) -> dict[str, JsonObject]:
    result = dict(document["call_paths"])
    for primitive in document["primitive_families"]:
        result.update(primitive["call_paths"])
    return result


def _resolve_call_paths(
    document: JsonObject,
    call_path_ids: set[str],
    selected_addons: tuple[str, ...],
) -> tuple[set[str], set[str], set[str]]:
    registry = _call_path_registry(document)
    inventory_ids: set[str] = set()
    effect_ids: set[str] = set()
    unknowns: set[str] = set()
    for call_path_id in call_path_ids:
        binding = registry[call_path_id]
        inventory_ids.update(binding["inventory_ids"])
        inventory_ids.update(binding["observation_ids"])
        effect_ids.update(binding["effect_ids"])
        if unknown := binding.get("unknown"):
            unknowns.add(unknown)
        if binding.get("selection") == "artifact_inventory_ids":
            artifacts = document["artifact_inventory_ids"]
            if selected_addons:
                unknown_addons = set(selected_addons) - artifacts.keys()
                if unknown_addons:
                    raise ValueError(
                        f"unknown locked add-on: {sorted(unknown_addons)[0]}"
                    )
                inventory_ids.update(artifacts[addon] for addon in selected_addons)
            else:
                inventory_ids.update(artifacts.values())
    return inventory_ids, effect_ids, unknowns


def _provision_call_paths(
    document: JsonObject,
    scopes: tuple[str, ...],
    harden_ssh: bool,
    apply_kodi: bool,
) -> set[str]:
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

    call_path_ids = set(provision["always_call_path_ids"])
    for scope in effective:
        call_path_ids.update(scope_map[scope]["call_path_ids"])
    if harden_ssh:
        call_path_ids.update(provision["harden_ssh"]["call_path_ids"])
    return call_path_ids


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

    if entry_point == "provision-coreelec.sh" and operation == "deploy":
        call_path_ids = _provision_call_paths(
            document,
            scopes,
            harden_ssh,
            apply_kodi,
        )
    else:
        call_path_ids = set(entry[operation]["call_path_ids"])
    inventory_ids, effect_ids, unknowns = _resolve_call_paths(
        document,
        call_path_ids,
        selected_addons,
    )
    if unknowns:
        return ShellPermission(
            False,
            tuple(sorted(inventory_ids)),
            tuple(sorted(effect_ids)),
            (),
            tuple(sorted(unknowns)),
        )

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
