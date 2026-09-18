"""Evidence-only canonical JSON golden tests."""

import math

import pytest

from coreelec_reconciler.reporting import JsonValue, canonical_json_bytes


def test_canonical_json_is_byte_for_byte_stable() -> None:
    value: JsonValue = {
        "z": "雪",
        "a": {"b": 2, "a": 1},
        "items": [True, None],
    }
    assert (
        canonical_json_bytes(value)
        == b'{"a":{"a":1,"b":2},"items":[true,null],"z":"\xe9\x9b\xaa"}\n'
    )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_canonical_json_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": value})
