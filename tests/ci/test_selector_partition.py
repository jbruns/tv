from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
TEST_ROOT = REPOSITORY_ROOT / "tests"

PURE_SELECTORS = (
    "tests/scaffold/test_application.py",
    "tests/scaffold/test_architecture.py",
    "tests/inventory",
    "tests/ci",
    "tests/unit",
)
OFFLINE_SELECTORS = (
    "tests/adapters",
    "tests/contracts",
    "tests/scaffold/test_cli.py",
    "tests/scaffold/test_cli_planning.py",
    "tests/scaffold/test_cli_execution.py",
    "tests/integration",
)


def _selected(selectors: tuple[str, ...]) -> set[Path]:
    selected: set[Path] = set()
    for selector in selectors:
        path = REPOSITORY_ROOT / selector
        selected.update(path.rglob("test_*.py") if path.is_dir() else (path,))
    return selected


def test_offline_selectors_are_complete_exact_and_non_overlapping() -> None:
    pure = _selected(PURE_SELECTORS)
    remaining = _selected(OFFLINE_SELECTORS)
    all_python_tests = {
        path
        for path in TEST_ROOT.rglob("test_*.py")
        if path.name != "test_home-assistant-ugoos-package.py"
    }

    assert pure
    assert remaining
    assert pure.isdisjoint(remaining)
    assert pure | remaining == all_python_tests
    assert not any(path.suffix == ".sh" for path in pure | remaining)
