"""
Unit tests for CodeQL cache module.
"""

import os
import tempfile
import time
import pytest
from pathlib import Path

from ipfs_datasets_py.caching.codeql_cache import (
    CodeQLCache,
    CodeQLScanResult,
    get_global_codeql_cache,
    configure_codeql_cache
)


class TestCodeQLScanResult:
    """Test CodeQLScanResult dataclass."""
    
    def test_create_scan_result(self):
        """Test creating a scan result."""
        result = CodeQLScanResult(
            commit_sha="abc123",
            scan_config_hash="def456",
            results={"runs": []},
            timestamp=time.time(),
            scan_duration=300.0,
            alerts_count=5,
            severity_breakdown={"high": 2, "medium": 3}
        )
        
        assert result.commit_sha == "abc123"
        assert result.alerts_count == 5
        assert result.severity_breakdown["high"] == 2
    
    def test_to_dict_and_from_dict(self):
        """Test serialization and deserialization."""
        original = CodeQLScanResult(
            commit_sha="abc123",
            scan_config_hash="def456",
            results={"runs": []},
            timestamp=time.time(),
            scan_duration=300.0,
            alerts_count=5,
            severity_breakdown={"high": 2, "medium": 3},
            sarif_location="/path/to/sarif"
        )
        
        # Convert to dict
        data = original.to_dict()
        
        # Convert back
        restored = CodeQLScanResult.from_dict(data)
        
        assert restored.commit_sha == original.commit_sha
        assert restored.alerts_count == original.alerts_count
        assert restored.sarif_location == original.sarif_location


