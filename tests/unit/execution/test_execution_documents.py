import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

import coreelec_reconciler.domain.execution as execution_domain
from coreelec_reconciler.domain.execution import (
    EvidenceAttachment,
    EvidenceObserver,
    ExecutionEvidenceBindings,
    ExecutionEvidenceKind,
    RunStatus,
    SessionCloseDisposition,
    build_execution_evidence,
    build_session_close_record,
    decode_execution_evidence,
    decode_session_close_record,
    validate_execution_evidence_sequence,
)
from coreelec_reconciler.reporting.canonical_json import canonical_document_bytes
from coreelec_reconciler.reporting.execution_documents import (
    build_execution_run_report,
    check_run_report_invariants,
    check_session_close_invariants,
    decode_execution_run_report,
    verify_run_revision_chain,
)
from coreelec_reconciler.resource_types.builtins import built_in_resource_registry
from coreelec_reconciler.resource_types.registry import ResourceRegistry

RUN_ID = "019950f8-4c00-7000-8000-000000000601"
ORIGIN_ID = "019950f8-4c00-7000-8000-000000000201"
PLAN_ID = "019950f8-4c00-7000-8000-000000000101"
DIGEST = "sha256:" + "b" * 64
TOKEN_DIGEST = (
    "sha256:" + "202b6cddfe21dac0427445df8c1756ec0a9bbc10f3b74cd4c693ebef3e63ae48"
)
WORKSPACE_ID = f"workspace:{RUN_ID}"
FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "canonical"
RESOURCE_REGISTRY = built_in_resource_registry()
RESOURCE_ID = "skin.playlist.new-shows"
CHANGE_ID = "change.skin.playlist.new-shows"
STATE_ADDRESS = "special://profile/playlists/video/new-shows.xsp"
ATTACHMENT_DIGESTS = {
    "before": "sha256:" + "1" * 64,
    "manifest": "sha256:" + "2" * 64,
    "content": "sha256:" + "3" * 64,
}


def session_close_value(
    disposition: str = "complete",
) -> dict[str, object]:
    return {
        "authority_state": "released",
        "device_id": "living-room.ugoos-am6b-plus",
        "disposition": disposition,
        "failure": (
            None
            if disposition == "complete"
            else {"category": "transport", "code": "transport.close_failed"}
        ),
        "kind": "CoreElecReconcilerSessionClose",
        "observed_at": "2026-09-19T08:11:00Z",
        "observed_head_digest": "sha256:" + "2" * 64,
        "observed_head_revision": 5,
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "record_id": "019950f8-4c00-7000-8000-000000000701",
        "run_id": RUN_ID,
        "schema_version": 1,
        "seal_digest": "sha256:" + "3" * 64,
        "session_id": "session.019950f8-4c00-7000-8000-000000000801",
        "terminal_digest": "sha256:" + "1" * 64,
        "terminal_revision": 2,
        "workspace_id": WORKSPACE_ID,
    }


OBSERVER_CODES = {
    ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION: "managed-file-observer",
    ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED: "managed-file-preparer",
    ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT: "managed-file-executor",
    ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT: "remote-run-ownership",
    ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME: "managed-file-executor",
    ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT: "managed-file-executor",
    ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT: "managed-file-verifier",
    ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT: "managed-file-verifier",
    ExecutionEvidenceKind.RESOURCE_SKIP_RESULT: "execution-controller",
    ExecutionEvidenceKind.RECOVERY_VERIFICATION_RESULT: "recovery-controller",
    ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT: "managed-file-executor",
    ExecutionEvidenceKind.EFFECT_INTENT: "effect-executor",
    ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION: "effect-readiness-observer",
    ExecutionEvidenceKind.EFFECT_OUTCOME: "effect-executor",
    ExecutionEvidenceKind.AUTHORITY_EVIDENCE: "remote-run-ownership",
    ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL: "recovery-controller",
}


