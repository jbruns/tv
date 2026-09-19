"""Late-bound Device credential resolution at the composition seam."""

from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.configuration import ResolvedDevice, SecretReference


@dataclass(frozen=True, slots=True, repr=False)
class SecretValue:
    value: bytes

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"


class SecretResolver(Protocol):
    def resolve(self, reference: SecretReference) -> SecretValue: ...


@dataclass(frozen=True, slots=True, repr=False)
class DeviceSessionParameters:
    device: ResolvedDevice
    credential: SecretValue

    def __repr__(self) -> str:
        return f"DeviceSessionParameters(device={self.device!r}, credential=<redacted>)"


def resolve_device_session_parameters(
    device: ResolvedDevice,
    resolver: SecretResolver,
) -> DeviceSessionParameters:
    """Resolve a credential only immediately before session construction."""
    return DeviceSessionParameters(
        device, resolver.resolve(device.credential_reference)
    )
