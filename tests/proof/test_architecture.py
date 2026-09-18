"""Evidence-only standard-library AST import-boundary test."""

import ast
from pathlib import Path

import pytest

PURE_MODULES = ("domain.py", "planning.py")
FORBIDDEN_ROOTS = {"yaml", "pydantic", "paramiko"}
FORBIDDEN_INTERNAL = {
    "coreelec_reconciler.cli",
    "coreelec_reconciler.config",
    "coreelec_reconciler.transports",
}
FORBIDDEN_STDLIB_ADAPTERS = {"pathlib", "socket", "subprocess", "urllib"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("module_name", PURE_MODULES)
def test_pure_layers_do_not_import_infrastructure(module_name: str) -> None:
    package = Path(__file__).parents[2] / "src" / "coreelec_reconciler"
    imports = imported_modules(package / module_name)
    roots = {name.split(".", 1)[0] for name in imports}
    assert not roots & FORBIDDEN_ROOTS
    assert not roots & FORBIDDEN_STDLIB_ADAPTERS
    assert not imports & FORBIDDEN_INTERNAL
