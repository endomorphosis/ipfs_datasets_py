#!/usr/bin/env python3
"""
Systematic validation and fixing script for remaining issues.
"""

import sys
import ast
import traceback
from pathlib import Path

def validate_python_syntax(file_path):
    """Validate Python file syntax."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        ast.parse(content)
        return True, None
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Error reading file: {e}"

def test_imports():
    """Test critical imports."""
    results = {}
    
    # Test main package
    try:
        import ipfs_datasets_py
        results['main_package'] = True
    except Exception as e:
        results['main_package'] = f"Failed: {e}"
    
    # Test embeddings
    try:
        from ipfs_datasets_py.embeddings import EmbeddingCore
        results['embeddings'] = True
    except Exception as e:
        results['embeddings'] = f"Failed: {e}"
    
    # Test vector stores
    try:
        from ipfs_datasets_py.vector_stores import BaseVectorStore
        results['vector_stores'] = True
    except Exception as e:
        results['vector_stores'] = f"Failed: {e}"
    
    # Test tool wrapper
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import EnhancedBaseMCPTool
        results['tool_wrapper'] = True
    except Exception as e:
        results['tool_wrapper'] = f"Failed: {e}"
    
    # Test tool registration
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
        results['tool_registration'] = True
    except Exception as e:
        results['tool_registration'] = f"Failed: {e}"
    
    # Test FastAPI
    try:
        from ipfs_datasets_py.fastapi_service import app
        results['fastapi'] = True
    except Exception as e:
        results['fastapi'] = f"Failed: {e}"
    
    return results

def main():
    """Run validation tests."""
    print("🔍 Running systematic validation...\n")
    
    # Test syntax of key files
    critical_files = [
        "ipfs_datasets_py/mcp_server/tools/tool_wrapper.py",
        "ipfs_datasets_py/mcp_server/tools/tool_registration.py",
        "ipfs_datasets_py/mcp_server/tools/session_tools/session_tools.py",
        "ipfs_datasets_py/fastapi_service.py"
    ]
    
    print("📋 Syntax validation:")
    for file_path in critical_files:
        if Path(file_path).exists():
            valid, error = validate_python_syntax(file_path)
            if valid:
                print(f"  ✅ {file_path}")
            else:
                print(f"  ❌ {file_path}: {error}")
        else:
            print(f"  ⚠️  {file_path}: File not found")
    
    print("\n🔗 Import validation:")
    import_results = test_imports()
    for component, result in import_results.items():
        if result is True:
            print(f"  ✅ {component}")
        else:
            print(f"  ❌ {component}: {result}")
    
    # Count successes
    success_count = sum(1 for r in import_results.values() if r is True)
    total_tests = len(import_results)
    
    print(f"\n📊 Results: {success_count}/{total_tests} components working")
    
    if success_count == total_tests:
        print("🎉 All validation tests passed!")
        return True
    else:
        print("⚠️  Some issues detected. Check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
