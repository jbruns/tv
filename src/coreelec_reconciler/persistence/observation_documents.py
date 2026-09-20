"""Canonical observation-only Run documents and independent invariants."""

import hashlib
import re
from collections.abc import Iterable, Mapping
from itertools import pairwise

from coreelec_reconciler.domain.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.domain.execution import AttachmentRef
from coreelec_reconciler.domain.observation import (
    TERMINAL_OBSERVATION_STATUSES,
    CanonicalObservationRun,
    ObservationCheckpoint,
    ObservationCodecBinding,
    ObservationDisposition,
    ObservationResourceScope,
    ObservationRunStatus,
    ObservationScope,
)
from coreelec_reconciler.domain.validation import (
    parse_rfc3339_utc,
    require_logical_id,
    require_sha256,
    require_uuid7,
)
from coreelec_reconciler.resource_types.builtins import built_in_resource_registry
from coreelec_reconciler.resource_types.registry import ResourceRegistry

OBSERVATION_RUN_KIND = "CoreElecReconcilerObservationRun"
OBSERVATION_RUN_SCHEMA_VERSION = 1

_PRODUCER = {"name": "coreelec-reconciler", "version": "0.1.0"}
_FIELDS = {
    "checkpoints",
    "completed_resource_ids",
    "current_digest",
    "device_id",
    "ended_at",
    "kind",
    "previous_revision_digest",
    "producer",
    "revision",
    "run_id",
    "schema_version",
    "scope",
    "started_at",
    "status",
    "workspace_id",
}
_SCOPE_FIELDS = {
    "artifact_set_digest",
    "capability_digest",
    "configuration_digest",
    "profile_digest",
    "resources",
    "selector_digest",
}
_RESOURCE_FIELDS = {
    "observation_codec",
    "requires",
    "resource_id",
    "resource_type",
    "state_addresses",
}
_CODEC_FIELDS = {"kind", "policy_digest", "schema_version"}
_CHECKPOINT_FIELDS = {
    "disposition",
    "evidence",
    "observed_at",
    "observer",
    "raw_attachments",
    "resource_id",
    "resource_type",
    "sequence",
    "state_addresses",
}
_EVIDENCE_FIELDS = {"payload", "payload_kind", "payload_schema_version"}
_OBSERVER_FIELDS = {"code", "version"}
_ATTACHMENT_FIELDS = {"codec", "digest", "kind"}
_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_RESOURCE_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_WORKSPACE = re.compile(r"^workspace:[a-zA-Z0-9_-]{8,128}$")


def build_observation_run(
    value: dict[str, object],
    *,
    resource_registry: ResourceRegistry | None = None,
) -> CanonicalObservationRun:
    candidate = dict(value)
    candidate["current_digest"] = ""
    without_digest = {
        key: item for key, item in candidate.items() if key != "current_digest"
    }
    candidate["current_digest"] = _sha256(canonical_document_bytes(without_digest))
    return decode_observation_run(
        canonical_document_bytes(candidate),
        resource_registry=resource_registry,
    )


