"""Fail-closed validation for the accepted inventory ownership ledger."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

type JsonObject = dict[str, Any]

ROLES: Final = frozenset(
    {
        "resource",
        "guard",
        "effect",
        "guided-action",
        "run-infrastructure",
        "unmanaged-inventory-fact",
    }
)
DISPOSITIONS: Final = frozenset({"migrate", "retire", "outside"})
OWNERS: Final = frozenset(
    {"shell", "python", "repository", "operator", "external", "none"}
)
MILESTONES: Final = frozenset({"M4", "M5", "M6", "M7", "M8"})
EXPECTED_ROLE_TOTALS: Final = {
    "resource": 128,
    "guard": 5,
    "effect": 5,
    "guided-action": 6,
    "run-infrastructure": 4,
    "unmanaged-inventory-fact": 21,
}
EXPECTED_DISPOSITION_TOTALS: Final = {
    "migrate": 153,
    "retire": 5,
    "outside": 11,
}
DOCUMENT_KEYS: Final = frozenset(
    {"schema_version", "catalog", "accepted_totals", "rows"}
)
ROW_KEYS: Final = frozenset(
    {
        "id",
        "state_address",
        "role",
        "disposition",
        "milestone",
        "current_owner_or_executor",
        "closure",
        "evidence",
        "shell_write_set",
        "permitted_effects",
        "recovery",
        "transfers",
    }
)
CLOSURE_KEYS: Final = frozenset({"state", "closing_issue", "closing_pr"})
EVIDENCE_KEYS: Final = frozenset({"test", "evidence", "documentation"})
TRANSFER_KEYS: Final = frozenset(
    {
        "sequence",
        "from",
        "to",
        "milestone",
        "issue",
        "pull_request",
        "prestate_evidence",
        "handoff_evidence",
        "acceptance_evidence",
        "former_owner_freeze_evidence",
        "documentation",
    }
)
SET_KEYS: Final = frozenset({"status", "items"})
RECOVERY_KEYS: Final = frozenset({"state", "evidence"})


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    role: str
    disposition: str
    milestone: str
    initial_owner: str


@dataclass(frozen=True, slots=True)
class LedgerDiagnostic:
    code: str
    message: str
    inventory_id: str | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class LedgerValidation:
    valid: bool
    diagnostics: tuple[LedgerDiagnostic, ...]
    row_count: int
    role_totals: dict[str, int]
    disposition_totals: dict[str, int]
    sha256: str
    audit_lines: tuple[str, ...]


class DuplicateKeyError(ValueError):
    """Raised when JSON contains an ambiguous duplicate mapping key."""


def _expand(prefix: str, start: int, end: int) -> tuple[str, ...]:
    return tuple(f"{prefix}-{number:03d}" for number in range(start, end + 1))


def _ids(*groups: str | tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for group in groups:
        values.extend((group,) if isinstance(group, str) else group)
    return tuple(values)


def _catalog() -> dict[str, CatalogEntry]:
    entries: dict[str, CatalogEntry] = {}

    def add(
        inventory_ids: Iterable[str],
        role: str,
        disposition: str,
        milestone: str,
        *,
        initial_owner: str | None = None,
    ) -> None:
        owner = initial_owner or {
            "resource": "shell",
            "guard": "shell",
            "effect": "shell",
            "guided-action": "operator",
            "run-infrastructure": "repository",
        }.get(role)
        if owner is None:
            raise AssertionError(f"initial owner required for role {role}")
        for inventory_id in inventory_ids:
            if inventory_id in entries:
                raise AssertionError(f"duplicate accepted ID {inventory_id}")
            entries[inventory_id] = CatalogEntry(
                role,
                disposition,
                milestone,
                owner,
            )

    add(_ids(_expand("PLAT", 1, 2), "PLAT-004", "PLAT-005"), "guard", "migrate", "M8")
    add(
        ("PLAT-003",),
        "unmanaged-inventory-fact",
        "outside",
        "M8",
        initial_owner="external",
    )
    add(
        _expand("SSH", 1, 2),
        "unmanaged-inventory-fact",
        "outside",
        "M8",
        initial_owner="operator",
    )
    add(("SSH-003",), "resource", "migrate", "M8")
    add(("SSH-004",), "guard", "migrate", "M8")
    add(
        _ids(_expand("CORE", 1, 6), _expand("CORE", 8, 29)),
        "resource",
        "migrate",
        "M5",
    )
    add(
        ("CORE-007",),
        "unmanaged-inventory-fact",
        "migrate",
        "M5",
        initial_owner="shell",
    )
    add(_expand("CEC", 1, 5), "resource", "migrate", "M8")
    add(_expand("ART", 1, 41), "resource", "migrate", "M6")
    add(("ADDON-001",), "resource", "migrate", "M6")
    add(
        ("ADDON-002",),
        "unmanaged-inventory-fact",
        "outside",
        "M6",
        initial_owner="external",
    )
    add(
        ("ADDON-003",),
        "unmanaged-inventory-fact",
        "retire",
        "M6",
        initial_owner="shell",
    )
    add(_expand("PATCH", 1, 4), "run-infrastructure", "migrate", "M6")
    add(("SVC-001",), "resource", "migrate", "M5")
    add(_expand("SVC", 2, 13), "resource", "migrate", "M6")
    add(
        _expand("SVC", 14, 17),
        "unmanaged-inventory-fact",
        "retire",
        "M6",
        initial_owner="shell",
    )
    add(_expand("GUIDE", 1, 6), "guided-action", "migrate", "M8")
    add(
        _expand("GUIDE", 7, 8),
        "unmanaged-inventory-fact",
        "migrate",
        "M8",
        initial_owner="external",
    )
    add(_expand("SKIN", 1, 2), "resource", "migrate", "M5")
    add(_expand("SKIN", 3, 16), "resource", "migrate", "M7")
    add(
        _expand("SKIN", 17, 18),
        "unmanaged-inventory-fact",
        "migrate",
        "M7",
        initial_owner="shell",
    )
    add(_expand("SKIN", 19, 24), "resource", "migrate", "M7")
    add(("SKIN-025",), "resource", "migrate", "M4")
    add(_expand("SKIN", 26, 28), "resource", "migrate", "M7")
    add(_expand("ROOM", 1, 11), "resource", "migrate", "M5")
    add(_expand("LIFE", 1, 2), "resource", "migrate", "M8")
    add(("LIFE-003",), "effect", "migrate", "M8")
    add(_expand("EFFECT", 1, 2), "effect", "migrate", "M5")
    add(("EFFECT-003",), "effect", "migrate", "M8")
    add(("EFFECT-004",), "effect", "migrate", "M7")
    add(
        ("EFFECT-005",),
        "unmanaged-inventory-fact",
        "outside",
        "M8",
        initial_owner="none",
    )
    add(
        _expand("FACT", 1, 6),
        "unmanaged-inventory-fact",
        "outside",
        "M8",
        initial_owner="external",
    )
    return entries


ACCEPTED_CATALOG: Final = _catalog()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def _diagnostic(
    diagnostics: list[LedgerDiagnostic],
    code: str,
    message: str,
    inventory_id: str | None = None,
    field: str | None = None,
) -> None:
    diagnostics.append(LedgerDiagnostic(code, message, inventory_id, field))


def _require_exact_keys(
    value: JsonObject,
    expected: frozenset[str],
    diagnostics: list[LedgerDiagnostic],
    *,
    inventory_id: str | None,
    field: str,
) -> None:
    if unknown := sorted(value.keys() - expected):
        _diagnostic(
            diagnostics,
            "ledger.unknown-field",
            f"{field} has unknown fields: {', '.join(unknown)}",
            inventory_id,
            field,
        )
    if missing := sorted(expected - value.keys()):
        _diagnostic(
            diagnostics,
            "ledger.missing-field",
            f"{field} is missing fields: {', '.join(missing)}",
            inventory_id,
            field,
        )


def _validate_transfer_chain(
    row: JsonObject,
    accepted: CatalogEntry | None,
    diagnostics: list[LedgerDiagnostic],
) -> None:
    inventory_id = row.get("id")
    transfers = row.get("transfers")
    if not isinstance(transfers, list):
        _diagnostic(
            diagnostics,
            "ledger.invalid-field",
            "transfers must be a list",
            inventory_id if isinstance(inventory_id, str) else None,
            "transfers",
        )
        return
    seen_sequences: set[int] = set()
    initial_owner = accepted.initial_owner if accepted is not None else None
    transfer_allowed = (
        accepted is not None
        and accepted.disposition == "migrate"
        and accepted.initial_owner == "shell"
        and accepted.role in {"resource", "guard", "effect", "unmanaged-inventory-fact"}
    )
    if transfers and not transfer_allowed:
        _diagnostic(
            diagnostics,
            "ledger.transfer-not-allowed",
            "this accepted role and ownership state does not transfer",
            inventory_id if isinstance(inventory_id, str) else None,
            "transfers",
        )
    previous_owner: str | None = initial_owner
    for expected_sequence, transfer in enumerate(transfers, start=1):
        if not isinstance(transfer, dict):
            _diagnostic(
                diagnostics,
                "ledger.invalid-transfer",
                "every transfer must be an object",
                inventory_id,
                "transfers",
            )
            continue
        _require_exact_keys(
            transfer,
            TRANSFER_KEYS,
            diagnostics,
            inventory_id=inventory_id,
            field="transfers",
        )
        sequence = transfer.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            _diagnostic(
                diagnostics,
                "ledger.invalid-transfer",
                "transfer sequence must be a positive integer",
                inventory_id,
                "transfers.sequence",
            )
        elif sequence in seen_sequences:
            _diagnostic(
                diagnostics,
                "ledger.conflicting-transfer",
                f"multiple transfers use sequence {sequence}",
                inventory_id,
                "transfers.sequence",
            )
        else:
            seen_sequences.add(sequence)
            if sequence != expected_sequence:
                _diagnostic(
                    diagnostics,
                    "ledger.conflicting-transfer",
                    "transfer sequences must be contiguous and in array order",
                    inventory_id,
                    "transfers.sequence",
                )
        source = transfer.get("from")
        target = transfer.get("to")
        if transfer.get("milestone") != row.get("milestone"):
            _diagnostic(
                diagnostics,
                "ledger.conflicting-transfer",
                "transfer milestone must equal the row milestone",
                inventory_id,
                "transfers.milestone",
            )
        if source not in OWNERS or target not in OWNERS or source == target:
            _diagnostic(
                diagnostics,
                "ledger.invalid-transfer",
                "transfer owners must be distinct allowed owner values",
                inventory_id,
                "transfers",
            )
        if previous_owner is not None and source != previous_owner:
            _diagnostic(
                diagnostics,
                "ledger.conflicting-transfer",
                f"transfer source {source!r} does not follow {previous_owner!r}",
                inventory_id,
                "transfers.from",
            )
        if isinstance(target, str):
            previous_owner = target
        for key in TRANSFER_KEYS - {"sequence", "issue", "pull_request"}:
            if not isinstance(transfer.get(key), str) or not transfer[key]:
                _diagnostic(
                    diagnostics,
                    "ledger.invalid-transfer",
                    f"transfer field {key} must be a non-empty string",
                    inventory_id,
                    f"transfers.{key}",
                )
        for key in ("issue", "pull_request"):
            value = transfer.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                _diagnostic(
                    diagnostics,
                    "ledger.invalid-transfer",
                    f"transfer field {key} must be a positive integer",
                    inventory_id,
                    f"transfers.{key}",
                )
    if transfers and previous_owner != row.get("current_owner_or_executor"):
        _diagnostic(
            diagnostics,
            "ledger.conflicting-transfer",
            "current owner must equal the final transfer target",
            inventory_id,
            "current_owner_or_executor",
        )
    closure = row.get("closure")
    closure_state = closure.get("state") if isinstance(closure, dict) else None
    if (
        not transfers
        and accepted is not None
        and row.get("current_owner_or_executor") != accepted.initial_owner
        and not (
            accepted.disposition == "retire"
            and closure_state == "retired"
            and row.get("current_owner_or_executor") == "none"
        )
    ):
        _diagnostic(
            diagnostics,
            "ledger.conflicting-transfer",
            "current owner differs from the accepted predecessor without a transfer",
            inventory_id if isinstance(inventory_id, str) else None,
            "current_owner_or_executor",
        )


def _valid_closure(
    role: str,
    disposition: str,
    owner: str,
    closure_state: str,
    initial_owner: str,
) -> bool:
    if disposition == "retire":
        return role == "unmanaged-inventory-fact" and (
            (owner == "shell" and closure_state == "open")
            or (owner == "none" and closure_state == "retired")
        )
    if disposition == "outside":
        return (
            role == "unmanaged-inventory-fact"
            and owner in {"operator", "external", "none"}
            and closure_state == "outside"
        )
    allowed_open_owner = {
        "resource": {"shell"},
        "guard": {"shell"},
        "effect": {"shell"},
        "guided-action": {"operator"},
        "run-infrastructure": {"repository"},
        "unmanaged-inventory-fact": {"shell", "external"},
    }
    if closure_state == "open":
        return owner in allowed_open_owner.get(role, set())
    accepted_closure: dict[str, tuple[str, set[str]]] = {
        "resource": ("transferred", {"python"}),
        "guard": ("transferred", {"python"}),
        "effect": ("transferred", {"python"}),
        "guided-action": ("accepted", {"operator"}),
        "run-infrastructure": ("accepted", {"repository"}),
    }
    if role == "unmanaged-inventory-fact":
        accepted_owner = "python" if initial_owner == "shell" else initial_owner
        accepted_closure[role] = ("evidence-integrated", {accepted_owner})
    expected_state, accepted_owners = accepted_closure.get(role, ("", set()))
    return closure_state == expected_state and owner in accepted_owners


def validate_ledger(path: Path) -> LedgerValidation:
    diagnostics: list[LedgerDiagnostic] = []
    try:
        content = path.read_bytes()
    except OSError as error:
        return LedgerValidation(
            valid=False,
            diagnostics=(
                LedgerDiagnostic("ledger.unreadable", str(error), field=str(path)),
            ),
            row_count=0,
            role_totals={},
            disposition_totals={},
            sha256="",
            audit_lines=(),
        )
    digest = hashlib.sha256(content).hexdigest()
    try:
        document = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError) as error:
        return LedgerValidation(
            valid=False,
            diagnostics=(
                LedgerDiagnostic("ledger.invalid-json", str(error), field=str(path)),
            ),
            row_count=0,
            role_totals={},
            disposition_totals={},
            sha256=digest,
            audit_lines=(),
        )
    if not isinstance(document, dict):
        return LedgerValidation(
            valid=False,
            diagnostics=(
                LedgerDiagnostic(
                    "ledger.invalid-document",
                    "ledger root must be an object",
                ),
            ),
            row_count=0,
            role_totals={},
            disposition_totals={},
            sha256=digest,
            audit_lines=(),
        )
    _require_exact_keys(
        document,
        DOCUMENT_KEYS,
        diagnostics,
        inventory_id=None,
        field="document",
    )
    if document.get("schema_version") != 1:
        _diagnostic(
            diagnostics,
            "ledger.unsupported-version",
            "schema_version must be 1",
            field="schema_version",
        )
    if document.get("catalog") != "accepted-managed-state-v1":
        _diagnostic(
            diagnostics,
            "ledger.invalid-catalog",
            "catalog must be accepted-managed-state-v1",
            field="catalog",
        )
    accepted_totals = document.get("accepted_totals")
    expected_totals = {
        "rows": 169,
        "roles": EXPECTED_ROLE_TOTALS,
        "dispositions": EXPECTED_DISPOSITION_TOTALS,
    }
    if accepted_totals != expected_totals:
        _diagnostic(
            diagnostics,
            "ledger.bad-totals",
            "accepted_totals do not match the accepted 169-row catalog",
            field="accepted_totals",
        )
    rows = document.get("rows")
    if not isinstance(rows, list):
        _diagnostic(
            diagnostics,
            "ledger.invalid-field",
            "rows must be a list",
            field="rows",
        )
        rows = []

    ids: list[str] = []
    role_totals: Counter[str] = Counter()
    disposition_totals: Counter[str] = Counter()
    audit_lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            _diagnostic(
                diagnostics,
                "ledger.invalid-row",
                "every row must be an object",
                field="rows",
            )
            continue
        inventory_id = row.get("id")
        inventory_id_text = inventory_id if isinstance(inventory_id, str) else None
        _require_exact_keys(
            row,
            ROW_KEYS,
            diagnostics,
            inventory_id=inventory_id_text,
            field="row",
        )
        if not isinstance(inventory_id, str) or not re.fullmatch(
            r"[A-Z]+-\d{3}", inventory_id
        ):
            _diagnostic(
                diagnostics,
                "ledger.invalid-id",
                "id must match [A-Z]+-NNN",
                inventory_id_text,
                "id",
            )
            continue
        ids.append(inventory_id)
        accepted = ACCEPTED_CATALOG.get(inventory_id)
        if accepted is None:
            _diagnostic(
                diagnostics,
                "ledger.unknown-id",
                f"{inventory_id} is not in the accepted catalog",
                inventory_id,
                "id",
            )
        role = row.get("role")
        disposition = row.get("disposition")
        milestone = row.get("milestone")
        owner = row.get("current_owner_or_executor")
        if role not in ROLES:
            _diagnostic(
                diagnostics,
                "ledger.invalid-role",
                f"unknown role {role!r}",
                inventory_id,
                "role",
            )
        else:
            role_totals[role] += 1
        if disposition not in DISPOSITIONS:
            _diagnostic(
                diagnostics,
                "ledger.invalid-disposition",
                f"unknown disposition {disposition!r}",
                inventory_id,
                "disposition",
            )
        else:
            disposition_totals[disposition] += 1
        if milestone not in MILESTONES:
            _diagnostic(
                diagnostics,
                "ledger.invalid-milestone",
                f"unknown milestone {milestone!r}",
                inventory_id,
                "milestone",
            )
        if owner not in OWNERS:
            _diagnostic(
                diagnostics,
                "ledger.invalid-owner",
                f"unknown owner/executor {owner!r}",
                inventory_id,
                "current_owner_or_executor",
            )
        if accepted is not None and (
            role,
            disposition,
            milestone,
        ) != (
            accepted.role,
            accepted.disposition,
            accepted.milestone,
        ):
            _diagnostic(
                diagnostics,
                "ledger.catalog-mismatch",
                "role, disposition, or milestone differs from the accepted mapping",
                inventory_id,
            )
        state_address = row.get("state_address")
        if not isinstance(state_address, str) or not state_address.strip():
            _diagnostic(
                diagnostics,
                "ledger.invalid-field",
                "state_address must be a non-empty string",
                inventory_id,
                "state_address",
            )
        closure_state: Any = ""
        closure = row.get("closure")
        if not isinstance(closure, dict):
            _diagnostic(
                diagnostics,
                "ledger.invalid-field",
                "closure must be an object",
                inventory_id,
                "closure",
            )
        else:
            _require_exact_keys(
                closure,
                CLOSURE_KEYS,
                diagnostics,
                inventory_id=inventory_id,
                field="closure",
            )
            closure_state = closure.get("state")
            if closure_state == "open":
                if (
                    closure.get("closing_issue") is not None
                    or closure.get("closing_pr") is not None
                ):
                    _diagnostic(
                        diagnostics,
                        "ledger.invalid-role-closure",
                        "open rows cannot name a closing issue or pull request",
                        inventory_id,
                        "closure",
                    )
            else:
                for key in ("closing_issue", "closing_pr"):
                    value = closure.get(key)
                    if (
                        not isinstance(value, int)
                        or isinstance(value, bool)
                        or value < 1
                    ):
                        _diagnostic(
                            diagnostics,
                            "ledger.invalid-role-closure",
                            f"{closure_state} closure requires a positive {key}",
                            inventory_id,
                            f"closure.{key}",
                        )
            if (
                isinstance(role, str)
                and isinstance(disposition, str)
                and isinstance(owner, str)
                and isinstance(closure_state, str)
                and accepted is not None
                and not _valid_closure(
                    role,
                    disposition,
                    owner,
                    closure_state,
                    accepted.initial_owner,
                )
            ):
                _diagnostic(
                    diagnostics,
                    "ledger.invalid-role-closure",
                    "closure is not valid for this role, disposition, and owner",
                    inventory_id,
                    "closure.state",
                )
        evidence = row.get("evidence")
        if not isinstance(evidence, dict):
            _diagnostic(
                diagnostics,
                "ledger.invalid-field",
                "evidence must be an object",
                inventory_id,
                "evidence",
            )
        else:
            _require_exact_keys(
                evidence,
                EVIDENCE_KEYS,
                diagnostics,
                inventory_id=inventory_id,
                field="evidence",
            )
            for key in EVIDENCE_KEYS:
                if not isinstance(evidence.get(key), str) or not evidence[key]:
                    _diagnostic(
                        diagnostics,
                        "ledger.invalid-evidence",
                        f"evidence field {key} must be a non-empty string",
                        inventory_id,
                        f"evidence.{key}",
                    )
        for field_name in ("shell_write_set", "permitted_effects"):
            value = row.get(field_name)
            if not isinstance(value, dict):
                _diagnostic(
                    diagnostics,
                    "ledger.invalid-field",
                    f"{field_name} must be an object",
                    inventory_id,
                    field_name,
                )
                continue
            _require_exact_keys(
                value,
                SET_KEYS,
                diagnostics,
                inventory_id=inventory_id,
                field=field_name,
            )
            status = value.get("status")
            items = value.get("items")
            if status not in {
                "unaudited",
                "audited",
                "frozen",
                "retired",
                "not-applicable",
            }:
                _diagnostic(
                    diagnostics,
                    "ledger.invalid-field",
                    f"{field_name}.status is invalid",
                    inventory_id,
                    f"{field_name}.status",
                )
            if not isinstance(items, list) or not all(
                isinstance(item, str) and item for item in items
            ):
                _diagnostic(
                    diagnostics,
                    "ledger.invalid-field",
                    f"{field_name}.items must be a list of non-empty strings",
                    inventory_id,
                    f"{field_name}.items",
                )
            if status in {"unaudited", "not-applicable"} and items:
                _diagnostic(
                    diagnostics,
                    "ledger.invalid-field",
                    f"{field_name} cannot list items while {status}",
                    inventory_id,
                    f"{field_name}.items",
                )
        recovery = row.get("recovery")
        if not isinstance(recovery, dict):
            _diagnostic(
                diagnostics,
                "ledger.invalid-field",
                "recovery must be an object",
                inventory_id,
                "recovery",
            )
        else:
            _require_exact_keys(
                recovery,
                RECOVERY_KEYS,
                diagnostics,
                inventory_id=inventory_id,
                field="recovery",
            )
            recovery_state = recovery.get("state")
            recovery_evidence = recovery.get("evidence")
            if recovery_state not in {"none", "unresolved", "quarantined", "resolved"}:
                _diagnostic(
                    diagnostics,
                    "ledger.invalid-field",
                    "recovery.state is invalid",
                    inventory_id,
                    "recovery.state",
                )
            if recovery_state == "none":
                if recovery_evidence is not None:
                    _diagnostic(
                        diagnostics,
                        "ledger.invalid-field",
                        "recovery evidence must be null when state is none",
                        inventory_id,
                        "recovery.evidence",
                    )
            elif not isinstance(recovery_evidence, str) or not recovery_evidence:
                _diagnostic(
                    diagnostics,
                    "ledger.invalid-field",
                    "non-empty recovery evidence is required for this state",
                    inventory_id,
                    "recovery.evidence",
                )
        _validate_transfer_chain(row, accepted, diagnostics)
        transfers = row.get("transfers")
        if (
            closure_state == "transferred"
            and isinstance(transfers, list)
            and not transfers
        ):
            _diagnostic(
                diagnostics,
                "ledger.invalid-role-closure",
                "transferred closure requires append-only transfer evidence",
                inventory_id,
                "transfers",
            )
        if (
            disposition in {"migrate", "retire"}
            and closure_state != "open"
            and isinstance(milestone, str)
        ):
            exit_path = (
                path.parent.parent
                / "docs"
                / "implementation"
                / "milestones"
                / f"{milestone.lower()}-exit.md"
            )
            if not exit_path.is_file():
                _diagnostic(
                    diagnostics,
                    "ledger.premature-closure",
                    f"{milestone} has no accepted exit record",
                    inventory_id,
                    "closure.state",
                )
        if (
            isinstance(role, str)
            and isinstance(disposition, str)
            and isinstance(milestone, str)
            and isinstance(owner, str)
            and isinstance(closure_state, str)
        ):
            audit_lines.append(
                " | ".join(
                    (
                        inventory_id,
                        role,
                        disposition,
                        milestone,
                        owner,
                        closure_state,
                        evidence.get("test", "") if isinstance(evidence, dict) else "",
                        evidence.get("evidence", "")
                        if isinstance(evidence, dict)
                        else "",
                        evidence.get("documentation", "")
                        if isinstance(evidence, dict)
                        else "",
                    )
                )
            )

    duplicates = sorted(
        inventory_id for inventory_id, count in Counter(ids).items() if count > 1
    )
    for inventory_id in duplicates:
        _diagnostic(
            diagnostics,
            "ledger.duplicate-id",
            f"{inventory_id} occurs more than once",
            inventory_id,
            "id",
        )
    actual_ids = set(ids)
    for inventory_id in sorted(ACCEPTED_CATALOG.keys() - actual_ids):
        _diagnostic(
            diagnostics,
            "ledger.missing-id",
            f"{inventory_id} is missing",
            inventory_id,
            "id",
        )
    if (
        len(rows) != 169
        or dict(role_totals) != EXPECTED_ROLE_TOTALS
        or dict(disposition_totals) != EXPECTED_DISPOSITION_TOTALS
    ):
        _diagnostic(
            diagnostics,
            "ledger.bad-totals",
            "actual rows or role/disposition totals do not match the accepted totals",
        )

    ordered_diagnostics = tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.inventory_id or "",
                item.field or "",
                item.code,
                item.message,
            ),
        )
    )
    return LedgerValidation(
        valid=not ordered_diagnostics,
        diagnostics=ordered_diagnostics,
        row_count=len(rows),
        role_totals=dict(sorted(role_totals.items())),
        disposition_totals=dict(sorted(disposition_totals.items())),
        sha256=digest,
        audit_lines=tuple(sorted(audit_lines)),
    )
