#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced IPFS Datasets CLI Tool

A comprehensive command line interface that provides access to ALL MCP tools
with simplified syntax. This tool exposes all 31+ tool categories available
in the IPFS Datasets Python package.

Usage:
    enhanced-cli <category> <tool> [arguments]
    enhanced-cli --list-categories
    enhanced-cli --list-tools <category>
    enhanced-cli --help
"""

import argparse
import anyio
import json
import sys
import importlib
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import traceback


def setup_sys_path():
    """Add the package to sys.path if needed."""
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))


def print_result(result: Dict[str, Any], format_type: str = "pretty") -> None:
    """Print results in a user-friendly format."""
    if format_type == "json":
        print(json.dumps(result, indent=2))
        return
    
    if result.get("status") == "success":
        print("✅ Success!")
        if "message" in result:
            print(f"Message: {result['message']}")
        if "dataset_id" in result:
            print(f"Dataset ID: {result['dataset_id']}")
        if "summary" in result:
            summary = result["summary"]
            if isinstance(summary, dict):
                print("Summary:")
                for key, value in summary.items():
                    print(f"  {key}: {value}")
            else:
                print(f"Summary: {summary}")
        if "result" in result and result["result"] != result.get("message"):
            print(f"Result: {result['result']}")
    else:
        print("❌ Error!")
        if "error" in result:
            print(f"Error: {result['error']}")
        if "message" in result:
            print(f"Message: {result['message']}")


class DynamicToolRunner:
    """Dynamically discover and run MCP tools."""
    
    def __init__(self):
        self.tools_dir = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools"
        self.discovered_tools = {}
        self.discover_tools()
    
    def discover_tools(self):
        """Discover all available tools."""
        if not self.tools_dir.exists():
            print(f"Warning: Tools directory not found: {self.tools_dir}")
            return
        
        for category_dir in self.tools_dir.iterdir():
            if not category_dir.is_dir() or category_dir.name.startswith('_'):
                continue
            
            category_name = category_dir.name
            self.discovered_tools[category_name] = {}
            
            # Look for Python files in the category
            for tool_file in category_dir.glob("*.py"):
                if tool_file.name.startswith('_') or tool_file.name == "__init__.py":
                    continue
                
                tool_name = tool_file.stem
                module_path = f"ipfs_datasets_py.mcp_server.tools.{category_name}.{tool_name}"
                self.discovered_tools[category_name][tool_name] = module_path
    
    def get_categories(self) -> List[str]:
        """Get list of available tool categories."""
        return sorted(self.discovered_tools.keys())
    
    def get_tools(self, category: str) -> List[str]:
        """Get list of tools in a category."""
        return sorted(self.discovered_tools.get(category, {}).keys())
    
    async def run_tool(self, category: str, tool: str, **kwargs) -> Dict[str, Any]:
        """Run a specific tool."""
        setup_sys_path()
        
        if category not in self.discovered_tools:
            return {"status": "error", "error": f"Category '{category}' not found"}
        
        if tool not in self.discovered_tools[category]:
            return {"status": "error", "error": f"Tool '{tool}' not found in category '{category}'"}
        
        module_path = self.discovered_tools[category][tool]
        
        try:
            # Import the module
            module = importlib.import_module(module_path)
            
            # Find callable functions in the module
            functions = []
            for name, obj in inspect.getmembers(module):
                if inspect.isfunction(obj) and not name.startswith('_'):
                    functions.append((name, obj))
            
            if not functions:
                return {"status": "error", "error": f"No callable functions found in {module_path}"}
            
            # Try to find a function that matches the tool name or use the first one
            target_function = None
            for func_name, func_obj in functions:
                if func_name == tool or func_name == f"{tool}_tool" or tool in func_name:
                    target_function = func_obj
                    break
            
            if not target_function:
                # Use the first function
                target_function = functions[0][1]
            
            # Get function signature
            sig = inspect.signature(target_function)
            
            # Filter kwargs to match function parameters
            filtered_kwargs = {}
            for param_name in sig.parameters:
                if param_name in kwargs:
                    filtered_kwargs[param_name] = kwargs[param_name]
            
            # Call the function
            if asyncio.iscoroutinefunction(target_function):
                result = await target_function(**filtered_kwargs)
            else:
                result = target_function(**filtered_kwargs)
            
            # Ensure result is a dict
            if not isinstance(result, dict):
                result = {"status": "success", "result": str(result)}
            
            return result
            
        except ImportError as e:
            return {"status": "error", "error": f"Failed to import {module_path}: {e}"}
        except Exception as e:
            return {"status": "error", "error": f"Failed to run tool: {e}"}


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    # Use parse_known_args to handle dynamic tool arguments
    parser = argparse.ArgumentParser(
        prog="enhanced-cli",
        description="Enhanced command line interface for IPFS Datasets Python tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,  # We'll handle help manually
        epilog="""
