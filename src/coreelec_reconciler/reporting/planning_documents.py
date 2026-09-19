"""Canonical immutable Plan and nonmutating planning Run documents."""

import hashlib
import re

from coreelec_reconciler.config.codecs import encode_resolved_configuration
from coreelec_reconciler.domain.configuration import (
    DesiredPresence,
    ResolvedConfiguration,
    Resource,
)
from coreelec_reconciler.domain.planning import (
    CanonicalPlan,
    CanonicalRunReport,
    PlanDisposition,
    PlaylistAssessment,
    RunStatus,
    SuppliedPlanningInput,
)
from coreelec_reconciler.reporting.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLAN_BASE_FIELDS = {
    "approval_requirements",
    "blockers",
    "continuation_policy",
    "created_at",
    "device",
    "disposition",
    "effects",
    "evidence",
    "full_digest",
    "input_digests",
    "kind",
    "originating_run_id",
    "plan_id",
    "producer",
    "resources",
    "schema_version",
    "semantic_digest",
    "warnings",
}
_RUN_FIELDS = {
    "approvals",
    "current_digest",
    "device_id",
    "ended_at",
    "failures",
    "kind",
    "lifecycle_history",
    "originating_planning_run_id",
    "plan_reference",
    "previous_revision_digest",
    "producer",
    "resource_results",
    "revision",
    "run_id",
    "schema_version",
    "started_at",
    "status",
}


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _as_dict(values: tuple[tuple[str, object], ...]) -> dict[str, object]:
    return dict(values)


def _observation_value(
    inputs: SuppliedPlanningInput,
    assessment: PlaylistAssessment,
) -> dict[str, object]:
    observation = inputs.observation
    return {
        "kind": observation.kind.value,
        "normalized_state_digest": assessment.before_digest,
        "observed_at": observation.observed_at,
        "resource_id": observation.resource_id,
        "state_address": observation.state_address,
    }


def _input_digests(
    configuration: ResolvedConfiguration,
    inputs: SuppliedPlanningInput,
    assessment: PlaylistAssessment,
) -> dict[str, str]:
    authored = _sha256(encode_resolved_configuration(configuration))
    observation = _sha256(
        canonical_document_bytes(_observation_value(inputs, assessment))
    )
    values = {
        "artifact_resolution": inputs.runtime.artifact_resolution_digest,
        "authored_configuration": authored,
        "controller_capabilities": inputs.runtime.controller_capabilities_digest,
        "observation_snapshot": observation,
        "resolved_profile": authored,
    }
    values["aggregate_semantic"] = _sha256(canonical_document_bytes(values))
    return values


def _evidence(
    resource: Resource,
    inputs: SuppliedPlanningInput,
    assessment: PlaylistAssessment,
) -> dict[str, object]:
    payload = _as_dict(assessment.before_summary)
    return {
        "evidence_id": f"evidence.{resource.id.value}.before",
        "observed_at": inputs.observation.observed_at,
        "observer": {"code": "supplied-kodi-smart-playlist", "version": 1},
        "payload": payload,
        "payload_kind": "KodiSmartPlaylistObservation",
        "payload_schema_version": 1,
        "raw_attachment_digest": None,
        "state_addresses": list(resource.state_addresses),
        "subject": {"id": resource.id.value, "kind": "resource"},
    }


def _change(
    resource: Resource,
    assessment: PlaylistAssessment,
) -> dict[str, object] | None:
    if assessment.operation_code is None:
        return None
    suffix = assessment.operation_code.rsplit(".", maxsplit=1)[-1]
    evidence_id = f"evidence.{resource.id.value}.before"
    return {
        "affected_state_addresses": list(resource.state_addresses),
        "before": {
            "evidence_refs": [evidence_id],
            "normalized_state_digest": assessment.before_digest,
            "summary": _as_dict(assessment.before_summary),
        },
        "change_id": f"change.{resource.id.value}.{suffix}",
        "desired": {
            "normalized_state_digest": assessment.desired_digest,
            "summary": _as_dict(assessment.desired_summary),
        },
        "effects": list(assessment.effects),
        "impact_codes": list(assessment.impact_codes),
        "operation_code": assessment.operation_code,
        "operation_key": resource.state_addresses[0],
        "preconditions": [
            {
                "evidence_ref": evidence_id,
                "expected_digest": assessment.before_digest,
                "kind": "normalized_state_digest_matches",
            }
        ],
        "reason_codes": list(assessment.reason_codes),
        "resource_id": resource.id.value,
        "resource_type": resource.type,
        "rollback": {
            "capability": "verified_supported",
            "required_before_evidence_ref": evidence_id,
        },
    }


