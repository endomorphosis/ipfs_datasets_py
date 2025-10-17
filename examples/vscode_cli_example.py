#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSCode CLI Example Usage

This script demonstrates various ways to use the VSCode CLI integration.
"""

import json
import sys
import os
import tempfile
from pathlib import Path

# Add the parent directory to the path so we can import the module
sys.path.insert(0, str(Path(__file__).parent.parent))


def example_status():
    """Example: Check VSCode CLI status"""
    print("\n=== Example: Check Status ===")
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    
    cli = VSCodeCLI()
    status = cli.get_status()
    
    print(f"Installed: {status['installed']}")
    print(f"Version: {status['version'] or 'N/A'}")
    print(f"Install Directory: {status['install_dir']}")
    print(f"Platform: {status['platform']}")
    print(f"Architecture: {status['architecture']}")


def example_custom_install_dir():
    """Example: Use custom installation directory"""
    print("\n=== Example: Custom Install Directory ===")
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = VSCodeCLI(install_dir=tmpdir)
        status = cli.get_status()
        
        print(f"Custom install directory: {status['install_dir']}")
        print(f"Installed: {status['installed']}")


def example_get_download_url():
    """Example: Get download URL"""
    print("\n=== Example: Get Download URL ===")
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    
    cli = VSCodeCLI()
    url = cli.get_download_url()
    
    print(f"Download URL: {url}")


def example_mcp_tool():
    """Example: Use MCP tool"""
    print("\n=== Example: MCP Tool ===")
    from ipfs_datasets_py.mcp_tools.tools.vscode_cli_tools import VSCodeCLIStatusTool
    import asyncio
    
    async def run():
        tool = VSCodeCLIStatusTool()
        result = await tool.execute({})
        print(f"Tool name: {tool.name}")
        print(f"Result: {json.dumps(result, indent=2)}")
    
    asyncio.run(run())


def example_mcp_server_function():
    """Example: Use MCP server function"""
    print("\n=== Example: MCP Server Function ===")
    
    # Import the function directly from the module file
    import importlib.util
    
    spec = importlib.util.spec_from_file_location(
        'vscode_cli_tools',
        str(Path(__file__).parent.parent / 'ipfs_datasets_py' / 'mcp_server' / 'tools' / 'development_tools' / 'vscode_cli_tools.py')
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    result = module.vscode_cli_status()
    print(f"Result: {json.dumps(result, indent=2)}")


def main():
    """Run all examples"""
    print("VSCode CLI Integration Examples")
    print("=" * 50)
    
    try:
        example_status()
    except Exception as e:
        print(f"Error: {e}")
    
    try:
        example_custom_install_dir()
    except Exception as e:
        print(f"Error: {e}")
    
    try:
        example_get_download_url()
    except Exception as e:
        print(f"Error: {e}")
    
    try:
        example_mcp_tool()
    except Exception as e:
        print(f"Error: {e}")
    
    try:
        example_mcp_server_function()
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n" + "=" * 50)
    print("Examples completed!")


if __name__ == '__main__':
    main()
