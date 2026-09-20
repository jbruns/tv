"""Canonical execution/recovery Run revisions and independent invariants."""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from coreelec_reconciler.domain.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.domain.execution import (
    EXECUTION_EVIDENCE_OBSERVERS,
    EXECUTION_EVIDENCE_PAYLOAD_FIELDS,
    EXECUTION_RESOURCE_EVIDENCE_KINDS,
    TERMINAL_RUN_STATUSES,
    ExecutionEvidenceKind,
    FinalConvergence,
    MutationOutcome,
    PostEffectVerification,
    RollbackOutcome,
    RunStatus,
    SessionCloseDisposition,
    SessionCloseFailureCategory,
    VerificationOutcome,
    execution_run_identity,
    is_post_terminal_cleanup_successor,
)
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport
from coreelec_reconciler.domain.validation import (
    parse_rfc3339_utc,
    require_logical_id,
    require_sha256,
    require_uuid7,
)
from coreelec_reconciler.resource_types.builtins import built_in_resource_registry
from coreelec_reconciler.resource_types.registry import ResourceRegistry

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
_RESOURCE_TYPE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_WORKSPACE = re.compile(r"^workspace:[a-zA-Z0-9_-]{8,128}$")
_SESSION_CLOSE_FIELDS = {
    "authority_state",
    "current_digest",
    "device_id",
    "disposition",
    "failure",
    "kind",
    "observed_at",
    "observed_head_digest",
    "observed_head_revision",
    "producer",
    "record_id",
    "run_id",
    "schema_version",
    "seal_digest",
    "session_id",
    "terminal_digest",
    "terminal_revision",
    "workspace_id",
}
_SESSION_CLOSE_V2_FIELDS = _SESSION_CLOSE_FIELDS | {"run_kind"}


def build_execution_run_report(
    value: dict[str, object],
    resource_registry: ResourceRegistry | None = None,
) -> CanonicalRunReport:
    """Validate a complete revision value and add its canonical digest."""
    candidate = dict(value)
    candidate["current_digest"] = ""
    without_digest = {
        key: item for key, item in candidate.items() if key != "current_digest"
    }
    candidate["current_digest"] = _sha256(canonical_document_bytes(without_digest))
    return decode_execution_run_report(
        canonical_document_bytes(candidate),
        resource_registry=resource_registry,
    )


def check_session_close_invariants(content: bytes) -> tuple[str, ...]:
    """Independently validate one canonical session-close record."""
    errors: list[str] = []
    try:
        value = decode_json_object(content)
    except ValueError:
        return ("session close record is not a JSON object",)
    schema_version = value.get("schema_version")
    expected_fields = (
        _SESSION_CLOSE_V2_FIELDS if schema_version == 2 else _SESSION_CLOSE_FIELDS
    )
    if set(value) != expected_fields:
        return ("unknown or missing session close fields",)
    if canonical_document_bytes(value) != content:
        errors.append("session close bytes are not canonical")
    if value["kind"] != "CoreElecReconcilerSessionClose":
        errors.append("unsupported session close kind")
    if type(schema_version) is not int or schema_version not in {1, 2}:
        errors.append("unsupported session close schema version")
    run_kind = (
        "CoreElecReconcilerRunReport" if schema_version == 1 else value.get("run_kind")
    )
    if not isinstance(run_kind, str) or run_kind not in {
        "CoreElecReconcilerRunReport",
        "CoreElecReconcilerObservationRun",
    }:
        errors.append("unsupported session close Run kind")
    if schema_version == 2 and run_kind != "CoreElecReconcilerObservationRun":
        errors.append("session close version 2 requires observation Run kind")
    if value["producer"] != _PRODUCER:
        errors.append("unsupported session close producer")
    try:
        require_uuid7(value["record_id"], "session close record_id")
        require_uuid7(value["run_id"], "session close run_id")
        require_logical_id(value["device_id"], "session close device_id")
        parse_rfc3339_utc(value["observed_at"], "session close observed_at")
    except (TypeError, ValueError) as error:
        errors.append(str(error))
    session_id = value["session_id"]
    if not isinstance(session_id, str) or _SAFE_CODE.fullmatch(session_id) is None:
        errors.append("invalid session close session_id")
    workspace_id = value["workspace_id"]
    if not isinstance(workspace_id, str) or _WORKSPACE.fullmatch(workspace_id) is None:
        errors.append("invalid session close workspace_id")
    terminal_revision = value["terminal_revision"]
    head_revision = value["observed_head_revision"]
    if type(terminal_revision) is not int or terminal_revision < 1:
        errors.append("invalid session close terminal_revision")
    if type(head_revision) is not int or head_revision < 1:
        errors.append("invalid session close observed_head_revision")
    if (
        type(terminal_revision) is int
        and type(head_revision) is int
        and head_revision < terminal_revision
    ):
        errors.append("session close head precedes terminal truth")
    for field in (
        "terminal_digest",
        "observed_head_digest",
        "current_digest",
    ):
        try:
            require_sha256(value[field], f"session close {field}")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
    seal_digest = value["seal_digest"]
    if seal_digest is not None:
        try:
            require_sha256(seal_digest, "session close seal_digest")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
    authority_state = value["authority_state"]
    if not isinstance(authority_state, str) or authority_state not in {
        "acquisition_pending",
        "owned",
        "quarantined",
        "released",
        "unknown",
        "not_applicable",
    }:
        errors.append("unknown session close authority state")
    if run_kind == "CoreElecReconcilerObservationRun" and (
        schema_version != 2
        or authority_state != "not_applicable"
        or value["seal_digest"] is not None
    ):
        errors.append("invalid observation session close authority binding")
    if (
        run_kind == "CoreElecReconcilerRunReport"
        and authority_state == "not_applicable"
    ):
        errors.append("invalid execution session close authority binding")
    disposition_value = value["disposition"]
    try:
        disposition = (
            SessionCloseDisposition(disposition_value)
            if isinstance(disposition_value, str)
            else None
        )
    except ValueError:
        disposition = None
    if disposition is None:
        errors.append("unknown session close disposition")
    failure = value["failure"]
    if disposition is SessionCloseDisposition.COMPLETE:
        if failure is not None:
            errors.append("complete session close contains failure")
    elif disposition is not None:
        if not isinstance(failure, dict) or set(failure) != {"category", "code"}:
            errors.append("failed or unknown session close lacks failure")
        else:
            category = failure["category"]
            try:
                valid_category = (
                    SessionCloseFailureCategory(category)
                    if isinstance(category, str)
                    else None
                )
            except ValueError:
                valid_category = None
            if valid_category is None:
                errors.append("unknown session close failure category")
            code = failure["code"]
            if not isinstance(code, str) or _SAFE_CODE.fullmatch(code) is None:
                errors.append("invalid session close failure code")
    digest = value["current_digest"]
    if isinstance(digest, str):
        without_digest = {
            key: item for key, item in value.items() if key != "current_digest"
        }
        if _sha256(canonical_document_bytes(without_digest)) != digest:
            errors.append("session close digest mismatch")
    return tuple(errors)


