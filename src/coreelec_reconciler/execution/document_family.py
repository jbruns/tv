"""Opaque canonical document-family operations used by RunStore."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.execution import AttachmentRef, StoredRevision


@dataclass(frozen=True, slots=True)
class DocumentRevision:
    stored: StoredRevision
    run_id: str
    workspace_id: str
    device_id: str
    status: str
    terminal: bool
    authority_phase: str | None
    identity: Mapping[str, object]
    attachments: tuple[AttachmentRef, ...]
    decoded: object


class DocumentAppendIntent(Protocol):
    @property
    def next_status(self) -> object: ...

    @property
    def terminal(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class SessionCloseBinding:
    schema_version: int
    authority_state: str
    seal_digest: str | None
    run_kind: str | None


class RunDocumentFamily(Protocol):
    kind: str
    identity_fields: frozenset[str]
    requires_ownership_token: bool
    uses_active_index: bool

    def decode_revision(self, payload: bytes) -> DocumentRevision: ...

    def verify_chain(
        self, payloads: tuple[bytes, ...]
    ) -> tuple[DocumentRevision, ...]: ...

    def validate_initial(
        self,
        payload: bytes,
        *,
        run_id: str,
        workspace_id: str,
        device_id: str,
    ) -> DocumentRevision: ...

    def validate_append(
        self,
        current_payloads: tuple[bytes, ...],
        proposed_payload: bytes,
        *,
        next_status: str,
        terminal: bool,
    ) -> DocumentRevision: ...

    def session_close_binding(
        self,
        revision: DocumentRevision,
    ) -> SessionCloseBinding: ...
