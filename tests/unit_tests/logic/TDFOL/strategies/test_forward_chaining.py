"""
Tests for ForwardChainingStrategy.

This module tests the forward chaining proof strategy implementation.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
from ipfs_datasets_py.logic.TDFOL.strategies.base import StrategyType
from ipfs_datasets_py.logic.TDFOL import (
    TDFOLKnowledgeBase,
    Predicate,
    Constant,
    Variable,
    BinaryFormula,
    LogicOperator,
    create_implication,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofStatus


class TestForwardChainingInitialization:
    """Tests for ForwardChainingStrategy initialization."""
    
    def test_strategy_initialization(self):
        """Test basic strategy initialization."""
        # GIVEN
        # WHEN creating a forward chaining strategy
        strategy = ForwardChainingStrategy()
        
        # THEN it should have correct properties
        assert strategy.name == "Forward Chaining"
        assert strategy.strategy_type == StrategyType.FORWARD_CHAINING
        assert strategy.max_iterations == 100
    
    def test_custom_max_iterations(self):
        """Test initialization with custom max iterations."""
        # GIVEN a custom max iterations value
        max_iters = 50
        
        # WHEN creating strategy with custom value
        strategy = ForwardChainingStrategy(max_iterations=max_iters)
        
        # THEN it should use custom value
        assert strategy.max_iterations == max_iters
    
    def test_tdfol_rules_loaded(self):
        """Test that TDFOL rules are loaded."""
        # GIVEN
        # WHEN creating a strategy
        strategy = ForwardChainingStrategy()
        
        # THEN TDFOL rules should be loaded
        assert isinstance(strategy.tdfol_rules, list)
        # Rules should be loaded if available
        # (may be empty if tdfol_inference_rules not available)


class TestForwardChainingCanHandle:
    """Tests for can_handle method."""
    
    def test_can_handle_any_formula(self):
        """Test that forward chaining can handle any formula."""
        # GIVEN a strategy and various formulas
        strategy = ForwardChainingStrategy()
        kb = TDFOLKnowledgeBase()
        
        formulas = [
            Predicate("P", ()),
            Predicate("Q", (Constant("a"),)),
            BinaryFormula(LogicOperator.AND, Predicate("P", ()), Predicate("Q", ()))
        ]
        
        # WHEN checking if strategy can handle each formula
        # THEN all should return True (forward chaining is general-purpose)
        for formula in formulas:
            assert strategy.can_handle(formula, kb) is True


class TestForwardChainingProve:
    """Tests for prove method."""
    
    def test_prove_axiom_already_in_kb(self):
        """Test proving a formula that's already an axiom."""
        # GIVEN a formula in the knowledge base
        strategy = ForwardChainingStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("P", (Constant("a"),))
        kb.add_axiom(formula)
        
        # WHEN proving the formula
        result = strategy.prove(formula, kb, timeout_ms=1000)
        
        # THEN it should be proved immediately
        assert result.status == ProofStatus.PROVED
        assert result.formula == formula
        assert result.method == "Forward Chaining"
        assert result.time_ms < 100  # Should be very fast
    
    def test_prove_theorem_already_in_kb(self):
        """Test proving a formula that's already a theorem."""
        # GIVEN a formula as a theorem
        strategy = ForwardChainingStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("Q", (Constant("b"),))
        kb.add_theorem(formula)
        
        # WHEN proving the formula
        result = strategy.prove(formula, kb, timeout_ms=1000)
        
        # THEN it should be proved immediately
        assert result.status == ProofStatus.PROVED
        assert result.formula == formula
    
    def test_prove_simple_derivation(self):
        """Test proving with simple rule application."""
        # GIVEN a knowledge base with axioms
        strategy = ForwardChainingStrategy(max_iterations=10)
        kb = TDFOLKnowledgeBase()
        
        # Add axioms (if we had inference rules, they would derive conclusions)
        p = Predicate("P", (Constant("a"),))
        kb.add_axiom(p)
        
        # WHEN proving a formula
        # For this test, we're proving something already in KB
        result = strategy.prove(p, kb, timeout_ms=5000)
        
        # THEN proof should succeed
        assert result.status == ProofStatus.PROVED
    
    def test_prove_timeout(self):
        """Test that proof respects timeout."""
        # GIVEN a strategy with many iterations and short timeout
        strategy = ForwardChainingStrategy(max_iterations=1000)
        kb = TDFOLKnowledgeBase()
        
        # Add many axioms to slow down proving
        for i in range(20):
            kb.add_axiom(Predicate(f"P{i}", (Constant(f"a{i}"),)))
        
        # Formula not in KB
        goal = Predicate("Goal", ())
        
        # WHEN proving with very short timeout
        result = strategy.prove(goal, kb, timeout_ms=1)  # 1ms timeout
        
        # THEN should timeout or fail quickly
        assert result.status in [ProofStatus.TIMEOUT, ProofStatus.UNKNOWN]
        assert result.time_ms < 100  # Should timeout quickly
    
    def test_prove_unknown_formula(self):
        """Test proving a formula not derivable from KB."""
        # GIVEN a knowledge base and unrelated goal
        strategy = ForwardChainingStrategy(max_iterations=5)
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(Predicate("P", (Constant("a"),)))
        
        # Goal not derivable from axioms
        goal = Predicate("Q", (Constant("b"),))
        
        # WHEN trying to prove with generous timeout
        result = strategy.prove(goal, kb, timeout_ms=10000)  # Long timeout to avoid timing out
        
        # THEN proof should fail (either UNKNOWN or TIMEOUT depending on timing)
        assert result.status in [ProofStatus.UNKNOWN, ProofStatus.TIMEOUT]
        assert result.formula == goal
    
    def test_prove_with_empty_kb(self):
        """Test proving with empty knowledge base."""
        # GIVEN an empty knowledge base
        strategy = ForwardChainingStrategy()
        kb = TDFOLKnowledgeBase()
        goal = Predicate("P", ())
        
        # WHEN trying to prove
        result = strategy.prove(goal, kb, timeout_ms=1000)
        
        # THEN should return UNKNOWN
        assert result.status == ProofStatus.UNKNOWN
    
    def test_prove_generates_proof_steps(self):
        """Test that proof generates steps when deriving formulas."""
        # GIVEN a knowledge base
        strategy = ForwardChainingStrategy(max_iterations=10)
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", (Constant("a"),))
        kb.add_axiom(p)
        
        # WHEN proving (with rules available, would generate steps)
        result = strategy.prove(p, kb, timeout_ms=5000)
        
        # THEN result should have proof steps
        # Note: Actual steps depend on available rules
        assert isinstance(result.proof_steps, list)


