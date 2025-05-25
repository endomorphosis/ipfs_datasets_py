#!/usr/bin/env python3
"""Minimal MCP server test script."""
import os
import sys
from pathlib import Path

# Print basic info
print(f"Python version: {sys.version}")
print(f"Current directory: {os.getcwd()}")

# Check if the repo exists
repo_path = Path(__file__).resolve().parent
ipfs_datasets_py_path = repo_path / "ipfs_datasets_py"
mcp_server_path = ipfs_datasets_py_path / "mcp_server"
tools_path = mcp_server_path / "tools"

print(f"Repository path: {repo_path}")
print(f"ipfs_datasets_py path exists: {ipfs_datasets_py_path.exists()}")
print(f"MCP server path exists: {mcp_server_path.exists()}")
print(f"Tools path exists: {tools_path.exists()}")

# List directories if they exist
if tools_path.exists():
    print("\nTool categories:")
    for item in tools_path.iterdir():
        if item.is_dir() and not item.name.startswith("__"):
            print(f"  - {item.name}")
