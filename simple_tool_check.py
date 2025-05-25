#!/usr/bin/env python3
"""
Simple tool status checker that avoids hanging.
"""

import sys
import importlib
sys.path.insert(0, '.')

def check_tool_import(module_name, function_name):
    """Check if a tool can be imported."""
    try:
        module_path = f"ipfs_datasets_py.mcp_server.tools.{module_name}"
        module = importlib.import_module(module_path)
        func = getattr(module, function_name)
        return True, "OK"
    except ImportError as e:
        return False, f"Import error: {e}"
    except AttributeError as e:
        return False, f"Function not found: {e}"
    except Exception as e:
        return False, f"Other error: {e}"

def main():
    """Check all tools."""
    tools = [
        ("audit_tools", "record_audit_event"),
        ("dataset_tools", "save_dataset"),
        ("dataset_tools", "load_dataset"),
        ("dataset_tools", "convert_dataset_format"),
        ("security_tools", "check_access_permission"),
        ("vector_tools", "create_vector_index"),
        ("graph_tools", "query_knowledge_graph"),
        ("provenance_tools", "record_provenance"),
        ("ipfs_tools", "get_from_ipfs"),
    ]
    
    print("=== Tool Import Status ===")
    success_count = 0
    total_count = len(tools)
    
    for module_name, function_name in tools:
        success, message = check_tool_import(module_name, function_name)
        status = "✓" if success else "✗"
        print(f"{status} {module_name}.{function_name}: {message}")
        if success:
            success_count += 1
    
    print(f"\n=== Summary ===")
    print(f"Successful imports: {success_count}/{total_count}")
    print(f"Success rate: {(success_count/total_count)*100:.1f}%")

if __name__ == "__main__":
    main()
