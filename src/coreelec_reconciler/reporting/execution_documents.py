"""Canonical execution/recovery Run revisions and independent invariants."""

import hashlib
import re
from collections.abc import Iterable

from coreelec_reconciler.domain.execution import (
    TERMINAL_RUN_STATUSES,
    FinalConvergence,
    MutationOutcome,
    PostEffectVerification,
    RollbackOutcome,
    RunStatus,
    VerificationOutcome,
)
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport
from coreelec_reconciler.domain.validation import (
    parse_rfc3339_utc,
    require_logical_id,
    require_sha256,
    require_uuid7,
)
from coreelec_reconciler.reporting.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)

_PRODUCER = {"name": "coreelec-reconciler", "version": "0.1.0"}
_FIELDS = {
    "approvals",
    "attachments",
    "attempts",
    "authority",
    "cleanup",
    "current_digest",
    "device_id",
    "ended_at",
    "evidence",
    "failures",
    "kind",
    "lifecycle_history",
    "originating_planning_run_id",
    "plan_reference",
    "previous_revision_digest",
    "producer",
    "recovery",
    "resource_results",
    "revision",
    "run_id",
    "schema_version",
    "started_at",
    "status",
}
_LIFECYCLE_TRANSITIONS = {
    RunStatus.AWAITING_APPROVAL: {RunStatus.READY},
    RunStatus.READY: {
        RunStatus.EXECUTING,
        RunStatus.INTERRUPTED,
        RunStatus.FAILED_PARTIAL,
    },
    RunStatus.EXECUTING: {
        RunStatus.EXECUTING,
        RunStatus.INTERRUPTED,
        RunStatus.CONVERGED,
        RunStatus.FAILED_ROLLED_BACK,
        RunStatus.FAILED_PARTIAL,
        RunStatus.FAILED_RECOVERY_REQUIRED,
    },
    RunStatus.INTERRUPTED: {
        RunStatus.EXECUTING,
        RunStatus.FAILED_PARTIAL,
        RunStatus.FAILED_RECOVERY_REQUIRED,
    },
}
_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_WORKSPACE = re.compile(r"^workspace:[a-zA-Z0-9_-]{8,128}$")


def build_execution_run_report(value: dict[str, object]) -> CanonicalRunReport:
    """Validate a complete revision value and add its canonical digest."""
    candidate = dict(value)
    candidate["current_digest"] = ""
    without_digest = {
        key: item for key, item in candidate.items() if key != "current_digest"
    }
    candidate["current_digest"] = _sha256(canonical_document_bytes(without_digest))
    return decode_execution_run_report(canonical_document_bytes(candidate))


def decode_execution_run_report(
    content: bytes,
    plan: CanonicalPlan | None = None,
) -> CanonicalRunReport:
    value = decode_json_object(content)
    if set(value) != _FIELDS:
        raise ValueError("unknown or missing execution Run Report fields")
    if canonical_document_bytes(value) != content:
        raise ValueError("execution Run Report bytes are not canonical")
    errors = check_run_report_invariants(content, plan)
    if errors:
        raise ValueError(errors[0])
    return CanonicalRunReport(
        canonical_bytes=content,
        run_id=str(value["run_id"]),
        current_digest=str(value["current_digest"]),
        revision=_positive_int(value["revision"], "revision"),
        status=RunStatus(str(value["status"])),
    )