def decode_observation_run(
    content: bytes,
    *,
    resource_registry: ResourceRegistry | None = None,
) -> CanonicalObservationRun:
    value = decode_json_object(content)
    if set(value) != _FIELDS:
        raise ValueError("unknown or missing observation Run fields")
    if canonical_document_bytes(value) != content:
        raise ValueError("observation Run bytes are not canonical")
    if value["kind"] != OBSERVATION_RUN_KIND:
        raise ValueError("unsupported observation Run kind")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != OBSERVATION_RUN_SCHEMA_VERSION
    ):
        raise ValueError("unsupported observation Run schema version")
    if value["producer"] != _PRODUCER:
        raise ValueError("unsupported observation Run producer")
    run_id = require_uuid7(value["run_id"], "observation Run ID")
    device_id = require_logical_id(value["device_id"], "observation Device ID")
    workspace_id = _workspace(value["workspace_id"])
    started_at = parse_rfc3339_utc(value["started_at"], "observation started_at")
    revision = _positive_int(value["revision"], "observation revision")
    previous_digest = value["previous_revision_digest"]
    if previous_digest is not None:
        require_sha256(previous_digest, "observation previous revision digest")
    require_sha256(value["current_digest"], "observation current digest")
    without_digest = {
        key: item for key, item in value.items() if key != "current_digest"
    }
    if _sha256(canonical_document_bytes(without_digest)) != value["current_digest"]:
        raise ValueError("observation Run digest mismatch")
    status = ObservationRunStatus(_string(value["status"], "observation status"))
    ended_at_value = value["ended_at"]
    ended_at = (
        None
        if ended_at_value is None
        else parse_rfc3339_utc(ended_at_value, "observation ended_at")
    )
    if ended_at is not None and ended_at < started_at:
        raise ValueError("observation Run ends before it starts")
    scope = _decode_scope(
        value["scope"],
        resource_registry or built_in_resource_registry(),
    )
    checkpoints = _decode_checkpoints(
        value["checkpoints"],
        scope,
        resource_registry or built_in_resource_registry(),
    )
    completed = _strings(value["completed_resource_ids"], "completed Resource IDs")
    if completed != tuple(item.resource_id for item in checkpoints):
        raise ValueError("completed Resource IDs do not match checkpoint prefix")
    checkpoint_times = tuple(
        parse_rfc3339_utc(item.observed_at, "observation checkpoint observed_at")
        for item in checkpoints
    )
    if checkpoint_times and (
        checkpoint_times[0] < started_at
        or any(current < previous for previous, current in pairwise(checkpoint_times))
        or (ended_at is not None and checkpoint_times[-1] > ended_at)
    ):
        raise ValueError("observation checkpoint timestamps are out of order")
    _validate_summary(status, revision, previous_digest, ended_at, scope, checkpoints)
    return CanonicalObservationRun(
        canonical_bytes=content,
        run_id=run_id,
        workspace_id=workspace_id,
        device_id=device_id,
        current_digest=_string(value["current_digest"], "current digest"),
        revision=revision,
        status=status,
        scope=scope,
        checkpoints=checkpoints,
    )


def verify_observation_revision_chain(
    revisions: Iterable[bytes],
    *,
    resource_registry: ResourceRegistry | None = None,
) -> tuple[CanonicalObservationRun, ...]:
    decoded = tuple(
        decode_observation_run(content, resource_registry=resource_registry)
        for content in revisions
    )
    if not decoded:
        raise ValueError("observation Run chain is empty")
    identity = observation_run_identity(decode_json_object(decoded[0].canonical_bytes))
    for index, report in enumerate(decoded):
        if report.revision != index + 1:
            raise ValueError("observation Run revision sequence has a gap")
        value = decode_json_object(report.canonical_bytes)
        if observation_run_identity(value) != identity:
            raise ValueError("observation Run immutable scope changed")
        expected_previous = None if index == 0 else decoded[index - 1].current_digest
        if value["previous_revision_digest"] != expected_previous:
            raise ValueError("observation Run chain digest mismatch")
        if index:
            _validate_transition(decoded[index - 1], report)
    return decoded


def observation_run_identity(value: dict[str, object]) -> dict[str, object]:
    if value.get("kind") != OBSERVATION_RUN_KIND or not isinstance(
        value.get("scope"), dict
    ):
        raise ValueError("observation Run immutable identity is malformed")
    return {
        "created_at": value.get("started_at"),
        "device_id": value.get("device_id"),
        "kind": value.get("kind"),
        "producer": value.get("producer"),
        "run_id": value.get("run_id"),
        "schema_version": value.get("schema_version"),
        "scope": value.get("scope"),
        "workspace_id": value.get("workspace_id"),
    }


def observation_attachment_refs(
    run: CanonicalObservationRun,
) -> tuple[AttachmentRef, ...]:
    return tuple(
        reference
        for checkpoint in run.checkpoints
        for reference in checkpoint.raw_attachments
    )


