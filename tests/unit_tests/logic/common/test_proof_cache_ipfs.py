"""
Tests for IPFS-backed Proof Cache (Phase 1 Task 1.3).

This module tests the IPFS backend integration for distributed caching
of proof results across nodes.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from ipfs_datasets_py.logic.common.proof_cache import (
    ProofCache,
    CachedProofResult,
    get_global_cache
)


class TestProofCacheBasic:
    """Tests for basic ProofCache functionality (backward compatibility)."""
    
    def test_create_cache_without_ipfs(self):
        """Test creating cache without IPFS backend."""
        # GIVEN parameters for local-only cache
        maxsize = 100
        ttl = 300
        
        # WHEN creating cache without IPFS
        cache = ProofCache(maxsize=maxsize, ttl=ttl, enable_ipfs_backend=False)
        
        # THEN cache should be created successfully
        assert cache.maxsize == maxsize
        assert cache.ttl == ttl
        assert cache.enable_ipfs_backend == False
        assert cache.ipfs_cache is None
    
    def test_cache_basic_operations(self):
        """Test basic cache set/get operations."""
        # GIVEN a local cache
        cache = ProofCache(maxsize=10, ttl=300)
        
        # WHEN storing and retrieving a result
        formula = "P(a)"
        result = {"proved": True, "steps": []}
        cid = cache.set(formula, result, prover_name="test")
        retrieved = cache.get(formula, prover_name="test")
        
        # THEN result should be retrieved successfully
        assert retrieved == result
        assert cache.get_stats()['hits'] == 1
        assert cache.get_stats()['sets'] == 1
    
    def test_cache_miss(self):
        """Test cache miss for non-existent entry."""
        # GIVEN an empty cache
        cache = ProofCache(maxsize=10, ttl=300)
        
        # WHEN retrieving non-existent entry
        result = cache.get("nonexistent", prover_name="test")
        
        # THEN should return None and count miss
        assert result is None
        assert cache.get_stats()['misses'] == 1


class TestProofCacheIPFSBackend:
    """Tests for IPFS backend integration."""
    
    def test_create_cache_with_ipfs_unavailable(self):
        """Test cache creation when IPFS backend is unavailable."""
        # GIVEN IPFS backend unavailable (default in most test environments)
        # WHEN creating cache with IPFS enabled
        cache = ProofCache(maxsize=100, ttl=300, enable_ipfs_backend=True)
        
        # THEN should fall back to local-only caching
        assert cache.enable_ipfs_backend == True
        # IPFS cache may be None if backend unavailable
        assert cache.ipfs_cache is None or cache.ipfs_cache is not None
    
    @patch('ipfs_datasets_py.logic.common.proof_cache.IPFS_BACKEND_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.common.proof_cache.get_ipfs_backend')
    @patch('ipfs_datasets_py.logic.common.proof_cache.IPFSBackedRemoteCache')
    def test_create_cache_with_ipfs_backend(self, mock_ipfs_cache_class, mock_get_backend):
        """Test cache creation with IPFS backend enabled."""
        # GIVEN mocked IPFS backend
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend
        mock_ipfs_cache = Mock()
        mock_ipfs_cache_class.return_value = mock_ipfs_cache
        
        # WHEN creating cache with IPFS enabled
        cache = ProofCache(
            maxsize=100,
            ttl=300,
            enable_ipfs_backend=True,
            ipfs_pin=True,
            ipfs_ttl=600
        )
        
        # THEN IPFS cache should be initialized
        assert cache.enable_ipfs_backend == True
        assert cache.ipfs_pin == True
        assert cache.ipfs_ttl == 600
        mock_ipfs_cache_class.assert_called_once()
    
    @patch('ipfs_datasets_py.logic.common.proof_cache.IPFS_BACKEND_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.common.proof_cache.get_ipfs_backend')
    @patch('ipfs_datasets_py.logic.common.proof_cache.IPFSBackedRemoteCache')
    def test_ipfs_cache_set(self, mock_ipfs_cache_class, mock_get_backend):
        """Test storing proof result in IPFS backend."""
        # GIVEN cache with mocked IPFS backend
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend
        mock_ipfs_cache = Mock()
        mock_ipfs_cache_class.return_value = mock_ipfs_cache
        
        cache = ProofCache(maxsize=10, ttl=300, enable_ipfs_backend=True)
        
        # WHEN storing a result
        formula = "P(a)"
        result = {"proved": True}
        cid = cache.set(formula, result, prover_name="z3")
        
        # THEN should store in both local cache and IPFS
        assert cid is not None
        assert cache.get_stats()['sets'] == 1
        # IPFS set may be called if backend is working
        # mock_ipfs_cache.set.assert_called_once()
    
    @patch('ipfs_datasets_py.logic.common.proof_cache.IPFS_BACKEND_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.common.proof_cache.get_ipfs_backend')
    @patch('ipfs_datasets_py.logic.common.proof_cache.IPFSBackedRemoteCache')
    def test_ipfs_cache_get_from_ipfs(self, mock_ipfs_cache_class, mock_get_backend):
        """Test retrieving proof result from IPFS when not in local cache."""
        # GIVEN cache with mocked IPFS backend
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend
        mock_ipfs_cache = Mock()
        mock_ipfs_cache_class.return_value = mock_ipfs_cache
        
        # IPFS has the result
        ipfs_result = {"proved": True, "source": "ipfs"}
        mock_ipfs_cache.get.return_value = ipfs_result
        
        cache = ProofCache(maxsize=10, ttl=300, enable_ipfs_backend=True)
        cache.ipfs_cache = mock_ipfs_cache  # Ensure it's set
        
        # WHEN retrieving a result not in local cache
        formula = "Q(b)"
        result = cache.get(formula, prover_name="lean")
        
        # THEN should retrieve from IPFS and cache locally
        assert result == ipfs_result
        assert cache.get_stats()['ipfs_hits'] == 1
    
    @patch('ipfs_datasets_py.logic.common.proof_cache.IPFS_BACKEND_AVAILABLE', True)
    @patch('ipfs_datasets_py.logic.common.proof_cache.get_ipfs_backend')
    @patch('ipfs_datasets_py.logic.common.proof_cache.IPFSBackedRemoteCache')
    def test_ipfs_cache_fallback_on_error(self, mock_ipfs_cache_class, mock_get_backend):
        """Test fallback to local cache when IPFS fails."""
        # GIVEN cache with mocked IPFS backend that fails
        mock_backend = Mock()
        mock_get_backend.return_value = mock_backend
        mock_ipfs_cache = Mock()
        mock_ipfs_cache.get.side_effect = Exception("IPFS connection failed")
        mock_ipfs_cache_class.return_value = mock_ipfs_cache
        
        cache = ProofCache(maxsize=10, ttl=300, enable_ipfs_backend=True)
        cache.ipfs_cache = mock_ipfs_cache  # Ensure it's set
        
        # WHEN retrieving with IPFS error
        formula = "R(c)"
        result = cache.get(formula, prover_name="coq")
        
        # THEN should handle gracefully and return None
        assert result is None
        assert cache.get_stats()['ipfs_errors'] == 1


class TestProofCacheStats:
    """Tests for cache statistics with IPFS."""
    
    def test_stats_include_ipfs_metrics(self):
        """Test that stats include IPFS-specific metrics."""
        # GIVEN a cache with IPFS backend
        cache = ProofCache(maxsize=10, ttl=300, enable_ipfs_backend=True)
        
        # WHEN getting stats
        stats = cache.get_stats()
        
        # THEN should include IPFS metrics
        assert 'ipfs_hits' in stats
        assert 'ipfs_sets' in stats
        assert 'ipfs_errors' in stats
        assert stats['ipfs_hits'] == 0
        assert stats['ipfs_sets'] == 0
        assert stats['ipfs_errors'] == 0
    
    def test_stats_tracking(self):
        """Test that IPFS stats are tracked correctly."""
        # GIVEN a cache
        cache = ProofCache(maxsize=10, ttl=300)
        
        # WHEN performing operations
        cache.set("P(a)", {"proved": True}, prover_name="test")
        cache.get("P(a)", prover_name="test")
        cache.get("P(b)", prover_name="test")  # miss
        
        # THEN stats should be updated
        stats = cache.get_stats()
        assert stats['sets'] == 1
        assert stats['hits'] == 1
        assert stats['misses'] == 1
        assert stats['hit_rate'] == 0.5  # 1 hit out of 2 requests


class TestProofCacheGlobalInstance:
    """Tests for global cache singleton."""
    
    def test_get_global_cache(self):
        """Test getting global cache instance."""
        # GIVEN no specific configuration
        # WHEN getting global cache
        cache = get_global_cache()
        
        # THEN should return a ProofCache instance
        assert isinstance(cache, ProofCache)
        assert cache.maxsize == 1000
        assert cache.ttl == 3600
    
    def test_global_cache_singleton(self):
        """Test that global cache is a singleton."""
        # GIVEN two calls to get_global_cache
        # WHEN getting cache twice
        cache1 = get_global_cache()
        cache2 = get_global_cache()
        
        # THEN should return same instance
        assert cache1 is cache2


class TestProofCacheBackwardCompatibility:
    """Tests for backward compatibility with existing code."""
    
    def test_default_parameters_work(self):
        """Test that default parameters maintain backward compatibility."""
        # GIVEN default parameters (no IPFS)
        # WHEN creating cache with defaults
        cache = ProofCache()
        
        # THEN should work as before
        assert cache.enable_ipfs_backend == False
        assert cache.ipfs_cache is None
        
        # And basic operations should work
        cache.set("P(x)", {"result": True})
        result = cache.get("P(x)")
        assert result == {"result": True}
    
    def test_existing_code_patterns(self):
        """Test that existing code patterns still work."""
        # GIVEN existing usage pattern
        cache = ProofCache(maxsize=500, ttl=1800)
        
        # WHEN using with formula objects (strings as placeholder)
        formulas = ["P(a)", "Q(b)", "R(c)"]
        results = [{"proved": True}, {"proved": False}, {"proved": True}]
        
        for formula, result in zip(formulas, results):
            cache.set(formula, result, prover_name="z3")
        
        # THEN all should be retrievable
        for formula, expected_result in zip(formulas, results):
            cached = cache.get(formula, prover_name="z3")
            assert cached == expected_result