def evidence_payload(kind: ExecutionEvidenceKind) -> dict[str, object]:
    digest = "sha256:" + "4" * 64
    operation_id = "operation.atomic-replace"
    observation_ref = "evidence.observation.after"
    payloads: dict[ExecutionEvidenceKind, dict[str, object]] = {
        ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION: {
            "content_digest": digest,
            "entry_kind": "regular",
            "managed_mode": 0o644,
            "normalized_state_digest": digest,
            "presence": "present",
            "relation": "post",
        },
        ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED: {
            "allowed_intermediate_state_digests": [digest],
            "before_state_attachment_digest": ATTACHMENT_DIGESTS["before"],
            "cleanup_object_refs": ["manifest.stage.new-shows"],
            "desired_state_digest": digest,
            "manifest_digest": ATTACHMENT_DIGESTS["manifest"],
            "preparation_manifest_attachment_digest": ATTACHMENT_DIGESTS["manifest"],
            "rollback_capable": True,
        },
        ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT: {
            "allowed_intermediate_state_digests": [digest],
            "content_attachment_digest": ATTACHMENT_DIGESTS["content"],
            "expected_after_digest": digest,
            "expected_before_digest": "sha256:" + "5" * 64,
            "manifest_object_ref": None,
            "marker_digest": "sha256:" + "6" * 64,
            "marker_generation": 1,
            "marker_phase": "prepared",
            "operation_id": operation_id,
            "preparation_manifest_digest": ATTACHMENT_DIGESTS["manifest"],
            "primitive": "atomic_replace",
            "terminal_revision_digest": None,
            "token_digest": TOKEN_DIGEST,
        },
        ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT: {
            "generation": 1,
            "manifest_digest": ATTACHMENT_DIGESTS["manifest"],
            "marker_digest": "sha256:" + "6" * 64,
            "operation_id": operation_id,
            "phase": "prepared",
            "token_digest": TOKEN_DIGEST,
        },
        ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME: {
            "disposition": "applied",
            "observation_evidence_ref": observation_ref,
            "observed_state_digest": digest,
            "operation_id": operation_id,
            "receipt_sequence": 1,
        },
        ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT: {
            "intent_evidence_ref": "evidence.intent",
            "mutation_outcome": "completed",
            "outcome_evidence_ref": "evidence.outcome",
        },
        ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT: {
            "observation_evidence_ref": observation_ref,
            "outcome": "matched",
            "post_effect": False,
            "relation": "post",
        },
        ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT: {
            "observation_evidence_ref": observation_ref,
            "original_failure_code": "failure.verification",
            "outcome": "restored_and_verified",
            "relation": "before",
        },
        ExecutionEvidenceKind.RESOURCE_SKIP_RESULT: {
            "final_convergence": "failed_known",
            "reason_code": "skip.prior-failure",
            "stop_scope": "resource",
        },
        ExecutionEvidenceKind.RECOVERY_VERIFICATION_RESULT: {
            "action": "resume_verification",
            "observation_evidence_ref": observation_ref,
            "outcome": "matched",
            "relation": "post",
        },
        ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT: {
            "disposition": "applied",
            "leftover": False,
            "manifest_object_ref": "manifest.stage.new-shows",
            "operation_id": "operation.cleanup",
            "terminal_revision_digest": digest,
        },
        ExecutionEvidenceKind.EFFECT_INTENT: {
            "affected_resources": [
                {
                    "change_id": CHANGE_ID,
                    "resource_id": RESOURCE_ID,
                    "resource_type": "KodiSmartPlaylist",
                    "state_addresses": [STATE_ADDRESS],
                }
            ],
            "approval_evidence_ref": "approval.apply",
            "descriptor_digest": digest,
            "effect_code": "effect.kodi.scan",
            "marker_digest": "sha256:" + "6" * 64,
            "marker_generation": 1,
            "marker_phase": "effect",
            "operation_id": "operation.effect",
            "readiness_evidence_ref": observation_ref,
            "token_digest": TOKEN_DIGEST,
        },
        ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION: {
            "effect_code": "effect.kodi.scan",
            "positive": True,
            "readiness_code": "kodi.json-rpc-ready",
        },
        ExecutionEvidenceKind.EFFECT_OUTCOME: {
            "disposition": "definitely_succeeded",
            "effect_code": "effect.kodi.scan",
            "operation_id": "operation.effect",
            "post_effect_evidence_refs": ["evidence.observation.post-effect"],
            "readiness_evidence_ref": "evidence.effect-readiness",
        },
        ExecutionEvidenceKind.AUTHORITY_EVIDENCE: {
            "generation": None,
            "manifest_digest": None,
            "marker_digest": None,
            "ownership_state": "acquisition_pending",
            "phase": None,
            "quarantine_receipt_digest": None,
            "token_digest": TOKEN_DIGEST,
        },
        ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL: {
            "actor": "actor.local-admin",
            "approved_at": "2026-09-19T08:09:00Z",
            "mechanism": "noninteractive-cli",
            "reason": "Operator approved abandonment after inspection.",
        },
    }
    return payloads[kind]


def evidence_value(
    kind: ExecutionEvidenceKind,
    evidence_id: str,
    *,
    observed_at: str,
    payload: dict[str, object] | None = None,
    resource_bound: bool | None = None,
    resource_type: str = "KodiSmartPlaylist",
    resource_registry: ResourceRegistry = RESOURCE_REGISTRY,
) -> dict[str, object]:
    evidence_payload_value = evidence_payload(kind) if payload is None else payload
    resource = kind not in {
        ExecutionEvidenceKind.EFFECT_INTENT,
        ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION,
        ExecutionEvidenceKind.EFFECT_OUTCOME,
        ExecutionEvidenceKind.AUTHORITY_EVIDENCE,
        ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL,
    }
    if resource_bound is not None:
        resource = resource_bound
    operation_evidence = kind in {
        ExecutionEvidenceKind.EFFECT_INTENT,
        ExecutionEvidenceKind.EFFECT_OUTCOME,
        ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
    }
    bindings = ExecutionEvidenceBindings(
        "living-room.ugoos-am6b-plus",
        RUN_ID,
        WORKSPACE_ID,
        PLAN_ID,
        DIGEST,
        "sha256:" + "a" * 64,
        RESOURCE_ID if resource else None,
        CHANGE_ID if resource else None,
    )
    effect_bound = kind in {
        ExecutionEvidenceKind.EFFECT_INTENT,
        ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION,
        ExecutionEvidenceKind.EFFECT_OUTCOME,
    } or (kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT and not resource)
    subject_kind = (
        "resource"
        if resource
        else "effect"
        if effect_bound
        else "device"
        if kind is ExecutionEvidenceKind.AUTHORITY_EVIDENCE
        else "run"
    )
    subject_id = (
        RESOURCE_ID
        if resource
        else "effect.kodi.scan"
        if subject_kind == "effect"
        else bindings.device_id
        if subject_kind == "device"
        else bindings.run_id
    )
    required_digests = {
        item
        for key, item in evidence_payload_value.items()
        if key.endswith("_attachment_digest") and isinstance(item, str)
    }
    attachment_refs = tuple(
        EvidenceAttachment(digest, f"{name}-state", "managed-file-v1")
        for name, digest in ATTACHMENT_DIGESTS.items()
        if digest in required_digests
    )
    return build_execution_evidence(
        evidence_id=evidence_id,
        observed_at=observed_at,
        observer=EvidenceObserver(OBSERVER_CODES[kind], 1),
        subject_kind=subject_kind,
        subject_id=subject_id,
        resource_type=resource_type if resource else None,
        bindings=bindings,
        state_addresses=(STATE_ADDRESS,) if resource else (),
        attachment_refs=attachment_refs,
        attempt=1 if resource or operation_evidence else None,
        kind=kind,
        payload=evidence_payload_value,
        resource_registry=resource_registry,
    )


