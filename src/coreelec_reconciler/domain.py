"""Evidence-only standard-library domain values."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Resource:
    resource_id: str
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Profile:
    schema_version: int
    resources: tuple[Resource, ...]
