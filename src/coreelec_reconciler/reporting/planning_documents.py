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
    PlanDependencyGraph,
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
from coreelec_reconciler.resource_types.builtins import built_in_resource_registry
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning_codecs import (
    ASSESSMENT_BLOCKER_CODES,
    PLAYLIST_RESOURCE_ID,
    PLAYLIST_STATE_ADDRESS,
    validate_change_codes,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry

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
_STATE_ADDRESS = PLAYLIST_STATE_ADDRESS
_RESOURCE_ID = PLAYLIST_RESOURCE_ID
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


def _multi_input_digests(
    configuration: ResolvedConfiguration,
    entries: tuple[
        tuple[Resource, SuppliedPlanningInput, PlaylistAssessment],
        ...,
    ],
) -> dict[str, str]:
    if len(entries) == 1:
        _, inputs, assessment = entries[0]
        return _input_digests(configuration, inputs, assessment)
    authored = _sha256(encode_resolved_configuration(configuration))
    observations = [
        _observation_value(inputs, assessment) for _, inputs, assessment in entries
    ]
    runtime = entries[0][1].runtime
    values = {
        "artifact_resolution": runtime.artifact_resolution_digest,
        "authored_configuration": authored,
        "controller_capabilities": runtime.controller_capabilities_digest,
        "observation_snapshot": _sha256(
            canonical_document_bytes({"observations": observations})
        ),
        "resolved_profile": authored,
    }
    values["aggregate_semantic"] = _sha256(canonical_document_bytes(values))
    return values


def _stable_topological_order(
    requires_by_resource: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    resource_ids = set(requires_by_resource)
    for resource_id, requirements in requires_by_resource.items():
        if resource_id in requirements:
            raise ValueError("Plan Resource cannot depend on itself")
        if len(set(requirements)) != len(requirements):
            raise ValueError("duplicate Plan dependency")
        if not set(requirements) <= resource_ids:
            raise ValueError("dangling Plan dependency")
    remaining: dict[str, set[str]] = {
        key: set(value) for key, value in requires_by_resource.items()
    }
    ordered: list[str] = []
    while remaining:
        ready = sorted(
            resource_id
            for resource_id, requirements in remaining.items()
            if not requirements
        )
        if not ready:
            raise ValueError("cyclic Plan dependencies")
        for resource_id in ready:
            ordered.append(resource_id)
            remaining.pop(resource_id)
        for pending_requirements in remaining.values():
            pending_requirements.difference_update(ready)
    return tuple(ordered)


def _evidence(
    resource: Resource,
    inputs: SuppliedPlanningInput,
    assessment: PlaylistAssessment,
    *,
    plan_schema_version: int,
) -> dict[str, object]:
    summary = _as_dict(assessment.before_summary)
    payload: dict[str, object] = summary
    payload_schema_version = 1
    if plan_schema_version == 2:
        payload = {
            "normalized_state_digest": assessment.before_digest,
            "summary": summary,
        }
        payload_schema_version = 2
    return {
        "evidence_id": f"evidence.{resource.id.value}.before",
        "observed_at": inputs.observation.observed_at,
        "observer": {"code": "supplied-kodi-smart-playlist", "version": 1},
        "payload": payload,
        "payload_kind": "KodiSmartPlaylistObservation",
        "payload_schema_version": payload_schema_version,
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
    return build_multi_resource_plan_and_run(
        configuration,
        ((resource, inputs, assessment),),
    )


def build_multi_resource_plan_and_run(
    configuration: ResolvedConfiguration,
    entries: tuple[
        tuple[Resource, SuppliedPlanningInput, PlaylistAssessment],
        ...,
    ],
) -> tuple[CanonicalPlan, CanonicalRunReport]:
    if not entries:
        raise ValueError("Plan requires at least one Resource")
    runtime = entries[0][1].runtime
    if any(entry[1].runtime != runtime for entry in entries[1:]):
        raise ValueError("all Plan Resources must share one planning runtime")
    resources_by_id = {resource.id.value: resource for resource, _, _ in entries}
    if len(resources_by_id) != len(entries):
        raise ValueError("duplicate Plan Resource ID")
    if set(resources_by_id) != {
        resource.id.value for resource in configuration.resources
    }:
        raise ValueError("Plan Resources must match the resolved selection")
    ordered_ids = _stable_topological_order(
        {
            resource.id.value: tuple(item.value for item in resource.requires)
            for resource, _, _ in entries
        }
    )
    entries_by_id = {
        resource.id.value: (resource, inputs, assessment)
        for resource, inputs, assessment in entries
    }
    ordered_entries = tuple(entries_by_id[resource_id] for resource_id in ordered_ids)
    blockers_by_resource = {
        resource.id.value: [
            {
                "code": code,
                "evidence_refs": [f"evidence.{resource.id.value}.before"],
                "subject": {"id": resource.id.value, "kind": "resource"},
            }
            for code in assessment.blocker_codes
        ]
        for resource, _, assessment in ordered_entries
    }
    blockers = [
        blocker
        for resource_id in ordered_ids
        for blocker in blockers_by_resource[resource_id]
    ]
    changes = {
        resource.id.value: _change(resource, assessment)
        for resource, _, assessment in ordered_entries
    }
    has_changes = any(change is not None for change in changes.values())
    disposition = (
        PlanDisposition.BLOCKED
        if blockers
        else PlanDisposition.ACTIONABLE
        if has_changes
        else PlanDisposition.NOOP
    )
    requirements: list[dict[str, str]] = []
    if disposition is PlanDisposition.ACTIONABLE:
        requirements.append({"scope": "apply"})
        if any(
            "removal" in assessment.impact_codes for _, _, assessment in ordered_entries
        ):
            requirements.append({"scope": "impact.removal"})
    schema_version = 1 if len(entries) == 1 and not entries[0][0].requires else 2
    resource_values: list[dict[str, object]] = []
    for resource, _, assessment in ordered_entries:
        resource_value: dict[str, object] = {
            "blockers": blockers_by_resource[resource.id.value],
            "changes": (
                []
                if changes[resource.id.value] is None
                else [changes[resource.id.value]]
            ),
            "desired_relation": assessment.relation.value,
            "evidence_refs": [f"evidence.{resource.id.value}.before"],
            "management": resource.management.value.replace("-", "_"),
            "resource_id": resource.id.value,
            "resource_type": resource.type,
            "state_addresses": list(resource.state_addresses),
        }
        if schema_version == 2:
            resource_value["requires"] = sorted(
                required.value for required in resource.requires
            )
        resource_values.append(resource_value)
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
        "input_digests": _multi_input_digests(configuration, ordered_entries),
        "kind": "CoreElecReconcilerPlan",
        "originating_run_id": runtime.planning_run_id,
        "plan_id": runtime.plan_id,
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "resources": resource_values,
        "schema_version": schema_version,
        "warnings": [],
        "evidence": [
            _evidence(
                resource,
                inputs,
                assessment,
                plan_schema_version=schema_version,
            )
            for resource, inputs, assessment in ordered_entries
        ],
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
    plan = decode_plan(plan_bytes)

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
                    or (
                        status is RunStatus.BLOCKED
                        and not assessment.blocker_codes
                        and assessment.operation_code is None
                    )
                    else "blocked"
                    if status is RunStatus.BLOCKED
                    else "pending"
                ),
                "latest_observed_relation": assessment.relation.value,
                "mutation_outcome": (
                    "not_required"
                    if status is RunStatus.NOOP
                    or (
                        status is RunStatus.BLOCKED
                        and not assessment.blocker_codes
                        and assessment.operation_code is None
                    )
                    else "blocked"
                    if status is RunStatus.BLOCKED
                    else "pending"
                ),
                "post_effect_verification": "not_applicable",
                "resource_id": resource.id.value,
                "rollback_outcome": "not_attempted",
                "verification_outcome": (
                    "fresh_match"
                    if status is RunStatus.NOOP
                    or (
                        status is RunStatus.BLOCKED
                        and not assessment.blocker_codes
                        and assessment.operation_code is None
                    )
                    else "not_started"
                ),
            }
            for resource, _, assessment in ordered_entries
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


def decode_plan(
    content: bytes,
    *,
    resource_registry: ResourceRegistry | None = None,
) -> CanonicalPlan:
    value = decode_json_object(content)
    fields = set(value)
    actionable_fields = _PLAN_BASE_FIELDS | {"expires_at", "valid_from"}
    if fields != _PLAN_BASE_FIELDS and fields != actionable_fields:
        raise ValueError("unknown or missing Plan fields")
    if canonical_document_bytes(value) != content:
        raise ValueError("Plan bytes are not canonical")
    schema_version = value["schema_version"]
    if (
        value["kind"] != "CoreElecReconcilerPlan"
        or type(schema_version) is not int
        or schema_version not in {1, 2}
    ):
        raise ValueError("unsupported Plan")
    try:
        disposition = PlanDisposition(_string(value["disposition"], "disposition"))
    except (TypeError, ValueError) as error:
        raise ValueError("unknown Plan disposition") from error
    try:
        _validate_plan_shape(
            value,
            disposition,
            schema_version=schema_version,
            resource_registry=resource_registry or built_in_resource_registry(),
        )
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
    invariant_errors = check_plan_invariants(
        content,
        resource_registry=resource_registry,
    )
    if invariant_errors:
        raise ValueError(invariant_errors[0])
    resources = _array(value["resources"], "resources")
    return CanonicalPlan(
        canonical_bytes=content,
        plan_id=str(value["plan_id"]),
        full_digest=full_digest,
        semantic_digest=semantic_digest,
        disposition=disposition,
        resource_dependencies=(
            tuple(
                (
                    str(
                        _mapping(
                            item,
                            _plan_resource_fields(schema_version),
                            "Resource",
                        )["resource_id"]
                    ),
                    tuple(
                        _string_array(
                            _mapping(
                                item,
                                _plan_resource_fields(schema_version),
                                "Resource",
                            )["requires"],
                            "dependency",
                        )
                    ),
                )
                for item in resources
            )
            if schema_version == 2
            else ()
        ),
    )


def check_plan_invariants(
    content: bytes,
    *,
    resource_registry: ResourceRegistry | None = None,
) -> tuple[str, ...]:
    """Independently check canonical Plan graph, references, and digests."""
    errors: list[str] = []
    registry = resource_registry or built_in_resource_registry()
    try:
        value = decode_json_object(content)
    except ValueError as error:
        return (str(error),)
    if canonical_document_bytes(value) != content:
        errors.append("oracle: Plan bytes are not canonical")
    fields = set(value)
    if fields not in (
        _PLAN_BASE_FIELDS,
        _PLAN_BASE_FIELDS | {"expires_at", "valid_from"},
    ):
        errors.append("oracle: unknown or missing Plan fields")
    schema_version = value.get("schema_version")
    if type(schema_version) is not int or schema_version not in {1, 2}:
        return (*errors, "oracle: unsupported Plan schema version")
    if value.get("kind") != "CoreElecReconcilerPlan":
        errors.append("oracle: unsupported Plan kind")
    if value.get("producer") != _PRODUCER:
        errors.append("oracle: unsupported Plan producer")
    full_digest = value.get("full_digest")
    semantic_digest = value.get("semantic_digest")
    if isinstance(full_digest, str):
        without_full = {
            key: item for key, item in value.items() if key != "full_digest"
        }
        if _sha256(canonical_document_bytes(without_full)) != full_digest:
            errors.append("oracle: Plan full digest mismatch")
    else:
        errors.append("oracle: invalid Plan full digest")
    if isinstance(semantic_digest, str):
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
        if isinstance(producer, dict):
            semantic["producer"] = {"name": producer.get("name")}
        if _sha256(canonical_document_bytes(semantic)) != semantic_digest:
            errors.append("oracle: Plan semantic digest mismatch")
    else:
        errors.append("oracle: invalid Plan semantic digest")
    raw_resources = value.get("resources")
    raw_evidence = value.get("evidence")
    if not isinstance(raw_resources, list) or not raw_resources:
        return (*errors, "oracle: Plan requires Resources")
    if not isinstance(raw_evidence, list):
        return (*errors, "oracle: Plan evidence must be an array")
    expected_resource_fields = _plan_resource_fields(schema_version)
    resources: list[dict[str, object]] = []
    for raw in raw_resources:
        if not isinstance(raw, dict) or set(raw) != expected_resource_fields:
            errors.append("oracle: unknown or missing Plan Resource fields")
            continue
        resources.append(raw)
    if len(resources) != len(raw_resources):
        return tuple(errors)
    resource_ids = [item.get("resource_id") for item in resources]
    if any(not isinstance(item, str) for item in resource_ids):
        errors.append("oracle: invalid Resource ID")
        return tuple(errors)
    typed_ids = [str(item) for item in resource_ids]
    if len(set(typed_ids)) != len(typed_ids):
        errors.append("oracle: duplicate Resource ID")
    for resource in resources:
        resource_type = resource.get("resource_type")
        if (
            not isinstance(resource_type, str)
            or registry.descriptor(resource_type) is None
        ):
            errors.append("oracle: unregistered Resource Type")
        addresses = resource.get("state_addresses")
        if (
            not isinstance(addresses, list)
            or not addresses
            or any(not isinstance(item, str) for item in addresses)
            or addresses != sorted(set(addresses))
        ):
            errors.append("oracle: invalid Resource State Addresses")
    if schema_version == 1:
        if len(resources) != 1 or len(raw_evidence) != 1:
            errors.append("oracle: v1 Plan requires one Resource and evidence")
    else:
        requires_by_id: dict[str, set[str]] = {}
        for resource_id, resource in zip(typed_ids, resources, strict=True):
            requires = resource.get("requires")
            if (
                not isinstance(requires, list)
                or any(not isinstance(item, str) for item in requires)
                or requires != sorted(requires)
                or len(set(requires)) != len(requires)
            ):
                errors.append("oracle: invalid dependency list")
                continue
            typed_requires = {str(item) for item in requires}
            if resource_id in typed_requires:
                errors.append("oracle: self dependency")
            if not typed_requires <= set(typed_ids):
                errors.append("oracle: dangling dependency")
            requires_by_id[resource_id] = typed_requires
        remaining = {key: set(items) for key, items in requires_by_id.items()}
        oracle_order: list[str] = []
        while remaining:
            ready = sorted(key for key, items in remaining.items() if not items)
            if not ready:
                errors.append("oracle: cyclic dependency graph")
                break
            oracle_order.extend(ready)
            for key in ready:
                remaining.pop(key)
            for items in remaining.values():
                items.difference_update(ready)
        if oracle_order != typed_ids:
            errors.append("oracle: unstable topological Resource order")
        if len(raw_evidence) != len(resources):
            errors.append("oracle: evidence count does not match Resources")

    evidence_ids: set[str] = set()
    evidence_resource_order: list[str] = []
    oracle_evidence_state: dict[str, tuple[dict[str, object], str]] = {}
    for raw in raw_evidence:
        expected = {
            "evidence_id",
            "observed_at",
            "observer",
            "payload",
            "payload_kind",
            "payload_schema_version",
            "raw_attachment_digest",
            "state_addresses",
            "subject",
        }
        if not isinstance(raw, dict) or set(raw) != expected:
            errors.append("oracle: unknown or missing evidence fields")
            continue
        evidence_id = raw.get("evidence_id")
        subject = raw.get("subject")
        if not isinstance(evidence_id, str) or evidence_id in evidence_ids:
            errors.append("oracle: duplicate or invalid evidence ID")
            continue
        evidence_ids.add(evidence_id)
        if not isinstance(subject, dict) or set(subject) != {"id", "kind"}:
            errors.append("oracle: invalid evidence subject")
            continue
        subject_id = subject.get("id")
        if subject.get("kind") != "resource" or subject_id not in typed_ids:
            errors.append("oracle: dangling evidence subject")
            continue
        if evidence_id != f"evidence.{subject_id}.before":
            errors.append("oracle: evidence ID does not match subject")
        evidence_resource_order.append(str(subject_id))
        resource = resources[typed_ids.index(str(subject_id))]
        if raw.get("state_addresses") != resource.get("state_addresses"):
            errors.append("oracle: evidence State Addresses do not match Resource")
        if raw.get("observer") != {
            "code": "supplied-kodi-smart-playlist",
            "version": 1,
        }:
            errors.append("oracle: unsupported evidence codec")
        if schema_version == 2:
            decoded_state = _oracle_decode_kodi_plan_evidence(raw, errors)
            if decoded_state is not None:
                oracle_evidence_state[str(subject_id)] = decoded_state
        elif (
            raw.get("payload_kind") != "KodiSmartPlaylistObservation"
            or raw.get("payload_schema_version") != 1
            or not isinstance(raw.get("payload"), dict)
        ):
            errors.append("oracle: unsupported evidence codec")
    if evidence_resource_order != typed_ids:
        errors.append("oracle: evidence is not in Resource order")

    change_ids: set[str] = set()
    flattened_blockers: list[object] = []
    change_count = 0
    for resource_id, resource in zip(typed_ids, resources, strict=True):
        evidence_ref = f"evidence.{resource_id}.before"
        if resource.get("evidence_refs") != [evidence_ref]:
            errors.append("oracle: Resource evidence references do not agree")
        blockers = resource.get("blockers")
        oracle_blocker_codes: list[str] = []
        if isinstance(blockers, list):
            flattened_blockers.extend(blockers)
            for blocker in blockers:
                if not isinstance(blocker, dict) or set(blocker) != {
                    "code",
                    "evidence_refs",
                    "subject",
                }:
                    errors.append("oracle: invalid Resource blocker")
                    continue
                code = blocker.get("code")
                if not isinstance(code, str) or code not in ASSESSMENT_BLOCKER_CODES:
                    errors.append("oracle: unknown Resource blocker")
                else:
                    oracle_blocker_codes.append(code)
                if blocker.get("evidence_refs") != [evidence_ref] or blocker.get(
                    "subject"
                ) != {"id": resource_id, "kind": "resource"}:
                    errors.append("oracle: blocker binding does not match Resource")
            if len(set(oracle_blocker_codes)) != len(oracle_blocker_codes):
                errors.append("oracle: duplicate Resource blocker")
        else:
            errors.append("oracle: Resource blockers must be an array")
        changes = resource.get("changes")
        if not isinstance(changes, list):
            errors.append("oracle: Resource Changes must be an array")
            continue
        for change in changes:
            change_count += 1
            expected_change_fields = {
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
            }
            if not isinstance(change, dict) or set(change) != expected_change_fields:
                errors.append("oracle: unknown or missing Change fields")
                continue
            change_id = change.get("change_id")
            if not isinstance(change_id, str) or change_id in change_ids:
                errors.append("oracle: duplicate or invalid Change ID")
            else:
                change_ids.add(change_id)
            if (
                change.get("resource_id") != resource_id
                or change.get("resource_type") != resource.get("resource_type")
                or change.get("affected_state_addresses")
                != resource.get("state_addresses")
            ):
                errors.append("oracle: Change binding does not match Resource")
            before = change.get("before")
            if not isinstance(before, dict) or before.get("evidence_refs") != [
                evidence_ref
            ]:
                errors.append("oracle: Change evidence reference does not agree")
            elif schema_version == 2:
                evidence_state = oracle_evidence_state.get(resource_id)
                if evidence_state is None or (
                    before.get("summary") != evidence_state[0]
                    or before.get("normalized_state_digest") != evidence_state[1]
                ):
                    errors.append("oracle: Change before state does not match evidence")
            rollback = change.get("rollback")
            if (
                not isinstance(rollback, dict)
                or rollback.get("required_before_evidence_ref") != evidence_ref
            ):
                errors.append("oracle: rollback evidence reference does not agree")
            preconditions = change.get("preconditions")
            if (
                not isinstance(preconditions, list)
                or len(preconditions) != 1
                or not isinstance(preconditions[0], dict)
                or preconditions[0].get("evidence_ref") != evidence_ref
            ):
                errors.append("oracle: precondition evidence reference does not agree")
        management = resource.get("management")
        relation = resource.get("desired_relation")
        if management not in _MANAGEMENT_MODES:
            errors.append("oracle: unknown Resource management")
        elif relation == "satisfied":
            if oracle_blocker_codes or changes:
                errors.append("oracle: satisfied Resource is contradictory")
        elif relation == "not_applicable":
            if oracle_blocker_codes or changes:
                errors.append("oracle: not-applicable Resource is contradictory")
        elif relation == "divergent":
            if management == "enforce":
                if oracle_blocker_codes or len(changes) != 1:
                    errors.append(
                        "oracle: enforcing divergent Resource is contradictory"
                    )
            elif len(changes) != 0 or oracle_blocker_codes != [
                "resource.observe-only-divergence"
            ]:
                errors.append(
                    "oracle: observe-only divergent Resource is contradictory"
                )
        elif relation == "unverifiable":
            if (
                changes
                or len(oracle_blocker_codes) != 1
                or oracle_blocker_codes[0] == "resource.observe-only-divergence"
            ):
                errors.append("oracle: unverifiable Resource is contradictory")
        else:
            errors.append("oracle: unknown desired relation")
    if value.get("blockers") != flattened_blockers:
        errors.append("oracle: Plan blockers do not match Resources")
    disposition = value.get("disposition")
    if disposition == "actionable" and (change_count == 0 or flattened_blockers):
        errors.append("oracle: actionable Plan lacks unblocked Changes")
    if disposition == "noop" and (change_count or flattened_blockers):
        errors.append("oracle: no-op Plan contains work or blockers")
    if disposition == "blocked" and not flattened_blockers:
        errors.append("oracle: blocked Plan lacks blockers")
    return tuple(errors)


def reconstruct_plan_dependency_graph(
    content: bytes,
    *,
    resource_registry: ResourceRegistry | None = None,
) -> PlanDependencyGraph:
    """Reconstruct approved execution ordering solely from canonical Plan bytes."""
    plan = decode_plan(content, resource_registry=resource_registry)
    if plan.resource_dependencies:
        return PlanDependencyGraph(plan.resource_dependencies)
    value = decode_json_object(plan.canonical_bytes)
    resources = _array(value["resources"], "Plan Resources")
    resource = _mapping(resources[0], _plan_resource_fields(1), "Plan Resource")
    resource_id = _string(resource["resource_id"], "Resource ID")
    return PlanDependencyGraph(((resource_id, ()),))


def _oracle_decode_kodi_plan_evidence(
    evidence: dict[str, object],
    errors: list[str],
) -> tuple[dict[str, object], str] | None:
    if (
        evidence.get("payload_kind") != "KodiSmartPlaylistObservation"
        or evidence.get("payload_schema_version") != 2
    ):
        errors.append("oracle: unsupported evidence payload version")
        return None
    payload = evidence.get("payload")
    if not isinstance(payload, dict) or set(payload) != {
        "normalized_state_digest",
        "summary",
    }:
        errors.append("oracle: unknown or missing evidence payload fields")
        return None
    digest = payload.get("normalized_state_digest")
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        errors.append("oracle: invalid evidence normalized-state digest")
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict) or not _oracle_kodi_summary_is_closed(summary):
        errors.append("oracle: invalid closed evidence summary")
        return None
    return summary, digest