def complete_evidence() -> list[dict[str, object]]:
    sequence = [
        (ExecutionEvidenceKind.AUTHORITY_EVIDENCE, "evidence.authority"),
        (ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION, "evidence.observation.before"),
        (
            ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED,
            "evidence.preparation",
        ),
        (ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT, "evidence.intent"),
        (ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT, "evidence.marker"),
        (ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION, "evidence.observation.after"),
        (ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME, "evidence.outcome"),
        (ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT, "evidence.execution"),
        (ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT, "evidence.verification"),
        (ExecutionEvidenceKind.EFFECT_INTENT, "evidence.effect-intent"),
        (ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT, "evidence.effect-marker"),
        (
            ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION,
            "evidence.effect-readiness",
        ),
        (
            ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION,
            "evidence.observation.post-effect",
        ),
        (ExecutionEvidenceKind.EFFECT_OUTCOME, "evidence.effect-outcome"),
        (ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT, "evidence.rollback"),
        (ExecutionEvidenceKind.RESOURCE_SKIP_RESULT, "evidence.skip"),
        (ExecutionEvidenceKind.RECOVERY_VERIFICATION_RESULT, "evidence.recovery"),
        (
            ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL,
            "evidence.abandonment",
        ),
    ]
    result = []
    for index, (kind, evidence_id) in enumerate(sequence):
        effect_marker = evidence_id == "evidence.effect-marker"
        payload = evidence_payload(kind)
        if effect_marker:
            payload.update(
                operation_id="operation.effect",
                phase="effect",
            )
        result.append(
            evidence_value(
                kind,
                evidence_id,
                observed_at=f"2026-09-19T08:{index + 1:02d}:00Z",
                payload=payload,
                resource_bound=False if effect_marker else None,
            )
        )
    return result


