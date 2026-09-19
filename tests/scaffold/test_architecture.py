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


def test_network_modules_are_limited_to_approved_boundaries() -> None:
    prohibited_modules = {"socket", "urllib", "httpx", "requests", "paramiko"}
    violations = {
        path.relative_to(PACKAGE_ROOT): modules & prohibited_modules
        for path in PACKAGE_ROOT.rglob("*.py")
        if (
            modules := {
                module.split(".", maxsplit=1)[0] for module in imported_modules(path)
            }
            & prohibited_modules
        )
        and "adapters" not in path.parts
        and "cli" not in path.parts
    }

    assert violations == {}


def test_yaml_and_pydantic_are_confined_to_config_boundary() -> None:
    boundary_modules = {"pydantic", "yaml"}
    violations = {
        path.relative_to(PACKAGE_ROOT): modules & boundary_modules
        for path in PACKAGE_ROOT.rglob("*.py")
        if (
            modules := {
                module.split(".", maxsplit=1)[0] for module in imported_modules(path)
            }
            & boundary_modules
        )
        and "config" not in path.parts
    }

    assert violations == {}


def test_domain_imports_only_standard_library_and_domain_modules() -> None:
    violations = {
        path.relative_to(PACKAGE_ROOT): sorted(
            module
            for module in imported_modules(path)
            if module.startswith("coreelec_reconciler.")
            and not module.startswith("coreelec_reconciler.domain.")
        )
        for path in (PACKAGE_ROOT / "domain").glob("*.py")
        if any(
            module.startswith("coreelec_reconciler.")
            and not module.startswith("coreelec_reconciler.domain.")
            for module in imported_modules(path)
        )
    }

    assert violations == {}
