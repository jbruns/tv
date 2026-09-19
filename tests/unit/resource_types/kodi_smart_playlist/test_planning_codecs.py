from collections.abc import Mapping
from dataclasses import replace
from typing import cast

import pytest

from coreelec_reconciler.config.load import load_configuration
from coreelec_reconciler.domain.identifiers import DeviceId, SelectorId
from coreelec_reconciler.domain.planning import (
    FileKind,
    KodiSmartPlaylistObservation,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning import (
    assess_playlist,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning_codecs import (
    decode_assessment,
    decode_observation,
    encode_assessment,
    encode_observation,
)
from tests.unit.planning_support import FIXTURE_ROOT, desired_xml


def test_observation_and_assessment_codecs_round_trip() -> None:
    loaded = load_configuration(
        FIXTURE_ROOT,
        DeviceId("living-room.ugoos-am6b-plus"),
        (SelectorId("selector.skin"),),
    )
    assert loaded.configuration is not None
    resource = loaded.configuration.resources[0]
    observation = KodiSmartPlaylistObservation(
        resource.id.value,
        resource.state_addresses[0],
        "2026-09-19T08:00:00Z",
        FileKind.REGULAR,
        "0600",
        desired_xml(),
    )
    assessment = assess_playlist(
        resource.intent,
        resource.desired,
        resource.management,
        observation,
    )

    assert decode_observation(encode_observation(observation)) == observation
    assert decode_assessment(encode_assessment(assessment)) == assessment


@pytest.mark.parametrize("codec", ["observation", "assessment"])
def test_planning_codecs_reject_unknown_fields(codec: str) -> None:
    observation = KodiSmartPlaylistObservation(
        "skin.playlist.new-shows",
        "special://profile/playlists/video/NewShows.xsp",
        "2026-09-19T08:00:00Z",
        FileKind.ABSENT,
        None,
        None,
    )
    if codec == "observation":
        value = dict(encode_observation(observation))
        payload = dict(cast(Mapping[str, object], value["payload"]))
        payload["unexpected"] = True
        value["payload"] = payload
        with pytest.raises(ValueError):
            decode_observation(value)
    else:
        loaded = load_configuration(
            FIXTURE_ROOT,
            DeviceId("living-room.ugoos-am6b-plus"),
            (SelectorId("selector.skin"),),
        )
        assert loaded.configuration is not None
        resource = loaded.configuration.resources[0]
        assessment = assess_playlist(
            resource.intent,
            resource.desired,
            resource.management,
            observation,
        )
        value = dict(encode_assessment(assessment))
        payload = dict(cast(Mapping[str, object], value["payload"]))
        payload["unexpected"] = True
        value["payload"] = payload
        with pytest.raises(ValueError):
            decode_assessment(value)


def test_codec_does_not_alias_mutable_input() -> None:
    observation = KodiSmartPlaylistObservation(
        "skin.playlist.new-shows",
        "special://profile/playlists/video/NewShows.xsp",
        "2026-09-19T08:00:00Z",
        FileKind.ABSENT,
        None,
        None,
    )
    assert decode_observation(encode_observation(replace(observation))) == observation


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resource_id", ""),
        ("state_address", ""),
        ("observed_at", "2026-99-99T99:99:99Z"),
        ("mode", "invalid"),
    ],
)
def test_observation_codec_rejects_invalid_domain_values(
    field: str,
    value: object,
) -> None:
    observation = KodiSmartPlaylistObservation(
        "skin.playlist.new-shows",
        "special://profile/playlists/video/NewShows.xsp",
        "2026-09-19T08:00:00Z",
        FileKind.REGULAR,
        "0644",
        desired_xml(),
    )
    encoded = dict(encode_observation(observation))
    payload = dict(cast(Mapping[str, object], encoded["payload"]))
    payload[field] = value
    encoded["payload"] = payload

    with pytest.raises(ValueError):
        decode_observation(encoded)


def test_absent_observation_codec_rejects_file_content() -> None:
    observation = KodiSmartPlaylistObservation(
        "skin.playlist.new-shows",
        "special://profile/playlists/video/NewShows.xsp",
        "2026-09-19T08:00:00Z",
        FileKind.REGULAR,
        "0644",
        desired_xml(),
    )
    encoded = dict(encode_observation(observation))
    payload = dict(cast(Mapping[str, object], encoded["payload"]))
    payload["kind"] = "absent"
    encoded["payload"] = payload

    with pytest.raises(ValueError):
        decode_observation(encoded)
