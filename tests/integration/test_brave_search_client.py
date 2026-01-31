"""Tests for Brave Search Client with caching.

These tests verify the improved Brave Search client functionality extracted
from the common_crawl_search_engine submodule, including IPFS cache support.
"""

import os
import pytest
import tempfile
from pathlib import Path


class TestBraveSearchClient:
    """Test suite for BraveSearchClient."""
    
    def test_import_brave_search_client(self):
        """Test that BraveSearchClient can be imported."""
        # GIVEN the web_archiving module
        # WHEN importing BraveSearchClient
        from ipfs_datasets_py.web_archiving import BraveSearchClient
        
        # THEN the class should be imported successfully
        assert BraveSearchClient is not None
    
    def test_import_brave_search_functions(self):
        """Test that brave search functions can be imported."""
        # GIVEN the web_archiving module
        # WHEN importing brave search functions
        from ipfs_datasets_py.web_archiving import (
            brave_web_search,
            brave_web_search_page,
            brave_search_cache_stats,
            clear_brave_search_cache
        )
        
        # THEN all functions should be imported successfully
        assert brave_web_search is not None
        assert brave_web_search_page is not None
        assert brave_search_cache_stats is not None
        assert clear_brave_search_cache is not None
    
    def test_import_ipfs_cache(self):
        """Test that IPFS cache can be imported."""
        # GIVEN the web_archiving module
        # WHEN importing IPFS cache
        from ipfs_datasets_py.web_archiving import BraveSearchIPFSCache, HAVE_IPFS_CACHE
        
        # THEN it should be imported (may be None if not available)
        assert HAVE_IPFS_CACHE is not None  # Boolean flag
        if HAVE_IPFS_CACHE:
            assert BraveSearchIPFSCache is not None
    
    def test_brave_search_client_initialization(self):
        """Test BraveSearchClient initialization."""
        # GIVEN the BraveSearchClient class
        from ipfs_datasets_py.web_archiving import BraveSearchClient
        
        # WHEN initializing without API key
        client = BraveSearchClient()
        
        # THEN the client should be initialized
        assert client is not None
        assert hasattr(client, 'config')
        assert hasattr(client, 'search')
        assert hasattr(client, 'search_page')
        assert hasattr(client, 'cache_stats')
        assert hasattr(client, 'clear_cache')
        assert hasattr(client, 'ipfs_cache')  # NEW
        assert hasattr(client, 'ipfs_cache_stats')  # NEW
    
    def test_brave_search_client_ipfs_methods(self):
        """Test that client has IPFS cache management methods."""
        # GIVEN a BraveSearchClient instance
        from ipfs_datasets_py.web_archiving import BraveSearchClient
        
        client = BraveSearchClient()
        
        # WHEN checking for IPFS methods
        # THEN they should exist
        assert hasattr(client, 'ipfs_cache_stats')
        assert hasattr(client, 'ipfs_cache_clear_index')
        assert hasattr(client, 'ipfs_cache_gc')
        assert hasattr(client, 'ipfs_cache_pin')
        assert hasattr(client, 'ipfs_cache_unpin')
        assert hasattr(client, 'ipfs_cache_list_pins')
        
        # All should be callable
        assert callable(client.ipfs_cache_stats)
        assert callable(client.ipfs_cache_clear_index)
        assert callable(client.ipfs_cache_gc)
        assert callable(client.ipfs_cache_pin)
        assert callable(client.ipfs_cache_unpin)
        assert callable(client.ipfs_cache_list_pins)
    
    def test_ipfs_cache_stats_when_disabled(self):
        """Test IPFS cache stats when cache is disabled."""
        # GIVEN a BraveSearchClient instance
        from ipfs_datasets_py.web_archiving import BraveSearchClient
        
        # Ensure IPFS cache is disabled
        os.environ.pop("BRAVE_SEARCH_IPFS_CACHE", None)
        
        client = BraveSearchClient()
        
        # WHEN calling ipfs_cache_stats
        stats = client.ipfs_cache_stats()
        
        # THEN it should return unavailable status
        assert isinstance(stats, dict)
        assert "available" in stats
        assert stats["available"] is False
    
    def test_ipfs_cache_class_initialization(self):
        """Test BraveSearchIPFSCache class initialization."""
        # GIVEN the BraveSearchIPFSCache class
        from ipfs_datasets_py.web_archiving import BraveSearchIPFSCache, HAVE_IPFS_CACHE
        
        if not HAVE_IPFS_CACHE:
            pytest.skip("IPFS cache not available")
        
        # WHEN initializing the cache
        cache = BraveSearchIPFSCache()
        
        # THEN it should have expected methods
        assert hasattr(cache, 'is_available')
        assert hasattr(cache, 'store')
        assert hasattr(cache, 'retrieve')
        assert hasattr(cache, 'stats')
        assert hasattr(cache, 'clear_index')
        assert hasattr(cache, 'gc')
        assert hasattr(cache, 'pin_entry')
        assert hasattr(cache, 'unpin_entry')
        assert hasattr(cache, 'list_pins')
    
    def test_ipfs_cache_stats(self):
        """Test IPFS cache stats method."""
        # GIVEN a BraveSearchIPFSCache instance
        from ipfs_datasets_py.web_archiving import BraveSearchIPFSCache, HAVE_IPFS_CACHE
        
        if not HAVE_IPFS_CACHE:
            pytest.skip("IPFS cache not available")
        
        cache = BraveSearchIPFSCache()
        
        # WHEN calling stats
        stats = cache.stats()
        
        # THEN it should return a dict with expected keys
        assert isinstance(stats, dict)
        assert "available" in stats
        assert "ipfs_connected" in stats
        assert "cid_index_entries" in stats
        assert "cid_index_path" in stats
        assert "pin_enabled" in stats
        assert "ttl_s" in stats
    
    def test_ipfs_cache_clear_index(self):
        """Test IPFS cache clear_index method."""
        # GIVEN a BraveSearchIPFSCache instance
        from ipfs_datasets_py.web_archiving import BraveSearchIPFSCache, HAVE_IPFS_CACHE
        
        if not HAVE_IPFS_CACHE:
            pytest.skip("IPFS cache not available")
        
        cache = BraveSearchIPFSCache()
        
        # WHEN calling clear_index
        result = cache.clear_index()
        
        # THEN it should return success
        assert isinstance(result, dict)
        assert "status" in result
        assert "cleared_entries" in result
    
    def test_brave_search_client_configure(self):
        """Test BraveSearchClient configuration."""
        # GIVEN a BraveSearchClient instance
        from ipfs_datasets_py.web_archiving import BraveSearchClient
        
        client = BraveSearchClient()
        
        # WHEN updating configuration
        result = client.configure(country="uk", safesearch="strict", default_count=20)
        
        # THEN configuration should be updated
        assert result["status"] == "success"
        assert client.config["country"] == "uk"
        assert client.config["safesearch"] == "strict"
        assert client.config["default_count"] == 20
    
    def test_cache_stats_function(self):
        """Test brave_search_cache_stats function."""
        # GIVEN the cache stats function
        from ipfs_datasets_py.web_archiving import brave_search_cache_stats
        
        # WHEN calling cache_stats
        stats = brave_search_cache_stats()
        
        # THEN stats should be returned
        assert isinstance(stats, dict)
        assert "path" in stats
        assert "exists" in stats
        assert "entries" in stats
        assert "ttl_s" in stats
        assert "disabled" in stats
    
    def test_clear_cache_function(self):
        """Test clear_brave_search_cache function."""
        # GIVEN the clear cache function
        from ipfs_datasets_py.web_archiving import clear_brave_search_cache
        
        # WHEN calling clear_cache
        result = clear_brave_search_cache()
        
        # THEN result should contain expected keys
        assert isinstance(result, dict)
        assert "deleted" in result
        assert "freed_bytes" in result
        assert "path" in result
    
    def test_cache_path_with_custom_env_var(self):
        """Test that custom cache path is respected."""
        # GIVEN a custom cache path environment variable
        from ipfs_datasets_py.web_archiving.brave_search_client import brave_search_cache_path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = Path(tmpdir) / "custom_cache.json"
            os.environ["BRAVE_SEARCH_CACHE_PATH"] = str(custom_path)
            
            try:
                # WHEN getting cache path
                cache_path = brave_search_cache_path()
                
                # THEN it should use the custom path
                assert cache_path == custom_path
            finally:
                # Cleanup
                if "BRAVE_SEARCH_CACHE_PATH" in os.environ:
                    del os.environ["BRAVE_SEARCH_CACHE_PATH"]
    
    def test_mcp_tools_cache_functions_import(self):
        """Test that MCP tools cache functions can be imported."""
        # GIVEN the web_archive_tools module
        # WHEN importing cache management functions
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
            get_brave_cache_stats,
            clear_brave_cache
        )
        
        # THEN functions should be imported successfully
        assert get_brave_cache_stats is not None
        assert clear_brave_cache is not None
    
    @pytest.mark.asyncio
    async def test_mcp_get_cache_stats(self):
        """Test MCP get_brave_cache_stats function."""
        # GIVEN the MCP cache stats function
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import get_brave_cache_stats
        
        # WHEN calling the function
        result = await get_brave_cache_stats()
        
        # THEN result should have status
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "unavailable"]
    
    @pytest.mark.asyncio
    async def test_mcp_clear_cache(self):
        """Test MCP clear_brave_cache function."""
        # GIVEN the MCP clear cache function
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import clear_brave_cache
        
        # WHEN calling the function
        result = await clear_brave_cache()
        
        # THEN result should have status
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "unavailable"]
    
    def test_brave_api_class_has_cache_methods(self):
        """Test that BraveSearchAPI class has cache management methods."""
        # GIVEN the BraveSearchAPI class
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import BraveSearchAPI
        
        # WHEN initializing the class
        api = BraveSearchAPI()
        
        # THEN it should have cache management methods
        assert hasattr(api, 'cache_stats')
        assert hasattr(api, 'clear_cache')
        assert callable(api.cache_stats)
        assert callable(api.clear_cache)
    
    def test_brave_api_cache_stats(self):
        """Test BraveSearchAPI cache_stats method."""
        # GIVEN a BraveSearchAPI instance
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import BraveSearchAPI
        
        api = BraveSearchAPI()
        
        # WHEN calling cache_stats
        result = api.cache_stats()
        
        # THEN result should be a dict
        assert isinstance(result, dict)
        assert "status" in result or "path" in result
    
    def test_brave_api_clear_cache(self):
        """Test BraveSearchAPI clear_cache method."""
        # GIVEN a BraveSearchAPI instance
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import BraveSearchAPI
        
        api = BraveSearchAPI()
        
        # WHEN calling clear_cache
        result = api.clear_cache()
        
        # THEN result should be a dict
        assert isinstance(result, dict)
        assert "status" in result or "deleted" in result
    
    def test_install_method_shows_caching_available(self):
        """Test that _install method reports caching availability."""
        # GIVEN a BraveSearchAPI instance
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import BraveSearchAPI
        
        api = BraveSearchAPI()
        
        # WHEN calling _install
        result = api._install()
        
        # THEN result should indicate caching availability
        assert isinstance(result, dict)
        assert "caching_available" in result
    
    def test_config_method_shows_caching_available(self):
        """Test that _config method reports caching availability."""
        # GIVEN a BraveSearchAPI instance
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import BraveSearchAPI
        
        api = BraveSearchAPI()
        
        # WHEN calling _config
        result = api._config()
        
        # THEN result should indicate caching availability
        assert isinstance(result, dict)
        assert "caching_available" in result