def decode_execution_run_report(
    content: bytes,
    plan: CanonicalPlan | None = None,
    *,
    resource_registry: ResourceRegistry | None = None,
) -> CanonicalRunReport:
    value = decode_json_object(content)
    if set(value) != _FIELDS:
        raise ValueError("unknown or missing execution Run Report fields")
    if canonical_document_bytes(value) != content:
        raise ValueError("execution Run Report bytes are not canonical")
    errors = check_run_report_invariants(
        content,
        plan,
        resource_registry=resource_registry,
    )
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
    *,
    resource_registry: ResourceRegistry | None = None,
) -> tuple[CanonicalRunReport, ...]:
    registry = resource_registry or built_in_resource_registry()
    decoded = tuple(
        decode_execution_run_report(
            content,
            plan,
            resource_registry=registry,
        )
        for content in revisions
    )
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
        if terminal_seen and not is_post_terminal_cleanup_successor(
            decode_json_object(decoded[index - 1].canonical_bytes),
            value,
            resource_registry=registry,
        ):
            raise ValueError("terminal Run has a non-cleanup successor")
        evidence = value.get("evidence")
        has_cleanup = isinstance(evidence, list) and any(
            isinstance(item, dict)
            and item.get("payload_kind")
            == ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT.value
            for item in evidence
        )
        if has_cleanup and (index == 0 or previous_status not in TERMINAL_RUN_STATUSES):
            raise ValueError("cleanup receipt requires a prior terminal revision")
        if previous_status is not None and report.status != previous_status:
            allowed = _LIFECYCLE_TRANSITIONS.get(previous_status, set())
            if report.status not in allowed:
                raise ValueError("invalid Run status transition")
        terminal_seen = report.status in TERMINAL_RUN_STATUSES
        previous_status = report.status
    return decoded


