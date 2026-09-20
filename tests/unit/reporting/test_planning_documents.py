import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from coreelec_reconciler.application.commands import PlanCommand
from coreelec_reconciler.application.outcomes import PlanOutcome
from coreelec_reconciler.application.supplied_observations import (
    load_supplied_planning_input,
)
from coreelec_reconciler.bootstrap import BootstrapSettings, bootstrap
from coreelec_reconciler.config.load import load_configuration
from coreelec_reconciler.domain.identifiers import DeviceId, ResourceId, SelectorId
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport
from coreelec_reconciler.reporting.canonical_json import canonical_document_bytes
from coreelec_reconciler.reporting.planning_documents import (
    build_multi_resource_plan_and_run,
    check_plan_invariants,
    decode_plan,
    decode_run_report,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning import (
    assess_playlist,
)
from tests.unit.planning_support import FIXTURE_ROOT, desired_xml, supplied_document

GOLDEN_ROOT = Path(__file__).parents[2] / "fixtures" / "canonical"
SEMANTIC_EXCLUSIONS = {
    "plan_id",
    "created_at",
    "expires_at",
    "full_digest",
    "semantic_digest",
}


def _plan(tmp_path: Path, content: bytes) -> PlanOutcome:
    supplied = tmp_path / "observations.json"
    supplied.write_bytes(supplied_document(content))
    outcome = bootstrap(BootstrapSettings(str(FIXTURE_ROOT))).execute(
        PlanCommand(
            str(FIXTURE_ROOT),
            DeviceId("living-room.ugoos-am6b-plus"),
            str(supplied),
        )
    )
    assert isinstance(outcome, PlanOutcome)
    assert outcome.plan is not None
    assert outcome.run_report is not None
    return outcome


def _multi_plan(tmp_path: Path) -> tuple[CanonicalPlan, CanonicalRunReport]:
    loaded = load_configuration(
        FIXTURE_ROOT,
        DeviceId("living-room.ugoos-am6b-plus"),
        (SelectorId("selector.skin"),),
    )
    assert loaded.configuration is not None
    base = loaded.configuration.resources[0]
    prerequisite = replace(
        base,
        id=ResourceId("skin.playlist.alpha"),
        requires=(),
        state_addresses=("special://profile/playlists/video/Alpha.xsp",),
    )
    dependent = replace(
        base,
        id=ResourceId("skin.playlist.beta"),
        requires=(prerequisite.id,),
        state_addresses=("special://profile/playlists/video/Beta.xsp",),
    )
    configuration = replace(
        loaded.configuration,
        resources=(dependent, prerequisite),
        dependency_order=(prerequisite.id, dependent.id),
    )
    supplied_path = tmp_path / "multi-observations.json"
    supplied_path.write_bytes(
        supplied_document(
            desired_xml().replace(b"<limit>50</limit>", b"<limit>25</limit>")
        )
    )
    base_input = load_supplied_planning_input(supplied_path)
    entries = []
    for resource in (dependent, prerequisite):
        observation = replace(
            base_input.observation,
            resource_id=resource.id.value,
            state_address=resource.state_addresses[0],
        )
        inputs = replace(base_input, observation=observation)
        assessment = assess_playlist(
            resource.intent,
            resource.desired,
            resource.management,
            observation,
        )
        entries.append((resource, inputs, assessment))
    return build_multi_resource_plan_and_run(configuration, tuple(entries))


def _sha256(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_document_bytes(value)).hexdigest()


def _canonical_plan(value: dict[str, object]) -> bytes:
    semantic = {
        key: item for key, item in value.items() if key not in SEMANTIC_EXCLUSIONS
    }
    producer = dict(cast(dict[str, object], semantic["producer"]))
    producer.pop("version")
    semantic["producer"] = producer
    value["semantic_digest"] = _sha256(semantic)
    without_full = dict(value)
    without_full.pop("full_digest")
    value["full_digest"] = _sha256(without_full)
    return canonical_document_bytes(value)


def _canonical_run(value: dict[str, object]) -> bytes:
    without_current = dict(value)
    without_current.pop("current_digest")
    value["current_digest"] = _sha256(without_current)
    return canonical_document_bytes(value)


def _relink_previous_run(value: dict[str, object]) -> None:
    initial = {
        "approvals": [],
        "device_id": value["device_id"],
        "ended_at": None,
        "failures": [],
        "kind": "CoreElecReconcilerRunReport",
        "lifecycle_history": ["planning"],
        "originating_planning_run_id": value["originating_planning_run_id"],
        "plan_reference": None,
        "previous_revision_digest": None,
        "producer": value["producer"],
        "resource_results": [],
        "revision": 1,
        "run_id": value["run_id"],
        "schema_version": 1,
        "started_at": value["started_at"],
        "status": "planning",
    }
    value["previous_revision_digest"] = _sha256(initial)


@pytest.mark.parametrize(
    ("content", "plan_name", "run_name"),
    [
        (desired_xml(), "plan-noop.json", "run-noop.json"),
        (
            desired_xml().replace(b"<limit>50</limit>", b"<limit>25</limit>"),
            "plan-actionable.json",
            "run-awaiting-approval.json",
        ),
    ],
)
def test_plan_and_run_match_canonical_goldens(
    tmp_path: Path,
    content: bytes,
    plan_name: str,
    run_name: str,
) -> None:
    outcome = _plan(tmp_path, content)
    assert outcome.plan is not None
    assert outcome.run_report is not None

    assert outcome.plan.canonical_bytes == (GOLDEN_ROOT / plan_name).read_bytes()
    assert outcome.run_report.canonical_bytes == (GOLDEN_ROOT / run_name).read_bytes()
    assert not outcome.plan.canonical_bytes.endswith(b"\n")
    assert not outcome.run_report.canonical_bytes.endswith(b"\n")
    assert decode_plan(outcome.plan.canonical_bytes) == outcome.plan
    assert decode_run_report(outcome.run_report.canonical_bytes) == outcome.run_report


def test_multi_resource_plan_round_trips_dependencies_from_canonical_bytes(
    tmp_path: Path,
) -> None:
    plan, run = _multi_plan(tmp_path)
    value = json.loads(plan.canonical_bytes)

    assert value["schema_version"] == 2
    assert [item["resource_id"] for item in value["resources"]] == [
        "skin.playlist.alpha",
        "skin.playlist.beta",
    ]
    assert [item["requires"] for item in value["resources"]] == [
        [],
        ["skin.playlist.alpha"],
    ]
    assert len(value["evidence"]) == 2
    assert sum(len(item["changes"]) for item in value["resources"]) == 2
    assert (
        plan.canonical_bytes
        == (GOLDEN_ROOT / "plan-actionable-multi.json").read_bytes()
    )
    assert (
        run.canonical_bytes
        == (GOLDEN_ROOT / "run-awaiting-approval-multi.json").read_bytes()
    )
    assert decode_plan(plan.canonical_bytes).resource_dependencies == (
        ("skin.playlist.alpha", ()),
        ("skin.playlist.beta", ("skin.playlist.alpha",)),
    )
    assert decode_run_report(run.canonical_bytes, plan) == run
    assert check_plan_invariants(plan.canonical_bytes) == ()


def _mutate_multi_plan(
    value: dict[str, object],
    mutation: str,
) -> None:
    resources = cast(list[dict[str, object]], value["resources"])
    evidence = cast(list[dict[str, object]], value["evidence"])
    if mutation == "unknown-field":
        resources[0]["dependencies"] = []
    elif mutation == "missing-requires":
        resources[0].pop("requires")
    elif mutation == "cycle":
        resources[0]["requires"] = ["skin.playlist.beta"]
    elif mutation == "self-dependency":
        resources[0]["requires"] = ["skin.playlist.alpha"]
    elif mutation == "dangling":
        resources[1]["requires"] = ["skin.playlist.missing"]
    elif mutation == "duplicate-edge":
        resources[1]["requires"] = [
            "skin.playlist.alpha",
            "skin.playlist.alpha",
        ]
    elif mutation == "unstable-order":
        resources.reverse()
        evidence.reverse()
    elif mutation == "duplicate-resource":
        resources[1]["resource_id"] = "skin.playlist.alpha"
    elif mutation == "duplicate-change":
        first_changes = cast(list[dict[str, object]], resources[0]["changes"])
        second_changes = cast(list[dict[str, object]], resources[1]["changes"])
        second_changes[0]["change_id"] = first_changes[0]["change_id"]
    elif mutation == "duplicate-evidence":
        evidence[1]["evidence_id"] = evidence[0]["evidence_id"]
    elif mutation == "change-binding":
        changes = cast(list[dict[str, object]], resources[1]["changes"])
        changes[0]["resource_id"] = "skin.playlist.alpha"
    elif mutation == "evidence-binding":
        subject = cast(dict[str, object], evidence[1]["subject"])
        subject["id"] = "skin.playlist.alpha"
    elif mutation == "unknown-resource-type":
        resources[1]["resource_type"] = "InventedResource"
    elif mutation == "requires-type":
        resources[1]["requires"] = "skin.playlist.alpha"
    elif mutation == "schema-version":
        value["schema_version"] = 999
    else:
        raise AssertionError(f"unknown test mutation: {mutation}")


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-field",
        "missing-requires",
        "cycle",
        "self-dependency",
        "dangling",
        "duplicate-edge",
        "unstable-order",
        "duplicate-resource",
        "duplicate-change",
        "duplicate-evidence",
        "change-binding",
        "evidence-binding",
        "unknown-resource-type",
        "requires-type",
        "schema-version",
    ],
)
def test_multi_resource_plan_rejects_closed_graph_and_reference_mutations(
    tmp_path: Path,
    mutation: str,
) -> None:
    plan, _ = _multi_plan(tmp_path)
    value = json.loads(plan.canonical_bytes)
    _mutate_multi_plan(value, mutation)
    content = _canonical_plan(value)

    with pytest.raises(ValueError):
        decode_plan(content)
    assert check_plan_invariants(content)


