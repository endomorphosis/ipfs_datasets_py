#!/usr/bin/env python3
"""
Simple test to check which MCP tools exist in the codebase.
"""
import os
import sys
from pathlib import Path

# Define the MCP server tools directory
project_root = Path("/home/barberb/ipfs_datasets_py")
mcp_tools_dir = project_root / "ipfs_datasets_py" / "mcp_server" / "tools"

def check_tool_existence():
    """Check which MCP tools exist on disk."""
    print("\nChecking MCP Tools Existence")
    print("=" * 50)

    # Check if the tools directory exists
    if not mcp_tools_dir.exists():
        print(f"Error: MCP tools directory not found: {mcp_tools_dir}")
        return

    print(f"Found MCP tools directory: {mcp_tools_dir}")

    # List all categories (subdirectories)
    categories = []
    for item in mcp_tools_dir.iterdir():
        if item.is_dir() and not item.name.startswith("__"):
            categories.append(item.name)

    categories.sort()
    print(f"\nFound {len(categories)} tool categories: {', '.join(categories)}")

    # Check each category
    all_tools = []
    category_tools = {}

    for category in categories:
        category_dir = mcp_tools_dir / category
        tools = []

        for item in category_dir.iterdir():
            if item.is_file() and item.name.endswith(".py") and not item.name.startswith("__"):
                tools.append(item.name)
                all_tools.append(f"{category}/{item.name}")

        tools.sort()
        category_tools[category] = tools
        print(f"\n{category}: {len(tools)} tools")
        for tool in tools:
            print(f"  - {tool}")

    print(f"\nTotal: {len(all_tools)} tools across {len(categories)} categories")

    # Check web_archive_tools specifically
    if "web_archive_tools" in categories:
        print("\nChecking web_archive_tools in detail:")
        for tool_file in category_tools.get("web_archive_tools", []):
            tool_path = mcp_tools_dir / "web_archive_tools" / tool_file
            print(f"\n{tool_file}")

            # Check file size
            size = tool_path.stat().st_size
            print(f"  Size: {size} bytes")

            # Check file content
            try:
                with open(tool_path, "r") as f:
                    content = f.read()
                    print(f"  Lines: {len(content.splitlines())}")
                    print(f"  First few lines: {content.splitlines()[:3]}")
            except Exception as e:
                print(f"  Error reading file: {e}")

if __name__ == "__main__":
    check_tool_existence()