def check_observation_run_invariants(
    content: bytes,
    *,
    resource_registry: ResourceRegistry | None = None,
) -> tuple[str, ...]:
    """Independently check one observation revision without using its decoder."""
    try:
        value = decode_json_object(content)
    except ValueError:
        return ("oracle: observation Run is not a JSON object",)
    errors: list[str] = []
    if set(value) != _FIELDS:
        return ("oracle: unknown or missing observation Run fields",)
    if canonical_document_bytes(value) != content:
        errors.append("oracle: observation Run bytes are not canonical")
    if value["kind"] != OBSERVATION_RUN_KIND:
        errors.append("oracle: unsupported observation Run kind")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        errors.append("oracle: unsupported observation Run version")
    if value["producer"] != _PRODUCER:
        errors.append("oracle: unsupported observation Run producer")
    for field, validator in (
        ("run_id", require_uuid7),
        ("device_id", require_logical_id),
    ):
        try:
            validator(value[field], f"oracle observation {field}")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
    if (
        not isinstance(value["workspace_id"], str)
        or _WORKSPACE.fullmatch(value["workspace_id"]) is None
    ):
        errors.append("oracle: invalid observation workspace ID")
    try:
        started_at = parse_rfc3339_utc(value["started_at"], "oracle started_at")
    except (TypeError, ValueError) as error:
        errors.append(str(error))
        started_at = None
    ended_at_value = value["ended_at"]
    if ended_at_value is None:
        ended_at = None
    else:
        try:
            ended_at = parse_rfc3339_utc(ended_at_value, "oracle ended_at")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
            ended_at = None
    if started_at is not None and ended_at is not None and ended_at < started_at:
        errors.append("oracle: observation Run ends before it starts")
    revision = value["revision"]
    if type(revision) is not int or revision < 1:
        errors.append("oracle: invalid observation revision")
    previous = value["previous_revision_digest"]
    if previous is not None:
        try:
            require_sha256(previous, "oracle previous digest")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
    digest = value["current_digest"]
    try:
        require_sha256(digest, "oracle current digest")
    except (TypeError, ValueError) as error:
        errors.append(str(error))
    else:
        without_digest = {
            key: item for key, item in value.items() if key != "current_digest"
        }
        if _sha256(canonical_document_bytes(without_digest)) != digest:
            errors.append("oracle: observation Run digest mismatch")
    try:
        status = (
            ObservationRunStatus(value["status"])
            if isinstance(value["status"], str)
            else None
        )
    except ValueError:
        status = None
    if status is None:
        errors.append("oracle: unknown observation status")
    registry = resource_registry or built_in_resource_registry()
    resources = _oracle_scope(value["scope"], registry, errors)
    checkpoints = _oracle_checkpoints(value["checkpoints"], resources, registry, errors)
    if isinstance(value["checkpoints"], list) and started_at is not None:
        previous_time = started_at
        for raw in value["checkpoints"]:
            if not isinstance(raw, dict):
                continue
            try:
                observed_time = parse_rfc3339_utc(
                    raw.get("observed_at"),
                    "oracle checkpoint observed_at",
                )
            except TypeError, ValueError:
                continue
            if observed_time < previous_time:
                errors.append(
                    "oracle: observation checkpoint timestamps are out of order"
                )
            previous_time = observed_time
        if ended_at is not None and previous_time > ended_at:
            errors.append("oracle: observation checkpoint follows Run end")
    completed = value["completed_resource_ids"]
    if not isinstance(completed, list) or any(
        not isinstance(item, str) for item in completed
    ):
        errors.append("oracle: completed Resource IDs are not strings")
    elif tuple(completed) != tuple(item[0] for item in checkpoints):
        errors.append("oracle: completed Resource IDs do not match checkpoint prefix")
    if status is not None and type(revision) is int:
        _oracle_summary(
            status,
            revision,
            previous,
            ended_at,
            len(resources),
            checkpoints,
            errors,
        )
    return tuple(errors)


def check_observation_chain_invariants(
    revisions: Iterable[bytes],
    *,
    resource_registry: ResourceRegistry | None = None,
) -> tuple[str, ...]:
    contents = tuple(revisions)
    if not contents:
        return ("oracle: observation Run chain is empty",)
    errors: list[str] = []
    values: list[dict[str, object]] = []
    for content in contents:
        errors.extend(
            check_observation_run_invariants(
                content,
                resource_registry=resource_registry,
            )
        )
        try:
            values.append(decode_json_object(content))
        except ValueError:
            return tuple(errors)
    first_identity = _oracle_identity(values[0])
    for index, value in enumerate(values):
        if value.get("revision") != index + 1:
            errors.append("oracle: observation revision sequence has a gap")
        if _oracle_identity(value) != first_identity:
            errors.append("oracle: observation immutable scope changed")
        previous = None if index == 0 else values[index - 1].get("current_digest")
        if value.get("previous_revision_digest") != previous:
            errors.append("oracle: observation chain digest mismatch")
        if index:
            _oracle_transition(values[index - 1], value, errors)
    return tuple(errors)


