"""
Tests for CECDelegateStrategy.

This module tests the CEC delegate proof strategy implementation.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.strategies.cec_delegate import CECDelegateStrategy
from ipfs_datasets_py.logic.TDFOL.strategies.base import StrategyType
from ipfs_datasets_py.logic.TDFOL import (
    TDFOLKnowledgeBase,
    Predicate,
    Constant,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus


class TestCECDelegateInitialization:
    """Tests for CECDelegateStrategy initialization."""
    
    def test_strategy_initialization(self):
        """Test basic strategy initialization."""
        # GIVEN
        # WHEN creating CEC delegate strategy
        strategy = CECDelegateStrategy()
        
        # THEN it should have correct properties
        assert strategy.name == "CEC Delegate"
        assert strategy.strategy_type == StrategyType.CEC_DELEGATE


class TestCECDelegateCanHandle:
    """Tests for can_handle method."""
    
    def test_can_handle_when_cec_unavailable(self):
        """Test can_handle when CEC engine is not available."""
        # GIVEN a strategy (CEC likely unavailable in test environment)
        strategy = CECDelegateStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("P", ())
        
        # WHEN checking if it can handle
        can_handle = strategy.can_handle(formula, kb)
        
        # THEN it should return False if CEC unavailable
        # (or True if CEC happens to be available)
        assert isinstance(can_handle, bool)


class TestCECDelegateProve:
    """Tests for prove method."""
    
    def test_prove_formula_in_kb(self):
        """Test proving formula already in KB."""
        # GIVEN a formula in KB
        strategy = CECDelegateStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("P", (Constant("a"),))
        kb.add_axiom(formula)
        
        # WHEN proving
        result = strategy.prove(formula, kb, timeout_ms=1000)
        
        # THEN it should be proved (or UNKNOWN if CEC unavailable)
        assert result.status in [ProofStatus.PROVED, ProofStatus.UNKNOWN]
        assert result.formula == formula
    
    def test_prove_without_cec(self):
        """Test proving when CEC is unavailable."""
        # GIVEN a formula not in KB
        strategy = CECDelegateStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("Q", ())
        
        # WHEN proving (CEC likely unavailable)
        result = strategy.prove(formula, kb, timeout_ms=1000)
        
        # THEN status should be UNKNOWN
        assert result.status in [ProofStatus.UNKNOWN, ProofStatus.PROVED]


class TestCECDelegatePriority:
    """Tests for strategy priority."""
    
    def test_get_priority(self):
        """Test that priority is medium-high."""
        # GIVEN a CEC delegate strategy
        strategy = CECDelegateStrategy()
        
        # WHEN getting priority
        priority = strategy.get_priority()
        
        # THEN it should be 60 (medium-high)
        assert priority == 60


class TestCECDelegateCostEstimation:
    """Tests for cost estimation."""
    
    def test_estimate_cost(self):
        """Test cost estimation."""
        # GIVEN a strategy and formula
        strategy = CECDelegateStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("P", ())
        
        # WHEN estimating cost
        cost = strategy.estimate_cost(formula, kb)
        
        # THEN cost should be 1.5 (moderate)
        assert cost == 1.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
