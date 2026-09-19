"""Validation shared by strict domain codecs and input adapters."""

import re
from datetime import datetime

_MODE = re.compile(r"0[0-7]{3}")


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
