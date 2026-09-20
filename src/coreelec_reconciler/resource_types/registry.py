"""Closed immutable Resource Type registry."""

import re
from dataclasses import dataclass
from types import MappingProxyType

from coreelec_reconciler.resource_types.descriptor import ResourceDescriptor

_TYPE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ResourceRegistry:
    descriptors: MappingProxyType[str, ResourceDescriptor]

    @classmethod
    def create(cls, descriptors: tuple[ResourceDescriptor, ...]) -> ResourceRegistry:
        if any(_TYPE_CODE.fullmatch(item.type_code) is None for item in descriptors):
            raise ValueError("invalid Resource Type code")
        by_code = {descriptor.type_code: descriptor for descriptor in descriptors}
        if len(by_code) != len(descriptors):
            raise ValueError("duplicate Resource Type code")
        return cls(MappingProxyType(by_code))

    def descriptor(self, type_code: str) -> ResourceDescriptor | None:
        return self.descriptors.get(type_code)

    @property
    def type_codes(self) -> frozenset[str]:
        return frozenset(self.descriptors)
