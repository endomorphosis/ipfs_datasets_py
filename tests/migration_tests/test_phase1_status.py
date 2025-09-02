#!/usr/bin/env python3
"""
Phase 1 Status Test - Simple validation
"""

import asyncio
import sys
import traceback
from pathlib import Path

async def async_test_phase1_status():
    """Test Phase 1 completion status"""
    print("Phase 1 Status Check")
    print("=" * 20)

    # Add current directory to Python path
    current_dir = Path(__file__).parent
    sys.path.insert(0, str(current_dir))

    results = {}

    # Test 1: Import development tools
    print("\n1. Testing development tools imports...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools import (
            test_generator,
            codebase_search,
            documentation_generator,
            lint_python_codebase,
            run_comprehensive_tests
        )
        print("✓ All 5 development tools imported successfully")
        results['imports'] = True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        traceback.print_exc()
        results['imports'] = False

    # Test 2: Server tool registration
    print("\n2. Testing server tool registration...")
    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        server = IPFSDatasetsMCPServer()
        await server.register_tools()

        # Check for development tools
        dev_tool_names = [
            'test_generator', 'codebase_search', 'documentation_generator',
            'lint_python_codebase', 'run_comprehensive_tests'
        ]

        registered_dev_tools = []
        for tool_name in dev_tool_names:
            if tool_name in server.tools:
                registered_dev_tools.append(tool_name)

        print(f"✓ {len(registered_dev_tools)}/5 development tools registered")
        for tool in registered_dev_tools:
            print(f"  - {tool}")

        if len(registered_dev_tools) < 5:
            missing = set(dev_tool_names) - set(registered_dev_tools)
            print(f"Missing tools: {missing}")

        results['registration'] = len(registered_dev_tools) == 5
    except Exception as e:
        print(f"✗ Server registration failed: {e}")
        traceback.print_exc()
        results['registration'] = False

    # Test 3: Basic function execution
    print("\n3. Testing basic tool execution...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search

        result = codebase_search(
            pattern="def",
            path=".",
            max_depth=1,
            format="json"
        )

        if result and isinstance(result, dict) and 'success' in result and result['success']:
            print("✓ Codebase search executed successfully")
            results['execution'] = True
        else:
            print(f"✗ Codebase search returned unexpected result: {type(result)} - {result}")
            results['execution'] = False
    except Exception as e:
        print(f"✗ Tool execution failed: {e}")
        traceback.print_exc()
        results['execution'] = False

    # Summary
    print("\n" + "=" * 30)
    print("PHASE 1 STATUS SUMMARY")
    print("=" * 30)

    all_passed = all(results.values())

    for test, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test.capitalize()}: {status}")

    if all_passed:
        print("\n🎉 Phase 1 COMPLETE - All systems operational!")
        print("\n📋 Next Steps:")
        print("   1. VS Code Copilot Chat integration testing")
        print("   2. Performance optimization")
        print("   3. End-to-end validation in production")
        print("   4. Begin Phase 2 planning")
    else:
        print("\n⚠️  Phase 1 has issues that need resolution")

    return all_passed

import pytest

def test_phase1_status_pytest():
    """Pytest wrapper for phase1 status test."""
    success = asyncio.run(async_test_phase1_status())
    assert success, "Phase 1 status test failed"

if __name__ == "__main__":
    try:
        success = asyncio.run(async_test_phase1_status())
        print(f"Test {'PASSED' if success else 'FAILED'}")
    except Exception as e:
        print(f"Test failed with exception: {e}")
        traceback.print_exc()