def verify_run_revision_chain(
    revisions: Iterable[bytes],
    plan: CanonicalPlan | None = None,
) -> tuple[CanonicalRunReport, ...]:
    decoded = tuple(decode_execution_run_report(content, plan) for content in revisions)
    if not decoded:
        raise ValueError("Run revision chain is empty")
    first_value = decode_json_object(decoded[0].canonical_bytes)
    if decoded[0].revision != 1 or first_value["previous_revision_digest"] is not None:
        raise ValueError("Run revision chain must begin at revision 1")
    run_id = decoded[0].run_id
    immutable_identity = execution_run_identity(
        decode_json_object(decoded[0].canonical_bytes)
    )
    terminal_seen = False
    previous_status: RunStatus | None = None
    for index, report in enumerate(decoded):
        value = decode_json_object(report.canonical_bytes)
        if report.run_id != run_id or report.revision != index + 1:
            raise ValueError("Run revision chain identity or sequence mismatch")
        if execution_run_identity(value) != immutable_identity:
            raise ValueError("Run immutable identity bindings changed")
        if (
            index
            and value["previous_revision_digest"] != decoded[index - 1].current_digest
        ):
            raise ValueError("Run revision chain digest mismatch")
        if terminal_seen:
            raise ValueError("terminal Run revision has a successor")
        if previous_status is not None and report.status != previous_status:
            allowed = _LIFECYCLE_TRANSITIONS.get(previous_status, set())
            if report.status not in allowed:
                raise ValueError("invalid Run status transition")
        terminal_seen = report.status in TERMINAL_RUN_STATUSES
        previous_status = report.status
    return decoded


def execution_run_identity(value: dict[str, object]) -> dict[str, object]:
    """Return the complete immutable identity projection for one execution Run."""
    reference = value.get("plan_reference")
    authority = value.get("authority")
    recovery = value.get("recovery")
    if (
        not isinstance(reference, dict)
        or not isinstance(authority, dict)
        or not isinstance(recovery, dict)
    ):
        raise ValueError("Run immutable identity bindings are malformed")
    return {
        "binding_digest": authority.get("binding_digest"),
        "boot_id": authority.get("boot_id"),
        "created_at": value.get("started_at"),
        "device_id": value.get("device_id"),
        "kind": value.get("kind"),
        "originating_planning_run_id": value.get("originating_planning_run_id"),
        "ownership_token_digest": authority.get("ownership_token_digest"),
        "plan_full_digest": reference.get("plan_full_digest"),
        "plan_id": reference.get("plan_id"),
        "producer": value.get("producer"),
        "run_id": value.get("run_id"),
        "schema_version": value.get("schema_version"),
        "workspace_id": recovery.get("workspace_id"),
    }


