#!/usr/bin/env python3
"""
Minimal test to validate the migration integration.
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

async def test_basic_imports():
    """Test that we can import the basic modules."""
    print("🔍 Testing basic imports...")
    
    try:
        # Test auth tools import
        from ipfs_datasets_py.mcp_server.tools.auth_tools import authenticate_user
        print("✅ Auth tools imported successfully")
    except ImportError as e:
        print(f"❌ Auth tools import failed: {e}")
    
    try:
        # Test session tools import  
        from ipfs_datasets_py.mcp_server.tools.session_tools import create_session
        print("✅ Session tools imported successfully")
    except ImportError as e:
        print(f"❌ Session tools import failed: {e}")
    
    try:
        # Test background task tools import
        from ipfs_datasets_py.mcp_server.tools.background_task_tools import check_task_status
        print("✅ Background task tools imported successfully")
    except ImportError as e:
        print(f"❌ Background task tools import failed: {e}")
    
    try:
        # Test tool wrapper
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import wrap_function_as_tool
        print("✅ Tool wrapper imported successfully")
    except ImportError as e:
        print(f"❌ Tool wrapper import failed: {e}")
    
    try:
        # Test tool registration
        from ipfs_datasets_py.mcp_server.tools.tool_registration import register_all_migrated_tools
        print("✅ Tool registration imported successfully")
    except ImportError as e:
        print(f"❌ Tool registration import failed: {e}")

async def test_tool_registration():
    """Test tool registration system."""
    print("\n🔧 Testing tool registration...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry, register_all_migrated_tools
        
        registry = MCPToolRegistry()
        
        # Test registration
        success_count = await register_all_migrated_tools(registry)
        print(f"✅ Registered {success_count} tools successfully")
        
        # List registered tools
        tools = registry.list_tools()
        print(f"📋 Total tools in registry: {len(tools)}")
        
        for tool_name in sorted(tools.keys())[:10]:  # Show first 10
            print(f"  - {tool_name}")
        
        if len(tools) > 10:
            print(f"  ... and {len(tools) - 10} more")
            
    except Exception as e:
        print(f"❌ Tool registration test failed: {e}")

async def test_tool_execution():
    """Test executing a simple tool."""
    print("\n⚙️ Testing tool execution...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.auth_tools import authenticate_user
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import wrap_function_as_tool
        
        # Wrap the function as a tool
        auth_tool = wrap_function_as_tool(authenticate_user)
        
        # Test execution
        test_params = {
            "username": "test_user",
            "password": "test_password"
        }
        
        result = await auth_tool.execute(test_params)
        print(f"✅ Tool execution successful: {result.get('success', False)}")
        
    except Exception as e:
        print(f"❌ Tool execution test failed: {e}")

async def main():
    """Main test function."""
    print("🚀 Starting migration integration tests...\n")
    
    await test_basic_imports()
    await test_tool_registration()
    await test_tool_execution()
    
    print("\n✨ Tests completed!")

if __name__ == "__main__":
    asyncio.run(main())