def _decode_scope(value: object, registry: ResourceRegistry) -> ObservationScope:
    raw = _object(value, _SCOPE_FIELDS, "observation scope")
    digests = {
        field: require_sha256(raw[field], f"observation scope {field}")
        for field in (
            "artifact_set_digest",
            "capability_digest",
            "configuration_digest",
            "profile_digest",
            "selector_digest",
        )
    }
    resource_values = _array(raw["resources"], "observation Resources")
    if not resource_values:
        raise ValueError("observation scope requires Resources")
    resources: list[ObservationResourceScope] = []
    seen: set[str] = set()
    for resource_value in resource_values:
        item = _object(resource_value, _RESOURCE_FIELDS, "observation Resource")
        resource_id = require_logical_id(item["resource_id"], "observation Resource ID")
        if resource_id in seen:
            raise ValueError("duplicate observation Resource ID")
        resource_type = _resource_type(item["resource_type"])
        descriptor = registry.descriptor(resource_type)
        if (
            descriptor is None
            or descriptor.observation_payload_kind is None
            or descriptor.observation_payload_version is None
            or descriptor.observation_policy_digest is None
            or descriptor.decode_observation_evidence is None
            or descriptor.validate_observation_addresses is None
        ):
            raise ValueError("unregistered observation Resource Type")
        state_addresses = _unique_strings(
            item["state_addresses"], "observation State Addresses"
        )
        if not state_addresses:
            raise ValueError("observation Resource requires State Addresses")
        descriptor.validate_observation_addresses(state_addresses)
        requires = _unique_strings(item["requires"], "observation dependencies")
        if resource_id in requires or any(
            required not in seen for required in requires
        ):
            raise ValueError("observation dependencies violate stable order")
        codec_value = _object(
            item["observation_codec"],
            _CODEC_FIELDS,
            "observation codec",
        )
        codec = ObservationCodecBinding(
            _string(codec_value["kind"], "observation codec kind"),
            _positive_int(
                codec_value["schema_version"],
                "observation codec version",
            ),
            require_sha256(
                codec_value["policy_digest"],
                "observation policy digest",
            ),
        )
        if (
            codec.kind != descriptor.observation_payload_kind
            or codec.schema_version != descriptor.observation_payload_version
            or codec.policy_digest != descriptor.observation_policy_digest
        ):
            raise ValueError("observation codec binding does not match registry")
        resources.append(
            ObservationResourceScope(
                resource_id,
                resource_type,
                state_addresses,
                requires,
                codec,
            )
        )
        seen.add(resource_id)
    if tuple(item.resource_id for item in resources) != _stable_resource_order(
        resources
    ):
        raise ValueError("observation Resources are not in stable dependency order")
    return ObservationScope(
        configuration_digest=digests["configuration_digest"],
        profile_digest=digests["profile_digest"],
        artifact_set_digest=digests["artifact_set_digest"],
        capability_digest=digests["capability_digest"],
        selector_digest=digests["selector_digest"],
        resources=tuple(resources),
    )


