import ast
import importlib
from pathlib import Path

import coreelec_reconciler.transports as transports
from coreelec_reconciler.transports import remote_ownership

PACKAGE_ROOT = Path(__file__).parents[2] / "src" / "coreelec_reconciler"


def test_adapters_never_import_execution_modules() -> None:
    violations: dict[str, tuple[str, ...]] = {}
    for path in sorted((PACKAGE_ROOT / "adapters").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if module.startswith("coreelec_reconciler.execution") or (
                node.level > 0 and module.startswith("execution")
            ):
                imports.add(("." * node.level) + module)
            if (
                module == "coreelec_reconciler" or (node.level > 0 and module == "")
            ) and any(alias.name == "execution" for alias in node.names):
                imports.add(("." * node.level) + module + ".execution")
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name.startswith("coreelec_reconciler.execution")
        )
        if imports:
            violations[str(path.relative_to(PACKAGE_ROOT))] = tuple(sorted(imports))

    assert violations == {}


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
