"""Evidence-only strict YAML and Pydantic boundary."""

from collections.abc import Callable, Mapping
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from coreelec_reconciler.domain import Profile, Resource
from coreelec_reconciler.planning import validate_acyclic, validate_references


class StrictLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: StrictLoader, node: MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


class ResourceInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    id: StrictStr
    dependencies: list[StrictStr] = []


class ProfileInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: StrictInt
    resources: list[ResourceInput]


def _parse_one_mapping(text: str) -> Mapping[str, Any]:
    documents = list(yaml.load_all(text, Loader=StrictLoader))
    if len(documents) != 1:
        raise ValueError("exactly one YAML document is required")
    document = documents[0]
    if not isinstance(document, Mapping):
        raise ValueError("Profile root must be a mapping")
    return document


def load_profile(text: str) -> Profile:
    boundary = ProfileInput.model_validate(_parse_one_mapping(text), strict=True)
    if boundary.schema_version != 1:
        raise ValueError(f"unsupported schema version: {boundary.schema_version}")
    resources = tuple(
        Resource(resource_id=item.id, dependencies=tuple(item.dependencies))
        for item in boundary.resources
    )
    if len({resource.resource_id for resource in resources}) != len(resources):
        raise ValueError("duplicate Resource IDs are not supported")
    validate_references(resources)
    validate_acyclic(resources)
    return Profile(schema_version=boundary.schema_version, resources=resources)


def validate_then_connect[TransportT](
    text: str, transport_factory: Callable[[], TransportT]
) -> tuple[Profile, TransportT]:
    profile = load_profile(text)
    return profile, transport_factory()
