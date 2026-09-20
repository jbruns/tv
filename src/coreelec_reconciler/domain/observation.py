"""Closed domain vocabulary for canonical observation-only Runs."""

from dataclasses import dataclass
from enum import StrEnum

from coreelec_reconciler.domain.execution import AttachmentRef


class ObservationRunStatus(StrEnum):
    READY = "ready"
    OBSERVING = "observing"
    OBSERVED = "observed"
    OBSERVED_PARTIAL = "observed_partial"


TERMINAL_OBSERVATION_STATUSES = frozenset(
    {
        ObservationRunStatus.OBSERVED,
        ObservationRunStatus.OBSERVED_PARTIAL,
    }
)


class ObservationDisposition(StrEnum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ObservationCodecBinding:
    kind: str
    schema_version: int
    policy_digest: str


@dataclass(frozen=True, slots=True)
class ObservationResourceScope:
    resource_id: str
    resource_type: str
    state_addresses: tuple[str, ...]
    requires: tuple[str, ...]
    codec: ObservationCodecBinding


@dataclass(frozen=True, slots=True)
class ObservationScope:
    configuration_digest: str
    profile_digest: str
    artifact_set_digest: str
    capability_digest: str
    selector_digest: str
    resources: tuple[ObservationResourceScope, ...]


@dataclass(frozen=True, slots=True)
class ObservationCheckpoint:
    sequence: int
    resource_id: str
    resource_type: str
    state_addresses: tuple[str, ...]
    observed_at: str
    observer_code: str
    observer_version: int
    disposition: ObservationDisposition
    payload_kind: str
    payload_schema_version: int
    payload: dict[str, object]
    raw_attachments: tuple[AttachmentRef, ...]


@dataclass(frozen=True, slots=True)
class CanonicalObservationRun:
    canonical_bytes: bytes
    run_id: str
    workspace_id: str
    device_id: str
    current_digest: str
    revision: int
    status: ObservationRunStatus
    scope: ObservationScope
    checkpoints: tuple[ObservationCheckpoint, ...]


@dataclass(frozen=True, slots=True)
class ObservationAppendIntent:
    next_status: ObservationRunStatus
    terminal: bool