def cleanup_evidence(
    terminal_digest: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    intent_payload = evidence_payload(ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT)
    intent_payload.update(
        allowed_intermediate_state_digests=[],
        content_attachment_digest=None,
        expected_after_digest=None,
        expected_before_digest=None,
        manifest_object_ref="manifest.stage.new-shows",
        marker_phase="terminal_release_pending",
        operation_id="operation.cleanup",
        primitive="cleanup",
        terminal_revision_digest=terminal_digest,
    )
    intent = evidence_value(
        ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
        "evidence.cleanup-intent",
        observed_at="2026-09-19T08:18:00Z",
        payload=intent_payload,
    )
    checkpoint_payload = evidence_payload(
        ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT
    )
    checkpoint_payload.update(
        operation_id="operation.cleanup",
        phase="terminal_release_pending",
    )
    checkpoint = evidence_value(
        ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
        "evidence.cleanup-checkpoint",
        observed_at="2026-09-19T08:19:00Z",
        payload=checkpoint_payload,
    )
    receipt_payload = evidence_payload(ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT)
    receipt_payload["terminal_revision_digest"] = terminal_digest
    receipt = evidence_value(
        ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT,
        "evidence.cleanup",
        observed_at="2026-09-19T08:20:00Z",
        payload=receipt_payload,
    )
    return intent, checkpoint, receipt


def authority_release_evidence() -> dict[str, object]:
    payload = evidence_payload(ExecutionEvidenceKind.AUTHORITY_EVIDENCE)
    payload.update(
        generation=1,
        marker_digest="sha256:" + "6" * 64,
        ownership_state="released",
        phase="terminal_release_pending",
    )
    return evidence_value(
        ExecutionEvidenceKind.AUTHORITY_EVIDENCE,
        "evidence.authority-release",
        observed_at="2026-09-19T08:21:00Z",
        payload=payload,
    )


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


def unchecked_run_bytes(value: dict[str, object]) -> bytes:
    candidate = deepcopy(value)
    candidate.pop("current_digest", None)
    candidate["current_digest"] = (
        "sha256:" + hashlib.sha256(canonical_document_bytes(candidate)).hexdigest()
    )
    return canonical_document_bytes(candidate)


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


def test_terminal_status_is_immutable_while_cleanup_receipts_advance() -> None:
    ready = build_execution_run_report(run_value())
    terminal_value = run_value(
        RunStatus.FAILED_PARTIAL,
        revision=2,
        previous=ready.current_digest,
    )
    terminal_value["evidence"] = complete_evidence()[:3]
    terminal_value["attachments"] = [
        {"codec": "managed-file-v1", "digest": digest, "kind": f"{name}-state"}
        for name, digest in ATTACHMENT_DIGESTS.items()
    ]
    terminal = build_execution_run_report(terminal_value)
    intent, checkpoint, receipt = cleanup_evidence(terminal.current_digest)
    cleanup_pending = deepcopy(terminal_value)
    cleanup_pending["revision"] = 3
    cleanup_pending["previous_revision_digest"] = terminal.current_digest
    authority = cleanup_pending["authority"]
    cleanup = cleanup_pending["cleanup"]
    assert isinstance(authority, dict)
    assert isinstance(cleanup, dict)
    authority.update(
        cleanup_state="pending",
    )
    cleanup.update(state="pending")
    cleanup_pending["evidence"] = [*terminal_value["evidence"], intent]  # type: ignore[misc]
    pending = build_execution_run_report(cleanup_pending)
    checkpoint_value = deepcopy(cleanup_pending)
    checkpoint_value["revision"] = 4
    checkpoint_value["previous_revision_digest"] = pending.current_digest
    checkpoint_value["evidence"] = [
        *cleanup_pending["evidence"],  # type: ignore[misc]
        checkpoint,
    ]
    checkpoint_report = build_execution_run_report(checkpoint_value)
    cleanup_value = deepcopy(checkpoint_value)
    cleanup_value["revision"] = 5
    cleanup_value["previous_revision_digest"] = checkpoint_report.current_digest
    authority = cleanup_value["authority"]
    cleanup = cleanup_value["cleanup"]
    assert isinstance(authority, dict)
    assert isinstance(cleanup, dict)
    authority.update(
        cleanup_state="complete",
    )
    cleanup.update(leftover_count=0, state="complete")
    cleanup_value["evidence"] = [
        *checkpoint_value["evidence"],  # type: ignore[misc]
        receipt,
    ]
    cleaned = build_execution_run_report(cleanup_value)
    release_value = deepcopy(cleanup_value)
    release_value["revision"] = 6
    release_value["previous_revision_digest"] = cleaned.current_digest
    authority = release_value["authority"]
    assert isinstance(authority, dict)
    authority.update(
        device_index_intent="remove_after_release_or_quarantine",
        marker_digest="sha256:" + "6" * 64,
        marker_generation=1,
        marker_phase="terminal_release_pending",
        ownership_state="released",
    )
    release_value["evidence"] = [
        *cleanup_value["evidence"],  # type: ignore[misc]
        authority_release_evidence(),
    ]
    released = build_execution_run_report(release_value)

    assert [
        item.status
        for item in verify_run_revision_chain(
            (
                ready.canonical_bytes,
                terminal.canonical_bytes,
                pending.canonical_bytes,
                checkpoint_report.canonical_bytes,
                cleaned.canonical_bytes,
                released.canonical_bytes,
            )
        )
    ] == [
        RunStatus.READY,
        RunStatus.FAILED_PARTIAL,
        RunStatus.FAILED_PARTIAL,
        RunStatus.FAILED_PARTIAL,
        RunStatus.FAILED_PARTIAL,
        RunStatus.FAILED_PARTIAL,
    ]

    invalid = deepcopy(terminal_value)
    invalid["revision"] = 3
    invalid["previous_revision_digest"] = terminal.current_digest
    invalid["status"] = RunStatus.CONVERGED.value
    invalid["lifecycle_history"] = ["ready", "executing", "converged"]
    resource_results = invalid["resource_results"]
    assert isinstance(resource_results, list)
    resource_result = resource_results[0]
    assert isinstance(resource_result, dict)
    resource_result.update(
        final_convergence="converged",
        latest_observed_relation="satisfied",
        verification_outcome="matched",
    )
    changed = build_execution_run_report(invalid)
    with pytest.raises(ValueError, match="non-cleanup successor"):
        verify_run_revision_chain(
            (ready.canonical_bytes, terminal.canonical_bytes, changed.canonical_bytes)
        )


def test_cleanup_receipt_requires_prior_terminal_revision() -> None:
    value = run_value(RunStatus.FAILED_PARTIAL)
    cleanup_records = cleanup_evidence("sha256:" + "4" * 64)
    value["evidence"] = [*complete_evidence()[:3], *cleanup_records]
    value["attachments"] = [
        {"codec": "managed-file-v1", "digest": digest, "kind": f"{name}-state"}
        for name, digest in ATTACHMENT_DIGESTS.items()
    ]
    report = build_execution_run_report(value)
    with pytest.raises(ValueError, match="prior terminal revision"):
        verify_run_revision_chain((report.canonical_bytes,))


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("intent-only", "complete cleanup is not proven"),
        ("missing-checkpoint", "cleanup receipt lacks intent/checkpoint"),
        ("mismatched-object", "cleanup receipt is not proven"),
        ("ambiguous-receipt", "cleanup receipt is not proven"),
        ("leftover", "cleanup leftover summary is not proven"),
        ("missing-release", "authority release or quarantine is not proven"),
        ("mismatched-release", "authority release or quarantine is not proven"),
    ],
)
def test_terminal_cleanup_summary_requires_complete_evidence_chain(
    defect: str,
    message: str,
) -> None:
    value = run_value(RunStatus.FAILED_PARTIAL)
    value["evidence"] = complete_evidence()[:3]
    value["attachments"] = [
        {"codec": "managed-file-v1", "digest": digest, "kind": f"{name}-state"}
        for name, digest in ATTACHMENT_DIGESTS.items()
    ]
    terminal = build_execution_run_report(value)
    intent, checkpoint, receipt = cleanup_evidence(terminal.current_digest)
    release = authority_release_evidence()
    evidence = [*value["evidence"], intent, checkpoint, receipt, release]  # type: ignore[misc]
    if defect == "intent-only":
        evidence = [*value["evidence"], intent]  # type: ignore[misc]
    elif defect == "missing-checkpoint":
        evidence.remove(checkpoint)
    elif defect == "mismatched-object":
        receipt_payload = receipt["payload"]
        assert isinstance(receipt_payload, dict)
        receipt_payload["manifest_object_ref"] = "manifest.stage.other"
    elif defect == "ambiguous-receipt":
        receipt_payload = receipt["payload"]
        assert isinstance(receipt_payload, dict)
        receipt_payload["disposition"] = "ambiguous"
    elif defect == "leftover":
        receipt_payload = receipt["payload"]
        assert isinstance(receipt_payload, dict)
        receipt_payload["leftover"] = True
    elif defect == "missing-release":
        evidence.remove(release)
    else:
        release_payload = release["payload"]
        assert isinstance(release_payload, dict)
        release_payload["token_digest"] = "sha256:" + "9" * 64
    successor = deepcopy(value)
    successor["revision"] = 2
    successor["previous_revision_digest"] = terminal.current_digest
    successor["evidence"] = evidence
    authority = successor["authority"]
    cleanup = successor["cleanup"]
    assert isinstance(authority, dict)
    assert isinstance(cleanup, dict)
    cleanup.update(state="complete", leftover_count=0)
    authority.update(cleanup_state="complete")
    if defect not in {
        "intent-only",
        "missing-checkpoint",
        "mismatched-object",
        "ambiguous-receipt",
    }:
        authority.update(
            device_index_intent="remove_after_release_or_quarantine",
            marker_digest="sha256:" + "6" * 64,
            marker_generation=1,
            marker_phase="terminal_release_pending",
            ownership_state="released",
        )
    if defect == "intent-only":
        authority.update(
            device_index_intent="remove_after_release_or_quarantine",
            marker_digest="sha256:" + "6" * 64,
            marker_generation=1,
            marker_phase="terminal_release_pending",
            ownership_state="released",
        )
        evidence.append(release)
    with pytest.raises(ValueError, match=message):
        build_execution_run_report(successor)


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


