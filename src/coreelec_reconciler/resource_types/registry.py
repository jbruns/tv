"""Closed immutable Resource Type registry."""

from dataclasses import dataclass
from types import MappingProxyType

from coreelec_reconciler.resource_types.descriptor import ResourceDescriptor


@dataclass(frozen=True, slots=True)
class ResourceRegistry:
    descriptors: MappingProxyType[str, ResourceDescriptor]

    @classmethod
    def create(cls, descriptors: tuple[ResourceDescriptor, ...]) -> ResourceRegistry:
        by_code = {descriptor.type_code: descriptor for descriptor in descriptors}
        if len(by_code) != len(descriptors):
            raise ValueError("duplicate Resource Type code")
        return cls(MappingProxyType(by_code))

    def descriptor(self, type_code: str) -> ResourceDescriptor | None:
        return self.descriptors.get(type_code)
