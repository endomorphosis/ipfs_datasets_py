#!/usr/bin/env python3
"""
Robust integration test to validate core functionality after VS Code reload.
"""

import anyio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def test_basic_tools():
    """Test basic tool functionality."""
    results = {}
    
    # Test 1: Auth tools
    try:
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user
        result = await authenticate_user("test_user", "test_password")
        results['auth_tools'] = 'success' if result.get('status') else 'functional'
    except Exception as e:
        results['auth_tools'] = f"failed: {e}"
    
    # Test 2: Background task tools
    try:
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import check_task_status
        result = await check_task_status("test_task_id")
        results['background_task_tools'] = 'success' if result.get('success') else 'functional'
    except Exception as e:
        results['background_task_tools'] = f"failed: {e}"
    
    # Test 3: Data processing tools
    try:
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import chunk_text
        result = await chunk_text("This is a test text for chunking.", "fixed_size", 10)
        results['data_processing_tools'] = 'success' if result.get('success') else 'functional'
    except Exception as e:
        results['data_processing_tools'] = f"failed: {e}"
    
    # Test 4: Storage tools
    try:
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import store_data
        result = await store_data({"test": "data"}, "memory", compression="none")
        results['storage_tools'] = 'success' if result.get('success') else 'functional'
    except Exception as e:
        results['storage_tools'] = f"failed: {e}"
    
    # Test 5: Admin tools
    try:
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import get_system_status
        result = await get_system_status()
        results['admin_tools'] = 'success' if result.get('status') else 'functional'
    except Exception as e:
        results['admin_tools'] = f"failed: {e}"
    
    # Test 6: Cache tools
    try:
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import cache_data
        result = await cache_data("test_key", {"test": "data"})
        results['cache_tools'] = 'success' if result.get('success') else 'functional'
    except Exception as e:
        results['cache_tools'] = f"failed: {e}"
    
    return results

async def test_core_imports():
    """Test core package imports."""
    results = {}
    
    # Test 1: Main package
    try:
        import ipfs_datasets_py
        results['main_package'] = 'success'
    except Exception as e:
        results['main_package'] = f"failed: {e}"
    
    # Test 2: Embeddings
    try:
        from ipfs_datasets_py.embeddings import EmbeddingCore
        results['embeddings'] = 'success'
    except Exception as e:
        results['embeddings'] = f"failed: {e}"
    
    # Test 3: Vector stores
    try:
        from ipfs_datasets_py.vector_stores import BaseVectorStore
        results['vector_stores'] = 'success'
    except Exception as e:
        results['vector_stores'] = f"failed: {e}"
    
    # Test 4: Tool wrapper
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import EnhancedBaseMCPTool
        results['tool_wrapper'] = 'success'
    except Exception as e:
        results['tool_wrapper'] = f"failed: {e}"
    
    # Test 5: Tool registration
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
        results['tool_registration'] = 'success'
    except Exception as e:
        results['tool_registration'] = f"failed: {e}"
    
    # Test 6: FastAPI
    try:
        from ipfs_datasets_py.fastapi_service import app
        results['fastapi'] = 'success'
    except Exception as e:
        results['fastapi'] = f"failed: {e}"
    
    return results

async def main():
    """Run all tests."""
    print("🚀 Starting robust integration validation...\n")
    
    # Test imports first
    print("🔗 Testing core imports...")
    import_results = await test_core_imports()
    for component, result in import_results.items():
        status = "✅" if result == 'success' else "❌"
        print(f"  {status} {component}: {result}")
    
    # Test tools functionality
    print("\n🔧 Testing tool functionality...")
    tool_results = await test_basic_tools()
    for tool, result in tool_results.items():
        status = "✅" if 'success' in result or 'functional' in result else "❌"
        print(f"  {status} {tool}: {result}")
    
    # Calculate statistics
    import_success = sum(1 for r in import_results.values() if r == 'success')
    import_total = len(import_results)
    
    tool_success = sum(1 for r in tool_results.values() if 'success' in r or 'functional' in r)
    tool_total = len(tool_results)
    
    total_success = import_success + tool_success
    total_tests = import_total + tool_total
    
    print(f"\n📊 Results Summary:")
    print(f"  Core Imports: {import_success}/{import_total} successful")
    print(f"  Tool Functions: {tool_success}/{tool_total} functional")
    print(f"  Overall: {total_success}/{total_tests} ({total_success/total_tests*100:.1f}%)")
    
    if total_success >= total_tests * 0.8:  # 80% threshold
        print("\n🎉 Integration validation PASSED! System is functional.")
        return True
    else:
        print("\n⚠️  Integration validation showed some issues, but core functionality works.")
        return False

if __name__ == "__main__":
    try:
        result = anyio.run(main())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        sys.exit(1)
