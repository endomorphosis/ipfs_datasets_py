#!/usr/bin/env python3
"""
Final Complete MCP Tools Test
This is the definitive test to verify 100% reliability of all MCP server tools.
"""

import asyncio
import json
import sys
import traceback
from pathlib import Path
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Test configurations for all tools
TOOL_TESTS = {
    # Dataset Tools
    "load_dataset": {
        "module": "ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset",
        "function": "load_dataset",
        "args": {"source": "test_dataset"}
    },
    "save_dataset": {
        "module": "ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset", 
        "function": "save_dataset",
        "args": {"dataset_data": {"test": "data"}, "destination": "/tmp/test.json"}
    },
    "process_dataset": {
        "module": "ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset",
        "function": "process_dataset", 
        "args": {"dataset_source": {"test": "data"}, "operations": [{"type": "test"}]}
    },
    "convert_dataset_format": {
        "module": "ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format",
        "function": "convert_dataset_format",
        "args": {"dataset_id": "test", "target_format": "json"}
    },
    
    # IPFS Tools
    "get_from_ipfs": {
        "module": "ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs",
        "function": "get_from_ipfs",
        "args": {"cid": "QmTest123"}
    },
    "pin_to_ipfs": {
        "module": "ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs",
        "function": "pin_to_ipfs", 
        "args": {"content_source": {"test": "data"}}
    },
    
    # Vector Tools
    "create_vector_index": {
        "module": "ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index",
        "function": "create_vector_index",
        "args": {"vectors": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]}
    },
    "search_vector_index": {
        "module": "ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index",
        "function": "search_vector_index",
        "args": {"index_id": "test_index", "query_vector": [1.0, 2.0, 3.0]}
    },
    
    # Knowledge Graph Tools
    "query_knowledge_graph": {
        "module": "ipfs_datasets_py.mcp_server.tools.knowledge_graph_tools.query_knowledge_graph",
        "function": "query_knowledge_graph",
        "args": {"graph_id": "test_graph", "query": "SELECT * WHERE { ?s ?p ?o }"}
    },
    
    # Audit Tools
    "record_audit_event": {
        "module": "ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event",
        "function": "record_audit_event",
        "args": {"action": "test_action"}
    },
    "generate_audit_report": {
        "module": "ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report",
        "function": "generate_audit_report",
        "args": {}
    },
    
    # Permission Tools
    "check_access_permission": {
        "module": "ipfs_datasets_py.mcp_server.tools.permission_tools.check_access_permission",
        "function": "check_access_permission",
        "args": {"resource_id": "test_resource", "user_id": "test_user"}
    },
    
    # Provenance Tools
    "record_provenance": {
        "module": "ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance",
        "function": "record_provenance",
        "args": {"dataset_id": "test_dataset", "operation": "test_operation"}
    },
    
    # Web Archive Tools
    "archive_webpage": {
        "module": "ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_webpage",
        "function": "archive_webpage",
        "args": {"url": "https://example.com"}
    },
    "fetch_archived_page": {
        "module": "ipfs_datasets_py.mcp_server.tools.web_archive_tools.fetch_archived_page",
        "function": "fetch_archived_page",
        "args": {"archive_id": "test_archive"}
    },
    "search_archive": {
        "module": "ipfs_datasets_py.mcp_server.tools.web_archive_tools.search_archive",
        "function": "search_archive",
        "args": {"query": "test query"}
    },
    "get_archive_metadata": {
        "module": "ipfs_datasets_py.mcp_server.tools.web_archive_tools.get_archive_metadata",
        "function": "get_archive_metadata",
        "args": {"archive_id": "test_archive"}
    },
    "export_archive_snapshot": {
        "module": "ipfs_datasets_py.mcp_server.tools.web_archive_tools.export_archive_snapshot",
        "function": "export_archive_snapshot",
        "args": {"archive_id": "test_archive", "format": "json"}
    },
    
    # Development Tools
    "test_generator": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.test_generator",
        "function": "test_generator",
        "args": {"name": "test_tool", "description": "Test tool description"}
    },
    "code_analyzer": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.code_analyzer", 
        "function": "code_analyzer",
        "args": {"name": "analyzer", "description": "Code analysis tool"}
    },
    "lint_python_codebase": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.lint_python_codebase",
        "function": "lint_python_codebase",
        "args": {"name": "linter", "description": "Python linting tool"}
    },
    "dependency_scanner": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.dependency_scanner",
        "function": "dependency_scanner", 
        "args": {"name": "scanner", "description": "Dependency scanning tool"}
    },
    "performance_profiler": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.performance_profiler",
        "function": "performance_profiler",
        "args": {"name": "profiler", "description": "Performance profiling tool"}
    },
    "security_scanner": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.security_scanner",
        "function": "security_scanner",
        "args": {"name": "security", "description": "Security scanning tool"}
    },
    "documentation_generator": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator",
        "function": "documentation_generator",
        "args": {"name": "docs", "description": "Documentation generation tool"}
    },
    "build_system_manager": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.build_system_manager",
        "function": "build_system_manager",
        "args": {"name": "build", "description": "Build system management tool"}
    },
    "version_controller": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.version_controller",
        "function": "version_controller",
        "args": {"name": "version", "description": "Version control tool"}
    },
    "deployment_manager": {
        "module": "ipfs_datasets_py.mcp_server.tools.development_tools.deployment_manager",
        "function": "deployment_manager",
        "args": {"name": "deploy", "description": "Deployment management tool"}
    },
    
    # LizardPersons Tools  
    "use_function_as_tool": {
        "module": "ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.use_function_as_tool",
        "function": "use_function_as_tool",
        "args": {"function_name": "test_function_name"}
    },
    "use_cli_program_as_tool": {
        "module": "ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.use_cli_program_as_tool",
        "function": "use_cli_program_as_tool",
        "args": {"program_name": "test_program_name"}
    }
}

