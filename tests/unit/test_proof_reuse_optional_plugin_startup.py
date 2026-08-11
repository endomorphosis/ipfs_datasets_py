"""Startup behaviour when the optional accelerator is unavailable."""

from __future__ import annotations

import importlib.util


def test_bridge_import_does_not_require_the_accelerator() -> None:
    spec = importlib.util.find_spec("ipfs_datasets_py.pytest_proof_reuse")
    assert spec is not None