def build_plan_and_run(
    configuration: ResolvedConfiguration,
    resource: Resource,
    inputs: SuppliedPlanningInput,
    assessment: PlaylistAssessment,
) -> tuple[CanonicalPlan, CanonicalRunReport]:
    blockers = [
        {
            "code": code,
            "evidence_refs": [f"evidence.{resource.id.value}.before"],
            "subject": {"id": resource.id.value, "kind": "resource"},
        }
        for code in assessment.blocker_codes
    ]
    change = _change(resource, assessment)
    disposition = (
        PlanDisposition.BLOCKED
        if blockers
        else PlanDisposition.ACTIONABLE
        if change is not None
        else PlanDisposition.NOOP
    )
    requirements: list[dict[str, str]] = []
    if disposition is PlanDisposition.ACTIONABLE:
        requirements.append({"scope": "apply"})
        if "removal" in assessment.impact_codes:
            requirements.append({"scope": "impact.removal"})
    runtime = inputs.runtime
    plan_value: dict[str, object] = {
        "approval_requirements": requirements,
        "blockers": blockers,
        "continuation_policy": "continue_safe_independent",
        "created_at": runtime.created_at,
        "device": {
            "endpoint": {
                "host": runtime.endpoint_host,
                "port": runtime.endpoint_port,
            },
            "logical_id": configuration.device_id.value,
            "observed_platform_identity_fingerprint": (
                runtime.platform_identity_fingerprint
            ),
            "ssh_host_key_fingerprint": runtime.ssh_host_key_fingerprint,
        },
        "disposition": disposition.value,
        "effects": [],
        "input_digests": _input_digests(configuration, inputs, assessment),
        "kind": "CoreElecReconcilerPlan",
        "originating_run_id": runtime.planning_run_id,
        "plan_id": runtime.plan_id,
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "resources": [
            {
                "blockers": blockers,
                "changes": [] if change is None else [change],
                "desired_relation": assessment.relation.value,
                "evidence_refs": [f"evidence.{resource.id.value}.before"],
                "management": resource.management.value.replace("-", "_"),
                "resource_id": resource.id.value,
                "resource_type": resource.type,
                "state_addresses": list(resource.state_addresses),
            }
        ],
        "schema_version": 1,
        "warnings": [],
        "evidence": [_evidence(resource, inputs, assessment)],
    }
    if disposition is PlanDisposition.ACTIONABLE:
        plan_value["expires_at"] = runtime.expires_at
        plan_value["valid_from"] = runtime.created_at
    semantic_projection = {
        key: value
        for key, value in plan_value.items()
        if key
        not in {
            "plan_id",
            "created_at",
            "expires_at",
            "full_digest",
            "semantic_digest",
        }
    }
    producer = _mapping(
        semantic_projection["producer"],
        {"name", "version"},
        "producer",
    ).copy()
    producer.pop("version")
    semantic_projection["producer"] = producer
    plan_value["semantic_digest"] = _sha256(
        canonical_document_bytes(semantic_projection)
    )
    plan_value["full_digest"] = _sha256(canonical_document_bytes(plan_value))
    plan_bytes = canonical_document_bytes(plan_value)
    plan = CanonicalPlan(
        canonical_bytes=plan_bytes,
        plan_id=runtime.plan_id,
        full_digest=str(plan_value["full_digest"]),
        semantic_digest=str(plan_value["semantic_digest"]),
        disposition=disposition,
    )

    initial_run: dict[str, object] = {
        "approvals": [],
        "current_digest": "",
        "device_id": configuration.device_id.value,
        "ended_at": None,
        "failures": [],
        "kind": "CoreElecReconcilerRunReport",
        "lifecycle_history": ["planning"],
        "originating_planning_run_id": runtime.planning_run_id,
        "plan_reference": None,
        "previous_revision_digest": None,
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "resource_results": [],
        "revision": 1,
        "run_id": runtime.planning_run_id,
        "schema_version": 1,
        "started_at": runtime.started_at,
        "status": "planning",
    }
    initial_run["current_digest"] = _sha256(
        canonical_document_bytes(
            {
                key: value
                for key, value in initial_run.items()
                if key != "current_digest"
            }
        )
    )
    status = (
        RunStatus(disposition.value)
        if disposition is not PlanDisposition.ACTIONABLE
        else RunStatus.AWAITING_APPROVAL
    )
    relation = assessment.relation.value
    run_value: dict[str, object] = {
        "approvals": [],
        "current_digest": "",
        "device_id": configuration.device_id.value,
        "ended_at": (
            runtime.ended_at if status in {RunStatus.NOOP, RunStatus.BLOCKED} else None
        ),
        "failures": [],
        "kind": "CoreElecReconcilerRunReport",
        "lifecycle_history": ["planning", status.value],
        "originating_planning_run_id": runtime.planning_run_id,
        "plan_reference": {
            "originating_planning_run_id": runtime.planning_run_id,
            "plan_full_digest": plan.full_digest,
            "plan_id": plan.plan_id,
        },
        "previous_revision_digest": initial_run["current_digest"],
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "resource_results": [
            {
                "desired_disposition": (
                    "absent"
                    if resource.desired is DesiredPresence.ABSENT
                    else "present"
                ),
                "final_convergence": (
                    "converged"
                    if status is RunStatus.NOOP
                    else "blocked"
                    if status is RunStatus.BLOCKED
                    else "pending"
                ),
                "latest_observed_relation": relation,
                "mutation_outcome": (
                    "not_required"
                    if status is RunStatus.NOOP
                    else "blocked"
                    if status is RunStatus.BLOCKED
                    else "pending"
                ),
                "post_effect_verification": "not_applicable",
                "resource_id": resource.id.value,
                "rollback_outcome": "not_attempted",
                "verification_outcome": (
                    "fresh_match" if status is RunStatus.NOOP else "not_started"
                ),
            }
        ],
        "revision": 2,
        "run_id": runtime.planning_run_id,
        "schema_version": 1,
        "started_at": runtime.started_at,
        "status": status.value,
    }
    run_value["current_digest"] = _sha256(
        canonical_document_bytes(
            {key: value for key, value in run_value.items() if key != "current_digest"}
        )
    )
    run = CanonicalRunReport(
        canonical_bytes=canonical_document_bytes(run_value),
        run_id=runtime.planning_run_id,
        current_digest=str(run_value["current_digest"]),
        revision=2,
        status=status,
    )
    return plan, run


