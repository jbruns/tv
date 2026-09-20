"""Production-only resolution of typed secret and pinned-host-key references."""

import base64
import binascii
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import paramiko

from coreelec_reconciler.config.device import SecretValue
from coreelec_reconciler.domain.configuration import SecretReference


class SecretResolutionError(RuntimeError):
    """A safe, redacted composition-seam failure."""


@dataclass(frozen=True, slots=True, repr=False)
class PinnedHostKey:
    algorithm: str
    key: paramiko.PKey

    def __repr__(self) -> str:
        return f"PinnedHostKey(algorithm={self.algorithm!r}, key=<redacted>)"


class HostKeyResolver(Protocol):
    def resolve_host_key(self, reference: str) -> PinnedHostKey: ...


class EnvironmentSecretResolver:
    """Resolve only explicitly supported controller environment references."""

    def __init__(
        self,
        names: Mapping[str, str],
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._names = dict(names)
        self._environment = os.environ if environment is None else environment

    def resolve(self, reference: SecretReference) -> SecretValue:
        if reference.provider != "controller.environment":
            raise SecretResolutionError("secret provider is unsupported")
        variable = self._names.get(reference.key)
        if variable is None:
            raise SecretResolutionError("secret reference is not configured")
        value = self._environment.get(variable)
        if value is None:
            raise SecretResolutionError("secret value is unavailable")
        return SecretValue(value.encode())


class MappingHostKeyResolver:
    """Resolve reviewed OpenSSH public-key lines by opaque reference."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def resolve_host_key(self, reference: str) -> PinnedHostKey:
        value = self._values.get(reference)
        if value is None:
            raise SecretResolutionError("pinned host-key reference is unavailable")
        fields = value.split()
        if len(fields) < 2:
            raise SecretResolutionError("pinned host key is malformed")
        algorithm, encoded = fields[:2]
        try:
            key = paramiko.PKey.from_type_string(
                algorithm, base64.b64decode(encoded, validate=True)
            )
        except ValueError, binascii.Error, paramiko.SSHException:
            raise SecretResolutionError("pinned host key is malformed") from None
        return PinnedHostKey(algorithm, key)
