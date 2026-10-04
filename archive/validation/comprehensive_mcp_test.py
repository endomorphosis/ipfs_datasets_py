# #!/usr/bin/env python3
# """
# Comprehensive test for migration integration using virtual environment.
# """

# import sys
# import anyio
# import os
# from pathlib import Path

# # Ensure we use the virtual environment
# venv_path = Path(__file__).parent / ".venv" / "bin" / "python"
# if venv_path.exists():
#     print(f"🐍 Using virtual environment: {venv_path}")
# else:
#     print("⚠️  Virtual environment not found, using system Python")

# # Add project root to path
# project_root = Path(__file__).parent
# sys.path.insert(0, str(project_root))

# async def test_auth_tools():
#     """Test authentication tools."""
#     print("🔐 Testing auth tools...")

#     try:
#         from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user, validate_token, get_user_info

#         # Test authenticate_user
#         result = await authenticate_user("test_user", "test_password")
#         print(f"  ✅ authenticate_user: {result.get('success', False)}")

#         # Test validate_token
#         result = await validate_token("test_token")
#         print(f"  ✅ validate_token: {result.get('valid', False)}")

#         # Test get_user_info
#         result = await get_user_info("test_user")
#         print(f"  ✅ get_user_info: {result.get('success', False)}")

#         return True
#     except Exception as e:
#         print(f"  ❌ Auth tools failed: {e}")
#         return False

# async def test_session_tools():
#     """Test session management tools."""
#     print("📝 Testing session tools...")

#     try:
#         from ipfs_datasets_py.mcp_server.tools.session_tools.session_tools import create_session, manage_session_state, cleanup_session

#         # Test create_session
#         result = await create_session("test_user", {"timeout": 3600})
#         print(f"  ✅ create_session: {result.get('success', False)}")

#         # Test manage_session_state
#         result = await manage_session_state("test_session_id", "active")
#         print(f"  ✅ manage_session_state: {result.get('success', False)}")

#         # Test cleanup_session
#         result = await cleanup_session("test_session_id")
#         print(f"  ✅ cleanup_session: {result.get('success', False)}")

#         return True
#     except Exception as e:
#         print(f"  ❌ Session tools failed: {e}")
#         return False

# async def test_background_task_tools():
#     """Test background task tools."""
#     print("⚙️ Testing background task tools...")

#     try:
#         from ipfs_datasets_py.mcp_server.tools.background_task_tools.background_task_tools import check_task_status, manage_background_tasks, manage_task_queue

#         # Test check_task_status
#         result = await check_task_status("test_task_id")
#         print(f"  ✅ check_task_status: {result.get('status') == 'success'}")

#         # Test manage_background_tasks
#         result = await manage_background_tasks("cancel", "test_task_id")
#         print(f"  ✅ manage_background_tasks: {result.get('status') == 'success'}")

#         # Test manage_task_queue
#         result = await manage_task_queue("get_stats")
#         print(f"  ✅ manage_task_queue: {result.get('status') == 'success'}")

#         return True
#     except Exception as e:
#         print(f"  ❌ Background task tools failed: {e}")
#         return False

# async def test_tool_wrapper():
#     """Test tool wrapper system."""
#     print("🔧 Testing tool wrapper...")

#     try:
#         from ipfs_datasets_py.mcp_server.tools.tool_wrapper import wrap_function_as_tool, FunctionToolWrapper
#         from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import authenticate_user

#         # Test wrapping a function
#         wrapped_tool = wrap_function_as_tool(authenticate_user)
#         print(f"  ✅ Function wrapped: {wrapped_tool.name}")

#         # Test execution
#         result = await wrapped_tool.execute({
#             "username": "test_user",
#             "password": "test_password"
#         })
#         print(f"  ✅ Tool execution: {result.get('success', False)}")

#         return True
#     except Exception as e:
#         print(f"  ❌ Tool wrapper failed: {e}")
#         return False

# async def test_tool_registration():
#     """Test tool registration system."""
#     print("📋 Testing tool registration...")

#     try:
#         from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry, register_all_migrated_tools

#         # Create registry
#         registry = MCPToolRegistry()
#         print(f"  ✅ Registry created")