def decode_plan(content: bytes) -> CanonicalPlan:
    value = decode_json_object(content)
    fields = set(value)
    actionable_fields = _PLAN_BASE_FIELDS | {"expires_at", "valid_from"}
    if fields != _PLAN_BASE_FIELDS and fields != actionable_fields:
        raise ValueError("unknown or missing Plan fields")
    if canonical_document_bytes(value) != content:
        raise ValueError("Plan bytes are not canonical")
    if value["kind"] != "CoreElecReconcilerPlan" or value["schema_version"] != 1:
        raise ValueError("unsupported Plan")
    _validate_plan_shape(value)
    disposition = PlanDisposition(str(value["disposition"]))
    if (disposition is PlanDisposition.ACTIONABLE) != (fields == actionable_fields):
        raise ValueError("Plan validity fields do not match disposition")
    full_digest = value["full_digest"]
    semantic_digest = value["semantic_digest"]
    if not isinstance(full_digest, str) or not _DIGEST.fullmatch(full_digest):
        raise ValueError("invalid Plan full digest")
    if not isinstance(semantic_digest, str) or not _DIGEST.fullmatch(semantic_digest):
        raise ValueError("invalid Plan semantic digest")
    without_full = {key: item for key, item in value.items() if key != "full_digest"}
    if _sha256(canonical_document_bytes(without_full)) != full_digest:
        raise ValueError("Plan full digest mismatch")
    semantic = {
        key: item
        for key, item in value.items()
        if key
        not in {
            "plan_id",
            "created_at",
            "expires_at",
            "full_digest",
            "semantic_digest",
        }
    }
    producer = semantic.get("producer")
    if not isinstance(producer, dict) or set(producer) != {"name", "version"}:
        raise ValueError("invalid Plan producer")
    semantic["producer"] = {"name": producer["name"]}
    if _sha256(canonical_document_bytes(semantic)) != semantic_digest:
        raise ValueError("Plan semantic digest mismatch")
    return CanonicalPlan(
        canonical_bytes=content,
        plan_id=str(value["plan_id"]),
        full_digest=full_digest,
        semantic_digest=semantic_digest,
        disposition=disposition,
    )


