"""Zero-config metadata checks for proof reuse."""

from __future__ import annotations

from pathlib import Path

import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_pytest11_bridge_is_declared_once_in_project_metadata() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pytest11 = pyproject["project"]["entry-points"]["pytest11"]
    assert pytest11 == {
        "ipfs-datasets-proof-reuse": "ipfs_datasets_py.pytest_proof_reuse",
    }


def test_collection_hook_is_module_scoped() -> None:
    source = (PROJECT_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "\ndef pytest_collection_modifyitems(" in source
