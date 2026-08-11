"""Regression coverage for the datasets-owned pytest bootstrap."""

from __future__ import annotations

import ast
import importlib.metadata
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_source_fallback_is_a_conditional_module_level_plugin_declaration() -> None:
    tree = ast.parse((PROJECT_ROOT / "conftest.py").read_text(encoding="utf-8"))
    assert "pytest_load_initial_conftests" not in (PROJECT_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "pytest_load_initial_conftests"
        for node in ast.walk(tree)
    )
    declarations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "pytest_plugins" for target in node.targets)
    ]
    assert len(declarations) == 1
    # A declaration nested in a function would be too late for pytest's
    # plugin discovery.  The module-level conditional expression avoids
    # duplicating an enabled installed entry point.
    declaration = declarations[0]
    assert declaration in tree.body
    assert isinstance(declaration.value, ast.IfExp)


def test_root_conftest_never_installs_pytest_dependencies() -> None:
    source = (PROJECT_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "_ensure_pytest_plugin" not in source
    assert "install_python_dependency" not in source


def test_source_fallback_defers_optional_absence_to_the_cold_bridge() -> None:
    source = (PROJECT_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "_datasets_bridge_entry_point_available" in source
    assert 'os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD")' in source
    assert "importlib.util.find_spec" not in source

    bridge = (PROJECT_ROOT / "ipfs_datasets_py" / "pytest_proof_reuse.py").read_text(
        encoding="utf-8"
    )
    assert "spec.origin is None" in bridge
    assert "spec.submodule_search_locations is not None" in bridge
    assert "spec.loader" not in bridge


def test_autoload_disabled_source_fallback_ignores_installed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    installed_bridge = importlib.metadata.EntryPoint(
        name="ipfs-datasets-proof-reuse",
        value="ipfs_datasets_py.pytest_proof_reuse",
        group="pytest11",
    )
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda: importlib.metadata.EntryPoints((installed_bridge,)),
    )
    namespace: dict[str, object] = {}
    source = (PROJECT_ROOT / "conftest.py").read_text(encoding="utf-8")
    exec(compile(source, "conftest.py", "exec"), namespace)
    assert namespace["pytest_plugins"] == ("ipfs_datasets_py.pytest_proof_reuse",)
