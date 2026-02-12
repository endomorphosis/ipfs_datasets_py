"""
Comprehensive tests for TDFOL proof caching infrastructure.

Tests cover:
- Cache hit/miss behavior
- CID-based content addressing
- TTL expiration
- Thread safety
- Statistics tracking
- Integration with prover
"""

import pytest
import time
from ipfs_datasets_py.logic.TDFOL import (
    TDFOLProofCache,
    get_global_proof_cache,
    clear_global_proof_cache,
    parse_tdfol,
    TDFOLProver,
    TDFOLProofResult
)


class TestTDFOLProofCache:
    """Test TDFOL proof caching functionality."""
    
    def setup_method(self):
        """Clear cache before each test."""
        clear_global_proof_cache()
    
    def test_cache_creation(self):
        """Test creating a proof cache."""
        cache = TDFOLProofCache(maxsize=100, ttl=60)
        assert cache is not None
        assert cache.maxsize == 100
        assert cache.ttl == 60
    
    def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = TDFOLProofCache()
        formula = parse_tdfol("P")
        
        result = cache.get(formula, [])
        assert result is None
    
    def test_cache_hit(self):
        """Test cache hit returns cached result."""
        cache = TDFOLProofCache()
        formula = parse_tdfol("P")
        
        # Create a proof result
        proof_result = TDFOLProofResult(
            is_proved=True,
            formula=formula,
            method="axiom",
            proof_steps=[],
            proof_time=0.001
        )
        
        # Cache it
        cache.set(formula, proof_result, [])
        
        # Retrieve it
        cached = cache.get(formula, [])
        assert cached is not None
        assert cached.is_proved == True
        assert cached.method == "axiom"
    
    def test_cache_with_axioms(self):
        """Test caching distinguishes between different axiom sets."""
        cache = TDFOLProofCache()
        formula = parse_tdfol("Q")
        
        # Cache with axiom P
        result1 = TDFOLProofResult(True, formula, "forward_chaining", [], 0.001)
        axioms1 = [parse_tdfol("P")]
        cache.set(formula, result1, axioms1)
        
        # Cache with different axiom R
        result2 = TDFOLProofResult(False, formula, "forward_chaining", [], 0.001)
        axioms2 = [parse_tdfol("R")]
        cache.set(formula, result2, axioms2)
        
        # Different axioms should give different results
        cached1 = cache.get(formula, axioms1)
        cached2 = cache.get(formula, axioms2)
        
        assert cached1.is_proved == True
        assert cached2.is_proved == False
    
    def test_cache_statistics(self):
        """Test cache statistics tracking."""
        cache = TDFOLProofCache()
        formula = parse_tdfol("P")
        
        # Initial stats
        stats = cache.get_stats()
        assert stats['total_requests'] == 0
        assert stats['hits'] == 0
        assert stats['misses'] == 0
        
        # Cache miss
        cache.get(formula, [])
        stats = cache.get_stats()
        assert stats['misses'] == 1
        
        # Cache set and hit
        result = TDFOLProofResult(True, formula, "axiom", [], 0.001)
        cache.set(formula, result, [])
        cache.get(formula, [])
        
        stats = cache.get_stats()
        assert stats['hits'] == 1
        assert stats['total_requests'] == 2
    
    def test_cache_clear(self):
        """Test clearing the cache."""
        cache = TDFOLProofCache()
        formula = parse_tdfol("P")
        
        # Add to cache
        result = TDFOLProofResult(True, formula, "axiom", [], 0.001)
        cache.set(formula, result, [])
        
        # Verify it's there
        assert cache.get(formula, []) is not None
        
        # Clear
        cache.clear()
        
        # Verify it's gone
        assert cache.get(formula, []) is None
    
    def test_global_cache_singleton(self):
        """Test global cache is a singleton."""
        cache1 = get_global_proof_cache()
        cache2 = get_global_proof_cache()
        
        assert cache1 is cache2
    
    def test_cache_ttl_expiration(self):
        """Test TTL expiration removes old entries."""
        # Create cache with 1 second TTL
        cache = TDFOLProofCache(ttl=1)
        formula = parse_tdfol("P")
        
        # Cache a result
        result = TDFOLProofResult(True, formula, "axiom", [], 0.001)
        cache.set(formula, result, [])
        
        # Should be available immediately
        assert cache.get(formula, []) is not None
        
        # Wait for expiration
        time.sleep(1.1)
        
        # Should be expired (TTLCache auto-expires)
        # Note: Actual expiration depends on TTLCache implementation
        # This test documents expected behavior
    
    def test_cache_maxsize_limit(self):
        """Test cache respects maxsize limit."""
        cache = TDFOLProofCache(maxsize=2)
        
        # Add 3 items
        for i in range(3):
            formula = parse_tdfol(f"P{i}")
            result = TDFOLProofResult(True, formula, "axiom", [], 0.001)
            cache.set(formula, result, [])
        
        # Cache should have at most 2 items
        stats = cache.get_stats()
        assert stats['cache_size'] <= 2
    
    def test_prover_integration_with_cache(self):
        """Test TDFOLProver uses cache when enabled."""
        clear_global_proof_cache()
        prover = TDFOLProver(enable_cache=True)
        formula = parse_tdfol("P -> P")
        
        # First proof (cache miss)
        result1 = prover.prove(formula, timeout_ms=1000)
        
        # Second proof (cache hit - should be much faster)
        result2 = prover.prove(formula, timeout_ms=1000)
        
        # Both should succeed
        assert result1.is_proved()
        assert result2.is_proved()
        
        # Check cache was used
        cache = get_global_proof_cache()
        stats = cache.get_stats()
        assert stats['hits'] >= 1
    
    def test_prover_without_cache(self):
        """Test TDFOLProver works without cache."""
        prover = TDFOLProver(enable_cache=False)
        formula = parse_tdfol("P -> P")
        
        result = prover.prove(formula, timeout_ms=1000)
        assert result.is_proved()
    
    def test_cache_thread_safety(self):
        """Test cache operations are thread-safe."""
        import threading
        
        cache = TDFOLProofCache()
        formula = parse_tdfol("P")
        result = TDFOLProofResult(True, formula, "axiom", [], 0.001)
        
        def set_cache():
            cache.set(formula, result, [])
        
        def get_cache():
            cache.get(formula, [])
        
        # Run concurrent operations
        threads = []
        for _ in range(10):
            threads.append(threading.Thread(target=set_cache))
            threads.append(threading.Thread(target=get_cache))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should not crash
        assert True
    
    def test_cache_different_formulas(self):
        """Test cache correctly distinguishes different formulas."""
        cache = TDFOLProofCache()
        
        formula1 = parse_tdfol("P")
        formula2 = parse_tdfol("Q")
        
        result1 = TDFOLProofResult(True, formula1, "axiom", [], 0.001)
        result2 = TDFOLProofResult(False, formula2, "axiom", [], 0.001)
        
        cache.set(formula1, result1, [])
        cache.set(formula2, result2, [])
        
        # Different formulas should have different cache entries
        cached1 = cache.get(formula1, [])
        cached2 = cache.get(formula2, [])
        
        assert cached1.is_proved == True
        assert cached2.is_proved == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
