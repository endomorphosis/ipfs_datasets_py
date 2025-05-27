#!/usr/bin/env python3
"""
Simple MCP Tools Verification and Test Script

This script checks which MCP tools are available and tests them individually.
"""

import os
import sys
import importlib
import traceback
import asyncio
from pathlib import Path

# Import the configuration loading function
from ipfs_datasets_py.mcp_server.configs import load_config_from_yaml, configs

def discover_tools():
    """Discover all available MCP tools."""
    tools_discovered = {}
    tools_path = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools"
    
    print(f"Looking for tools in: {tools_path}")
    
    if not tools_path.exists():
        print(f"Tools path does not exist: {tools_path}")
        return tools_discovered
    
    # Iterate through each category directory
    for category_dir in tools_path.iterdir():
        if category_dir.is_dir() and not category_dir.name.startswith('__'):
            category_name = category_dir.name
            tools_discovered[category_name] = []
            
            print(f"\nChecking category: {category_name}")
            
            # Look for Python files in this category
            for tool_file in category_dir.glob("*.py"):
                if tool_file.name != "__init__.py":
                    tool_name = tool_file.stem
                    tools_discovered[category_name].append(tool_name)
                    print(f"  Found tool: {tool_name}")
    
    return tools_discovered

def test_tool_import(category, tool_name):
    """Test if a tool can be imported."""
    try:
        module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
        module = importlib.import_module(module_path)
        
        # Look for the main function (usually has the same name as the file)
        if hasattr(module, tool_name):
            func = getattr(module, tool_name)
            print(f"    ✓ Tool function found: {tool_name}")
            return True, func
        else:
            # Look for any async function
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if callable(attr) and not attr_name.startswith('_'):
                    print(f"    ✓ Found callable: {attr_name}")
                    return True, attr
            
            print(f"    ✗ No suitable function found in {tool_name}")
            return False, None
            
    except ImportError as e:
        print(f"    ✗ Import failed: {e}")
        return False, None
    except Exception as e:
        print(f"    ✗ Unexpected error: {e}")
        return False, None

async def test_tool_execution(category, tool_name, func):
    """Test basic execution of a tool."""
    try:
        # Get function signature to understand parameters
        import inspect
        sig = inspect.signature(func)
        params = {}
        
        # Provide basic test parameters based on common patterns
        for param_name, param in sig.parameters.items():
            if param_name in ['source', 'dataset', 'data']:
                params[param_name] = "test_data"
            elif param_name in ['path', 'output_path', 'destination']:
                params[param_name] = "/tmp/test_output"
            elif param_name in ['cid']:
                params[param_name] = "QmTestCID123"
            elif param_name in ['format']:
                params[param_name] = "json"
            elif param_name in ['command']:
                params[param_name] = "echo 'test'"
            elif param_name in ['code']:
                params[param_name] = "print('test')"
            elif param_name in ['query']:
                params[param_name] = "SELECT * FROM test LIMIT 1"
            elif param_name in ['urls']:
                params[param_name] = ["https://example.com"]
            elif param_name in ['operations']:
                params[param_name] = ["normalize"]
            
        # Try to call the function
        if asyncio.iscoroutinefunction(func):
            result = await func(**params)
        else:
            result = func(**params)
        
        print(f"    ✓ Execution successful")
        print(f"      Result type: {type(result)}")
        
        if isinstance(result, dict) and 'status' in result:
            print(f"      Status: {result.get('status')}")
        
        return True, result
        
    except Exception as e:
        print(f"    ⚠ Execution failed: {e}")
        return False, str(e)

async def main():
    """Main test function."""
    print("="*60)
    print("MCP TOOLS VERIFICATION AND TEST")
    print("="*60)
    
    # Load configuration
    config_path = Path(__file__).parent / "config" / "mcp_config.yaml"
    loaded_configs = load_config_from_yaml(str(config_path))
    # Update the global configs instance
    configs.__dict__.update(loaded_configs.__dict__)

    # Print configuration values for debugging
    print(f"Debug: configs.ipfs_kit_integration = {configs.ipfs_kit_integration}")
    print(f"Debug: configs.ipfs_kit_mcp_url = {configs.ipfs_kit_mcp_url}")

    # Discover tools
    tools = discover_tools()
    
    if not tools:
        print("No tools discovered!")
        return
    
    total_tools = sum(len(tool_list) for tool_list in tools.values())
    print(f"\nTotal tools discovered: {total_tools}")
    
    # Test each tool
    passed = 0
    failed = 0
    
    for category, tool_list in tools.items():
        print(f"\n{'='*40}")
        print(f"TESTING CATEGORY: {category.upper()}")
        print(f"{'='*40}")
        
        for tool_name in tool_list:
            print(f"\nTesting {category}.{tool_name}:")
            
            # Test import
            import_success, func = test_tool_import(category, tool_name)
            
            if import_success and func:
                # Test execution
                exec_success, result = await test_tool_execution(category, tool_name, func)
                
                if exec_success:
                    passed += 1
                else:
                    failed += 1
            else:
                failed += 1
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Total tools: {total_tools}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success rate: {passed/total_tools*100:.1f}%" if total_tools > 0 else "0%")

if __name__ == "__main__":
    asyncio.run(main())
