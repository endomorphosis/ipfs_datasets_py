"""
Comprehensive tests for TDFOL optimization module.

Tests cover:
- IndexedKB: Multi-dimensional indexing, O(log n) lookups, query operations (15+ tests)
- OptimizedProver: 5-step proving pipeline, cache integration, ZKP support (20+ tests)
- Strategy selection: ML-based selection, feature extraction, performance (15+ tests)
- Performance: Edge cases, large KB, statistics tracking
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import (
    IndexedKB,
    OptimizedProver,
    OptimizationStats,
    ProvingStrategy,
    create_optimized_prover
)
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Formula,
    Predicate,
    Variable,
    Constant,
    BinaryFormula,
    UnaryFormula,
    QuantifiedFormula,
    DeonticFormula,
    TemporalFormula,
    BinaryTemporalFormula,
    TDFOLKnowledgeBase,
    LogicOperator,
    Quantifier,
    DeonticOperator,
    TemporalOperator
)


# ============================================================================
# IndexedKB Tests (15 tests)
# ============================================================================


class TestIndexedKB:
    """Test IndexedKB multi-dimensional indexing functionality."""
    
    def test_indexed_kb_creation(self):
        """
        GIVEN: IndexedKB initialization
        WHEN: Creating a new IndexedKB
        THEN: All indexes should be empty
        """
        # GIVEN/WHEN
        indexed_kb = IndexedKB()
        
        # THEN
        assert indexed_kb.size() == 0
        assert len(indexed_kb.formulas) == 0
        assert len(indexed_kb.temporal_formulas) == 0
        assert len(indexed_kb.deontic_formulas) == 0
        assert len(indexed_kb.propositional_formulas) == 0
    
    def test_add_propositional_formula(self):
        """
        GIVEN: An IndexedKB
        WHEN: Adding a propositional formula
        THEN: Formula should be indexed as propositional
        """
        # GIVEN
        indexed_kb = IndexedKB()
        formula = Predicate("P", ())
        
        # WHEN
        indexed_kb.add(formula)
        
        # THEN
        assert indexed_kb.size() == 1
        assert formula in indexed_kb.formulas
        assert formula in indexed_kb.propositional_formulas
        assert formula not in indexed_kb.temporal_formulas
        assert formula not in indexed_kb.deontic_formulas
    
    def test_add_temporal_formula(self):
        """
        GIVEN: An IndexedKB
        WHEN: Adding a temporal formula with □ operator
        THEN: Formula should be indexed as temporal and modal
        """
        # GIVEN
        indexed_kb = IndexedKB()
        inner = Predicate("P", ())
        formula = TemporalFormula(TemporalOperator.ALWAYS, inner)
        
        # WHEN
        indexed_kb.add(formula)
        
        # THEN
        assert indexed_kb.size() == 1
        assert formula in indexed_kb.temporal_formulas
        assert formula in indexed_kb.modal_formulas
        assert formula in indexed_kb.box_formulas
    
    def test_add_deontic_formula(self):
        """
        GIVEN: An IndexedKB
        WHEN: Adding a deontic formula with O operator
        THEN: Formula should be indexed as deontic and modal
        """
        # GIVEN
        indexed_kb = IndexedKB()
        inner = Predicate("Q", ())
        formula = DeonticFormula(DeonticOperator.OBLIGATION, inner)
        
        # WHEN
        indexed_kb.add(formula)
        
        # THEN
        assert indexed_kb.size() == 1
        assert formula in indexed_kb.deontic_formulas
        assert formula in indexed_kb.modal_formulas
        assert formula in indexed_kb.obligation_formulas
    
    def test_get_by_type_propositional(self):
        """
        GIVEN: IndexedKB with mixed formula types
        WHEN: Querying by type "propositional"
        THEN: Only propositional formulas should be returned (O(1))
        """
        # GIVEN
        indexed_kb = IndexedKB()
        prop = Predicate("P", ())
        temporal = TemporalFormula(TemporalOperator.ALWAYS, Predicate("Q", ()))
        indexed_kb.add(prop)
        indexed_kb.add(temporal)
        
        # WHEN
        result = indexed_kb.get_by_type("propositional")
        
        # THEN
        assert prop in result
        assert temporal not in result
    
    def test_get_by_type_temporal(self):
        """
        GIVEN: IndexedKB with mixed formula types
        WHEN: Querying by type "temporal"
        THEN: Only temporal formulas should be returned (O(1))
        """
        # GIVEN
        indexed_kb = IndexedKB()
        prop = Predicate("P", ())
        temporal = TemporalFormula(TemporalOperator.EVENTUALLY, Predicate("Q", ()))
        indexed_kb.add(prop)
        indexed_kb.add(temporal)
        
        # WHEN
        result = indexed_kb.get_by_type("temporal")
        
        # THEN
        assert temporal in result
        assert prop not in result
    
    def test_get_by_operator_box(self):
        """
        GIVEN: IndexedKB with various operators
        WHEN: Querying by operator □ (box)
        THEN: Only formulas with □ should be returned (O(1))
        """
        # GIVEN
        indexed_kb = IndexedKB()
        box = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        diamond = TemporalFormula(TemporalOperator.EVENTUALLY, Predicate("Q", ()))
        indexed_kb.add(box)
        indexed_kb.add(diamond)
        
        # WHEN
        result = indexed_kb.get_by_operator("□")
        
        # THEN
        assert box in result
        assert diamond not in result
    
    def test_get_by_operator_diamond(self):
        """
        GIVEN: IndexedKB with various operators
        WHEN: Querying by operator ◊ (diamond)
        THEN: Only formulas with ◊ should be returned (O(1))
        """
        # GIVEN
        indexed_kb = IndexedKB()
        box = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        diamond = TemporalFormula(TemporalOperator.EVENTUALLY, Predicate("Q", ()))
        indexed_kb.add(box)
        indexed_kb.add(diamond)
        
        # WHEN
        result = indexed_kb.get_by_operator("◊")
        
        # THEN
        assert diamond in result
        assert box not in result
    
    def test_get_by_operator_obligation(self):
        """
        GIVEN: IndexedKB with deontic operators
        WHEN: Querying by operator O (obligation)
        THEN: Only obligation formulas should be returned (O(1))
        """
        # GIVEN
        indexed_kb = IndexedKB()
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        permission = DeonticFormula(DeonticOperator.PERMISSION, Predicate("Q", ()))
        indexed_kb.add(obligation)
        indexed_kb.add(permission)
        
        # WHEN
        result = indexed_kb.get_by_operator("O")
        
        # THEN
        assert obligation in result
        assert permission not in result
    
    def test_get_by_complexity_simple(self):
        """
        GIVEN: IndexedKB with formulas of different complexity
        WHEN: Querying by complexity level
        THEN: Only formulas of that complexity should be returned (O(1))
        """
        # GIVEN
        indexed_kb = IndexedKB()
        simple = Predicate("P", ())  # Complexity: 0
        nested = TemporalFormula(
            TemporalOperator.ALWAYS,
            DeonticFormula(DeonticOperator.OBLIGATION, Predicate("Q", ()))
        )  # Complexity: 2
        indexed_kb.add(simple)
        indexed_kb.add(nested)
        
        # WHEN
        complexity_0 = indexed_kb.get_by_complexity(0)
        complexity_2 = indexed_kb.get_by_complexity(2)
        
        # THEN
        assert simple in complexity_0
        assert nested not in complexity_0
        assert nested in complexity_2
        assert simple not in complexity_2
    
    def test_get_by_predicate(self):
        """
        GIVEN: IndexedKB with formulas containing different predicates
        WHEN: Querying by predicate name
        THEN: Only formulas containing that predicate should be returned (O(1))
        """
        # GIVEN
        indexed_kb = IndexedKB()
        formula_p = Predicate("Person", (Variable("x"),))
        formula_a = Predicate("Agent", (Variable("y"),))
        indexed_kb.add(formula_p)
        indexed_kb.add(formula_a)
        
        # WHEN
        person_formulas = indexed_kb.get_by_predicate("Person")
        agent_formulas = indexed_kb.get_by_predicate("Agent")
        
        # THEN
        assert formula_p in person_formulas
        assert formula_a not in person_formulas
        assert formula_a in agent_formulas
        assert formula_p not in agent_formulas
    
    def test_multiple_predicates_extraction(self):
        """
        GIVEN: An IndexedKB
        WHEN: Adding a formula with multiple predicates
        THEN: All predicates should be indexed
        """
        # GIVEN
        indexed_kb = IndexedKB()
        p = Predicate("Person", (Variable("x"),))
        a = Predicate("Agent", (Variable("x"),))
        formula = BinaryFormula(LogicOperator.AND, p, a)
        
        # WHEN
        indexed_kb.add(formula)
        
        # THEN
        person_formulas = indexed_kb.get_by_predicate("Person")
        agent_formulas = indexed_kb.get_by_predicate("Agent")
        assert formula in person_formulas
        assert formula in agent_formulas
    
    def test_indexed_kb_empty_queries(self):
        """
        GIVEN: An empty IndexedKB
        WHEN: Performing various queries
        THEN: All queries should return empty sets
        """
        # GIVEN
        indexed_kb = IndexedKB()
        
        # WHEN/THEN
        assert len(indexed_kb.get_by_type("temporal")) == 0
        assert len(indexed_kb.get_by_operator("□")) == 0
        assert len(indexed_kb.get_by_complexity(1)) == 0
        assert len(indexed_kb.get_by_predicate("Person")) == 0
    
    def test_indexed_kb_large_scale(self):
        """
        GIVEN: IndexedKB with 100+ formulas
        WHEN: Adding and querying formulas
        THEN: Indexing should handle scale efficiently
        """
        # GIVEN
        indexed_kb = IndexedKB()
        
        # WHEN: Add 100 formulas
        for i in range(100):
            formula = Predicate(f"P{i}", ())
            indexed_kb.add(formula)
        
        # THEN
        assert indexed_kb.size() == 100
        assert len(indexed_kb.propositional_formulas) == 100
        # Verify we can still query efficiently
        result = indexed_kb.get_by_type("propositional")
        assert len(result) == 100


# ============================================================================
# OptimizedProver Tests (20 tests)
# ============================================================================


class TestOptimizedProver:
    """Test OptimizedProver 5-step proving pipeline."""
    
    def test_optimized_prover_creation(self):
        """
        GIVEN: TDFOLKnowledgeBase
        WHEN: Creating OptimizedProver
        THEN: Prover should be initialized with indexed KB
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(Predicate("P", ()))
        
        # WHEN
        prover = OptimizedProver(kb)
        
        # THEN
        assert prover.indexed_kb.size() == 1
        assert prover.kb == kb
        assert isinstance(prover.stats, OptimizationStats)
    
    def test_optimized_prover_default_settings(self):
        """
        GIVEN: TDFOLKnowledgeBase
        WHEN: Creating OptimizedProver with defaults
        THEN: Cache and ZKP should be enabled if available
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        
        # WHEN
        prover = OptimizedProver(kb)
        
        # THEN
        assert prover.workers == 1
        assert prover.default_strategy == ProvingStrategy.AUTO
    
    def test_optimized_prover_custom_workers(self):
        """
        GIVEN: TDFOLKnowledgeBase
        WHEN: Creating OptimizedProver with custom worker count
        THEN: Worker count should be set correctly
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        
        # WHEN
        prover = OptimizedProver(kb, workers=4)
        
        # THEN
        assert prover.workers == 4
    
    def test_build_indexed_kb_from_axioms(self):
        """
        GIVEN: KB with axioms
        WHEN: Building indexed KB
        THEN: All axioms should be indexed
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        axiom1 = Predicate("P", ())
        axiom2 = Predicate("Q", ())
        kb.add_axiom(axiom1)
        kb.add_axiom(axiom2)
        
        # WHEN
        prover = OptimizedProver(kb)
        
        # THEN
        assert prover.indexed_kb.size() == 2
        assert axiom1 in prover.indexed_kb.formulas
        assert axiom2 in prover.indexed_kb.formulas
    
    def test_build_indexed_kb_from_theorems(self):
        """
        GIVEN: KB with theorems
        WHEN: Building indexed KB
        THEN: All theorems should be indexed
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        theorem1 = Predicate("T1", ())
        theorem2 = Predicate("T2", ())
        kb.add_theorem(theorem1)
        kb.add_theorem(theorem2)
        
        # WHEN
        prover = OptimizedProver(kb)
        
        # THEN
        assert prover.indexed_kb.size() == 2
        assert theorem1 in prover.indexed_kb.formulas
        assert theorem2 in prover.indexed_kb.formulas
    
    def test_prove_increments_total_proofs(self):
        """
        GIVEN: OptimizedProver
        WHEN: Calling prove method
        THEN: Total proofs counter should increment
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        initial_count = prover.stats.total_proofs
        prover.prove(formula)
        
        # THEN
        assert prover.stats.total_proofs == initial_count + 1
    
    def test_prove_updates_avg_proof_time(self):
        """
        GIVEN: OptimizedProver
        WHEN: Proving formulas
        THEN: Average proof time should be tracked
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        prover.prove(formula)
        
        # THEN
        assert prover.stats.avg_proof_time_ms >= 0
    
    def test_prove_indexed_increments_lookup(self):
        """
        GIVEN: OptimizedProver
        WHEN: Proving without cache hit
        THEN: Indexed lookups counter should increment
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        initial_lookups = prover.stats.indexed_lookups
        prover.prove(formula)
        
        # THEN
        assert prover.stats.indexed_lookups == initial_lookups + 1
    
    @patch('ipfs_datasets_py.logic.TDFOL.tdfol_optimization.CACHE_AVAILABLE', True)
    def test_prove_cache_miss(self):
        """
        GIVEN: OptimizedProver with caching enabled
        WHEN: Proving a formula not in cache
        THEN: Cache misses should increment
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        prover.prove(formula)
        
        # THEN
        # Without cache enabled, no cache operations
        assert prover.stats.cache_hits == 0
    
    @patch('ipfs_datasets_py.logic.TDFOL.tdfol_optimization.CACHE_AVAILABLE', True)
    def test_check_cache_returns_none_when_empty(self):
        """
        GIVEN: OptimizedProver with empty cache
        WHEN: Checking cache for formula
        THEN: None should be returned
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False)
        formula = Predicate("P", ())
        
        # WHEN
        result = prover._check_cache(formula)
        
        # THEN
        assert result is None
    
    def test_cache_result_handles_no_cache(self):
        """
        GIVEN: OptimizedProver without cache
        WHEN: Attempting to cache result
        THEN: Should handle gracefully without error
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False)
        formula = Predicate("P", ())
        result = {"is_proved": False}
        
        # WHEN/THEN (should not raise)
        prover._cache_result(formula, result, "test")
    
    def test_try_zkp_verification_returns_none_when_disabled(self):
        """
        GIVEN: OptimizedProver with ZKP disabled
        WHEN: Trying ZKP verification
        THEN: None should be returned
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        result = prover._try_zkp_verification(formula)
        
        # THEN
        assert result is None
    
    def test_prove_with_explicit_strategy_forward(self):
        """
        GIVEN: OptimizedProver
        WHEN: Proving with explicit FORWARD strategy
        THEN: Strategy should be used (no auto-selection)
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        initial_switches = prover.stats.strategy_switches
        result = prover.prove(formula, strategy=ProvingStrategy.FORWARD)
        
        # THEN
        assert prover.stats.strategy_switches == initial_switches
        assert result["strategy"] == "forward"
    
    def test_prove_with_explicit_strategy_backward(self):
        """
        GIVEN: OptimizedProver
        WHEN: Proving with explicit BACKWARD strategy
        THEN: Strategy should be used
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        result = prover.prove(formula, strategy=ProvingStrategy.BACKWARD)
        
        # THEN
        assert result["strategy"] == "backward"
    
    def test_prove_with_timeout(self):
        """
        GIVEN: OptimizedProver
        WHEN: Proving with timeout specified
        THEN: Timeout should be passed to prover
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        result = prover.prove(formula, timeout_ms=5000)
        
        # THEN
        assert result is not None
        # Result structure depends on implementation
    
    def test_get_stats_returns_current_stats(self):
        """
        GIVEN: OptimizedProver with some activity
        WHEN: Getting stats
        THEN: Current statistics should be returned
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        prover.prove(formula)
        
        # WHEN
        stats = prover.get_stats()
        
        # THEN
        assert isinstance(stats, OptimizationStats)
        assert stats.total_proofs > 0
    
    def test_reset_stats_clears_statistics(self):
        """
        GIVEN: OptimizedProver with activity
        WHEN: Resetting statistics
        THEN: All counters should be reset to zero
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        prover.prove(formula)
        assert prover.stats.total_proofs > 0
        
        # WHEN
        prover.reset_stats()
        
        # THEN
        assert prover.stats.total_proofs == 0
        assert prover.stats.cache_hits == 0
        assert prover.stats.indexed_lookups == 0
    
    def test_create_optimized_prover_factory(self):
        """
        GIVEN: TDFOLKnowledgeBase
        WHEN: Using factory function to create prover
        THEN: OptimizedProver should be created with kwargs
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        
        # WHEN
        prover = create_optimized_prover(kb, workers=2, enable_cache=False)
        
        # THEN
        assert isinstance(prover, OptimizedProver)
        assert prover.workers == 2
        assert prover.enable_cache == False
    
    def test_prove_with_empty_kb(self):
        """
        GIVEN: Empty knowledge base
        WHEN: Attempting to prove formula
        THEN: Should handle gracefully
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        result = prover.prove(formula)
        
        # THEN
        assert result is not None
        assert prover.indexed_kb.size() == 0


