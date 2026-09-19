"""Strict versioned codecs for supplied playlist observations and assessments."""

import base64
from collections.abc import Mapping

from coreelec_reconciler.domain.configuration import ManagementMode
from coreelec_reconciler.domain.planning import (
    DesiredRelation,
    FileKind,
    KodiSmartPlaylistObservation,
    PlaylistAssessment,
)
from coreelec_reconciler.domain.validation import (
    require_file_mode,
    require_rfc3339_utc,
    require_sha256,
)

_MAX_CONTENT_BYTES = 65536
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


def encode_observation(
    observation: KodiSmartPlaylistObservation,
) -> Mapping[str, object]:
    return {
        "payload": {
            "content_base64": (
                None
                if observation.content is None
                else base64.b64encode(observation.content).decode("ascii")
            ),
            "kind": observation.kind.value,
            "mode": observation.mode,
            "observed_at": observation.observed_at,
            "resource_id": observation.resource_id,
            "state_address": observation.state_address,
        },
        "payload_kind": "KodiSmartPlaylistObservation",
        "payload_schema_version": 1,
    }


def decode_observation(value: Mapping[str, object]) -> KodiSmartPlaylistObservation:
    if set(value) != {"payload", "payload_kind", "payload_schema_version"}:
        raise ValueError("unknown or missing Observation envelope fields")
    if (
        value["payload_kind"] != "KodiSmartPlaylistObservation"
        or value["payload_schema_version"] != 1
    ):
        raise ValueError("unsupported Observation payload")
    payload = _object(
        value["payload"],
        {
            "content_base64",
            "kind",
            "mode",
            "observed_at",
            "resource_id",
            "state_address",
        },
        "Observation",
    )
    encoded = payload["content_base64"]
    if encoded is None:
        content = None
    else:
        if not isinstance(encoded, str):
            raise ValueError("Observation content must be base64 text")
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ValueError("Observation content must be base64 text") from error
        if len(content) > _MAX_CONTENT_BYTES:
            raise ValueError("Observation content exceeds the safe limit")
    mode = require_file_mode(payload["mode"])
    kind = FileKind(_string(payload["kind"]))
    resource_id = _nonempty_string(payload["resource_id"], "Resource ID")
    state_address = _nonempty_string(payload["state_address"], "State Address")
    observed_at = require_rfc3339_utc(payload["observed_at"], "observed_at")
    if kind is FileKind.ABSENT and (mode is not None or content is not None):
        raise ValueError("absent observation cannot contain file state")
    if kind is FileKind.REGULAR and mode is None:
        raise ValueError("regular observation requires mode")
    if kind not in {FileKind.ABSENT, FileKind.REGULAR} and content is not None:
        raise ValueError("unsafe observations cannot contain raw content")
    return KodiSmartPlaylistObservation(
        resource_id=resource_id,
        state_address=state_address,
        observed_at=observed_at,
        kind=kind,
        mode=mode,
        content=content,
    )


def encode_assessment(assessment: PlaylistAssessment) -> Mapping[str, object]:
    _validate_assessment(assessment)
    return {
        "payload": {
            "before_digest": assessment.before_digest,
            "before_summary": dict(assessment.before_summary),
            "blocker_codes": list(assessment.blocker_codes),
            "desired_digest": assessment.desired_digest,
            "desired_summary": dict(assessment.desired_summary),
            "effects": list(assessment.effects),
            "impact_codes": list(assessment.impact_codes),
            "management": assessment.management.value,
            "operation_code": assessment.operation_code,
            "reason_codes": list(assessment.reason_codes),
            "relation": assessment.relation.value,
        },
        "payload_kind": "KodiSmartPlaylistAssessment",
        "payload_schema_version": 1,
    }


def decode_assessment(value: Mapping[str, object]) -> PlaylistAssessment:
    if set(value) != {"payload", "payload_kind", "payload_schema_version"}:
        raise ValueError("unknown or missing Assessment envelope fields")
    if (
        value["payload_kind"] != "KodiSmartPlaylistAssessment"
        or value["payload_schema_version"] != 1
    ):
        raise ValueError("unsupported Assessment payload")
    payload = _object(
        value["payload"],
        {
            "before_digest",
            "before_summary",
            "blocker_codes",
            "desired_digest",
            "desired_summary",
            "effects",
            "impact_codes",
            "management",
            "operation_code",
            "reason_codes",
            "relation",
        },
        "Assessment",
    )
    operation = payload["operation_code"]
    if operation is not None and not isinstance(operation, str):
        raise ValueError("Assessment operation must be a string or null")
    assessment = PlaylistAssessment(
        relation=DesiredRelation(_string(payload["relation"])),
        management=ManagementMode(_string(payload["management"])),
        operation_code=operation,
        reason_codes=_strings(payload["reason_codes"]),
        impact_codes=_strings(payload["impact_codes"]),
        blocker_codes=_strings(payload["blocker_codes"]),
        before_digest=_string(payload["before_digest"]),
        desired_digest=_string(payload["desired_digest"]),
        before_summary=tuple(
            sorted(_object_any(payload["before_summary"], "before summary").items())
        ),
        desired_summary=tuple(
            sorted(_object_any(payload["desired_summary"], "desired summary").items())
        ),
        effects=_strings(payload["effects"]),
    )
    _validate_assessment(assessment)
    return assessment


