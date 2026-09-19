import json
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from pathlib import Path

import pytest

from coreelec_reconciler.config.codecs import (
    decode_resolved_configuration,
    encode_resolved_configuration,
)
from coreelec_reconciler.config.load import load_configuration
from coreelec_reconciler.domain.configuration import (
    Artifact,
    ResolvedConfiguration,
    SecretReference,
)
from coreelec_reconciler.domain.identifiers import (
    ArtifactId,
    DeviceId,
    SelectorId,
)

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository"


def test_fixed_layers_compose_playlist_into_frozen_domain_values() -> None:
    result = load_configuration(
        FIXTURE_ROOT,
        DeviceId("living-room.ugoos-am6b-plus"),
        (SelectorId("selector.skin"),),
    )

    assert result.diagnostics == ()
    assert isinstance(result.configuration, ResolvedConfiguration)
    assert result.configuration.profile_ids == (
        "platform.coreelec-21.amlogic-ng",
        "room.living-room",
        "device.living-room.ugoos-am6b-plus",
    )
    resource = result.configuration.resources[0]
    assert resource.id.value == "skin.playlist.new-shows"
    assert resource.selectors == (
        SelectorId("selector.baseline"),
        SelectorId("selector.skin"),
        SelectorId("selector.room"),
    )
    assert resource.intent.playlist.limit == 50
    assert resource.intent.playlist.display_name == "New Shows"
    assert resource.state_addresses == (
        "special://profile/playlists/video/NewShows.xsp",
    )
    assert dict(resource.origins)["intent.playlist.limit"].endswith(
        "profiles/device/living-room-ugoos.yaml"
    )
    assert dict(resource.origins)["intent.playlist.display_name"].endswith(
        "profiles/platform/coreelec-21-amlogic-ng.yaml"
    )
    assert result.configuration.dependency_order == (resource.id,)
    assert all(
        "pydantic" not in type(value).__module__.lower()
        and "yaml" not in type(value).__module__.lower()
        for value in (
            result,
            result.configuration,
            resource,
            resource.intent,
            resource.intent.playlist,
        )
    )
    with pytest.raises(FrozenInstanceError):
        resource.intent.playlist.limit = 1  # type: ignore[misc]


def test_canonical_codec_round_trip_is_byte_stable_and_secret_opaque() -> None:
    result = load_configuration(
        FIXTURE_ROOT,
        DeviceId("living-room.ugoos-am6b-plus"),
        (SelectorId("selector.skin"),),
    )
    assert result.configuration is not None

    encoded = encode_resolved_configuration(result.configuration)
    decoded = decode_resolved_configuration(encoded)

    assert decoded == result.configuration
    assert encode_resolved_configuration(decoded) == encoded
    assert encoded.endswith(b"}") and not encoded.endswith(b"\n")
    assert (
        sha256(encoded).hexdigest()
        == "004d7e8c39e512fae99572a8e912d6eecd6b3fe0f9088584acae41f61da2208b"
    )
    assert decoded.secret_references == (
        SecretReference(
            provider="controller.environment",
            key="coreelec.admin-private-key",
        ),
    )
    assert b"COREELEC_ADMIN_PRIVATE_KEY_FILE" not in encoded


@pytest.mark.parametrize(
    "content",
    [
        b'{"kind":"CoreElecResolvedConfiguration","kind":"duplicate"}',
        b'{ "kind": "CoreElecResolvedConfiguration" }',
    ],
)
def test_canonical_decoder_rejects_duplicate_or_noncanonical_json(
    content: bytes,
) -> None:
    with pytest.raises(ValueError):
        decode_resolved_configuration(content)


def _configuration_with_artifact() -> ResolvedConfiguration:
    result = load_configuration(
        FIXTURE_ROOT,
        DeviceId("living-room.ugoos-am6b-plus"),
    )
    assert result.configuration is not None
    return replace(
        result.configuration,
        artifacts=(
            Artifact(
                id=ArtifactId("artifact.kodi.example"),
                kind="kodi-addon",
                version="1.0.0",
                origin_sha256="a" * 64,
                distribution_sha256="a" * 64,
                platforms=("coreelec-21-amlogic-ng",),
                dependencies=(),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("section", "mutation"),
    [
        ("artifacts", ("missing", "id")),
        ("artifacts", ("extra", "unexpected")),
        ("artifacts", ("wrong", "platforms")),
        ("secret_references", ("missing", "provider")),
        ("secret_references", ("extra", "unexpected")),
        ("secret_references", ("wrong", "key")),
    ],
)
def test_canonical_decoder_rejects_malformed_nested_objects(
    section: str,
    mutation: tuple[str, str],
) -> None:
    value = json.loads(encode_resolved_configuration(_configuration_with_artifact()))
    nested = value[section][0]
    operation, field = mutation
    if operation == "missing":
        del nested[field]
    elif operation == "extra":
        nested[field] = "not-allowed"
    else:
        nested[field] = 42
    content = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    with pytest.raises(ValueError):
        decode_resolved_configuration(content)


def test_canonical_decoder_rejects_noncanonical_valid_payload() -> None:
    canonical = encode_resolved_configuration(_configuration_with_artifact())
    noncanonical = json.dumps(
        json.loads(canonical),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode()

    with pytest.raises(ValueError, match="not canonical"):
        decode_resolved_configuration(noncanonical)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("artifacts", "id", "INVALID"),
        ("artifacts", "version", ""),
        ("artifacts", "platforms", ["unknown-platform"]),
        ("artifacts", "dependencies", ["INVALID"]),
        ("secret_references", "provider", "INVALID"),
        ("secret_references", "key", ""),
    ],
)
def test_canonical_decoder_rejects_invalid_nested_values(
    section: str,
    field: str,
    value: object,
) -> None:
    document = json.loads(encode_resolved_configuration(_configuration_with_artifact()))
    document[section][0][field] = value
    content = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    with pytest.raises(ValueError):
        decode_resolved_configuration(content)
