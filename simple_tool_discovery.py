#!/usr/bin/env python3
"""
Simple tool discovery script.
"""

import sys
import importlib
from pathlib import Path

sys.path.insert(0, '.')

def discover_tools():
    """Discover all MCP tools."""
    tools_base_path = Path("ipfs_datasets_py/mcp_server/tools")
    tool_categories = [
        "audit_tools", "dataset_tools", "web_archive_tools", 
        "cli", "functions", "security_tools", "vector_tools",
        "graph_tools", "provenance_tools", "ipfs_tools"
    ]
    
    discovered_tools = {}
    total_tools = 0
    
    print("=== MCP Tools Discovery ===")
    
    for category in tool_categories:
        try:
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
            module = importlib.import_module(module_path)
            
            # Get all exported functions
            exported_functions = getattr(module, '__all__', [])
            if not exported_functions:
                exported_functions = [
                    name for name in dir(module) 
                    if not name.startswith('_') and callable(getattr(module, name))
                ]
            
            discovered_tools[category] = exported_functions
            total_tools += len(exported_functions)
            print(f"✓ {category}: {len(exported_functions)} tools")
            for tool in exported_functions:
                print(f"  - {tool}")
                
        except Exception as e:
            print(f"✗ {category}: Error - {e}")
            discovered_tools[category] = []
    
    print(f"\nTotal discovered tools: {total_tools}")
    return discovered_tools, total_tools

if __name__ == "__main__":
    tools, count = discover_tools()
