"""Immutable Resource Type descriptors."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.configuration import (
    DesiredPresence,
    KodiSmartPlaylistIntent,
)


@dataclass(frozen=True, slots=True)
class IntentValidationError(Exception):
    path: tuple[str | int, ...]
    safe_message: str


type IntentParser = Callable[
    [Mapping[str, object], DesiredPresence],
    KodiSmartPlaylistIntent,
]
type StateAddressResolver = Callable[
    [KodiSmartPlaylistIntent],
    tuple[str, ...],
]
type IntentEncoder = Callable[[KodiSmartPlaylistIntent], Mapping[str, object]]
type IntentDecoder = Callable[[Mapping[str, object]], KodiSmartPlaylistIntent]


class ErasedResourceExecution(Protocol):
    """Private heterogeneous execution seam; persisted values remain typed."""

    def observe(self) -> object: ...

    def prepare(self, change: object) -> object: ...

    def apply(self, prepared: object) -> object: ...

    def verify(self, prepared: object) -> object: ...

    def rollback(self, prepared: object) -> object: ...


@dataclass(frozen=True, slots=True)
class ResourceDescriptor:
    type_code: str
    parse_intent: IntentParser
    state_addresses: StateAddressResolver
    encode_intent: IntentEncoder
    decode_intent: IntentDecoder
    execution: ErasedResourceExecution | None = None
