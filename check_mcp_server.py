#!/usr/bin/env python3
"""
MCP Server Component Verification Script

This script verifies the basic components of the MCP server implementation.
"""
import os
import sys
from pathlib import Path
import importlib

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

def check_mcp_server():
    """Check the MCP server implementation components."""
    print("\nIPFS Datasets MCP Server Component Check\n" + "=" * 40)
    
    # Check for MCP server directory
    mcp_server_dir = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server"
    if mcp_server_dir.exists():
        print(f"✓ MCP server directory found: {mcp_server_dir}")
    else:
        print(f"✗ MCP server directory not found: {mcp_server_dir}")
        return False
    
    # List key files
    print("\nKey files:")
    key_files = ["__init__.py", "server.py", "client.py", "configs.py", "logger.py", "simple_server.py"]
    for file in key_files:
        file_path = mcp_server_dir / file
        if file_path.exists():
            print(f"  ✓ {file}")
        else:
            print(f"  ✗ {file} (missing)")
    
    # Check tools directory
    tools_dir = mcp_server_dir / "tools"
    if tools_dir.exists():
        print("\n✓ Tools directory found")
        print("\nTool categories:")
        for item in tools_dir.iterdir():
            if item.is_dir() and not item.name.startswith("__"):
                tool_files = list(item.glob("*.py"))
                tool_count = len([f for f in tool_files if not f.name.startswith("__")])
                print(f"  ✓ {item.name} ({tool_count} tools)")
    else:
        print("\n✗ Tools directory not found")
    
    # Try to import the MCP server module
    print("\nModule import check:")
    try:
        mcp_server_module = importlib.import_module("ipfs_datasets_py.mcp_server")
        print("✓ Successfully imported ipfs_datasets_py.mcp_server")
        
        # Check for important attributes
        check_attrs = ["configs", "IPFSDatasetsMCPServer", "SimpleIPFSDatasetsMCPServer", "start_server"]
        for attr in check_attrs:
            try:
                if hasattr(mcp_server_module, attr):
                    print(f"  ✓ Found {attr}")
                else:
                    print(f"  ✗ Missing {attr}")
            except Exception as e:
                print(f"  ✗ Error checking {attr}: {e}")
    except ImportError as e:
        print(f"✗ Failed to import MCP server module: {e}")
    
    # print("\nDependency check:")
    # try:
    #     import modelcontextprotocol
    #     print("✓ modelcontextprotocol package is installed")
    # except ImportError:
    #     print("✗ modelcontextprotocol package is not installed")
    #     print("  - Using simplified implementation")
    
    # try:
    #     import flask
    #     print("✓ flask package is installed")
    # except ImportError:
    #     print("✗ flask package is not installed (needed for simplified implementation)")
    
    print("\nComponent check complete!")
    return True

if __name__ == "__main__":
    check_mcp_server()
