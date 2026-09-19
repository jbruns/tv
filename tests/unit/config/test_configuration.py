from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from coreelec_reconciler.config.codecs import (
    decode_resolved_configuration,
    encode_resolved_configuration,
)
from coreelec_reconciler.config.load import load_configuration
from coreelec_reconciler.domain.configuration import (
    ResolvedConfiguration,
    SecretReference,
)
from coreelec_reconciler.domain.identifiers import DeviceId, SelectorId

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