def check_run_report_invariants(
    content: bytes,
    plan: CanonicalPlan | None = None,
    *,
    resource_registry: ResourceRegistry | None = None,
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
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
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
    attachment_digests = _check_attachments(value["attachments"], errors)
    registry = resource_registry or built_in_resource_registry()
    evidence_kinds = _check_evidence(
        value,
        status,
        attachment_digests,
        registry.type_codes,
        errors,
    )
    attempt_ids = _check_attempts(
        value,
        evidence_kinds,
        errors,
    )
    _check_failures(value["failures"], set(evidence_kinds), errors)
    _check_authority(value["authority"], status, errors)
    _check_recovery(value["recovery"], status, errors)
    _check_cleanup(value["cleanup"], status, errors)
    authority_value = value["authority"]
    cleanup_value = value["cleanup"]
    if (
        isinstance(authority_value, dict)
        and isinstance(cleanup_value, dict)
        and authority_value.get("cleanup_state") != cleanup_value.get("state")
    ):
        errors.append("authority and cleanup state disagree")
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


def _check_evidence(
    report: dict[str, object],
    status: RunStatus,
    attachment_digests: set[str],
    registered_resource_types: frozenset[str],
    errors: list[str],
) -> dict[str, ExecutionEvidenceKind]:
    values = _array(report["evidence"], "evidence", errors)
    records: list[_OracleEvidence] = []
    identifiers: dict[str, ExecutionEvidenceKind] = {}
    for value in values:
        record = _oracle_decode_evidence(
            value,
            report,
            attachment_digests,
            registered_resource_types,
            errors,
        )
        if record is not None:
            records.append(record)
            if record.identifier in identifiers:
                errors.append("execution evidence IDs are duplicated")
            identifiers[record.identifier] = record.kind
    _oracle_check_evidence_sequence(records, status, errors)
    _oracle_check_evidence_summary(report, records, errors)
    return identifiers


@dataclass(frozen=True, slots=True)
class _OracleEvidence:
    identifier: str
    kind: ExecutionEvidenceKind
    observed_at: str
    subject_kind: str
    subject_id: str
    resource_type: str | None
    bindings: dict[str, object]
    state_addresses: tuple[str, ...]
    payload: dict[str, object]


_EVIDENCE_FIELDS = {
    "attachment_refs",
    "attempt",
    "bindings",
    "evidence_id",
    "observed_at",
    "observer",
    "payload",
    "payload_kind",
    "payload_schema_version",
    "raw_attachment_digest",
    "resource_type",
    "state_addresses",
    "subject",
}
_EVIDENCE_BINDING_FIELDS = {
    "binding_digest",
    "change_id",
    "device_id",
    "plan_full_digest",
    "plan_id",
    "resource_id",
    "run_id",
    "workspace_id",
}


def _oracle_decode_evidence(
    raw: object,
    report: dict[str, object],
    attachment_digests: set[str],
    registered_resource_types: frozenset[str],
    errors: list[str],
) -> _OracleEvidence | None:
    if not isinstance(raw, dict) or set(raw) != _EVIDENCE_FIELDS:
        errors.append("unknown or missing execution evidence fields")
        return None
    try:
        kind = ExecutionEvidenceKind(raw["payload_kind"])
    except TypeError, ValueError:
        errors.append("unknown execution evidence kind")
        return None
    if (
        type(raw["payload_schema_version"]) is not int
        or raw["payload_schema_version"] != 1
    ):
        errors.append("unsupported execution evidence schema version")
    payload = raw["payload"]
    if (
        not isinstance(payload, dict)
        or set(payload) != EXECUTION_EVIDENCE_PAYLOAD_FIELDS[kind]
    ):
        errors.append("unknown or missing execution evidence payload fields")
        return None
    observer = raw["observer"]
    if (
        not isinstance(observer, dict)
        or set(observer) != {"code", "version"}
        or observer.get("code") != EXECUTION_EVIDENCE_OBSERVERS[kind]
        or type(observer.get("version")) is not int
        or observer.get("version") != 1
    ):
        errors.append("unsupported execution evidence observer")
    subject = raw["subject"]
    if not isinstance(subject, dict) or set(subject) != {"id", "kind"}:
        errors.append("unknown or missing execution evidence subject fields")
        return None
    _oracle_code(subject["id"], "subject ID", errors)
    _oracle_code(subject["kind"], "subject kind", errors)
    bindings = raw["bindings"]
    if not isinstance(bindings, dict) or set(bindings) != _EVIDENCE_BINDING_FIELDS:
        errors.append("unknown or missing execution evidence bindings fields")
        return None
    identifier = raw["evidence_id"]
    observed_at = raw["observed_at"]
    if not isinstance(identifier, str) or not _SAFE_CODE.fullmatch(identifier):
        errors.append("invalid execution evidence evidence ID")
        return None
    try:
        parse_rfc3339_utc(observed_at, "evidence observed_at")
        require_logical_id(bindings["device_id"], "evidence Device ID")
        require_uuid7(bindings["run_id"], "evidence Run ID")
        require_uuid7(bindings["plan_id"], "evidence Plan ID")
        require_sha256(bindings["plan_full_digest"], "evidence Plan digest")
        require_sha256(bindings["binding_digest"], "evidence binding digest")
    except (TypeError, ValueError) as error:
        errors.append(str(error))
        return None
    reference = report["plan_reference"]
    authority = report["authority"]
    recovery = report["recovery"]
    if (
        not isinstance(reference, dict)
        or not isinstance(authority, dict)
        or not isinstance(recovery, dict)
        or bindings["device_id"] != report["device_id"]
        or bindings["run_id"] != report["run_id"]
        or bindings["workspace_id"] != recovery.get("workspace_id")
        or bindings["plan_id"] != reference.get("plan_id")
        or bindings["plan_full_digest"] != reference.get("plan_full_digest")
        or bindings["binding_digest"] != authority.get("binding_digest")
    ):
        errors.append("execution evidence bindings do not match Run")
    resource_type = raw["resource_type"]
    resource_bound = kind in EXECUTION_RESOURCE_EVIDENCE_KINDS or (
        kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT
        and resource_type is not None
    )
    addresses = _oracle_state_addresses(raw["state_addresses"], errors)
    attempt = raw["attempt"]
    if resource_bound:
        if resource_type not in registered_resource_types:
            errors.append("unknown execution evidence Resource Type")
        if (
            not isinstance(bindings["resource_id"], str)
            or not _SAFE_CODE.fullmatch(bindings["resource_id"])
            or not isinstance(bindings["change_id"], str)
            or not _SAFE_CODE.fullmatch(bindings["change_id"])
        ):
            errors.append("Resource evidence bindings are incomplete")
        if subject != {"id": bindings["resource_id"], "kind": "resource"}:
            errors.append("Resource evidence subject does not match bindings")
        if not addresses:
            errors.append("Resource evidence State Addresses are invalid")
        if type(attempt) is not int or attempt != 1:
            errors.append("execution evidence attempt must be 1")
    else:
        expected_kind = (
            "device"
            if kind is ExecutionEvidenceKind.AUTHORITY_EVIDENCE
            else "run"
            if kind is ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL
            else "effect"
        )
        expected_id = (
            bindings["device_id"]
            if expected_kind == "device"
            else bindings["run_id"]
            if expected_kind == "run"
            else subject.get("id")
            if kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT
            else payload.get("effect_code")
        )
        if (
            resource_type is not None
            or bindings["resource_id"] is not None
            or bindings["change_id"] is not None
            or addresses
        ):
            errors.append("non-Resource evidence has Resource-only bindings")
        if subject != {"id": expected_id, "kind": expected_kind}:
            errors.append("execution evidence subject does not match kind")
        operation_evidence = kind in {
            ExecutionEvidenceKind.EFFECT_INTENT,
            ExecutionEvidenceKind.EFFECT_OUTCOME,
            ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
        }
        if operation_evidence and (type(attempt) is not int or attempt != 1):
            errors.append("Effect operation evidence attempt must be 1")
        if not operation_evidence and attempt is not None:
            errors.append("non-operation evidence attempt must be null")
    _oracle_check_attachments(raw, payload, attachment_digests, errors)
    _oracle_check_payload(kind, payload, registered_resource_types, errors)
    if kind is ExecutionEvidenceKind.EFFECT_INTENT:
        approvals = report["approvals"]
        expected_approvals = (
            {
                f"approval.{approval.get('scope')}"
                for approval in approvals
                if isinstance(approval, dict) and isinstance(approval.get("scope"), str)
            }
            if isinstance(approvals, list)
            else set()
        )
        if payload["approval_evidence_ref"] not in expected_approvals:
            errors.append("Effect approval evidence reference is unresolved")
    _oracle_reject_unsafe(payload, errors)
    if not isinstance(observed_at, str):
        return None
    return _OracleEvidence(
        identifier,
        kind,
        observed_at,
        str(subject["kind"]),
        str(subject["id"]),
        resource_type if isinstance(resource_type, str) else None,
        bindings,
        addresses,
        payload,
    )


def _oracle_state_addresses(raw: object, errors: list[str]) -> tuple[str, ...]:
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        errors.append("execution evidence state address must be a string array")
        return ()
    addresses = tuple(raw)
    if tuple(sorted(set(addresses))) != addresses or any(
        not item.startswith("special://")
        or any(token in item for token in ("\n", "\r", "\\", ".."))
        for item in addresses
    ):
        errors.append("Resource evidence State Addresses are invalid")
    return addresses


def _oracle_check_attachments(
    raw: dict[str, object],
    payload: dict[str, object],
    attachment_digests: set[str],
    errors: list[str],
) -> None:
    references = raw["attachment_refs"]
    if not isinstance(references, list):
        errors.append("execution evidence attachment_refs must be an array")
        return
    declared: set[str] = set()
    for reference in references:
        if not isinstance(reference, dict) or set(reference) != {
            "codec",
            "digest",
            "kind",
        }:
            errors.append("execution evidence attachment reference is invalid")
            continue
        _oracle_code(reference["codec"], "attachment codec", errors)
        _oracle_code(reference["kind"], "attachment kind", errors)
        try:
            digest = require_sha256(reference["digest"], "attachment digest")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
            continue
        if digest in declared:
            errors.append("execution evidence attachment references are duplicated")
        declared.add(digest)
        if digest not in attachment_digests:
            errors.append("execution evidence attachment reference is unresolved")
    for key, item in payload.items():
        if (
            key.endswith("_attachment_digest")
            and item is not None
            and item not in declared
        ):
            errors.append("payload attachment digest is not declared")
    raw_digest = raw["raw_attachment_digest"]
    if raw_digest is not None:
        try:
            digest = require_sha256(raw_digest, "raw attachment digest")
            if digest not in attachment_digests:
                errors.append("execution evidence raw attachment is unresolved")
        except (TypeError, ValueError) as error:
            errors.append(str(error))


def _oracle_check_payload(
    kind: ExecutionEvidenceKind,
    payload: dict[str, object],
    registered_resource_types: frozenset[str],
    errors: list[str],
) -> None:
    for key, item in payload.items():
        if key.endswith("_digest") and item is not None:
            try:
                require_sha256(item, key)
            except (TypeError, ValueError) as error:
                errors.append(str(error))
        if key.endswith("_digests"):
            values = _oracle_string_list(item, key, errors)
            if len(set(values)) != len(values):
                errors.append(f"{key} values are duplicated")
            for digest in values:
                try:
                    require_sha256(digest, key)
                except (TypeError, ValueError) as error:
                    errors.append(str(error))
    if kind is ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION:
        presence = payload["presence"]
        if presence not in {"present", "absent", "unknown"}:
            errors.append("unknown Observation presence")
        if payload["relation"] not in {
            "before",
            "post",
            "allowed_intermediate",
            "other",
            "unknown",
        }:
            errors.append("unknown Observation relation")
        mode = payload["managed_mode"]
        if mode is not None and (type(mode) is not int or not 0 <= mode <= 0o777):
            errors.append("invalid managed mode")
        state = (payload["entry_kind"], payload["content_digest"], mode)
        if presence == "present" and (
            state[0] != "regular" or state[1] is None or state[2] is None
        ):
            errors.append("present Observation is incomplete")
        if presence != "present" and any(item is not None for item in state):
            errors.append("non-present Observation claims file state")
    elif kind is ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED:
        if type(payload["rollback_capable"]) is not bool:
            errors.append("rollback_capable must be boolean")
        objects = _oracle_string_list(
            payload["cleanup_object_refs"],
            "cleanup object reference",
            errors,
        )
        if not objects or len(set(objects)) != len(objects):
            errors.append("cleanup object references are incomplete")
        for item in objects:
            _oracle_code(item, "cleanup object reference", errors)
    elif kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT:
        primitive = payload["primitive"]
        if primitive not in {
            "stage_write",
            "chmod",
            "atomic_replace",
            "remove",
            "restore",
            "cleanup",
        }:
            errors.append("unknown primitive kind")
        _oracle_code(payload["operation_id"], "operation ID", errors)
        _oracle_positive_int(payload["marker_generation"], "marker generation", errors)
        if payload["marker_phase"] not in {
            "acquired",
            "preparing",
            "prepared",
            "mutating",
            "verifying",
            "effect",
            "rolling_back",
            "terminal_release_pending",
            "quarantine_pending",
        }:
            errors.append("unknown remote marker phase")
        state_primitive = primitive in {
            "stage_write",
            "chmod",
            "atomic_replace",
            "remove",
            "restore",
        }
        if state_primitive and (
            payload["expected_before_digest"] is None
            or payload["expected_after_digest"] is None
            or payload["terminal_revision_digest"] is not None
            or payload["manifest_object_ref"] is not None
        ):
            errors.append("state primitive intent bindings are incomplete")
        if primitive == "cleanup" and (
            payload["terminal_revision_digest"] is None
            or payload["manifest_object_ref"] is None
            or payload["expected_before_digest"] is not None
            or payload["expected_after_digest"] is not None
            or payload["allowed_intermediate_state_digests"] != []
        ):
            errors.append("cleanup primitive intent bindings are incomplete")
        content_required = primitive in {"stage_write", "atomic_replace", "restore"}
        if content_required != (payload["content_attachment_digest"] is not None):
            errors.append("primitive content attachment is invalid")
    elif kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT:
        _oracle_code(payload["operation_id"], "operation ID", errors)
        _oracle_positive_int(payload["generation"], "marker generation", errors)
        if payload["phase"] not in {
            "acquired",
            "preparing",
            "prepared",
            "mutating",
            "verifying",
            "effect",
            "rolling_back",
            "terminal_release_pending",
            "quarantine_pending",
        }:
            errors.append("unknown remote marker phase")
    elif kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME:
        if payload["disposition"] not in {
            "applied",
            "definitely_not_applied",
            "ambiguous",
        }:
            errors.append("unknown primitive disposition")
        _oracle_code(payload["operation_id"], "operation ID", errors)
        _oracle_positive_int(payload["receipt_sequence"], "receipt sequence", errors)
    elif kind is ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT:
        if payload["mutation_outcome"] not in {item.value for item in MutationOutcome}:
            errors.append("unknown mutation outcome")
    elif kind is ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT:
        if payload["outcome"] not in {item.value for item in VerificationOutcome}:
            errors.append("unknown Verification outcome")
        if payload["relation"] not in {
            "before",
            "post",
            "allowed_intermediate",
            "other",
            "unknown",
        }:
            errors.append("unknown state relation")
        if type(payload["post_effect"]) is not bool:
            errors.append("post_effect must be boolean")
    elif kind is ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT:
        if payload["outcome"] not in {item.value for item in RollbackOutcome}:
            errors.append("unknown rollback outcome")
        if payload["relation"] not in {
            "before",
            "post",
            "allowed_intermediate",
            "other",
            "unknown",
        }:
            errors.append("unknown state relation")
        _oracle_code(payload["original_failure_code"], "failure code", errors)
    elif kind is ExecutionEvidenceKind.RESOURCE_SKIP_RESULT:
        if payload["final_convergence"] not in {
            item.value for item in FinalConvergence
        }:
            errors.append("unknown final convergence")
        if payload["stop_scope"] not in {"resource", "barrier", "run"}:
            errors.append("unknown stop scope")
        _oracle_code(payload["reason_code"], "skip reason", errors)
    elif kind is ExecutionEvidenceKind.RECOVERY_VERIFICATION_RESULT:
        if payload["action"] not in {"resume_verification", "rollback"}:
            errors.append("unknown recovery Verification action")
        if payload["outcome"] not in {item.value for item in VerificationOutcome}:
            errors.append("unknown Verification outcome")
        if payload["relation"] not in {
            "before",
            "post",
            "allowed_intermediate",
            "other",
            "unknown",
        }:
            errors.append("unknown state relation")
    elif kind is ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT:
        if payload["disposition"] not in {
            "applied",
            "definitely_not_applied",
            "ambiguous",
        }:
            errors.append("unknown primitive disposition")
        _oracle_code(payload["operation_id"], "operation ID", errors)
        _oracle_code(
            payload["manifest_object_ref"],
            "manifest object reference",
            errors,
        )
        if type(payload["leftover"]) is not bool:
            errors.append("cleanup leftover must be boolean")
    elif kind is ExecutionEvidenceKind.EFFECT_INTENT:
        _oracle_code(payload["effect_code"], "Effect code", errors)
        _oracle_code(payload["operation_id"], "operation ID", errors)
        _oracle_code(
            payload["approval_evidence_ref"],
            "approval evidence reference",
            errors,
        )
        _oracle_positive_int(payload["marker_generation"], "marker generation", errors)
        if payload["marker_phase"] != "effect":
            errors.append("Effect intent marker phase must be effect")
        _oracle_affected_resources(
            payload["affected_resources"],
            registered_resource_types,
            errors,
        )
    elif kind is ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION:
        _oracle_code(payload["effect_code"], "Effect code", errors)
        _oracle_code(payload["readiness_code"], "readiness code", errors)
        if type(payload["positive"]) is not bool:
            errors.append("Effect readiness positive must be boolean")
    elif kind is ExecutionEvidenceKind.EFFECT_OUTCOME:
        _oracle_code(payload["effect_code"], "Effect code", errors)
        _oracle_code(payload["operation_id"], "operation ID", errors)
        if payload["disposition"] not in {
            "definitely_succeeded",
            "definitely_failed",
            "ambiguous",
        }:
            errors.append("unknown Effect disposition")
        references = _oracle_string_list(
            payload["post_effect_evidence_refs"],
            "post-Effect evidence reference",
            errors,
        )
        if not references or len(set(references)) != len(references):
            errors.append("post-Effect evidence references are incomplete")
    elif kind is ExecutionEvidenceKind.AUTHORITY_EVIDENCE:
        if payload["ownership_state"] not in {
            "acquisition_pending",
            "owned",
            "released",
            "quarantined",
            "unknown",
        }:
            errors.append("unknown authority evidence state")
        generation = payload["generation"]
        if generation is not None:
            _oracle_positive_int(generation, "authority generation", errors)
        if payload["phase"] is not None and payload["phase"] not in {
            "acquired",
            "preparing",
            "prepared",
            "mutating",
            "verifying",
            "effect",
            "rolling_back",
            "terminal_release_pending",
            "quarantine_pending",
        }:
            errors.append("unknown authority evidence phase")
    elif kind is ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL:
        _oracle_code(payload["actor"], "abandonment actor", errors)
        _oracle_code(payload["mechanism"], "abandonment mechanism", errors)
        try:
            parse_rfc3339_utc(
                payload["approved_at"],
                "abandonment approval time",
            )
        except (TypeError, ValueError) as error:
            errors.append(str(error))
        reason = payload["reason"]
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 512:
            errors.append("abandonment reason must be non-empty and safe")


def _oracle_check_evidence_sequence(
    records: list[_OracleEvidence],
    status: RunStatus,
    errors: list[str],
) -> None:
    by_id: dict[str, _OracleEvidence] = {}
    operations: dict[str, dict[ExecutionEvidenceKind, _OracleEvidence]] = {}
    operation_bindings: dict[str, tuple[object, ...]] = {}
    resource_kinds: dict[tuple[object, object], set[ExecutionEvidenceKind]] = {}
    result_signatures: set[tuple[object, ...]] = set()
    prior: _OracleEvidence | None = None
    for record in records:
        if prior is not None and record.observed_at < prior.observed_at:
            errors.append("execution evidence records are out of order")
        key = (record.bindings["resource_id"], record.bindings["change_id"])
        seen = resource_kinds.setdefault(key, set())
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED
            and ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION not in seen
        ):
            errors.append("Resource preparation precedes fresh Observation")
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT
            and ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED not in seen
        ):
            errors.append("primitive intent precedes Resource preparation")
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT
            and ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT not in seen
        ):
            errors.append("Resource Verification precedes execution result")
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT
            and ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT not in seen
        ):
            errors.append("Resource rollback precedes execution result")
        mutation_kinds = {
            ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
            ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
            ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME,
            ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT,
            ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT,
            ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT,
        }
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_SKIP_RESULT
            and seen & mutation_kinds
        ) or (
            record.kind in mutation_kinds
            and ExecutionEvidenceKind.RESOURCE_SKIP_RESULT in seen
        ):
            errors.append("Resource skip conflicts with execution evidence")
        payload = record.payload
        operation_id = payload.get("operation_id")
        if isinstance(operation_id, str):
            binding = (
                record.subject_kind,
                record.subject_id,
                tuple(sorted(record.bindings.items())),
            )
            if (
                operation_id in operation_bindings
                and operation_bindings[operation_id] != binding
            ):
                errors.append("execution operation bindings changed")
            operation_bindings[operation_id] = binding
            operation = operations.setdefault(operation_id, {})
            if record.kind in operation:
                errors.append("execution operation evidence is duplicated")
            if record.kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT:
                intent = operation.get(
                    ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT
                ) or operation.get(ExecutionEvidenceKind.EFFECT_INTENT)
                if intent is None:
                    errors.append("marker checkpoint precedes operation intent")
                else:
                    if prior is None or prior.identifier != intent.identifier:
                        errors.append("marker checkpoint is not immediate")
                    if (
                        payload["marker_digest"] != intent.payload["marker_digest"]
                        or payload["generation"] != intent.payload["marker_generation"]
                        or payload["phase"] != intent.payload["marker_phase"]
                        or payload["token_digest"] != intent.payload["token_digest"]
                    ):
                        errors.append("marker checkpoint does not match intent")
            if record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME and not {
                ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
                ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
            } <= set(operation):
                errors.append("primitive outcome lacks intent/checkpoint")
            if record.kind is ExecutionEvidenceKind.EFFECT_OUTCOME and not {
                ExecutionEvidenceKind.EFFECT_INTENT,
                ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT,
            } <= set(operation):
                errors.append("Effect outcome lacks intent/checkpoint")
            if record.kind is ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT:
                intent = operation.get(ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT)
                if (
                    intent is None
                    or operation.get(ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT)
                    is None
                    or intent.payload.get("primitive") != "cleanup"
                ):
                    errors.append("cleanup receipt lacks intent/checkpoint")
            operation[record.kind] = record
        signature = _oracle_result_signature(record)
        if signature is not None:
            if signature in result_signatures:
                errors.append("execution result evidence is duplicated")
            result_signatures.add(signature)
        _oracle_check_references(record, by_id, operations, errors)
        if (
            record.kind is ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT
            and status not in TERMINAL_RUN_STATUSES
        ):
            errors.append("cleanup receipt precedes terminal Run truth")
        if (
            record.kind is ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL
            and status
            not in {RunStatus.INTERRUPTED, RunStatus.FAILED_RECOVERY_REQUIRED}
        ):
            errors.append("abandonment approval is invalid for Run status")
        by_id[record.identifier] = record
        seen.add(record.kind)
        prior = record