def _oracle_kodi_summary_is_closed(summary: dict[str, object]) -> bool:
    presence = summary.get("presence")
    if presence == "absent":
        return set(summary) == {"presence"}
    if presence != "present":
        return False
    if set(summary) == {"kind", "presence"}:
        return summary["kind"] in {"directory", "other", "symlink"}
    if set(summary) == {"presence", "readable"}:
        return summary["readable"] is False
    mode = summary.get("mode")
    if type(mode) is not int or not 0 <= mode <= 0o7777:
        return False
    if set(summary) == {"mode", "presence"}:
        return True
    playlist = summary.get("playlist")
    if not isinstance(playlist, dict):
        return False
    if set(summary) == {"content_digest", "mode", "playlist", "presence"}:
        digest = summary.get("content_digest")
        return (
            playlist == {"parse_status": "malformed"}
            and isinstance(digest, str)
            and _DIGEST.fullmatch(digest) is not None
        )
    if set(summary) != {"mode", "playlist", "presence"}:
        return False
    if set(playlist) != {
        "display_name",
        "limit",
        "match",
        "media_type",
        "order",
        "rules",
    }:
        return False
    order = playlist.get("order")
    rules = playlist.get("rules")
    return (
        isinstance(playlist.get("display_name"), str)
        and bool(playlist["display_name"])
        and type(playlist.get("limit")) is int
        and int(playlist["limit"]) >= 0
        and playlist.get("match") in {"all", "one"}
        and isinstance(playlist.get("media_type"), str)
        and bool(playlist["media_type"])
        and isinstance(order, dict)
        and set(order) == {"by", "direction"}
        and isinstance(order.get("by"), str)
        and bool(order["by"])
        and order.get("direction") in {"ascending", "descending"}
        and isinstance(rules, list)
        and all(
            isinstance(rule, dict)
            and set(rule) == {"field", "operator", "value"}
            and isinstance(rule.get("field"), str)
            and bool(rule["field"])
            and isinstance(rule.get("operator"), str)
            and bool(rule["operator"])
            and isinstance(rule.get("value"), (str, int))
            and not isinstance(rule.get("value"), bool)
            for rule in rules
        )
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
    *,
    schema_version: int,
    resource_registry: ResourceRegistry,
) -> None:
    if schema_version == 1:
        _validate_plan_shape_v1(value, disposition)
        return
    _validate_plan_shape_v2(value, disposition, resource_registry)