def test_plan_dependency_tampering_changes_full_and_semantic_digests(
    tmp_path: Path,
) -> None:
    plan, _ = _multi_plan(tmp_path)
    value = json.loads(plan.canonical_bytes)
    resources = cast(list[dict[str, object]], value["resources"])
    resources[1]["requires"] = []
    without_full = dict(value)
    without_full.pop("full_digest")
    value["full_digest"] = _sha256(without_full)

    with pytest.raises(ValueError, match="semantic digest mismatch"):
        decode_plan(canonical_document_bytes(value))

    value = json.loads(plan.canonical_bytes)
    resources = cast(list[dict[str, object]], value["resources"])
    changes = cast(list[dict[str, object]], resources[1]["changes"])
    desired = cast(dict[str, object], changes[0]["desired"])
    desired["normalized_state_digest"] = "sha256:" + "0" * 64
    without_full = dict(value)
    without_full.pop("full_digest")
    value["full_digest"] = _sha256(without_full)
    with pytest.raises(ValueError, match="semantic digest mismatch"):
        decode_plan(canonical_document_bytes(value))


def test_identical_inputs_produce_identical_documents_and_digests(
    tmp_path: Path,
) -> None:
    first = _plan(tmp_path, desired_xml())
    second = _plan(tmp_path, desired_xml())

    assert first.plan == second.plan
    assert first.run_report == second.run_report


