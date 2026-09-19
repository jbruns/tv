import json
from copy import deepcopy
from pathlib import Path

import pytest

from coreelec_reconciler.domain.execution import RunStatus
from coreelec_reconciler.reporting.canonical_json import canonical_document_bytes
from coreelec_reconciler.reporting.execution_documents import (
    build_execution_run_report,
    check_run_report_invariants,
    decode_execution_run_report,
    verify_run_revision_chain,
)

RUN_ID = "019950f8-4c00-7000-8000-000000000601"
ORIGIN_ID = "019950f8-4c00-7000-8000-000000000201"
PLAN_ID = "019950f8-4c00-7000-8000-000000000101"
DIGEST = "sha256:" + "b" * 64
TOKEN_DIGEST = (
    "sha256:" + "202b6cddfe21dac0427445df8c1756ec0a9bbc10f3b74cd4c693ebef3e63ae48"
)
WORKSPACE_ID = f"workspace:{RUN_ID}"
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "canonical"


def run_value(
    status: RunStatus = RunStatus.READY,
    *,
    revision: int = 1,
    previous: str | None = None,
) -> dict[str, object]:
    terminal = status in {
        RunStatus.CONVERGED,
        RunStatus.FAILED_ROLLED_BACK,
        RunStatus.FAILED_PARTIAL,
        RunStatus.FAILED_RECOVERY_REQUIRED,
    }
    convergence = (
        "converged"
        if status is RunStatus.CONVERGED
        else "rolled_back_verified"
        if status is RunStatus.FAILED_ROLLED_BACK
        else "recovery_required"
        if status is RunStatus.FAILED_RECOVERY_REQUIRED
        else "failed_known"
        if status is RunStatus.FAILED_PARTIAL
        else "pending"
    )
    rollback = (
        "restored_and_verified"
        if status is RunStatus.FAILED_ROLLED_BACK
        else "not_attempted"
    )
    lifecycle = (
        ["ready", "executing", status.value]
        if terminal
        else ["ready"]
        if status is RunStatus.READY
        else ["ready", status.value]
    )
    recovery_required = status in {
        RunStatus.INTERRUPTED,
        RunStatus.FAILED_RECOVERY_REQUIRED,
    }
    return {
        "approvals": [
            {
                "actor": "actor.local-admin",
                "granted_at": "2026-09-19T08:01:00Z",
                "mechanism": "noninteractive_cli",
                "plan_full_digest": DIGEST,
                "plan_id": PLAN_ID,
                "scope": "apply",
            }
        ],
        "attachments": [],
        "attempts": [],
        "authority": {
            "binding_digest": "sha256:" + "a" * 64,
            "boot_id": "boot.opaque",
            "cleanup_state": "not_started",
            "device_index_intent": "add_or_retain_active",
            "marker_digest": None,
            "marker_generation": None,
            "marker_phase": None,
            "ownership_state": "acquisition_pending",
            "ownership_token_digest": TOKEN_DIGEST,
        },
        "cleanup": {"leftover_count": 0, "state": "not_started"},
        "device_id": "living-room.ugoos-am6b-plus",
        "ended_at": "2026-09-19T08:10:00Z" if terminal else None,
        "evidence": [],
        "failures": [],
        "kind": "CoreElecReconcilerRunReport",
        "lifecycle_history": lifecycle,
        "originating_planning_run_id": ORIGIN_ID,
        "plan_reference": {
            "originating_planning_run_id": ORIGIN_ID,
            "plan_full_digest": DIGEST,
            "plan_id": PLAN_ID,
        },
        "previous_revision_digest": previous,
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "recovery": {
            "actions": [
                {
                    "allowed": True,
                    "code": "inspect",
                    "mode": None,
                    "reason_code": "recovery.workspace-present",
                    "requires_approval": False,
                    "requires_reason": False,
                },
                {
                    "allowed": recovery_required,
                    "code": "finalize",
                    "mode": "abandon",
                    "reason_code": "recovery.abandonment-available",
                    "requires_approval": True,
                    "requires_reason": True,
                },
            ],
            "required": recovery_required,
            "workspace_id": WORKSPACE_ID,
        },
        "resource_results": [
            {
                "decisive_attempt_id": None,
                "desired_disposition": "present",
                "final_convergence": convergence,
                "latest_observed_relation": (
                    "satisfied" if status is RunStatus.CONVERGED else "divergent"
                ),
                "mutation_outcome": ("completed" if terminal else "pending"),
                "post_effect_verification": "not_applicable",
                "resource_id": "skin.playlist.new-shows",
                "rollback_outcome": rollback,
                "verification_outcome": (
                    "matched" if status is RunStatus.CONVERGED else "not_started"
                ),
            }
        ],
        "revision": revision,
        "run_id": RUN_ID,
        "schema_version": 1,
        "started_at": "2026-09-19T08:00:00Z",
        "status": status.value,
    }


