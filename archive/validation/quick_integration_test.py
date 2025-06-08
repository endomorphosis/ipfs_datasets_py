#!/usr/bin/env python3
"""
Simple integration validation script to test the current state of the migration.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_basic_imports():
    """Test basic imports to validate project structure."""
    print("🔍 Testing basic imports...")
    
    tests = [
        ("ipfs_datasets_py", "Core package"),
        ("ipfs_datasets_py.embeddings", "Embeddings module"),
        ("ipfs_datasets_py.embeddings.core", "Embeddings core"),
        ("ipfs_datasets_py.embeddings.schema", "Embeddings schema"),
        ("ipfs_datasets_py.embeddings.chunker", "Text chunker"),
        ("ipfs_datasets_py.vector_stores", "Vector stores module"),
        ("ipfs_datasets_py.vector_stores.base", "Vector store base"),
        ("ipfs_datasets_py.vector_stores.qdrant_store", "Qdrant store"),
        ("ipfs_datasets_py.vector_stores.elasticsearch_store", "Elasticsearch store"),
        ("ipfs_datasets_py.vector_stores.faiss_store", "FAISS store"),
        ("ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_embedding_generation", "Advanced embeddings"),
        ("ipfs_datasets_py.mcp_server.tools.embedding_tools.advanced_search", "Advanced search"),
        ("ipfs_datasets_py.mcp_server.tools.embedding_tools.shard_embeddings", "Shard embeddings"),
        ("ipfs_datasets_py.mcp_server.tools.embedding_tools.tool_registration", "Tool registration"),
    ]
    
    passed = 0
    failed = 0
    
    for module_name, description in tests:
        try:
            __import__(module_name)
            print(f"  ✅ {description}: {module_name}")
            passed += 1
        except ImportError as e:
            print(f"  ❌ {description}: {module_name} - {e}")
            failed += 1
        except Exception as e:
            print(f"  ⚠️  {description}: {module_name} - {e}")
            failed += 1
    
    print(f"\n📊 Import Results: {passed} passed, {failed} failed")
    return passed, failed

def test_tool_registration():
    """Test tool registration system."""
    print("\n🔧 Testing tool registration...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.embedding_tools.tool_registration import (
            register_enhanced_embedding_tools, 
            get_tool_manifest
        )
        
        tools = register_enhanced_embedding_tools()
        manifest = get_tool_manifest()
        
        print(f"  ✅ Registered {len(tools)} enhanced embedding tools")
        print(f"  ✅ Tool manifest generated with {manifest['total_tools']} tools")
        print(f"  ✅ Categories: {list(manifest['categories'].keys())}")
        return True
        
    except Exception as e:
        print(f"  ❌ Tool registration failed: {e}")
        return False

def test_feature_flags():
    """Test feature flags and integration status."""
    print("\n🚩 Testing feature flags...")
    
    try:
        import ipfs_datasets_py
        
        # Check if feature flags are available
        if hasattr(ipfs_datasets_py, 'FEATURES'):
            features = ipfs_datasets_py.FEATURES
            print(f"  ✅ Feature flags found: {features}")
        else:
            print("  ⚠️  Feature flags not found in main package")
            
        # Check embeddings availability
        if hasattr(ipfs_datasets_py, 'embeddings') or hasattr(ipfs_datasets_py, 'EmbeddingCore'):
            print("  ✅ Embeddings module exposed in main package")
        else:
            print("  ⚠️  Embeddings not exposed in main package")
            
        # Check vector stores availability  
        if hasattr(ipfs_datasets_py, 'vector_stores') or hasattr(ipfs_datasets_py, 'VectorStoreBase'):
            print("  ✅ Vector stores exposed in main package")
        else:
            print("  ⚠️  Vector stores not exposed in main package")
            
        return True
        
    except Exception as e:
        print(f"  ❌ Feature flag test failed: {e}")
        return False

def main():
    """Run all validation tests."""
    print("🚀 IPFS Embeddings Integration Validation")
    print("=" * 50)
    
    # Test basic imports
    passed, failed = test_basic_imports()
    
    # Test tool registration
    tools_ok = test_tool_registration()
    
    # Test feature flags
    features_ok = test_feature_flags()
    
    # Summary
    print("\n" + "=" * 50)
    print("📋 VALIDATION SUMMARY")
    print("=" * 50)
    
    print(f"✅ Imports: {passed} passed, {failed} failed")
    print(f"{'✅' if tools_ok else '❌'} Tool Registration: {'PASSED' if tools_ok else 'FAILED'}")
    print(f"{'✅' if features_ok else '❌'} Feature Flags: {'PASSED' if features_ok else 'FAILED'}")
    
    overall_status = "PASSED" if (failed == 0 and tools_ok and features_ok) else "NEEDS WORK"
    print(f"\n🎯 OVERALL STATUS: {overall_status}")
    
    if overall_status == "NEEDS WORK":
        print("\n📋 Next Steps:")
        if failed > 0:
            print("  - Fix import errors for missing modules")
        if not tools_ok:
            print("  - Debug tool registration system")
        if not features_ok:
            print("  - Update main package __init__.py with feature flags")

if __name__ == "__main__":
    main()
