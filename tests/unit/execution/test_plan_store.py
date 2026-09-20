from pathlib import Path

import pytest

from coreelec_reconciler.domain.identifiers import PlanId
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport
from coreelec_reconciler.execution.local_durability import (
    DurabilityOperation,
    ScriptedFault,
    ScriptedLocalDurability,
)
from coreelec_reconciler.execution.plan_store import (
    CorruptPlanStore,
    PlanStore,
)
from coreelec_reconciler.reporting.planning_documents import (
    decode_plan,
    decode_run_report,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "canonical"


def _pair() -> tuple[CanonicalPlan, CanonicalRunReport]:
    plan = decode_plan((FIXTURES / "plan-actionable.json").read_bytes())
    run = decode_run_report(
        (FIXTURES / "run-awaiting-approval.json").read_bytes(),
        plan,
    )
    return plan, run


def test_saved_plan_round_trips_exact_bytes_across_restart(tmp_path: Path) -> None:
    plan, run = _pair()
    first = PlanStore(tmp_path / "plans")

    first.save(plan, run)
    loaded = PlanStore(tmp_path / "plans").load(PlanId(plan.plan_id))

    assert loaded.plan == plan
    assert loaded.planning_run == run
    assert loaded.plan.canonical_bytes == plan.canonical_bytes
    assert loaded.planning_run.canonical_bytes == run.canonical_bytes
    assert loaded.device_id.value == "living-room.ugoos-am6b-plus"
    assert loaded.originating_run_id.value == run.run_id
    assert loaded.approval_scopes == ("apply",)
    assert dict(loaded.input_digests)["authored_configuration"].startswith("sha256:")


def test_saved_plan_rejects_corrupt_canonical_bytes(tmp_path: Path) -> None:
    plan, run = _pair()
    store = PlanStore(tmp_path / "plans")
    store.save(plan, run)
    directory = next((tmp_path / "plans").iterdir())
    (directory / "plan.json").write_bytes(plan.canonical_bytes + b" ")

    with pytest.raises(CorruptPlanStore, match="validation failed"):
        PlanStore(tmp_path / "plans").load(PlanId(plan.plan_id))


def test_saved_plan_reconciles_lost_publish_acknowledgement(tmp_path: Path) -> None:
    plan, run = _pair()
    durability = ScriptedLocalDurability(
        (ScriptedFault(DurabilityOperation.ACKNOWLEDGE, acknowledgement_lost=True),)
    )

    saved = PlanStore(tmp_path / "plans", durability).save(plan, run)

    assert saved.plan.canonical_bytes == plan.canonical_bytes
