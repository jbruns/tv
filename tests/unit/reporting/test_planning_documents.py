import hashlib
import json
from pathlib import Path

import pytest

from coreelec_reconciler.application.commands import PlanCommand
from coreelec_reconciler.application.outcomes import PlanOutcome
from coreelec_reconciler.bootstrap import BootstrapSettings, bootstrap
from coreelec_reconciler.domain.identifiers import DeviceId
from coreelec_reconciler.reporting.canonical_json import canonical_document_bytes
from coreelec_reconciler.reporting.planning_documents import (
    decode_plan,
    decode_run_report,
)
from tests.unit.planning_support import FIXTURE_ROOT, desired_xml, supplied_document

GOLDEN_ROOT = Path(__file__).parents[2] / "fixtures" / "canonical"


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
