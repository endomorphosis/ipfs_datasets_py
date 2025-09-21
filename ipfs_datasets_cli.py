#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPFS Datasets CLI Tool

A lightweight command line interface that provides convenient access to the MCP tools
with minimal imports. Only loads what's needed when needed.
"""

import sys
import os
import subprocess
from pathlib import Path


def show_help():
    """Show CLI help without importing anything heavy."""
    help_text = """
IPFS Datasets CLI Tool

Usage:
    ipfs-datasets [command] [subcommand] [options]
    ipfs-datasets --help
    ipfs-datasets --version

Commands:
    info         System information
      status     Show system status
      version    Show version information
      
    mcp          MCP server management  
      start      Start MCP server
      stop       Stop MCP server
      status     Show MCP server status
      
    tools        Tool management
      categories List available tool categories
      list       List tools in a category
      execute    Execute a specific tool
      
    dataset      Dataset operations
      load       Load a dataset
      convert    Convert dataset format
      
    ipfs         IPFS operations
      pin        Pin data to IPFS
      get        Get data from IPFS
      
    vector       Vector operations
      create     Create vector embeddings
      search     Search vectors

Options:
    --help, -h   Show this help message
    --version    Show version information
    --json       Output in JSON format
    --verbose    Verbose output

Examples:
    ipfs-datasets info status
    ipfs-datasets mcp start
    ipfs-datasets tools categories
    ipfs-datasets dataset load ./data.json
    
For detailed help on a specific command:
    ipfs-datasets [command] --help
"""
    print(help_text.strip())


def show_version():
    """Show version without importing anything heavy."""
    print("ipfs-datasets CLI v1.0.0")


def show_status():
    """Show basic system status without heavy imports."""
    print("System Status: CLI tool is available")
    print("Version: 1.0.0")
    print("Python:", sys.version.split()[0])
    print("Path:", Path(__file__).parent)


def execute_heavy_command(args):
    """Execute commands that require heavy imports - only import when needed."""
    # Only import heavy modules when actually executing commands
    try:
        import asyncio
        import json
        import importlib
        from typing import Any, Dict, List
        
        # Setup sys path for imports
        current_dir = Path(__file__).parent  
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))
        
        # Heavy command execution logic here
        command = args[0] if args else None
        
        if command == "tools":
            subcommand = args[1] if len(args) > 1 else None
            if subcommand == "categories":
                print("Available tool categories:")
                print("- temporal_deontic_logic")  
                print("- dataset_tools")
                print("- vector_tools")
                print("- ipfs_tools")
                return
        
        if command == "mcp":
            subcommand = args[1] if len(args) > 1 else None
            if subcommand == "start":
                host = "127.0.0.1"
                port = "8899"
                blocking = False
                extra = args[2:]
                i = 0
                while i < len(extra):
                    token = extra[i]
                    if token in ("--host", "-H") and i + 1 < len(extra):
                        host = str(extra[i + 1])
                        i += 2
                    elif token in ("--port", "-p") and i + 1 < len(extra):
                        port = str(extra[i + 1])
                        i += 2
                    elif token in ("--blocking", "-b"):
                        blocking = True
                        i += 1
                    else:
                        i += 1

                env = os.environ.copy()
                env["MCP_DASHBOARD_HOST"] = host
                env["MCP_DASHBOARD_PORT"] = str(port)
                if blocking:
                    env["MCP_DASHBOARD_BLOCKING"] = "1"

                cmd = [sys.executable, "-m", "ipfs_datasets_py.mcp_dashboard"]
                try:
                    if blocking:
                        print(f"Starting MCP dashboard (blocking) at http://{host}:{port}/mcp ...")
                        subprocess.run(cmd, env=env, check=False)
                    else:
                        print(f"Starting MCP dashboard at http://{host}:{port}/mcp (background)...")
                        stdout = subprocess.DEVNULL
                        stderr = subprocess.DEVNULL
                        subprocess.Popen(cmd, env=env, stdout=stdout, stderr=stderr)
                        print("MCP dashboard launched.")
                    return
                except Exception as e:
                    print(f"Failed to start MCP dashboard: {e}")
                    print("Tip: try 'python -m ipfs_datasets_py.mcp_dashboard' for diagnostics")
                    return

            elif subcommand == "status":
                # Lightweight status check via HTTP if requests is available
                host = "127.0.0.1"
                port = "8899"
                extra = args[2:]
                i = 0
                while i < len(extra):
                    token = extra[i]
                    if token in ("--host", "-H") and i + 1 < len(extra):
                        host = str(extra[i + 1])
                        i += 2
                    elif token in ("--port", "-p") and i + 1 < len(extra):
                        port = str(extra[i + 1])
                        i += 2
                    else:
                        i += 1
                try:
                    import requests
                    url = f"http://{host}:{port}/api/mcp/status"
                    r = requests.get(url, timeout=2)
                    if r.ok:
                        print(f"MCP Dashboard status at {url}: {r.status_code}")
                        try:
                            data = r.json()
                            print(json.dumps({
                                "status": data.get("status"),
                                "tools_available": data.get("tools_available")
                            }, indent=2))
                        except Exception:
                            print(r.text[:300])
                    else:
                        print(f"MCP Dashboard not healthy (HTTP {r.status_code}) at {url}")
                except Exception as e:
                    print(f"MCP status check failed: {e}")
                return
        
        print(f"Command '{' '.join(args)}' requires full system - importing modules...")
        
        # For complex operations, import the full original functionality
    # Heavy subsystem imports would go here when needed
        # Continue with heavy operations...
        
    except ImportError as e:
        print(f"Error: Missing dependencies for command '{' '.join(args)}': {e}")
        print("Try: pip install -e . to install all dependencies")
    except Exception as e:
        print(f"Error executing command: {e}")


def main():
    """Main CLI entry point - lightweight by default."""
    args = sys.argv[1:]
    
    # Handle help and version immediately without any imports
    if not args or args[0] in ['-h', '--help', 'help']:
        show_help()
        return
        
    if args[0] in ['--version', 'version']:
        show_version()
        return
    
    # Handle basic info commands without heavy imports
    if args[0] == 'info':
        if len(args) > 1:
            if args[1] in ['status', 'version']:
                show_status()
                return
    
    # For any other command, use heavy import function
    execute_heavy_command(args)


def cli_main():
    """Entry point wrapper for console scripts."""
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()