def check_run_report_invariants(
    content: bytes,
    plan: CanonicalPlan | None = None,
) -> tuple[str, ...]:
    """Independent, total checker used for fixtures and external validation."""
    errors: list[str] = []
    try:
        value = decode_json_object(content)
    except ValueError:
        return ("Run Report is not a JSON object",)
    if set(value) != _FIELDS:
        return ("unknown or missing execution Run Report fields",)
    if canonical_document_bytes(value) != content:
        errors.append("execution Run Report bytes are not canonical")
    if value["kind"] != "CoreElecReconcilerRunReport":
        errors.append("unsupported Run Report kind")
    if value["schema_version"] != 1:
        errors.append("unsupported Run Report schema version")
    if value["producer"] != _PRODUCER:
        errors.append("unsupported Run Report producer")
    try:
        run_id = require_uuid7(value["run_id"], "run_id")
        origin_id = require_uuid7(
            value["originating_planning_run_id"],
            "originating_planning_run_id",
        )
        require_logical_id(value["device_id"], "device_id")
        started = parse_rfc3339_utc(value["started_at"], "started_at")
        status = RunStatus(_string(value["status"], "status"))
    except (TypeError, ValueError) as error:
        return (*errors, str(error))
    revision = value["revision"]
    if type(revision) is not int or revision < 1:
        errors.append("invalid Run Report revision")
    previous = value["previous_revision_digest"]
    if revision == 1:
        if previous is not None:
            errors.append("revision 1 must not reference a predecessor")
    else:
        try:
            require_sha256(previous, "previous_revision_digest")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
    digest = value["current_digest"]
    try:
        require_sha256(digest, "current_digest")
        without_digest = {
            key: item for key, item in value.items() if key != "current_digest"
        }
        if _sha256(canonical_document_bytes(without_digest)) != digest:
            errors.append("Run Report digest mismatch")
    except (TypeError, ValueError) as error:
        errors.append(str(error))
    ended = value["ended_at"]
    if status in TERMINAL_RUN_STATUSES:
        if ended is None:
            errors.append("terminal Run requires ended_at")
    elif ended is not None:
        errors.append("nonterminal Run cannot have ended_at")
    if ended is not None:
        try:
            if parse_rfc3339_utc(ended, "ended_at") < started:
                errors.append("Run ended before it started")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
    lifecycle = _array(value["lifecycle_history"], "lifecycle_history", errors)
    if not lifecycle or lifecycle[-1] != status.value:
        errors.append("lifecycle history must end in current status")
    for item in lifecycle:
        try:
            RunStatus(_string(item, "lifecycle status"))
        except TypeError, ValueError:
            errors.append("lifecycle history contains unknown status")
    reference = _mapping(
        value["plan_reference"],
        {
            "originating_planning_run_id",
            "plan_full_digest",
            "plan_id",
        },
        "plan_reference",
        errors,
    )
    if reference:
        try:
            if (
                require_uuid7(reference["originating_planning_run_id"], "origin")
                != origin_id
            ):
                errors.append("Plan reference origin does not match Run")
            plan_id = require_uuid7(reference["plan_id"], "plan_id")
            full_digest = require_sha256(
                reference["plan_full_digest"], "plan_full_digest"
            )
            if plan is not None and (
                plan.plan_id != plan_id or plan.full_digest != full_digest
            ):
                errors.append("Plan reference does not match supplied Plan")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
    if run_id == origin_id:
        errors.append("execution Run ID must differ from originating planning Run")
    _check_approvals(value["approvals"], reference, errors)
    evidence_ids = _check_evidence(value["evidence"], errors)
    attempt_ids = _check_attempts(value["attempts"], evidence_ids, errors)
    _check_failures(value["failures"], evidence_ids, errors)
    _check_attachments(value["attachments"], errors)
    _check_authority(value["authority"], status, errors)
    _check_recovery(value["recovery"], status, errors)
    _check_cleanup(value["cleanup"], status, errors)
    _check_resources(
        value["resource_results"],
        status,
        attempt_ids,
        errors,
    )
    return tuple(dict.fromkeys(errors))


def _check_approvals(
    raw: object,
    reference: dict[str, object],
    errors: list[str],
) -> None:
    seen: set[str] = set()
    for item in _array(raw, "approvals", errors):
        approval = _mapping(
            item,
            {
                "actor",
                "granted_at",
                "mechanism",
                "plan_full_digest",
                "plan_id",
                "scope",
            },
            "approval",
            errors,
        )
        if not approval:
            continue
        scope = approval.get("scope")
        if not isinstance(scope, str) or not _SAFE_CODE.fullmatch(scope):
            errors.append("approval scope is invalid")
        elif scope in seen:
            errors.append("approval scopes must be unique")
        else:
            seen.add(scope)
        if reference and (
            approval.get("plan_id") != reference.get("plan_id")
            or approval.get("plan_full_digest") != reference.get("plan_full_digest")
        ):
            errors.append("approval is not bound to exact Plan")
        try:
            parse_rfc3339_utc(approval.get("granted_at"), "approval granted_at")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
        for key in ("actor", "mechanism"):
            if not isinstance(approval.get(key), str) or not _SAFE_CODE.fullmatch(
                str(approval.get(key))
            ):
                errors.append(f"approval {key} is invalid")