def test_formatting_only_observation_differences_produce_identical_reports(
    tmp_path: Path,
) -> None:
    canonical = _plan(tmp_path, desired_xml())
    formatted = _plan(tmp_path, desired_xml().replace(b"\n    ", b"\r\n\t"))

    assert canonical.plan == formatted.plan
    assert canonical.run_report == formatted.run_report


@pytest.mark.parametrize(
    ("document_kind", "field", "invalid"),
    [
        ("plan", "unexpected", True),
        ("plan", "management", "invented_mode"),
        ("plan", "operation_code", "unknown.operation"),
        ("run", "unexpected", True),
        ("run", "final_convergence", "invented_state"),
    ],
)
def test_canonical_decoders_reject_tampering_and_unknown_nested_fields(
    tmp_path: Path,
    document_kind: str,
    field: str,
    invalid: object,
) -> None:
    content = (
        desired_xml().replace(b"<limit>50</limit>", b"<limit>25</limit>")
        if field == "operation_code"
        else desired_xml()
    )
    outcome = _plan(tmp_path, content)
    document = outcome.plan if document_kind == "plan" else outcome.run_report
    assert document is not None
    value = json.loads(document.canonical_bytes)
    if document_kind == "plan":
        target = (
            value["resources"][0]["changes"][0]
            if field == "operation_code"
            else value["resources"][0]
        )
        target[field] = invalid
        without_digest = dict(value)
        without_digest.pop("full_digest")
        value["full_digest"] = (
            "sha256:"
            + hashlib.sha256(canonical_document_bytes(without_digest)).hexdigest()
        )
        tampered = canonical_document_bytes(value)
        with pytest.raises(ValueError):
            decode_plan(tampered)
    else:
        value["resource_results"][0][field] = invalid
        without_digest = dict(value)
        without_digest.pop("current_digest")
        value["current_digest"] = (
            "sha256:"
            + hashlib.sha256(canonical_document_bytes(without_digest)).hexdigest()
        )
        tampered = canonical_document_bytes(value)
        with pytest.raises(ValueError):
            decode_run_report(tampered)


