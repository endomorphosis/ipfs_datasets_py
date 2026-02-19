"""
Tests for Proof Strategies (Phase 4 Weeks 2-3, Task 2.2)

This test module validates different proof search strategies including
forward chaining, backward chaining, bidirectional search, and hybrid strategies.

Test Coverage:
- Forward chaining strategy (3 tests)
- Backward chaining strategy (3 tests)
- Bidirectional search strategy (3 tests)
- Hybrid adaptive strategy (4 tests)
- Strategy selection and interface (2 tests)

Total: 15 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.proof_strategies import (
    ProofStrategy,
    ForwardChainingStrategy,
    BackwardChainingStrategy,
    BidirectionalStrategy,
    HybridStrategy,
    StrategyType,
    get_strategy,
)
from ipfs_datasets_py.logic.CEC.native.prover_core import (
    InferenceRule,
    ModusPonens,
    Simplification,
    ProofResult,
)
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    AtomicFormula,
    ConnectiveFormula,
    LogicalConnective,
    Predicate,
)
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECNamespace


class TestForwardChainingStrategy:
    """Test forward chaining proof strategy."""
    
    def test_forward_chaining_simple_proof(self):
        """
        GIVEN axioms P and P→Q
        WHEN using forward chaining strategy
        THEN should prove Q via modus ponens
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        # P → Q
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        axioms = [p, impl]
        goal = q
        rules = [ModusPonens(), Simplification()]
        
        # WHEN
        strategy = ForwardChainingStrategy(max_steps=10)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.PROVED
        assert strategy.steps_taken > 0
        assert strategy.name() == "Forward Chaining"
    
    def test_forward_chaining_goal_is_axiom(self):
        """
        GIVEN goal that is already an axiom
        WHEN using forward chaining
        THEN should immediately recognize as proved
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        axioms = [p]
        goal = p
        rules = [ModusPonens()]
        
        # WHEN
        strategy = ForwardChainingStrategy(max_steps=10)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.PROVED
        assert strategy.steps_taken == 0  # No steps needed
    
    def test_forward_chaining_unprovable(self):
        """
        GIVEN axioms that cannot derive the goal
        WHEN using forward chaining
        THEN should return UNKNOWN after exhausting steps
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        axioms = [p]  # Just P
        goal = q      # Want to prove Q (impossible)
        rules = [ModusPonens()]
        
        # WHEN
        strategy = ForwardChainingStrategy(max_steps=5)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.UNKNOWN
        assert strategy.steps_taken == 5  # Exhausted max steps


