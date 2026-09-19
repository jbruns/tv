"""Strict loader for bounded, offline planning inputs."""

import base64
import re
import uuid
from collections.abc import Mapping
from pathlib import Path

from coreelec_reconciler.domain.planning import (
    FileKind,
    KodiSmartPlaylistObservation,
    PlanningRuntime,
    SuppliedPlanningInput,
)
from coreelec_reconciler.reporting.canonical_json import decode_json_object

_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_CONTENT_BYTES = 65536


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
    timestamp = _string(value, label)
    if _TIME.fullmatch(timestamp) is None:
        raise ValueError(f"{label} must be RFC 3339 UTC")
    return timestamp


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
    kind = FileKind(_string(observation["kind"], "observation kind"))
    mode_value = observation["mode"]
    mode = None if mode_value is None else _string(mode_value, "observation mode")
    if mode is not None and re.fullmatch(r"0[0-7]{3}", mode) is None:
        raise ValueError("observation mode is invalid")
    encoded = observation["content_base64"]
    if encoded is None:
        decoded = None
    else:
        try:
            decoded = base64.b64decode(
                _string(encoded, "observation content"),
                validate=True,
            )
        except ValueError as error:
            raise ValueError("observation content is not base64") from error
        if len(decoded) > _MAX_CONTENT_BYTES:
            raise ValueError("observation content exceeds the safe limit")
    if kind is FileKind.ABSENT and (mode is not None or decoded is not None):
        raise ValueError("absent observation cannot contain file state")
    if kind is FileKind.REGULAR and mode is None:
        raise ValueError("regular observation requires mode")
    if kind not in {FileKind.ABSENT, FileKind.REGULAR} and decoded is not None:
        raise ValueError("unsafe observations cannot contain raw content")
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
        observation=KodiSmartPlaylistObservation(
            resource_id=_string(observation["resource_id"], "resource_id"),
            state_address=_string(observation["state_address"], "state_address"),
            observed_at=_time(observation["observed_at"], "observed_at"),
            kind=kind,
            mode=mode,
            content=decoded,
        ),
    )