@pytest.mark.parametrize("kind", tuple(ExecutionEvidenceKind))
def test_every_execution_evidence_kind_v1_round_trips(
    kind: ExecutionEvidenceKind,
) -> None:
    value = evidence_value(
        kind,
        f"evidence.roundtrip.{kind.name.lower()}",
        observed_at="2026-09-19T08:02:00Z",
    )
    decoded = decode_execution_evidence(
        value,
        resource_registry=RESOURCE_REGISTRY,
    )
    assert decoded.kind is kind
    assert decoded.schema_version == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value.update(payload_kind="InventedPrivatePayload"),
            "unknown execution evidence kind",
        ),
        (
            lambda value: value.update(payload_schema_version=999),
            "unsupported execution evidence schema version",
        ),
        (
            lambda value: value["payload"].update(arbitrary_field="anything"),
            "unknown or missing execution evidence payload fields",
        ),
    ],
)
def test_closed_evidence_schema_rejects_unregistered_combinations(
    mutation: object,
    message: str,
) -> None:
    value = evidence_value(
        ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION,
        "evidence.closed-schema",
        observed_at="2026-09-19T08:02:00Z",
    )
    mutation(value)  # type: ignore[operator]
    with pytest.raises(ValueError, match=message):
        decode_execution_evidence(
            value,
            resource_registry=RESOURCE_REGISTRY,
        )

    report_value = run_value()
    report_value["evidence"] = [value]
    with pytest.raises(ValueError, match=message):
        build_execution_run_report(report_value)


def test_complete_resource_and_effect_sequence_passes_independent_checker() -> None:
    value = run_value(RunStatus.FAILED_PARTIAL)
    value["evidence"] = complete_evidence()[:14]
    value["attachments"] = [
        {"codec": "managed-file-v1", "digest": digest, "kind": f"{name}-state"}
        for name, digest in ATTACHMENT_DIGESTS.items()
    ]
    report = build_execution_run_report(value)
    assert decode_execution_run_report(report.canonical_bytes) == report
    assert check_run_report_invariants(report.canonical_bytes) == ()


