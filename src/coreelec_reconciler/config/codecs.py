"""Canonical codecs for frozen configuration domain values."""

import json
from collections.abc import Mapping

from coreelec_reconciler.domain.configuration import (
    Artifact,
    DesiredPresence,
    ManagementMode,
    ResolvedConfiguration,
    Resource,
    SecretReference,
)
from coreelec_reconciler.domain.identifiers import (
    ArtifactId,
    DeviceId,
    ResourceId,
    SelectorId,
)
from coreelec_reconciler.resource_types.builtins import (
    built_in_resource_registry,
)


def _resource_to_value(resource: Resource) -> dict[str, object]:
    descriptor = built_in_resource_registry().descriptor(resource.type)
    if descriptor is None:
        raise ValueError(f"unknown Resource Type {resource.type}")
    return {
        "desired": resource.desired.value,
        "id": resource.id.value,
        "intent": descriptor.encode_intent(resource.intent),
        "management": resource.management.value,
        "origins": dict(resource.origins),
        "requires": [item.value for item in resource.requires],
        "selectors": [item.value for item in resource.selectors],
        "state_addresses": list(resource.state_addresses),
        "type": resource.type,
    }


def encode_resolved_configuration(configuration: ResolvedConfiguration) -> bytes:
    value = {
        "artifacts": [
            {
                "dependencies": [item.value for item in artifact.dependencies],
                "distribution_sha256": artifact.distribution_sha256,
                "id": artifact.id.value,
                "kind": artifact.kind,
                "origin_sha256": artifact.origin_sha256,
                "platforms": list(artifact.platforms),
                "version": artifact.version,
            }
            for artifact in configuration.artifacts
        ],
        "dependency_order": [item.value for item in configuration.dependency_order],
        "device_id": configuration.device_id.value,
        "kind": "CoreElecResolvedConfiguration",
        "profile_ids": list(configuration.profile_ids),
        "resources": [
            _resource_to_value(resource) for resource in configuration.resources
        ],
        "schema_version": configuration.schema_version,
        "secret_references": [
            {"key": item.key, "provider": item.provider}
            for item in configuration.secret_references
        ],
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _required_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError("canonical value must be an object")
    return value


def _required_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("canonical value must be an array")
    return value


def _required_str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("canonical value must be a string")
    return value


def decode_resolved_configuration(content: bytes) -> ResolvedConfiguration:
    def reject_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate canonical field {key}")
            result[key] = value
        return result

    raw = _required_mapping(
        json.loads(content, object_pairs_hook=reject_duplicate_keys)
    )
    if set(raw) != {
        "artifacts",
        "dependency_order",
        "device_id",
        "kind",
        "profile_ids",
        "resources",
        "schema_version",
        "secret_references",
    }:
        raise ValueError("unknown or missing canonical fields")
    if raw["kind"] != "CoreElecResolvedConfiguration" or raw["schema_version"] != 1:
        raise ValueError("unsupported resolved configuration")
    resources: list[Resource] = []
    for item in _required_list(raw["resources"]):
        resource = _required_mapping(item)
        if set(resource) != {
            "desired",
            "id",
            "intent",
            "management",
            "origins",
            "requires",
            "selectors",
            "state_addresses",
            "type",
        }:
            raise ValueError("unknown or missing Resource fields")
        type_code = _required_str(resource["type"])
        descriptor = built_in_resource_registry().descriptor(type_code)
        if descriptor is None:
            raise ValueError(f"unknown Resource Type {type_code}")
        resources.append(
            Resource(
                id=ResourceId(_required_str(resource["id"])),
                type=type_code,
                management=ManagementMode(_required_str(resource["management"])),
                desired=DesiredPresence(_required_str(resource["desired"])),
                selectors=tuple(
                    SelectorId(_required_str(value))
                    for value in _required_list(resource["selectors"])
                ),
                requires=tuple(
                    ResourceId(_required_str(value))
                    for value in _required_list(resource["requires"])
                ),
                intent=descriptor.decode_intent(_required_mapping(resource["intent"])),
                origins=tuple(
                    sorted(
                        (
                            _required_str(key),
                            _required_str(value),
                        )
                        for key, value in _required_mapping(resource["origins"]).items()
                    )
                ),
                state_addresses=tuple(
                    _required_str(value)
                    for value in _required_list(resource["state_addresses"])
                ),
            )
        )
    artifacts = tuple(
        Artifact(
            id=ArtifactId(_required_str(artifact["id"])),
            kind=_required_str(artifact["kind"]),
            version=_required_str(artifact["version"]),
            origin_sha256=_required_str(artifact["origin_sha256"]),
            distribution_sha256=_required_str(artifact["distribution_sha256"]),
            platforms=tuple(
                _required_str(value) for value in _required_list(artifact["platforms"])
            ),
            dependencies=tuple(
                ArtifactId(_required_str(value))
                for value in _required_list(artifact["dependencies"])
            ),
        )
        for value in _required_list(raw["artifacts"])
        if (artifact := _required_mapping(value))
    )
    configuration = ResolvedConfiguration(
        schema_version=1,
        device_id=DeviceId(_required_str(raw["device_id"])),
        profile_ids=tuple(
            _required_str(value) for value in _required_list(raw["profile_ids"])
        ),
        resources=tuple(resources),
        dependency_order=tuple(
            ResourceId(_required_str(value))
            for value in _required_list(raw["dependency_order"])
        ),
        artifacts=artifacts,
        secret_references=tuple(
            SecretReference(
                provider=_required_str(_required_mapping(value)["provider"]),
                key=_required_str(_required_mapping(value)["key"]),
            )
            for value in _required_list(raw["secret_references"])
        ),
    )
    if encode_resolved_configuration(configuration) != content:
        raise ValueError("resolved configuration bytes are not canonical")
    return configuration