def _validate_plan_shape_v1(
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
        if code not in ASSESSMENT_BLOCKER_CODES:
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
        _string(
            _mapping(item, {"scope"}, "approval requirement")["scope"],
            "approval scope",
        )
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


def _plan_resource_fields(schema_version: int) -> set[str]:
    fields = {
        "blockers",
        "changes",
        "desired_relation",
        "evidence_refs",
        "management",
        "resource_id",
        "resource_type",
        "state_addresses",
    }
    return fields | ({"requires"} if schema_version == 2 else set())


def _validate_plan_shape_v2(
    value: dict[str, object],
    disposition: PlanDisposition,
    resource_registry: ResourceRegistry,
) -> None:
    _validate_nested_digests(value)
    if _mapping(value["producer"], {"name", "version"}, "producer") != _PRODUCER:
        raise ValueError("unsupported Plan producer")
    if value["continuation_policy"] != "continue_safe_independent":
        raise ValueError("unknown continuation policy")
    if _array(value["warnings"], "warnings"):
        raise ValueError("warnings are not supported")
    plan_id = require_uuid7(value["plan_id"], "plan_id")
    originating_run_id = require_uuid7(
        value["originating_run_id"], "originating_run_id"
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

    resource_values = _array(value["resources"], "resources")
    evidence_values = _array(value["evidence"], "evidence")
    if not resource_values or len(evidence_values) != len(resource_values):
        raise ValueError("Plan requires one evidence record per Resource")
    resources: list[dict[str, object]] = [
        _mapping(item, _plan_resource_fields(2), "Plan Resource")
        for item in resource_values
    ]
    resource_ids = [_string(item["resource_id"], "Resource ID") for item in resources]
    if len(set(resource_ids)) != len(resource_ids):
        raise ValueError("duplicate Plan Resource ID")
    requires_by_resource: dict[str, tuple[str, ...]] = {}
    resources_by_id: dict[str, dict[str, object]] = {}
    for resource, resource_id in zip(resources, resource_ids, strict=True):
        require_logical_id(resource_id, "Resource ID")
        resource_type = _string(resource["resource_type"], "Resource Type")
        if resource_registry.descriptor(resource_type) is None:
            raise ValueError("unregistered Plan Resource Type")
        state_addresses = _string_array(resource["state_addresses"], "State Address")
        if not state_addresses or state_addresses != sorted(set(state_addresses)):
            raise ValueError("Resource State Addresses must be sorted and unique")
        requirements = _string_array(resource["requires"], "dependency")
        if requirements != sorted(requirements):
            raise ValueError("Resource dependencies must be sorted")
        requires_by_resource[resource_id] = tuple(requirements)
        resources_by_id[resource_id] = resource
    if tuple(resource_ids) != _stable_topological_order(requires_by_resource):
        raise ValueError("Plan Resources are not in stable topological order")

    evidence_ids: set[str] = set()
    evidence_by_resource: dict[str, dict[str, object]] = {}
    evidence_state_by_resource: dict[
        str,
        tuple[dict[str, object], str],
    ] = {}
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
        subject = _mapping(evidence["subject"], {"id", "kind"}, "subject")
        resource_id = _string(subject["id"], "evidence subject ID")
        if subject["kind"] != "resource" or resource_id not in resources_by_id:
            raise ValueError("invalid evidence subject")
        if resource_id in evidence_by_resource:
            raise ValueError("duplicate Resource evidence")
        resource = resources_by_id[resource_id]
        if _mapping(evidence["observer"], {"code", "version"}, "observer") != {
            "code": "supplied-kodi-smart-playlist",
            "version": 1,
        }:
            raise ValueError("unsupported evidence observer")
        descriptor = resource_registry.descriptor(
            _string(resource["resource_type"], "Resource Type")
        )
        if descriptor is None or not isinstance(evidence["payload"], dict):
            raise ValueError("unsupported evidence payload")
        payload_kind = _string(evidence["payload_kind"], "evidence payload kind")
        payload_schema_version = evidence["payload_schema_version"]
        if type(payload_schema_version) is not int:
            raise ValueError("invalid evidence payload schema version")
        summary, normalized_state_digest = descriptor.decode_plan_evidence(
            payload_kind,
            payload_schema_version,
            evidence["payload"],
        )
        if evidence["state_addresses"] != resource["state_addresses"]:
            raise ValueError("evidence State Addresses do not match Resource")
        if parse_rfc3339_utc(evidence["observed_at"], "observed_at") > created_at:
            raise ValueError("evidence cannot be observed after Plan creation")
        attachment = evidence["raw_attachment_digest"]
        if attachment is not None:
            require_sha256(attachment, "raw attachment digest")
        evidence_id = _string(evidence["evidence_id"], "evidence ID")
        if evidence_id != f"evidence.{resource_id}.before":
            raise ValueError("invalid evidence ID")
        if evidence_id in evidence_ids:
            raise ValueError("duplicate evidence ID")
        evidence_ids.add(evidence_id)
        evidence_by_resource[resource_id] = evidence
        evidence_state_by_resource[resource_id] = (
            dict(summary),
            normalized_state_digest,
        )
    if list(evidence_by_resource) != resource_ids:
        raise ValueError("evidence is not in Resource order")

    all_blockers: list[object] = []
    all_changes: list[dict[str, object]] = []
    change_ids: set[str] = set()
    for resource, resource_id in zip(resources, resource_ids, strict=True):
        evidence_ref = f"evidence.{resource_id}.before"
        if _string_array(resource["evidence_refs"], "evidence reference") != [
            evidence_ref
        ]:
            raise ValueError("Resource evidence references do not agree")
        management = _string(resource["management"], "management")
        relation = _string(resource["desired_relation"], "desired relation")
        if management not in _MANAGEMENT_MODES:
            raise ValueError("unknown management mode")
        if relation not in _RELATIONS:
            raise ValueError("unknown desired relation")
        resource_blockers = _array(resource["blockers"], "Resource blockers")
        for blocker_value in resource_blockers:
            blocker = _mapping(
                blocker_value, {"code", "evidence_refs", "subject"}, "blocker"
            )
            if _mapping(blocker["subject"], {"id", "kind"}, "blocker subject") != {
                "id": resource_id,
                "kind": "resource",
            }:
                raise ValueError("invalid blocker subject")
            if blocker["code"] not in ASSESSMENT_BLOCKER_CODES:
                raise ValueError("unknown blocker code")
            if blocker["evidence_refs"] != [evidence_ref]:
                raise ValueError("unresolved blocker evidence reference")
        blocker_codes = [
            _string(
                _mapping(item, {"code", "evidence_refs", "subject"}, "blocker")["code"],
                "blocker code",
            )
            for item in resource_blockers
        ]
        if len(set(blocker_codes)) != len(blocker_codes):
            raise ValueError("duplicate blocker code")
        all_blockers.extend(resource_blockers)

        changes = _array(resource["changes"], "changes")
        for change_value in changes:
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
            operation = _string(change["operation_code"], "operation code")
            if change_id in change_ids:
                raise ValueError("duplicate Change ID")
            change_ids.add(change_id)
            if (
                change_id
                != f"change.{resource_id}.{operation.rsplit('.', maxsplit=1)[-1]}"
                or change["resource_id"] != resource_id
                or change["resource_type"] != resource["resource_type"]
                or change["operation_key"]
                != _string_array(resource["state_addresses"], "State Address")[0]
                or change["affected_state_addresses"] != resource["state_addresses"]
            ):
                raise ValueError("Change references do not agree with Resource")
            before = _mapping(
                change["before"],
                {"evidence_refs", "normalized_state_digest", "summary"},
                "Change before",
            )
            if before["evidence_refs"] != [evidence_ref]:
                raise ValueError("Change evidence references do not agree")
            before_digest = require_sha256(
                before["normalized_state_digest"], "before normalized state digest"
            )
            evidence_summary, evidence_digest = evidence_state_by_resource[resource_id]
            if (
                before["summary"] != evidence_summary
                or before_digest != evidence_digest
            ):
                raise ValueError("Change before state does not match evidence")
            desired = _mapping(
                change["desired"],
                {"normalized_state_digest", "summary"},
                "Change desired",
            )
            require_sha256(
                desired["normalized_state_digest"], "desired normalized state digest"
            )
            rollback = _mapping(
                change["rollback"],
                {"capability", "required_before_evidence_ref"},
                "rollback",
            )
            if rollback != {
                "capability": "verified_supported",
                "required_before_evidence_ref": evidence_ref,
            }:
                raise ValueError("rollback evidence reference does not agree")
            preconditions = _array(change["preconditions"], "preconditions")
            if len(preconditions) != 1:
                raise ValueError("Change requires exactly one precondition")
            precondition = _mapping(
                preconditions[0],
                {"evidence_ref", "expected_digest", "kind"},
                "precondition",
            )
            if precondition != {
                "evidence_ref": evidence_ref,
                "expected_digest": before_digest,
                "kind": "normalized_state_digest_matches",
            }:
                raise ValueError("Change precondition does not agree")
            if operation not in _OPERATIONS:
                raise ValueError("unknown operation code")
            if _array(change["effects"], "Change effects"):
                raise ValueError("KodiSmartPlaylist Change cannot declare Effects")
            _validate_change_combination(change, operation)
            all_changes.append(change)
        _validate_resource_assessment_semantics(
            management=management,
            relation=relation,
            blocker_codes=blocker_codes,
            change_count=len(changes),
        )

    if value["blockers"] != all_blockers:
        raise ValueError("Plan blockers do not match Resource blockers")
    if _array(value["effects"], "Plan effects"):
        raise ValueError("KodiSmartPlaylist Plan cannot declare Effects")
    requirements = [
        _string(
            _mapping(item, {"scope"}, "approval requirement")["scope"],
            "approval scope",
        )
        for item in _array(value["approval_requirements"], "approval requirements")
    ]
    if len(set(requirements)) != len(requirements):
        raise ValueError("duplicate approval requirement")
    if disposition is PlanDisposition.ACTIONABLE:
        if all_blockers or not all_changes:
            raise ValueError("actionable Plan requires unblocked Changes")
        valid_from = parse_rfc3339_utc(value["valid_from"], "valid_from")
        expires_at = parse_rfc3339_utc(value["expires_at"], "expires_at")
        if valid_from != created_at or expires_at <= valid_from:
            raise ValueError("invalid actionable Plan validity window")
        expected = ["apply"]
        if any(
            "removal" in _string_array(change["impact_codes"], "impact code")
            for change in all_changes
        ):
            expected.append("impact.removal")
        if requirements != expected:
            raise ValueError("approval requirements do not match impacts")
    elif requirements:
        raise ValueError("non-actionable Plan cannot require approval")
    elif disposition is PlanDisposition.NOOP:
        if all_blockers or all_changes:
            raise ValueError("no-op Plan cannot contain blockers or Changes")
    elif not all_blockers:
        raise ValueError("blocked Plan requires a blocker")


def _validate_resource_assessment_semantics(
    *,
    management: str,
    relation: str,
    blocker_codes: list[str],
    change_count: int,
) -> None:
    if relation == "satisfied":
        if blocker_codes or change_count:
            raise ValueError("satisfied Resource is contradictory")
        return
    if relation == "not_applicable":
        if blocker_codes or change_count:
            raise ValueError("not-applicable Resource is contradictory")
        return
    if relation == "divergent":
        if management == "enforce":
            if blocker_codes or change_count != 1:
                raise ValueError("enforcing divergent Resource requires one Change")
            return
        if (
            management == "observe_only"
            and change_count == 0
            and blocker_codes == ["resource.observe-only-divergence"]
        ):
            return
        raise ValueError("observe-only divergent Resource is contradictory")
    if relation == "unverifiable":
        if (
            change_count
            or len(blocker_codes) != 1
            or blocker_codes[0] == "resource.observe-only-divergence"
        ):
            raise ValueError("unverifiable Resource is contradictory")
        return
    raise ValueError("unknown desired relation")


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
    validate_change_codes(operation, tuple(reasons), tuple(impacts))


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
    if referenced_plan_id == originating_run_id:
        raise ValueError("referenced Plan ID must differ from originating Run ID")
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
    if not results:
        raise ValueError("planning Run requires Resource results")
    result_ids: list[str] = []
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
        result_id = require_logical_id(result["resource_id"], "Run Resource ID")
        result_ids.append(result_id)
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
        if status is RunStatus.NOOP:
            expected = ("satisfied", "not_required", "fresh_match", "converged")
        elif status is RunStatus.AWAITING_APPROVAL:
            expected = ("divergent", "pending", "not_started", "pending")
        elif result["latest_observed_relation"] == "satisfied":
            expected = ("satisfied", "not_required", "fresh_match", "converged")
        else:
            expected = (
                result["latest_observed_relation"],
                "blocked",
                "not_started",
                "blocked",
            )
        actual = (
            result["latest_observed_relation"],
            result["mutation_outcome"],
            result["verification_outcome"],
            result["final_convergence"],
        )
        if actual != expected:
            raise ValueError("Run Resource result contradicts status")
        if status is RunStatus.BLOCKED and result["latest_observed_relation"] not in {
            "satisfied",
            "divergent",
            "unverifiable",
        }:
            raise ValueError("blocked Run requires divergent or unverifiable state")
    if len(set(result_ids)) != len(result_ids):
        raise ValueError("duplicate Run Resource result")
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
        plan_schema_version = plan_value["schema_version"]
        if type(plan_schema_version) is not int:
            raise ValueError("invalid Plan schema version")
        plan_resource_ids = [
            _string(
                _mapping(
                    item,
                    _plan_resource_fields(plan_schema_version),
                    "Plan Resource",
                )["resource_id"],
                "Resource ID",
            )
            for item in _array(plan_value["resources"], "Plan Resources")
        ]
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
            or result_ids != plan_resource_ids
        ):
            raise ValueError("Run Plan reference is inconsistent")
        created_at = parse_rfc3339_utc(plan_value["created_at"], "created_at")
        if started_at > created_at:
            raise ValueError("Run cannot start after Plan creation")
        if ended is not None and parse_rfc3339_utc(ended, "ended_at") < created_at:
            raise ValueError("Run cannot end before Plan creation")
