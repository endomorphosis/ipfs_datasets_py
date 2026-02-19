"""
Tests for ModalTableauxStrategy.

This module tests the modal tableaux proof strategy implementation.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
from ipfs_datasets_py.logic.TDFOL.strategies.base import StrategyType
from ipfs_datasets_py.logic.TDFOL import (
    TDFOLKnowledgeBase,
    Predicate,
    DeonticFormula,
    DeonticOperator,
    TemporalFormula,
    TemporalOperator,
    Constant,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus


class TestModalTableauxInitialization:
    """Tests for ModalTableauxStrategy initialization."""
    
    def test_strategy_initialization(self):
        """Test basic strategy initialization."""
        # GIVEN
        # WHEN creating modal tableaux strategy
        strategy = ModalTableauxStrategy()
        
        # THEN it should have correct properties
        assert strategy.name == "Modal Tableaux"
        assert strategy.strategy_type == StrategyType.MODAL_TABLEAUX


class TestModalTableauxCanHandle:
    """Tests for can_handle method."""
    
    def test_can_handle_deontic_formula(self):
        """Test that modal tableaux can handle deontic formulas."""
        # GIVEN a deontic formula
        strategy = ModalTableauxStrategy()
        kb = TDFOLKnowledgeBase()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        
        # WHEN checking if strategy can handle it
        can_handle = strategy.can_handle(formula, kb)
        
        # THEN it should return True
        assert can_handle is True
    
    def test_can_handle_temporal_formula(self):
        """Test that modal tableaux can handle temporal formulas."""
        # GIVEN a temporal formula
        strategy = ModalTableauxStrategy()
        kb = TDFOLKnowledgeBase()
        formula = TemporalFormula(TemporalOperator.ALWAYS, Predicate("Q", ()))
        
        # WHEN checking if strategy can handle it
        can_handle = strategy.can_handle(formula, kb)
        
        # THEN it should return True
        assert can_handle is True
    
    def test_cannot_handle_non_modal_formula(self):
        """Test that non-modal formulas return False."""
        # GIVEN a non-modal formula
        strategy = ModalTableauxStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("R", (Constant("a"),))
        
        # WHEN checking if strategy can handle it
        can_handle = strategy.can_handle(formula, kb)
        
        # THEN it should return False
        assert can_handle is False


class TestModalTableauxProve:
    """Tests for prove method."""
    
    def test_prove_deontic_in_kb(self):
        """Test proving deontic formula already in KB."""
        # GIVEN a deontic formula in KB
        strategy = ModalTableauxStrategy()
        kb = TDFOLKnowledgeBase()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        kb.add_axiom(formula)
        
        # WHEN proving
        result = strategy.prove(formula, kb, timeout_ms=1000)
        
        # THEN it should be proved
        assert result.status == ProofStatus.PROVED
        assert result.formula == formula
    
    def test_prove_without_shadowprover(self):
        """Test basic modal reasoning without ShadowProver."""
        # GIVEN a formula not in KB
        strategy = ModalTableauxStrategy()
        kb = TDFOLKnowledgeBase()
        formula = DeonticFormula(DeonticOperator.PERMISSION, Predicate("Q", ()))
        
        # WHEN proving (ShadowProver likely unavailable)
        result = strategy.prove(formula, kb, timeout_ms=1000)
        
        # THEN status should be UNKNOWN (can't prove without advanced tableaux)
        assert result.status == ProofStatus.UNKNOWN
        assert "not available" in result.message.lower() or "progress" in result.message.lower()


class TestModalTableauxPriority:
    """Tests for strategy priority."""
    
    def test_get_priority(self):
        """Test that priority is very high."""
        # GIVEN a modal tableaux strategy
        strategy = ModalTableauxStrategy()
        
        # WHEN getting priority
        priority = strategy.get_priority()
        
        # THEN it should be 80 (very high)
        assert priority == 80


class TestModalTableauxCostEstimation:
    """Tests for cost estimation."""
    
    def test_estimate_cost_simple_formula(self):
        """Test cost estimation for simple modal formula."""
        # GIVEN a simple deontic formula
        strategy = ModalTableauxStrategy()
        kb = TDFOLKnowledgeBase()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        
        # WHEN estimating cost
        cost = strategy.estimate_cost(formula, kb)
        
        # THEN cost should be positive
        assert cost > 0.0
        assert cost >= 2.0  # Base cost for modal tableaux


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
