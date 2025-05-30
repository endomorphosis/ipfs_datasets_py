#!/usr/bin/env python3
"""
Minimal import test to isolate hanging issues.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

def test_import_order():
    """Test imports in specific order to identify hanging point."""
    
    print("1. Testing base_tool import...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool
        print("   ✅ base_tool imported")
    except Exception as e:
        print(f"   ❌ base_tool error: {e}")
        return False
    
    print("2. Testing codebase_search import...")
    try:
        import ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search
        print("   ✅ codebase_search module imported")
    except Exception as e:
        print(f"   ❌ codebase_search error: {e}")
        return False
    
    print("3. Testing codebase_search function import...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
        print("   ✅ codebase_search function imported")
    except Exception as e:
        print(f"   ❌ codebase_search function error: {e}")
        return False
    
    print("4. Testing linting_tools module import...")
    try:
        import ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools
        print("   ✅ linting_tools module imported")
    except Exception as e:
        print(f"   ❌ linting_tools module error: {e}")
        return False
    
    print("5. Testing LintingTools class import...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import LintingTools
        print("   ✅ LintingTools class imported")
    except Exception as e:
        print(f"   ❌ LintingTools class error: {e}")
        return False
    
    print("\n✅ All imports successful!")
    return True

if __name__ == "__main__":
    test_import_order()