Examples:
  # List all available categories
  enhanced-cli --list-categories
  
  # List tools in a specific category
  enhanced-cli --list-tools dataset_tools
  
  # Run a specific tool
  enhanced-cli dataset_tools load_dataset --source squad --format json
  enhanced-cli ipfs_tools get_from_ipfs --hash QmHash123
  enhanced-cli vector_tools create_vector_index --data "text data" --index_name my_index
  
  # Get JSON output
  enhanced-cli --format json dataset_tools load_dataset --source squad
        """
    )
    
    parser.add_argument("--help", "-h", action="store_true",
                       help="Show this help message and exit")
    parser.add_argument("--format", choices=["pretty", "json"], default="pretty",
                       help="Output format (default: pretty)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose output")
    parser.add_argument("--list-categories", action="store_true",
                       help="List all available tool categories")
    parser.add_argument("--list-tools", metavar="CATEGORY",
                       help="List tools in a specific category")
    
    parser.add_argument("category", nargs="?", help="Tool category")
    parser.add_argument("tool", nargs="?", help="Tool name")
    
    return parser


def parse_tool_args(args_list: List[str]) -> Dict[str, Any]:
    """Parse tool arguments from command line."""
    kwargs = {}
    i = 0
    while i < len(args_list):
        arg = args_list[i]
        if arg.startswith('--'):
            key = arg[2:]  # Remove --
            if i + 1 < len(args_list) and not args_list[i + 1].startswith('--'):
                value = args_list[i + 1]
                # Try to parse as JSON, otherwise keep as string
                try:
                    kwargs[key] = json.loads(value)
                except json.JSONDecodeError:
                    kwargs[key] = value
                i += 2
            else:
                # Boolean flag
                kwargs[key] = True
                i += 1
        else:
            i += 1
    return kwargs


async def main():
    """Main CLI entry point."""
    parser = create_parser()
    
    # Parse known args to handle dynamic tool arguments
    args, unknown_args = parser.parse_known_args()
    
    if args.help:
        parser.print_help()
        return
    
    runner = DynamicToolRunner()
    
    if args.list_categories:
        categories = runner.get_categories()
        if args.format == "json":
            print(json.dumps({"categories": categories}, indent=2))
        else:
            print("Available tool categories:")
            for category in categories:
                tools = runner.get_tools(category)
                print(f"  {category} ({len(tools)} tools)")
        return
    
    if args.list_tools:
        tools = runner.get_tools(args.list_tools)
        if not tools:
            print(f"Category '{args.list_tools}' not found or has no tools")
            return
        
        if args.format == "json":
            print(json.dumps({"category": args.list_tools, "tools": tools}, indent=2))
        else:
            print(f"Tools in {args.list_tools}:")
            for tool in tools:
                print(f"  {tool}")
        return
    
    if not args.category or not args.tool:
        print("Error: Both category and tool are required")
        parser.print_help()
        return
    
    if args.verbose:
        print(f"Running: {args.category}.{args.tool} with args: {unknown_args}")
    
    try:
        # Parse tool arguments from unknown_args
        kwargs = parse_tool_args(unknown_args)
        
        # Run the tool
        result = await runner.run_tool(args.category, args.tool, **kwargs)
        
        if result:
            print_result(result, args.format)
        
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        if args.verbose:
            traceback.print_exc()
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main)