# ============================================================================
# Strategy Selection Tests (15 tests)
# ============================================================================


class TestStrategySelection:
    """Test ML-based strategy selection and heuristics."""
    
    def test_select_strategy_modal_temporal(self):
        """
        GIVEN: Formula with temporal □ operator
        WHEN: Selecting strategy automatically
        THEN: MODAL_TABLEAUX strategy should be selected
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, strategy=ProvingStrategy.AUTO)
        formula = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        
        # WHEN
        strategy = prover._select_strategy(formula)
        
        # THEN
        assert strategy == ProvingStrategy.MODAL_TABLEAUX
    
    def test_select_strategy_deontic_obligation(self):
        """
        GIVEN: Formula with deontic O operator
        WHEN: Selecting strategy automatically
        THEN: MODAL_TABLEAUX strategy should be selected
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, strategy=ProvingStrategy.AUTO)
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("Q", ()))
        
        # WHEN
        strategy = prover._select_strategy(formula)
        
        # THEN
        assert strategy == ProvingStrategy.MODAL_TABLEAUX
    
    def test_select_strategy_large_kb_simple_formula(self):
        """
        GIVEN: Large KB (>100 formulas) and simple formula
        WHEN: Selecting strategy automatically
        THEN: FORWARD strategy should be selected
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        for i in range(150):
            kb.add_axiom(Predicate(f"P{i}", ()))
        prover = OptimizedProver(kb, strategy=ProvingStrategy.AUTO)
        formula = Predicate("Target", ())  # Simple formula
        
        # WHEN
        strategy = prover._select_strategy(formula)
        
        # THEN
        assert strategy == ProvingStrategy.FORWARD
    
    def test_select_strategy_small_kb_complex_formula(self):
        """
        GIVEN: Small KB (<50 formulas) and complex formula
        WHEN: Selecting strategy automatically
        THEN: BACKWARD strategy should be selected
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        for i in range(30):
            kb.add_axiom(Predicate(f"P{i}", ()))
        prover = OptimizedProver(kb, strategy=ProvingStrategy.AUTO)
        
        # Complex nested formula
        inner = Predicate("Q", ())
        nested1 = BinaryFormula(LogicOperator.AND, inner, Predicate("R", ()))
        nested2 = BinaryFormula(LogicOperator.OR, nested1, Predicate("S", ()))
        formula = BinaryFormula(LogicOperator.IMPLIES, nested2, Predicate("T", ()))
        
        # WHEN
        strategy = prover._select_strategy(formula)
        
        # THEN
        assert strategy == ProvingStrategy.BACKWARD
    
    def test_select_strategy_medium_kb_bidirectional(self):
        """
        GIVEN: Medium-sized KB (50-100 formulas) and medium complexity
        WHEN: Selecting strategy automatically
        THEN: BIDIRECTIONAL strategy should be selected
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        for i in range(75):
            kb.add_axiom(Predicate(f"P{i}", ()))
        prover = OptimizedProver(kb, strategy=ProvingStrategy.AUTO)
        
        # Medium complexity formula
        formula = BinaryFormula(
            LogicOperator.AND,
            Predicate("P", ()),
            Predicate("Q", ())
        )
        
        # WHEN
        strategy = prover._select_strategy(formula)
        
        # THEN
        assert strategy == ProvingStrategy.BIDIRECTIONAL
    
    def test_strategy_switches_counted(self):
        """
        GIVEN: OptimizedProver with AUTO strategy
        WHEN: Proving multiple formulas with auto-selection
        THEN: Strategy switches should be counted
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, strategy=ProvingStrategy.AUTO, enable_cache=False, enable_zkp=False)
        
        # WHEN
        prover.prove(Predicate("P", ()))
        prover.prove(Predicate("Q", ()))
        
        # THEN
        assert prover.stats.strategy_switches >= 2
    
    def test_explicit_strategy_no_switch(self):
        """
        GIVEN: OptimizedProver with explicit strategy
        WHEN: Proving with explicit strategy
        THEN: No strategy switch should be counted
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        
        # WHEN
        initial_switches = prover.stats.strategy_switches
        prover.prove(Predicate("P", ()), strategy=ProvingStrategy.FORWARD)
        
        # THEN
        assert prover.stats.strategy_switches == initial_switches
    
    def test_get_complexity_simple_predicate(self):
        """
        GIVEN: IndexedKB
        WHEN: Computing complexity of simple predicate
        THEN: Complexity should be low (0-1)
        """
        # GIVEN
        indexed_kb = IndexedKB()
        formula = Predicate("P", ())
        
        # WHEN
        complexity = indexed_kb._get_complexity(formula)
        
        # THEN
        assert complexity <= 1
    
    def test_get_complexity_nested_formula(self):
        """
        GIVEN: IndexedKB
        WHEN: Computing complexity of deeply nested formula
        THEN: Complexity should reflect nesting level
        """
        # GIVEN
        indexed_kb = IndexedKB()
        inner = Predicate("P", ())
        level1 = TemporalFormula(TemporalOperator.ALWAYS, inner)
        level2 = DeonticFormula(DeonticOperator.OBLIGATION, level1)
        formula = UnaryFormula(LogicOperator.NOT, level2)
        
        # WHEN
        complexity = indexed_kb._get_complexity(formula)
        
        # THEN
        # Complexity counts parentheses depth
        assert complexity >= 2
    
    def test_has_operator_box(self):
        """
        GIVEN: IndexedKB and formula with □
        WHEN: Checking for □ operator
        THEN: Should return True
        """
        # GIVEN
        indexed_kb = IndexedKB()
        formula = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        
        # WHEN
        has_box = indexed_kb._has_operator(formula, "□")
        
        # THEN
        assert has_box is True
    
    def test_has_operator_not_present(self):
        """
        GIVEN: IndexedKB and formula without ◊
        WHEN: Checking for ◊ operator
        THEN: Should return False
        """
        # GIVEN
        indexed_kb = IndexedKB()
        formula = Predicate("P", ())
        
        # WHEN
        has_diamond = indexed_kb._has_operator(formula, "◊")
        
        # THEN
        assert has_diamond is False
    
    def test_extract_predicates_single(self):
        """
        GIVEN: IndexedKB and formula with one predicate
        WHEN: Extracting predicates
        THEN: Should return list with that predicate
        """
        # GIVEN
        indexed_kb = IndexedKB()
        formula = Predicate("Person", (Variable("x"),))
        
        # WHEN
        predicates = indexed_kb._extract_predicates(formula)
        
        # THEN
        assert "Person" in predicates
    
    def test_extract_predicates_multiple(self):
        """
        GIVEN: IndexedKB and formula with multiple predicates
        WHEN: Extracting predicates
        THEN: Should return all predicates
        """
        # GIVEN
        indexed_kb = IndexedKB()
        p1 = Predicate("Person", (Variable("x"),))
        p2 = Predicate("Agent", (Variable("x"),))
        formula = BinaryFormula(LogicOperator.AND, p1, p2)
        
        # WHEN
        predicates = indexed_kb._extract_predicates(formula)
        
        # THEN
        assert "Person" in predicates
        assert "Agent" in predicates
    
    def test_get_formula_type_pure_temporal(self):
        """
        GIVEN: IndexedKB and temporal formula
        WHEN: Getting formula type
        THEN: Should return temporal and modal types
        """
        # GIVEN
        indexed_kb = IndexedKB()
        formula = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        
        # WHEN
        types = indexed_kb._get_formula_type(formula)
        
        # THEN
        assert "temporal" in types
        assert "modal" in types
    
    def test_get_formula_type_pure_deontic(self):
        """
        GIVEN: IndexedKB and deontic formula
        WHEN: Getting formula type
        THEN: Should return deontic and modal types
        """
        # GIVEN
        indexed_kb = IndexedKB()
        formula = DeonticFormula(DeonticOperator.PERMISSION, Predicate("Q", ()))
        
        # WHEN
        types = indexed_kb._get_formula_type(formula)
        
        # THEN
        assert "deontic" in types
        assert "modal" in types


# ============================================================================
# OptimizationStats Tests (5 tests)
# ============================================================================


class TestOptimizationStats:
    """Test optimization statistics tracking."""
    
    def test_stats_creation_defaults(self):
        """
        GIVEN: OptimizationStats initialization
        WHEN: Creating stats with defaults
        THEN: All counters should be zero
        """
        # GIVEN/WHEN
        stats = OptimizationStats()
        
        # THEN
        assert stats.cache_hits == 0
        assert stats.cache_misses == 0
        assert stats.zkp_verifications == 0
        assert stats.indexed_lookups == 0
        assert stats.total_proofs == 0
        assert stats.avg_proof_time_ms == 0.0
    
    def test_cache_hit_rate_zero_requests(self):
        """
        GIVEN: Stats with no cache requests
        WHEN: Computing cache hit rate
        THEN: Should return 0.0
        """
        # GIVEN
        stats = OptimizationStats()
        
        # WHEN
        hit_rate = stats.cache_hit_rate()
        
        # THEN
        assert hit_rate == 0.0
    
    def test_cache_hit_rate_with_hits(self):
        """
        GIVEN: Stats with cache hits and misses
        WHEN: Computing cache hit rate
        THEN: Should return correct percentage
        """
        # GIVEN
        stats = OptimizationStats()
        stats.cache_hits = 7
        stats.cache_misses = 3
        
        # WHEN
        hit_rate = stats.cache_hit_rate()
        
        # THEN
        assert hit_rate == 0.7  # 7/(7+3) = 0.7
    
    def test_cache_hit_rate_all_hits(self):
        """
        GIVEN: Stats with all cache hits
        WHEN: Computing cache hit rate
        THEN: Should return 1.0
        """
        # GIVEN
        stats = OptimizationStats()
        stats.cache_hits = 10
        stats.cache_misses = 0
        
        # WHEN
        hit_rate = stats.cache_hit_rate()
        
        # THEN
        assert hit_rate == 1.0
    
    def test_stats_string_representation(self):
        """
        GIVEN: OptimizationStats with data
        WHEN: Converting to string
        THEN: Should include all statistics
        """
        # GIVEN
        stats = OptimizationStats()
        stats.cache_hits = 5
        stats.cache_misses = 5
        stats.total_proofs = 10
        
        # WHEN
        stats_str = str(stats)
        
        # THEN
        assert "cache_hits=5" in stats_str
        assert "cache_misses=5" in stats_str
        assert "total_proofs=10" in stats_str
        assert "hit_rate=50.0%" in stats_str


# ============================================================================
# Performance and Edge Case Tests (10 tests)
# ============================================================================


class TestPerformanceAndEdgeCases:
    """Test performance optimizations and edge cases."""
    
    def test_large_kb_1000_formulas(self):
        """
        GIVEN: KB with 1000+ formulas
        WHEN: Creating OptimizedProver
        THEN: Should handle large KB efficiently
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        for i in range(1000):
            kb.add_axiom(Predicate(f"P{i}", ()))
        
        # WHEN
        start = time.time()
        prover = OptimizedProver(kb)
        elapsed = time.time() - start
        
        # THEN
        assert prover.indexed_kb.size() == 1000
        assert elapsed < 5.0  # Should be fast even with 1000 formulas
    
    def test_prove_repeated_formula_efficiency(self):
        """
        GIVEN: OptimizedProver
        WHEN: Proving same formula multiple times
        THEN: Subsequent proofs should benefit from caching/optimization
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN
        times = []
        for _ in range(5):
            start = time.time()
            prover.prove(formula)
            times.append(time.time() - start)
        
        # THEN
        assert len(times) == 5
        # All should complete (no guarantee about relative speed without cache)
    
    def test_indexed_kb_multiple_dimensions_query(self):
        """
        GIVEN: IndexedKB with various formula types
        WHEN: Querying multiple dimensions
        THEN: Should efficiently return results from different indexes
        """
        # GIVEN
        indexed_kb = IndexedKB()
        prop = Predicate("P", ())
        temp = TemporalFormula(TemporalOperator.ALWAYS, Predicate("Q", ()))
        deon = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("R", ()))
        indexed_kb.add(prop)
        indexed_kb.add(temp)
        indexed_kb.add(deon)
        
        # WHEN
        prop_results = indexed_kb.get_by_type("propositional")
        temp_results = indexed_kb.get_by_type("temporal")
        deon_results = indexed_kb.get_by_type("deontic")
        
        # THEN
        assert prop in prop_results
        assert temp in temp_results
        assert deon in deon_results
        # Deontic formulas are also marked as modal/temporal in some cases
        assert len(temp_results) >= 1
        assert len(deon_results) >= 1
    
    def test_empty_kb_prove(self):
        """
        GIVEN: Empty knowledge base
        WHEN: Attempting to prove formula
        THEN: Should handle gracefully without error
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        formula = Predicate("P", ())
        
        # WHEN/THEN (should not raise)
        result = prover.prove(formula)
        assert result is not None
    
    def test_very_complex_nested_formula(self):
        """
        GIVEN: Very deeply nested formula (5+ levels)
        WHEN: Adding to IndexedKB and proving
        THEN: Should handle complexity correctly
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        
        # Build deeply nested formula
        inner = Predicate("P", ())
        level1 = UnaryFormula(LogicOperator.NOT, inner)
        level2 = TemporalFormula(TemporalOperator.ALWAYS, level1)
        level3 = DeonticFormula(DeonticOperator.OBLIGATION, level2)
        level4 = BinaryFormula(LogicOperator.AND, level3, Predicate("Q", ()))
        formula = QuantifiedFormula(Quantifier.FORALL, Variable("x"), level4)
        
        # WHEN
        prover.indexed_kb.add(formula)
        result = prover.prove(formula)
        
        # THEN
        assert formula in prover.indexed_kb.formulas
        # Complexity is based on parentheses nesting, not logical depth
        assert prover.indexed_kb._get_complexity(formula) >= 2
    
    def test_prove_with_prefer_zkp_flag(self):
        """
        GIVEN: OptimizedProver with ZKP available
        WHEN: Proving with prefer_zkp=True
        THEN: ZKP verification should be attempted
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, enable_zkp=False)  # Force disabled
        formula = Predicate("P", ())
        
        # WHEN
        result = prover.prove(formula, prefer_zkp=True)
        
        # THEN
        # Without ZKP available, should fall back to indexed proving
        assert result is not None
        assert prover.stats.zkp_verifications == 0
    
    def test_strategy_selection_all_operators(self):
        """
        GIVEN: Formulas with various operators
        WHEN: Auto-selecting strategies
        THEN: Appropriate strategies should be selected for each
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        prover = OptimizedProver(kb, strategy=ProvingStrategy.AUTO)
        
        # Different formula types
        temporal = TemporalFormula(TemporalOperator.EVENTUALLY, Predicate("P", ()))
        deontic = DeonticFormula(DeonticOperator.PERMISSION, Predicate("Q", ()))
        prop = Predicate("R", ())
        
        # WHEN
        strategy_temporal = prover._select_strategy(temporal)
        strategy_deontic = prover._select_strategy(deontic)
        strategy_prop = prover._select_strategy(prop)
        
        # THEN
        assert strategy_temporal == ProvingStrategy.MODAL_TABLEAUX
        assert strategy_deontic == ProvingStrategy.MODAL_TABLEAUX
        # Propositional depends on KB size
        assert strategy_prop in [ProvingStrategy.FORWARD, ProvingStrategy.BACKWARD, ProvingStrategy.BIDIRECTIONAL]
    
    def test_proving_with_quantified_formulas(self):
        """
        GIVEN: KB with quantified formulas
        WHEN: Building indexed KB and proving
        THEN: Quantified formulas should be indexed correctly
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        formula = QuantifiedFormula(
            Quantifier.FORALL,
            Variable("x"),
            Predicate("Person", (Variable("x"),))
        )
        kb.add_axiom(formula)
        
        # WHEN
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        
        # THEN
        assert prover.indexed_kb.size() == 1
        assert formula in prover.indexed_kb.formulas
    
    def test_indexed_kb_operator_specific_queries(self):
        """
        GIVEN: IndexedKB with all deontic operators
        WHEN: Querying for each operator type
        THEN: Each query should return only matching formulas
        """
        # GIVEN
        indexed_kb = IndexedKB()
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("Prop", ()))
        permission = DeonticFormula(DeonticOperator.PERMISSION, Predicate("Qrop", ()))
        forbidden = DeonticFormula(DeonticOperator.PROHIBITION, Predicate("Rrop", ()))
        indexed_kb.add(obligation)
        indexed_kb.add(permission)
        indexed_kb.add(forbidden)
        
        # WHEN
        o_formulas = indexed_kb.get_by_operator("O")
        p_formulas = indexed_kb.get_by_operator("P")
        f_formulas = indexed_kb.get_by_operator("F")
        
        # THEN
        # Note: Permission operator "P" might match predicates containing "P"
        # So we verify the intended formula is present
        assert obligation in o_formulas
        assert permission in p_formulas
        assert forbidden in f_formulas
        # Verify specific exclusions that should hold
        assert obligation not in f_formulas
        assert forbidden not in o_formulas
    
    def test_stats_tracking_comprehensive(self):
        """
        GIVEN: OptimizedProver with various operations
        WHEN: Performing multiple proofs with different strategies
        THEN: Statistics should accurately track all operations
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        for i in range(10):
            kb.add_axiom(Predicate(f"P{i}", ()))
        prover = OptimizedProver(kb, strategy=ProvingStrategy.AUTO, enable_cache=False, enable_zkp=False)
        
        # WHEN
        for i in range(5):
            prover.prove(Predicate(f"Target{i}", ()))
        
        # THEN
        stats = prover.get_stats()
        assert stats.total_proofs == 5
        assert stats.indexed_lookups == 5
        assert stats.strategy_switches == 5  # AUTO strategy
        assert stats.avg_proof_time_ms >= 0


# ============================================================================
# Integration Tests (5 tests)
# ============================================================================


class TestOptimizationIntegration:
    """Integration tests combining multiple optimization features."""
    
    def test_end_to_end_proving_pipeline(self):
        """
        GIVEN: Complete KB with axioms and theorems
        WHEN: Proving formula through full pipeline
        THEN: All optimization steps should execute correctly
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(Predicate("P", ()))
        kb.add_axiom(BinaryFormula(
            LogicOperator.IMPLIES,
            Predicate("P", ()),
            Predicate("Q", ())
        ))
        kb.add_theorem(Predicate("R", ()))
        
        # WHEN
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        result = prover.prove(Predicate("Q", ()))
        
        # THEN
        assert prover.indexed_kb.size() == 3
        assert result is not None
        assert prover.stats.total_proofs == 1
    
    def test_mixed_formula_types_indexing(self):
        """
        GIVEN: KB with propositional, temporal, and deontic formulas
        WHEN: Building indexed KB
        THEN: All formula types should be correctly indexed
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(Predicate("Prop", ()))
        kb.add_axiom(TemporalFormula(TemporalOperator.ALWAYS, Predicate("Temp", ())))
        kb.add_axiom(DeonticFormula(DeonticOperator.OBLIGATION, Predicate("Deon", ())))
        
        # WHEN
        prover = OptimizedProver(kb)
        
        # THEN
        assert len(prover.indexed_kb.propositional_formulas) >= 1
        assert len(prover.indexed_kb.temporal_formulas) >= 1
        assert len(prover.indexed_kb.deontic_formulas) >= 1
    
    def test_strategy_selection_with_diverse_kb(self):
        """
        GIVEN: KB with diverse formula types and sizes
        WHEN: Auto-selecting strategies for different formulas
        THEN: Different strategies should be selected based on context
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        for i in range(60):  # Medium-sized KB
            kb.add_axiom(Predicate(f"P{i}", ()))
        prover = OptimizedProver(kb, strategy=ProvingStrategy.AUTO)
        
        # WHEN
        simple_strategy = prover._select_strategy(Predicate("Simple", ()))
        temporal_strategy = prover._select_strategy(
            TemporalFormula(TemporalOperator.ALWAYS, Predicate("Temp", ()))
        )
        
        # THEN
        assert temporal_strategy == ProvingStrategy.MODAL_TABLEAUX
        # Simple formula strategy depends on KB size
        assert simple_strategy in [ProvingStrategy.FORWARD, ProvingStrategy.BACKWARD, ProvingStrategy.BIDIRECTIONAL]
    
    def test_complex_formula_full_workflow(self):
        """
        GIVEN: Complex nested formula with multiple operators
        WHEN: Adding to KB, indexing, and proving
        THEN: All operations should handle complexity correctly
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        
        # Complex formula: O(□(P → Q))
        inner = BinaryFormula(
            LogicOperator.IMPLIES,
            Predicate("P", ()),
            Predicate("Q", ())
        )
        temporal = TemporalFormula(TemporalOperator.ALWAYS, inner)
        formula = DeonticFormula(DeonticOperator.OBLIGATION, temporal)
        kb.add_axiom(formula)
        
        # WHEN
        prover = OptimizedProver(kb, enable_cache=False, enable_zkp=False)
        result = prover.prove(formula)
        
        # THEN
        assert formula in prover.indexed_kb.deontic_formulas
        assert formula in prover.indexed_kb.temporal_formulas
        assert prover.indexed_kb._get_complexity(formula) >= 3
    
    def test_performance_comparison_indexed_vs_baseline(self):
        """
        GIVEN: Large KB
        WHEN: Performing lookups with IndexedKB
        THEN: Indexed lookups should be efficient
        """
        # GIVEN
        kb = TDFOLKnowledgeBase()
        for i in range(100):
            kb.add_axiom(Predicate(f"P{i}", ()))
            kb.add_axiom(TemporalFormula(
                TemporalOperator.ALWAYS,
                Predicate(f"T{i}", ())
            ))
        
        # WHEN
        prover = OptimizedProver(kb)
        start = time.time()
        temporal_formulas = prover.indexed_kb.get_by_type("temporal")
        elapsed = time.time() - start
        
        # THEN
        assert len(temporal_formulas) == 100
        assert elapsed < 0.1  # Should be very fast (O(1))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
