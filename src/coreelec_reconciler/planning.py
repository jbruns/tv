"""Evidence-only pure dependency-graph validation."""

from collections.abc import Mapping, Sequence

from coreelec_reconciler.domain import Resource


def validate_references(resources: Sequence[Resource]) -> None:
    identifiers = {resource.resource_id for resource in resources}
    for resource in resources:
        missing = set(resource.dependencies) - identifiers
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"{resource.resource_id} has missing references: {names}")


def validate_acyclic(resources: Sequence[Resource]) -> None:
    graph: Mapping[str, tuple[str, ...]] = {
        resource.resource_id: resource.dependencies for resource in resources
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(resource_id: str) -> None:
        if resource_id in visiting:
            raise ValueError(f"dependency cycle includes {resource_id}")
        if resource_id in visited:
            return
        visiting.add(resource_id)
        for dependency in graph[resource_id]:
            visit(dependency)
        visiting.remove(resource_id)
        visited.add(resource_id)

    for resource_id in graph:
        visit(resource_id)