def test_evidence_sequence_rejects_duplicate_out_of_order_and_self_reference() -> None:
    value = run_value(RunStatus.FAILED_RECOVERY_REQUIRED)
    evidence = complete_evidence()
    value["attachments"] = [
        {"codec": "managed-file-v1", "digest": digest, "kind": f"{name}-state"}
        for name, digest in ATTACHMENT_DIGESTS.items()
    ]
    duplicated = deepcopy(evidence)
    duplicated[1]["evidence_id"] = duplicated[0]["evidence_id"]
    value["evidence"] = duplicated
    with pytest.raises(ValueError, match="duplicated"):
        build_execution_run_report(value)

    out_of_order = deepcopy(evidence)
    out_of_order[1]["observed_at"] = "2026-09-19T08:00:00Z"
    value["evidence"] = out_of_order
    with pytest.raises(ValueError, match="out of order"):
        build_execution_run_report(value)

    self_referencing = deepcopy(evidence)
    outcome = next(
        item
        for item in self_referencing
        if item["payload_kind"] == "ResourcePrimitiveOutcome"
    )
    outcome_payload = outcome["payload"]
    assert isinstance(outcome_payload, dict)
    outcome_payload["observation_evidence_ref"] = outcome["evidence_id"]
    value["evidence"] = self_referencing
    with pytest.raises(ValueError, match="unresolved or forward"):
        build_execution_run_report(value)


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    [
        (("resource_type",), "InventedResource", "Resource Type"),
        (("observer", "code"), "invented-observer", "observer"),
        (("bindings", "resource_id"), None, "bindings are incomplete"),
        (("bindings", "device_id"), "not-a-device", "Device ID"),
        (("bindings", "plan_full_digest"), "sha256:bad", "Plan digest"),
        (("attempt",), 2, "attempt must be 1"),
        (("state_addresses",), ["/private/device/path"], "not logical"),
    ],
)
def test_resource_evidence_rejects_invalid_binding_and_type_combinations(
    path: tuple[str, ...],
    replacement: object,
    message: str,
) -> None:
    value = evidence_value(
        ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION,
        "evidence.invalid-binding",
        observed_at="2026-09-19T08:02:00Z",
    )
    target = value
    for component in path[:-1]:
        nested = target[component]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = replacement
    with pytest.raises(ValueError, match=message):
        decode_execution_evidence(
            value,
            resource_registry=RESOURCE_REGISTRY,
        )


def test_evidence_rejects_unsafe_content_and_undeclared_attachment() -> None:
    abandonment = evidence_value(
        ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL,
        "evidence.abandonment",
        observed_at="2026-09-19T08:02:00Z",
    )
    abandonment_payload = abandonment["payload"]
    assert isinstance(abandonment_payload, dict)
    abandonment_payload["reason"] = "/Users/operator/private-state"
    with pytest.raises(ValueError, match="unsafe"):
        decode_execution_evidence(
            abandonment,
            resource_registry=RESOURCE_REGISTRY,
        )

    preparation = evidence_value(
        ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED,
        "evidence.preparation",
        observed_at="2026-09-19T08:02:00Z",
    )
    preparation["attachment_refs"] = []
    with pytest.raises(ValueError, match="not declared"):
        decode_execution_evidence(
            preparation,
            resource_registry=RESOURCE_REGISTRY,
        )


def test_evidence_sequence_rejects_missing_checkpoint_and_conflicting_skip() -> None:
    evidence = complete_evidence()
    without_checkpoint = [
        item
        for item in evidence[:8]
        if item["payload_kind"] != "RemoteMarkerCheckpoint"
    ]
    with pytest.raises(ValueError, match="lacks intent/checkpoint"):
        validate_execution_evidence_sequence(
            tuple(without_checkpoint),
            status=RunStatus.EXECUTING,
            resource_registry=RESOURCE_REGISTRY,
        )

    with pytest.raises(ValueError, match="skip conflicts"):
        skip_index = next(
            index
            for index, item in enumerate(evidence)
            if item["payload_kind"] == "ResourceSkipResult"
        )
        validate_execution_evidence_sequence(
            tuple(evidence[: skip_index + 1]),
            status=RunStatus.FAILED_PARTIAL,
            resource_registry=RESOURCE_REGISTRY,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda records: next(
                item for item in records if item["payload_kind"] == "EffectIntent"
            )["payload"].pop("operation_id"),
            "unknown or missing execution evidence payload fields",
        ),
        (
            lambda records: records.pop(
                next(
                    index
                    for index, item in enumerate(records)
                    if item["evidence_id"] == "evidence.effect-marker"
                )
            ),
            "Effect outcome lacks intent/checkpoint",
        ),
        (
            lambda records: records.__setitem__(
                slice(9, 11),
                [records[10], records[9]],
            ),
            "marker checkpoint precedes operation intent",
        ),
        (
            lambda records: next(
                item
                for item in records
                if item["evidence_id"] == "evidence.effect-marker"
            )["payload"].update(marker_digest="sha256:" + "9" * 64),
            "marker checkpoint does not match intent",
        ),
    ],
)
def test_effect_requires_matching_immediate_checkpoint(
    mutation: object,
    message: str,
) -> None:
    records = complete_evidence()[:14]
    mutation(records)  # type: ignore[operator]
    with pytest.raises(ValueError, match=message):
        validate_execution_evidence_sequence(
            tuple(records),
            status=RunStatus.FAILED_PARTIAL,
            resource_registry=RESOURCE_REGISTRY,
        )


