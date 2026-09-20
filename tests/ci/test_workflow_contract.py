from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "offline-ci.yml"


def test_workflow_is_least_privilege_and_runs_supported_platforms() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"python-offline"}
    python_job = workflow["jobs"]["python-offline"]
    assert python_job["timeout-minutes"] == 15
    assert workflow["env"]["SOURCE_SHA"] == (
        "${{ github.event.pull_request.head.sha || github.sha }}"
    )
    for job in workflow["jobs"].values():
        checkout = next(
            step for step in job["steps"] if step["name"] == "Check out source"
        )
        assert checkout["with"]["ref"] == "${{ env.SOURCE_SHA }}"


def test_workflow_uses_frozen_tools_exact_selectors_and_hard_budgets() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["python-offline"]["steps"]
    run_commands = [step["run"] for step in steps if "run" in step]

    assert "uv sync --frozen" in run_commands
    assert "uv run ruff check ." in run_commands
    assert any(
        "uv run ruff format --check" in command
        and "scripts/run_test_budget.py" in command
        and "scripts/check_inventory_milestones.py" in command
        and "scripts/run_m3_pilot_harness.py" in command
        and "scripts/verify_m3_evidence_bundle.py" in command
        and "tests/inventory" in command
        and "tests/support" in command
        for command in run_commands
    )
    assert "uv run mypy" in run_commands
    assert "uv build" in run_commands
    assert any(
        "uv pip install" in command
        and "coreelec-reconciler --version" in command
        and "coreelec-reconciler --help" in command
        and "ZipFile" in command
        for command in run_commands
    )
    assert any(
        "tests/scaffold/test_application.py "
        "tests/scaffold/test_architecture.py tests/inventory tests/ci"
        in command
        and "--budget-seconds 10" in command
        for command in run_commands
    )
    assert any(
        "uv run python scripts/check_inventory_milestones.py" in command
        for command in run_commands
    )
    assert any(
        "python3 scripts/check_shell_permissions.py --audit" in command
        for command in run_commands
    )
    assert any(
        "tests/adapters tests/contracts" in command
        and "tests/scaffold/test_cli.py" in command
        and "tests/scaffold/test_cli_execution.py tests/integration" in command
        and "--budget-seconds 60" in command
        and "--include-result .ci-evidence/pure.json" in command
        for command in run_commands
    )
    assert any(
        "scripts/run_m3_pilot_harness.py" in command
        and "scripts/verify_m3_evidence_bundle.py" in command
        and "diff -r" in command
        for command in run_commands
    )

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "source_sha=${SOURCE_SHA}" in workflow_text
    assert 'test "$checked_out_sha" = "$SOURCE_SHA"' in workflow_text
    assert "checked_out_sha=${checked_out_sha}" in workflow_text
    assert "workflow_sha=${GITHUB_SHA}" in workflow_text
    assert (
        "offline-ci-${{ runner.os }}-${{ runner.arch }}-${{ env.SOURCE_SHA }}"
        in workflow_text
    )
    assert (
        "offline-ci-${{ runner.os }}-${{ runner.arch }}-${{ github.sha }}"
        not in workflow_text
    )
    for forbidden in ("continue-on-error", "pytest-rerunfailures", "flaky", "xfail"):
        assert forbidden not in workflow_text
