#!/usr/bin/env python3
"""Validate and print the accepted inventory ownership ledger."""

from pathlib import Path

from coreelec_reconciler.inventory.ledger import validate_ledger
from coreelec_reconciler.inventory.shell_permissions import audit_shell_map


def main() -> int:
    path = Path("inventory/ownership-ledger.json")
    result = validate_ledger(path)
    if not result.valid:
        for diagnostic in result.diagnostics:
            location = ".".join(
                part
                for part in (diagnostic.inventory_id, diagnostic.field)
                if part is not None
            )
            suffix = f" [{location}]" if location else ""
            print(f"{diagnostic.code}: {diagnostic.message}{suffix}")
        return 1
    print(
        "id | role | disposition | milestone | current_owner | closure | "
        "test | evidence | doc"
    )
    print("\n".join(result.audit_lines))
    dispositions = " ".join(
        f"{name}={count}" for name, count in result.disposition_totals.items()
    )
    print(f"validated rows={result.row_count} {dispositions} sha256={result.sha256}")
    shell_audit = audit_shell_map(
        Path("inventory/shell-write-sets.json"),
        path,
    )
    if not shell_audit.valid:
        for shell_diagnostic in shell_audit.diagnostics:
            print(shell_diagnostic)
        return 1
    print(
        "shell-audit "
        f"rows={shell_audit.shell_inventory_rows} "
        f"covered={shell_audit.covered_shell_inventory_rows} "
        f"unknowns={shell_audit.unknown_targets} "
        f"sha256={shell_audit.sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
