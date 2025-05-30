#!/usr/bin/env python3
"""
Quick Integration Test for Development Tools
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

def quick_test():
    """Quick validation of core functionality."""
    print("🔍 Quick Integration Test")
    print("=" * 30)

    # Test 1: Basic imports
    print("1. Testing imports...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools import (
            test_generator, codebase_search, documentation_generator,
            lint_python_codebase, run_comprehensive_tests
        )
        print("   ✓ All tools imported")
    except Exception as e:
        print(f"   ✗ Import failed: {e}")
        return False

    # Test 2: Server registration
    print("2. Testing server registration...")
    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        server = IPFSDatasetsMCPServer()
        server.register_tools()

        dev_tools = [name for name in server.tools.keys() if name in [
            'test_generator', 'codebase_search', 'documentation_generator',
            'lint_python_codebase', 'run_comprehensive_tests'
        ]]

        print(f"   ✓ {len(dev_tools)}/5 development tools registered")
        if len(dev_tools) < 5:
            missing = set(['test_generator', 'codebase_search', 'documentation_generator',
                          'lint_python_codebase', 'run_comprehensive_tests']) - set(dev_tools)
            print(f"   Missing: {missing}")

    except Exception as e:
        print(f"   ✗ Registration failed: {e}")
        return False

    # Test 3: Quick function call
    print("3. Testing function execution...")
    try:
        result = codebase_search(
            pattern="import",
            path=".",
            max_depth=1,
            format="text"
        )
        print("   ✓ Codebase search executed successfully")
    except Exception as e:
        print(f"   ✗ Function execution failed: {e}")
        return False

    print("\n✅ Quick test PASSED - Core functionality working!")
    return True

if __name__ == "__main__":
    success = quick_test()
    if success:
        print("\n🚀 Ready for VS Code integration!")
        print("\n📋 Next Steps:")
        print("   1. Test with VS Code Copilot Chat")
        print("   2. Performance optimization")
        print("   3. Phase 2 planning")
    sys.exit(0 if success else 1)
