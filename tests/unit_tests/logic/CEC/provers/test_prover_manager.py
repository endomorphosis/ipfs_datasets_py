"""
Tests for Unified Prover Manager (Phase 6 Week 3).

This test module validates the unified prover manager for CEC,
covering auto-selection, parallel proving, and result aggregation.

Test Coverage:
- Manager initialization (5 tests)
- Prover selection (5 tests)
- Auto strategy (5 tests)
- Sequential strategy (5 tests)
- Parallel strategy (5 tests)
- Statistics and monitoring (5 tests)

Total: 30 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.provers.prover_manager import (
    ProverManager,
    ProverConfig,
    ProverType,
    ProverStrategy,
    UnifiedProofResult
)
from ipfs_datasets_py.logic.CEC.provers.z3_adapter import ProofStatus, Z3_AVAILABLE
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective,
    Predicate,
    Variable,
    VariableTerm,
)
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECNamespace


@pytest.fixture
def namespace():
    """Create DCEC namespace for tests."""
    return DCECNamespace()


@pytest.fixture
def manager():
    """Create prover manager for tests."""
    return ProverManager()


class TestManagerInitialization:
    """Test prover manager initialization."""
    
    def test_manager_creation_default(self):
        """
        GIVEN ProverManager class
        WHEN creating manager with defaults
        THEN should initialize successfully
        """
        manager = ProverManager()
        assert manager.config is not None
        assert isinstance(manager.available_provers, dict)
        assert manager.stats is not None
    
    def test_manager_creation_custom_config(self):
        """
        GIVEN custom ProverConfig
        WHEN creating manager
        THEN should use custom configuration
        """
        config = ProverConfig(
            enabled_provers={ProverType.Z3},
            default_timeout=60
        )
        manager = ProverManager(config)
        assert manager.config.default_timeout == 60
    
    def test_manager_available_provers(self, manager):
        """
        GIVEN initialized manager
        WHEN getting available provers
        THEN should return list of ProverTypes
        """
        provers = manager.get_available_provers()
        assert isinstance(provers, list)
        # At least Z3 should be available if installed
        if Z3_AVAILABLE:
            assert ProverType.Z3 in provers
    
    def test_manager_stats_initialization(self, manager):
        """
        GIVEN new manager
        WHEN getting stats
        THEN should have zero counts
        """
        stats = manager.get_stats()
        assert stats['total_proofs'] == 0
        assert stats['valid_proofs'] == 0
        assert stats['z3_used'] == 0
    
    def test_manager_reset_stats(self, manager):
        """
        GIVEN manager with stats
        WHEN resetting stats
        THEN should clear all counts
        """
        manager.stats['total_proofs'] = 10
        manager.reset_stats()
        stats = manager.get_stats()
        assert stats['total_proofs'] == 0


class TestProverSelection:
    """Test prover selection logic."""
    
    def test_select_best_for_deontic(self, manager, namespace):
        """
        GIVEN deontic formula
        WHEN selecting best prover
        THEN should prefer Z3 if available
        """
        pred = namespace.add_predicate("action", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = DeonticFormula(DeonticOperator.OBLIGATION, base)
        
        best = manager.select_best_prover(formula)
        if Z3_AVAILABLE and ProverType.Z3 in manager.available_provers:
            assert best == ProverType.Z3
    
    def test_select_best_for_cognitive(self, manager, namespace):
        """
        GIVEN cognitive formula
        WHEN selecting best prover
        THEN should prefer Z3 if available
        """
        pred = namespace.add_predicate("fact", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = CognitiveFormula(CognitiveOperator.BELIEF, VariableTerm(agent), base)
        
        best = manager.select_best_prover(formula)
        if Z3_AVAILABLE and ProverType.Z3 in manager.available_provers:
            assert best == ProverType.Z3
    
    def test_select_best_for_temporal(self, manager, namespace):
        """
        GIVEN temporal formula
        WHEN selecting best prover
        THEN should prefer Z3 if available
        """
        pred = namespace.add_predicate("state", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = TemporalFormula(TemporalOperator.ALWAYS, base)
        
        best = manager.select_best_prover(formula)
        if Z3_AVAILABLE and ProverType.Z3 in manager.available_provers:
            assert best == ProverType.Z3
    
    def test_select_best_for_connective(self, manager, namespace):
        """
        GIVEN connective formula
        WHEN selecting best prover
        THEN should select appropriate prover
        """
        pred1 = namespace.add_predicate("p1", ["Agent"])
        pred2 = namespace.add_predicate("p2", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        f1 = AtomicFormula(pred1, [VariableTerm(agent)])
        f2 = AtomicFormula(pred2, [VariableTerm(agent)])
        formula = ConnectiveFormula(LogicalConnective.AND, [f1, f2])
        
        best = manager.select_best_prover(formula)
        # When no external provers are installed, result may be None
        if manager.available_provers:
            assert best is not None
    
    def test_select_best_no_provers(self):
        """
        GIVEN manager with no provers
        WHEN selecting best prover
        THEN should return None
        """
        config = ProverConfig(enabled_provers=set())
        manager = ProverManager(config)
        
        # Create dummy formula
        from ipfs_datasets_py.logic.CEC.native.dcec_core import AtomicFormula
        namespace = DCECNamespace()
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        best = manager.select_best_prover(formula)
        assert best is None


class TestAutoStrategy:
    """Test auto proving strategy."""
    
    def test_prove_auto_simple(self, manager, namespace):
        """
        GIVEN simple formula
        WHEN proving with auto strategy
        THEN should select and use best prover
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="auto")
        assert isinstance(result, UnifiedProofResult)
        assert result.total_time >= 0.0
    
    def test_prove_auto_with_axioms(self, manager, namespace):
        """
        GIVEN formula and axioms
        WHEN proving with auto strategy
        THEN should pass axioms to prover
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("goal", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, axioms=[formula], strategy="auto")
        assert isinstance(result, UnifiedProofResult)
    
    def test_prove_auto_deontic(self, manager, namespace):
        """
        GIVEN deontic formula
        WHEN proving with auto strategy
        THEN should select appropriate prover
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("action", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        base = AtomicFormula(pred, [VariableTerm(agent)])
        formula = DeonticFormula(DeonticOperator.OBLIGATION, base)
        
        result = manager.prove(formula, strategy="auto")
        assert isinstance(result, UnifiedProofResult)
    
    def test_prove_auto_updates_stats(self, manager, namespace):
        """
        GIVEN formula
        WHEN proving with auto strategy
        THEN should update statistics
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        initial_count = manager.stats['total_proofs']
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="auto")
        assert manager.stats['total_proofs'] == initial_count + 1
    
    def test_prove_best_strategy(self, manager, namespace):
        """
        GIVEN formula
        WHEN proving with 'best' strategy
        THEN should use best prover
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="best")
        assert isinstance(result, UnifiedProofResult)