#         # Register tools
#         success_count = await register_all_migrated_tools(registry)
#         print(f"  ✅ Registered {success_count} tools")

#         # List tools
#         tools = registry.list_tools()
#         print(f"  ✅ Total tools: {len(tools)}")

#         # Show sample tools
#         for i, tool_name in enumerate(sorted(tools.keys())):
#             if i < 5:  # Show first 5
#                 print(f"    - {tool_name}")

#         if len(tools) > 5:
#             print(f"    ... and {len(tools) - 5} more")

#         return True
#     except Exception as e:
#         print(f"  ❌ Tool registration failed: {e}")
#         return False

# async def test_fastapi_integration():
#     """Test FastAPI integration."""
#     print("🌐 Testing FastAPI integration...")

#     try:
#         from ipfs_datasets_py.mcp_server.tools.fastapi_integration import MCPToolsAPI

#         # Create API instance
#         api = MCPToolsAPI()
#         print(f"  ✅ API instance created")

#         # Test health endpoint
#         health = api.health()
#         print(f"  ✅ Health check: {health.get('status') == 'healthy'}")

#         return True
#     except Exception as e:
#         print(f"  ❌ FastAPI integration failed: {e}")
#         return False

# async def test_data_processing_tools():
#     """Test data processing tools."""
#     print("📊 Testing data processing tools...")

#     try:
#         from ipfs_datasets_py.mcp_server.tools.data_processing_tools.data_processing_tools import chunk_text, transform_data, convert_format, validate_data

#         # Test chunk_text
#         result = await chunk_text("This is a test text for chunking.", 10)
#         print(f"  ✅ chunk_text: {result.get('success', False)}")

#         # Test transform_data
#         result = await transform_data([{"test": "data"}], "normalize")
#         print(f"  ✅ transform_data: {result.get('success', False)}")

#         return True
#     except Exception as e:
#         print(f"  ❌ Data processing tools failed: {e}")
#         return False

# async def test_storage_tools():
#     """Test storage tools."""
#     print("💾 Testing storage tools...")

#     try:
#         from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import store_data, manage_collections, retrieve_data, query_storage

#         # Test store_data
#         result = await store_data({"test": "data"}, "ipfs", compression="none")
#         print(f"  ✅ store_data: {result.get('success', False)}")

#         # Test manage_collections
#         result = await manage_collections("list", "test_collection")
#         print(f"  ✅ manage_collections: {result.get('success', False)}")

#         return True
#     except Exception as e:
#         print(f"  ❌ Storage tools failed: {e}")
#         return False

# async def main():
#     """Main test function."""
#     print("🚀 Starting comprehensive migration integration tests...\n")

#     test_results = []

#     # Run all tests
#     tests = [
#         ("Auth Tools", test_auth_tools),
#         ("Session Tools", test_session_tools),
#         ("Background Task Tools", test_background_task_tools),
#         ("Tool Wrapper", test_tool_wrapper),
#         ("Tool Registration", test_tool_registration),
#         ("FastAPI Integration", test_fastapi_integration),
#         ("Data Processing Tools", test_data_processing_tools),
#         ("Storage Tools", test_storage_tools),
#     ]

#     for test_name, test_func in tests:
#         try:
#             result = await test_func()
#             test_results.append((test_name, result))
#         except Exception as e:
#             print(f"  💥 {test_name} crashed: {e}")
#             test_results.append((test_name, False))
#         print()  # Add spacing

#     # Summary
#     print("📊 Test Results Summary:")
#     print("=" * 50)

#     passed = sum(1 for _, result in test_results if result)
#     total = len(test_results)

#     for test_name, result in test_results:
#         status = "✅ PASSED" if result else "❌ FAILED"
#         print(f"  {status}: {test_name}")

#     print(f"\n🎯 Overall: {passed}/{total} tests passed ({passed/total*100:.1f}%)")

#     if passed == total:
#         print("🎉 All tests passed! Migration integration is successful!")
#     else:
#         print("⚠️  Some tests failed. Please check the errors above.")

#     return passed == total

# if __name__ == "__main__":
#     anyio.run(main())