def _check_evidence(raw: object, errors: list[str]) -> set[str]:
    identifiers: set[str] = set()
    for item in _array(raw, "evidence", errors):
        evidence = _mapping(
            item,
            {
                "evidence_id",
                "observed_at",
                "payload",
                "payload_kind",
                "payload_schema_version",
                "raw_attachment_digest",
                "subject",
            },
            "evidence",
            errors,
        )
        if not evidence:
            continue
        identifier = evidence.get("evidence_id")
        if not isinstance(identifier, str) or not _SAFE_CODE.fullmatch(identifier):
            errors.append("evidence ID is invalid")
        elif identifier in identifiers:
            errors.append("evidence IDs must be unique")
        else:
            identifiers.add(identifier)
        try:
            parse_rfc3339_utc(evidence.get("observed_at"), "evidence observed_at")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
        attachment = evidence.get("raw_attachment_digest")
        if attachment is not None:
            try:
                require_sha256(attachment, "raw attachment digest")
            except (TypeError, ValueError) as error:
                errors.append(str(error))
        if not isinstance(evidence.get("payload"), dict):
            errors.append("evidence payload must be an object")
        _check_subject(evidence.get("subject"), errors)
    return identifiers


def _check_attempts(
    raw: object,
    evidence_ids: set[str],
    errors: list[str],
) -> set[str]:
    identifiers: set[str] = set()
    valid_phases = {
        "precondition_recheck",
        "mutation",
        "verification",
        "effect",
        "post_effect_verification",
        "rollback",
        "rollback_verification",
        "recovery",
        "cleanup",
    }
    valid_outcomes = {
        "completed",
        "matched",
        "mismatch",
        "stale_no_mutation",
        "definitely_not_applied",
        "ambiguous",
        "failed",
        "skipped",
    }
    for item in _array(raw, "attempts", errors):
        attempt = _mapping(
            item,
            {
                "attempt_id",
                "ended_at",
                "evidence_refs",
                "operation_code",
                "outcome",
                "phase",
                "started_at",
                "subject",
            },
            "attempt",
            errors,
        )
        if not attempt:
            continue
        identifier = attempt.get("attempt_id")
        if not isinstance(identifier, str) or not _SAFE_CODE.fullmatch(identifier):
            errors.append("attempt ID is invalid")
        elif identifier in identifiers:
            errors.append("attempt IDs must be unique")
        else:
            identifiers.add(identifier)
        if attempt.get("phase") not in valid_phases:
            errors.append("attempt phase is unknown")
        if attempt.get("outcome") not in valid_outcomes:
            errors.append("attempt outcome is unknown")
        _check_references(attempt.get("evidence_refs"), evidence_ids, errors)
        _check_subject(attempt.get("subject"), errors)
        try:
            began = parse_rfc3339_utc(attempt.get("started_at"), "attempt started_at")
            ended = parse_rfc3339_utc(attempt.get("ended_at"), "attempt ended_at")
            if ended < began:
                errors.append("attempt ended before it started")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
    return identifiers


def _check_failures(
    raw: object,
    evidence_ids: set[str],
    errors: list[str],
) -> None:
    for item in _array(raw, "failures", errors):
        failure = _mapping(
            item,
            {
                "code",
                "effective_stop_scope",
                "evidence_refs",
                "inherent_stop_scope",
                "phase",
                "retry_classification",
                "safe_message",
                "subject",
            },
            "failure",
            errors,
        )
        if not failure:
            continue
        for key in ("code", "phase"):
            if not isinstance(failure.get(key), str) or not _SAFE_CODE.fullmatch(
                str(failure.get(key))
            ):
                errors.append(f"failure {key} is invalid")
        if failure.get("inherent_stop_scope") not in {"resource", "barrier", "run"}:
            errors.append("failure inherent stop scope is unknown")
        if failure.get("effective_stop_scope") not in {"resource", "barrier", "run"}:
            errors.append("failure effective stop scope is unknown")
        if failure.get("retry_classification") not in {
            "never",
            "replan",
            "same_run",
            "operator_action",
        }:
            errors.append("failure retry classification is unknown")
        message = failure.get("safe_message")
        if not isinstance(message, str) or not message or len(message) > 512:
            errors.append("failure safe message is invalid")
        _check_references(failure.get("evidence_refs"), evidence_ids, errors)
        _check_subject(failure.get("subject"), errors)


