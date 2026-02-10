#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSCode CLI Example Usage

This script demonstrates various ways to use the VSCode CLI integration.
Run this from the repository root or install the package first.
"""

import json
import sys
import os
import tempfile
from pathlib import Path

# Try to import the package normally first
try:
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    from ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.vscode_cli_tools import VSCodeCLIStatusTool
    PACKAGE_AVAILABLE = True
except ImportError:
    # If not installed, add parent directory to path
    repo_root = Path(__file__).parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
        from ipfs_datasets_py.mcp_server.tools.legacy_mcp_tools.vscode_cli_tools import VSCodeCLIStatusTool
        PACKAGE_AVAILABLE = True
    except ImportError:
        PACKAGE_AVAILABLE = False
        print("Error: Could not import ipfs_datasets_py. Please install the package or run from repository root.")


def example_status():
    """Example: Check VSCode CLI status"""
    if not PACKAGE_AVAILABLE:
        print("Skipping: Package not available")
        return
        
    print("\n=== Example: Check Status ===")
    
    cli = VSCodeCLI()
    status = cli.get_status()
    
    print(f"Installed: {status['installed']}")
    print(f"Version: {status['version'] or 'N/A'}")
    print(f"Install Directory: {status['install_dir']}")
    print(f"Platform: {status['platform']}")
    print(f"Architecture: {status['architecture']}")


def example_custom_install_dir():
    """Example: Use custom installation directory"""
    if not PACKAGE_AVAILABLE:
        print("Skipping: Package not available")
        return
        
    print("\n=== Example: Custom Install Directory ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = VSCodeCLI(install_dir=tmpdir)
        status = cli.get_status()
        
        print(f"Custom install directory: {status['install_dir']}")
        print(f"Installed: {status['installed']}")


def example_get_download_url():
    """Example: Get download URL"""
    if not PACKAGE_AVAILABLE:
        print("Skipping: Package not available")
        return
        
    print("\n=== Example: Get Download URL ===")
    
    cli = VSCodeCLI()
    url = cli.get_download_url()
    
    print(f"Download URL: {url}")


def example_mcp_tool():
    """Example: Use MCP tool"""
    if not PACKAGE_AVAILABLE:
        print("Skipping: Package not available")
        return
        
    print("\n=== Example: MCP Tool ===")
    import anyio
    
    async def run():
        tool = VSCodeCLIStatusTool()
        result = await tool.execute({})
        print(f"Tool name: {tool.name}")
        print(f"Result: {json.dumps(result, indent=2)}")
    
    anyio.run(run())


def main():
    """Run all examples"""
    print("VSCode CLI Integration Examples")
    print("=" * 50)
    
    if not PACKAGE_AVAILABLE:
        print("\nError: Package not available. Install with 'pip install -e .' or run from repository root.")
        return 1
    
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
    
    print("\n" + "=" * 50)
    print("Examples completed!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
