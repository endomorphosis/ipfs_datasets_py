"""
Tests for StrategySelector.

This module tests the automatic strategy selection functionality.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
from ipfs_datasets_py.logic.TDFOL.strategies.base import ProverStrategy, StrategyType
from ipfs_datasets_py.logic.TDFOL import (
    TDFOLKnowledgeBase,
    Predicate,
    DeonticFormula,
    DeonticOperator,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus


# Mock strategy for testing
class MockHighPriorityStrategy(ProverStrategy):
    """Mock high priority strategy."""
    
    def __init__(self):
        super().__init__("Mock High Priority", StrategyType.FORWARD_CHAINING)
    
    def can_handle(self, formula, kb):
        return True
    
    def prove(self, formula, kb, timeout_ms=None):
        return ProofResult(
            status=ProofStatus.PROVED,
            formula=formula,
            proof_steps=[],
            time_ms=0.0,
            method=self.name
        )
    
    def get_priority(self):
        return 90


class MockLowPriorityStrategy(ProverStrategy):
    """Mock low priority strategy."""
    
    def __init__(self):
        super().__init__("Mock Low Priority", StrategyType.BACKWARD_CHAINING)
    
    def can_handle(self, formula, kb):
        return True
    
    def prove(self, formula, kb, timeout_ms=None):
        return ProofResult(
            status=ProofStatus.PROVED,
            formula=formula,
            proof_steps=[],
            time_ms=0.0,
            method=self.name
        )
    
    def get_priority(self):
        return 30


class TestStrategySelectorInitialization:
    """Tests for StrategySelector initialization."""
    
    def test_initialization_with_strategies(self):
        """Test initialization with provided strategies."""
        # GIVEN strategies
        strategies = [MockLowPriorityStrategy(), MockHighPriorityStrategy()]
        
        # WHEN creating selector
        selector = StrategySelector(strategies)
        
        # THEN selector should be initialized
        assert len(selector.strategies) == 2
        # Strategies should be sorted by priority (high first)
        assert selector.strategies[0].get_priority() == 90
        assert selector.strategies[1].get_priority() == 30
    
    def test_initialization_with_default_strategies(self):
        """Test initialization with default strategies."""
        # GIVEN
        # WHEN creating selector without strategies
        selector = StrategySelector()
        
        # THEN it should have default strategies
        assert len(selector.strategies) > 0


class TestStrategySelectorSelection:
    """Tests for strategy selection."""
    
    def test_select_high_priority_strategy(self):
        """Test that high priority strategy is selected."""
        # GIVEN strategies with different priorities
        strategies = [MockLowPriorityStrategy(), MockHighPriorityStrategy()]
        selector = StrategySelector(strategies)
        formula = Predicate("P", ())
        kb = TDFOLKnowledgeBase()
        
        # WHEN selecting strategy
        selected = selector.select_strategy(formula, kb)
        
        # THEN high priority strategy should be selected
        assert selected.get_priority() == 90
        assert selected.name == "Mock High Priority"
    
    def test_select_with_no_applicable_strategies(self):
        """Test fallback when no strategies applicable."""
        # GIVEN a strategy that can't handle anything
        class NonApplicableStrategy(ProverStrategy):
            def __init__(self):
                super().__init__("Non Applicable", StrategyType.MODAL_TABLEAUX)
            
            def can_handle(self, formula, kb):
                return False
            
            def prove(self, formula, kb, timeout_ms=None):
                return ProofResult(ProofStatus.UNKNOWN, formula, [], 0.0, self.name)
            
            def get_priority(self):
                return 50
        
        selector = StrategySelector([NonApplicableStrategy(), MockHighPriorityStrategy()])
        formula = Predicate("P", ())
        kb = TDFOLKnowledgeBase()
        
        # WHEN selecting strategy
        selected = selector.select_strategy(formula, kb)
        
        # THEN fallback should be used
        assert selected is not None


class TestStrategySelectorMultiple:
    """Tests for multiple strategy selection."""
    
    def test_select_multiple_strategies(self):
        """Test selecting multiple strategies."""
        # GIVEN multiple strategies
        strategies = [MockLowPriorityStrategy(), MockHighPriorityStrategy()]
        selector = StrategySelector(strategies)
        formula = Predicate("P", ())
        kb = TDFOLKnowledgeBase()
        
        # WHEN selecting multiple strategies
        selected = selector.select_multiple(formula, kb, max_strategies=2)
        
        # THEN should return list of strategies in priority order
        assert len(selected) <= 2
        if len(selected) == 2:
            assert selected[0].get_priority() >= selected[1].get_priority()


class TestStrategySelectorUtilities:
    """Tests for utility methods."""
    
    def test_get_strategy_info(self):
        """Test getting strategy information."""
        # GIVEN a selector with strategies
        strategies = [MockLowPriorityStrategy(), MockHighPriorityStrategy()]
        selector = StrategySelector(strategies)
        
        # WHEN getting strategy info
        info = selector.get_strategy_info()
        
        # THEN it should return list of info dicts
        assert isinstance(info, list)
        assert len(info) == 2
        assert all("name" in s and "type" in s and "priority" in s for s in info)
    
    def test_add_strategy(self):
        """Test adding a new strategy."""
        # GIVEN a selector
        selector = StrategySelector([MockLowPriorityStrategy()])
        initial_count = len(selector.strategies)
        
        # WHEN adding a strategy
        selector.add_strategy(MockHighPriorityStrategy())
        
        # THEN strategy count should increase
        assert len(selector.strategies) == initial_count + 1
        # And strategies should be re-sorted by priority
        assert selector.strategies[0].get_priority() >= selector.strategies[-1].get_priority()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