def _check_attachments(raw: object, errors: list[str]) -> None:
    seen: set[str] = set()
    for item in _array(raw, "attachments", errors):
        attachment = _mapping(
            item,
            {"codec", "digest", "kind"},
            "attachment",
            errors,
        )
        if not attachment:
            continue
        try:
            digest = require_sha256(attachment.get("digest"), "attachment digest")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
            continue
        if digest in seen:
            errors.append("attachment digests must be unique")
        seen.add(digest)
        for key in ("kind", "codec"):
            if not isinstance(attachment.get(key), str) or not _SAFE_CODE.fullmatch(
                str(attachment.get(key))
            ):
                errors.append(f"attachment {key} is invalid")


def _check_authority(raw: object, status: RunStatus, errors: list[str]) -> None:
    authority = _mapping(
        raw,
        {
            "binding_digest",
            "boot_id",
            "cleanup_state",
            "device_index_intent",
            "marker_digest",
            "marker_generation",
            "marker_phase",
            "ownership_state",
            "ownership_token_digest",
        },
        "authority",
        errors,
    )
    if not authority:
        return
    for key in (
        "binding_digest",
        "marker_digest",
        "ownership_token_digest",
    ):
        item = authority.get(key)
        if item is not None:
            try:
                require_sha256(item, key)
            except (TypeError, ValueError) as error:
                errors.append(str(error))
    if authority.get("ownership_state") not in {
        "not_acquired",
        "acquisition_pending",
        "owned",
        "released",
        "quarantined",
        "unknown",
    }:
        errors.append("ownership state is unknown")
    if authority.get("cleanup_state") not in {
        "not_started",
        "pending",
        "complete",
        "failed",
        "unknown",
    }:
        errors.append("cleanup state is unknown")
    if authority.get("device_index_intent") not in {
        "add_or_retain_active",
        "remove_after_release_or_quarantine",
        "no_change",
    }:
        errors.append("Device index intent is unknown")
    if (
        status in TERMINAL_RUN_STATUSES
        and authority.get("device_index_intent") == "remove_after_release_or_quarantine"
        and authority.get("ownership_state") not in {"released", "quarantined"}
    ):
        errors.append("active index removal precedes release or quarantine")


def _check_recovery(raw: object, status: RunStatus, errors: list[str]) -> None:
    recovery = _mapping(
        raw,
        {"actions", "required", "workspace_id"},
        "recovery",
        errors,
    )
    if not recovery:
        return
    workspace_id = recovery.get("workspace_id")
    if not isinstance(workspace_id, str) or not _WORKSPACE.fullmatch(workspace_id):
        errors.append("recovery workspace ID is invalid")
    required = recovery.get("required")
    if type(required) is not bool:
        errors.append("recovery required must be boolean")
    if required != (
        status in {RunStatus.INTERRUPTED, RunStatus.FAILED_RECOVERY_REQUIRED}
    ):
        errors.append("recovery-required fact does not match status")
    actions = _array(recovery.get("actions"), "recovery actions", errors)
    seen: set[tuple[object, object]] = set()
    for item in actions:
        action = _mapping(
            item,
            {
                "allowed",
                "code",
                "mode",
                "reason_code",
                "requires_approval",
                "requires_reason",
            },
            "recovery action",
            errors,
        )
        if not action:
            continue
        code = action.get("code")
        mode = action.get("mode")
        if code not in {"inspect", "resume_verification", "rollback", "finalize"}:
            errors.append("recovery action code is unknown")
        if (code == "finalize") != (mode in {"normal", "abandon"}):
            errors.append("recovery finalize mode is invalid")
        key = (code, mode)
        if key in seen:
            errors.append("recovery actions must be unique")
        seen.add(key)
        if mode == "abandon" and (
            action.get("requires_approval") is not True
            or action.get("requires_reason") is not True
        ):
            errors.append("abandonment requires separate approval and reason")
        if type(action.get("allowed")) is not bool:
            errors.append("recovery action allowed must be boolean")


