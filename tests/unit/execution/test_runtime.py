import pytest

from coreelec_reconciler.execution.runtime import FiniteRuntimeValues


def test_finite_runtime_values_are_deterministic_and_exhaustible() -> None:
    runtime = FiniteRuntimeValues(
        utc_instants=["2026-09-19T08:00:00Z"],
        uuid7_values=["019950f8-4c00-7000-8000-000000000601"],
        ownership_tokens=[b"token"],
    )
    assert runtime.utc_now() == "2026-09-19T08:00:00Z"
    assert runtime.new_uuid7() == "019950f8-4c00-7000-8000-000000000601"
    assert runtime.new_ownership_token() == b"token"
    with pytest.raises(RuntimeError, match="exhausted"):
        runtime.utc_now()