async def test_tool(tool_name, test_config):
    """Test a single MCP tool"""
    try:
        # Import the module
        module_name = test_config["module"]
        function_name = test_config["function"]
        args = test_config["args"]
        
        module = __import__(module_name, fromlist=[function_name])
        func = getattr(module, function_name)
        
        # Call the function
        if asyncio.iscoroutinefunction(func):
            result = await func(**args)
        else:
            result = func(**args)
            
        # Check if result indicates success
        status = "PASS"
        message = "Tool executed successfully"
        
        if isinstance(result, dict):
            if result.get("status") == "error":
                status = "FAIL"
                message = result.get("message", "Tool returned error status")
            elif "error" in result:
                status = "FAIL" 
                message = str(result.get("error"))
        
        return {
            "tool": tool_name,
            "status": status,
            "message": message,
            "result": result
        }
        
    except Exception as e:
        return {
            "tool": tool_name,
            "status": "FAIL",
            "message": str(e),
            "traceback": traceback.format_exc()
        }

async def run_all_tests():
    """Run all MCP tool tests"""
    print("🧪 Running Final Complete MCP Tools Test")
    print("=" * 60)
    
    results = []
    passed = 0
    failed = 0
    
    for tool_name, test_config in TOOL_TESTS.items():
        print(f"\n⚡ Testing {tool_name}...", end=" ")
        
        result = await test_tool(tool_name, test_config)
        results.append(result)
        
        if result["status"] == "PASS":
            print("✅ PASS")
            passed += 1
        else:
            print("❌ FAIL")
            print(f"   Error: {result['message']}")
            failed += 1
    
    # Summary
    total = len(TOOL_TESTS)
    pass_rate = (passed / total) * 100
    
    print("\n" + "=" * 60)
    print("📊 FINAL TEST SUMMARY")
    print("=" * 60)
    print(f"Total Tools Tested: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Pass Rate: {pass_rate:.1f}%")
    
    if pass_rate == 100.0:
        print("\n🎉 SUCCESS! 100% RELIABILITY ACHIEVED!")
        print("All MCP server tools are working correctly.")
    else:
        print(f"\n⚠️  {failed} tools still need attention:")
        for result in results:
            if result["status"] == "FAIL":
                print(f"   - {result['tool']}: {result['message']}")
    
    # Save detailed results
    detailed_results = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": pass_rate
        },
        "tools": results
    }
    
    with open("final_complete_mcp_test_results.json", "w") as f:
        json.dump(detailed_results, f, indent=2)
    
    print(f"\n📄 Detailed results saved to: final_complete_mcp_test_results.json")
    
    return pass_rate == 100.0

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
