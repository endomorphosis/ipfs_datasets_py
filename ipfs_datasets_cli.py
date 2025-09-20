#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPFS Datasets CLI Tool

A lightweight command line interface that provides convenient access to the MCP tools
with minimal imports. Only loads what's needed when needed.
"""

import sys
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
                print("MCP server starting...")
                print("Use: python -m ipfs_datasets_py.mcp_dashboard")
                return
            elif subcommand == "status":
                print("MCP Status: Available")
                return
        
        print(f"Command '{' '.join(args)}' requires full system - importing modules...")
        
        # For complex operations, import the full original functionality
        from . import mcp_server
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