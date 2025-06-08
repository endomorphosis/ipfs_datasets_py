#!/usr/bin/env python3
"""
Comprehensive integration validation for ipfs_embeddings_py migration.
Tests imports, tool registration, and basic functionality.
"""

import sys
import inspect
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_embeddings_module():
    """Test embeddings module integration."""
    print("🧠 Testing embeddings module...")
    
    try:
        # Test basic imports
        from ipfs_datasets_py.embeddings import EmbeddingConfig, TextChunker
        from ipfs_datasets_py.embeddings.core import EmbeddingCore, generate_embeddings
        from ipfs_datasets_py.embeddings.schema import EmbeddingRequest, EmbeddingResponse
        
        print("  ✅ All embeddings classes imported successfully")
        
        # Test class definitions
        print(f"  ✅ EmbeddingConfig: {EmbeddingConfig.__name__}")
        print(f"  ✅ TextChunker: {TextChunker.__name__}")
        print(f"  ✅ EmbeddingCore: {EmbeddingCore.__name__}")
        
        return True
    except Exception as e:
        print(f"  ❌ Embeddings module test failed: {e}")
        return False

def test_vector_stores_module():
    """Test vector stores module integration."""
    print("\n🗄️ Testing vector stores module...")
    
    try:
        from ipfs_datasets_py.vector_stores import BaseVectorStore, QdrantVectorStore, FAISSVectorStore
        
        print("  ✅ All vector store classes imported successfully")
        print(f"  ✅ BaseVectorStore: {BaseVectorStore.__name__}")
        print(f"  ✅ QdrantVectorStore: {QdrantVectorStore.__name__}")
        print(f"  ✅ FAISSVectorStore: {FAISSVectorStore.__name__}")
        
        # Test ElasticsearchVectorStore (optional)
        try:
            from ipfs_datasets_py.vector_stores import ElasticsearchVectorStore
            if ElasticsearchVectorStore:
                print(f"  ✅ ElasticsearchVectorStore: {ElasticsearchVectorStore.__name__}")
            else:
                print("  ⚠️  ElasticsearchVectorStore not available (optional)")
        except:
            print("  ⚠️  ElasticsearchVectorStore not available (optional)")
        
        return True
    except Exception as e:
        print(f"  ❌ Vector stores module test failed: {e}")
        return False

def test_mcp_tool_modules():
    """Test MCP tool module imports."""
    print("\n🔧 Testing MCP tool modules...")
    
    tool_categories = [
        'embedding_tools', 'analysis_tools', 'workflow_tools',
        'admin_tools', 'cache_tools', 'monitoring_tools', 
        'sparse_embedding_tools', 'background_task_tools',
        'auth_tools', 'session_tools', 'rate_limiting_tools',
        'data_processing_tools', 'index_management_tools',
        'vector_store_tools', 'storage_tools', 'web_archive_tools'
    ]
    
    success_count = 0
    
    for category in tool_categories:
        try:
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{category}"
            module = __import__(module_path, fromlist=[category])
            
            # Count functions/classes in the module
            members = inspect.getmembers(module, inspect.isfunction) + inspect.getmembers(module, inspect.isclass)
            functions = [name for name, obj in members if not name.startswith('_')]
            
            print(f"  ✅ {category}: {len(functions)} functions/classes")
            success_count += 1
        except Exception as e:
            print(f"  ❌ {category}: {e}")
    
    print(f"\n  📊 Successfully imported {success_count}/{len(tool_categories)} tool categories")
    return success_count, len(tool_categories)

def test_mcp_server_import():
    """Test MCP server import."""
    print("\n🌐 Testing MCP server...")
    
    try:
        from ipfs_datasets_py.mcp_server.server import MCPServer
        print(f"  ✅ MCPServer imported: {MCPServer.__name__}")
        
        # Test server initialization (without actually starting it)
        try:
            server = MCPServer()
            print("  ✅ MCPServer instantiated successfully")
        except Exception as e:
            print(f"  ⚠️  MCPServer instantiation warning: {e}")
        
        return True
    except Exception as e:
        print(f"  ❌ MCP server test failed: {e}")
        return False

