"""Repository-owned canonical JSON byte production."""

import json
from collections.abc import Mapping


def canonical_document_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def decode_json_object(content: bytes) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate canonical field {key}")
            result[key] = value
        return result

    value = json.loads(content, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("canonical document must be an object")
    return value
