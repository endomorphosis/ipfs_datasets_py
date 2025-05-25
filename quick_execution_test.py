#!/usr/bin/env python3
"""
Quick execution test for the core 9 tools.
"""

import sys
import asyncio
import importlib
sys.path.insert(0, '.')

async def test_tool_execution(module_name, function_name, test_args):
    """Test executing a tool function."""
    try:
        module_path = f"ipfs_datasets_py.mcp_server.tools.{module_name}"
        module = importlib.import_module(module_path)
        func = getattr(module, function_name)
        
        # Call the function
        if asyncio.iscoroutinefunction(func):
            result = await func(**test_args)
        else:
            result = func(**test_args)
        
        status = result.get('status', 'unknown')
        return True, status, str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
        
    except Exception as e:
        return False, "error", str(e)[:100] + "..." if len(str(e)) > 100 else str(e)

async def main():
    """Test all tools."""
    tools = [
        ("audit_tools", "record_audit_event", {"action": "test.operation"}),
        ("dataset_tools", "save_dataset", {"dataset_id": "test", "destination": "/tmp/test.json"}),
        ("dataset_tools", "load_dataset", {"dataset_path": "/tmp/test.json"}),
        ("dataset_tools", "convert_dataset_format", {"dataset_id": "test", "target_format": "json", "output_path": "/tmp/test.json"}),
        ("security_tools", "check_access_permission", {"resource_id": "test", "user_id": "user"}),
        ("vector_tools", "create_vector_index", {"vectors": [[1.0, 2.0], [3.0, 4.0]]}),
        ("graph_tools", "query_knowledge_graph", {"graph_id": "test", "query": "MATCH (n) RETURN n LIMIT 5"}),
        ("provenance_tools", "record_provenance", {"dataset_id": "test", "operation": "test_op"}),
        ("ipfs_tools", "get_from_ipfs", {"cid": "QmTest123"}),
    ]
    
    print("=== Tool Execution Test ===")
    success_count = 0
    total_count = len(tools)
    
    for module_name, function_name, test_args in tools:
        success, status, result = await test_tool_execution(module_name, function_name, test_args)
        symbol = "✓" if success and status == "success" else "✗" if not success else "~"
        print(f"{symbol} {module_name}.{function_name}: {status}")
        if success and status == "success":
            success_count += 1
    
    print(f"\n=== Summary ===")
    print(f"Successfully executed: {success_count}/{total_count}")
    print(f"Success rate: {(success_count/total_count)*100:.1f}%")

if __name__ == "__main__":
    asyncio.run(main())