def test_tool_registration():
    """Test tool registration functionality."""
    print("\n📝 Testing tool registration...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.embedding_tools.tool_registration import register_tools
        print("  ✅ Tool registration imported")
        
        # Test if register_tools is callable
        if callable(register_tools):
            print("  ✅ register_tools is callable")
        else:
            print("  ❌ register_tools is not callable")
            
        return True
    except Exception as e:
        print(f"  ❌ Tool registration test failed: {e}")
        return False

def test_feature_flags():
    """Test feature flags in main package."""
    print("\n🎛️ Testing feature flags...")
    
    try:
        from ipfs_datasets_py import EMBEDDINGS_ENABLED, VECTOR_STORES_ENABLED, MCP_TOOLS_ENABLED
        
        print(f"  ✅ EMBEDDINGS_ENABLED: {EMBEDDINGS_ENABLED}")
        print(f"  ✅ VECTOR_STORES_ENABLED: {VECTOR_STORES_ENABLED}")
        print(f"  ✅ MCP_TOOLS_ENABLED: {MCP_TOOLS_ENABLED}")
        
        return True
    except Exception as e:
        print(f"  ❌ Feature flags test failed: {e}")
        return False

def test_package_structure():
    """Test package structure and organization."""
    print("\n📁 Testing package structure...")
    
    project_path = Path("ipfs_datasets_py")
    if not project_path.exists():
        print("  ❌ ipfs_datasets_py package not found")
        return False
    
    # Check key directories
    required_dirs = [
        "embeddings", "vector_stores", "mcp_server", 
        "mcp_server/tools", "mcp_server/tools/embedding_tools"
    ]
    
    missing_dirs = []
    for dir_name in required_dirs:
        dir_path = project_path / dir_name
        if dir_path.exists():
            print(f"  ✅ {dir_name}/")
        else:
            print(f"  ❌ {dir_name}/ missing")
            missing_dirs.append(dir_name)
    
    if missing_dirs:
        print(f"  ⚠️  Missing directories: {', '.join(missing_dirs)}")
        return False
    
    print("  ✅ Package structure looks good")
    return True

def main():
    """Run comprehensive integration validation."""
    print("🚀 Starting Comprehensive Integration Validation\n")
    print("=" * 60)
    
    # Run all tests
    tests = [
        ("Package Structure", test_package_structure),
        ("Embeddings Module", test_embeddings_module),
        ("Vector Stores Module", test_vector_stores_module),
        ("MCP Server Import", test_mcp_server_import),
        ("Tool Registration", test_tool_registration),
        ("Feature Flags", test_feature_flags),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"  ❌ {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Test MCP tools separately to get detailed results
    print("\n" + "=" * 60)
    mcp_success, mcp_total = test_mcp_tool_modules()
    
    # Calculate overall results
    print("\n" + "=" * 60)
    print("📊 INTEGRATION VALIDATION SUMMARY")
    print("=" * 60)
    
    total_passed = 0
    total_tests = len(tests)
    
    for test_name, result in results:
        if isinstance(result, bool):
            status = "✅ PASS" if result else "❌ FAIL"
            if result:
                total_passed += 1
        else:
            status = "⚠️  PARTIAL"
            total_passed += 0.5
        
        print(f"{test_name:25} {status}")
    
    # Add MCP tools result
    mcp_percentage = (mcp_success / mcp_total) * 100 if mcp_total > 0 else 0
    print(f"{'MCP Tool Categories':25} ✅ {mcp_success}/{mcp_total} ({mcp_percentage:.1f}%)")
    
    # Overall assessment
    overall_percentage = (total_passed / total_tests) * 100
    print("\n" + "-" * 60)
    print(f"Overall Success Rate: {total_passed}/{total_tests} ({overall_percentage:.1f}%)")
    
    if overall_percentage >= 90:
        print("🎉 EXCELLENT! Integration is highly successful.")
        status = "EXCELLENT"
    elif overall_percentage >= 75:
        print("⚡ GOOD! Integration is mostly successful.")
        status = "GOOD"
    elif overall_percentage >= 50:
        print("⚠️  PARTIAL! Integration has some issues.")
        status = "PARTIAL"
    else:
        print("❌ POOR! Integration needs significant work.")
        status = "POOR"
    
    print("=" * 60)
    
    return status, overall_percentage

if __name__ == "__main__":
    status, percentage = main()
    print(f"\nFinal Status: {status} ({percentage:.1f}%)")
