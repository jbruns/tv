"""Frozen authored-configuration domain values."""

from dataclasses import dataclass, field
from enum import StrEnum

from coreelec_reconciler.domain.diagnostics import Diagnostic
from coreelec_reconciler.domain.identifiers import (
    ArtifactId,
    DeviceId,
    ResourceId,
    SelectorId,
)


class ProfileLayer(StrEnum):
    PLATFORM = "platform"
    ROOM = "room"
    DEVICE = "device"


class ManagementMode(StrEnum):
    ENFORCE = "enforce"
    OBSERVE_ONLY = "observe-only"


class DesiredPresence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class SecretReference:
    provider: str
    key: str


@dataclass(frozen=True, slots=True)
class DeviceEndpoint:
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class ResolvedDevice:
    """Validated connection policy; deliberately contains no secret value."""

    id: DeviceId
    endpoint: DeviceEndpoint
    ssh_username: str
    host_key_reference: str
    credential_reference: SecretReference


@dataclass(frozen=True, slots=True)
class PlaylistRule:
    field: str
    operator: str
    value: int | str


@dataclass(frozen=True, slots=True)
class PlaylistOrder:
    by: str
    direction: str


@dataclass(frozen=True, slots=True)
class PlaylistDefinition:
    id: str
    media_type: str
    display_name: str | None
    match: str | None
    limit: int | None
    rules: tuple[PlaylistRule, ...]
    order: PlaylistOrder | None


@dataclass(frozen=True, slots=True)
class KodiSmartPlaylistIntent:
    playlist: PlaylistDefinition
    file_mode: str | None


type ResourceIntent = KodiSmartPlaylistIntent


@dataclass(frozen=True, slots=True)
class Resource:
    id: ResourceId
    type: str
    management: ManagementMode
    desired: DesiredPresence
    selectors: tuple[SelectorId, ...]
    requires: tuple[ResourceId, ...]
    intent: ResourceIntent
    origins: tuple[tuple[str, str], ...]
    state_addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Artifact:
    id: ArtifactId
    kind: str
    version: str
    origin_sha256: str
    distribution_sha256: str
    platforms: tuple[str, ...]
    dependencies: tuple[ArtifactId, ...]


@dataclass(frozen=True, slots=True)
class ResolvedConfiguration:
    schema_version: int
    device_id: DeviceId
    profile_ids: tuple[str, ...]
    resources: tuple[Resource, ...]
    dependency_order: tuple[ResourceId, ...]
    artifacts: tuple[Artifact, ...]
    secret_references: tuple[SecretReference, ...]
    device: ResolvedDevice | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class ConfigurationLoadResult:
    configuration: ResolvedConfiguration | None
    diagnostics: tuple[Diagnostic, ...]
