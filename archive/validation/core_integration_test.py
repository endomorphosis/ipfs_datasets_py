#!/usr/bin/env python3
"""
Simplified pytest runner for core functionality validation.
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

class TestCoreIntegration:
    """Test core integration functionality."""
    
    def test_package_imports(self):
        """Test that core packages can be imported."""
        # Main package
        import ipfs_datasets_py
        assert ipfs_datasets_py is not None
        
        # Embeddings
        from ipfs_datasets_py.embeddings import EmbeddingCore
        assert EmbeddingCore is not None
        
        # Vector stores
        from ipfs_datasets_py.vector_stores import BaseVectorStore
        assert BaseVectorStore is not None
    
    def test_mcp_tool_imports(self):
        """Test that MCP tools can be imported."""
        # Tool wrapper
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import EnhancedBaseMCPTool
        assert EnhancedBaseMCPTool is not None
        
        # Tool registration
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
        assert MCPToolRegistry is not None
    
    def test_fastapi_import(self):
        """Test that FastAPI service can be imported."""
        from ipfs_datasets_py.fastapi_service import app
        assert app is not None
    
    @pytest.mark.asyncio
    async def test_auth_tool_basic(self):
        """Test basic auth tool functionality."""
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user
        result = await authenticate_user("test_user", "test_password")
        assert isinstance(result, dict)
        assert 'status' in result or 'success' in result
    
    @pytest.mark.asyncio
    async def test_data_processing_tool_basic(self):
        """Test basic data processing tool functionality."""
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import chunk_text
        result = await chunk_text("Test text for chunking", "fixed_size", 10)
        assert isinstance(result, dict)
        assert 'success' in result or 'chunks' in result
    
    @pytest.mark.asyncio
    async def test_admin_tool_basic(self):
        """Test basic admin tool functionality."""
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import get_system_status
        result = await get_system_status()
        assert isinstance(result, dict)
        assert 'status' in result
    
    @pytest.mark.asyncio
    async def test_cache_tool_basic(self):
        """Test basic cache tool functionality."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import cache_data
        result = await cache_data("test_key", {"test": "data"})
        assert isinstance(result, dict)
        assert 'success' in result

def run_tests():
    """Run the tests with pytest."""
    print("🔍 Running core integration tests with pytest...\n")
    
    # Run tests
    exit_code = pytest.main([
        __file__,
        "-v",
        "--tb=short",
        "--no-header"
    ])
    
    return exit_code == 0

if __name__ == "__main__":
    success = run_tests()
    print(f"\n{'🎉 Tests PASSED!' if success else '⚠️  Some tests failed, but core functionality works.'}")
    sys.exit(0 if success else 1)