def test_digest_bytes_are_exactly_the_canonical_bytes_without_newline(
    tmp_path: Path,
) -> None:
    outcome = _plan(tmp_path, desired_xml())
    assert outcome.plan is not None
    assert outcome.run_report is not None
    plan_value = json.loads(outcome.plan.canonical_bytes)
    plan_digest = plan_value.pop("full_digest")
    assert (
        plan_digest
        == "sha256:" + hashlib.sha256(canonical_document_bytes(plan_value)).hexdigest()
    )
    run_value = json.loads(outcome.run_report.canonical_bytes)
    run_digest = run_value.pop("current_digest")
    assert (
        run_digest
        == "sha256:" + hashlib.sha256(canonical_document_bytes(run_value)).hexdigest()
    )


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("producer", "name"), "other"),
        (("plan_id",), "not-a-uuid"),
        (("originating_run_id",), "018f0000-0000-4000-8000-000000000001"),
        (("created_at",), "2026-09-19T08:01:00+00:00"),
        (("valid_from",), "2026-09-19T08:00:59Z"),
        (("expires_at",), "2026-09-19T08:01:00Z"),
        (("input_digests", "resolved_profile"), "sha256:no"),
        (("evidence", 0, "evidence_id"), "evidence.other.before"),
        (("evidence", 0, "observed_at"), "2027-09-19T08:00:00Z"),
        (("resources", 0, "changes", 0, "reason_codes"), []),
        (("resources", 0, "changes", 0, "impact_codes"), ["removal"]),
        (("resources", 0, "changes", 0, "preconditions"), []),
        (("resources", 0, "changes", 0, "effects"), ["effect.remote"]),
    ],
)
def test_plan_decoder_rejects_adversarial_invariants(
    tmp_path: Path,
    path: tuple[str | int, ...],
    invalid: object,
) -> None:
    outcome = _plan(
        tmp_path,
        desired_xml().replace(b"<limit>50</limit>", b"<limit>25</limit>"),
    )
    assert outcome.plan is not None
    value = json.loads(outcome.plan.canonical_bytes)
    target: object = value
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = invalid  # type: ignore[index]

    with pytest.raises(ValueError):
        decode_plan(_canonical_plan(value))


@pytest.mark.parametrize(
    ("path", "invalid"),
    [
        (("producer", "name"), "other"),
        (("run_id",), "not-a-uuid"),
        (("originating_planning_run_id",), "0190aa00-0000-7000-8000-000000000009"),
        (("started_at",), "2026-09-19T08:01:01+00:00"),
        (("ended_at",), "2026-09-19T07:00:00Z"),
        (("revision",), 3),
        (("lifecycle_history",), ["noop"]),
        (("previous_revision_digest",), "sha256:no"),
        (
            ("plan_reference", "originating_planning_run_id"),
            "0190aa00-0000-7000-8000-000000000009",
        ),
        (
            ("plan_reference", "plan_id"),
            "0199542a-7800-7000-8000-000000000101",
        ),
        (("resource_results", 0, "mutation_outcome"), "applied"),
    ],
)
def test_run_decoder_rejects_adversarial_invariants(
    tmp_path: Path,
    path: tuple[str | int, ...],
    invalid: object,
) -> None:
    outcome = _plan(tmp_path, desired_xml())
    assert outcome.run_report is not None
    value = json.loads(outcome.run_report.canonical_bytes)
    target: object = value
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = invalid  # type: ignore[index]

    with pytest.raises(ValueError):
        decode_run_report(_canonical_run(value))


def test_run_decoder_can_bind_exact_plan_reference(tmp_path: Path) -> None:
    outcome = _plan(tmp_path, desired_xml())
    assert outcome.plan is not None
    assert outcome.run_report is not None
    assert (
        decode_run_report(outcome.run_report.canonical_bytes, outcome.plan)
        == outcome.run_report
    )

    value = json.loads(outcome.run_report.canonical_bytes)
    value["plan_reference"]["plan_id"] = "0190aa00-0000-7000-8000-000000000009"
    with pytest.raises(ValueError):
        decode_run_report(_canonical_run(value), outcome.plan)


def test_plan_decoder_rejects_full_and_semantic_projection_tampering(
    tmp_path: Path,
) -> None:
    outcome = _plan(tmp_path, desired_xml())
    assert outcome.plan is not None
    value = json.loads(outcome.plan.canonical_bytes)
    value["semantic_digest"] = "sha256:" + "0" * 64
    without_full = dict(value)
    without_full.pop("full_digest")
    value["full_digest"] = _sha256(without_full)
    with pytest.raises(ValueError, match="semantic digest mismatch"):
        decode_plan(canonical_document_bytes(value))

    value = json.loads(outcome.plan.canonical_bytes)
    value["full_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="full digest mismatch"):
        decode_plan(canonical_document_bytes(value))


def test_run_decoder_rejects_revision_linkage_and_plan_time_order(
    tmp_path: Path,
) -> None:
    outcome = _plan(tmp_path, desired_xml())
    assert outcome.plan is not None
    assert outcome.run_report is not None
    value = json.loads(outcome.run_report.canonical_bytes)
    value["previous_revision_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="previous revision digest mismatch"):
        decode_run_report(_canonical_run(value))

    value = json.loads(outcome.run_report.canonical_bytes)
    value["started_at"] = "2026-09-19T08:02:00Z"
    value["ended_at"] = "2026-09-19T08:02:01Z"
    _relink_previous_run(value)
    with pytest.raises(ValueError, match="start after Plan creation"):
        decode_run_report(_canonical_run(value), outcome.plan)
