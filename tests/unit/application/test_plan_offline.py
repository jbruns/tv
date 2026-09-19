import shutil
from pathlib import Path

import pytest

from coreelec_reconciler.application.commands import PlanCommand, ValidateCommand
from coreelec_reconciler.application.outcomes import PlanOutcome, ValidationOutcome
from coreelec_reconciler.bootstrap import BootstrapSettings, bootstrap
from coreelec_reconciler.domain.identifiers import DeviceId
from tests.unit.planning_support import FIXTURE_ROOT, desired_xml, supplied_document


def test_validate_and_plan_use_only_supplied_observations_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURE_ROOT, repository)
    source_ledger = Path(__file__).parents[3] / "inventory" / "ownership-ledger.json"
    shutil.copy2(source_ledger, repository / "inventory" / "ownership-ledger.json")
    supplied = tmp_path / "observations.json"
    supplied.write_bytes(supplied_document(desired_xml()))
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    def reject_write(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("validate/plan attempted filesystem mutation")

    monkeypatch.setattr(Path, "write_bytes", reject_write)
    monkeypatch.setattr(Path, "write_text", reject_write)
    reconciler = bootstrap(BootstrapSettings(str(repository)))

    validation = reconciler.execute(
        ValidateCommand(
            str(repository),
            DeviceId("living-room.ugoos-am6b-plus"),
            str(supplied),
        )
    )
    plan = reconciler.execute(
        PlanCommand(
            str(repository),
            DeviceId("living-room.ugoos-am6b-plus"),
            str(supplied),
        )
    )

    assert isinstance(validation, ValidationOutcome)
    assert validation.valid
    assert isinstance(plan, PlanOutcome)
    assert plan.disposition == "noop"
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_plan_rejects_observation_binding_mismatch(tmp_path: Path) -> None:
    value = supplied_document(desired_xml()).replace(
        b"skin.playlist.new-shows",
        b"skin.playlist.other-shows",
    )
    supplied = tmp_path / "observations.json"
    supplied.write_bytes(value)

    outcome = bootstrap(BootstrapSettings(str(FIXTURE_ROOT))).execute(
        PlanCommand(
            str(FIXTURE_ROOT),
            DeviceId("living-room.ugoos-am6b-plus"),
            str(supplied),
        )
    )

    assert isinstance(outcome, PlanOutcome)
    assert outcome.plan is None
    assert outcome.diagnostics == ("observation.binding-mismatch",)
