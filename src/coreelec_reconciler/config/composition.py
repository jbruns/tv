"""Fixed Profile composition with field provenance."""

from collections.abc import Mapping
from dataclasses import dataclass

from coreelec_reconciler.config.input_models import ProfileInput, ResourceInput
from coreelec_reconciler.domain.diagnostics import Diagnostic


@dataclass(frozen=True, slots=True)
class ProfileDocument:
    source: str
    model: ProfileInput


@dataclass(frozen=True, slots=True)
class ComposedResource:
    source: str
    value: dict[str, object]
    origins: dict[str, str]


@dataclass(frozen=True, slots=True)
class CompositionResult:
    resources: dict[str, ComposedResource]
    diagnostics: tuple[Diagnostic, ...]


def _leaf_paths(value: object, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_leaf_paths(value[key], child))
        return tuple(paths)
    return (prefix,)


def _merge_mapping(
    base: dict[str, object],
    overlay: Mapping[str, object],
) -> dict[str, object]:
    result = dict(base)
    for key, value in overlay.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            result[key] = _merge_mapping(current, value)
        else:
            result[key] = value
    return result


def _resource_mapping(resource: ResourceInput) -> dict[str, object]:
    dumped = resource.model_dump(mode="python", exclude_none=True)
    if not isinstance(dumped, dict):
        raise TypeError("Resource model did not produce a mapping")
    return dumped


def compose_profiles(profiles: tuple[ProfileDocument, ...]) -> CompositionResult:
    resources: dict[str, ComposedResource] = {}
    diagnostics: list[Diagnostic] = []
    for document in profiles:
        for resource in document.model.resources:
            incoming = _resource_mapping(resource)
            existing = resources.get(resource.id)
            if existing is None:
                origins = {
                    path: document.source
                    for path in _leaf_paths(incoming)
                    if path != "id"
                }
                resources[resource.id] = ComposedResource(
                    source=document.source,
                    value=incoming,
                    origins=origins,
                )
                continue
            if existing.value["type"] != incoming["type"]:
                diagnostics.append(
                    Diagnostic(
                        source=document.source,
                        line=1,
                        column=1,
                        path=("resources", resource.id, "type"),
                        code="composition.type-conflict",
                        message=(
                            f"Resource {resource.id} cannot change type across layers."
                        ),
                        subject_id=resource.id,
                    )
                )
                continue
            merged = _merge_mapping(existing.value, incoming)
            origins = dict(existing.origins)
            for path in _leaf_paths(incoming):
                if path != "id":
                    origins[path] = document.source
            resources[resource.id] = ComposedResource(
                source=document.source,
                value=merged,
                origins=origins,
            )
    return CompositionResult(resources=resources, diagnostics=tuple(diagnostics))
