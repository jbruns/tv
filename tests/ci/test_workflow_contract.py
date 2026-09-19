from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "offline-ci.yml"


def test_workflow_is_least_privilege_and_runs_supported_platforms() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert workflow["permissions"] == {"contents": "read"}
    python_job = workflow["jobs"]["python-offline"]
    assert python_job["strategy"] == {
        "fail-fast": False,
        "matrix": {"os": ["ubuntu-24.04", "macos-15"]},
    }
    assert python_job["runs-on"] == "${{ matrix.os }}"
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
        "tests/scaffold/test_cli.py" in command
        and "--budget-seconds 60" in command
        and "--include-result .ci-evidence/pure.json" in command
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


def test_shell_transition_suite_remains_a_separate_job() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    shell_job = workflow["jobs"]["shell-transition"]

    assert shell_job["name"] == "Shell transition suite"
    assert shell_job["runs-on"] == "macos-15"
    assert shell_job["timeout-minutes"] == 15
    run_commands = [step["run"] for step in shell_job["steps"] if "run" in step]
    assert "uv sync --frozen" in run_commands
    assert any(
        "for test_script in tests/test-*.sh" in command
        and "*test-helper.sh) continue" in command
        and 'export PATH="$PWD/.venv/bin:$PATH"' in command
        for command in run_commands
    )
