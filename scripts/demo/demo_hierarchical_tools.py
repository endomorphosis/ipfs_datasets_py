#!/usr/bin/env python3
"""Demonstration of Hierarchical Tool Manager Integration.

This script demonstrates how to integrate the hierarchical tool manager
with the existing MCP server to reduce context window usage.

Usage:
    python demo_hierarchical_tools.py --list-categories
    python demo_hierarchical_tools.py --list-tools <category>
    python demo_hierarchical_tools.py --run <category> <tool> [--params '{"key": "value"}']
"""

import asyncio
import argparse
import json
import sys
import importlib.util
from pathlib import Path

# Direct import of the hierarchical_tool_manager module to avoid loading full mcp_server
manager_path = Path(__file__).parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "hierarchical_tool_manager.py"
spec = importlib.util.spec_from_file_location("hierarchical_tool_manager", manager_path)
htm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(htm)

# Import functions
get_tool_manager = htm.get_tool_manager
tools_list_categories = htm.tools_list_categories
tools_list_tools = htm.tools_list_tools
tools_get_schema = htm.tools_get_schema
tools_dispatch = htm.tools_dispatch


async def main():
    """Main demonstration function."""
    parser = argparse.ArgumentParser(
        description="Demonstrate Hierarchical Tool Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all tool categories
  %(prog)s --list-categories
  
  # List tools in a category
  %(prog)s --list-tools dataset_tools
  
  # Get schema for a tool
  %(prog)s --get-schema dataset_tools load_dataset
  
  # Run a tool
  %(prog)s --run graph_tools query_knowledge_graph --params '{"query": "test", "max_results": 5}'
        """
    )
    
    # Command options
    parser.add_argument('--list-categories', action='store_true',
                       help='List all tool categories')
    parser.add_argument('--list-tools', metavar='CATEGORY',
                       help='List tools in a category')
    parser.add_argument('--get-schema', nargs=2, metavar=('CATEGORY', 'TOOL'),
                       help='Get schema for a specific tool')
    parser.add_argument('--run', nargs=2, metavar=('CATEGORY', 'TOOL'),
                       help='Run a specific tool')
    parser.add_argument('--params', type=str,
                       help='JSON parameters for tool execution')
    parser.add_argument('--include-count', action='store_true',
                       help='Include tool count when listing categories')
    parser.add_argument('--format', choices=['pretty', 'json'], default='pretty',
                       help='Output format (default: pretty)')
    
    args = parser.parse_args()
    
    # List categories
    if args.list_categories:
        print("Listing tool categories...")
        result = await tools_list_categories(include_count=args.include_count)
        
        if args.format == 'json':
            print(json.dumps(result, indent=2))
        else:
            print(f"\n✅ Found {result['category_count']} categories:\n")
            for cat in result['categories']:
                count_str = f" ({cat['tool_count']} tools)" if args.include_count else ""
                desc = cat.get('description', 'No description')
                print(f"  • {cat['name']}{count_str}")
                if desc:
                    print(f"    {desc}")
        return
    
    # List tools in category
    if args.list_tools:
        print(f"Listing tools in category: {args.list_tools}")
        result = await tools_list_tools(args.list_tools)
        
        if args.format == 'json':
            print(json.dumps(result, indent=2))
        else:
            if result['status'] == 'error':
                print(f"\n❌ Error: {result['error']}")
                if 'available_categories' in result:
                    print(f"\nAvailable categories: {', '.join(result['available_categories'])}")
            else:
                print(f"\n✅ Found {result['tool_count']} tools in '{result['category']}':\n")
                for tool in result['tools']:
                    print(f"  • {tool['name']}")
                    if tool['description']:
                        print(f"    {tool['description']}")
        return
    
    # Get tool schema
    if args.get_schema:
        category, tool = args.get_schema
        print(f"Getting schema for: {category}.{tool}")
        result = await tools_get_schema(category, tool)
        
        if args.format == 'json':
            print(json.dumps(result, indent=2))
        else:
            if result['status'] == 'error':
                print(f"\n❌ Error: {result['error']}")
            else:
                schema = result['schema']
                print(f"\n✅ Schema for {schema['name']}:\n")
                print(f"  Category: {schema['category']}")
                print(f"  Description: {schema['description'][:200]}...")
                print(f"  Signature: {schema['signature']}")
                print(f"\n  Parameters:")
                for param_name, param_info in schema['parameters'].items():
                    req = "required" if param_info.get('required') else "optional"
                    ptype = param_info.get('type', 'Any')
                    default = f" (default: {param_info.get('default')})" if 'default' in param_info else ""
                    print(f"    • {param_name}: {ptype} [{req}]{default}")
        return
    
    # Run a tool
    if args.run:
        category, tool = args.run
        params = {}
        if args.params:
            try:
                params = json.loads(args.params)
            except json.JSONDecodeError as e:
                print(f"❌ Error parsing params: {e}")
                return
        
        print(f"Running tool: {category}.{tool}")
        if params:
            print(f"Parameters: {params}")
        
        result = await tools_dispatch(category, tool, params)
        
        if args.format == 'json':
            print(json.dumps(result, indent=2))
        else:
            if result.get('status') == 'error':
                print(f"\n❌ Error: {result.get('error', 'Unknown error')}")
            else:
                print("\n✅ Tool executed successfully!")
                # Pretty print result
                for key, value in result.items():
                    if key == 'status':
                        continue
                    if isinstance(value, (dict, list)):
                        print(f"\n{key}:")
                        print(json.dumps(value, indent=2))
                    else:
                        print(f"{key}: {value}")
        return
    
    # No command specified
    parser.print_help()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
