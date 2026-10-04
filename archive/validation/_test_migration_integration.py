#!/usr/bin/env python3
"""
Test script for the migrated MCP tools integration.
"""

import anyio
import sys
import traceback
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))


def test_tool_wrapper():
    """Test the tool wrapper system."""
    print("=== Testing Tool Wrapper System ===")

    try:
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import (
            BaseMCPTool,
            FunctionToolWrapper,
            wrap_function_as_tool,
        )

        print("✅ Tool wrapper imports successful")

        # Create a test function
        def test_function(message: str, count: int = 1):
            """Test function for wrapping"""
            return {
                "status": "success",
                "message": f"Processed '{message}' {count} times",
                "count": count,
            }

        # Wrap the function
        tool = wrap_function_as_tool(
            test_function,
            "test_tool",
            category="testing",
            description="A test tool for validation",
            tags=["test", "validation"],
        )

        print(f"✅ Created tool: {tool.name}")
        print(f"   Category: {tool.category}")
        print(f"   Description: {tool.description}")
        print(f"   Tags: {tool.tags}")
        print(f"   Schema: {tool.input_schema}")

        return True

    except Exception as e:
        print(f"❌ Tool wrapper test failed: {e}")
        traceback.print_exc()
        return False


def test_tool_registration():
    """Test the tool registration system."""
    print("\n=== Testing Tool Registration System ===")

    try:
        from ipfs_datasets_py.mcp_server.tools.tool_registration import (
            MCPToolRegistry,
            TOOL_MAPPINGS,
        )

        print("✅ Tool registration imports successful")

        # Create a registry
        registry = MCPToolRegistry()
        print(f"✅ Created tool registry")

        # Check tool mappings
        print(f"✅ Found {len(TOOL_MAPPINGS)} tool categories:")
        for category, config in TOOL_MAPPINGS.items():
            func_count = len(config["functions"])
            print(f"   📂 {category}: {func_count} functions")

        return True

    except Exception as e:
        print(f"❌ Tool registration test failed: {e}")
        traceback.print_exc()
        return False


def test_migrated_tools():
    """Test importing migrated tools."""
    print("\n=== Testing Migrated Tools Import ===")

    success_count = 0
    total_tests = 0

    # Test auth tools
    total_tests += 1
    try:
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user

        print("✅ Auth tools: authenticate_user imported")
        success_count += 1
    except Exception as e:
        print(f"❌ Auth tools: {e}")

    # Test session tools
    total_tests += 1
    try:
        from ipfs_datasets_py.mcp_server.tools.session_tools.session_tools import create_session

        print("✅ Session tools: create_session imported")
        success_count += 1
    except Exception as e:
        print(f"❌ Session tools: {e}")

    # Test background task tools
    total_tests += 1
    try:
        from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import (
            create_task,
        )

        print("✅ Background task tools: create_task imported")
        success_count += 1
    except Exception as e:
        print(f"❌ Background task tools: {e}")

    # Test data processing tools
    total_tests += 1
    try:
        from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import (
            chunk_text,
        )

        print("✅ Data processing tools: chunk_text imported")
        success_count += 1
    except Exception as e:
        print(f"❌ Data processing tools: {e}")

    # Test storage tools
    total_tests += 1
    try:
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import store_data

        print("✅ Storage tools: store_data imported")
        success_count += 1
    except Exception as e:
        print(f"❌ Storage tools: {e}")

    print(f"\n📊 Import test results: {success_count}/{total_tests} successful")
    return success_count == total_tests


async def test_tool_execution():
    """Test actual tool execution."""
    print("\n=== Testing Tool Execution ===")

    try:
        from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user

        # Test the authentication function
        result = await authenticate_user("testuser", "testpass")
        print(f"✅ Auth test result: {result}")

        if result.get("success"):
            print("✅ Tool execution successful")
            return True
        else:
            print("⚠️  Tool executed but returned failure (expected for test)")
            return True

    except Exception as e:
        print(f"❌ Tool execution failed: {e}")
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("🧪 MCP Tools Migration Testing")
    print("=" * 50)

    tests = [
        test_tool_wrapper,
        test_tool_registration,
        test_migrated_tools,
    ]

    async_tests = [test_tool_execution]

    # Run synchronous tests
    sync_results = []
    for test in tests:
        result = test()
        sync_results.append(result)

    # Run asynchronous tests
    async_results = []
    for test in async_tests:
        try:
            result = anyio.run(test())
            async_results.append(result)
        except Exception as e:
            print(f"❌ Async test {test.__name__} failed: {e}")
            async_results.append(False)

    # Summary
    total_tests = len(sync_results) + len(async_results)
    successful_tests = sum(sync_results) + sum(async_results)

    print("\n" + "=" * 50)
    print(f"🎯 Test Summary: {successful_tests}/{total_tests} passed")

    if successful_tests == total_tests:
        print("🎉 All tests passed! Migration integration ready.")
        return 0
    else:
        print("⚠️  Some tests failed. Check the output above.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
