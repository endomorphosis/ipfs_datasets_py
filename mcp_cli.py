#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP CLI Tool for IPFS Datasets Python

A command line interface that provides convenient access to all MCP (Model Context Protocol)
tools with simplified syntax. This tool wraps the MCP server functionality and provides
direct access to tools without requiring a running MCP server.

Usage:
    mcp_cli.py <category> <tool> [arguments...]
    mcp_cli.py --list-categories
    mcp_cli.py --list-tools [category]
    mcp_cli.py --help

Examples:
    mcp_cli.py dataset load --source "huggingface:datasets/imdb" --format json
    mcp_cli.py ipfs get --hash "QmXgqKTbzdh83pQdX2E93gLKUMW7QMj9r6jzZK6vYK7x5m"
    mcp_cli.py vector create --data "sample.json" --dimension 768 --metric cosine
    mcp_cli.py graph extract --text "sample.txt" --format graphml
"""

import argparse
import anyio
import json
import sys
import importlib
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Callable
import traceback


def setup_sys_path():
    """Add the package to sys.path if needed."""
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))


def discover_mcp_tools() -> Dict[str, Dict[str, Any]]:
    """Discover all available MCP tools from the mcp_server.tools directory."""
    setup_sys_path()
    
    tools_by_category = {}
    base_tools_path = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools"
    
    if not base_tools_path.exists():
        print(f"Warning: Tools directory not found at {base_tools_path}")
        return tools_by_category
    
    # Scan for tool categories (directories)
    for category_dir in base_tools_path.iterdir():
        if not category_dir.is_dir() or category_dir.name.startswith('_'):
            continue
            
        category_name = category_dir.name
        tools_by_category[category_name] = {}
        
        # Scan for Python files in the category
        for tool_file in category_dir.glob("*.py"):
            if tool_file.name.startswith('_') or tool_file.name == "__init__.py":
                continue
                
            tool_name = tool_file.stem
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category_name}.{tool_name}"
            
            try:
                # Try to import the module
                module = importlib.import_module(module_path)
                
                # Look for callable functions in the module
                functions = []
                for name, obj in inspect.getmembers(module, inspect.isfunction):
                    if not name.startswith('_') and name not in ['main', 'setup', 'test']:
                        sig = inspect.signature(obj)
                        functions.append({
                            'name': name,
                            'signature': str(sig),
                            'doc': obj.__doc__ or "No description available"
                        })
                
                if functions:
                    tools_by_category[category_name][tool_name] = {
                        'module_path': module_path,
                        'functions': functions,
                        'file_path': str(tool_file)
                    }
                    
            except Exception as e:
                # Skip modules that can't be imported
                pass
                
    return tools_by_category


def print_available_categories(tools_by_category: Dict[str, Dict[str, Any]]) -> None:
    """Print all available tool categories."""
    print("Available MCP Tool Categories:")
    print("=" * 40)
    
    for category, tools in sorted(tools_by_category.items()):
        tool_count = len(tools)
        print(f"  {category:<25} ({tool_count} tools)")
    
    print(f"\nTotal: {len(tools_by_category)} categories")
    print("\nUse --list-tools <category> to see tools in a specific category")


def print_tools_in_category(category: str, tools_by_category: Dict[str, Dict[str, Any]]) -> None:
    """Print all tools in a specific category."""
    if category not in tools_by_category:
        print(f"Error: Category '{category}' not found")
        return
        
    tools = tools_by_category[category]
    print(f"Tools in category '{category}':")
    print("=" * 50)
    
    for tool_name, tool_info in sorted(tools.items()):
        print(f"\n  {tool_name}:")
        for func_info in tool_info['functions']:
            print(f"    • {func_info['name']}{func_info['signature']}")
            if func_info['doc']:
                doc_preview = func_info['doc'].split('\n')[0][:80]
                print(f"      {doc_preview}...")


def convert_cli_args_to_kwargs(args: List[str]) -> Dict[str, Any]:
    """Convert CLI arguments to keyword arguments for tool functions."""
    kwargs = {}
    i = 0
    
    while i < len(args):
        arg = args[i]
        
        if arg.startswith('--'):
            key = arg[2:]  # Remove --
            
            # Check if next arg is a value or another flag
            if i + 1 < len(args) and not args[i + 1].startswith('--'):
                value = args[i + 1]
                
                # Try to parse as JSON, number, or boolean
                try:
                    if value.lower() in ['true', 'false']:
                        kwargs[key] = value.lower() == 'true'
                    elif value.startswith('{') or value.startswith('['):
                        kwargs[key] = json.loads(value)
                    elif value.isdigit():
                        kwargs[key] = int(value)
                    elif '.' in value and value.replace('.', '').isdigit():
                        kwargs[key] = float(value)
                    else:
                        kwargs[key] = value
                except:
                    kwargs[key] = value
                    
                i += 2
            else:
                # Boolean flag without value
                kwargs[key] = True
                i += 1
        else:
            # Positional argument - use as 'data' or 'input'
            if 'data' not in kwargs and 'input' not in kwargs:
                kwargs['data'] = arg
            i += 1
    
    return kwargs


async def execute_tool(category: str, tool_name: str, function_name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a specific tool function with given arguments."""
    try:
        module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
        module = importlib.import_module(module_path)
        
        if not hasattr(module, function_name):
            return {
                "status": "error",
                "error": f"Function '{function_name}' not found in {tool_name}",
                "available_functions": [name for name, obj in inspect.getmembers(module, inspect.isfunction) 
                                      if not name.startswith('_')]
            }
        
        func = getattr(module, function_name)
        
        # Handle async and sync functions
        if asyncio.iscoroutinefunction(func):
            result = await func(**kwargs)
        else:
            result = func(**kwargs)
            
        return {
            "status": "success",
            "tool": f"{category}.{tool_name}.{function_name}",
            "result": result
        }
        
    except Exception as e:
        return {
            "status": "error",
            "tool": f"{category}.{tool_name}.{function_name}",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def print_result(result: Dict[str, Any], output_format: str = "pretty") -> None:
    """Print execution results in the specified format."""
    if output_format == "json":
        print(json.dumps(result, indent=2, default=str))
        return
    
    status = result.get("status", "unknown")
    
    if status == "success":
        print("✅ Success!")
        if "tool" in result:
            print(f"Tool: {result['tool']}")
        
        if "result" in result:
            result_data = result["result"]
            if isinstance(result_data, dict):
                for key, value in result_data.items():
                    print(f"  {key}: {value}")
            else:
                print(f"  Result: {result_data}")
                
    elif status == "error":
        print("❌ Error!")
        if "tool" in result:
            print(f"Tool: {result['tool']}")
        if "error" in result:
            print(f"Error: {result['error']}")
        if "available_functions" in result:
            print("Available functions:")
            for func in result["available_functions"]:
                print(f"  - {func}")


def main():
    """Main CLI entry point."""
    # Handle special flags first
    if "--list-categories" in sys.argv:
        tools_by_category = discover_mcp_tools()
        print_available_categories(tools_by_category)
        return
    
    if "--list-tools" in sys.argv:
        try:
            idx = sys.argv.index("--list-tools")
            if idx + 1 < len(sys.argv):
                category = sys.argv[idx + 1]
                tools_by_category = discover_mcp_tools()
                print_tools_in_category(category, tools_by_category)
                return
        except:
            pass
    
    if "--help" in sys.argv or "-h" in sys.argv or len(sys.argv) < 3:
        print("""MCP CLI Tool for IPFS Datasets Python

Usage:
  mcp_cli.py <category> <tool> [function] [arguments...]
  mcp_cli.py --list-categories
  mcp_cli.py --list-tools <category>
  mcp_cli.py --help

Examples:
  mcp_cli.py dataset_tools load_dataset --source "test" --format json
  mcp_cli.py ipfs_tools get_from_ipfs --hash "QmTest123"
  mcp_cli.py vector_tools create_vector_index --dimension 768 --metric cosine
  
  mcp_cli.py --list-categories
  mcp_cli.py --list-tools dataset_tools

Arguments:
  --output {pretty,json}    Output format (default: pretty)
  
Tool-specific arguments use --key value format.""")
        return
    
    # Parse basic arguments
    output_format = "pretty"
    if "--output" in sys.argv:
        try:
            idx = sys.argv.index("--output")
            if idx + 1 < len(sys.argv):
                output_format = sys.argv[idx + 1]
                # Remove --output and its value from args
                sys.argv.pop(idx)  # Remove --output
                sys.argv.pop(idx)  # Remove value
        except:
            pass
    
    if len(sys.argv) < 3:
        print("Error: Missing category and tool arguments")
        return
        
    category = sys.argv[1]
    tool = sys.argv[2]
    remaining_args = sys.argv[3:]  # Everything after tool name
    
    # Discover available tools
    tools_by_category = discover_mcp_tools()
    
    # Validate category and tool
    if category not in tools_by_category:
        print(f"Error: Category '{category}' not found")
        print("Use --list-categories to see available categories")
        return
        
    if tool not in tools_by_category[category]:
        print(f"Error: Tool '{tool}' not found in category '{category}'")
        print(f"Use --list-tools {category} to see available tools")
        return
    
    # Determine function to call
    tool_info = tools_by_category[category][tool]
    available_functions = [f['name'] for f in tool_info['functions']]
    
    # Check if first arg might be a function name
    function_name = None
    tool_args = remaining_args
    
    if remaining_args and remaining_args[0] in available_functions:
        function_name = remaining_args[0]
        tool_args = remaining_args[1:]  # Remove function name from args
    elif available_functions:
        function_name = available_functions[0]  # Use first available function
    else:
        print(f"Error: No callable functions found in {tool}")
        return
    
    # Convert CLI args to kwargs
    kwargs = convert_cli_args_to_kwargs(tool_args)
    
    # Execute the tool
    async def run():
        result = await execute_tool(category, tool, function_name, kwargs)
        print_result(result, output_format)
    
    try:
        anyio.run(run())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}")
        if output_format == "json":
            print(json.dumps({"status": "error", "error": str(e)}))


if __name__ == "__main__":
    main()