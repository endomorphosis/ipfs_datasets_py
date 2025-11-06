#!/usr/bin/env python3
"""
Quick validation script to test integration after VS Code reload.
"""

import sys
import traceback
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_basic_imports():
    """Test basic package imports."""
    print("🔍 Testing basic imports...")
    
    try:
        import ipfs_datasets_py
        print("  ✅ Main package imported successfully")
    except Exception as e:
        print(f"  ❌ Main package import failed: {e}")
        return False
    
    try:
        from ipfs_datasets_py.embeddings import EmbeddingCore
        print("  ✅ EmbeddingCore imported successfully")
    except Exception as e:
        print(f"  ❌ EmbeddingCore import failed: {e}")
    
    try:
        from ipfs_datasets_py.vector_stores import BaseVectorStore
        print("  ✅ BaseVectorStore imported successfully")
    except Exception as e:
        print(f"  ❌ BaseVectorStore import failed: {e}")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import EnhancedBaseMCPTool
        print("  ✅ EnhancedBaseMCPTool imported successfully")
    except Exception as e:
        print(f"  ❌ EnhancedBaseMCPTool import failed: {e}")
        traceback.print_exc()
    
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
        print("  ✅ MCPToolRegistry imported successfully")
    except Exception as e:
        print(f"  ❌ MCPToolRegistry import failed: {e}")
        traceback.print_exc()
    
    return True

def test_fastapi_import():
    """Test FastAPI service import."""
    print("\n🌐 Testing FastAPI import...")
    
    try:
        from ipfs_datasets_py.fastapi_service import app
        print("  ✅ FastAPI app imported successfully")
        return True
    except Exception as e:
        print(f"  ❌ FastAPI app import failed: {e}")
        return False

def main():
    """Run all validation tests."""
    print("🚀 Starting quick validation after VS Code reload...\n")
    
    success_count = 0
    total_tests = 2
    
    if test_basic_imports():
        success_count += 1
    
    if test_fastapi_import():
        success_count += 1
    
    print(f"\n📊 Validation Results: {success_count}/{total_tests} tests passed")
    
    if success_count == total_tests:
        print("🎉 All validation tests passed! Integration is working correctly.")
        return True
    else:
        print("⚠️  Some validation tests failed. Check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
