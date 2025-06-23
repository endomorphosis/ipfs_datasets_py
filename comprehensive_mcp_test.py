#!/usr/bin/env python3
"""
Comprehensive MCP Tools Test Suite

This script tests all MCP server tools to ensure they're working correctly
and validates their outputs.
"""

import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Test results storage
test_results = {
    "dataset_tools": {},
    "ipfs_tools": {},
    "audit_tools": {},
    "vector_tools": {},
    "provenance_tools": {},
    "security_tools": {},
    "graph_tools": {},
    "web_archive_tools": {}
}

class MCPToolTester:
    """Test harness for MCP tools"""
    
    def __init__(self):
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        
    async def test_tool(self, category: str, tool_name: str, tool_function, test_params: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """Test a single MCP tool"""
        try:
            self.total_tests += 1
            print(f"\n🔧 Testing {category}.{tool_name}...")
            
            # Call the tool
            result = await tool_function(**test_params)
            
            # Validate result structure
            if not isinstance(result, dict):
                raise ValueError(f"Tool returned {type(result)}, expected dict")
                
            if 'status' not in result:
                raise ValueError("Tool result missing 'status' field")
                
            # Check if tool succeeded
            status = result.get('status', 'unknown')
            
            if status == 'success':
                self.passed_tests += 1
                print(f"✅ {tool_name} PASSED")
                return True, "success", result
            elif status == 'error':
                error_msg = result.get('message', 'Unknown error')
                print(f"❌ {tool_name} FAILED: {error_msg}")
                return False, f"Tool error: {error_msg}", result
            else:
                print(f"⚠️  {tool_name} UNCLEAR: status={status}")
                return False, f"Unclear status: {status}", result
                
        except Exception as e:
            self.failed_tests += 1
            error_msg = f"Exception: {str(e)}"
            print(f"💥 {tool_name} CRASHED: {error_msg}")
            print(f"Traceback: {traceback.format_exc()}")
            return False, error_msg, {}

    async def test_dataset_tools(self):
        """Test dataset-related tools"""
        print("\n📊 Testing Dataset Tools...")
        
        # Test load_dataset
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
            passed, msg, result = await self.test_tool(
                "dataset_tools", "load_dataset", load_dataset,
                {"source": "imdb", "options": {"split": "test[:10]"}}  # Small sample
            )
            test_results["dataset_tools"]["load_dataset"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["dataset_tools"]["load_dataset"] = {"passed": False, "message": f"Import error: {e}", "result": {}}
            
        # Test process_dataset
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
            
            # Create a simple test dataset
            test_data = {
                "data": [
                    {"id": 1, "text": "Hello world", "label": 1},
                    {"id": 2, "text": "Goodbye world", "label": 0},
                    {"id": 3, "text": "Testing data", "label": 1}
                ]
            }
            
            operations = [
                {"type": "filter", "condition": "label == 1"},
                {"type": "select", "columns": ["id", "text"]}
            ]
            
            passed, msg, result = await self.test_tool(
                "dataset_tools", "process_dataset", process_dataset,
                {"dataset_source": test_data, "operations": operations}
            )
            test_results["dataset_tools"]["process_dataset"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["dataset_tools"]["process_dataset"] = {"passed": False, "message": f"Import error: {e}", "result": {}}
            
        # Test save_dataset
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
            
            test_data = {"data": [{"id": 1, "text": "test"}]}
            
            passed, msg, result = await self.test_tool(
                "dataset_tools", "save_dataset", save_dataset,
                {"dataset_data": test_data, "destination": "/tmp/test_dataset.json", "format": "json"}
            )
            test_results["dataset_tools"]["save_dataset"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["dataset_tools"]["save_dataset"] = {"passed": False, "message": f"Import error: {e}", "result": {}}

    async def test_ipfs_tools(self):
        """Test IPFS-related tools"""
        print("\n🌐 Testing IPFS Tools...")
        
        # Test get_from_ipfs (with a test CID - may fail if IPFS not available)
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs
            passed, msg, result = await self.test_tool(
                "ipfs_tools", "get_from_ipfs", get_from_ipfs,
                {"cid": "QmTest123InvalidCID", "timeout_seconds": 5}  # Intentionally invalid for testing
            )
            test_results["ipfs_tools"]["get_from_ipfs"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["ipfs_tools"]["get_from_ipfs"] = {"passed": False, "message": f"Import error: {e}", "result": {}}
            
        # Test pin_to_ipfs
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs
            
            # Create a test file
            test_file = "/tmp/test_ipfs_pin.txt"
            with open(test_file, "w") as f:
                f.write("Test content for IPFS pinning")
                
            passed, msg, result = await self.test_tool(
                "ipfs_tools", "pin_to_ipfs", pin_to_ipfs,
                {"content_source": test_file}
            )
            test_results["ipfs_tools"]["pin_to_ipfs"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["ipfs_tools"]["pin_to_ipfs"] = {"passed": False, "message": f"Import error: {e}", "result": {}}

    async def test_audit_tools(self):
        """Test audit-related tools"""
        print("\n🔍 Testing Audit Tools...")
        
        # Test record_audit_event
        try:
            from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event
            passed, msg, result = await self.test_tool(
                "audit_tools", "record_audit_event", record_audit_event,
                {
                    "action": "test.action",
                    "resource_id": "test_resource_123",
                    "user_id": "test_user",
                    "details": {"test": True}
                }
            )
            test_results["audit_tools"]["record_audit_event"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["audit_tools"]["record_audit_event"] = {"passed": False, "message": f"Import error: {e}", "result": {}}
            
        # Test generate_audit_report
        try:
            from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report
            passed, msg, result = await self.test_tool(
                "audit_tools", "generate_audit_report", generate_audit_report,
                {"report_type": "security", "output_format": "json"}
            )
            test_results["audit_tools"]["generate_audit_report"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["audit_tools"]["generate_audit_report"] = {"passed": False, "message": f"Import error: {e}", "result": {}}

    async def test_vector_tools(self):
        """Test vector-related tools"""
        print("\n🔢 Testing Vector Tools...")
        
        # Test create_vector_index
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
            
            test_vectors = [
                [0.1, 0.2, 0.3, 0.4],
                [0.5, 0.6, 0.7, 0.8],
                [0.9, 1.0, 1.1, 1.2]
            ]
            
            passed, msg, result = await self.test_tool(
                "vector_tools", "create_vector_index", create_vector_index,
                {"vectors": test_vectors, "dimension": 4, "metric": "cosine"}
            )
            test_results["vector_tools"]["create_vector_index"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["vector_tools"]["create_vector_index"] = {"passed": False, "message": f"Import error: {e}", "result": {}}
            
        # Test search_vector_index
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index
            
            # This might fail if no index exists, but we should test the function
            passed, msg, result = await self.test_tool(
                "vector_tools", "search_vector_index", search_vector_index,
                {"index_id": "test_index", "query_vector": [0.1, 0.2, 0.3, 0.4], "top_k": 5}
            )
            test_results["vector_tools"]["search_vector_index"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["vector_tools"]["search_vector_index"] = {"passed": False, "message": f"Import error: {e}", "result": {}}

    async def test_provenance_tools(self):
        """Test provenance-related tools"""
        print("\n📝 Testing Provenance Tools...")
        
        try:
            from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import record_provenance
            passed, msg, result = await self.test_tool(
                "provenance_tools", "record_provenance", record_provenance,
                {
                    "dataset_id": "test_dataset_123",
                    "operation": "test_transformation",
                    "inputs": ["input_dataset_1"],
                    "parameters": {"test_param": "test_value"}
                }
            )
            test_results["provenance_tools"]["record_provenance"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["provenance_tools"]["record_provenance"] = {"passed": False, "message": f"Import error: {e}", "result": {}}

    async def test_security_tools(self):
        """Test security-related tools"""
        print("\n🔒 Testing Security Tools...")
        
        try:
            from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import check_access_permission
            passed, msg, result = await self.test_tool(
                "security_tools", "check_access_permission", check_access_permission,
                {
                    "resource_id": "test_resource_123",
                    "user_id": "test_user",
                    "permission_type": "read"
                }
            )
            test_results["security_tools"]["check_access_permission"] = {"passed": passed, "message": msg, "result": result}
        except ImportError as e:
            test_results["security_tools"]["check_access_permission"] = {"passed": False, "message": f"Import error: {e}", "result": {}}

    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("🧪 MCP TOOLS TEST SUMMARY")
        print("="*60)
        
        total_categories = len([cat for cat in test_results.values() if cat])
        
        print(f"📊 Overall Results:")
        print(f"   Total tests run: {self.total_tests}")
        print(f"   Passed: {self.passed_tests}")
        print(f"   Failed: {self.failed_tests}")
        print(f"   Success rate: {(self.passed_tests/self.total_tests*100):.1f}%" if self.total_tests > 0 else "   Success rate: N/A")
        
        print(f"\n📋 By Category:")
        for category, tools in test_results.items():
            if tools:
                category_passed = sum(1 for tool in tools.values() if tool.get("passed", False))
                category_total = len(tools)
                print(f"   {category}: {category_passed}/{category_total} tools passed")
        
        # Detailed results
        print(f"\n🔍 Detailed Results:")
        for category, tools in test_results.items():
            if tools:
                print(f"\n  {category.upper()}:")
                for tool_name, result in tools.items():
                    status = "✅" if result.get("passed", False) else "❌"
                    message = result.get("message", "No message")
                    print(f"    {status} {tool_name}: {message}")

async def main():
    """Main test execution"""
    print("🚀 Starting Comprehensive MCP Tools Test")
    print("="*60)
    
    tester = MCPToolTester()
    
    # Run all test categories
    await tester.test_dataset_tools()
    await tester.test_ipfs_tools() 
    await tester.test_audit_tools()
    await tester.test_vector_tools()
    await tester.test_provenance_tools()
    await tester.test_security_tools()
    
    # Print summary
    tester.print_summary()
    
    # Save results to file
    results_file = Path(__file__).parent / "mcp_test_results.json"
    with open(results_file, "w") as f:
        json.dump(test_results, f, indent=2, default=str)
    
    print(f"\n💾 Full results saved to: {results_file}")
    
    # Return appropriate exit code
    if tester.failed_tests == 0:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {tester.failed_tests} tests failed.")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
