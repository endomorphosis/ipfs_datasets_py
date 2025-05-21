#!/usr/bin/env python3
"""
List MCP server directory structure.
"""
import os
from pathlib import Path

def list_directory(directory, indent=0):
    """List the contents of a directory with indentation."""
    if not os.path.exists(directory):
        print(f"Directory not found: {directory}")
        return
    
    for item in os.listdir(directory):
        path = os.path.join(directory, item)
        if os.path.isdir(path) and not item.startswith("__pycache__"):
            print("  " * indent + f"📁 {item}/")
            list_directory(path, indent + 1)
        elif os.path.isfile(path) and not item.startswith("__") and item.endswith(".py"):
            print("  " * indent + f"📄 {item}")

# MCP server path
mcp_server_path = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server"
print(f"MCP Server Path: {mcp_server_path}")

# List the MCP server directory structure
if os.path.exists(mcp_server_path):
    print("\nMCP Server Structure:")
    list_directory(mcp_server_path)
else:
    print(f"MCP server directory not found at: {mcp_server_path}")

# List tools specifically
tools_path = mcp_server_path / "tools"
if os.path.exists(tools_path):
    print("\nMCP Tools Categories:")
    for item in os.listdir(tools_path):
        category_path = os.path.join(tools_path, item)
        if os.path.isdir(category_path) and not item.startswith("__"):
            tool_files = [f for f in os.listdir(category_path) 
                         if os.path.isfile(os.path.join(category_path, f)) 
                         and f.endswith(".py") 
                         and not f.startswith("__")]
            print(f"📁 {item}/ ({len(tool_files)} tools)")
            for tool in tool_files:
                print(f"  📄 {tool}")
else:
    print(f"MCP tools directory not found at: {tools_path}")
