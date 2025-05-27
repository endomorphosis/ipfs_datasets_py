#!/usr/bin/env python3
"""
Debug helper for individual MCP tools.
Use this script to debug specific MCP tools.
"""
import asyncio
import sys
from typing import Any, Dict

async def debug_tool(tool_category: str, tool_name: str, *args, **kwargs) -> Dict[str, Any]:
    """
    Debug a specific MCP tool.
    
    Args:
        tool_category: Category of the tool (e.g., 'dataset_tools')
        tool_name: Name of the tool (e.g., 'load_dataset')
        *args: Arguments to pass to the tool
        **kwargs: Keyword arguments to pass to the tool
    """
    try:
        # Import the tool
        module_path = f"ipfs_datasets_py.mcp_server.tools.{tool_category}.{tool_name}"
        module = __import__(module_path, fromlist=[tool_name])
        tool_func = getattr(module, tool_name)
        
        print(f"🔧 Debugging tool: {tool_category}.{tool_name}")
        print(f"📥 Input args: {args}")
        print(f"📥 Input kwargs: {kwargs}")
        print("=" * 50)
        
        # Call the tool
        if asyncio.iscoroutinefunction(tool_func):
            result = await tool_func(*args, **kwargs)
        else:
            result = tool_func(*args, **kwargs)
        
        print("📤 Result:")
        print(result)
        print("=" * 50)
        
        return result
        
    except Exception as e:
        print(f"❌ Error debugging tool: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

async def main():
    """Main function for debugging tools."""
    if len(sys.argv) < 3:
        print("Usage: python debug_tool.py <tool_category> <tool_name> [args...]")
        print("Example: python debug_tool.py dataset_tools load_dataset test_dataset")
        print("Example: python debug_tool.py ipfs_tools get_from_ipfs QmTest123")
        return
    
    tool_category = sys.argv[1]
    tool_name = sys.argv[2]
    args = sys.argv[3:] if len(sys.argv) > 3 else []
    
    await debug_tool(tool_category, tool_name, *args)

if __name__ == "__main__":
    asyncio.run(main())
