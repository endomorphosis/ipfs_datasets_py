#!/usr/bin/env python3
"""
Check for available MCP tools in the ipfs_datasets_py library.

This script enumerates all the available tools in the MCP server and
creates a mapping from library features to MCP tools.
"""
import os
import sys
import json
from pathlib import Path

print("Script started")

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
print(f"Project root: {PROJECT_ROOT}")
IPFS_DATASETS_PATH = PROJECT_ROOT / "ipfs_datasets_py"
print(f"IPFS datasets path: {IPFS_DATASETS_PATH}")
MCP_SERVER_PATH = IPFS_DATASETS_PATH / "mcp_server"
print(f"MCP server path: {MCP_SERVER_PATH}")
TOOLS_PATH = MCP_SERVER_PATH / "tools"
print(f"Tools path: {TOOLS_PATH}")
print(f"Tools path exists: {TOOLS_PATH.exists()}")

def check_mcp_tools():
    """Check for available MCP tools and create a mapping."""
    print("\nChecking MCP Tools\n" + "=" * 40)

    if not TOOLS_PATH.exists():
        print(f"MCP tools directory not found at: {TOOLS_PATH}")
        return False

    # Build tool mapping
    tool_mapping = {}
    tool_categories = []
    total_tools = 0

    # Get all tool categories
    for item in TOOLS_PATH.iterdir():
        if item.is_dir() and not item.name.startswith("__"):
            category_name = item.name
            tool_categories.append(category_name)

            # Get tools in this category
            category_tools = []
            for tool_file in item.glob("*.py"):
                if tool_file.name != "__init__.py":
                    tool_name = tool_file.stem
                    category_tools.append(tool_name)
                    total_tools += 1

            tool_mapping[category_name] = category_tools

    # Print results
    print(f"Found {len(tool_categories)} tool categories with {total_tools} total tools:\n")

    for category, tools in tool_mapping.items():
        print(f"{category} ({len(tools)} tools):")
        for tool in tools:
            tool_path = TOOLS_PATH / category / f"{tool}.py"
            tool_exists = "✓" if tool_path.exists() else "✗"
            print(f"  {tool_exists} {tool}")

    # Create mapping from library features to MCP tools
    print("\nMapping Library Features to MCP Tools\n" + "=" * 40)

    # Define expected mappings from library files to MCP tools
    feature_mappings = {
        "ipfs_datasets.py": ["dataset_tools"],
        "web_archive_utils.py": ["web_archive_tools"],
        "ipfs_knn_index.py": ["vector_tools"],
        "data_provenance.py": ["provenance_tools"],
        "security.py": ["security_tools"],
        "knowledge_graph_extraction.py": ["graph_tools"]
    }

    # Check each mapping
    for lib_file, expected_categories in feature_mappings.items():
        lib_path = IPFS_DATASETS_PATH / lib_file
        lib_exists = "✓" if lib_path.exists() else "✗"

        print(f"\n{lib_exists} Library: {lib_file}")
        for category in expected_categories:
            if category in tool_mapping:
                category_exists = "✓"
                tools = tool_mapping[category]
                print(f"  {category_exists} Exposed via: {category} ({len(tools)} tools)")
                for tool in tools:
                    print(f"    - {tool}")
            else:
                category_exists = "✗"
                print(f"  {category_exists} Missing MCP tools: {category}")

    # Save mapping to file
    mapping_file = PROJECT_ROOT / "mcp_tools_mapping.json"
    with open(mapping_file, "w") as f:
        json.dump({
            "tool_categories": tool_categories,
            "total_tools": total_tools,
            "tools_by_category": tool_mapping,
            "library_to_tool_mapping": feature_mappings
        }, f, indent=2)

    print(f"\nMapping saved to: {mapping_file}")
    return True

if __name__ == "__main__":
    check_mcp_tools()