def decode_run_report(content: bytes) -> CanonicalRunReport:
    value = decode_json_object(content)
    if set(value) != _RUN_FIELDS:
        raise ValueError("unknown or missing Run Report fields")
    if canonical_document_bytes(value) != content:
        raise ValueError("Run Report bytes are not canonical")
    if value["kind"] != "CoreElecReconcilerRunReport" or value["schema_version"] != 1:
        raise ValueError("unsupported Run Report")
    _validate_run_shape(value)
    digest = value["current_digest"]
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError("invalid Run Report digest")
    without_digest = {
        key: item for key, item in value.items() if key != "current_digest"
    }
    if _sha256(canonical_document_bytes(without_digest)) != digest:
        raise ValueError("Run Report digest mismatch")
    revision = value["revision"]
    if type(revision) is not int or revision < 1:
        raise ValueError("invalid Run Report revision")
    return CanonicalRunReport(
        canonical_bytes=content,
        run_id=str(value["run_id"]),
        current_digest=digest,
        revision=revision,
        status=RunStatus(str(value["status"])),
    )


def _mapping(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"unknown or missing {label} fields")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _validate_plan_shape(value: dict[str, object]) -> None:
    _mapping(value["producer"], {"name", "version"}, "producer")
    device = _mapping(
        value["device"],
        {
            "endpoint",
            "logical_id",
            "observed_platform_identity_fingerprint",
            "ssh_host_key_fingerprint",
        },
        "device",
    )
    _mapping(device["endpoint"], {"host", "port"}, "endpoint")
    _mapping(
        value["input_digests"],
        {
            "aggregate_semantic",
            "artifact_resolution",
            "authored_configuration",
            "controller_capabilities",
            "observation_snapshot",
            "resolved_profile",
        },
        "input digests",
    )
    for evidence_value in _array(value["evidence"], "evidence"):
        evidence = _mapping(
            evidence_value,
            {
                "evidence_id",
                "observed_at",
                "observer",
                "payload",
                "payload_kind",
                "payload_schema_version",
                "raw_attachment_digest",
                "state_addresses",
                "subject",
            },
            "evidence",
        )
        _mapping(evidence["observer"], {"code", "version"}, "observer")
        _mapping(evidence["subject"], {"id", "kind"}, "subject")
        if not isinstance(evidence["payload"], dict):
            raise ValueError("evidence payload must be an object")
    for blocker_value in _array(value["blockers"], "blockers"):
        blocker = _mapping(
            blocker_value,
            {"code", "evidence_refs", "subject"},
            "blocker",
        )
        _mapping(blocker["subject"], {"id", "kind"}, "blocker subject")
    for resource_value in _array(value["resources"], "resources"):
        resource = _mapping(
            resource_value,
            {
                "blockers",
                "changes",
                "desired_relation",
                "evidence_refs",
                "management",
                "resource_id",
                "resource_type",
                "state_addresses",
            },
            "Plan Resource",
        )
        for change_value in _array(resource["changes"], "changes"):
            change = _mapping(
                change_value,
                {
                    "affected_state_addresses",
                    "before",
                    "change_id",
                    "desired",
                    "effects",
                    "impact_codes",
                    "operation_code",
                    "operation_key",
                    "preconditions",
                    "reason_codes",
                    "resource_id",
                    "resource_type",
                    "rollback",
                },
                "Change",
            )
            _mapping(
                change["before"],
                {"evidence_refs", "normalized_state_digest", "summary"},
                "Change before",
            )
            _mapping(
                change["desired"],
                {"normalized_state_digest", "summary"},
                "Change desired",
            )
            _mapping(
                change["rollback"],
                {"capability", "required_before_evidence_ref"},
                "rollback",
            )
            for precondition_value in _array(
                change["preconditions"],
                "preconditions",
            ):
                _mapping(
                    precondition_value,
                    {"evidence_ref", "expected_digest", "kind"},
                    "precondition",
                )
    for requirement in _array(
        value["approval_requirements"],
        "approval requirements",
    ):
        _mapping(requirement, {"scope"}, "approval requirement")


def _validate_run_shape(value: dict[str, object]) -> None:
    _mapping(value["producer"], {"name", "version"}, "producer")
    reference = value["plan_reference"]
    if reference is not None:
        _mapping(
            reference,
            {
                "originating_planning_run_id",
                "plan_full_digest",
                "plan_id",
            },
            "Plan reference",
        )
    for result_value in _array(value["resource_results"], "resource results"):
        _mapping(
            result_value,
            {
                "desired_disposition",
                "final_convergence",
                "latest_observed_relation",
                "mutation_outcome",
                "post_effect_verification",
                "resource_id",
                "rollback_outcome",
                "verification_outcome",
            },
            "Resource result",
        )
