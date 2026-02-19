"""
Tests for base ProverStrategy interface.

This module tests the abstract base class and base functionality
for TDFOL proving strategies.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.strategies.base import (
    ProverStrategy,
    StrategyType,
    ProofStep,
)
from ipfs_datasets_py.logic.TDFOL import (
    TDFOLKnowledgeBase,
    Predicate,
    Constant,
)


# Mock strategy for testing
class MockStrategy(ProverStrategy):
    """Mock strategy for testing base functionality."""
    
    def __init__(self, priority: int = 50):
        super().__init__("Mock Strategy", StrategyType.FORWARD_CHAINING)
        self._priority = priority
    
    def can_handle(self, formula, kb):
        return True
    
    def prove(self, formula, kb, timeout_ms=None):
        from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus
        return ProofResult(
            status=ProofStatus.PROVED,
            formula=formula,
            proof_steps=[],
            time_ms=0.0,
            method=self.name
        )
    
    def get_priority(self):
        return self._priority


class TestStrategyType:
    """Tests for StrategyType enum."""
    
    def test_strategy_types_defined(self):
        """Test that all strategy types are defined."""
        # GIVEN strategy type enum
        # WHEN checking available types
        types = [st.value for st in StrategyType]
        
        # THEN all expected types should be present
        assert "forward_chaining" in types
        assert "backward_chaining" in types
        assert "modal_tableaux" in types
        assert "cec_delegate" in types
        assert "bidirectional" in types
        assert "auto" in types


class TestProofStep:
    """Tests for ProofStep dataclass."""
    
    def test_proof_step_creation(self):
        """Test creating a proof step."""
        # GIVEN a formula and justification
        formula = Predicate("P", (Constant("a"),))
        justification = "Applied modus ponens"
        
        # WHEN creating a proof step
        step = ProofStep(
            formula=formula,
            justification=justification,
            rule_name="ModusPonens"
        )
        
        # THEN step should have correct properties
        assert step.formula == formula
        assert step.justification == justification
        assert step.rule_name == "ModusPonens"
        assert step.premises == []
    
    def test_proof_step_with_premises(self):
        """Test proof step with premises."""
        # GIVEN a formula and premises
        formula = Predicate("Q", (Constant("a"),))
        premise1 = Predicate("P", (Constant("a"),))
        premise2 = Predicate("R", (Constant("a"),))
        
        # WHEN creating a proof step with premises
        step = ProofStep(
            formula=formula,
            justification="Applied rule",
            premises=[premise1, premise2]
        )
        
        # THEN premises should be stored
        assert len(step.premises) == 2
        assert premise1 in step.premises
        assert premise2 in step.premises


class TestProverStrategy:
    """Tests for ProverStrategy base class."""
    
    def test_strategy_initialization(self):
        """Test strategy initialization."""
        # GIVEN a mock strategy
        # WHEN creating a strategy
        strategy = MockStrategy()
        
        # THEN it should have correct properties
        assert strategy.name == "Mock Strategy"
        assert strategy.strategy_type == StrategyType.FORWARD_CHAINING
    
    def test_can_handle_method(self):
        """Test can_handle method."""
        # GIVEN a strategy and formula
        strategy = MockStrategy()
        formula = Predicate("P", ())
        kb = TDFOLKnowledgeBase()
        
        # WHEN checking if strategy can handle formula
        can_handle = strategy.can_handle(formula, kb)
        
        # THEN it should return a boolean
        assert isinstance(can_handle, bool)
        assert can_handle is True
    
    def test_prove_method(self):
        """Test prove method."""
        # GIVEN a strategy and formula
        strategy = MockStrategy()
        formula = Predicate("P", ())
        kb = TDFOLKnowledgeBase()
        
        # WHEN proving a formula
        result = strategy.prove(formula, kb, timeout_ms=5000)
        
        # THEN result should have correct properties
        assert result.formula == formula
        assert result.is_proved()
    
    def test_get_priority(self):
        """Test get_priority method."""
        # GIVEN strategies with different priorities
        strategy_low = MockStrategy(priority=10)
        strategy_high = MockStrategy(priority=90)
        
        # WHEN getting priorities
        priority_low = strategy_low.get_priority()
        priority_high = strategy_high.get_priority()
        
        # THEN priorities should be correct
        assert priority_low == 10
        assert priority_high == 90
        assert priority_high > priority_low
    
    def test_estimate_cost_default(self):
        """Test default cost estimation."""
        # GIVEN a strategy
        strategy = MockStrategy()
        formula = Predicate("P", ())
        kb = TDFOLKnowledgeBase()
        
        # WHEN estimating cost (default implementation)
        cost = strategy.estimate_cost(formula, kb)
        
        # THEN default cost should be 1.0
        assert cost == 1.0
    
    def test_string_representation(self):
        """Test string representation of strategy."""
        # GIVEN a strategy
        strategy = MockStrategy()
        
        # WHEN getting string representation
        str_repr = str(strategy)
        
        # THEN it should include name and type
        assert "Mock Strategy" in str_repr
        assert "forward_chaining" in str_repr
    
    def test_repr(self):
        """Test repr of strategy."""
        # GIVEN a strategy
        strategy = MockStrategy()
        
        # WHEN getting repr
        repr_str = repr(strategy)
        
        # THEN it should be informative
        assert "ProverStrategy" in repr_str
        assert "Mock Strategy" in repr_str
        assert "StrategyType" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