@pytest.mark.parametrize(
    "defect",
    ("unrelated", "duplicate", "missing", "binding", "stale"),
)
def test_effect_outcome_requires_fresh_complete_affected_resource_observations(
    defect: str,
) -> None:
    records = complete_evidence()[:14]
    intent = next(item for item in records if item["payload_kind"] == "EffectIntent")
    outcome = next(item for item in records if item["payload_kind"] == "EffectOutcome")
    outcome_payload = outcome["payload"]
    intent_payload = intent["payload"]
    assert isinstance(outcome_payload, dict)
    assert isinstance(intent_payload, dict)
    if defect == "unrelated":
        outcome_payload["post_effect_evidence_refs"] = ["evidence.effect-readiness"]
    elif defect == "duplicate":
        outcome_payload["post_effect_evidence_refs"] = [
            "evidence.observation.post-effect",
            "evidence.observation.post-effect",
        ]
    elif defect == "missing":
        affected = intent_payload["affected_resources"]
        assert isinstance(affected, list)
        affected.append(
            {
                "change_id": "change.skin.playlist.second",
                "resource_id": "skin.playlist.second",
                "resource_type": "KodiSmartPlaylist",
                "state_addresses": ["special://profile/playlists/video/second.xsp"],
            }
        )
    elif defect == "binding":
        observation = next(
            item
            for item in records
            if item["evidence_id"] == "evidence.observation.post-effect"
        )
        bindings = observation["bindings"]
        assert isinstance(bindings, dict)
        bindings["change_id"] = "change.skin.playlist.other"
    else:
        observation = next(
            item
            for item in records
            if item["evidence_id"] == "evidence.observation.post-effect"
        )
        observation["observed_at"] = "2026-09-19T08:12:00Z"
    with pytest.raises(ValueError, match=r"post-Effect|fresh"):
        validate_execution_evidence_sequence(
            tuple(records),
            status=RunStatus.FAILED_PARTIAL,
            resource_registry=RESOURCE_REGISTRY,
        )


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("version", "unsupported execution evidence schema version"),
        ("field", "unknown or missing execution evidence payload fields"),
        ("order", "execution evidence records are out of order"),
        ("reference", "execution evidence reference is unresolved or forward"),
        ("checkpoint", "marker checkpoint does not match intent"),
    ],
)
def test_independent_checker_does_not_delegate_to_domain_validator(
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
    message: str,
) -> None:
    value = run_value(RunStatus.FAILED_PARTIAL)
    value["evidence"] = complete_evidence()[:14]
    value["attachments"] = [
        {"codec": "managed-file-v1", "digest": digest, "kind": f"{name}-state"}
        for name, digest in ATTACHMENT_DIGESTS.items()
    ]
    evidence = value["evidence"]
    assert isinstance(evidence, list)
    if defect == "version":
        evidence[0]["payload_schema_version"] = 999
    elif defect == "field":
        payload = evidence[0]["payload"]
        assert isinstance(payload, dict)
        payload["arbitrary_field"] = "anything"
    elif defect == "order":
        evidence[1]["observed_at"] = "2026-09-19T08:00:00Z"
    elif defect == "reference":
        outcome = next(
            item
            for item in evidence
            if item["payload_kind"] == "ResourcePrimitiveOutcome"
        )
        payload = outcome["payload"]
        assert isinstance(payload, dict)
        payload["observation_evidence_ref"] = "evidence.missing"
    else:
        marker = next(
            item for item in evidence if item["evidence_id"] == "evidence.effect-marker"
        )
        payload = marker["payload"]
        assert isinstance(payload, dict)
        payload["marker_digest"] = "sha256:" + "9" * 64
    monkeypatch.setattr(
        execution_domain,
        "validate_execution_evidence_sequence",
        lambda *args, **kwargs: (),
    )
    errors = check_run_report_invariants(unchecked_run_bytes(value))
    assert message in errors


def test_resource_type_registration_is_owned_by_immutable_registry() -> None:
    type_code = "SyntheticManagedFile"
    descriptor = RESOURCE_REGISTRY.descriptor("KodiSmartPlaylist")
    assert descriptor is not None
    registry = ResourceRegistry.create((replace(descriptor, type_code=type_code),))
    evidence = evidence_value(
        ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION,
        "evidence.synthetic",
        observed_at="2026-09-19T08:02:00Z",
        resource_type=type_code,
        resource_registry=registry,
    )
    value = run_value()
    value["evidence"] = [evidence]
    with pytest.raises(ValueError, match="Resource Type"):
        build_execution_run_report(value)

    report = build_execution_run_report(value, resource_registry=registry)
    assert (
        decode_execution_run_report(
            report.canonical_bytes,
            resource_registry=registry,
        )
        == report
    )