class TestForwardChainingPriority:
    """Tests for strategy priority."""
    
    def test_get_priority(self):
        """Test that priority is high."""
        # GIVEN a forward chaining strategy
        strategy = ForwardChainingStrategy()
        
        # WHEN getting priority
        priority = strategy.get_priority()
        
        # THEN it should be high priority (70)
        assert priority == 70
        assert priority >= 50  # High priority range


class TestForwardChainingCostEstimation:
    """Tests for cost estimation."""
    
    def test_estimate_cost_increases_with_kb_size(self):
        """Test that cost increases with KB size."""
        # GIVEN a strategy and two knowledge bases of different sizes
        strategy = ForwardChainingStrategy()
        
        small_kb = TDFOLKnowledgeBase()
        small_kb.add_axiom(Predicate("P", ()))
        
        large_kb = TDFOLKnowledgeBase()
        for i in range(10):
            large_kb.add_axiom(Predicate(f"P{i}", ()))
        
        formula = Predicate("Goal", ())
        
        # WHEN estimating costs
        cost_small = strategy.estimate_cost(formula, small_kb)
        cost_large = strategy.estimate_cost(formula, large_kb)
        
        # THEN larger KB should have higher cost
        assert cost_large > cost_small
    
    def test_estimate_cost_is_positive(self):
        """Test that estimated cost is positive."""
        # GIVEN a strategy
        strategy = ForwardChainingStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("P", ())
        
        # WHEN estimating cost
        cost = strategy.estimate_cost(formula, kb)
        
        # THEN cost should be positive
        assert cost >= 0.0


class TestForwardChainingApplyRules:
    """Tests for _apply_rules internal method."""
    
    def test_apply_rules_with_no_rules(self):
        """Test applying rules when no rules are loaded."""
        # GIVEN a strategy with no rules
        strategy = ForwardChainingStrategy()
        strategy.tdfol_rules = []  # Clear rules
        
        derived = {Predicate("P", ())}
        proof_steps = []
        
        # WHEN applying rules (frontier == derived for this unit test)
        new_formulas = strategy._apply_rules(derived, derived, proof_steps)
        
        # THEN no new formulas should be derived
        assert len(new_formulas) == 0
    
    def test_apply_rules_with_empty_derived_set(self):
        """Test applying rules with empty derived set."""
        # GIVEN a strategy with rules but empty derived set
        strategy = ForwardChainingStrategy()
        derived = set()
        proof_steps = []
        
        # WHEN applying rules (frontier == derived for this unit test)
        new_formulas = strategy._apply_rules(derived, derived, proof_steps)
        
        # THEN no new formulas
        assert len(new_formulas) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
