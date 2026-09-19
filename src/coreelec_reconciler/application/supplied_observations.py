"""Strict loader for bounded, offline planning inputs."""

import re
import uuid
from collections.abc import Mapping
from pathlib import Path

from coreelec_reconciler.domain.planning import (
    PlanningRuntime,
    SuppliedPlanningInput,
)
from coreelec_reconciler.domain.validation import (
    require_rfc3339_utc,
)
from coreelec_reconciler.reporting.canonical_json import decode_json_object
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning_codecs import (
    decode_observation,
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def _time(value: object, label: str) -> str:
    return require_rfc3339_utc(value, label)


def _uuid7(value: object, label: str) -> str:
    text = _string(value, label)
    parsed = uuid.UUID(text)
    if parsed.version != 7:
        raise ValueError(f"{label} must be UUIDv7")
    return text


def _digest(value: object, label: str) -> str:
    text = _string(value, label)
    if _DIGEST.fullmatch(text) is None:
        raise ValueError(f"{label} must be a SHA-256 digest")
    return text


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
    return SuppliedPlanningInput(
        runtime=PlanningRuntime(
            planning_run_id=_uuid7(runtime["planning_run_id"], "planning_run_id"),
            plan_id=_uuid7(runtime["plan_id"], "plan_id"),
            started_at=_time(runtime["started_at"], "started_at"),
            created_at=_time(runtime["created_at"], "created_at"),
            ended_at=_time(runtime["ended_at"], "ended_at"),
            expires_at=_time(runtime["expires_at"], "expires_at"),
            endpoint_host=_string(endpoint["host"], "endpoint host"),
            endpoint_port=port,
            ssh_host_key_fingerprint=_string(
                runtime["ssh_host_key_fingerprint"],
                "SSH host-key fingerprint",
            ),
            platform_identity_fingerprint=_digest(
                runtime["platform_identity_fingerprint"],
                "platform identity fingerprint",
            ),
            controller_capabilities_digest=_digest(
                runtime["controller_capabilities_digest"],
                "controller capabilities digest",
            ),
            artifact_resolution_digest=_digest(
                runtime["artifact_resolution_digest"],
                "Artifact resolution digest",
            ),
        ),
        observation=typed_observation,
    )