def _oracle_result_signature(record: _OracleEvidence) -> tuple[object, ...] | None:
    key = (record.bindings["resource_id"], record.bindings["change_id"])
    if record.kind in {
        ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED,
        ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT,
        ExecutionEvidenceKind.RESOURCE_ROLLBACK_RESULT,
        ExecutionEvidenceKind.RESOURCE_SKIP_RESULT,
        ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL,
    }:
        return (*key, record.kind)
    if record.kind is ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT:
        return (*key, record.kind, record.payload["post_effect"])
    if record.kind in {
        ExecutionEvidenceKind.EFFECT_INTENT,
        ExecutionEvidenceKind.EFFECT_OUTCOME,
    }:
        return (record.kind, record.payload["effect_code"])
    return None


def _oracle_check_references(
    record: _OracleEvidence,
    by_id: dict[str, _OracleEvidence],
    operations: dict[str, dict[ExecutionEvidenceKind, _OracleEvidence]],
    errors: list[str],
) -> None:
    for key, item in record.payload.items():
        if (
            key.endswith("_evidence_ref")
            and key != "approval_evidence_ref"
            and item is not None
            and (not isinstance(item, str) or item not in by_id)
        ):
            errors.append("execution evidence reference is unresolved or forward")
        if key.endswith("_evidence_refs"):
            for reference in _oracle_string_list(item, key, errors):
                if reference not in by_id:
                    errors.append(
                        "execution evidence reference is unresolved or forward"
                    )
    expected = {
        "intent_evidence_ref": ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT,
        "observation_evidence_ref": ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION,
        "outcome_evidence_ref": ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME,
    }
    for key, kind in expected.items():
        target_ref = record.payload.get(key)
        if isinstance(target_ref, str) and (
            target_ref not in by_id or by_id[target_ref].kind is not kind
        ):
            errors.append("execution evidence reference has the wrong kind")
        elif (
            isinstance(target_ref, str)
            and target_ref in by_id
            and (
                by_id[target_ref].bindings["resource_id"]
                != record.bindings["resource_id"]
                or by_id[target_ref].bindings["change_id"]
                != record.bindings["change_id"]
            )
        ):
            errors.append("execution evidence reference bindings do not match")
    if record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME:
        observation_ref = record.payload["observation_evidence_ref"]
        observation = by_id.get(str(observation_ref))
        if (
            observation is not None
            and observation.kind is ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION
            and observation.payload["normalized_state_digest"]
            != record.payload["observed_state_digest"]
        ):
            errors.append("primitive outcome does not match fresh Observation")
    if record.kind is ExecutionEvidenceKind.EFFECT_INTENT:
        readiness = by_id.get(str(record.payload["readiness_evidence_ref"]))
        if (
            readiness is None
            or readiness.kind is not ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION
        ):
            errors.append("Effect intent readiness reference is invalid")
    if record.kind is ExecutionEvidenceKind.EFFECT_OUTCOME:
        readiness_ref = record.payload["readiness_evidence_ref"]
        readiness = by_id.get(str(readiness_ref))
        operation = operations.get(str(record.payload["operation_id"]), {})
        checkpoint = operation.get(ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT)
        intent = operation.get(ExecutionEvidenceKind.EFFECT_INTENT)
        if (
            readiness is None
            or readiness.kind is not ExecutionEvidenceKind.EFFECT_READINESS_OBSERVATION
            or checkpoint is None
            or readiness.observed_at <= checkpoint.observed_at
            or readiness.payload.get("positive") is not True
        ):
            errors.append("Effect outcome lacks fresh positive readiness")
        if intent is not None and checkpoint is not None:
            _oracle_check_post_effect_observations(
                record,
                intent,
                checkpoint,
                readiness,
                by_id,
                errors,
            )