def _object(
    value: object,
    fields: set[str],
    label: str,
) -> Mapping[str, object]:
    mapping = _object_any(value, label)
    if set(mapping) != fields:
        raise ValueError(f"unknown or missing {label} fields")
    return mapping


def _object_any(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("codec value must be a string")
    return value


def _nonempty_string(value: object, label: str) -> str:
    text = _string(value)
    if not text:
        raise ValueError(f"{label} must not be empty")
    return text


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("codec value must be an array")
    return tuple(_string(item) for item in value)


def _validate_assessment(assessment: PlaylistAssessment) -> None:
    require_sha256(assessment.before_digest, "before_digest")
    require_sha256(assessment.desired_digest, "desired_digest")
    if not assessment.before_summary or not assessment.desired_summary:
        raise ValueError("Assessment summaries must not be empty")
    if len(dict(assessment.before_summary)) != len(assessment.before_summary):
        raise ValueError("Assessment before summary has duplicate fields")
    if len(dict(assessment.desired_summary)) != len(assessment.desired_summary):
        raise ValueError("Assessment desired summary has duplicate fields")
    for key, _ in (*assessment.before_summary, *assessment.desired_summary):
        if not key:
            raise ValueError("Assessment summary fields must not be empty")
    if len(set(assessment.reason_codes)) != len(assessment.reason_codes):
        raise ValueError("Assessment reason codes must be unique")
    if len(set(assessment.impact_codes)) != len(assessment.impact_codes):
        raise ValueError("Assessment impact codes must be unique")
    if len(set(assessment.blocker_codes)) != len(assessment.blocker_codes):
        raise ValueError("Assessment blocker codes must be unique")
    if assessment.effects:
        raise ValueError("KodiSmartPlaylist Assessment cannot declare Effects")
    if not set(assessment.blocker_codes) <= _BLOCKERS:
        raise ValueError("Assessment has an unknown blocker code")

    operation = assessment.operation_code
    if assessment.relation is DesiredRelation.SATISFIED:
        if (
            assessment.before_digest != assessment.desired_digest
            or operation is not None
            or assessment.reason_codes
            or assessment.impact_codes
            or assessment.blocker_codes
        ):
            raise ValueError("satisfied Assessment is contradictory")
        return
    if assessment.relation is DesiredRelation.NOT_APPLICABLE:
        if (
            operation is not None
            or assessment.reason_codes
            or assessment.impact_codes
            or assessment.blocker_codes
        ):
            raise ValueError("not-applicable Assessment is contradictory")
        return
    if assessment.relation is DesiredRelation.UNVERIFIABLE:
        if (
            operation is not None
            or assessment.reason_codes
            or assessment.impact_codes
            or len(assessment.blocker_codes) != 1
            or assessment.blocker_codes[0] == "resource.observe-only-divergence"
        ):
            raise ValueError("unverifiable Assessment is contradictory")
        return

    if assessment.before_digest == assessment.desired_digest:
        raise ValueError("divergent Assessment digests must differ")
    if assessment.management is ManagementMode.OBSERVE_ONLY:
        if (
            operation is not None
            or assessment.impact_codes
            or assessment.blocker_codes != ("resource.observe-only-divergence",)
        ):
            raise ValueError("observe-only divergent Assessment is contradictory")
    elif assessment.blocker_codes:
        raise ValueError("enforcing divergent Assessment cannot be blocked")

    if operation == "smart_playlist.create":
        if assessment.reason_codes != (
            "playlist.absent",
        ) or assessment.impact_codes != ("content_mutation",):
            raise ValueError("create Assessment is contradictory")
    elif operation == "smart_playlist.remove":
        if assessment.reason_codes != (
            "playlist.desired-absent",
        ) or assessment.impact_codes != ("content_mutation", "removal"):
            raise ValueError("remove Assessment is contradictory")
    elif operation == "smart_playlist.update":
        if (
            assessment.reason_codes not in _UPDATE_REASON_COMBINATIONS
            or assessment.impact_codes != ("content_mutation",)
        ):
            raise ValueError("update Assessment is contradictory")
    elif assessment.management is ManagementMode.ENFORCE:
        raise ValueError("divergent enforcing Assessment requires an operation")
    elif assessment.reason_codes not in _UPDATE_REASON_COMBINATIONS | {
        ("playlist.absent",),
        ("playlist.desired-absent",),
    }:
        raise ValueError("observe-only Assessment reasons are invalid")