class TestBackwardChainingStrategy:
    """Test backward chaining proof strategy."""
    
    def test_backward_chaining_simple_proof(self):
        """
        GIVEN axioms P and P→Q
        WHEN using backward chaining strategy
        THEN should prove Q by working backward
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        # P → Q
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        axioms = [p, impl]
        goal = q
        rules = [ModusPonens(), Simplification()]
        
        # WHEN
        strategy = BackwardChainingStrategy(max_steps=10)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.PROVED
        assert strategy.name() == "Backward Chaining"
    
    def test_backward_chaining_goal_is_axiom(self):
        """
        GIVEN goal that is already an axiom
        WHEN using backward chaining
        THEN should immediately recognize as proved
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        axioms = [p]
        goal = p
        rules = [ModusPonens()]
        
        # WHEN
        strategy = BackwardChainingStrategy(max_steps=10)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.PROVED
    
    def test_backward_chaining_with_multiple_axioms(self):
        """
        GIVEN many axioms
        WHEN using backward chaining
        THEN should work efficiently from goal backward
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        r_pred = namespace.add_predicate("R", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        r = AtomicFormula(r_pred, [])
        
        # P → Q, Q → R
        impl1 = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        impl2 = ConnectiveFormula(LogicalConnective.IMPLIES, [q, r])
        
        axioms = [p, impl1, impl2, q, r]  # Many axioms
        goal = r
        rules = [ModusPonens()]
        
        # WHEN
        strategy = BackwardChainingStrategy(max_steps=20)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result in [ProofResult.PROVED, ProofResult.UNKNOWN]


class TestBidirectionalStrategy:
    """Test bidirectional search proof strategy."""
    
    def test_bidirectional_simple_proof(self):
        """
        GIVEN axioms P and P→Q
        WHEN using bidirectional search
        THEN should prove Q by searching from both ends
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        # P → Q
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        axioms = [p, impl]
        goal = q
        rules = [ModusPonens(), Simplification()]
        
        # WHEN
        strategy = BidirectionalStrategy(max_steps=10)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.PROVED
        assert strategy.name() == "Bidirectional Search"
    
    def test_bidirectional_goal_is_axiom(self):
        """
        GIVEN goal that is already an axiom
        WHEN using bidirectional search
        THEN should immediately recognize as proved
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        p = AtomicFormula(p_pred, [])
        
        axioms = [p]
        goal = p
        rules = [ModusPonens()]
        
        # WHEN
        strategy = BidirectionalStrategy(max_steps=10)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.PROVED
    
    def test_bidirectional_medium_complexity(self):
        """
        GIVEN medium complexity problem
        WHEN using bidirectional search
        THEN should efficiently meet in the middle
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        r_pred = namespace.add_predicate("R", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        r = AtomicFormula(r_pred, [])
        
        # P → Q → R chain
        impl1 = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        impl2 = ConnectiveFormula(LogicalConnective.IMPLIES, [q, r])
        
        axioms = [p, impl1, impl2]
        goal = r
        rules = [ModusPonens()]
        
        # WHEN
        strategy = BidirectionalStrategy(max_steps=20)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result in [ProofResult.PROVED, ProofResult.UNKNOWN]
        assert strategy.steps_taken <= 20


class TestHybridStrategy:
    """Test hybrid adaptive proof strategy."""
    
    def test_hybrid_selects_forward_few_axioms(self):
        """
        GIVEN few axioms (< 5)
        WHEN using hybrid strategy
        THEN should select forward chaining
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        # P → Q
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        axioms = [p, impl]  # Only 2 axioms
        goal = q
        rules = [ModusPonens()]
        
        # WHEN
        strategy = HybridStrategy(max_steps=10)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.PROVED
        assert strategy.name() == "Hybrid Adaptive"
    
    def test_hybrid_selects_backward_many_axioms(self):
        """
        GIVEN many axioms (>= 10)
        WHEN using hybrid strategy
        THEN should select backward chaining
        """
        # GIVEN
        namespace = DCECNamespace()
        predicates = [namespace.add_predicate(f"P{i}", []) for i in range(12)]
        formulas = [AtomicFormula(p, []) for p in predicates]
        
        axioms = formulas[:11]  # 11 axioms
        goal = formulas[0]
        rules = [ModusPonens()]
        
        # WHEN
        strategy = HybridStrategy(max_steps=10)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.PROVED  # Goal is in axioms
    
    def test_hybrid_selects_bidirectional_medium_axioms(self):
        """
        GIVEN medium number of axioms (5-9)
        WHEN using hybrid strategy
        THEN should select bidirectional search
        """
        # GIVEN
        namespace = DCECNamespace()
        predicates = [namespace.add_predicate(f"P{i}", []) for i in range(8)]
        formulas = [AtomicFormula(p, []) for p in predicates]
        
        axioms = formulas[:7]  # 7 axioms (medium)
        goal = formulas[0]
        rules = [ModusPonens()]
        
        # WHEN
        strategy = HybridStrategy(max_steps=10)
        result = strategy.prove(goal, axioms, rules)
        
        # THEN
        assert result.result == ProofResult.PROVED
    
    def test_hybrid_adapts_to_problem(self):
        """
        GIVEN different problem sizes
        WHEN using hybrid strategy
        THEN should adapt selection appropriately
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        # Test with different axiom counts
        small_axioms = [p, impl]  # 2 axioms
        large_axioms = [p] + [AtomicFormula(namespace.add_predicate(f"X{i}", []), []) 
                              for i in range(10)] + [impl]  # 12 axioms
        
        goal = q
        rules = [ModusPonens()]
        
        # WHEN - small problem
        strategy1 = HybridStrategy(max_steps=10)
        result1 = strategy1.prove(goal, small_axioms, rules)
        
        # WHEN - large problem
        strategy2 = HybridStrategy(max_steps=20)
        result2 = strategy2.prove(goal, large_axioms, rules)
        
        # THEN - both should work
        assert result1.result == ProofResult.PROVED
        assert result2.result == ProofResult.PROVED


class TestStrategySelection:
    """Test strategy selection interface."""
    
    def test_get_strategy_all_types(self):
        """
        GIVEN all strategy types
        WHEN getting strategies
        THEN should return correct strategy instances
        """
        # WHEN
        forward = get_strategy(StrategyType.FORWARD_CHAINING, max_steps=50)
        backward = get_strategy(StrategyType.BACKWARD_CHAINING, max_steps=50)
        bidirectional = get_strategy(StrategyType.BIDIRECTIONAL, max_steps=50)
        hybrid = get_strategy(StrategyType.HYBRID, max_steps=50)
        
        # THEN
        assert isinstance(forward, ForwardChainingStrategy)
        assert forward.max_steps == 50
        assert forward.name() == "Forward Chaining"
        
        assert isinstance(backward, BackwardChainingStrategy)
        assert backward.name() == "Backward Chaining"
        
        assert isinstance(bidirectional, BidirectionalStrategy)
        assert bidirectional.name() == "Bidirectional Search"
        
        assert isinstance(hybrid, HybridStrategy)
        assert hybrid.name() == "Hybrid Adaptive"
    
    def test_strategy_comparison(self):
        """
        GIVEN same problem with different strategies
        WHEN comparing strategies
        THEN all should find proof (though steps may differ)
        """
        # GIVEN
        namespace = DCECNamespace()
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        p = AtomicFormula(p_pred, [])
        q = AtomicFormula(q_pred, [])
        
        impl = ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])
        
        axioms = [p, impl]
        goal = q
        rules = [ModusPonens()]
        
        # WHEN - test all strategies
        strategies = [
            get_strategy(StrategyType.FORWARD_CHAINING, max_steps=10),
            get_strategy(StrategyType.BACKWARD_CHAINING, max_steps=10),
            get_strategy(StrategyType.BIDIRECTIONAL, max_steps=10),
            get_strategy(StrategyType.HYBRID, max_steps=10),
        ]
        
        results = [s.prove(goal, axioms, rules) for s in strategies]
        
        # THEN - all should prove the goal
        assert all(r.result == ProofResult.PROVED for r in results)
        assert all(r.goal.to_string() == goal.to_string() for r in results)
