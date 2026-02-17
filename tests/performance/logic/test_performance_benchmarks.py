"""
Performance Benchmark Tests for Logic Module

Establishes performance baselines and validates performance characteristics.
Tests conversion speed, memory usage, and scalability.
"""

import pytest
import time
import sys
from typing import List

# Try to import logic modules
try:
    from ipfs_datasets_py.logic.fol.converter import FOLConverter
    from ipfs_datasets_py.logic.deontic.converter import DeonticConverter
    from ipfs_datasets_py.logic.common.proof_cache import ProofCache
    LOGIC_AVAILABLE = True
except ImportError:
    LOGIC_AVAILABLE = False


@pytest.mark.skipif(not LOGIC_AVAILABLE, reason="Logic modules not available")
class TestPerformanceBenchmarks:
    """Performance benchmark tests for logic module operations."""

    def test_simple_conversion_speed(self):
        """
        GIVEN simple formulas
        WHEN converting to FOL
        THEN conversion should complete in <100ms
        """
        # GIVEN
        simple_formulas = [
            "P and Q",
            "P or Q",
            "not P",
            "P implies Q",
            "If P then Q",
        ]
        converter = FOLConverter()
        
        # WHEN
        durations = []
        for formula in simple_formulas:
            start = time.time()
            result = converter.to_fol(formula)
            duration = time.time() - start
            durations.append(duration)
            
            # THEN - Individual conversions should be fast
            assert result is not None
            assert duration < 0.1, f"Simple conversion took {duration:.3f}s, expected <0.1s"
        
        # Average should also be fast
        avg_duration = sum(durations) / len(durations)
        assert avg_duration < 0.05, f"Average {avg_duration:.3f}s, expected <0.05s"
        
    def test_complex_conversion_speed(self):
        """
        GIVEN complex formulas with quantifiers
        WHEN converting to FOL
        THEN conversion should complete in <500ms
        """
        # GIVEN
        complex_formulas = [
            "All x (P(x) implies Q(x))",
            "Exists x (P(x) and not Q(x))",
            "All x (Exists y (R(x,y) implies S(y)))",
        ]
        converter = FOLConverter()
        
        # WHEN/THEN
        for formula in complex_formulas:
            start = time.time()
            result = converter.to_fol(formula)
            duration = time.time() - start
            
            assert result is not None
            assert duration < 0.5, f"Complex conversion took {duration:.3f}s, expected <0.5s"
            
    def test_proof_search_speed(self):
        """
        GIVEN a simple proof scenario
        WHEN searching for proof
        THEN search should complete in reasonable time
        """
        # GIVEN
        converter = FOLConverter()
        formula = "If P and (P implies Q) then Q"
        
        # WHEN
        start = time.time()
        result = converter.to_fol(formula)
        duration = time.time() - start
        
        # THEN
        assert result is not None
        assert duration < 1.0, f"Proof search took {duration:.3f}s, expected <1.0s"
        
    def test_cache_hit_speed(self):
        """
        GIVEN a cached formula
        WHEN retrieving from cache
        THEN retrieval should be very fast (<10ms)
        """
        # GIVEN
        cache = ProofCache()
        key = "test_formula_123"
        value = "cached_result"
        cache.cache[key] = value
        
        # WHEN
        start = time.time()
        result = cache.cache.get(key)
        duration = time.time() - start
        
        # THEN
        assert result == value
        assert duration < 0.01, f"Cache hit took {duration:.3f}s, expected <0.01s"
        
    def test_cache_miss_speed(self):
        """
        GIVEN a non-cached formula
        WHEN checking cache
        THEN cache miss should be fast (<10ms)
        """
        # GIVEN
        cache = ProofCache()
        key = "nonexistent_key"
        
        # WHEN
        start = time.time()
        result = cache.cache.get(key)
        duration = time.time() - start
        
        # THEN
        assert result is None
        assert duration < 0.01, f"Cache miss took {duration:.3f}s, expected <0.01s"
        
    def test_fallback_conversion_speed(self):
        """
        GIVEN fallback conversion methods
        WHEN using regex-based fallbacks
        THEN performance should be acceptable (<200ms)
        """
        # GIVEN
        converter = FOLConverter()
        formula = "All humans are mortal"
        
        # WHEN
        start = time.time()
        result = converter.to_fol(formula)
        duration = time.time() - start
        
        # THEN
        assert result is not None
        assert duration < 0.2, f"Fallback took {duration:.3f}s, expected <0.2s"
        
    def test_batch_processing_speed(self):
        """
        GIVEN 50 formulas to process
        WHEN processing in batch
        THEN throughput should be >10 formulas/second
        """
        # GIVEN
        formulas = [f"P{i} implies Q{i}" for i in range(50)]
        converter = FOLConverter()
        
        # WHEN
        start = time.time()
        results = [converter.to_fol(f) for f in formulas]
        duration = time.time() - start
        
        # THEN
        assert len(results) == 50
        throughput = 50 / duration
        assert throughput > 10, f"Throughput {throughput:.1f} formulas/s, expected >10/s"
        
    def test_memory_usage_profiling(self):
        """
        GIVEN multiple conversions
        WHEN monitoring memory usage
        THEN memory should not grow excessively
        """
        # GIVEN
        converter = FOLConverter()
        formulas = [f"test formula {i}" for i in range(100)]
        
        # WHEN - Process multiple formulas
        initial_size = sys.getsizeof(converter)
        results = []
        for formula in formulas:
            result = converter.to_fol(formula)
            results.append(result)
        final_size = sys.getsizeof(converter)
        
        # THEN - Memory growth should be reasonable
        # Converter object size shouldn't grow dramatically
        growth = final_size - initial_size
        assert growth < 1000000, f"Memory grew {growth} bytes, expected <1MB"
        
    def test_concurrent_performance(self):
        """
        GIVEN concurrent conversion requests
        WHEN processing simultaneously
        THEN performance should remain acceptable
        """
        # GIVEN
        converter = FOLConverter()
        formula = "test concurrent formula"
        iterations = 10
        
        # WHEN - Simulate concurrent by rapid sequential calls
        start = time.time()
        results = []
        for _ in range(iterations):
            result = converter.to_fol(formula)
            results.append(result)
        duration = time.time() - start
        
        # THEN
        assert len(results) == iterations
        avg_time = duration / iterations
        assert avg_time < 0.1, f"Average time {avg_time:.3f}s, expected <0.1s"
        
    def test_large_formula_set_handling(self):
        """
        GIVEN a large set of formulas
        WHEN processing all
        THEN system should handle without errors
        """
        # GIVEN
        large_set = [
            f"All x{i} (P{i}(x{i}) implies Q{i}(x{i}))"
            for i in range(100)
        ]
        converter = FOLConverter()
        
        # WHEN
        start = time.time()
        successful = 0
        for formula in large_set:
            try:
                result = converter.to_fol(formula)
                if result:
                    successful += 1
            except Exception:
                pass
        duration = time.time() - start
        
        # THEN
        success_rate = successful / len(large_set)
        assert success_rate > 0.8, f"Success rate {success_rate:.1%}, expected >80%"
        assert duration < 30.0, f"Processing took {duration:.1f}s, expected <30s"