class TestCodeQLCache:
    """Test CodeQLCache class."""
    
    @pytest.fixture
    def temp_cache_dir(self):
        """Create temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    @pytest.fixture
    def cache(self, temp_cache_dir):
        """Create a CodeQLCache instance for testing."""
        return CodeQLCache(
            cache_dir=temp_cache_dir,
            default_ttl=3600,
            enable_p2p=False  # Disable P2P for unit tests
        )
    
    def test_initialize_cache(self, cache, temp_cache_dir):
        """Test cache initialization."""
        assert cache.cache_dir == Path(temp_cache_dir)
        assert cache.default_ttl == 3600
        assert cache.cache_dir.exists()
    
    def test_compute_scan_config_hash(self, cache):
        """Test scan configuration hashing."""
        config1 = {"queries": "security-extended", "languages": ["python"]}
        config2 = {"languages": ["python"], "queries": "security-extended"}
        config3 = {"queries": "security-extended", "languages": ["java"]}
        
        hash1 = cache._compute_scan_config_hash(config1)
        hash2 = cache._compute_scan_config_hash(config2)
        hash3 = cache._compute_scan_config_hash(config3)
        
        # Same config (different order) should give same hash
        assert hash1 == hash2
        
        # Different config should give different hash
        assert hash1 != hash3
    
    def test_make_cache_key(self, cache):
        """Test cache key generation."""
        key1 = cache._make_cache_key(
            "owner/repo",
            "abc123",
            "hash456",
            "python"
        )
        
        key2 = cache._make_cache_key(
            "owner/repo",
            "abc123",
            "hash456",
            "python"
        )
        
        key3 = cache._make_cache_key(
            "owner/repo",
            "abc123",
            "hash456",
            "java"
        )
        
        # Same parameters should give same key
        assert key1 == key2
        
        # Different language should give different key
        assert key1 != key3
        
        # Key should contain all components
        assert "owner/repo" in key1
        assert "abc123" in key1
        assert "python" in key1
    
    def test_put_and_get_scan_result(self, cache):
        """Test storing and retrieving scan results."""
        repo = "owner/repo"
        commit_sha = "abc123def456"
        scan_config = {"queries": "security-extended"}
        results = {"runs": [{"results": [{"level": "error"}]}]}
        
        # Store result
        cache_key = cache.put_scan_result(
            repo=repo,
            commit_sha=commit_sha,
            scan_config=scan_config,
            results=results,
            scan_duration=300.0,
            language="python"
        )
        
        assert cache_key is not None
        
        # Retrieve result
        cached_result = cache.get_scan_result(
            repo=repo,
            commit_sha=commit_sha,
            scan_config=scan_config,
            language="python"
        )
        
        assert cached_result is not None
        assert cached_result.commit_sha == commit_sha
        assert cached_result.alerts_count == 1
        assert cached_result.scan_duration == 300.0
    
    def test_should_skip_scan_no_cache(self, cache):
        """Test should_skip_scan with no cached result."""
        should_skip, cached = cache.should_skip_scan(
            repo="owner/repo",
            commit_sha="notcached",
            scan_config={"queries": "security-extended"}
        )
        
        assert should_skip is False
        assert cached is None
    
    def test_should_skip_scan_with_cache(self, cache):
        """Test should_skip_scan with cached result."""
        repo = "owner/repo"
        commit_sha = "abc123"
        scan_config = {"queries": "security-extended"}
        
        # Cache a result
        cache.put_scan_result(
            repo=repo,
            commit_sha=commit_sha,
            scan_config=scan_config,
            results={"runs": []},
            scan_duration=300.0
        )
        
        # Check if scan can be skipped
        should_skip, cached = cache.should_skip_scan(
            repo=repo,
            commit_sha=commit_sha,
            scan_config=scan_config
        )
        
        assert should_skip is True
        assert cached is not None
        assert cached.commit_sha == commit_sha
    
    def test_should_skip_scan_with_changed_files(self, cache):
        """Test should_skip_scan with changed files detection."""
        repo = "owner/repo"
        commit_sha = "abc123"
        scan_config = {"queries": "security-extended"}
        language = "python"
        
        # Cache a result
        cache.put_scan_result(
            repo=repo,
            commit_sha=commit_sha,
            scan_config=scan_config,
            results={"runs": []},
            scan_duration=300.0,
            language=language
        )
        
        # No Python files changed - should skip
        should_skip, _ = cache.should_skip_scan(
            repo=repo,
            commit_sha=commit_sha,
            scan_config=scan_config,
            language=language,
            changed_files=["README.md", "docs/guide.txt"]
        )
        assert should_skip is True
        
        # Python files changed - should not skip
        should_skip, _ = cache.should_skip_scan(
            repo=repo,
            commit_sha=commit_sha,
            scan_config=scan_config,
            language=language,
            changed_files=["src/main.py", "README.md"]
        )
        assert should_skip is True  # Still skip for recent cache
    
    def test_invalidate_scan(self, cache):
        """Test cache invalidation."""
        repo = "owner/repo"
        commit_sha = "abc123"
        scan_config = {"queries": "security-extended"}
        
        # Cache a result
        cache.put_scan_result(
            repo=repo,
            commit_sha=commit_sha,
            scan_config=scan_config,
            results={"runs": []},
            scan_duration=300.0
        )
        
        # Verify it's cached
        cached = cache.get_scan_result(repo, commit_sha, scan_config)
        assert cached is not None
        
        # Invalidate
        cache.invalidate_scan(repo, commit_sha, scan_config)
        
        # Verify it's gone
        cached = cache.get_scan_result(repo, commit_sha, scan_config)
        assert cached is None
    
    def test_get_stats(self, cache):
        """Test statistics collection."""
        # Initial stats
        stats = cache.get_stats()
        assert stats["scans_cached"] == 0
        assert stats["scans_retrieved"] == 0
        
        # Cache a result
        cache.put_scan_result(
            repo="owner/repo",
            commit_sha="abc123",
            scan_config={"queries": "security-extended"},
            results={"runs": []},
            scan_duration=300.0
        )
        
        # Stats should update
        stats = cache.get_stats()
        assert stats["scans_cached"] == 1
        
        # Retrieve result
        cache.get_scan_result(
            repo="owner/repo",
            commit_sha="abc123",
            scan_config={"queries": "security-extended"}
        )
        
        # Stats should update
        stats = cache.get_stats()
        assert stats["scans_retrieved"] == 1
        assert stats["scan_time_saved_hours"] > 0
    
    def test_clear_cache(self, cache):
        """Test clearing all cache entries."""
        # Cache multiple results
        for i in range(3):
            cache.put_scan_result(
                repo="owner/repo",
                commit_sha=f"commit{i}",
                scan_config={"queries": "security-extended"},
                results={"runs": []},
                scan_duration=300.0
            )
        
        # Verify cached
        stats = cache.get_stats()
        assert stats["scans_cached"] == 3
        
        # Clear
        cache.clear()
        
        # Verify cleared
        stats = cache.get_stats()
        assert stats["scans_cached"] == 0


class TestGlobalCache:
    """Test global cache instance management."""
    
    def test_get_global_cache(self):
        """Test getting global cache instance."""
        cache1 = get_global_codeql_cache()
        cache2 = get_global_codeql_cache()
        
        # Should return same instance
        assert cache1 is cache2
    
    def test_configure_cache(self):
        """Test configuring global cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = configure_codeql_cache(
                cache_dir=tmpdir,
                default_ttl=7200
            )
            
            assert cache.cache_dir == Path(tmpdir)
            assert cache.default_ttl == 7200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