def _decode_checkpoints(
    value: object,
    scope: ObservationScope,
    registry: ResourceRegistry,
) -> tuple[ObservationCheckpoint, ...]:
    raw = _array(value, "observation checkpoints")
    if len(raw) > len(scope.resources):
        raise ValueError("observation checkpoints exceed scope")
    checkpoints: list[ObservationCheckpoint] = []
    for index, checkpoint_value in enumerate(raw):
        checkpoint = _object(
            checkpoint_value,
            _CHECKPOINT_FIELDS,
            "observation checkpoint",
        )
        resource = scope.resources[index]
        if checkpoint["sequence"] != index + 1:
            raise ValueError("observation checkpoint sequence has a gap")
        if (
            checkpoint["resource_id"] != resource.resource_id
            or checkpoint["resource_type"] != resource.resource_type
            or checkpoint["state_addresses"] != list(resource.state_addresses)
        ):
            raise ValueError("observation checkpoint does not match scope prefix")
        observer = _object(
            checkpoint["observer"],
            _OBSERVER_FIELDS,
            "observation observer",
        )
        observer_code = _safe_code(observer["code"], "observer code")
        observer_version = _positive_int(observer["version"], "observer version")
        parse_rfc3339_utc(
            checkpoint["observed_at"],
            "observation checkpoint observed_at",
        )
        disposition = ObservationDisposition(
            _string(checkpoint["disposition"], "observation disposition")
        )
        evidence = _object(
            checkpoint["evidence"],
            _EVIDENCE_FIELDS,
            "observation evidence",
        )
        payload_kind = _string(evidence["payload_kind"], "payload kind")
        payload_version = _positive_int(
            evidence["payload_schema_version"],
            "payload schema version",
        )
        payload = _object_any(evidence["payload"], "observation payload")
        descriptor = registry.descriptor(resource.resource_type)
        if descriptor is None or descriptor.decode_observation_evidence is None:
            raise ValueError("unregistered observation Resource Type")
        normalized = descriptor.decode_observation_evidence(
            payload_kind,
            payload_version,
            payload,
        )
        attachments = _decode_attachments(checkpoint["raw_attachments"])
        _validate_checkpoint_facts(disposition, normalized, attachments)
        checkpoints.append(
            ObservationCheckpoint(
                sequence=index + 1,
                resource_id=resource.resource_id,
                resource_type=resource.resource_type,
                state_addresses=resource.state_addresses,
                observed_at=_string(
                    checkpoint["observed_at"],
                    "observation checkpoint observed_at",
                ),
                observer_code=observer_code,
                observer_version=observer_version,
                disposition=disposition,
                payload_kind=payload_kind,
                payload_schema_version=payload_version,
                payload=dict(normalized),
                raw_attachments=attachments,
            )
        )
    return tuple(checkpoints)


def _decode_attachments(value: object) -> tuple[AttachmentRef, ...]:
    raw = _array(value, "raw observation attachments")
    attachments: list[AttachmentRef] = []
    seen: set[str] = set()
    for item_value in raw:
        item = _object(
            item_value,
            _ATTACHMENT_FIELDS,
            "raw observation attachment",
        )
        digest = require_sha256(item["digest"], "raw observation attachment digest")
        if digest in seen:
            raise ValueError("duplicate raw observation attachment")
        attachments.append(
            AttachmentRef(
                digest,
                _safe_code(item["kind"], "attachment kind"),
                _safe_code(item["codec"], "attachment codec"),
            )
        )
        seen.add(digest)
    return tuple(attachments)


def _validate_checkpoint_facts(
    disposition: ObservationDisposition,
    payload: Mapping[str, object],
    attachments: tuple[AttachmentRef, ...],
) -> None:
    availability = payload.get("availability")
    expected = {
        ObservationDisposition.OBSERVED: "available",
        ObservationDisposition.UNAVAILABLE: "unavailable",
        ObservationDisposition.UNKNOWN: "unknown",
    }[disposition]
    if availability != expected:
        raise ValueError("observation disposition contradicts payload")
    content_digest = payload.get("content_digest")
    if content_digest is None:
        if attachments:
            raise ValueError("observation without raw content has attachments")
        return
    if (
        len(attachments) != 1
        or attachments[0].digest != content_digest
        or attachments[0].kind != "raw-observation"
        or attachments[0].codec != "raw-bytes-v1"
    ):
        raise ValueError("raw observation attachment does not match content")


