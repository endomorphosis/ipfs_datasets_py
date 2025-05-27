#!/usr/bin/env python3
"""
Simple MCP Tools Status Check
"""

import os
import sys
from pathlib import Path

def main():
    print("=== MCP Tools Status Check ===")
    
    project_root = Path(__file__).resolve().parent
    tools_path = project_root / "ipfs_datasets_py" / "mcp_server" / "tools"
    
    if not tools_path.exists():
        print(f"❌ Tools directory not found: {tools_path}")
        return
    
    print(f"✅ Tools directory found: {tools_path}")
    
    # List all tool categories
    categories = [d.name for d in tools_path.iterdir() if d.is_dir() and not d.name.startswith('__')]
    print(f"\nFound {len(categories)} tool categories:")
    
    total_tools = 0
    for category in sorted(categories):
        category_path = tools_path / category
        tools = [f.stem for f in category_path.glob("*.py") if not f.name.startswith('__')]
        total_tools += len(tools)
        print(f"  {category}: {len(tools)} tools")
        for tool in tools:
            print(f"    - {tool}")
    
    print(f"\nTotal tools found: {total_tools}")
    
    # Quick import test
    print("\n=== Quick Import Test ===")
    sys.path.insert(0, str(project_root))
    
    try:
        from ipfs_datasets_py.mcp_server import server
        print("✅ MCP server module imports successfully")
    except Exception as e:
        print(f"❌ MCP server import failed: {e}")
    
    try:
        from ipfs_datasets_py.mcp_server.configs import Configs
        print("✅ Configs imports successfully")
    except Exception as e:
        print(f"❌ Configs import failed: {e}")
    
    # Test a few tools
    test_tools = [
        ("dataset_tools", "load_dataset"),
        ("ipfs_tools", "get_from_ipfs"),
        ("web_archive_tools", "extract_text_from_warc")
    ]
    
    print("\n=== Sample Tool Import Test ===")
    for category, tool_name in test_tools:
        try:
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
            module = __import__(module_path, fromlist=[tool_name])
            if hasattr(module, tool_name):
                print(f"✅ {category}/{tool_name} - imports and has main function")
            else:
                print(f"⚠️ {category}/{tool_name} - imports but missing main function")
        except Exception as e:
            print(f"❌ {category}/{tool_name} - import failed: {e}")

if __name__ == "__main__":
    main()
