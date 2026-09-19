"""Strict Pydantic models confined to the authored input boundary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, model_validator


class _InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SecretReferenceInput(_InputModel):
    type: Literal["secret"]
    provider: StrictStr
    key: StrictStr


class EndpointInput(_InputModel):
    host: StrictStr
    port: StrictInt


class HostKeyInput(_InputModel):
    policy: Literal["pinned"]
    reference: StrictStr


class SshInput(_InputModel):
    username: StrictStr
    host_key: HostKeyInput
    credential: SecretReferenceInput


class ProfileSelectionInput(_InputModel):
    platform: StrictStr
    room: StrictStr | None = None
    device: StrictStr | None = None


class DeviceInput(_InputModel):
    id: StrictStr
    endpoint: EndpointInput
    ssh: SshInput
    profiles: ProfileSelectionInput


class DeviceInventoryInput(_InputModel):
    kind: Literal["DeviceInventory"]
    schema_version: StrictInt
    devices: list[DeviceInput]


class ResourceInput(_InputModel):
    id: StrictStr
    type: StrictStr
    management: Literal["enforce", "observe-only"]
    desired: Literal["present", "absent"]
    selectors: list[StrictStr]
    requires: list[StrictStr]
    intent: dict[StrictStr, object]


class ProfileInput(_InputModel):
    kind: Literal["Profile"]
    schema_version: StrictInt
    id: StrictStr
    layer: Literal["platform", "room", "device"]
    resources: list[ResourceInput]


class SecretKeyInput(_InputModel):
    variable: StrictStr


class SecretProviderInput(_InputModel):
    id: StrictStr
    type: Literal["environment"]
    keys: dict[StrictStr, SecretKeyInput]


class SecretProviderCatalogInput(_InputModel):
    kind: Literal["SecretProviderCatalog"]
    schema_version: StrictInt
    providers: list[SecretProviderInput]


class ArtifactDependencyInput(_InputModel):
    id: StrictStr
    minimum_version: StrictStr


class ArtifactOriginInput(_InputModel):
    adapter: Literal["github-release-asset"]
    project: StrictStr
    retrieval_url: StrictStr
    mutable: Literal[False]
    sha256: StrictStr
    tag: StrictStr
    commit: StrictStr
    release_id: StrictInt
    asset_id: StrictInt


class ArtifactDistributionInput(_InputModel):
    relation: Literal["direct-origin-bytes"]
    owner: Literal["upstream"]
    asset: StrictStr
    immutable_release: Literal[True]
    sha256: StrictStr
    release_id: StrictInt
    asset_id: StrictInt


class ArtifactReleaseInput(_InputModel):
    channel: Literal["stable"]


class ArtifactInput(_InputModel):
    id: StrictStr
    kind: Literal["kodi-addon"]
    version: StrictStr
    origin: ArtifactOriginInput
    distribution: ArtifactDistributionInput
    release: ArtifactReleaseInput
    platforms: list[StrictStr]
    dependencies: list[ArtifactDependencyInput]

    @model_validator(mode="after")
    def reject_dependencies_until_consumed(self) -> ArtifactInput:
        if self.dependencies:
            raise ValueError(
                "Artifact dependencies are not supported by the M2 playlist slice."
            )
        return self


class ArtifactCatalogInput(_InputModel):
    kind: Literal["ArtifactCatalog"]
    schema_version: StrictInt
    artifacts: list[ArtifactInput]
