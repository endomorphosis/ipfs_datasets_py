"""Lazy namespace and submodule_registry coverage for logic.tactician."""

from __future__ import annotations

import importlib
import sys


def test_logic_namespace_exposes_tactician_lazily() -> None:
    # Ensure a clean attribute miss path for tactician when possible.
    logic = importlib.import_module("ipfs_datasets_py.logic")
    assert "tactician" in logic._SUBMODULE_EXPORTS
    assert "tactician" in logic.__all__
    module = logic.tactician
    assert module.__name__ == "ipfs_datasets_py.logic.tactician"
    assert module.TACTICIAN_INTERFACE == "ipfs_datasets_py.logic.tactician@1"
    assert module.LogicTactician is not None


def test_tactician_package_exports_are_lazy() -> None:
    # Import package without pulling adapters (which may load legal processors).
    pkg_name = "ipfs_datasets_py.logic.tactician"
    adapters_name = f"{pkg_name}.adapters"
    # Drop submodule modules to exercise __getattr__.
    for key in list(sys.modules):
        if key.startswith(pkg_name + "."):
            del sys.modules[key]
    if pkg_name in sys.modules:
        del sys.modules[pkg_name]

    pkg = importlib.import_module(pkg_name)
    assert adapters_name not in sys.modules
    # Accessing models must not import the adapters submodule.
    _ = pkg.TacticianGoal
    assert adapters_name not in sys.modules
    assert f"{pkg_name}.models" in sys.modules
    # Adapters remain unloaded until explicitly requested.
    _ = pkg.LogicTactician
    assert adapters_name not in sys.modules


def test_submodule_registry_records_tactician_without_eager_import() -> None:
    from ipfs_datasets_py.logic.submodule_registry import (
        logic_integration_manifest,
        logic_submodule_names,
        logic_submodule_spec,
    )

    assert "tactician" in logic_submodule_names()
    spec = logic_submodule_spec("tactician")
    assert spec.module == "ipfs_datasets_py.logic.tactician"
    assert spec.required is True
    assert "LogicTactician" in spec.public_symbols
    assert "TACTICIAN_INTERFACE" in spec.public_symbols
    assert "Lazy" in spec.notes or "lazy" in spec.notes.lower()

    manifest = logic_integration_manifest()
    names = {entry["name"] for entry in manifest["submodules"]}
    assert "tactician" in names
