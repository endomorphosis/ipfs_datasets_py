#!/usr/bin/env python3
"""Test MCP tools API for CI/CD"""
import requests
import json
import sys

def main():
    try:
        response = requests.get("http://127.0.0.1:8899/api/mcp/tools", timeout=30)
        if response.status_code != 200:
            print(f"❌ Tools API returned {response.status_code}")
            sys.exit(1)
        
        tools = response.json()
        print(f"✅ API returned {len(tools)} tools")
        
        tool_items = list(tools.items())[:5] if isinstance(tools, dict) else []
        for tool_name, tool_info in tool_items:
            print(f"🔧 {tool_name}:")
            if isinstance(tool_info, dict):
                print(f"  - Description: {tool_info.get('description', 'N/A')}")
                print(f"  - Category: {tool_info.get('category', 'N/A')}")
                print(f"  - Parameters: {len(tool_info.get('parameters', {}))}")
        
        status_response = requests.get("http://127.0.0.1:8899/api/mcp/status", timeout=10)
        if status_response.status_code == 200:
            status_data = status_response.json()
            print(f"📊 Dashboard status: {status_data.get('status', 'unknown')}")
            print(f"📊 Tools available: {status_data.get('tools_available', 0)}")
    except Exception as e:
        print(f"❌ Error testing tools API: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
