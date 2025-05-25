#!/usr/bin/env python3
"""
Minimal test for the MCP server component of IPFS Datasets.

This test checks if we can import the necessary modules and classes
without actually starting the server.
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Display environment information
print(f"Python version: {sys.version}")
print(f"Python executable: {sys.executable}")
print(f"Current working directory: {os.getcwd()}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}")

# Test importing the project modules
print("\nImporting project modules:")
try:
    import ipfs_datasets_py
    print(f"✓ ipfs_datasets_py imported")
except ImportError as e:
    print(f"✗ Error importing ipfs_datasets_py: {e}")

# Test if the project has MCP components
print("\nChecking for MCP server components:")
# try:
#     from ipfs_datasets_py.ipfs_kit import IPFSKit
#     print(f"✓ IPFSKit imported")
# except ImportError as e:
#     print(f"✗ Error importing IPFSKit: {e}")

try:
    # The following lines assume we don't need modelcontextprotocol
    # directly and just need the components from ipfs_datasets_py
    from ipfs_datasets_py.mcp_server.configs import Configs
    print(f"✓ MCP server configs imported")
except ImportError as e:
    print(f"✗ Error importing MCP server configs: {e}")

# try:
#     from ipfs_datasets_py.mcp_server.utils import tool_utils
#     print(f"✓ MCP server tool utils imported")
# except ImportError as e:
#     print(f"✗ Error importing MCP server tool utils: {e}")

# Check available tools in the MCP server
print("\nChecking MCP server tools:")
try:
    tools_dir = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server" / "tools"
    if tools_dir.exists():
        tools_categories = [d.name for d in tools_dir.iterdir() if d.is_dir() and not d.name.startswith("__")]
        print(f"Found tool categories: {tools_categories}")
        
        for category in tools_categories:
            category_dir = tools_dir / category
            tools = [f.stem for f in category_dir.iterdir() if f.is_file() and f.name.endswith('.py') and not f.name.startswith('__')]
            print(f"  {category}: {', '.join(tools)}")
    else:
        print("MCP server tools directory not found")
except Exception as e:
    print(f"Error listing MCP server tools: {e}")

print("\nTest completed.")
