"""Tests for formula validation caching."""

import pytest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_cache import (
    FormulaCache,
    CachedFormulaResult,
)


class TestFormulaCacheBasics:
    """Test basic cache operations."""
    
    def test_cache_miss_on_empty_cache(self):
        """Verify cache miss for formula not in cache."""
        cache = FormulaCache(maxsize=10)
        result = cache.get("P(x) -> Q(x)", prover_name="z3")
        assert result is None
        assert cache.stats['misses'] == 1
        assert cache.stats['hits'] == 0
    
    def test_cache_hit_after_put(self):
        """Verify cache hit after storing formula."""
        cache = FormulaCache(maxsize=10)
        
        # Store formula
        cache.put(
            formula="P(x) -> Q(x)",
            is_valid=True,
            confidence=0.95,
            prover_name="z3",
            proof_time=0.1,
        )
        
        # Retrieve and verify hit
        result = cache.get("P(x) -> Q(x)", prover_name="z3")
        assert result is not None
        assert result.is_valid is True
        assert result.confidence == 0.95
        assert result.proof_time == 0.1
        assert cache.stats['hits'] == 1
        assert cache.stats['misses'] == 0
    
    def test_formula_and_prover_key_specificity(self):
        """Verify cache keys are specific to both formula and prover."""
        cache = FormulaCache(maxsize=10)
        formula = "P(x) -> Q(x)"
        
        # Store with z3
        cache.put(
            formula=formula,
            is_valid=True,
            confidence=0.95,
            prover_name="z3",
            proof_time=0.1,
        )
        
        # Miss with different prover
        result = cache.get(formula, prover_name="cvc5")
        assert result is None
        
        # Hit with same prover
        result = cache.get(formula, prover_name="z3")
        assert result is not None
        assert result.prover_name == "z3"


class TestFormulaCacheLRU:
    """Test LRU eviction behavior."""
    
    def test_lru_eviction_at_maxsize(self):
        """Verify LRU eviction when cache reaches maxsize."""
        cache = FormulaCache(maxsize=3)
        formulas = ["P(x)", "Q(x)", "R(x)", "S(x)"]
        
        # Fill cache
        for f in formulas:
            cache.put(f, is_valid=True, confidence=0.9, prover_name="z3", proof_time=0.1)
        
        # Verify size doesn't exceed maxsize
        assert len(cache._cache) == 3
        assert cache.stats['evictions'] == 1
        
        # Verify first formula was evicted
        assert cache.get("P(x)", prover_name="z3") is None
        assert cache.get("S(x)", prover_name="z3") is not None
    
    def test_lru_order_updates_on_access(self):
        """Verify LRU order updates when accessing cached items."""
        cache = FormulaCache(maxsize=3)
        
        # Fill cache with 3 items
        cache.put("P(x)", is_valid=True, confidence=0.9, prover_name="z3", proof_time=0.1)
        cache.put("Q(x)", is_valid=True, confidence=0.9, prover_name="z3", proof_time=0.1)
        cache.put("R(x)", is_valid=True, confidence=0.9, prover_name="z3", proof_time=0.1)
        
        # Access first item (should move to end of LRU order)
        cache.get("P(x)", prover_name="z3")
        
        # Add new item (should evict Q, not P)
        cache.put("S(x)", is_valid=True, confidence=0.9, prover_name="z3", proof_time=0.1)
        
        assert cache.get("Q(x)", prover_name="z3") is None
        assert cache.get("P(x)", prover_name="z3") is not None


class TestFormulaCacheStats:
    """Test cache statistics tracking."""
    
    def test_hit_rate_calculation(self):
        """Verify hit rate is correctly calculated."""
        cache = FormulaCache(maxsize=10)
        formula = "P(x) -> Q(x)"
        
        # Store formula
        cache.put(formula, is_valid=True, confidence=0.9, prover_name="z3", proof_time=0.1)
        
        # Access 9 times (8 hits + 1 miss)
        for _ in range(8):
            cache.get(formula, prover_name="z3")
        cache.get("X(y)", prover_name="z3")  # Miss
        
        stats = cache.get_stats()
        assert stats['hits'] == 8
        assert stats['misses'] == 1
        assert stats['hit_rate_percent'] == 88.89
        assert stats['total_lookups'] == 9
    
    def test_stats_with_empty_cache(self):
        """Verify stats handle empty cache correctly."""
        cache = FormulaCache(maxsize=10)
        stats = cache.get_stats()
        
        assert stats['size'] == 0
        assert stats['hit_rate_percent'] == 0.0
        assert stats['miss_rate_percent'] == 0.0