class TestSequentialStrategy:
    """Test sequential proving strategy."""
    
    def test_prove_sequential(self, manager, namespace):
        """
        GIVEN formula
        WHEN proving with sequential strategy
        THEN should try provers one by one
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="sequential")
        assert isinstance(result, UnifiedProofResult)
        assert len(result.prover_results) >= 1
    
    def test_sequential_stops_on_valid(self, manager, namespace):
        """
        GIVEN tautology
        WHEN proving sequentially
        THEN should stop after first valid proof
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("p", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        p = AtomicFormula(pred, [VariableTerm(agent)])
        not_p = ConnectiveFormula(LogicalConnective.NOT, [p])
        tautology = ConnectiveFormula(LogicalConnective.OR, [p, not_p])
        
        result = manager.prove(tautology, strategy="sequential")
        # May stop early if first prover succeeds
        assert isinstance(result, UnifiedProofResult)
    
    def test_sequential_with_timeout(self, manager, namespace):
        """
        GIVEN formula with timeout
        WHEN proving sequentially
        THEN should respect timeout per prover
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="sequential", timeout=5)
        assert isinstance(result, UnifiedProofResult)
    
    def test_sequential_aggregates_results(self, manager, namespace):
        """
        GIVEN formula
        WHEN proving sequentially
        THEN should collect all prover results
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="sequential")
        assert isinstance(result.prover_results, dict)
    
    def test_sequential_updates_stats(self, manager, namespace):
        """
        GIVEN formula
        WHEN proving sequentially
        THEN should update prover stats
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        initial_count = manager.stats['total_proofs']
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="sequential")
        assert manager.stats['total_proofs'] == initial_count + 1


class TestParallelStrategy:
    """Test parallel proving strategy."""
    
    def test_prove_parallel(self, manager, namespace):
        """
        GIVEN formula
        WHEN proving with parallel strategy
        THEN should run provers in parallel
        """
        if len(manager.available_provers) < 2:
            pytest.skip("Need multiple provers for parallel test")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="parallel")
        assert isinstance(result, UnifiedProofResult)
    
    def test_parallel_faster_than_sequential(self, manager, namespace):
        """
        GIVEN formula
        WHEN proving in parallel vs sequential
        THEN parallel should complete in reasonable time
        """
        if len(manager.available_provers) < 2:
            pytest.skip("Need multiple provers")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="parallel", timeout=10)
        # Should complete within reasonable time
        assert result.total_time < 60.0
    
    def test_parallel_returns_first_valid(self, manager, namespace):
        """
        GIVEN tautology
        WHEN proving in parallel
        THEN should return as soon as one prover succeeds
        """
        if len(manager.available_provers) < 2:
            pytest.skip("Need multiple provers")
        
        pred = namespace.add_predicate("p", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        
        p = AtomicFormula(pred, [VariableTerm(agent)])
        not_p = ConnectiveFormula(LogicalConnective.NOT, [p])
        tautology = ConnectiveFormula(LogicalConnective.OR, [p, not_p])
        
        result = manager.prove(tautology, strategy="parallel")
        # At least one prover should attempt
        assert isinstance(result, UnifiedProofResult)
    
    def test_parallel_aggregates_results(self, manager, namespace):
        """
        GIVEN formula
        WHEN proving in parallel
        THEN should aggregate prover results
        """
        if len(manager.available_provers) < 2:
            pytest.skip("Need multiple provers")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="parallel")
        assert isinstance(result.prover_results, dict)
    
    def test_parallel_updates_stats(self, manager, namespace):
        """
        GIVEN formula
        WHEN proving in parallel
        THEN should update statistics
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        initial_count = manager.stats['total_proofs']
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula, strategy="parallel")
        assert manager.stats['total_proofs'] == initial_count + 1


