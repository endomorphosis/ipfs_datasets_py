#!/usr/bin/env python3
"""
Simple MCP Tools Discovery Script

This script discovers all available MCP tools in the ipfs_datasets_py package
and checks which ones have implementation files.
"""

import os
import sys
from pathlib import Path
import json

# Add the project root to the Python path
sys.path.insert(0, '.')

def discover_mcp_tools():
    """Discover all MCP tools and check their implementation status."""
    tools_base_path = Path("ipfs_datasets_py/mcp_server/tools")

    tool_categories = []
    discovered_tools = {}
    tool_count = 0

    print("=== MCP Tools Discovery ===")

    # Find all tool categories (subdirectories)
    if tools_base_path.exists():
        tool_categories = [d.name for d in tools_base_path.iterdir()
                          if d.is_dir() and not d.name.startswith('__')]
    else:
        print(f"Error: Tools directory {tools_base_path} not found")
        return {}

    print(f"Found {len(tool_categories)} tool categories: {', '.join(tool_categories)}")

    # Check each category for tool implementation files
    for category in tool_categories:
        category_path = tools_base_path / category
        tool_files = [f.name for f in category_path.glob("*.py")
                     if f.is_file() and not f.name.startswith('__')]

        tool_names = [os.path.splitext(f)[0] for f in tool_files]
        discovered_tools[category] = tool_names
        tool_count += len(tool_names)

        print(f"- {category}: {len(tool_names)} tools")
        for tool in tool_names:
            print(f"  - {tool}")

    print(f"\nTotal discovered tools: {tool_count}")

    # Save results to a JSON file
    results = {
        'total_tools': tool_count,
        'categories': tool_categories,
        'tools': discovered_tools
    }

    with open('mcp_tools_inventory.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Tool inventory saved to mcp_tools_inventory.json")
    return results

def discover_existing_tests():
    """Check for existing test files."""
    test_dir = Path("test")
    test_files = []

    if test_dir.exists():
        test_files = list(test_dir.glob("**/*test*.py"))
        print(f"\n=== Test Files Discovery ===")
        print(f"Found {len(test_files)} test files:")
        for test_file in test_files:
            print(f"- {test_file}")
    else:
        print(f"\nTest directory {test_dir} not found")

    return test_files

def check_implementation_files(tools_info):
    """Check that each tool has an implementation file."""
    missing_implementations = []

    print("\n=== Implementation Check ===")

    for category, tools in tools_info['tools'].items():
        for tool in tools:
            tool_file = Path(f"ipfs_datasets_py/mcp_server/tools/{category}/{tool}.py")
            if not tool_file.exists():
                missing_implementations.append((category, tool))
                print(f"Missing implementation file: {tool_file}")

    if not missing_implementations:
        print("All tools have implementation files.")
    else:
        print(f"{len(missing_implementations)} tools are missing implementation files.")

    return missing_implementations

def generate_simple_test_summary():
    """Generate a simple summary of available tests."""
    tools_info = discover_mcp_tools()
    test_files = discover_existing_tests()
    missing_implementations = check_implementation_files(tools_info)

    # Generate a report
    report = "# MCP Tools Testing Status\n\n"
    report += f"## Summary\n"
    report += f"- Total tool categories: {len(tools_info['categories'])}\n"
    report += f"- Total tools discovered: {tools_info['total_tools']}\n"
    report += f"- Test files found: {len(test_files)}\n"
    report += f"- Missing implementation files: {len(missing_implementations)}\n\n"

    report += "## Tools by Category\n"
    for category, tools in tools_info['tools'].items():
        report += f"\n### {category}\n"
        for tool in tools:
            report += f"- {tool}\n"

    with open('mcp_tools_test_summary.md', 'w') as f:
        f.write(report)

    print(f"\nTest summary report saved to mcp_tools_test_summary.md")

if __name__ == "__main__":
    generate_simple_test_summary()