def _oracle_check_post_effect_observations(
    outcome: _OracleEvidence,
    intent: _OracleEvidence,
    checkpoint: _OracleEvidence,
    readiness: _OracleEvidence | None,
    by_id: dict[str, _OracleEvidence],
    errors: list[str],
) -> None:
    expected = set(
        _oracle_affected_resources(
            intent.payload["affected_resources"],
            frozenset(),
            errors,
            check_registration=False,
        )
    )
    references = _oracle_string_list(
        outcome.payload["post_effect_evidence_refs"],
        "post-Effect evidence reference",
        errors,
    )
    actual: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for reference in references:
        observation = by_id.get(reference)
        if (
            observation is None
            or observation.kind is not ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION
            or observation.observed_at <= checkpoint.observed_at
            or (
                readiness is not None
                and observation.observed_at <= readiness.observed_at
            )
            or any(
                observation.bindings[field] != outcome.bindings[field]
                for field in (
                    "run_id",
                    "workspace_id",
                    "device_id",
                    "plan_id",
                    "plan_full_digest",
                    "binding_digest",
                )
            )
            or observation.resource_type is None
            or not isinstance(observation.bindings["resource_id"], str)
            or not isinstance(observation.bindings["change_id"], str)
        ):
            errors.append("post-Effect evidence reference is not a fresh Observation")
            continue
        actual.add(
            (
                observation.resource_type,
                observation.bindings["resource_id"],
                observation.bindings["change_id"],
                observation.state_addresses,
            )
        )
    if actual != expected or len(actual) != len(references):
        errors.append("post-Effect observations do not cover affected Resources")


