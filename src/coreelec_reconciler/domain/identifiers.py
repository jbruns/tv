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