def _validate_summary(
    status: ObservationRunStatus,
    revision: int,
    previous_digest: object,
    ended_at: object,
    scope: ObservationScope,
    checkpoints: tuple[ObservationCheckpoint, ...],
) -> None:
    if revision == 1 and previous_digest is not None:
        raise ValueError("initial observation revision has a predecessor")
    if revision > 1 and previous_digest is None:
        raise ValueError("successor observation revision lacks predecessor")
    if status is ObservationRunStatus.READY:
        if revision != 1 or checkpoints or ended_at is not None:
            raise ValueError("ready observation Run is contradictory")
        return
    if status is ObservationRunStatus.OBSERVING:
        if len(checkpoints) >= len(scope.resources) or ended_at is not None:
            raise ValueError("observing Run checkpoint summary is contradictory")
        return
    if len(checkpoints) != len(scope.resources) or ended_at is None:
        raise ValueError("terminal observation Run is incomplete")
    all_observed = all(
        item.disposition is ObservationDisposition.OBSERVED for item in checkpoints
    )
    if (status is ObservationRunStatus.OBSERVED) != all_observed:
        raise ValueError("terminal observation status contradicts checkpoints")


def _validate_transition(
    previous: CanonicalObservationRun,
    current: CanonicalObservationRun,
) -> None:
    if previous.status in TERMINAL_OBSERVATION_STATUSES:
        raise ValueError("terminal observation Run has a successor")
    previous_checkpoints = previous.checkpoints
    if current.checkpoints[: len(previous_checkpoints)] != previous_checkpoints:
        raise ValueError("prior observation checkpoints changed")
    added = len(current.checkpoints) - len(previous_checkpoints)
    if added not in {0, 1}:
        raise ValueError("observation Run appended multiple checkpoints")
    if added == 0 and not (
        previous.status is ObservationRunStatus.READY
        and current.status is ObservationRunStatus.OBSERVING
    ):
        raise ValueError("observation Run successor made no progress")
    if previous.status is ObservationRunStatus.READY and current.status not in {
        ObservationRunStatus.OBSERVING,
        ObservationRunStatus.OBSERVED,
        ObservationRunStatus.OBSERVED_PARTIAL,
    }:
        raise ValueError("invalid observation lifecycle transition")
    if previous.status is ObservationRunStatus.OBSERVING and current.status not in {
        ObservationRunStatus.OBSERVING,
        ObservationRunStatus.OBSERVED,
        ObservationRunStatus.OBSERVED_PARTIAL,
    }:
        raise ValueError("invalid observation lifecycle transition")


def _oracle_scope(
    value: object,
    registry: ResourceRegistry,
    errors: list[str],
) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
    if not isinstance(value, dict) or set(value) != _SCOPE_FIELDS:
        errors.append("oracle: unknown or missing observation scope fields")
        return []
    for field in _SCOPE_FIELDS - {"resources"}:
        try:
            require_sha256(value[field], f"oracle scope {field}")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
    raw_resources = value["resources"]
    if not isinstance(raw_resources, list) or not raw_resources:
        errors.append("oracle: observation scope requires Resources")
        return []
    resources: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = []
    seen: set[str] = set()
    for raw in raw_resources:
        if not isinstance(raw, dict) or set(raw) != _RESOURCE_FIELDS:
            errors.append("oracle: malformed observation Resource")
            continue
        resource_id = raw["resource_id"]
        resource_type = raw["resource_type"]
        try:
            valid_id = require_logical_id(resource_id, "oracle Resource ID")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
            continue
        if valid_id in seen:
            errors.append("oracle: duplicate observation Resource ID")
        addresses = _oracle_string_array(
            raw["state_addresses"], "State Addresses", errors
        )
        requires = _oracle_string_array(raw["requires"], "dependencies", errors)
        if valid_id in requires or any(item not in seen for item in requires):
            errors.append("oracle: dependencies violate stable order")
        if (
            not isinstance(resource_type, str)
            or _RESOURCE_TYPE.fullmatch(resource_type) is None
        ):
            errors.append("oracle: invalid Resource Type")
            continue
        descriptor = registry.descriptor(resource_type)
        codec = raw["observation_codec"]
        if (
            descriptor is None
            or descriptor.check_observation_evidence is None
            or descriptor.check_observation_addresses is None
            or not isinstance(codec, dict)
            or set(codec) != _CODEC_FIELDS
            or codec.get("kind") != descriptor.observation_payload_kind
            or codec.get("schema_version") != descriptor.observation_payload_version
            or codec.get("policy_digest") != descriptor.observation_policy_digest
        ):
            errors.append("oracle: observation codec binding is unregistered")
        elif descriptor is not None:
            errors.extend(descriptor.check_observation_addresses(addresses))
        resources.append((valid_id, resource_type, addresses, requires))
        seen.add(valid_id)
    pending = {item[0]: set(item[3]) for item in resources}
    stable: list[str] = []
    while pending:
        ready = sorted(
            resource_id
            for resource_id, requirements in pending.items()
            if requirements <= set(stable)
        )
        if not ready:
            errors.append("oracle: observation dependency graph is cyclic")
            break
        selected = ready[0]
        stable.append(selected)
        del pending[selected]
    if tuple(item[0] for item in resources) != tuple(stable):
        errors.append("oracle: Resources are not in stable dependency order")
    return resources


