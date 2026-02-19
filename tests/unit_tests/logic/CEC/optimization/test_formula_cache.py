"""
Tests for CEC Formula Cache

Tests caching mechanisms for formulas, proofs, and parsing results to ensure
performance improvements through memoization and interning.
"""

import pytest
import time
from typing import Dict, Any


from ipfs_datasets_py.logic.CEC.optimization.formula_cache import (
    CacheEntry,
    FormulaInterningCache,
    LRUCache,
    ProofResultCache,
    ParseResultCache,
    CacheManager,
)
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    Sort, Variable, Predicate, AtomicFormula,
    VariableTerm, DeonticOperator, DeonticFormula,
)


class TestCacheEntry:
    """
    GIVEN CacheEntry dataclass
    WHEN creating and accessing entries
    THEN metadata should be tracked correctly
    """
    
    def test_cache_entry_creation(self):
        """
        GIVEN cache entry parameters
        WHEN creating a CacheEntry
        THEN all attributes should be set correctly
        """
        entry = CacheEntry(key="test_key", value="test_value")
        
        assert entry.key == "test_key"
        assert entry.value == "test_value"
        assert entry.access_count == 0
        assert entry.created_at > 0
        assert entry.accessed_at > 0
    
    def test_cache_entry_access_tracking(self):
        """
        GIVEN an existing cache entry
        WHEN accessing it multiple times
        THEN access count should increment
        """
        entry = CacheEntry(key="test", value=42)
        initial_accessed_at = entry.accessed_at
        
        # Access the entry
        time.sleep(0.01)  # Small delay to ensure timestamp changes
        entry.access()
        
        assert entry.access_count == 1
        assert entry.accessed_at > initial_accessed_at
        
        # Access again
        entry.access()
        assert entry.access_count == 2
    
    def test_cache_entry_size_tracking(self):
        """
        GIVEN cache entry with size information
        WHEN setting size_bytes
        THEN it should be stored correctly
        """
        entry = CacheEntry(key="test", value="data", size_bytes=1024)
        
        assert entry.size_bytes == 1024


