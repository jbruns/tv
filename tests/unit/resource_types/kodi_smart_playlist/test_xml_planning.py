import base64
from dataclasses import replace

import pytest

from coreelec_reconciler.config.load import load_configuration
from coreelec_reconciler.domain.configuration import (
    DesiredPresence,
    ManagementMode,
    Resource,
)
from coreelec_reconciler.domain.identifiers import DeviceId, SelectorId
from coreelec_reconciler.domain.planning import (
    DesiredRelation,
    FileKind,
    KodiSmartPlaylistObservation,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning import (
    assess_playlist,
    desired_model,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.xml import (
    PlaylistXmlError,
    parse_playlist_xml,
    render_playlist_xml,
)
from tests.unit.planning_support import FIXTURE_ROOT, desired_xml


def _resource() -> Resource:
    result = load_configuration(
        FIXTURE_ROOT,
        DeviceId("living-room.ugoos-am6b-plus"),
        (SelectorId("selector.skin"),),
    )
    assert result.configuration is not None
    return result.configuration.resources[0]


@pytest.mark.parametrize(
    "content",
    [
        desired_xml(),
        desired_xml().replace(b"\n    ", b"\r\n\t"),
        desired_xml().replace(
            b'<rule field="playcount" operator="is">',
            b'<rule operator="is" field="playcount">',
        ),
        b"\xef\xbb\xbf" + desired_xml(),
    ],
)
def test_semantically_equivalent_xml_is_a_noop(content: bytes) -> None:
    resource = _resource()
    observation = KodiSmartPlaylistObservation(
        resource.id.value,
        resource.state_addresses[0],
        "2026-09-19T08:00:00Z",
        FileKind.REGULAR,
        "0644",
        content,
    )

    assessment = assess_playlist(
        resource.intent,
        resource.desired,
        resource.management,
        observation,
    )

    assert assessment.relation is DesiredRelation.SATISFIED
    assert assessment.operation_code is None
    assert assessment.reason_codes == ()
    assert assessment.effects == ()


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (
            desired_xml().replace(b"<limit>50</limit>", b"<limit>25</limit>"),
            "playlist.semantic-drift",
        ),
        (b"<smartplaylist", "playlist.malformed-current"),
        (
            desired_xml().replace(
                b"</smartplaylist>",
                b"<unknown>value</unknown></smartplaylist>",
            ),
            "playlist.malformed-current",
        ),
        (
            desired_xml().replace(
                b"<limit>50</limit>",
                b"<limit>50</limit><limit>50</limit>",
            ),
            "playlist.malformed-current",
        ),
    ],
)
def test_semantic_or_malformed_drift_is_one_repair_change(
    content: bytes,
    reason: str,
) -> None:
    resource = _resource()
    assessment = assess_playlist(
        resource.intent,
        resource.desired,
        resource.management,
        KodiSmartPlaylistObservation(
            resource.id.value,
            resource.state_addresses[0],
            "2026-09-19T08:00:00Z",
            FileKind.REGULAR,
            "0644",
            content,
        ),
    )

    assert assessment.relation is DesiredRelation.DIVERGENT
    assert assessment.operation_code == "smart_playlist.update"
    assert assessment.reason_codes == (reason,)
    assert assessment.impact_codes == ("content_mutation",)
    assert assessment.effects == ()


def test_mode_only_drift_is_one_update_without_semantic_drift() -> None:
    resource = _resource()
    assessment = assess_playlist(
        resource.intent,
        resource.desired,
        resource.management,
        KodiSmartPlaylistObservation(
            resource.id.value,
            resource.state_addresses[0],
            "2026-09-19T08:00:00Z",
            FileKind.REGULAR,
            "0600",
            desired_xml(),
        ),
    )

    assert assessment.operation_code == "smart_playlist.update"
    assert assessment.reason_codes == ("managed-file.mode-drift",)


def test_absent_and_desired_absence_cases_are_exact() -> None:
    resource = _resource()
    absent = KodiSmartPlaylistObservation(
        resource.id.value,
        resource.state_addresses[0],
        "2026-09-19T08:00:00Z",
        FileKind.ABSENT,
        None,
        None,
    )
    create = assess_playlist(
        resource.intent,
        resource.desired,
        resource.management,
        absent,
    )
    absent_resource = replace(resource, desired=DesiredPresence.ABSENT)
    absent_satisfied = assess_playlist(
        absent_resource.intent,
        absent_resource.desired,
        absent_resource.management,
        absent,
    )
    remove = assess_playlist(
        absent_resource.intent,
        absent_resource.desired,
        absent_resource.management,
        replace(absent, kind=FileKind.REGULAR, mode="0644", content=desired_xml()),
    )

    assert (create.operation_code, create.reason_codes) == (
        "smart_playlist.create",
        ("playlist.absent",),
    )
    assert absent_satisfied.relation is DesiredRelation.SATISFIED
    assert absent_satisfied.operation_code is None
    assert (remove.operation_code, remove.reason_codes, remove.impact_codes) == (
        "smart_playlist.remove",
        ("playlist.desired-absent",),
        ("content_mutation", "removal"),
    )


def test_observe_only_reports_drift_without_a_change() -> None:
    resource = replace(_resource(), management=ManagementMode.OBSERVE_ONLY)
    assessment = assess_playlist(
        resource.intent,
        resource.desired,
        resource.management,
        KodiSmartPlaylistObservation(
            resource.id.value,
            resource.state_addresses[0],
            "2026-09-19T08:00:00Z",
            FileKind.ABSENT,
            None,
            None,
        ),
    )

    assert assessment.relation is DesiredRelation.DIVERGENT
    assert assessment.operation_code is None
    assert assessment.impact_codes == ()
    assert assessment.blocker_codes == ("resource.observe-only-divergence",)


def test_renderer_has_one_deterministic_utf8_representation() -> None:
    resource = _resource()
    rendered = render_playlist_xml(desired_model(resource.intent))

    assert rendered == desired_xml()
    assert parse_playlist_xml(rendered) == desired_model(resource.intent)
    assert base64.b64decode(base64.b64encode(rendered)) == rendered


@pytest.mark.parametrize(
    "content",
    [
        b'<?xml version="1.0" encoding="ISO-8859-1"?><smartplaylist/>',
        b'<smartplaylist xmlns="urn:unsupported" type="tvshows"/>',
        desired_xml().replace(b"<rule ", b'<rule extra="x" '),
        b'<!DOCTYPE x [<!ENTITY a "x">]><smartplaylist type="tvshows"/>',
    ],
)
def test_parser_rejects_unsupported_or_malformed_shapes(content: bytes) -> None:
    with pytest.raises(PlaylistXmlError):
        parse_playlist_xml(content)
