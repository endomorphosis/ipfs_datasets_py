#!/usr/bin/env python3
"""
Quick test of all 21 MCP tools to check their current status.
This will test the basic import and execution of each tool.
"""

import sys
import asyncio
import importlib
import traceback
from typing import Dict, Any

sys.path.insert(0, '.')

# Tool mapping with correct function names and parameters
TOOLS = {
    "audit_tools": [
        ("record_audit_event", {"action": "test.operation", "resource_id": "test", "details": {"test": "data"}})
    ],
    "dataset_tools": [
        ("save_dataset", {"dataset_id": "test", "destination": "/tmp/test.json"}),
        ("load_dataset", {"dataset_path": "/tmp/test.json"}),
        ("convert_dataset_format", {"dataset_id": "test", "target_format": "json", "output_path": "/tmp/test.json"})
    ],
    "security_tools": [
        ("check_access_permission", {"resource_id": "test", "user_id": "user", "permission_type": "read"})
    ],
    "vector_tools": [
        ("create_vector_index", {"vectors": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], "dimension": 3})
    ],
    "graph_tools": [
        ("query_knowledge_graph", {"graph_id": "test", "query": "MATCH (n) RETURN n LIMIT 10"})
    ],
    "provenance_tools": [
        ("record_provenance", {"dataset_id": "test", "operation": "test_operation"})
    ],
    "ipfs_tools": [
        ("get_from_ipfs", {"cid": "QmTest123"})
    ]
}

async def test_tool(module_name: str, function_name: str, test_args: Dict[str, Any]) -> Dict[str, Any]:
    """Test a single tool function."""
    try:
        print(f"Testing {module_name}.{function_name}...")
        
        # Import the module and function
        module_path = f"ipfs_datasets_py.mcp_server.tools.{module_name}"
        module = importlib.import_module(module_path)
        func = getattr(module, function_name)
        
        # Call the function
        if asyncio.iscoroutinefunction(func):
            result = await func(**test_args)
        else:
            result = func(**test_args)
        
        print(f"✓ {function_name}: {result.get('status', 'success')}")
        return {"status": "success", "result": result}
        
    except Exception as e:
        print(f"✗ {function_name}: {e}")
        return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

async def main():
    """Run all tool tests."""
    results = {}
    total_tools = 0
    successful_tools = 0
    
    for module_name, tool_list in TOOLS.items():
        print(f"\n=== Testing {module_name} ===")
        module_results = {}
        
        for function_name, test_args in tool_list:
            total_tools += 1
            result = await test_tool(module_name, function_name, test_args)
            module_results[function_name] = result
            
            if result["status"] == "success":
                successful_tools += 1
        
        results[module_name] = module_results
    
    # Print summary
    success_rate = (successful_tools / total_tools) * 100 if total_tools > 0 else 0
    print(f"\n=== SUMMARY ===")
    print(f"Total tools tested: {total_tools}")
    print(f"Successful: {successful_tools}")
    print(f"Failed: {total_tools - successful_tools}")
    print(f"Success rate: {success_rate:.1f}%")
    
    # Save detailed results
    import json
    with open("tool_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nDetailed results saved to tool_test_results.json")

if __name__ == "__main__":
    asyncio.run(main())