def _oracle_affected_resources(
    raw: object,
    registered_resource_types: frozenset[str],
    errors: list[str],
    *,
    check_registration: bool = True,
) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
    if not isinstance(raw, list) or not raw:
        errors.append("Effect affected Resources must be a non-empty array")
        return ()
    result: list[tuple[str, str, str, tuple[str, ...]]] = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {
            "change_id",
            "resource_id",
            "resource_type",
            "state_addresses",
        }:
            errors.append("Effect affected Resource fields are invalid")
            continue
        resource_type = item["resource_type"]
        resource_id = item["resource_id"]
        change_id = item["change_id"]
        addresses = _oracle_state_addresses(item["state_addresses"], errors)
        if not addresses:
            errors.append("Effect affected Resource State Addresses are invalid")
        if (
            not isinstance(resource_type, str)
            or not _RESOURCE_TYPE_CODE.fullmatch(resource_type)
            or (check_registration and resource_type not in registered_resource_types)
        ):
            errors.append("unknown execution evidence Resource Type")
            continue
        if (
            not isinstance(resource_id, str)
            or not _SAFE_CODE.fullmatch(resource_id)
            or not isinstance(change_id, str)
            or not _SAFE_CODE.fullmatch(change_id)
        ):
            errors.append("Effect affected Resource identity is invalid")
            continue
        result.append((resource_type, resource_id, change_id, addresses))
    if len(set(result)) != len(result):
        errors.append("Effect affected Resources are duplicated")
    return tuple(result)