def _check_cleanup(raw: object, status: RunStatus, errors: list[str]) -> None:
    cleanup = _mapping(
        raw,
        {"leftover_count", "state"},
        "cleanup",
        errors,
    )
    if not cleanup:
        return
    if cleanup.get("state") not in {
        "not_started",
        "pending",
        "complete",
        "failed",
        "unknown",
    }:
        errors.append("cleanup state is unknown")
    count = cleanup.get("leftover_count")
    if type(count) is not int or count < 0:
        errors.append("cleanup leftover count is invalid")
    if status not in TERMINAL_RUN_STATUSES and cleanup.get("state") != "not_started":
        errors.append("cleanup cannot begin before terminal truth")


def _check_resources(
    raw: object,
    status: RunStatus,
    attempt_ids: set[str],
    errors: list[str],
) -> None:
    seen: set[str] = set()
    for item in _array(raw, "resource_results", errors):
        result = _mapping(
            item,
            {
                "decisive_attempt_id",
                "desired_disposition",
                "final_convergence",
                "latest_observed_relation",
                "mutation_outcome",
                "post_effect_verification",
                "resource_id",
                "rollback_outcome",
                "verification_outcome",
            },
            "resource result",
            errors,
        )
        if not result:
            continue
        resource_id = result.get("resource_id")
        if not isinstance(resource_id, str) or not _SAFE_CODE.fullmatch(resource_id):
            errors.append("resource ID is invalid")
        elif resource_id in seen:
            errors.append("resource results must be unique")
        else:
            seen.add(resource_id)
        try:
            MutationOutcome(str(result.get("mutation_outcome")))
            VerificationOutcome(str(result.get("verification_outcome")))
            RollbackOutcome(str(result.get("rollback_outcome")))
            PostEffectVerification(str(result.get("post_effect_verification")))
            convergence = FinalConvergence(str(result.get("final_convergence")))
        except ValueError:
            errors.append("resource result contains unknown outcome")
            continue
        decisive = result.get("decisive_attempt_id")
        if decisive is not None and decisive not in attempt_ids:
            errors.append("resource decisive attempt reference is unresolved")
        if (
            status is RunStatus.CONVERGED
            and convergence is not FinalConvergence.CONVERGED
        ):
            errors.append("converged Run contains non-converged Resource")
        if status is RunStatus.FAILED_ROLLED_BACK and result.get(
            "rollback_outcome"
        ) not in {"restored_and_verified", "restored_or_unchanged"}:
            errors.append("failed_rolled_back requires verified restoration")


def _check_references(
    raw: object,
    identifiers: set[str],
    errors: list[str],
) -> None:
    references = _array(raw, "evidence references", errors)
    if any(not isinstance(item, str) or item not in identifiers for item in references):
        errors.append("evidence reference is unresolved")


def _check_subject(raw: object, errors: list[str]) -> None:
    subject = _mapping(raw, {"id", "kind"}, "subject", errors)
    if not subject:
        return
    if subject.get("kind") not in {"resource", "effect", "run", "device"}:
        errors.append("subject kind is unknown")
    if not isinstance(subject.get("id"), str) or not _SAFE_CODE.fullmatch(
        str(subject.get("id"))
    ):
        errors.append("subject ID is invalid")


def _mapping(
    value: object,
    fields: set[str],
    label: str,
    errors: list[str],
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        errors.append(f"unknown or missing {label} fields")
        return {}
    return value


def _array(value: object, label: str, errors: list[str]) -> list[object]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return []
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()
