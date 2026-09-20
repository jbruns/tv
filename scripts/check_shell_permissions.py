#!/usr/bin/env python3
"""Fail-closed legacy shell write-set permission check."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shell_permissions import audit_shell_map, evaluate_shell_permission

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument(
        "--map",
        type=Path,
        default=REPOSITORY_ROOT / "inventory" / "shell-write-sets.json",
    )
    result.add_argument(
        "--ledger",
        type=Path,
        default=REPOSITORY_ROOT / "inventory" / "ownership-ledger.json",
    )
    result.add_argument("--entry-point")
    result.add_argument("--operation")
    result.add_argument("--scope", action="append", default=[])
    result.add_argument("--addon", action="append", default=[])
    harden = result.add_mutually_exclusive_group()
    harden.add_argument("--harden-ssh", action="store_true")
    harden.add_argument("--no-harden-ssh", action="store_false", dest="harden_ssh")
    result.set_defaults(harden_ssh=False)
    result.add_argument("--skip-kodi", action="store_true")
    result.add_argument("--audit", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.audit:
        audit = audit_shell_map(arguments.map, arguments.ledger)
        print(f"audit={'valid' if audit.valid else 'invalid'}")
        print(f"map_sha256={audit.sha256}")
        print(f"shell_inventory_rows={audit.shell_inventory_rows}")
        print(f"covered_shell_inventory_rows={audit.covered_shell_inventory_rows}")
        print(f"unknown_targets={audit.unknown_targets}")
        if audit.diagnostics:
            print("diagnostics=" + ",".join(audit.diagnostics))
        return 0 if audit.valid else 2
    if not arguments.entry_point or not arguments.operation:
        parser().error("--entry-point and --operation are required without --audit")
    try:
        permission = evaluate_shell_permission(
            arguments.map,
            arguments.ledger,
            entry_point=arguments.entry_point,
            operation=arguments.operation,
            scopes=tuple(arguments.scope),
            selected_addons=tuple(arguments.addon),
            harden_ssh=arguments.harden_ssh,
            apply_kodi=not arguments.skip_kodi,
        )
    except (KeyError, OSError, ValueError) as error:
        print(f"permission=blocked\nerror={error}", file=sys.stderr)
        return 2
    print(f"permission={'allowed' if permission.allowed else 'blocked'}")
    print("inventory_ids=" + ",".join(permission.inventory_ids))
    print("effect_ids=" + ",".join(permission.effect_ids))
    print("blocked_inventory_ids=" + ",".join(permission.blocked_inventory_ids))
    print("unknowns=" + ",".join(permission.unknowns))
    return 0 if permission.allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
