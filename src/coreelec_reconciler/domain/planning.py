"""Frozen values for pure observation, planning, and planning Run reports."""

from dataclasses import dataclass
from enum import StrEnum

from coreelec_reconciler.domain.configuration import ManagementMode
from coreelec_reconciler.domain.execution import RunStatus as RunStatus


class Presence(StrEnum):
    ABSENT = "absent"
    PRESENT = "present"


class FileKind(StrEnum):
    ABSENT = "absent"
    REGULAR = "regular"
    SYMLINK = "symlink"
    DIRECTORY = "directory"
    OTHER = "other"


class DesiredRelation(StrEnum):
    SATISFIED = "satisfied"
    DIVERGENT = "divergent"
    NOT_APPLICABLE = "not_applicable"
    UNVERIFIABLE = "unverifiable"


class PlanDisposition(StrEnum):
    NOOP = "noop"
    ACTIONABLE = "actionable"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PlaylistSemanticModel:
    media_type: str
    display_name: str
    match: str
    limit: int
    rules: tuple[tuple[str, str, int | str], ...]
    order: tuple[str, str]


@dataclass(frozen=True, slots=True)
class KodiSmartPlaylistObservation:
    resource_id: str
    state_address: str
    observed_at: str
    kind: FileKind
    mode: str | None
    content: bytes | None


@dataclass(frozen=True, slots=True)
class PlanningRuntime:
    planning_run_id: str
    plan_id: str
    started_at: str
    created_at: str
    ended_at: str
    expires_at: str
    endpoint_host: str
    endpoint_port: int
    ssh_host_key_fingerprint: str
    platform_identity_fingerprint: str
    controller_capabilities_digest: str
    artifact_resolution_digest: str


@dataclass(frozen=True, slots=True)
class SuppliedPlanningInput:
    runtime: PlanningRuntime
    observation: KodiSmartPlaylistObservation


@dataclass(frozen=True, slots=True)
class PlaylistAssessment:
    relation: DesiredRelation
    management: ManagementMode
    operation_code: str | None
    reason_codes: tuple[str, ...]
    impact_codes: tuple[str, ...]
    blocker_codes: tuple[str, ...]
    before_digest: str
    desired_digest: str
    before_summary: tuple[tuple[str, object], ...]
    desired_summary: tuple[tuple[str, object], ...]
    effects: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalPlan:
    canonical_bytes: bytes
    plan_id: str
    full_digest: str
    semantic_digest: str
    disposition: PlanDisposition


@dataclass(frozen=True, slots=True)
class CanonicalRunReport:
    canonical_bytes: bytes
    run_id: str
    current_digest: str
    revision: int
    status: RunStatus
