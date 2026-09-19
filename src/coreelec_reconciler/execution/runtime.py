"""Injected runtime values for reproducible execution."""

import secrets
import uuid
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol


class RuntimeValues(Protocol):
    def utc_now(self) -> str: ...

    def new_uuid7(self) -> str: ...

    def new_ownership_token(self) -> bytes: ...


class SystemRuntimeValues:
    def utc_now(self) -> str:
        return (
            datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )

    def new_uuid7(self) -> str:
        return str(uuid.uuid7())

    def new_ownership_token(self) -> bytes:
        return secrets.token_bytes(32)


class FiniteRuntimeValues:
    """Finite queues fail loudly instead of hiding nondeterminism in tests."""

    def __init__(
        self,
        *,
        utc_instants: Iterable[str] = (),
        uuid7_values: Iterable[str] = (),
        ownership_tokens: Iterable[bytes] = (),
    ) -> None:
        self._times = deque(utc_instants)
        self._uuids = deque(uuid7_values)
        self._tokens = deque(ownership_tokens)

    def utc_now(self) -> str:
        if not self._times:
            raise RuntimeError("UTC instant queue exhausted")
        return self._times.popleft()

    def new_uuid7(self) -> str:
        if not self._uuids:
            raise RuntimeError("UUIDv7 queue exhausted")
        return self._uuids.popleft()

    def new_ownership_token(self) -> bytes:
        if not self._tokens:
            raise RuntimeError("ownership token queue exhausted")
        return self._tokens.popleft()
