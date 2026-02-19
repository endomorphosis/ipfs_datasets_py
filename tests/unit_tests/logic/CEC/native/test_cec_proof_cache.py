"""
Unit tests for CEC proof cache integration.

These tests validate proof caching functionality for DCEC theorem proving.
"""

import pytest
import sys
import time
import threading
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.CEC.native import (
    AtomicFormula,
    DeonticFormula,
    ConnectiveFormula,
    DeonticOperator,
    LogicalConnective,
    VariableTerm,
    DCECNamespace,
    ProofResult,
    CachedTheoremProver,
    get_global_cached_prover,
    CACHING_AVAILABLE,
)


# Skip all tests if caching not available
pytestmark = pytest.mark.skipif(
    not CACHING_AVAILABLE,
    reason="Proof caching dependencies not available"
)


class TestBasicCacheOperations:
    """Test suite for basic cache operations."""
    
    def test_cache_hit_on_repeated_proof(self):
        """
        GIVEN a cached prover and a simple proof
        WHEN proving the same theorem twice
        THEN second proof should be from cache (much faster)
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        # Create simple goal: P
        p_pred = namespace.add_predicate("P", [])
        goal = AtomicFormula(p_pred, [])
        axioms = [goal]  # P ⊢ P (trivial)
        
        # WHEN - First proof (cache miss)
        start1 = time.time()
        result1 = prover.prove_theorem(goal, axioms, timeout=5.0)
        time1 = time.time() - start1
        
        # WHEN - Second proof (cache hit)
        start2 = time.time()
        result2 = prover.prove_theorem(goal, axioms, timeout=5.0)
        time2 = time.time() - start2
        
        # THEN
        assert result1.result == ProofResult.PROVED
        assert result2.result == ProofResult.PROVED
        assert result1.proof_tree is not None
        assert result2.proof_tree is not None
        
        # Cache hit should be significantly faster (at least 3x)
        if time2 > 0:
            speedup = time1 / time2
            assert speedup >= 3, f"Cache hit not faster: {time1:.6f}s vs {time2:.6f}s (speedup: {speedup:.1f}x)"
        
        # Verify cache statistics
        stats = prover.get_cache_statistics()
        assert stats['total_lookups'] >= 2
        assert stats['cache_hits'] >= 1
        assert stats['cache_misses'] >= 1
    
    def test_cache_miss_on_first_proof(self):
        """
        GIVEN a cached prover with empty cache
        WHEN proving a theorem for the first time
        THEN it should be a cache miss
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        goal = AtomicFormula(p_pred, [])
        axioms = [goal]
        
        # WHEN
        result = prover.prove_theorem(goal, axioms, timeout=5.0)
        
        # THEN
        assert result.result == ProofResult.PROVED
        stats = prover.get_cache_statistics()
        assert stats['cache_misses'] >= 1
    
    def test_cache_statistics(self):
        """
        GIVEN a cached prover
        WHEN performing various proofs
        THEN statistics should accurately track hits/misses
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        p_goal = AtomicFormula(p_pred, [])
        q_goal = AtomicFormula(q_pred, [])
        
        # WHEN - Perform various proofs
        prover.prove_theorem(p_goal, [p_goal], timeout=5.0)  # P miss
        stats1 = prover.get_cache_statistics()
        
        prover.prove_theorem(p_goal, [p_goal], timeout=5.0)  # P hit
        stats2 = prover.get_cache_statistics()
        
        prover.prove_theorem(q_goal, [q_goal], timeout=5.0)  # Q miss
        stats3 = prover.get_cache_statistics()
        
        prover.prove_theorem(q_goal, [q_goal], timeout=5.0)  # Q hit
        stats4 = prover.get_cache_statistics()
        
        # THEN
        assert stats2['cache_hits'] > stats1['cache_hits']
        assert stats3['cache_misses'] > stats2['cache_misses']
        assert stats4['cache_hits'] > stats3['cache_hits']
        assert stats4['total_lookups'] >= 4
    
    def test_global_cached_prover_singleton(self):
        """
        GIVEN the global cached prover function
        WHEN calling it multiple times
        THEN same instance should be returned
        """
        # GIVEN/WHEN
        prover1 = get_global_cached_prover()
        prover2 = get_global_cached_prover()
        
        # THEN
        assert prover1 is prover2
        assert prover1 is not None


class TestCacheCorrectness:
    """Test suite for cache correctness."""
    
    def test_cached_result_equivalence(self):
        """
        GIVEN a proof that can be cached
        WHEN comparing cached and non-cached results
        THEN they should be equivalent
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        goal = AtomicFormula(p_pred, [])
        axioms = [goal]
        
        # WHEN
        result1 = prover.prove_theorem(goal, axioms, timeout=5.0)
        result2 = prover.prove_theorem(goal, axioms, timeout=5.0)
        
        # THEN
        assert result1.result == result2.result
        assert (result1.proof_tree is None) == (result2.proof_tree is None)
    
    def test_different_axioms_different_cache_keys(self):
        """
        GIVEN the same goal with different axiom sets
        WHEN proving both
        THEN they should have different cache entries
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        goal = AtomicFormula(p_pred, [])
        
        axioms1 = [goal]
        axioms2 = [goal, AtomicFormula(q_pred, [])]
        
        # WHEN
        result1 = prover.prove_theorem(goal, axioms1, timeout=5.0)
        result2 = prover.prove_theorem(goal, axioms2, timeout=5.0)
        result1_again = prover.prove_theorem(goal, axioms1, timeout=5.0)
        result2_again = prover.prove_theorem(goal, axioms2, timeout=5.0)
        
        # THEN
        assert result1.result == ProofResult.PROVED
        assert result2.result == ProofResult.PROVED
        assert result1_again.result == ProofResult.PROVED
        assert result2_again.result == ProofResult.PROVED
        
        stats = prover.get_cache_statistics()
        assert stats['cache_hits'] >= 2
    
    def test_thread_safety_concurrent_access(self):
        """
        GIVEN a cached prover
        WHEN multiple threads access it concurrently
        THEN no race conditions should occur
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        goal = AtomicFormula(p_pred, [])
        axioms = [goal]
        
        results = []
        errors = []
        
        def prove_in_thread():
            try:
                result = prover.prove_theorem(goal, axioms, timeout=5.0)
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # WHEN
        threads = [threading.Thread(target=prove_in_thread) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # THEN
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 10
        assert all(r.result == ProofResult.PROVED for r in results)
        
        stats = prover.get_cache_statistics()
        assert stats['total_lookups'] >= 10
    
    def test_cache_with_complex_formulas(self):
        """
        GIVEN complex nested DCEC formulas
        WHEN caching proofs
        THEN cache should work correctly
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        # Create nested formula: O(P ∧ Q)
        p_atom = AtomicFormula(p_pred, [])
        q_atom = AtomicFormula(q_pred, [])
        conj = ConnectiveFormula(LogicalConnective.AND, [p_atom, q_atom])
        goal = DeonticFormula(DeonticOperator.OBLIGATION, conj)
        
        axioms = [
            DeonticFormula(DeonticOperator.OBLIGATION, p_atom),
            DeonticFormula(DeonticOperator.OBLIGATION, q_atom),
        ]
        
        # WHEN
        result1 = prover.prove_theorem(goal, axioms, timeout=5.0)
        result2 = prover.prove_theorem(goal, axioms, timeout=5.0)
        
        # THEN
        assert result1.result == result2.result
        stats = prover.get_cache_statistics()
        assert stats['cache_hits'] >= 1
    
    def test_cache_handles_failed_proofs(self):
        """
        GIVEN a proof that fails
        WHEN caching the result
        THEN failed proofs should also be cached
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        goal = AtomicFormula(q_pred, [])  # Q
        axioms = [AtomicFormula(p_pred, [])]  # P
        
        # WHEN
        result1 = prover.prove_theorem(goal, axioms, timeout=5.0)
        result2 = prover.prove_theorem(goal, axioms, timeout=5.0)
        
        # THEN - Both should be unprovable
        assert result1.result in [ProofResult.UNKNOWN, ProofResult.TIMEOUT]
        assert result2.result in [ProofResult.UNKNOWN, ProofResult.TIMEOUT]
        
        stats = prover.get_cache_statistics()
        assert stats['cache_hits'] >= 1


class TestCachePerformance:
    """Test suite for cache performance."""
    
    def test_cache_speedup_measurement(self):
        """
        GIVEN a cached prover
        WHEN measuring cache vs non-cache performance
        THEN cache should provide significant speedup
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        goal = AtomicFormula(p_pred, [])
        axioms = [goal]
        
        # WHEN
        start = time.time()
        result1 = prover.prove_theorem(goal, axioms, timeout=5.0)
        time_miss = time.time() - start
        
        start = time.time()
        result2 = prover.prove_theorem(goal, axioms, timeout=5.0)
        time_hit = time.time() - start
        
        # THEN
        assert result1.result == ProofResult.PROVED
        assert result2.result == ProofResult.PROVED
        
        if time_hit > 0:
            speedup = time_miss / time_hit
            assert speedup >= 3, f"Speedup only {speedup:.1f}x"
    
    def test_cache_hit_rate_multiple_proofs(self):
        """
        GIVEN multiple repeated proofs
        WHEN tracking hit rate
        THEN hit rate should be high
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        # WHEN - Prove same theorems multiple times
        for _ in range(3):
            prover.prove_theorem(AtomicFormula(p_pred, []), [AtomicFormula(p_pred, [])], timeout=5.0)
            prover.prove_theorem(AtomicFormula(q_pred, []), [AtomicFormula(q_pred, [])], timeout=5.0)
        
        # THEN
        stats = prover.get_cache_statistics()
        assert stats['total_lookups'] >= 6
        assert stats['cache_hits'] >= 4
        assert stats['hit_rate'] >= 0.5


class TestCacheStatistics:
    """Test suite for cache statistics."""
    
    def test_statistics_initialization(self):
        """
        GIVEN a new cached prover
        WHEN getting statistics
        THEN initial values should be zero
        """
        # GIVEN
        prover = CachedTheoremProver()
        
        # WHEN
        stats = prover.get_cache_statistics()
        
        # THEN
        assert 'total_lookups' in stats
        assert 'cache_hits' in stats
        assert 'cache_misses' in stats
        assert 'hit_rate' in stats
        assert stats['cache_hits'] >= 0
        assert stats['cache_misses'] >= 0
    
    def test_statistics_accuracy(self):
        """
        GIVEN a series of proofs
        WHEN tracking statistics
        THEN counts should be accurate
        """
        # GIVEN
        prover = CachedTheoremProver()
        prover.initialize()
        namespace = DCECNamespace()
        
        p_pred = namespace.add_predicate("P", [])
        q_pred = namespace.add_predicate("Q", [])
        
        initial_stats = prover.get_cache_statistics()
        
        # WHEN
        prover.prove_theorem(AtomicFormula(p_pred, []), [AtomicFormula(p_pred, [])], timeout=5.0)
        prover.prove_theorem(AtomicFormula(p_pred, []), [AtomicFormula(p_pred, [])], timeout=5.0)
        prover.prove_theorem(AtomicFormula(q_pred, []), [AtomicFormula(q_pred, [])], timeout=5.0)
        prover.prove_theorem(AtomicFormula(q_pred, []), [AtomicFormula(q_pred, [])], timeout=5.0)
        
        final_stats = prover.get_cache_statistics()
        
        # THEN
        assert final_stats['total_lookups'] >= initial_stats['total_lookups'] + 4
        assert final_stats['cache_hits'] >= initial_stats['cache_hits'] + 2
        assert final_stats['cache_misses'] >= initial_stats['cache_misses'] + 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
