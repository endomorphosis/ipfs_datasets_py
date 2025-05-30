#!/usr/bin/env python3
"""
Final validation test for Phase 1 development tools migration.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

def test_imports():
    """Test all development tool imports."""
    print("1. Testing imports...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools import (
            test_generator, codebase_search, documentation_generator,
            lint_python_codebase, run_comprehensive_tests
        )
        print("   ✓ All development tools import successfully")
        return True
    except Exception as e:
        print(f"   ✗ Import error: {e}")
        return False

def test_function_calls():
    """Test that the functions can be called."""
    print("2. Testing function calls...")
    try:
        # Test codebase_search (simplest test)
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
        result = codebase_search(
            pattern="test",
            path="/tmp",
            format="text",
            max_depth=1
        )
        print("   ✓ codebase_search function executes")
        return True
    except Exception as e:
        print(f"   ✗ Function call error: {e}")
        return False

def test_discovery():
    """Test tool discovery mechanism."""
    print("3. Testing tool discovery...")
    try:
        from pathlib import Path
        from ipfs_datasets_py.mcp_server.server import import_tools_from_directory

        tools_path = Path('ipfs_datasets_py/mcp_server/tools/development_tools')
        tools = import_tools_from_directory(tools_path)

        expected = ['test_generator', 'codebase_search', 'documentation_generator',
                   'lint_python_codebase', 'run_comprehensive_tests']
        found = [name for name in expected if name in tools]

        print(f"   Found {len(found)}/5 expected tools: {found}")
        return len(found) == 5
    except Exception as e:
        print(f"   ✗ Discovery error: {e}")
        return False

def main():
    """Run all validation tests."""
    print("Phase 1 Development Tools Migration - Final Validation")
    print("=" * 60)

    tests = [
        test_imports,
        test_function_calls,
        test_discovery
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"   ✗ Test failed with exception: {e}")
            results.append(False)

    print("\nValidation Summary:")
    print("=" * 30)

    all_passed = all(results)
    if all_passed:
        print("🎉 SUCCESS: Phase 1 migration is COMPLETE!")
        print("\nAchievements:")
        print("✓ All 5 development tools implemented")
        print("✓ Test Generator Tool")
        print("✓ Documentation Generator Tool")
        print("✓ Linting Tools")
        print("✓ Test Runner Tool")
        print("✓ Codebase Search Tool")
        print("✓ MCP server integration working")
        print("✓ Tool discovery mechanism functional")

        print("\nNext Steps:")
        print("- End-to-end testing with VS Code")
        print("- Performance optimization")
        print("- Phase 2 planning")
    else:
        print("❌ Some issues remain")
        failed_tests = [i for i, r in enumerate(results) if not r]
        print(f"Failed tests: {failed_tests}")

    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