def _oracle_check_evidence_summary(
    report: dict[str, object],
    records: list[_OracleEvidence],
    errors: list[str],
) -> None:
    cleanup = report["cleanup"]
    authority = report["authority"]
    if not isinstance(cleanup, dict) or not isinstance(authority, dict):
        return
    required: set[tuple[object, object, object]] = set()
    intents: dict[str, _OracleEvidence] = {}
    checkpoints: set[str] = set()
    receipts: dict[tuple[object, object, object], _OracleEvidence] = {}
    latest_authority: _OracleEvidence | None = None
    for record in records:
        payload = record.payload
        if record.kind is ExecutionEvidenceKind.RESOURCE_PREPARATION_COMPLETED:
            for object_ref in _oracle_string_list(
                payload["cleanup_object_refs"],
                "cleanup object reference",
                errors,
            ):
                required.add(
                    (
                        record.bindings["resource_id"],
                        record.bindings["change_id"],
                        object_ref,
                    )
                )
        elif (
            record.kind is ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT
            and payload["primitive"] == "cleanup"
        ):
            intents[str(payload["operation_id"])] = record
        elif record.kind is ExecutionEvidenceKind.REMOTE_MARKER_CHECKPOINT:
            checkpoints.add(str(payload["operation_id"]))
        elif record.kind is ExecutionEvidenceKind.RESOURCE_CLEANUP_RECEIPT:
            operation_id = str(payload["operation_id"])
            intent = intents.get(operation_id)
            key = (
                record.bindings["resource_id"],
                record.bindings["change_id"],
                payload["manifest_object_ref"],
            )
            if (
                intent is None
                or operation_id not in checkpoints
                or intent.payload["manifest_object_ref"]
                != payload["manifest_object_ref"]
                or payload["disposition"] not in {"applied", "definitely_not_applied"}
                or key in receipts
            ):
                errors.append("cleanup receipt is not proven by intent/checkpoint")
            receipts[key] = record
        elif record.kind is ExecutionEvidenceKind.AUTHORITY_EVIDENCE:
            latest_authority = record
    leftovers = sum(record.payload["leftover"] is True for record in receipts.values())
    if cleanup.get("leftover_count") != leftovers:
        errors.append("cleanup leftover summary is not proven by receipts")
    if cleanup.get("state") == "complete" and (
        set(receipts) != required or leftovers != 0
    ):
        errors.append("complete cleanup is not proven by receipts")
    ownership = authority.get("ownership_state")
    if ownership == "released" and cleanup.get("state") != "complete":
        errors.append("authority release precedes complete cleanup")
    if latest_authority is not None:
        if (
            latest_authority.payload["ownership_state"] != ownership
            or latest_authority.payload["token_digest"]
            != authority.get("ownership_token_digest")
            or latest_authority.payload["generation"]
            != authority.get("marker_generation")
            or latest_authority.payload["marker_digest"]
            != authority.get("marker_digest")
            or latest_authority.payload["phase"] != authority.get("marker_phase")
            or (
                ownership == "quarantined"
                and latest_authority.payload["quarantine_receipt_digest"] is None
            )
        ):
            errors.append("authority release or quarantine is not proven by evidence")
    elif ownership in {"released", "quarantined"}:
        errors.append("authority release or quarantine is not proven by evidence")
    if (
        ownership in {"released", "quarantined"}
        and latest_authority is not None
        and receipts
        and records.index(latest_authority)
        < max(records.index(receipt) for receipt in receipts.values())
    ):
        errors.append("authority release precedes cleanup receipts")
    if authority.get(
        "device_index_intent"
    ) == "remove_after_release_or_quarantine" and (
        cleanup.get("state") != "complete"
        or ownership not in {"released", "quarantined"}
    ):
        errors.append("active index removal is not proven by cleanup and authority")