@pytest.mark.parametrize("status", tuple(RunStatus)[4:])
def test_complete_execution_status_vocabulary_round_trips(status: RunStatus) -> None:
    report = build_execution_run_report(run_value(status))
    assert decode_execution_run_report(report.canonical_bytes) == report
    assert check_run_report_invariants(report.canonical_bytes) == ()


def test_revision_chain_is_complete_linear_and_terminal() -> None:
    ready = build_execution_run_report(run_value())
    executing = build_execution_run_report(
        run_value(
            RunStatus.EXECUTING,
            revision=2,
            previous=ready.current_digest,
        )
    )
    converged = build_execution_run_report(
        run_value(
            RunStatus.CONVERGED,
            revision=3,
            previous=executing.current_digest,
        )
    )
    chain = verify_run_revision_chain(
        (
            ready.canonical_bytes,
            executing.canonical_bytes,
            converged.canonical_bytes,
        )
    )
    assert [item.status for item in chain] == [
        RunStatus.READY,
        RunStatus.EXECUTING,
        RunStatus.CONVERGED,
    ]

    with pytest.raises(ValueError, match="sequence mismatch"):
        verify_run_revision_chain(
            (
                ready.canonical_bytes,
                executing.canonical_bytes,
                converged.canonical_bytes,
                converged.canonical_bytes,
            )
        )


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("device_id",), "bedroom.different-device"),
        (
            ("originating_planning_run_id",),
            "019950f8-4c00-7000-8000-000000000777",
        ),
        (("plan_reference", "plan_id"), "019950f8-4c00-7000-8000-000000000999"),
        (("plan_reference", "plan_full_digest"), "sha256:" + "9" * 64),
        (("recovery", "workspace_id"), "workspace:different-workspace"),
        (("started_at",), "2026-09-19T08:00:01Z"),
    ],
)
def test_revision_chain_rejects_immutable_identity_drift(
    path: tuple[str, ...],
    replacement: object,
) -> None:
    ready = build_execution_run_report(run_value())
    successor = run_value(
        RunStatus.EXECUTING,
        revision=2,
        previous=ready.current_digest,
    )
    target: object = successor
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    if path == ("originating_planning_run_id",):
        plan_reference = successor["plan_reference"]
        assert isinstance(plan_reference, dict)
        plan_reference["originating_planning_run_id"] = replacement
    if path in {
        ("plan_reference", "plan_id"),
        ("plan_reference", "plan_full_digest"),
    }:
        approvals = successor["approvals"]
        assert isinstance(approvals, list)
        approval = approvals[0]
        assert isinstance(approval, dict)
        approval[path[-1]] = replacement
    drifted = build_execution_run_report(successor)
    with pytest.raises(ValueError, match="immutable"):
        verify_run_revision_chain((ready.canonical_bytes, drifted.canonical_bytes))


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    [
        (("run_id",), ORIGIN_ID, "must differ"),
        (("ended_at",), "2026-09-19T07:59:00Z", "ended before"),
        (("authority", "ownership_token_digest"), "secret", "SHA-256"),
        (
            ("recovery", "actions", 1, "requires_approval"),
            False,
            "separate approval",
        ),
        (
            ("resource_results", 0, "final_convergence"),
            "failed_known",
            "non-converged",
        ),
    ],
)
def test_independent_checker_rejects_each_cross_field_invariant(
    path: tuple[str | int, ...],
    replacement: object,
    message: str,
) -> None:
    value = run_value(RunStatus.CONVERGED)
    target: object = value
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    value["current_digest"] = ""
    content = canonical_document_bytes(value)
    errors = check_run_report_invariants(content)
    assert any(message in error for error in errors)


def test_decoder_rejects_unknown_fields_even_with_recomputed_digest() -> None:
    report = build_execution_run_report(run_value())
    value = json.loads(report.canonical_bytes)
    value["private_path"] = "/Users/operator/runs/secret"
    value.pop("current_digest")
    value["current_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="unknown or missing"):
        decode_execution_run_report(canonical_document_bytes(value))


def test_documents_never_contain_private_token_or_path() -> None:
    value = deepcopy(run_value())
    content = build_execution_run_report(value).canonical_bytes
    assert b"/Users/" not in content
    assert b"ownership-token-bytes" not in content
    assert TOKEN_DIGEST.encode() in content


@pytest.mark.parametrize(
    "name",
    [
        "execution-ready.json",
        "execution-converged.json",
        "recovery-interrupted.json",
    ],
)
def test_positive_fixtures_are_canonical_and_valid(name: str) -> None:
    content = (FIXTURE_ROOT / name).read_bytes()
    assert decode_execution_run_report(content).canonical_bytes == content
    assert check_run_report_invariants(content) == ()


def test_every_negative_fixture_breaks_an_independent_invariant() -> None:
    fixtures = sorted(FIXTURE_ROOT.glob("execution-invalid-*.json"))
    fixtures.extend(sorted(FIXTURE_ROOT.glob("recovery-invalid-*.json")))
    assert len(fixtures) == 8
    for fixture in fixtures:
        assert check_run_report_invariants(fixture.read_bytes()), fixture.name
