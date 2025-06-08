#!/usr/bin/env python3
"""
Synchronous validation script for the ipfs_datasets_py integration.
This script tests basic functionality without async/await to avoid event loop issues.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_basic_imports():
    """Test basic module imports."""
    print("=" * 60)
    print("🧪 TESTING BASIC IMPORTS")
    print("=" * 60)
    
    tests = []
    
    # Test main package import
    try:
        import ipfs_datasets_py
        print("✅ ipfs_datasets_py package imported successfully")
        tests.append(("ipfs_datasets_py", True))
        
        # Check feature flags
        features = {
            'EMBEDDINGS_ENABLED': getattr(ipfs_datasets_py, 'EMBEDDINGS_ENABLED', False),
            'VECTOR_STORES_ENABLED': getattr(ipfs_datasets_py, 'VECTOR_STORES_ENABLED', False),
            'ADVANCED_MCP_ENABLED': getattr(ipfs_datasets_py, 'ADVANCED_MCP_ENABLED', False),
            'FASTAPI_ENABLED': getattr(ipfs_datasets_py, 'FASTAPI_ENABLED', False)
        }
        print("📊 Feature flags:", features)
        
    except Exception as e:
        print(f"❌ Failed to import ipfs_datasets_py: {e}")
        tests.append(("ipfs_datasets_py", False))
    
    # Test embedding modules
    try:
        from ipfs_datasets_py.embeddings import EmbeddingCore, EmbeddingSchema
        print("✅ Embedding modules imported successfully")
        tests.append(("embeddings", True))
    except Exception as e:
        print(f"❌ Failed to import embedding modules: {e}")
        tests.append(("embeddings", False))
    
    # Test vector store modules
    try:
        from ipfs_datasets_py.vector_stores import BaseVectorStore
        print("✅ Vector store modules imported successfully")
        tests.append(("vector_stores", True))
    except Exception as e:
        print(f"❌ Failed to import vector store modules: {e}")
        tests.append(("vector_stores", False))
    
    return tests

def test_mcp_tool_imports():
    """Test MCP tool imports."""
    print("\n" + "=" * 60)
    print("🔧 TESTING MCP TOOL IMPORTS")
    print("=" * 60)
    
    tool_categories = [
        "admin_tools",
        "auth_tools", 
        "cache_tools",
        "analysis_tools",
        "embedding_tools",
        "vector_tools",
        "workflow_tools",
        "monitoring_tools"
    ]
    
    tests = []
    
    for category in tool_categories:
        try:
            # Try to import the tool module
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
            __import__(module_path)
            print(f"✅ {category} imported successfully")
            tests.append((category, True))
        except Exception as e:
            print(f"❌ Failed to import {category}: {e}")
            tests.append((category, False))
    
    return tests

def test_server_imports():
    """Test server component imports."""
    print("\n" + "=" * 60)
    print("🌐 TESTING SERVER IMPORTS")
    print("=" * 60)
    
    tests = []
    
    # Test MCP server
    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        print("✅ MCP server imported successfully")
        tests.append(("mcp_server", True))
    except Exception as e:
        print(f"❌ Failed to import MCP server: {e}")
        tests.append(("mcp_server", False))
    
    # Test FastAPI service
    try:
        from ipfs_datasets_py.fastapi_service import app
        print("✅ FastAPI service imported successfully") 
        tests.append(("fastapi_service", True))
    except Exception as e:
        print(f"❌ Failed to import FastAPI service: {e}")
        tests.append(("fastapi_service", False))
    
    return tests

def test_dependency_availability():
    """Test if key dependencies are available."""
    print("\n" + "=" * 60)
    print("📦 TESTING DEPENDENCY AVAILABILITY")
    print("=" * 60)
    
    key_deps = [
        "numpy",
        "pandas", 
        "scikit-learn",
        "transformers",
        "sentence_transformers",
        "qdrant_client",
        "elasticsearch",
        "faiss-cpu",
        "fastapi",
        "uvicorn",
        "datasets"
    ]
    
    tests = []
    
    for dep in key_deps:
        try:
            __import__(dep.replace('-', '_'))
            print(f"✅ {dep} available")
            tests.append((dep, True))
        except ImportError:
            print(f"⚠️  {dep} not available")
            tests.append((dep, False))
    
    return tests

def generate_report(all_tests):
    """Generate a summary report."""
    print("\n" + "=" * 60)
    print("📋 VALIDATION SUMMARY REPORT")
    print("=" * 60)
    
    total_tests = len(all_tests)
    passed_tests = sum(1 for _, status in all_tests if status)
    failed_tests = total_tests - passed_tests
    
    print(f"📊 Total tests: {total_tests}")
    print(f"✅ Passed: {passed_tests}")
    print(f"❌ Failed: {failed_tests}")
    print(f"📈 Success rate: {(passed_tests/total_tests)*100:.1f}%")
    
    if failed_tests > 0:
        print("\n❌ Failed tests:")
        for name, status in all_tests:
            if not status:
                print(f"  - {name}")
    
    return passed_tests, failed_tests

def main():
    """Run all validation tests."""
    print("🚀 Starting ipfs_datasets_py Integration Validation")
    print(f"📂 Project root: {project_root}")
    print(f"🐍 Python version: {sys.version}")
    
    all_tests = []
    
    # Run all test categories
    all_tests.extend(test_basic_imports())
    all_tests.extend(test_mcp_tool_imports())
    all_tests.extend(test_server_imports())
    all_tests.extend(test_dependency_availability())
    
    # Generate report
    passed, failed = generate_report(all_tests)
    
    # Save results
    results_file = project_root / "sync_validation_results.txt"
    with open(results_file, 'w') as f:
        f.write(f"Sync Validation Results\n")
        f.write(f"======================\n")
        f.write(f"Total tests: {len(all_tests)}\n")
        f.write(f"Passed: {passed}\n")
        f.write(f"Failed: {failed}\n")
        f.write(f"Success rate: {(passed/len(all_tests))*100:.1f}%\n\n")
        
        f.write("Test Details:\n")
        for name, status in all_tests:
            f.write(f"  {name}: {'PASS' if status else 'FAIL'}\n")
    
    print(f"\n💾 Results saved to: {results_file}")
    
    # Exit with appropriate code
    if failed == 0:
        print("\n🎉 All tests passed! Integration validation successful.")
        return 0
    else:
        print(f"\n⚠️  {failed} tests failed. See report for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