def _oracle_string_list(
    raw: object,
    label: str,
    errors: list[str],
) -> tuple[str, ...]:
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        errors.append(f"{label} must be a string array")
        return ()
    return tuple(raw)


def _oracle_positive_int(value: object, label: str, errors: list[str]) -> None:
    if type(value) is not int or value < 1:
        errors.append(f"{label} must be positive")


def _oracle_code(value: object, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not _SAFE_CODE.fullmatch(value):
        errors.append(f"invalid execution evidence {label}")


def _oracle_reject_unsafe(value: object, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if any(token in key.lower() for token in ("secret", "password", "private")):
                errors.append("unsafe execution evidence field")
            _oracle_reject_unsafe(item, errors)
    elif isinstance(value, list):
        for item in value:
            _oracle_reject_unsafe(item, errors)
    elif isinstance(value, str) and (
        "\n" in value
        or "\r" in value
        or value.startswith(("/", "file://"))
        or "/.coreelec-reconciler/" in value
    ):
        errors.append("unsafe execution evidence content")


def _check_attempts(
    report: dict[str, object],
    evidence_kinds: dict[str, ExecutionEvidenceKind],
    errors: list[str],
) -> set[str]:
    raw = report["attempts"]
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
        "pending",
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
                "attempt",
                "attempt_id",
                "bindings",
                "ended_at",
                "intent_evidence_ref",
                "operation_code",
                "outcome",
                "outcome_evidence_ref",
                "phase",
                "resource_type",
                "started_at",
                "state_addresses",
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
        operation_code = attempt.get("operation_code")
        if not isinstance(operation_code, str) or not _SAFE_CODE.fullmatch(
            operation_code
        ):
            errors.append("attempt operation code is invalid")
        _check_subject(attempt.get("subject"), errors)
        effect_attempt = attempt.get("phase") == "effect"
        attempt_number = attempt.get("attempt")
        if type(attempt_number) is not int or attempt_number != 1:
            errors.append("attempt number must be 1")
        state_addresses = _string_array(
            attempt.get("state_addresses"),
            "attempt State Address",
            errors,
        )
        if effect_attempt and state_addresses:
            errors.append("Effect attempt cannot claim Resource State Addresses")
        if not effect_attempt and (
            not state_addresses
            or state_addresses != sorted(set(state_addresses))
            or any(not item.startswith("special://") for item in state_addresses)
        ):
            errors.append("attempt State Addresses are invalid")
        bindings = _mapping(
            attempt.get("bindings"),
            {
                "binding_digest",
                "change_id",
                "device_id",
                "plan_full_digest",
                "plan_id",
                "resource_id",
                "run_id",
                "workspace_id",
            },
            "attempt bindings",
            errors,
        )
        reference = report["plan_reference"]
        authority = report["authority"]
        recovery = report["recovery"]
        subject = attempt.get("subject")
        if (
            not isinstance(reference, dict)
            or not isinstance(authority, dict)
            or not isinstance(recovery, dict)
            or not isinstance(subject, dict)
            or not bindings
            or bindings.get("device_id") != report["device_id"]
            or bindings.get("run_id") != report["run_id"]
            or bindings.get("workspace_id") != recovery.get("workspace_id")
            or bindings.get("plan_id") != reference.get("plan_id")
            or bindings.get("plan_full_digest") != reference.get("plan_full_digest")
            or bindings.get("binding_digest") != authority.get("binding_digest")
        ):
            errors.append("attempt bindings do not match Run")
        resource_id = bindings.get("resource_id")
        change_id = bindings.get("change_id")
        if effect_attempt:
            if (
                attempt.get("resource_type") is not None
                or resource_id is not None
                or change_id is not None
                or not isinstance(subject, dict)
                or subject.get("kind") != "effect"
            ):
                errors.append("Effect attempt has Resource-only bindings")
        elif (
            attempt.get("resource_type") != "KodiSmartPlaylist"
            or not isinstance(subject, dict)
            or subject.get("kind") != "resource"
            or resource_id != subject.get("id")
            or not isinstance(change_id, str)
            or not _SAFE_CODE.fullmatch(change_id)
        ):
            errors.append("attempt bindings do not match Run and Resource")
        intent_ref = attempt.get("intent_evidence_ref")
        expected_intent = (
            ExecutionEvidenceKind.EFFECT_INTENT
            if effect_attempt
            else ExecutionEvidenceKind.RESOURCE_PRIMITIVE_INTENT
        )
        if (
            not isinstance(intent_ref, str)
            or evidence_kinds.get(intent_ref) is not expected_intent
        ):
            errors.append("attempt intent evidence reference is invalid")
        outcome = attempt.get("outcome")
        ended_value = attempt.get("ended_at")
        outcome_ref = attempt.get("outcome_evidence_ref")
        expected_outcome = (
            ExecutionEvidenceKind.EFFECT_OUTCOME
            if effect_attempt
            else ExecutionEvidenceKind.RESOURCE_PRIMITIVE_OUTCOME
        )
        if outcome == "pending":
            if ended_value is not None or outcome_ref is not None:
                errors.append("pending attempt cannot have outcome completion")
        elif (
            ended_value is None
            or not isinstance(outcome_ref, str)
            or evidence_kinds.get(outcome_ref) is not expected_outcome
        ):
            errors.append("completed attempt requires typed outcome evidence")
        try:
            began = parse_rfc3339_utc(attempt.get("started_at"), "attempt started_at")
            if ended_value is not None:
                ended = parse_rfc3339_utc(ended_value, "attempt ended_at")
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


def _check_attachments(raw: object, errors: list[str]) -> set[str]:
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
    return seen


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
    if cleanup.get("state") == "complete" and count != 0:
        errors.append("complete cleanup cannot retain leftovers")
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


def _string_array(
    value: object,
    label: str,
    errors: list[str],
) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"{label} must be a string array")
        return []
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()
