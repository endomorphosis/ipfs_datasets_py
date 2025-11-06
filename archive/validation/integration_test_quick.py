#!/usr/bin/env python3
"""
Quick integration test for IPFS Embeddings migration
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def test_imports():
    """Test basic imports of migrated components."""
    print("🔍 Testing imports...")
    
    try:
        # Test core embeddings
        from ipfs_datasets_py.embeddings import EmbeddingConfig, Chunker
        print("  ✅ embeddings.EmbeddingConfig imported")
        print("  ✅ embeddings.Chunker imported")
    except ImportError as e:
        print(f"  ❌ embeddings import failed: {e}")
        
    try:
        from ipfs_datasets_py.vector_stores import VectorStoreBase, QdrantStore
        print("  ✅ vector_stores.VectorStoreBase imported")
        print("  ✅ vector_stores.QdrantStore imported")
    except ImportError as e:
        print(f"  ❌ vector_stores import failed: {e}")
        
    try:
        # Test MCP tools
        from ipfs_datasets_py.mcp_server.tools.embedding_tools import embedding_generation
        print("  ✅ embedding_tools.embedding_generation imported")
    except ImportError as e:
        print(f"  ❌ embedding_tools import failed: {e}")

async def test_mcp_tool_availability():
    """Test availability of key MCP tools."""
    print("\n🔧 Testing MCP tool availability...")
    
    # Check for key MCP tools
    tool_categories = [
        'embedding_tools', 'analysis_tools', 'workflow_tools',
        'admin_tools', 'cache_tools', 'monitoring_tools', 
        'sparse_embedding_tools', 'background_task_tools'
    ]
    
    for category in tool_categories:
        try:
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
            __import__(module_path)
            print(f"  ✅ {category} module available")
        except ImportError as e:
            print(f"  ❌ {category} import failed: {e}")

async def test_tool_registration():
    """Test tool registration system."""
    print("\n📝 Testing tool registration...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_registration import register_tools
        print("  ✅ tool_registration.register_tools imported")
        
        # Try to get tools
        tools = await register_tools()
        print(f"  ✅ Found {len(tools)} registered tools")
        
        # Show a few tools
        for i, tool in enumerate(tools[:5]):
            print(f"    - {tool.get('name', 'unnamed')}")
            
    except Exception as e:
        print(f"  ❌ tool registration failed: {e}")

async def test_mcp_server():
    """Test MCP server initialization."""
    print("\n🌐 Testing MCP server...")
    
    try:
        from ipfs_datasets_py.mcp_server.server import MCPServer
        print("  ✅ MCPServer imported")
        
        # Try to create server instance
        server = MCPServer()
        print("  ✅ MCPServer instantiated")
        
    except Exception as e:
        print(f"  ❌ MCP server failed: {e}")

async def main():
    """Run all tests."""
    print("🚀 Starting Integration Test...\n")
    
    await test_imports()
    await test_mcp_tool_availability()
    await test_tool_registration()
    await test_mcp_server()
    
    print("\n✨ Integration test complete!")

if __name__ == "__main__":
    asyncio.run(main())
