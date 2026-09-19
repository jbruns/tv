import json
from dataclasses import replace
from pathlib import Path

import pytest

from coreelec_reconciler.application.supplied_observations import (
    load_supplied_planning_input,
)
from coreelec_reconciler.config.load import load_configuration
from coreelec_reconciler.domain.configuration import DesiredPresence
from coreelec_reconciler.domain.identifiers import DeviceId, SelectorId
from coreelec_reconciler.reporting.planning_documents import build_plan_and_run
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning import (
    assess_playlist,
)
from tests.unit.planning_support import FIXTURE_ROOT, desired_xml, supplied_document


@pytest.mark.parametrize(
    (
        "content",
        "kind",
        "mode",
        "desired",
        "disposition",
        "status",
        "operation",
        "reasons",
    ),
    [
        (
            None,
            "absent",
            None,
            DesiredPresence.PRESENT,
            "actionable",
            "awaiting_approval",
            "smart_playlist.create",
            ["playlist.absent"],
        ),
        (
            desired_xml().replace(b"\n    ", b"\n\t"),
            "regular",
            "0644",
            DesiredPresence.PRESENT,
            "noop",
            "noop",
            None,
            [],
        ),
        (
            desired_xml().replace(b"<limit>50</limit>", b"<limit>25</limit>"),
            "regular",
            "0644",
            DesiredPresence.PRESENT,
            "actionable",
            "awaiting_approval",
            "smart_playlist.update",
            ["playlist.semantic-drift"],
        ),
        (
            desired_xml(),
            "regular",
            "0600",
            DesiredPresence.PRESENT,
            "actionable",
            "awaiting_approval",
            "smart_playlist.update",
            ["managed-file.mode-drift"],
        ),
        (
            b"<not-xml",
            "regular",
            "0644",
            DesiredPresence.PRESENT,
            "actionable",
            "awaiting_approval",
            "smart_playlist.update",
            ["playlist.malformed-current"],
        ),
        (
            desired_xml(),
            "regular",
            "0644",
            DesiredPresence.ABSENT,
            "actionable",
            "awaiting_approval",
            "smart_playlist.remove",
            ["playlist.desired-absent"],
        ),
        (
            None,
            "absent",
            None,
            DesiredPresence.ABSENT,
            "noop",
            "noop",
            None,
            [],
        ),
    ],
)
def test_exact_pure_planning_behavior_matrix(
    tmp_path: Path,
    content: bytes | None,
    kind: str,
    mode: str | None,
    desired: DesiredPresence,
    disposition: str,
    status: str,
    operation: str | None,
    reasons: list[str],
) -> None:
    loaded = load_configuration(
        FIXTURE_ROOT,
        DeviceId("living-room.ugoos-am6b-plus"),
        (SelectorId("selector.skin"),),
    )
    assert loaded.configuration is not None
    resource = replace(loaded.configuration.resources[0], desired=desired)
    configuration = replace(loaded.configuration, resources=(resource,))
    supplied_path = tmp_path / "observations.json"
    supplied_path.write_bytes(supplied_document(content, kind=kind, mode=mode))
    supplied = load_supplied_planning_input(supplied_path)
    assessment = assess_playlist(
        resource.intent,
        resource.desired,
        resource.management,
        supplied.observation,
    )

    plan, run = build_plan_and_run(
        configuration,
        resource,
        supplied,
        assessment,
    )
    plan_value = json.loads(plan.canonical_bytes)
    run_value = json.loads(run.canonical_bytes)
    changes = plan_value["resources"][0]["changes"]

    assert plan_value["disposition"] == disposition
    assert run_value["status"] == status
    assert plan_value["effects"] == []
    if operation is None:
        assert changes == []
    else:
        assert len(changes) == 1
        change = changes[0]
        assert change["operation_code"] == operation
        assert change["reason_codes"] == reasons
        assert change["effects"] == []
        assert change["preconditions"] == [
            {
                "evidence_ref": "evidence.skin.playlist.new-shows.before",
                "expected_digest": change["before"]["normalized_state_digest"],
                "kind": "normalized_state_digest_matches",
            }
        ]
