"""Integration tests for Common Crawl Search Engine submodule.

These tests verify that the common_crawl_search_engine submodule is properly
integrated and accessible through the web_archiving module and MCP tools.
"""

import pytest
from pathlib import Path


class TestCommonCrawlIntegration:
    """Test suite for Common Crawl Search Engine integration."""
    
    def test_submodule_exists(self):
        """Verify the submodule directory exists."""
        # GIVEN the ipfs_datasets_py package
        import ipfs_datasets_py
        package_path = Path(ipfs_datasets_py.__file__).parent
        
        # WHEN checking for the submodule directory
        submodule_path = package_path / "web_archiving" / "common_crawl_search_engine"
        
        # THEN the submodule directory should exist
        assert submodule_path.exists(), "common_crawl_search_engine submodule not found"
        assert submodule_path.is_dir(), "common_crawl_search_engine should be a directory"
    
    def test_integration_module_import(self):
        """Test that the integration module can be imported."""
        # GIVEN the ipfs_datasets_py package
        # WHEN importing the common_crawl_integration module
        from ipfs_datasets_py.web_archiving import common_crawl_integration
        
        # THEN the module should be imported successfully
        assert common_crawl_integration is not None
        assert hasattr(common_crawl_integration, 'CommonCrawlSearchEngine')
        assert hasattr(common_crawl_integration, 'create_search_engine')
    
    def test_search_engine_class_import(self):
        """Test that the CommonCrawlSearchEngine class can be imported."""
        # GIVEN the web_archiving module
        # WHEN importing CommonCrawlSearchEngine
        from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine
        
        # THEN the class should be imported successfully
        assert CommonCrawlSearchEngine is not None
    
    def test_create_search_engine_function(self):
        """Test the create_search_engine convenience function."""
        # GIVEN the web_archiving module
        from ipfs_datasets_py.web_archiving import create_search_engine
        
        # WHEN creating a search engine instance
        engine = create_search_engine()
        
        # THEN it should return a CommonCrawlSearchEngine instance
        assert engine is not None
        assert hasattr(engine, 'is_available')
        assert hasattr(engine, 'search_domain')
        assert hasattr(engine, 'fetch_warc_record')
        assert hasattr(engine, 'list_collections')
    
    def test_search_engine_initialization(self):
        """Test CommonCrawlSearchEngine initialization."""
        # GIVEN the CommonCrawlSearchEngine class
        from ipfs_datasets_py.web_archiving import CommonCrawlSearchEngine
        
        # WHEN initializing with default parameters
        engine = CommonCrawlSearchEngine()
        
        # THEN the engine should be initialized
        assert engine is not None
        assert engine.state_dir is not None
        assert engine.state_dir.exists()  # State dir should be created
    
    def test_mcp_tools_import(self):
        """Test that MCP tools can be imported."""
        # GIVEN the mcp_server web_archive_tools module
        # WHEN importing the advanced common crawl tools
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
            search_common_crawl_advanced,
            fetch_warc_record_advanced,
            list_common_crawl_collections_advanced,
            get_common_crawl_collection_info_advanced
        )
        
        # THEN all tools should be imported successfully
        assert search_common_crawl_advanced is not None
        assert fetch_warc_record_advanced is not None
        assert list_common_crawl_collections_advanced is not None
        assert get_common_crawl_collection_info_advanced is not None
    
    def test_mcp_tools_in_web_archive_tools_all(self):
        """Test that advanced tools are exposed in __all__."""
        # GIVEN the web_archive_tools module
        from ipfs_datasets_py.mcp_server.tools import web_archive_tools
        
        # WHEN checking __all__
        all_exports = web_archive_tools.__all__
        
        # THEN advanced tools should be in __all__
        assert "search_common_crawl_advanced" in all_exports
        assert "fetch_warc_record_advanced" in all_exports
        assert "list_common_crawl_collections_advanced" in all_exports
        assert "get_common_crawl_collection_info_advanced" in all_exports
    
    @pytest.mark.asyncio
    async def test_search_tool_handles_unavailable_submodule(self):
        """Test that search tool gracefully handles unavailable submodule."""
        # GIVEN the search_common_crawl_advanced tool
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import search_common_crawl_advanced
        
        # WHEN calling the tool (submodule may not be initialized)
        result = await search_common_crawl_advanced(
            domain="example.com",
            max_matches=10
        )
        
        # THEN it should return a result (either success or error with fallback info)
        assert result is not None
        assert "status" in result
        assert result["status"] in ["success", "error"]
        
        # IF error, it should provide fallback information
        if result["status"] == "error":
            assert "error" in result
            # Should mention fallback availability
            if "submodule not available" in result.get("error", "").lower():
                assert result.get("fallback_available") is True
                assert result.get("fallback_tool") == "search_common_crawl"
    
    @pytest.mark.asyncio
    async def test_list_collections_tool_structure(self):
        """Test that list_collections_advanced returns proper structure."""
        # GIVEN the list_common_crawl_collections_advanced tool
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
            list_common_crawl_collections_advanced
        )
        
        # WHEN calling the tool
        result = await list_common_crawl_collections_advanced()
        
        # THEN it should return a structured result
        assert result is not None
        assert "status" in result
        assert result["status"] in ["success", "error"]
        
        # IF successful, it should have collections
        if result["status"] == "success":
            assert "collections" in result
            assert "count" in result
            assert "engine" in result
            assert result["engine"] == "common_crawl_search_engine"
    
    def test_gitmodules_entry(self):
        """Verify the submodule is registered in .gitmodules."""
        # GIVEN the repository root
        import ipfs_datasets_py
        package_path = Path(ipfs_datasets_py.__file__).parent
        repo_root = package_path.parent
        
        # WHEN reading .gitmodules
        gitmodules_path = repo_root / ".gitmodules"
        
        # THEN .gitmodules should exist
        assert gitmodules_path.exists(), ".gitmodules file not found"
        
        # AND should contain the common_crawl_search_engine entry
        content = gitmodules_path.read_text()
        assert "common_crawl_search_engine" in content, \
            "common_crawl_search_engine not found in .gitmodules"
        assert "https://github.com/endomorphosis/common_crawl_search_engine" in content, \
            "Submodule URL not found in .gitmodules"
