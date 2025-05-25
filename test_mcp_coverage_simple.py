#!/usr/bin/env python3
"""
Simple MCP Server Structure Check

This script checks the MCP server structure and lists all available tools
without trying to import modules, which might be causing issues.
"""
import os
import sys
import json
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
LIB_ROOT = PROJECT_ROOT / "ipfs_datasets_py"
MCP_SERVER_PATH = LIB_ROOT / "mcp_server"
MCP_TOOLS_PATH = MCP_SERVER_PATH / "tools"

def check_tool_coverage():
    """Check the MCP server implementation for tool coverage."""
    print("\nIPFS Datasets MCP Tool Coverage Check\n" + "=" * 60)
    
    # Check if MCP server directory exists
    if not MCP_SERVER_PATH.exists():
        print(f"✗ MCP server directory not found: {MCP_SERVER_PATH}")
        return False
    
    print(f"✓ Found MCP server directory: {MCP_SERVER_PATH}")
    
    # Check if tools directory exists
    if not MCP_TOOLS_PATH.exists():
        print(f"✗ Tools directory not found: {MCP_TOOLS_PATH}")
        return False
    
    print(f"✓ Found tools directory: {MCP_TOOLS_PATH}")
    
    # Get all tool categories
    tool_categories = []
    for item in MCP_TOOLS_PATH.iterdir():
        if item.is_dir() and not item.name.startswith("__"):
            tool_categories.append(item.name)
    
    if not tool_categories:
        print("✗ No tool categories found")
        return False
    
    print(f"\nFound {len(tool_categories)} tool categories:")
    
    # Get tools in each category
    tool_coverage = {}
    for category in tool_categories:
        category_path = MCP_TOOLS_PATH / category
        tool_files = [
            f.stem 
            for f in category_path.glob("*.py") 
            if f.is_file() and not f.name.startswith("__")
        ]
        
        tool_coverage[category] = tool_files
        print(f"  - {category}: {len(tool_files)} tools")
        
        # List up to 5 example tools
        examples = tool_files[:5]
        if examples:
            print(f"    Examples: {', '.join(examples)}")
    
    # Check for expected library features
    expected_features = {
        "dataset operations": "dataset_tools",
        "IPFS operations": "ipfs_tools",
        "vector search": "vector_tools",
        "knowledge graph": "graph_tools",
        "data provenance": "provenance_tools",
        "security": "security_tools",
        "audit logging": "audit_tools",
        "web archive": "web_archive_tools"
    }
    
    print("\nChecking for expected feature coverage:")
    
    missing_features = []
    for feature_name, expected_category in expected_features.items():
        if expected_category in tool_categories:
            print(f"  ✓ {feature_name} (via {expected_category})")
        else:
            missing_features.append(feature_name)
            print(f"  ✗ {feature_name} (missing {expected_category})")
    
    # Save results to a file
    results = {
        "tool_categories": tool_categories,
        "tools_by_category": tool_coverage,
        "missing_features": missing_features
    }
    
    with open("mcp_tool_coverage_simple.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to: mcp_tool_coverage_simple.json")
    
    return len(missing_features) == 0

if __name__ == "__main__":
    success = check_tool_coverage()
    sys.exit(0 if success else 1)
