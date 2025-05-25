#!/usr/bin/env python3
"""
Check what functions are actually available in each tool module.
"""

import sys
import importlib
sys.path.insert(0, '.')

def check_module_functions(module_path):
    """Check what functions are available in a module."""
    try:
        print(f"\n=== Checking module: {module_path} ===")
        module = importlib.import_module(module_path)
        
        # Get all callable functions (not private)
        functions = [name for name in dir(module) 
                    if not name.startswith('_') and callable(getattr(module, name))]
        
        print(f"Available functions: {functions}")
        return functions
    except Exception as e:
        print(f"Error importing {module_path}: {e}")
        return []

if __name__ == "__main__":
    modules_to_check = [
        "ipfs_datasets_py.mcp_server.tools.security_tools",
        "ipfs_datasets_py.mcp_server.tools.vector_tools", 
        "ipfs_datasets_py.mcp_server.tools.graph_tools",
        "ipfs_datasets_py.mcp_server.tools.provenance_tools",
        "ipfs_datasets_py.mcp_server.tools.ipfs_tools",
    ]
    
    all_functions = {}
    for module_path in modules_to_check:
        all_functions[module_path] = check_module_functions(module_path)
    
    print(f"\n=== Summary ===")
    for module, functions in all_functions.items():
        print(f"{module}: {len(functions)} functions - {functions}")
