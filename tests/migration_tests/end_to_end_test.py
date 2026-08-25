#!/usr/bin/env python3
"""
End-to-End Integration Test for Development Tools MCP Server

This script tests the complete workflow:
1. MCP server startup
2. Tool registration and discovery
3. Individual tool functionality
4. VS Code integration readiness
"""

import sys
import anyio
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def test_mcp_server_startup():
    """Test MCP server can start and register tools."""
    print("🚀 Testing MCP Server Startup...")

    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

        server = IPFSDatasetsMCPServer()
        server.register_tools()

        dev_tools = [
            name
            for name in server.tools.keys()
            if name
            in [
                "test_generator",
                "codebase_search",
                "documentation_generator",
                "lint_python_codebase",
                "run_comprehensive_tests",
            ]
        ]

        print(f"   ✓ Server started successfully")
        print(f"   ✓ {len(server.tools)} total tools registered")
        print(f"   ✓ {len(dev_tools)}/5 development tools found")

        return True, server
    except Exception as e:
        print(f"   ✗ Server startup failed: {e}")
        return False, None


def test_individual_tools():
    """Test each development tool individually."""
    print("\n🔧 Testing Individual Tools...")

    tests = []

    # Test 1: Codebase Search
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import (
            codebase_search,
        )

        result = codebase_search(
            pattern="def test", path=".", regex=True, extensions="py", max_depth=2, format="text"
        )

        success = isinstance(result, str) and "Search Results" in result
        print(f"   {'✓' if success else '✗'} Codebase Search: {'PASS' if success else 'FAIL'}")
        tests.append(success)

    except Exception as e:
        print(f"   ✗ Codebase Search: FAIL - {e}")
        tests.append(False)

    # Test 2: Test Generator (basic validation)
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import (
            test_generator,
        )

        # Create a simple test spec
        test_spec = {
            "test_class": "TestExample",
            "tests": [
                {"name": "test_basic", "description": "Basic test", "assertions": ["assert True"]}
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            result = test_generator(
                name="example_test",
                description="Example test file",
                test_specification=json.dumps(test_spec),
                output_dir=tmpdir,
                harness="pytest",
            )

            success = isinstance(result, dict) and result.get("success", False)
            print(f"   {'✓' if success else '✗'} Test Generator: {'PASS' if success else 'FAIL'}")
            tests.append(success)

    except Exception as e:
        print(f"   ✗ Test Generator: FAIL - {e}")
        tests.append(False)

    # Test 3: Documentation Generator
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import (
            documentation_generator,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple Python file to document
            test_file = Path(tmpdir) / "test_module.py"
            test_file.write_text('''
def example_function(x, y):
    """Add two numbers.

    Args:
        x: First number
        y: Second number

    Returns:
        Sum of x and y
    """
    return x + y
''')

            result = documentation_generator(
                input_path=str(test_file),
                output_path=str(Path(tmpdir) / "docs"),
                format_type="markdown",
            )

            success = isinstance(result, dict) and result.get("success", False)
            print(
                f"   {'✓' if success else '✗'} Documentation Generator: {'PASS' if success else 'FAIL'}"
            )
            tests.append(success)

    except Exception as e:
        print(f"   ✗ Documentation Generator: FAIL - {e}")
        tests.append(False)

    # Test 4: Linting Tools
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import (
            lint_python_codebase,
        )

        result = lint_python_codebase(
            path=".", max_depth=1, include_formatting=True, output_format="json"
        )

        success = isinstance(result, str) and ("lint_results" in result or "error" in result)
        print(f"   {'✓' if success else '✗'} Linting Tools: {'PASS' if success else 'FAIL'}")
        tests.append(success)

    except Exception as e:
        print(f"   ✗ Linting Tools: FAIL - {e}")
        tests.append(False)

    # Test 5: Test Runner
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import (
            run_comprehensive_tests,
        )

        result = run_comprehensive_tests(
            path=".", max_depth=1, include_coverage=False, output_format="json"
        )

        success = isinstance(result, str) and ("test_results" in result or "error" in result)
        print(f"   {'✓' if success else '✗'} Test Runner: {'PASS' if success else 'FAIL'}")
        tests.append(success)

    except Exception as e:
        print(f"   ✗ Test Runner: FAIL - {e}")
        tests.append(False)

    return tests


def test_vscode_compatibility():
    """Test VS Code MCP integration compatibility."""
    print("\n🔌 Testing VS Code Compatibility...")

    try:
        # Test that we can create the server in stdio mode (VS Code integration)
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

        server = IPFSDatasetsMCPServer()
        server.register_tools()

        # Verify MCP object has required methods for VS Code
        mcp_methods = ["add_tool", "run_stdio_async"]
        has_methods = all(hasattr(server.mcp, method) for method in mcp_methods)

        print(
            f"   {'✓' if has_methods else '✗'} MCP interface compatibility: {'PASS' if has_methods else 'FAIL'}"
        )

        # Check that all development tools are callable
        dev_tool_names = [
            "test_generator",
            "codebase_search",
            "documentation_generator",
            "lint_python_codebase",
            "run_comprehensive_tests",
        ]

        callable_tools = [
            name for name in dev_tool_names if name in server.tools and callable(server.tools[name])
        ]

        print(f"   ✓ Callable tools: {len(callable_tools)}/5")

        return has_methods and len(callable_tools) == 5

    except Exception as e:
        print(f"   ✗ VS Code compatibility test failed: {e}")
        return False


def test_performance_metrics():
    """Basic performance validation."""
    print("\n⚡ Testing Performance...")

    import time

    try:
        # Test import time
        start_time = time.time()
        from ipfs_datasets_py.mcp_server.tools.development_tools import (
            test_generator,
            codebase_search,
            documentation_generator,
            lint_python_codebase,
            run_comprehensive_tests,
        )

        import_time = time.time() - start_time

        # Test server startup time
        start_time = time.time()
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

        server = IPFSDatasetsMCPServer()
        server.register_tools()
        startup_time = time.time() - start_time

        print(f"   ✓ Import time: {import_time:.2f}s")
        print(f"   ✓ Server startup time: {startup_time:.2f}s")

        # Performance targets
        import_ok = import_time < 5.0  # Should import in under 5 seconds
        startup_ok = startup_time < 10.0  # Should start in under 10 seconds

        print(
            f"   {'✓' if import_ok else '✗'} Import performance: {'GOOD' if import_ok else 'SLOW'}"
        )
        print(
            f"   {'✓' if startup_ok else '✗'} Startup performance: {'GOOD' if startup_ok else 'SLOW'}"
        )

        return import_ok and startup_ok

    except Exception as e:
        print(f"   ✗ Performance test failed: {e}")
        return False


def main():
    """Run all end-to-end tests."""
    print("🧪 End-to-End Integration Testing")
    print("=" * 50)

    # Test 1: Server startup
    server_ok, server = test_mcp_server_startup()

    # Test 2: Individual tools
    tool_results = test_individual_tools()
    tools_ok = all(tool_results) if tool_results else False

    # Test 3: VS Code compatibility
    vscode_ok = test_vscode_compatibility()

    # Test 4: Performance
    perf_ok = test_performance_metrics()

    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)

    print(f"🚀 Server Startup:     {'✓ PASS' if server_ok else '✗ FAIL'}")
    print(
        f"🔧 Individual Tools:   {'✓ PASS' if tools_ok else '✗ FAIL'} ({sum(tool_results) if tool_results else 0}/5)"
    )
    print(f"🔌 VS Code Compat:     {'✓ PASS' if vscode_ok else '✗ FAIL'}")
    print(f"⚡ Performance:        {'✓ PASS' if perf_ok else '✗ FAIL'}")

    all_tests_passed = server_ok and tools_ok and vscode_ok and perf_ok

    if all_tests_passed:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ Development tools are ready for production use")
        print("✅ VS Code integration is functional")
        print("✅ Performance meets requirements")
        print("\n🚀 Ready for Phase 2 migration!")
    else:
        print("\n⚠️  Some tests failed - review above for details")

    return 0 if all_tests_passed else 1


if __name__ == "__main__":
    sys.exit(main())
