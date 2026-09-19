"""Stable domain identifiers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceId:
    value: str


@dataclass(frozen=True, slots=True)
class PlanId:
    value: str


@dataclass(frozen=True, slots=True)
class RunId:
    value: str


@dataclass(frozen=True, slots=True)
class ProfileId:
    value: str


@dataclass(frozen=True, slots=True)
class ResourceId:
    value: str


@dataclass(frozen=True, slots=True)
class ArtifactId:
    value: str


@dataclass(frozen=True, slots=True)
class SelectorId:
    value: str