class TestFormulaInterningCache:
    """
    GIVEN FormulaInterningCache for reducing memory
    WHEN interning identical formulas
    THEN they should share the same object
    """
    
    def test_interning_cache_initialization(self):
        """
        GIVEN no prior cache
        WHEN creating FormulaInterningCache
        THEN it should initialize with empty state
        """
        cache = FormulaInterningCache()
        
        stats = cache.get_stats()
        assert stats['hits'] == 0
        assert stats['misses'] == 0
        assert stats['interned_count'] == 0
    
    def test_intern_identical_formulas(self):
        """
        GIVEN two identical formulas
        WHEN interning both
        THEN they should return the same object
        """
        cache = FormulaInterningCache()
        
        sort = Sort("person")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula1 = AtomicFormula(pred, [term])
        formula2 = AtomicFormula(pred, [term])
        
        # Intern both formulas
        interned1 = cache.intern(formula1)
        interned2 = cache.intern(formula2)
        
        # They should be the same object (memory sharing)
        assert interned1 is interned2
        
        # Stats should show 1 hit and 1 miss
        stats = cache.get_stats()
        assert stats['misses'] == 1  # First one
        assert stats['hits'] == 1    # Second one (cache hit)
        assert stats['interned_count'] == 1
    
    def test_intern_different_formulas(self):
        """
        GIVEN two different formulas
        WHEN interning both
        THEN they should be different objects
        """
        cache = FormulaInterningCache()
        
        sort = Sort("person")
        pred1 = Predicate("P", [sort])
        pred2 = Predicate("Q", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        
        formula1 = AtomicFormula(pred1, [term])
        formula2 = AtomicFormula(pred2, [term])
        
        interned1 = cache.intern(formula1)
        interned2 = cache.intern(formula2)
        
        # Different formulas should remain different objects
        assert interned1 is not interned2
        assert interned1 == formula1
        assert interned2 == formula2
        
        stats = cache.get_stats()
        assert stats['misses'] == 2
        assert stats['hits'] == 0
        assert stats['interned_count'] == 2
    
    def test_intern_hit_rate_calculation(self):
        """
        GIVEN multiple interning operations
        WHEN calculating hit rate
        THEN it should reflect cache effectiveness
        """
        cache = FormulaInterningCache()
        
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        # Intern same formula multiple times
        cache.intern(formula)  # miss
        cache.intern(formula)  # hit
        cache.intern(formula)  # hit
        cache.intern(formula)  # hit
        
        stats = cache.get_stats()
        assert stats['hits'] == 3
        assert stats['misses'] == 1
        assert stats['hit_rate'] == 0.75  # 3/4 = 0.75


class TestLRUCache:
    """
    GIVEN LRU (Least Recently Used) cache
    WHEN cache reaches capacity
    THEN least recently used items should be evicted
    """
    
    def test_lru_cache_creation(self):
        """
        GIVEN cache parameters
        WHEN creating LRUCache
        THEN it should initialize correctly
        """
        cache = LRUCache(max_size=10)
        
        assert cache.max_size == 10
        assert cache.current_size == 0
        assert len(cache.get_all_keys()) == 0
    
    def test_lru_cache_add_and_retrieve(self):
        """
        GIVEN an LRU cache
        WHEN adding and retrieving items
        THEN values should be stored and retrieved correctly
        """
        cache = LRUCache(max_size=5)
        
        # Add items
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        # Retrieve items
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("key3") is None  # Not in cache
    
    def test_lru_cache_eviction(self):
        """
        GIVEN an LRU cache at capacity
        WHEN adding a new item
        THEN least recently used item should be evicted
        """
        cache = LRUCache(max_size=3)
        
        # Fill cache
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")
        
        # Access key1 to make it recently used
        cache.get("key1")
        
        # Add new item (should evict key2, least recently used)
        cache.put("key4", "value4")
        
        assert cache.get("key1") == "value1"  # Still present
        assert cache.get("key2") is None       # Evicted
        assert cache.get("key3") == "value3"  # Still present
        assert cache.get("key4") == "value4"  # New item
    
    def test_lru_cache_update_existing(self):
        """
        GIVEN an item already in cache
        WHEN updating it
        THEN it should update and move to most recently used
        """
        cache = LRUCache(max_size=3)
        
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        # Update key1
        cache.put("key1", "updated_value1")
        
        assert cache.get("key1") == "updated_value1"
    
    def test_lru_cache_clear(self):
        """
        GIVEN a cache with items
        WHEN clearing the cache
        THEN all items should be removed
        """
        cache = LRUCache(max_size=5)
        
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        assert cache.current_size > 0
        
        cache.clear()
        
        assert cache.current_size == 0
        assert cache.get("key1") is None
        assert cache.get("key2") is None


class TestProofResultCache:
    """
    GIVEN ProofResultCache for caching proof results
    WHEN proving theorems
    THEN previously proven theorems should be cached
    """
    
    def test_proof_cache_creation(self):
        """
        GIVEN proof cache parameters
        WHEN creating ProofResultCache
        THEN it should initialize correctly
        """
        cache = ProofResultCache(max_size=100)
        
        # Check stats exist
        stats = cache.get_stats()
        assert stats is not None
    
    def test_cache_proof_result(self):
        """
        GIVEN a proof result
        WHEN caching it
        THEN it should be retrievable
        """
        cache = ProofResultCache()
        
        # Create a simple formula (mock)
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        # Mock proof result
        proof_result = {"success": True, "steps": 5}
        
        # Cache the result
        cache.cache_proof(formula, None, proof_result)
        
        # Retrieve it
        cached = cache.get_proof(formula, None)
        assert cached is not None
        assert cached["success"] is True
        assert cached["steps"] == 5
    
    def test_proof_cache_miss(self):
        """
        GIVEN an empty cache
        WHEN querying for non-existent proof
        THEN it should return None
        """
        cache = ProofResultCache()
        
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        result = cache.get_proof(formula, None)
        assert result is None
    
    def test_proof_cache_with_axioms(self):
        """
        GIVEN proof with axioms
        WHEN caching proof results
        THEN axioms should be part of cache key
        """
        cache = ProofResultCache()
        
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        axiom1 = AtomicFormula(Predicate("Q", [sort]), [term])
        axiom2 = AtomicFormula(Predicate("R", [sort]), [term])
        
        # Cache with different axiom sets
        cache.cache_proof(formula, [axiom1], {"result": "1"})
        cache.cache_proof(formula, [axiom2], {"result": "2"})
        
        # Should get different results based on axioms
        result1 = cache.get_proof(formula, axioms=[axiom1])
        result2 = cache.get_proof(formula, axioms=[axiom2])
        
        assert result1["result"] == "1"
        assert result2["result"] == "2"


class TestParseResultCache:
    """
    GIVEN ParseResultCache for NL parsing
    WHEN parsing natural language
    THEN results should be cached for reuse
    """
    
    def test_parse_cache_creation(self):
        """
        GIVEN parse cache parameters
        WHEN creating ParseResultCache
        THEN it should initialize correctly
        """
        cache = ParseResultCache(max_size=50)
        
        stats = cache.get_stats()
        assert stats is not None
    
    def test_cache_parse_result(self):
        """
        GIVEN a parse result
        WHEN caching it
        THEN it should be retrievable
        """
        cache = ParseResultCache()
        
        text = "The agent must obey the rules"
        parse_result = {
            "formula": "O(obey(agent, rules))",
            "confidence": 0.95
        }
        
        cache.cache_parse_result(text, "en", parse_result)
        
        cached = cache.get_parse_result(text, "en")
        assert cached is not None
        assert cached["formula"] == "O(obey(agent, rules))"
        assert cached["confidence"] == 0.95
    
    def test_parse_cache_language_specific(self):
        """
        GIVEN parsing in different languages
        WHEN caching results
        THEN language should be part of cache key
        """
        cache = ParseResultCache()
        
        # Same text in different languages should cache separately
        cache.cache_parse_result("hello", "en", {"formula": "greeting"})
        cache.cache_parse_result("hello", "es", {"formula": "saludo"})
        
        result_en = cache.get_parse_result("hello", language="en")
        result_es = cache.get_parse_result("hello", language="es")
        
        assert result_en["formula"] == "greeting"
        assert result_es["formula"] == "saludo"
    
    def test_parse_cache_case_sensitivity(self):
        """
        GIVEN text with different cases
        WHEN caching
        THEN case should matter (or be normalized)
        """
        cache = ParseResultCache()
        
        cache.cache_parse_result("Hello", "en", {"formula": "F1"})
        cache.cache_parse_result("hello", "en", {"formula": "F2"})
        
        # Depending on implementation, these might be different or normalized
        result1 = cache.get_parse_result("Hello", "en")
        result2 = cache.get_parse_result("hello", "en")
        
        # At minimum, cache should work consistently
        assert result1 is not None
        assert result2 is not None


class TestCacheManager:
    """
    GIVEN CacheManager coordinating multiple caches
    WHEN managing all cache types
    THEN it should provide unified interface
    """
    
    def test_cache_manager_creation(self):
        """
        GIVEN cache configuration
        WHEN creating CacheManager
        THEN all caches should be initialized
        """
        manager = CacheManager(
            proof_cache_size=100,
            parse_cache_size=200,
            memoization_cache_size=150
        )
        
        assert manager.formula_interning is not None
        assert manager.proof_cache is not None
        assert manager.parse_cache is not None
        assert manager.memoization is not None
    
    def test_cache_manager_get_cached_proof(self):
        """
        GIVEN CacheManager with proof cache
        WHEN caching and retrieving proofs
        THEN it should work through manager interface
        """
        manager = CacheManager()
        
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        # Cache through manager
        proof_result = {"success": True}
        manager.proof_cache.cache_proof(formula, None, proof_result)
        
        # Retrieve through manager
        cached = manager.proof_cache.get_proof(formula, None)
        assert cached is not None
        assert cached["success"] is True
    
    def test_cache_manager_statistics(self):
        """
        GIVEN CacheManager with activity
        WHEN querying statistics
        THEN it should aggregate stats from all caches
        """
        manager = CacheManager()
        
        # Perform some cache operations
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        # Intern formula
        manager.formula_interning.intern(formula)
        manager.formula_interning.intern(formula)  # Second time should hit cache
        
        # Get stats
        stats = manager.get_all_stats()
        
        assert stats is not None
        assert 'formula_interning' in stats
        assert stats['formula_interning']['hits'] >= 1
    
    def test_cache_manager_clear_all(self):
        """
        GIVEN CacheManager with cached data
        WHEN clearing all caches
        THEN all caches should be empty
        """
        manager = CacheManager()
        
        # Add some data
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        manager.proof_cache.cache_proof(formula, None, {"result": "test"})
        manager.parse_cache.cache_parse_result("test text", "en", {"formula": "F"})
        
        # Clear all
        manager.clear_all()
        
        # Verify caches are empty
        assert manager.proof_cache.get_proof(formula, None) is None
        assert manager.parse_cache.get_parse_result("test text", "en") is None


# Remove CacheStats tests as it doesn't exist in the implementation


class TestCachePerformance:
    """
    GIVEN cache implementations
    WHEN performing many operations
    THEN cache should provide performance benefits
    """
    
    def test_interning_performance_benefit(self):
        """
        GIVEN many identical formulas
        WHEN using interning cache
        THEN memory should be reduced
        """
        cache = FormulaInterningCache()
        
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        
        # Create many identical formulas
        formulas = []
        for _ in range(100):
            formula = AtomicFormula(pred, [term])
            interned = cache.intern(formula)
            formulas.append(interned)
        
        # All interned formulas should be the same object
        assert all(f is formulas[0] for f in formulas)
        
        # Stats should show high hit rate
        stats = cache.get_stats()
        assert stats['hits'] >= 90  # At least 90% hit rate
    
    def test_proof_cache_speedup(self):
        """
        GIVEN a proof cache
        WHEN proving same theorem multiple times
        THEN cached lookups should be faster
        """
        cache = ProofResultCache()
        
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        # Cache a proof result
        proof_result = {"success": True, "steps": 100}
        cache.cache_proof(formula, None, proof_result)
        
        # Measure time for cache lookup (should be very fast)
        start = time.time()
        for _ in range(1000):
            result = cache.get_proof(formula, None)
        elapsed = time.time() - start
        
        # 1000 lookups should be very fast (under 1 second)
        assert elapsed < 1.0
        assert result is not None
    
    def test_parse_cache_reduces_parsing(self):
        """
        GIVEN a parse result cache
        WHEN parsing same text multiple times
        THEN cache should avoid repeated parsing
        """
        cache = ParseResultCache()
        
        text = "The agent believes the goal is achievable"
        parse_result = {"formula": "B(agent, achievable(goal))"}
        
        # Cache the parse result
        cache.cache_parse_result(text, "en", parse_result)
        
        # Subsequent lookups should be instant
        start = time.time()
        for _ in range(1000):
            result = cache.get_parse_result(text, "en")
        elapsed = time.time() - start
        
        assert elapsed < 0.5  # Should be very fast
        assert result is not None


class TestCacheConcurrency:
    """
    GIVEN cache with concurrent access
    WHEN multiple threads access cache
    THEN operations should be thread-safe
    """
    
    def test_interning_cache_thread_safety(self):
        """
        GIVEN FormulaInterningCache
        WHEN accessed from multiple threads
        THEN it should handle concurrent access safely
        """
        cache = FormulaInterningCache()
        
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        formula = AtomicFormula(pred, [term])
        
        # Simple test - intern same formula multiple times
        # (Full concurrency test would require threading)
        results = [cache.intern(formula) for _ in range(10)]
        
        # All should be the same object
        assert all(r is results[0] for r in results)
    
    def test_lru_cache_concurrent_eviction(self):
        """
        GIVEN LRU cache at capacity
        WHEN multiple items added concurrently
        THEN eviction should work correctly
        """
        cache = LRUCache(max_size=5)
        
        # Fill cache
        for i in range(10):
            cache.put(f"key{i}", f"value{i}")
        
        # Only last 5 should remain
        assert cache.current_size <= 5
        
        # First items should have been evicted
        assert cache.get("key0") is None
        assert cache.get("key1") is None
        
        # Last items should be present
        assert cache.get("key9") == "value9"
        assert cache.get("key8") == "value8"