def _oracle_checkpoints(
    value: object,
    resources: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]],
    registry: ResourceRegistry,
    errors: list[str],
) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        errors.append("oracle: observation checkpoints are not an array")
        return []
    if len(value) > len(resources):
        errors.append("oracle: checkpoints exceed scope")
    checked: list[tuple[str, str]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != _CHECKPOINT_FIELDS:
            errors.append("oracle: malformed observation checkpoint")
            continue
        if index >= len(resources):
            continue
        resource_id, resource_type, addresses, _ = resources[index]
        if (
            raw["sequence"] != index + 1
            or raw["resource_id"] != resource_id
            or raw["resource_type"] != resource_type
            or raw["state_addresses"] != list(addresses)
        ):
            errors.append("oracle: checkpoint does not match scope prefix")
        observer = raw["observer"]
        if (
            not isinstance(observer, dict)
            or set(observer) != _OBSERVER_FIELDS
            or not isinstance(observer.get("code"), str)
            or _SAFE_CODE.fullmatch(observer["code"]) is None
            or type(observer.get("version")) is not int
            or observer["version"] < 1
        ):
            errors.append("oracle: invalid observation observer")
        try:
            parse_rfc3339_utc(raw["observed_at"], "oracle observed_at")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
        disposition = raw["disposition"]
        if not isinstance(disposition, str) or disposition not in {
            "observed",
            "unavailable",
            "unknown",
        }:
            errors.append("oracle: invalid observation disposition")
        evidence = raw["evidence"]
        descriptor = registry.descriptor(resource_type)
        if (
            not isinstance(evidence, dict)
            or set(evidence) != _EVIDENCE_FIELDS
            or descriptor is None
            or descriptor.check_observation_evidence is None
        ):
            errors.append("oracle: malformed observation evidence")
            continue
        errors.extend(
            descriptor.check_observation_evidence(
                evidence["payload_kind"],
                evidence["payload_schema_version"],
                evidence["payload"],
            )
        )
        attachments = _oracle_attachments(raw["raw_attachments"], errors)
        payload = evidence["payload"]
        if isinstance(payload, dict):
            expected = {
                "observed": "available",
                "unavailable": "unavailable",
                "unknown": "unknown",
            }.get(disposition)
            if payload.get("availability") != expected:
                errors.append("oracle: disposition contradicts observation payload")
            content_digest = payload.get("content_digest")
            if content_digest is None:
                if attachments:
                    errors.append("oracle: observation without content has attachment")
            elif attachments != (
                (
                    content_digest,
                    "raw-observation",
                    "raw-bytes-v1",
                ),
            ):
                errors.append("oracle: raw attachment does not match content")
        checked.append((resource_id, str(disposition)))
    return checked


def _oracle_attachments(
    value: object,
    errors: list[str],
) -> tuple[tuple[object, object, object], ...]:
    if not isinstance(value, list):
        errors.append("oracle: raw attachments are not an array")
        return ()
    result: list[tuple[object, object, object]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _ATTACHMENT_FIELDS:
            errors.append("oracle: malformed raw attachment")
            continue
        digest = raw["digest"]
        try:
            require_sha256(digest, "oracle attachment digest")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
        if isinstance(digest, str) and digest in seen:
            errors.append("oracle: duplicate raw attachment")
        if not isinstance(raw["kind"], str) or not isinstance(raw["codec"], str):
            errors.append("oracle: invalid raw attachment code")
        result.append((digest, raw["kind"], raw["codec"]))
        if isinstance(digest, str):
            seen.add(digest)
    return tuple(result)


def _oracle_summary(
    status: ObservationRunStatus,
    revision: int,
    previous: object,
    ended_at: object,
    resource_count: int,
    checkpoints: list[tuple[str, str]],
    errors: list[str],
) -> None:
    if revision == 1 and previous is not None:
        errors.append("oracle: initial revision has predecessor")
    if revision > 1 and previous is None:
        errors.append("oracle: successor lacks predecessor")
    if status is ObservationRunStatus.READY:
        if revision != 1 or checkpoints or ended_at is not None:
            errors.append("oracle: contradictory ready observation Run")
    elif status is ObservationRunStatus.OBSERVING:
        if len(checkpoints) >= resource_count or ended_at is not None:
            errors.append("oracle: contradictory observing Run")
    else:
        if len(checkpoints) != resource_count or ended_at is None:
            errors.append("oracle: incomplete terminal observation Run")
        all_observed = all(item[1] == "observed" for item in checkpoints)
        if (status is ObservationRunStatus.OBSERVED) != all_observed:
            errors.append("oracle: terminal status contradicts checkpoints")


def _oracle_transition(
    previous: dict[str, object],
    current: dict[str, object],
    errors: list[str],
) -> None:
    if previous.get("status") in {"observed", "observed_partial"}:
        errors.append("oracle: terminal observation Run has successor")
    old = previous.get("checkpoints")
    new = current.get("checkpoints")
    if not isinstance(old, list) or not isinstance(new, list):
        return
    if new[: len(old)] != old:
        errors.append("oracle: prior observation checkpoints changed")
    added = len(new) - len(old)
    if added not in {0, 1}:
        errors.append("oracle: successor appended multiple checkpoints")
    if added == 0 and not (
        previous.get("status") == "ready" and current.get("status") == "observing"
    ):
        errors.append("oracle: observation successor made no progress")


def _oracle_identity(value: dict[str, object]) -> tuple[object, ...]:
    return (
        value.get("kind"),
        value.get("schema_version"),
        value.get("producer"),
        value.get("run_id"),
        value.get("workspace_id"),
        value.get("device_id"),
        value.get("started_at"),
        value.get("scope"),
    )


def _stable_resource_order(
    resources: list[ObservationResourceScope],
) -> tuple[str, ...]:
    pending = {resource.resource_id: set(resource.requires) for resource in resources}
    ordered: list[str] = []
    while pending:
        ready = sorted(
            resource_id
            for resource_id, requirements in pending.items()
            if requirements <= set(ordered)
        )
        if not ready:
            raise ValueError("observation dependency graph is cyclic")
        selected = ready[0]
        ordered.append(selected)
        del pending[selected]
    return tuple(ordered)


def _object(value: object, fields: set[str], label: str) -> dict[str, object]:
    result = _object_any(value, label)
    if set(result) != fields:
        raise ValueError(f"unknown or missing {label} fields")
    return result


def _object_any(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    raw = _array(value, label)
    if any(not isinstance(item, str) for item in raw):
        raise ValueError(f"{label} must contain strings")
    return tuple(raw)  # type: ignore[arg-type]


def _unique_strings(value: object, label: str) -> tuple[str, ...]:
    values = _strings(value, label)
    if not all(values) or len(set(values)) != len(values):
        raise ValueError(f"{label} must be non-empty unique strings")
    return values


def _oracle_string_array(
    value: object,
    label: str,
    errors: list[str],
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        errors.append(f"oracle: {label} must contain strings")
        return ()
    result = tuple(value)
    if not all(result) or len(set(result)) != len(result):
        errors.append(f"oracle: {label} must be non-empty and unique")
    return result


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _workspace(value: object) -> str:
    workspace_id = _string(value, "observation workspace ID")
    if _WORKSPACE.fullmatch(workspace_id) is None:
        raise ValueError("invalid observation workspace ID")
    return workspace_id


def _resource_type(value: object) -> str:
    resource_type = _string(value, "observation Resource Type")
    if _RESOURCE_TYPE.fullmatch(resource_type) is None:
        raise ValueError("invalid observation Resource Type")
    return resource_type


def _safe_code(value: object, label: str) -> str:
    code = _string(value, label)
    if _SAFE_CODE.fullmatch(code) is None:
        raise ValueError(f"invalid {label}")
    return code


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()
