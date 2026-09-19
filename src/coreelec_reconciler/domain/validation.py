"""Validation shared by strict domain codecs and input adapters."""

import re
import uuid
from datetime import datetime

_MODE = re.compile(r"0[0-7]{3}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_LOGICAL_ID = re.compile(
    r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
)


def require_rfc3339_utc(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be RFC 3339 UTC")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError(f"{label} must be RFC 3339 UTC") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError(f"{label} must be RFC 3339 UTC")
    return value


def require_file_mode(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _MODE.fullmatch(value) is None:
        raise ValueError("observation mode is invalid")
    return value


def require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value


def require_uuid7(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be UUIDv7")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{label} must be UUIDv7") from error
    if parsed.version != 7 or str(parsed) != value:
        raise ValueError(f"{label} must be UUIDv7")
    return value


def require_logical_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _LOGICAL_ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a logical ID")
    return value


def parse_rfc3339_utc(value: object, label: str) -> datetime:
    timestamp = require_rfc3339_utc(value, label)
    return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
