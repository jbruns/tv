"""Evidence-only strict-boundary tests."""

import pytest
import yaml
from pydantic import ValidationError

from coreelec_reconciler.config import load_profile, validate_then_connect

VALID = """
schema_version: 1
resources:
  - id: base
  - id: child
    dependencies: [base]
"""


def test_valid_profile_converts_to_frozen_standard_library_domain() -> None:
    profile = load_profile(VALID)
    assert profile.resources[1].dependencies == ("base",)
    with pytest.raises(AttributeError):
        profile.schema_version = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("schema_version: 1\nschema_version: 1\nresources: []", yaml.YAMLError),
        ("---\nschema_version: 1\nresources: []\n---\n{}", ValueError),
        ("schema_version: 1\nresources: !proof []", yaml.YAMLError),
        ("- schema_version\n- 1", ValueError),
        ("schema_version: 1\nresources: []\nunknown: true", ValidationError),
        ('schema_version: "1"\nresources: []', ValidationError),
        (
            "schema_version: 1\nresources:\n  - id: child\n"
            "    dependencies: [missing]\n",
            ValueError,
        ),
        (
            "schema_version: 1\nresources:\n"
            "  - id: one\n    dependencies: [two]\n"
            "  - id: two\n    dependencies: [one]\n",
            ValueError,
        ),
        ("schema_version: 2\nresources: []", ValueError),
    ],
)
def test_invalid_input_fails_before_transport(
    text: str, error: type[Exception]
) -> None:
    invoked = False

    def sentinel() -> object:
        nonlocal invoked
        invoked = True
        return object()

    with pytest.raises(error):
        validate_then_connect(text, sentinel)
    assert not invoked


def test_valid_input_invokes_transport_only_after_validation() -> None:
    calls: list[str] = []

    def sentinel() -> str:
        calls.append("constructed")
        return "transport"

    _profile, transport = validate_then_connect(VALID, sentinel)
    assert transport == "transport"
    assert calls == ["constructed"]
