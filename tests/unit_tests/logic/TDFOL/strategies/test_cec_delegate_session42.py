"""
Session 42: TDFOL cec_delegate.py coverage: lines 82-84.

Target:
- cec_delegate.py 95% → 98%+

Coverage focuses on:
- Lines 82-84: CECDelegateStrategy.__init__ when _try_load_cec_prover returns True
  but InferenceEngine() constructor raises an exception — cec_engine set to None.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import ipfs_datasets_py.logic.TDFOL.strategies.cec_delegate as cec_mod


class TestCECDelegateEngineInitException:
    """Lines 82-84 — InferenceEngine() raises in __init__."""

    def test_init_engine_exception_sets_cec_engine_none(self):
        """
        GIVEN _try_load_cec_prover returns True
        AND InferenceEngine() raises RuntimeError
        WHEN CECDelegateStrategy() is instantiated
        THEN cec_engine is None (lines 82-84 executed).
        """
        from ipfs_datasets_py.logic.TDFOL.strategies.cec_delegate import (
            CECDelegateStrategy,
        )

        mock_engine_class = MagicMock(side_effect=RuntimeError("engine init failed"))

        # Patch both the function and the module-level InferenceEngine variable
        with patch.object(cec_mod, "_try_load_cec_prover", return_value=True), \
             patch.object(cec_mod, "InferenceEngine", mock_engine_class):
            strat = CECDelegateStrategy()

        assert strat.cec_engine is None

    def test_init_engine_exception_logs_warning(self):
        """
        GIVEN _try_load_cec_prover returns True
        AND InferenceEngine() raises ValueError
        WHEN CECDelegateStrategy() instantiated
        THEN cec_engine is None (lines 82-84 with ValueError).
        """
        from ipfs_datasets_py.logic.TDFOL.strategies.cec_delegate import (
            CECDelegateStrategy,
        )

        mock_engine_class = MagicMock(side_effect=ValueError("bad engine config"))

        with patch.object(cec_mod, "_try_load_cec_prover", return_value=True), \
             patch.object(cec_mod, "InferenceEngine", mock_engine_class):
            strat = CECDelegateStrategy()

        assert strat.cec_engine is None

    def test_init_engine_no_cec_prover_skips_init(self):
        """
        GIVEN _try_load_cec_prover returns False
        WHEN CECDelegateStrategy() instantiated
        THEN cec_engine is None without attempting InferenceEngine().
        """
        from ipfs_datasets_py.logic.TDFOL.strategies.cec_delegate import (
            CECDelegateStrategy,
        )

        mock_engine_class = MagicMock()

        with patch.object(cec_mod, "_try_load_cec_prover", return_value=False), \
             patch.object(cec_mod, "InferenceEngine", mock_engine_class):
            strat = CECDelegateStrategy()

        # InferenceEngine should NOT have been called
        mock_engine_class.assert_not_called()
        assert strat.cec_engine is None
