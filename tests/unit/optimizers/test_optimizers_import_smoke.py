"""Smoke tests for the optimizers package.

Goal: catch import-time breakages early without exercising heavy runtime paths.

These tests should remain fast and not require network access.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "ipfs_datasets_py.optimizers",
        "ipfs_datasets_py.optimizers.agentic",
        "ipfs_datasets_py.optimizers.common",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer",
        "ipfs_datasets_py.optimizers.graphrag",
    ],
)
def test_import_smoke(module_name: str) -> None:
    """Core optimizer packages should be importable."""
    importlib.import_module(module_name)
