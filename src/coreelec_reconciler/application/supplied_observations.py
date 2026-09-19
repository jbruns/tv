"""Strict loader for bounded, offline planning inputs."""

from collections.abc import Mapping
from pathlib import Path

from coreelec_reconciler.domain.planning import (
    PlanningRuntime,
    SuppliedPlanningInput,
)
from coreelec_reconciler.domain.validation import (
    parse_rfc3339_utc,
    require_sha256,
    require_uuid7,
)
from coreelec_reconciler.reporting.canonical_json import decode_json_object
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning_codecs import (
    decode_observation,
)


def _object(
    value: object,
    keys: set[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"unknown or missing {label} fields")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def load_supplied_planning_input(path: str | Path) -> SuppliedPlanningInput:
    try:
        content = Path(path).read_bytes()
    except OSError as error:
        raise ValueError("supplied observations could not be read") from error
    raw = decode_json_object(content)
    if set(raw) != {"kind", "observation", "runtime", "schema_version"}:
        raise ValueError("unknown or missing supplied observation fields")
    if raw["kind"] != "CoreElecSuppliedPlanningInput" or raw["schema_version"] != 1:
        raise ValueError("unsupported supplied observation document")
    runtime = _object(
        raw["runtime"],
        {
            "artifact_resolution_digest",
            "controller_capabilities_digest",
            "created_at",
            "ended_at",
            "endpoint",
            "expires_at",
            "plan_id",
            "planning_run_id",
            "platform_identity_fingerprint",
            "ssh_host_key_fingerprint",
            "started_at",
        },
        "runtime",
    )
    endpoint = _object(runtime["endpoint"], {"host", "port"}, "endpoint")
    port = endpoint["port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("endpoint port is invalid")
    observation = _object(
        raw["observation"],
        {
            "content_base64",
            "kind",
            "mode",
            "observed_at",
            "resource_id",
            "state_address",
        },
        "observation",
    )
    typed_observation = decode_observation(
        {
            "payload": dict(observation),
            "payload_kind": "KodiSmartPlaylistObservation",
            "payload_schema_version": 1,
        }
    )
    planning_run_id = require_uuid7(runtime["planning_run_id"], "planning_run_id")
    plan_id = require_uuid7(runtime["plan_id"], "plan_id")
    if plan_id == planning_run_id:
        raise ValueError("plan_id and planning_run_id must differ")
    started_at = parse_rfc3339_utc(runtime["started_at"], "started_at")
    observed_at = parse_rfc3339_utc(
        typed_observation.observed_at,
        "observed_at",
    )
    created_at = parse_rfc3339_utc(runtime["created_at"], "created_at")
    ended_at = parse_rfc3339_utc(runtime["ended_at"], "ended_at")
    expires_at = parse_rfc3339_utc(runtime["expires_at"], "expires_at")
    if not started_at <= observed_at <= created_at <= ended_at < expires_at:
        raise ValueError(
            "planning timestamps must satisfy "
            "started_at <= observed_at <= created_at <= ended_at < expires_at"
        )
    return SuppliedPlanningInput(
        runtime=PlanningRuntime(
            planning_run_id=planning_run_id,
            plan_id=plan_id,
            started_at=str(runtime["started_at"]),
            created_at=str(runtime["created_at"]),
            ended_at=str(runtime["ended_at"]),
            expires_at=str(runtime["expires_at"]),
            endpoint_host=_string(endpoint["host"], "endpoint host"),
            endpoint_port=port,
            ssh_host_key_fingerprint=_string(
                runtime["ssh_host_key_fingerprint"],
                "SSH host-key fingerprint",
            ),
            platform_identity_fingerprint=require_sha256(
                runtime["platform_identity_fingerprint"],
                "platform identity fingerprint",
            ),
            controller_capabilities_digest=require_sha256(
                runtime["controller_capabilities_digest"],
                "controller capabilities digest",
            ),
            artifact_resolution_digest=require_sha256(
                runtime["artifact_resolution_digest"],
                "Artifact resolution digest",
            ),
        ),
        observation=typed_observation,
    )
