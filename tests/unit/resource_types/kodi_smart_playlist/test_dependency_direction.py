import ast
from pathlib import Path


def test_resource_type_execution_does_not_import_execution_package() -> None:
    path = (
        Path(__file__).parents[4]
        / "src/coreelec_reconciler/resource_types/kodi_smart_playlist/execution.py"
    )
    tree = ast.parse(path.read_text())
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(
        name.startswith("coreelec_reconciler.execution") for name in imported
    )
