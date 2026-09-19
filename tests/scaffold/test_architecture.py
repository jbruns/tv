import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "coreelec_reconciler"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_cli_imports_stop_at_application_and_bootstrap() -> None:
    project_imports = {
        module
        for path in (PACKAGE_ROOT / "cli").glob("*.py")
        for module in imported_modules(path)
        if module.startswith("coreelec_reconciler")
    }

    assert project_imports <= {
        "coreelec_reconciler.application.commands",
        "coreelec_reconciler.application.outcomes",
        "coreelec_reconciler.bootstrap",
        "coreelec_reconciler.cli.parser",
    }


def test_production_package_has_one_bootstrap_composition_root() -> None:
    bootstrap_definitions = [
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        for node in ast.walk(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        if isinstance(node, ast.FunctionDef) and node.name == "bootstrap"
    ]

    assert bootstrap_definitions == [PACKAGE_ROOT / "bootstrap.py"]