class TestFormulaCacheClear:
    """Test cache clearing."""
    
    def test_clear_empties_cache(self):
        """Verify clear() empties the cache."""
        cache = FormulaCache(maxsize=10)
        
        # Fill cache
        for i in range(5):
            cache.put(
                f"P{i}(x)",
                is_valid=True,
                confidence=0.9,
                prover_name="z3",
                proof_time=0.1
            )
        
        assert len(cache._cache) == 5
        
        # Clear
        cache.clear()
        assert len(cache._cache) == 0
        assert cache.get("P0(x)", prover_name="z3") is None


class TestFormulaCacheErrorHandling:
    """Test error case handling."""
    
    def test_cache_stores_error_message(self):
        """Verify error messages are stored in cache."""
        cache = FormulaCache(maxsize=10)
        error_msg = "Z3 returned unknown (timeout or resource limit)"
        
        cache.put(
            formula="P(x)",
            is_valid=False,
            confidence=0.0,
            prover_name="z3",
            proof_time=5.0,
            error_message=error_msg,
        )
        
        result = cache.get("P(x)", prover_name="z3")
        assert result.error_message == error_msg
        assert result.is_valid is False


class TestFormulaCacheIntegration:
    """Integration tests with realistic usage patterns."""
    
    def test_repeated_formula_validation(self):
        """Simulate repeated validation of same formulas."""
        cache = FormulaCache(maxsize=100)
        formulas = [
            "P(x) -> Q(x)",
            "Q(x) -> R(x)",
            "R(x) -> P(x)",
        ]
        
        # Simulate 100 validations of 3 formulas
        for _ in range(100):
            for formula in formulas:
                result = cache.get(formula, prover_name="z3")
                if result is None:
                    # Simulate prover work
                    cache.put(
                        formula=formula,
                        is_valid=True,
                        confidence=0.95,
                        prover_name="z3",
                        proof_time=0.5,
                    )
        
        stats = cache.get_stats()
        # Should have high hit rate: 100 attempts per formula * 3 formulas = 300 total
        # First 3 were misses, rest were hits
        assert stats['hits'] > 290
        assert stats['hit_rate_percent'] > 96.0
    
    def test_cache_repr(self):
        """Verify string representation."""
        cache = FormulaCache(maxsize=50)
        cache.put("P(x)", is_valid=True, confidence=0.9, prover_name="z3", proof_time=0.1)
        
        repr_str = repr(cache)
        assert "FormulaCache" in repr_str
        assert "size=1" in repr_str or "1/50" in repr_str


class TestFormulaCacheKeyGeneration:
    """Test cache key generation and uniqueness."""
    
    def test_same_formula_same_key(self):
        """Verify identical formulas produce identical keys."""
        cache = FormulaCache()
        formula = "P(x) -> Q(x)"
        
        key1 = cache._get_formula_key(formula, "z3")
        key2 = cache._get_formula_key(formula, "z3")
        
        assert key1 == key2
        assert len(key1) == 64  # SHA-256 produces 64 hex characters
    
    def test_different_formulas_different_keys(self):
        """Verify different formulas produce different keys."""
        cache = FormulaCache()
        
        key1 = cache._get_formula_key("P(x) -> Q(x)", "z3")
        key2 = cache._get_formula_key("Q(x) -> P(x)", "z3")
        
        assert key1 != key2
    
    def test_different_provers_different_keys(self):
        """Verify same formula with different provers produce different keys."""
        cache = FormulaCache()
        formula = "P(x) -> Q(x)"
        
        key1 = cache._get_formula_key(formula, "z3")
        key2 = cache._get_formula_key(formula, "cvc5")
        
        assert key1 != key2
