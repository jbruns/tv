import ast
import importlib
from functools import cache
from pathlib import Path

import coreelec_reconciler.transports as transports
from coreelec_reconciler.transports import remote_ownership

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "coreelec_reconciler"
NETWORK_MODULES = {"socket", "urllib", "httpx", "requests", "paramiko"}
FIXTURE_ROOT = Path(__file__).parent / "fixtures"


@cache
def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def adapter_execution_import_violations(
    adapter_root: Path,
) -> dict[str, tuple[str, ...]]:
    violations: dict[str, tuple[str, ...]] = {}
    for path in sorted(adapter_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("coreelec_reconciler.execution") or (
                    node.level > 0 and module.startswith("execution")
                ):
                    imports.add(("." * node.level) + module)
                if (
                    module == "coreelec_reconciler" or (node.level > 0 and module == "")
                ) and any(alias.name == "execution" for alias in node.names):
                    imports.add(("." * node.level) + module + ".execution")
            elif isinstance(node, ast.Import):
                imports.update(
                    alias.name
                    for alias in node.names
                    if alias.name.startswith("coreelec_reconciler.execution")
                )
        if imports:
            violations[str(path.relative_to(adapter_root))] = tuple(sorted(imports))
    return violations


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


def test_only_bootstrap_imports_concrete_production_adapters() -> None:
    violations = {
        path.relative_to(PACKAGE_ROOT): sorted(
            module
            for module in imported_modules(path)
            if module.startswith("coreelec_reconciler.adapters")
        )
        for path in PACKAGE_ROOT.rglob("*.py")
        if path.name != "bootstrap.py"
        and any(
            module.startswith("coreelec_reconciler.adapters")
            for module in imported_modules(path)
        )
    }

    assert violations == {}


def test_application_and_cli_do_not_instantiate_concrete_adapters() -> None:
    concrete_names = {
        "EnvironmentSecretResolver",
        "MappingHostKeyResolver",
        "ParamikoManagedFiles",
        "ParamikoSessionFactory",
        "RunStore",
    }
    violations = {
        path.relative_to(PACKAGE_ROOT): sorted(
            node.func.id
            for node in ast.walk(
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            )
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in concrete_names
        )
        for directory in ("application", "cli")
        for path in (PACKAGE_ROOT / directory).glob("*.py")
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in concrete_names
            for node in ast.walk(
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            )
        )
    }

    assert violations == {}


def network_import_violations(package_root: Path) -> dict[Path, set[str]]:
    return {
        path.relative_to(package_root): modules & NETWORK_MODULES
        for path in package_root.rglob("*.py")
        if (
            modules := {
                module.split(".", maxsplit=1)[0] for module in imported_modules(path)
            }
            & NETWORK_MODULES
        )
        and "adapters" not in path.parts
        and path != package_root / "bootstrap.py"
    }


def test_network_modules_are_limited_to_approved_boundaries() -> None:
    assert network_import_violations(PACKAGE_ROOT) == {}


def test_network_guard_rejects_cli_and_allows_adapter_and_bootstrap(
    tmp_path: Path,
) -> None:
    package = tmp_path / "coreelec_reconciler"
    (package / "cli").mkdir(parents=True)
    (package / "adapters").mkdir()
    (package / "cli" / "bad.py").write_text("import socket\nimport paramiko\n")
    (package / "adapters" / "allowed.py").write_text("import socket\n")
    (package / "bootstrap.py").write_text("import paramiko\n")

    assert network_import_violations(package) == {
        Path("cli/bad.py"): {"socket", "paramiko"}
    }


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


def test_adapters_never_import_execution_modules() -> None:
    assert adapter_execution_import_violations(PACKAGE_ROOT / "adapters") == {}


def test_adapter_execution_guard_recurses_into_nested_packages() -> None:
    fixture_root = FIXTURE_ROOT / "adapter_tree"

    assert adapter_execution_import_violations(fixture_root) == {
        "nested/forbidden.py": ("coreelec_reconciler.execution",)
    }


def test_remote_ownership_contract_has_one_lower_level_definition() -> None:
    authority = importlib.import_module("coreelec_reconciler.execution.authority")

    assert transports.AuthorityBlocked is remote_ownership.AuthorityBlocked
    assert transports.AuthorityConflict is remote_ownership.AuthorityConflict
    assert transports.RemoteObject is remote_ownership.RemoteObject
    assert transports.RemoteAuthorityBackend is remote_ownership.RemoteAuthorityBackend
    assert not hasattr(authority, "AuthorityBlocked")
    assert not hasattr(authority, "AuthorityConflict")
    assert not hasattr(authority, "RemoteObject")
    assert not hasattr(authority, "RemoteAuthorityBackend")
