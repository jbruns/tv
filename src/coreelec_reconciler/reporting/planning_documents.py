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
_RELATIONS = {"satisfied", "divergent", "not_applicable", "unverifiable"}
_MANAGEMENT_MODES = {"enforce", "observe_only"}
_OPERATIONS = {
    "smart_playlist.create",
    "smart_playlist.remove",
    "smart_playlist.update",
}
_REASONS = {
    "managed-file.mode-drift",
    "playlist.absent",
    "playlist.desired-absent",
    "playlist.malformed-current",
    "playlist.semantic-drift",
}
_IMPACTS = {"content_mutation", "removal"}
_BLOCKERS = {
    "resource.observe-only-divergence",
    "resource.unsafe-directory",
    "resource.unsafe-other",
    "resource.unsafe-symlink",
    "resource.unreadable",
}
_UPDATE_REASON_COMBINATIONS = {
    ("managed-file.mode-drift",),
    ("playlist.malformed-current",),
    ("playlist.malformed-current", "managed-file.mode-drift"),
    ("playlist.semantic-drift",),
    ("playlist.semantic-drift", "managed-file.mode-drift"),
}
_STATE_ADDRESS = "special://profile/playlists/video/NewShows.xsp"
_RESOURCE_ID = "skin.playlist.new-shows"
_RESOURCE_TYPE = "KodiSmartPlaylist"
_PRODUCER = {"name": "coreelec-reconciler", "version": "0.1.0"}


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
    if (
        value["kind"] != "CoreElecReconcilerPlan"
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("unsupported Plan")
    try:
        disposition = PlanDisposition(_string(value["disposition"], "disposition"))
    except (TypeError, ValueError) as error:
        raise ValueError("unknown Plan disposition") from error
    try:
        _validate_plan_shape(value, disposition)
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError("malformed Plan") from error
    if (disposition is PlanDisposition.ACTIONABLE) != (fields == actionable_fields):
        raise ValueError("Plan validity fields do not match disposition")
    full_digest = value["full_digest"]
    semantic_digest = value["semantic_digest"]
    full_digest = require_sha256(full_digest, "Plan full_digest")
    semantic_digest = require_sha256(semantic_digest, "Plan semantic_digest")
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
    producer = _mapping(
        semantic["producer"],
        {"name", "version"},
        "Plan producer",
    )
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


def decode_run_report(
    content: bytes,
    plan: CanonicalPlan | None = None,
) -> CanonicalRunReport:
    value = decode_json_object(content)
    if set(value) != _RUN_FIELDS:
        raise ValueError("unknown or missing Run Report fields")
    if canonical_document_bytes(value) != content:
        raise ValueError("Run Report bytes are not canonical")
    if (
        value["kind"] != "CoreElecReconcilerRunReport"
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("unsupported Run Report")
    try:
        status = RunStatus(_string(value["status"], "status"))
    except (TypeError, ValueError) as error:
        raise ValueError("unknown Run Report status") from error
    try:
        _validate_run_shape(value, status, plan)
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError("malformed Run Report") from error
    digest = value["current_digest"]
    digest = require_sha256(digest, "Run Report current_digest")
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
        status=status,
    )


def _mapping(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"unknown or missing {label} fields")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _string_array(value: object, label: str) -> list[str]:
    return [_string(item, label) for item in _array(value, label)]


def _validate_nested_digests(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("digest") and item is not None:
                require_sha256(item, key)
            _validate_nested_digests(item)
    elif isinstance(value, list):
        for item in value:
            _validate_nested_digests(item)


def _validate_plan_shape(
    value: dict[str, object],
    disposition: PlanDisposition,
) -> None:
    _validate_nested_digests(value)
    if _mapping(value["producer"], {"name", "version"}, "producer") != _PRODUCER:
        raise ValueError("unsupported Plan producer")
    if value["continuation_policy"] != "continue_safe_independent":
        raise ValueError("unknown continuation policy")
    if _array(value["warnings"], "warnings"):
        raise ValueError("warnings are not supported by this slice")
    plan_id = require_uuid7(value["plan_id"], "plan_id")
    originating_run_id = require_uuid7(
        value["originating_run_id"],
        "originating_run_id",
    )
    if plan_id == originating_run_id:
        raise ValueError("Plan and originating Run IDs must differ")
    created_at = parse_rfc3339_utc(value["created_at"], "created_at")
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
    require_logical_id(device["logical_id"], "Device logical ID")
    require_sha256(
        device["observed_platform_identity_fingerprint"],
        "platform identity fingerprint",
    )
    host_key = _string(device["ssh_host_key_fingerprint"], "host-key fingerprint")
    if not host_key.startswith("SHA256:") or len(host_key) <= len("SHA256:"):
        raise ValueError("invalid SSH host-key fingerprint")
    endpoint = _mapping(device["endpoint"], {"host", "port"}, "endpoint")
    if not _string(endpoint["host"], "endpoint host"):
        raise ValueError("endpoint host must not be empty")
    if type(endpoint["port"]) is not int or not 1 <= endpoint["port"] <= 65535:
        raise ValueError("endpoint port is invalid")
    input_digests = _mapping(
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
    for name, digest in input_digests.items():
        require_sha256(digest, f"input digest {name}")
    aggregate_inputs = {
        key: item for key, item in input_digests.items() if key != "aggregate_semantic"
    }
    if (
        _sha256(canonical_document_bytes(aggregate_inputs))
        != input_digests["aggregate_semantic"]
    ):
        raise ValueError("aggregate semantic input digest mismatch")
    evidence_values = _array(value["evidence"], "evidence")
    resource_values = _array(value["resources"], "resources")
    if len(evidence_values) != 1 or len(resource_values) != 1:
        raise ValueError("this Plan requires exactly one Resource and evidence")
    evidence_ids: set[str] = set()
    for evidence_value in evidence_values:
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
        if _mapping(evidence["observer"], {"code", "version"}, "observer") != {
            "code": "supplied-kodi-smart-playlist",
            "version": 1,
        }:
            raise ValueError("unsupported evidence observer")
        subject = _mapping(evidence["subject"], {"id", "kind"}, "subject")
        if subject != {"id": _RESOURCE_ID, "kind": "resource"}:
            raise ValueError("invalid evidence subject")
        if not isinstance(evidence["payload"], dict):
            raise ValueError("evidence payload must be an object")
        if (
            evidence["payload_kind"] != "KodiSmartPlaylistObservation"
            or evidence["payload_schema_version"] != 1
        ):
            raise ValueError("unsupported evidence payload")
        attachment = evidence["raw_attachment_digest"]
        if attachment is not None:
            require_sha256(attachment, "raw attachment digest")
        if evidence["state_addresses"] != [_STATE_ADDRESS]:
            raise ValueError("invalid evidence State Address")
        if parse_rfc3339_utc(evidence["observed_at"], "observed_at") > created_at:
            raise ValueError("evidence cannot be observed after Plan creation")
        evidence_id = _string(evidence["evidence_id"], "evidence ID")
        if evidence_id != f"evidence.{_RESOURCE_ID}.before":
            raise ValueError("invalid evidence ID")
        if evidence_id in evidence_ids:
            raise ValueError("duplicate evidence ID")
        evidence_ids.add(evidence_id)
    blocker_codes: list[str] = []
    for blocker_value in _array(value["blockers"], "blockers"):
        blocker = _mapping(
            blocker_value,
            {"code", "evidence_refs", "subject"},
            "blocker",
        )
        if _mapping(
            blocker["subject"],
            {"id", "kind"},
            "blocker subject",
        ) != {"id": _RESOURCE_ID, "kind": "resource"}:
            raise ValueError("invalid blocker subject")
        code = _string(blocker["code"], "blocker code")
        if code not in _BLOCKERS:
            raise ValueError("unknown blocker code")
        blocker_codes.append(code)
        if _string_array(blocker["evidence_refs"], "evidence reference") != [
            f"evidence.{_RESOURCE_ID}.before"
        ]:
            raise ValueError("unresolved blocker evidence reference")
    if len(set(blocker_codes)) != len(blocker_codes):
        raise ValueError("duplicate blocker code")
    change_ids: set[str] = set()
    for resource_value in resource_values:
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
        if (
            resource["resource_id"] != _RESOURCE_ID
            or resource["resource_type"] != _RESOURCE_TYPE
            or resource["state_addresses"] != [_STATE_ADDRESS]
        ):
            raise ValueError("invalid Plan Resource identity")
        if _string(resource["management"], "management") not in _MANAGEMENT_MODES:
            raise ValueError("unknown management mode")
        if _string(resource["desired_relation"], "desired relation") not in _RELATIONS:
            raise ValueError("unknown desired relation")
        if _string_array(resource["evidence_refs"], "evidence reference") != [
            f"evidence.{_RESOURCE_ID}.before"
        ]:
            raise ValueError("unresolved Resource evidence reference")
        if resource["blockers"] != value["blockers"]:
            raise ValueError("Resource blockers do not match Plan blockers")
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
            change_id = _string(change["change_id"], "Change ID")
            if change_id in change_ids:
                raise ValueError("duplicate Change ID")
            change_ids.add(change_id)
            operation = _string(change["operation_code"], "operation code")
            expected_change_id = (
                f"change.{_RESOURCE_ID}.{operation.rsplit('.', maxsplit=1)[-1]}"
            )
            if (
                change_id != expected_change_id
                or change["resource_id"] != _RESOURCE_ID
                or change["resource_type"] != _RESOURCE_TYPE
                or change["operation_key"] != _STATE_ADDRESS
                or change["affected_state_addresses"] != [_STATE_ADDRESS]
            ):
                raise ValueError("invalid Change identity or State Address")
            before = _mapping(
                change["before"],
                {"evidence_refs", "normalized_state_digest", "summary"},
                "Change before",
            )
            if _string_array(before["evidence_refs"], "evidence reference") != [
                f"evidence.{_RESOURCE_ID}.before"
            ]:
                raise ValueError("unresolved Change evidence reference")
            desired = _mapping(
                change["desired"],
                {"normalized_state_digest", "summary"},
                "Change desired",
            )
            before_digest = require_sha256(
                before["normalized_state_digest"],
                "before normalized state digest",
            )
            require_sha256(
                desired["normalized_state_digest"],
                "desired normalized state digest",
            )
            rollback = _mapping(
                change["rollback"],
                {"capability", "required_before_evidence_ref"},
                "rollback",
            )
            if rollback["capability"] != "verified_supported":
                raise ValueError("unknown rollback capability")
            if rollback["required_before_evidence_ref"] not in evidence_ids:
                raise ValueError("unresolved rollback evidence reference")
            if operation not in _OPERATIONS:
                raise ValueError("unknown operation code")
            if (
                not set(_string_array(change["reason_codes"], "reason code"))
                <= _REASONS
            ):
                raise ValueError("unknown reason code")
            if (
                not set(_string_array(change["impact_codes"], "impact code"))
                <= _IMPACTS
            ):
                raise ValueError("unknown impact code")
            if _array(change["effects"], "Change effects"):
                raise ValueError("KodiSmartPlaylist Change cannot declare Effects")
            for precondition_value in _array(
                change["preconditions"],
                "preconditions",
            ):
                precondition = _mapping(
                    precondition_value,
                    {"evidence_ref", "expected_digest", "kind"},
                    "precondition",
                )
                if precondition["kind"] != "normalized_state_digest_matches":
                    raise ValueError("unknown precondition kind")
                if precondition["evidence_ref"] not in evidence_ids:
                    raise ValueError("unresolved precondition evidence reference")
                if precondition["expected_digest"] != before_digest:
                    raise ValueError("precondition digest does not match before state")
            if len(_array(change["preconditions"], "preconditions")) != 1:
                raise ValueError("Change requires exactly one precondition")
            _validate_change_combination(change, operation)
    for requirement in _array(
        value["approval_requirements"],
        "approval requirements",
    ):
        requirement_value = _mapping(
            requirement,
            {"scope"},
            "approval requirement",
        )
        if requirement_value["scope"] not in {"apply", "impact.removal"}:
            raise ValueError("unknown approval scope")
    if _array(value["effects"], "Plan effects"):
        raise ValueError("KodiSmartPlaylist Plan cannot declare Effects")
    if bool(blocker_codes) != (value["disposition"] == "blocked"):
        raise ValueError("Plan blockers do not match disposition")
    changes = _array(resource["changes"], "changes")
    requirements = [
        _mapping(item, {"scope"}, "approval requirement")["scope"]
        for item in _array(value["approval_requirements"], "approval requirements")
    ]
    if disposition is PlanDisposition.ACTIONABLE:
        valid_from = parse_rfc3339_utc(value["valid_from"], "valid_from")
        expires_at = parse_rfc3339_utc(value["expires_at"], "expires_at")
        if valid_from != created_at or expires_at <= valid_from:
            raise ValueError("invalid actionable Plan validity window")
        if len(changes) != 1 or blocker_codes:
            raise ValueError("actionable Plan requires one unblocked Change")
        expected_requirements = ["apply"]
        planned_change = _mapping(
            changes[0],
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
        if "removal" in _string_array(
            planned_change["impact_codes"],
            "impact code",
        ):
            expected_requirements.append("impact.removal")
        if requirements != expected_requirements:
            raise ValueError("approval requirements do not match impacts")
        if resource["desired_relation"] != "divergent":
            raise ValueError("actionable Resource must be divergent")
        if resource["management"] != "enforce":
            raise ValueError("actionable Resource must be enforcing")
    elif requirements or changes:
        raise ValueError("non-actionable Plan cannot require approval or Changes")
    elif disposition is PlanDisposition.NOOP:
        if blocker_codes or resource["desired_relation"] != "satisfied":
            raise ValueError("no-op Plan must contain one satisfied Resource")
    elif not blocker_codes or resource["desired_relation"] not in {
        "divergent",
        "unverifiable",
    }:
        raise ValueError("blocked Plan must contain a blocked Resource")
    elif resource["desired_relation"] == "divergent" and (
        blocker_codes != ["resource.observe-only-divergence"]
        or resource["management"] != "observe_only"
    ):
        raise ValueError("divergent blocked Resource must be observe-only")
    elif resource["desired_relation"] == "unverifiable" and (
        len(blocker_codes) != 1
        or blocker_codes[0] == "resource.observe-only-divergence"
    ):
        raise ValueError("unverifiable Resource requires one read-safety blocker")


def _validate_change_combination(
    change: dict[str, object],
    operation: str,
) -> None:
    reasons = _string_array(change["reason_codes"], "reason code")
    impacts = _string_array(change["impact_codes"], "impact code")
    if len(set(reasons)) != len(reasons) or len(set(impacts)) != len(impacts):
        raise ValueError("Change codes must be unique")
    before = _mapping(
        change["before"],
        {"evidence_refs", "normalized_state_digest", "summary"},
        "Change before",
    )
    desired = _mapping(
        change["desired"],
        {"normalized_state_digest", "summary"},
        "Change desired",
    )
    if before["normalized_state_digest"] == desired["normalized_state_digest"]:
        raise ValueError("Change before and desired digests must differ")
    if not isinstance(before["summary"], dict) or not before["summary"]:
        raise ValueError("Change before summary must not be empty")
    if not isinstance(desired["summary"], dict) or not desired["summary"]:
        raise ValueError("Change desired summary must not be empty")
    if operation == "smart_playlist.create":
        if reasons != ["playlist.absent"] or impacts != ["content_mutation"]:
            raise ValueError("create Change codes are contradictory")
    elif operation == "smart_playlist.remove":
        if reasons != ["playlist.desired-absent"] or impacts != [
            "content_mutation",
            "removal",
        ]:
            raise ValueError("remove Change codes are contradictory")
    elif tuple(reasons) not in _UPDATE_REASON_COMBINATIONS or impacts != [
        "content_mutation"
    ]:
        raise ValueError("update Change codes are contradictory")


def _validate_run_shape(
    value: dict[str, object],
    status: RunStatus,
    plan: CanonicalPlan | None,
) -> None:
    _validate_nested_digests(value)
    if _mapping(value["producer"], {"name", "version"}, "producer") != _PRODUCER:
        raise ValueError("unsupported Run Report producer")
    run_id = require_uuid7(value["run_id"], "run_id")
    originating_run_id = require_uuid7(
        value["originating_planning_run_id"],
        "originating_planning_run_id",
    )
    if run_id != originating_run_id:
        raise ValueError("planning Run ID must equal originating planning Run ID")
    require_logical_id(value["device_id"], "Run Device ID")
    started_at = parse_rfc3339_utc(value["started_at"], "started_at")
    revision = value["revision"]
    if type(revision) is not int or revision not in {1, 2}:
        raise ValueError("unsupported Run Report revision")
    lifecycle = _string_array(value["lifecycle_history"], "lifecycle status")
    if _array(value["approvals"], "approvals") or _array(
        value["failures"],
        "failures",
    ):
        raise ValueError("planning Run cannot contain approvals or failures")
    reference = value["plan_reference"]
    if revision == 1:
        if (
            status is not RunStatus.PLANNING
            or lifecycle != ["planning"]
            or value["previous_revision_digest"] is not None
            or reference is not None
            or value["ended_at"] is not None
            or _array(value["resource_results"], "resource results")
        ):
            raise ValueError("invalid initial planning Run revision")
        return
    if status not in {
        RunStatus.NOOP,
        RunStatus.BLOCKED,
        RunStatus.AWAITING_APPROVAL,
    }:
        raise ValueError("invalid planning Run terminal/planning status")
    if lifecycle != ["planning", status.value]:
        raise ValueError("Run lifecycle does not match status")
    reference_value = _mapping(
        reference,
        {
            "originating_planning_run_id",
            "plan_full_digest",
            "plan_id",
        },
        "Plan reference",
    )
    if reference_value["originating_planning_run_id"] != originating_run_id:
        raise ValueError("Plan reference has a different originating Run")
    referenced_plan_id = require_uuid7(reference_value["plan_id"], "referenced plan_id")
    referenced_digest = require_sha256(
        reference_value["plan_full_digest"],
        "referenced Plan full digest",
    )
    previous_digest = require_sha256(
        value["previous_revision_digest"],
        "previous_revision_digest",
    )
    initial_run = {
        "approvals": [],
        "current_digest": "",
        "device_id": value["device_id"],
        "ended_at": None,
        "failures": [],
        "kind": "CoreElecReconcilerRunReport",
        "lifecycle_history": ["planning"],
        "originating_planning_run_id": originating_run_id,
        "plan_reference": None,
        "previous_revision_digest": None,
        "producer": _PRODUCER,
        "resource_results": [],
        "revision": 1,
        "run_id": run_id,
        "schema_version": 1,
        "started_at": value["started_at"],
        "status": "planning",
    }
    expected_previous = _sha256(
        canonical_document_bytes(
            {key: item for key, item in initial_run.items() if key != "current_digest"}
        )
    )
    if previous_digest != expected_previous:
        raise ValueError("Run previous revision digest mismatch")
    results = _array(value["resource_results"], "resource results")
    if len(results) != 1:
        raise ValueError("planning Run requires exactly one Resource result")
    for result_value in _array(value["resource_results"], "resource results"):
        result = _mapping(
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
        if result["resource_id"] != _RESOURCE_ID:
            raise ValueError("invalid Run Resource ID")
        if result["desired_disposition"] not in {"present", "absent"}:
            raise ValueError("unknown desired disposition")
        if result["latest_observed_relation"] not in _RELATIONS:
            raise ValueError("unknown observed relation")
        if result["mutation_outcome"] not in {
            "not_required",
            "blocked",
            "pending",
        }:
            raise ValueError("unknown mutation outcome")
        if result["verification_outcome"] not in {
            "fresh_match",
            "not_started",
        }:
            raise ValueError("unknown verification outcome")
        if result["rollback_outcome"] != "not_attempted":
            raise ValueError("unknown rollback outcome")
        if result["post_effect_verification"] != "not_applicable":
            raise ValueError("unknown post-Effect Verification outcome")
        if result["final_convergence"] not in {"converged", "blocked", "pending"}:
            raise ValueError("unknown final convergence")
        expected = {
            RunStatus.NOOP: (
                "satisfied",
                "not_required",
                "fresh_match",
                "converged",
            ),
            RunStatus.BLOCKED: (
                result["latest_observed_relation"],
                "blocked",
                "not_started",
                "blocked",
            ),
            RunStatus.AWAITING_APPROVAL: (
                "divergent",
                "pending",
                "not_started",
                "pending",
            ),
        }[status]
        actual = (
            result["latest_observed_relation"],
            result["mutation_outcome"],
            result["verification_outcome"],
            result["final_convergence"],
        )
        if actual != expected:
            raise ValueError("Run Resource result contradicts status")
        if status is RunStatus.BLOCKED and result["latest_observed_relation"] not in {
            "divergent",
            "unverifiable",
        }:
            raise ValueError("blocked Run requires divergent or unverifiable state")
    ended = value["ended_at"]
    if status in {RunStatus.NOOP, RunStatus.BLOCKED}:
        ended_at = parse_rfc3339_utc(ended, "ended_at")
        if ended_at < started_at:
            raise ValueError("Run cannot end before it starts")
    elif ended is not None:
        raise ValueError("nonterminal planning Run cannot have ended_at")
    if plan is not None:
        validated_plan = decode_plan(plan.canonical_bytes)
        if validated_plan != plan:
            raise ValueError("supplied Plan value does not match canonical bytes")
        plan_value = decode_json_object(plan.canonical_bytes)
        if (
            referenced_plan_id != plan.plan_id
            or referenced_digest != plan.full_digest
            or reference_value["originating_planning_run_id"]
            != plan_value["originating_run_id"]
            or value["device_id"] != plan_value["device"]["logical_id"]  # type: ignore[index]
            or status.value
            != {
                "actionable": "awaiting_approval",
                "blocked": "blocked",
                "noop": "noop",
            }[plan.disposition.value]
        ):
            raise ValueError("Run Plan reference is inconsistent")
        created_at = parse_rfc3339_utc(plan_value["created_at"], "created_at")
        if started_at > created_at:
            raise ValueError("Run cannot start after Plan creation")
        if ended is not None and parse_rfc3339_utc(ended, "ended_at") < created_at:
            raise ValueError("Run cannot end before Plan creation")
