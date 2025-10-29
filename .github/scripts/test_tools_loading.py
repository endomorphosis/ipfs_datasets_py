#!/usr/bin/env python3
"""Test MCP tools loading for CI/CD"""
import sys
import traceback

def main():
    try:
        from ipfs_datasets_py.mcp_server.tools import get_all_tools
        tools = get_all_tools()
        print(f"✅ Successfully loaded {len(tools)} MCP tools")
        
        categories = {}
        for tool_name, tool_info in tools.items():
            category = tool_info.get("category", "uncategorized")
            if category not in categories:
                categories[category] = []
            categories[category].append(tool_name)
        
        print("📊 Tools by category:")
        for category, tool_list in categories.items():
            print(f"  {category}: {len(tool_list)} tools")
        
        sample_tools = list(tools.keys())[:5]
        print(f"🔍 Sample tools: {sample_tools}")
    except Exception as e:
        print(f"❌ Error loading MCP tools: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
