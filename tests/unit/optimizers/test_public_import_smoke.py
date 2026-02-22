"""Smoke test: all public symbols in graphrag/__init__.py are importable.

This catches any import-time breakage in new exports before they reach CI.
"""
from __future__ import annotations

import importlib

import pytest


def _get_graphrag_all():
    mod = importlib.import_module("ipfs_datasets_py.optimizers.graphrag")
    return list(getattr(mod, "__all__", []))


class TestGraphragPublicImports:
    """Every name in graphrag.__all__ must be importable without error."""

    @pytest.mark.parametrize("symbol", _get_graphrag_all())
    def test_symbol_importable(self, symbol):
        import ipfs_datasets_py.optimizers.graphrag as pkg
        obj = getattr(pkg, symbol, None)
        assert obj is not None, f"{symbol!r} is in __all__ but not importable from graphrag"

    def test_all_list_is_nonempty(self):
        symbols = _get_graphrag_all()
        assert len(symbols) > 10, "graphrag.__all__ seems suspiciously short"


class TestLogicTheoremPublicImports:
    """Every name exported by logic_theorem_optimizer package is importable."""

    def test_logic_theorem_optimizer_importable(self):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer  # noqa: F401
        assert LogicTheoremOptimizer is not None

    def test_logic_optimizer_cli_importable(self):
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.cli_wrapper import LogicOptimizerCLI  # noqa: F401
        assert LogicOptimizerCLI is not None
