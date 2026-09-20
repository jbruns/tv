"""Closed observation-Run evidence codec for Kodi Smart Playlists."""

import hashlib
import re
from collections.abc import Mapping

from coreelec_reconciler.domain.validation import require_sha256

OBSERVATION_PAYLOAD_KIND = "KodiSmartPlaylistObservationResult"
OBSERVATION_PAYLOAD_VERSION = 1
OBSERVATION_POLICY_ID = "kodi-smart-playlist-observation-policy-v1"
OBSERVATION_POLICY_DIGEST = (
    "sha256:" + hashlib.sha256(OBSERVATION_POLICY_ID.encode()).hexdigest()
)

_FIELDS = {
    "availability",
    "content_digest",
    "entry_type",
    "failure_code",
    "mode",
    "presence",
    "readability",
    "safety",
}
_PRESENCE = {"absent", "present", "unknown"}
_READABILITY = {"not_applicable", "readable", "unreadable", "unknown"}
_ENTRY_TYPES = {"directory", "other", "regular", "symlink", "unknown"}
_SAFETY = {"safe", "unsafe", "unknown"}
_AVAILABILITY = {"available", "unavailable", "unknown"}
_STATE_ADDRESS = re.compile(r"special://profile/playlists/video/[A-Za-z0-9._-]+\.xsp")


def validate_observation_addresses(addresses: tuple[str, ...]) -> None:
    if len(addresses) != 1 or _STATE_ADDRESS.fullmatch(addresses[0]) is None:
        raise ValueError("invalid Kodi Smart Playlist observation State Address")


def check_observation_addresses(addresses: tuple[str, ...]) -> tuple[str, ...]:
    if len(addresses) != 1 or _STATE_ADDRESS.fullmatch(addresses[0]) is None:
        return ("oracle: invalid Kodi Smart Playlist observation State Address",)
    return ()


def decode_observation_run_payload(
    payload_kind: str,
    schema_version: int,
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Validate and normalize one persisted playlist observation result."""
    if (
        payload_kind != OBSERVATION_PAYLOAD_KIND
        or schema_version != OBSERVATION_PAYLOAD_VERSION
    ):
        raise ValueError("unsupported observation payload codec")
    _validate_payload(payload)
    return dict(payload)


def check_observation_run_payload(
    payload_kind: object,
    schema_version: object,
    payload: object,
) -> tuple[str, ...]:
    """Independently check the built-in payload without calling the decoder."""
    errors: list[str] = []
    if payload_kind != OBSERVATION_PAYLOAD_KIND:
        errors.append("oracle: unsupported observation payload kind")
    if type(schema_version) is not int or schema_version != 1:
        errors.append("oracle: unsupported observation payload version")
    if not isinstance(payload, dict):
        return (*errors, "oracle: observation payload is not an object")
    if set(payload) != _FIELDS:
        errors.append("oracle: unknown or missing observation payload fields")
        return tuple(errors)
    if not isinstance(payload["presence"], str) or payload["presence"] not in _PRESENCE:
        errors.append("oracle: invalid observation presence")
    if (
        not isinstance(payload["readability"], str)
        or payload["readability"] not in _READABILITY
    ):
        errors.append("oracle: invalid observation readability")
    if payload["entry_type"] is not None and (
        not isinstance(payload["entry_type"], str)
        or payload["entry_type"] not in _ENTRY_TYPES
    ):
        errors.append("oracle: invalid observation entry type")
    if not isinstance(payload["safety"], str) or payload["safety"] not in _SAFETY:
        errors.append("oracle: invalid observation safety")
    if (
        not isinstance(payload["availability"], str)
        or payload["availability"] not in _AVAILABILITY
    ):
        errors.append("oracle: invalid observation availability")
    _check_shape(payload, errors, "oracle: ")
    return tuple(errors)


def _validate_payload(payload: Mapping[str, object]) -> None:
    if set(payload) != _FIELDS:
        raise ValueError("unknown or missing observation payload fields")
    if not isinstance(payload["presence"], str) or payload["presence"] not in _PRESENCE:
        raise ValueError("invalid observation presence")
    if (
        not isinstance(payload["readability"], str)
        or payload["readability"] not in _READABILITY
    ):
        raise ValueError("invalid observation readability")
    if payload["entry_type"] is not None and (
        not isinstance(payload["entry_type"], str)
        or payload["entry_type"] not in _ENTRY_TYPES
    ):
        raise ValueError("invalid observation entry type")
    if not isinstance(payload["safety"], str) or payload["safety"] not in _SAFETY:
        raise ValueError("invalid observation safety")
    if (
        not isinstance(payload["availability"], str)
        or payload["availability"] not in _AVAILABILITY
    ):
        raise ValueError("invalid observation availability")
    errors: list[str] = []
    _check_shape(payload, errors, "")
    if errors:
        raise ValueError(errors[0])


def _check_shape(
    payload: Mapping[str, object],
    errors: list[str],
    prefix: str,
) -> None:
    content_digest = payload["content_digest"]
    mode = payload["mode"]
    failure_code = payload["failure_code"]
    if content_digest is not None:
        try:
            require_sha256(content_digest, "observation content_digest")
        except TypeError, ValueError:
            errors.append(f"{prefix}invalid observation content digest")
    if mode is not None and (type(mode) is not int or mode < 0 or mode > 0o7777):
        errors.append(f"{prefix}invalid observation mode")
    if failure_code is not None and (
        not isinstance(failure_code, str)
        or not failure_code
        or len(failure_code) > 128
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in failure_code
        )
    ):
        errors.append(f"{prefix}invalid observation failure code")

    availability = payload["availability"]
    presence = payload["presence"]
    readability = payload["readability"]
    entry_type = payload["entry_type"]
    safety = payload["safety"]
    if (
        not isinstance(availability, str)
        or not isinstance(presence, str)
        or not isinstance(readability, str)
        or not isinstance(safety, str)
        or (entry_type is not None and not isinstance(entry_type, str))
    ):
        return
    if availability == "available":
        if presence == "absent":
            if (
                readability != "not_applicable"
                or entry_type is not None
                or safety != "safe"
                or content_digest is not None
                or mode is not None
                or failure_code is not None
            ):
                errors.append(f"{prefix}absent observation is contradictory")
        elif presence == "present":
            if entry_type == "regular":
                readable = (
                    readability == "readable"
                    and safety == "safe"
                    and content_digest is not None
                    and mode is not None
                    and failure_code is None
                )
                unreadable = (
                    readability == "unreadable"
                    and safety == "safe"
                    and content_digest is None
                    and failure_code is not None
                )
                if not (readable or unreadable):
                    errors.append(f"{prefix}regular observation is incomplete")
            elif entry_type != "regular" and (
                entry_type not in {"directory", "other", "symlink"}
                or readability != "not_applicable"
                or safety != "unsafe"
                or content_digest is not None
                or mode is not None
            ):
                errors.append(f"{prefix}unsafe observation is contradictory")
        else:
            errors.append(f"{prefix}available observation has unknown presence")
    elif availability in {"unavailable", "unknown"} and (
        presence != "unknown"
        or readability != "unknown"
        or entry_type != "unknown"
        or safety != "unknown"
        or content_digest is not None
        or mode is not None
        or failure_code is None
    ):
        errors.append(f"{prefix}incomplete observation is contradictory")