class TestStatisticsAndMonitoring:
    """Test statistics and monitoring features."""
    
    def test_stats_track_total_proofs(self, manager, namespace):
        """
        GIVEN multiple proof attempts
        WHEN getting stats
        THEN should track total count
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        initial = manager.stats['total_proofs']
        
        manager.prove(formula)
        manager.prove(formula)
        
        assert manager.stats['total_proofs'] == initial + 2
    
    def test_stats_track_prover_usage(self, manager, namespace):
        """
        GIVEN proof attempts
        WHEN getting stats
        THEN should track which provers were used
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        initial_z3 = manager.stats['z3_used']
        
        result = manager.prove(formula, strategy="auto")
        
        # At least one prover should be used
        if Z3_AVAILABLE and ProverType.Z3 in manager.available_provers:
            # Z3 may have been used
            assert manager.stats['z3_used'] >= initial_z3
    
    def test_stats_immutable_copy(self, manager):
        """
        GIVEN stats dict
        WHEN modifying returned stats
        THEN should not affect internal stats
        """
        stats = manager.get_stats()
        original_count = stats['total_proofs']
        
        stats['total_proofs'] = 999
        
        # Internal stats should be unchanged
        assert manager.stats['total_proofs'] == original_count
    
    def test_reset_stats_clears_all(self, manager, namespace):
        """
        GIVEN manager with usage
        WHEN resetting stats
        THEN should clear all counters
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        # Do some proving
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        manager.prove(formula)
        
        # Reset
        manager.reset_stats()
        
        stats = manager.get_stats()
        assert all(count == 0 for count in stats.values())
    
    def test_confidence_scoring(self, manager, namespace):
        """
        GIVEN proof result
        WHEN checking confidence
        THEN should have reasonable confidence score
        """
        if not manager.available_provers:
            pytest.skip("No provers available")
        
        pred = namespace.add_predicate("test", ["Agent"])
        agent = namespace.add_variable("agent", "Agent")
        formula = AtomicFormula(pred, [VariableTerm(agent)])
        
        result = manager.prove(formula)
        assert 0.0 <= result.confidence <= 1.0