def test_abandonment_approval_requires_recovery_status() -> None:
    value = run_value(RunStatus.READY)
    value["evidence"] = [
        evidence_value(
            ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL,
            "evidence.abandonment",
            observed_at="2026-09-19T08:02:00Z",
        )
    ]
    with pytest.raises(ValueError, match="abandonment approval"):
        build_execution_run_report(value)


def test_pending_attempt_is_write_ahead_and_has_no_completion() -> None:
    value = run_value(RunStatus.EXECUTING)
    evidence = complete_evidence()[:4]
    value["evidence"] = evidence
    value["attachments"] = [
        {"codec": "managed-file-v1", "digest": digest, "kind": f"{name}-state"}
        for name, digest in ATTACHMENT_DIGESTS.items()
    ]
    value["attempts"] = [
        {
            "attempt": 1,
            "attempt_id": "attempt.atomic-replace",
            "bindings": {
                "binding_digest": "sha256:" + "a" * 64,
                "change_id": CHANGE_ID,
                "device_id": "living-room.ugoos-am6b-plus",
                "plan_full_digest": DIGEST,
                "plan_id": PLAN_ID,
                "resource_id": RESOURCE_ID,
                "run_id": RUN_ID,
                "workspace_id": WORKSPACE_ID,
            },
            "ended_at": None,
            "intent_evidence_ref": "evidence.intent",
            "operation_code": "atomic-replace",
            "outcome": "pending",
            "outcome_evidence_ref": None,
            "phase": "mutation",
            "resource_type": "KodiSmartPlaylist",
            "started_at": "2026-09-19T08:04:00Z",
            "state_addresses": [STATE_ADDRESS],
            "subject": {"id": RESOURCE_ID, "kind": "resource"},
        }
    ]
    assert (
        check_run_report_invariants(build_execution_run_report(value).canonical_bytes)
        == ()
    )

    value["attempts"][0]["ended_at"] = "2026-09-19T08:05:00Z"  # type: ignore[index]
    with pytest.raises(ValueError, match="pending attempt"):
        build_execution_run_report(value)


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
        "execution-evidence-v1.json",
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
    assert len(fixtures) == 11
    for fixture in fixtures:
        assert check_run_report_invariants(fixture.read_bytes()), fixture.name


@pytest.mark.parametrize(
    "disposition",
    [item.value for item in SessionCloseDisposition],
)
def test_session_close_record_round_trips_closed_dispositions(
    disposition: str,
) -> None:
    record = build_session_close_record(session_close_value(disposition))

    assert decode_session_close_record(record.canonical_bytes) == record
    assert check_session_close_invariants(record.canonical_bytes) == ()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(extra=True), "fields"),
        (lambda value: value.update(kind="InventedClose"), "kind"),
        (lambda value: value.update(schema_version=999), "version"),
        (lambda value: value.update(terminal_revision=6), "terminal"),
        (
            lambda value: value.update(
                failure={"category": "transport", "code": "raw exception: secret"}
            ),
            "failure",
        ),
        (
            lambda value: value.update(
                failure={"category": "invented", "code": "transport.close_failed"}
            ),
            "category",
        ),
        (
            lambda value: value.update(
                disposition="complete",
                failure={"category": "transport", "code": "transport.close_failed"},
            ),
            "complete",
        ),
    ],
)
def test_session_close_codec_and_oracle_reject_tampering(
    mutation: object,
    message: str,
) -> None:
    value = session_close_value("failed")
    mutation(value)  # type: ignore[operator]
    candidate = dict(value)
    candidate["current_digest"] = ""
    without_digest = {
        key: item for key, item in candidate.items() if key != "current_digest"
    }
    candidate["current_digest"] = (
        "sha256:" + hashlib.sha256(canonical_document_bytes(without_digest)).hexdigest()
    )
    content = canonical_document_bytes(candidate)

    with pytest.raises(ValueError):
        decode_session_close_record(content)
    assert any(
        message in error.lower() for error in check_session_close_invariants(content)
    )


def test_session_close_positive_fixture_is_canonical_and_independently_valid() -> None:
    content = (FIXTURE_ROOT / "execution-session-close-v1.json").read_bytes()
    record = decode_session_close_record(content)

    assert record.disposition is SessionCloseDisposition.FAILED
    assert check_session_close_invariants(content) == ()


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("authority_state",), []),
        (("authority_state",), {}),
        (("disposition",), []),
        (("disposition",), {}),
        (("failure", "category"), []),
        (("failure", "category"), {}),
    ],
)
def test_session_close_oracle_is_total_for_non_string_enum_fields(
    path: tuple[str, ...],
    invalid: object,
) -> None:
    value = session_close_value("failed")
    target = value
    for component in path[:-1]:
        nested = target[component]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = invalid
    candidate = dict(value)
    candidate["current_digest"] = ""
    without_digest = {
        key: item for key, item in candidate.items() if key != "current_digest"
    }
    candidate["current_digest"] = (
        "sha256:" + hashlib.sha256(canonical_document_bytes(without_digest)).hexdigest()
    )

    errors = check_session_close_invariants(canonical_document_bytes(candidate))

    assert errors
