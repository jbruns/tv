"""Shared remote Run ownership port and typed failures."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from coreelec_reconciler.domain.execution import MutationReceipt


class RemoteObjectKind(StrEnum):
    ABSENT = "absent"
    REGULAR = "regular"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RemoteObject:
    kind: RemoteObjectKind
    payload: bytes | None = None


class RemoteAuthorityBackend(Protocol):
    def inspect_ownership(self, device_key: str) -> RemoteObject: ...

    def inspect_quarantine(self, device_key: str) -> RemoteObject: ...

    def create_ownership_if_unowned_and_not_quarantined(
        self,
        device_key: str,
        payload: bytes,
        expected_digest: str,
    ) -> None: ...

    def replace_ownership(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None: ...

    def remove_ownership(
        self,
        device_key: str,
        expected_digest: str,
        terminal_receipt_digest: str,
    ) -> MutationReceipt: ...

    def convert_to_quarantine(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None: ...


class AuthorityError(RuntimeError):
    pass


class AuthorityBlocked(AuthorityError):
    pass


class AuthorityConflict(AuthorityError):
    pass
