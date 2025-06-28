#!/usr/bin/env python3
"""
Comprehensive MCP Server Tools Verification

This script tests all MCP server tools to ensure they properly expose the
ipfs_datasets_py library features and function correctly.
"""

import os
import sys
import json
import asyncio
import logging
import traceback
import importlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from unittest.mock import MagicMock, AsyncMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("mcp_tools_test")

class MCPToolsVerifier:
    """Comprehensive verifier for all MCP server tools."""
    
    def __init__(self):
        self.project_root = Path(__file__).resolve().parent
        self.mcp_server_path = self.project_root / "ipfs_datasets_py" / "mcp_server"
        self.tools_path = self.mcp_server_path / "tools"
        
        self.results = {
            "total_tools": 0,
            "tools_tested": 0,
            "tools_passed": 0,
            "tools_failed": 0,
            "tool_categories": {},
            "detailed_results": {},
            "coverage_analysis": {}
        }
        
        # Expected tool categories
        self.expected_categories = [
            "dataset_tools", "ipfs_tools", "vector_tools", "graph_tools",
            "audit_tools", "security_tools", "provenance_tools", 
            "web_archive_tools", "development_tools", "cli", "functions"
        ]
    
    def discover_all_tools(self):
        """Discover all available MCP tools."""
        print("🔍 Discovering MCP Tools...")
        print("=" * 60)
        
        if not self.tools_path.exists():
            print(f"❌ Tools directory not found: {self.tools_path}")
            return False
        
        # Scan all tool categories
        for category_path in self.tools_path.iterdir():
            if category_path.is_dir() and not category_path.name.startswith('__'):
                category_name = category_path.name
                tools = []
                
                # Find all Python files in the category
                for tool_file in category_path.glob("*.py"):
                    if not tool_file.name.startswith('__'):
                        tool_name = tool_file.stem
                        tools.append(tool_name)
                
                if tools:
                    self.results["tool_categories"][category_name] = {
                        "tools": tools,
                        "count": len(tools),
                        "path": str(category_path)
                    }
                    self.results["total_tools"] += len(tools)
                    
                    print(f"📁 {category_name}: {len(tools)} tools")
                    for tool in tools:
                        print(f"   - {tool}")
        
        print(f"\n📊 Total tools discovered: {self.results['total_tools']}")
        print(f"📂 Categories found: {len(self.results['tool_categories'])}")
        return True
    
    def test_tool_imports(self):
        """Test if all tools can be imported."""
        print("\n🧪 Testing Tool Imports...")
        print("=" * 60)
        
        import_results = {}
        
        for category, info in self.results["tool_categories"].items():
            category_results = []
            
            for tool_name in info["tools"]:
                result = self._test_single_tool_import(category, tool_name)
                category_results.append(result)
                
                if result["status"] == "success":
                    print(f"✅ {category}.{tool_name}")
                else:
                    print(f"❌ {category}.{tool_name}: {result['error'][:50]}...")
            
            import_results[category] = category_results
        
        self.results["detailed_results"]["imports"] = import_results
        
        # Calculate success rates
        total_tested = sum(len(results) for results in import_results.values())
        total_passed = sum(1 for results in import_results.values() 
                          for result in results if result["status"] == "success")
        
        print(f"\n📈 Import Success Rate: {total_passed}/{total_tested} ({total_passed/total_tested*100:.1f}%)")
        return total_passed, total_tested
    
    def _test_single_tool_import(self, category, tool_name):
        """Test importing a single tool."""
        try:
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
            module = importlib.import_module(module_path)
            
            # Check if the tool has the expected function
            if hasattr(module, tool_name):
                return {
                    "status": "success",
                    "has_function": True,
                    "module": module_path
                }
            else:
                return {
                    "status": "warning",
                    "has_function": False,
                    "error": f"No main function '{tool_name}' found",
                    "module": module_path
                }
        except Exception as e:
            return {
                "status": "error",
                "has_function": False,
                "error": str(e),
                "module": module_path
            }
    
    def test_tool_functionality(self):
        """Test basic functionality of importable tools."""
        print("\n⚡ Testing Tool Functionality...")
        print("=" * 60)
        
        functionality_results = {}
        
        # Test tools from each category
        test_functions = {
            "dataset_tools": self._test_dataset_tools,
            "ipfs_tools": self._test_ipfs_tools,
            "vector_tools": self._test_vector_tools,
            "graph_tools": self._test_graph_tools,
            "audit_tools": self._test_audit_tools,
            "security_tools": self._test_security_tools,
            "provenance_tools": self._test_provenance_tools,
            "web_archive_tools": self._test_web_archive_tools,
            "development_tools": self._test_development_tools,
            "cli": self._test_cli_tools,
            "functions": self._test_function_tools
        }
        
        for category in self.results["tool_categories"]:
            if category in test_functions:
                print(f"\n🔧 Testing {category}...")
                try:
                    results = test_functions[category]()
                    functionality_results[category] = results
                    
                    passed = sum(1 for r in results if r.get("status") == "success")
                    total = len(results)
                    print(f"   {category}: {passed}/{total} tools passed")
                    
                except Exception as e:
                    print(f"   ❌ Error testing {category}: {e}")
                    functionality_results[category] = []
            else:
                print(f"   ⚠️ No test function for {category}")
                functionality_results[category] = []
        
        self.results["detailed_results"]["functionality"] = functionality_results
        return functionality_results
    
    def _test_dataset_tools(self):
        """Test dataset tools functionality."""
        results = []
        
        # Test load_dataset
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
            
            # Test with mock data
            result = asyncio.run(load_dataset("test_dataset"))
            if isinstance(result, dict) and "status" in result:
                results.append({"tool": "load_dataset", "status": "success"})
            else:
                results.append({"tool": "load_dataset", "status": "error", "error": "Invalid return format"})
        except Exception as e:
            results.append({"tool": "load_dataset", "status": "error", "error": str(e)})
        
        # Test save_dataset
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
            result = asyncio.run(save_dataset("test_id", "/tmp/test.json"))
            results.append({"tool": "save_dataset", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "save_dataset", "status": "error", "error": str(e)})
        
        # Test process_dataset
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
            result = asyncio.run(process_dataset({"data": []}, [{"type": "filter"}]))
            results.append({"tool": "process_dataset", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "process_dataset", "status": "error", "error": str(e)})
        
        # Test convert_dataset_format
        try:
            from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format
            result = asyncio.run(convert_dataset_format("test_id", "csv"))
            results.append({"tool": "convert_dataset_format", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "convert_dataset_format", "status": "error", "error": str(e)})
        
        return results
    
    def _test_ipfs_tools(self):
        """Test IPFS tools functionality."""
        results = []
        
        # Test get_from_ipfs
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs
            result = asyncio.run(get_from_ipfs("QmTest123"))
            results.append({"tool": "get_from_ipfs", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "get_from_ipfs", "status": "error", "error": str(e)})
        
        # Test pin_to_ipfs
        try:
            from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs
            result = asyncio.run(pin_to_ipfs("/tmp/test.txt"))
            results.append({"tool": "pin_to_ipfs", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "pin_to_ipfs", "status": "error", "error": str(e)})
        
        return results
    
    def _test_vector_tools(self):
        """Test vector tools functionality."""
        results = []
        
        # Test create_vector_index
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
            vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
            result = asyncio.run(create_vector_index(vectors))
            results.append({"tool": "create_vector_index", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "create_vector_index", "status": "error", "error": str(e)})
        
        # Test search_vector_index
        try:
            from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index
            result = asyncio.run(search_vector_index("test_index", [0.1, 0.2, 0.3]))
            results.append({"tool": "search_vector_index", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "search_vector_index", "status": "error", "error": str(e)})
        
        return results
    
    def _test_graph_tools(self):
        """Test graph tools functionality."""
        results = []
        
        try:
            from ipfs_datasets_py.mcp_server.tools.graph_tools.query_knowledge_graph import query_knowledge_graph
            result = asyncio.run(query_knowledge_graph("test_graph", "SELECT * WHERE { ?s ?p ?o }"))
            results.append({"tool": "query_knowledge_graph", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "query_knowledge_graph", "status": "error", "error": str(e)})
        
        return results
    
    def _test_audit_tools(self):
        """Test audit tools functionality."""
        results = []
        
        # Test record_audit_event
        try:
            from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event
            result = asyncio.run(record_audit_event("test.action"))
            results.append({"tool": "record_audit_event", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "record_audit_event", "status": "error", "error": str(e)})
        
        # Test generate_audit_report
        try:
            from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report
            result = asyncio.run(generate_audit_report())
            results.append({"tool": "generate_audit_report", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "generate_audit_report", "status": "error", "error": str(e)})
        
        return results
    
    def _test_security_tools(self):
        """Test security tools functionality."""
        results = []
        
        try:
            from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import check_access_permission
            result = asyncio.run(check_access_permission("resource_id", "user_id"))
            results.append({"tool": "check_access_permission", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "check_access_permission", "status": "error", "error": str(e)})
        
        return results
    
    def _test_provenance_tools(self):
        """Test provenance tools functionality."""
        results = []
        
        try:
            from ipfs_datasets_py.mcp_server.tools.provenance_tools.record_provenance import record_provenance
            result = asyncio.run(record_provenance("dataset_id", "operation"))
            results.append({"tool": "record_provenance", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "record_provenance", "status": "error", "error": str(e)})
        
        return results
    
    def _test_web_archive_tools(self):
        """Test web archive tools functionality."""
        results = []
        
        tools_to_test = [
            "create_warc", "extract_dataset_from_cdxj", "extract_links_from_warc",
            "extract_metadata_from_warc", "extract_text_from_warc", "index_warc"
        ]
        
        for tool_name in tools_to_test:
            try:
                module = importlib.import_module(f"ipfs_datasets_py.mcp_server.tools.web_archive_tools.{tool_name}")
                tool_func = getattr(module, tool_name)
                
                # Test with minimal parameters
                if tool_name == "create_warc":
                    result = asyncio.run(tool_func("http://example.com"))
                elif tool_name in ["extract_dataset_from_cdxj", "index_warc"]:
                    result = asyncio.run(tool_func("/tmp/test.warc"))
                else:
                    result = asyncio.run(tool_func("/tmp/test.warc"))
                
                results.append({"tool": tool_name, "status": "success" if isinstance(result, dict) else "error"})
            except Exception as e:
                results.append({"tool": tool_name, "status": "error", "error": str(e)})
        
        return results
    
    def _test_development_tools(self):
        """Test development tools functionality."""
        results = []
        
        development_tools = [
            "test_generator", "documentation_generator", "codebase_search", 
            "linting_tools", "test_runner"
        ]
        
        for tool_name in development_tools:
            try:
                # Try to import the development tool
                module = importlib.import_module(f"ipfs_datasets_py.mcp_server.tools.development_tools.{tool_name}")
                
                # Check if it has expected methods/classes
                if hasattr(module, tool_name) or hasattr(module, tool_name.replace('_', '').title()):
                    results.append({"tool": tool_name, "status": "success"})
                else:
                    results.append({"tool": tool_name, "status": "warning", "error": "No main function/class found"})
            except Exception as e:
                results.append({"tool": tool_name, "status": "error", "error": str(e)})
        
        return results
    
    def _test_cli_tools(self):
        """Test CLI tools functionality."""
        results = []
        
        try:
            from ipfs_datasets_py.mcp_server.tools.cli.execute_command import execute_command
            result = asyncio.run(execute_command("echo test"))
            results.append({"tool": "execute_command", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "execute_command", "status": "error", "error": str(e)})
        
        return results
    
    def _test_function_tools(self):
        """Test function tools functionality."""
        results = []
        
        try:
            from ipfs_datasets_py.mcp_server.tools.functions.execute_python_snippet import execute_python_snippet
            result = asyncio.run(execute_python_snippet("print('test')"))
            results.append({"tool": "execute_python_snippet", "status": "success" if isinstance(result, dict) else "error"})
        except Exception as e:
            results.append({"tool": "execute_python_snippet", "status": "error", "error": str(e)})
        
        return results
    
    def test_mcp_server_startup(self):
        """Test MCP server startup and tool registration."""
        print("\n🚀 Testing MCP Server Startup...")
        print("=" * 60)
        
        try:
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            
            # Test server initialization
            server = IPFSDatasetsMCPServer()
            print("✅ Server initialization successful")
            
            # Test tool registration
            server.register_tools()
            print(f"✅ Tool registration successful - {len(server.tools)} tools registered")
            
            # Check for expected tools
            expected_core_tools = [
                "load_dataset", "save_dataset", "process_dataset", 
                "get_from_ipfs", "pin_to_ipfs", "record_audit_event"
            ]
            
            missing_tools = []
            for tool in expected_core_tools:
                if tool not in server.tools:
                    missing_tools.append(tool)
            
            if missing_tools:
                print(f"⚠️ Missing expected tools: {', '.join(missing_tools)}")
            else:
                print("✅ All expected core tools are registered")
            
            self.results["detailed_results"]["server_startup"] = {
                "status": "success",
                "tools_registered": len(server.tools),
                "missing_tools": missing_tools,
                "tool_names": list(server.tools.keys())
            }
            
            return True
            
        except Exception as e:
            print(f"❌ Server startup failed: {e}")
            self.results["detailed_results"]["server_startup"] = {
                "status": "error",
                "error": str(e)
            }
            return False
    
    def analyze_library_coverage(self):
        """Analyze how well MCP tools cover the ipfs_datasets_py library features."""
        print("\n📋 Analyzing Library Feature Coverage...")
        print("=" * 60)
        
        # Expected library features that should have MCP tool coverage
        expected_features = {
            "dataset_operations": ["load_dataset", "save_dataset", "process_dataset", "convert_dataset_format"],
            "ipfs_operations": ["pin_to_ipfs", "get_from_ipfs"],
            "vector_search": ["create_vector_index", "search_vector_index"],
            "knowledge_graphs": ["query_knowledge_graph"],
            "audit_logging": ["record_audit_event", "generate_audit_report"],
            "data_provenance": ["record_provenance"],
            "security": ["check_access_permission"],
            "web_archiving": ["create_warc", "extract_text_from_warc", "index_warc"],
            "development_tools": ["test_generator", "documentation_generator", "codebase_search"]
        }
        
        # Check coverage
        coverage_results = {}
        
        # Get all discovered tools
        all_tools = []
        for category_info in self.results["tool_categories"].values():
            all_tools.extend(category_info["tools"])
        
        for feature_area, expected_tools in expected_features.items():
            covered_tools = []
            missing_tools = []
            
            for tool in expected_tools:
                if tool in all_tools:
                    covered_tools.append(tool)
                else:
                    missing_tools.append(tool)
            
            coverage_percentage = (len(covered_tools) / len(expected_tools)) * 100
            
            coverage_results[feature_area] = {
                "expected": len(expected_tools),
                "covered": len(covered_tools),
                "coverage_percentage": coverage_percentage,
                "covered_tools": covered_tools,
                "missing_tools": missing_tools
            }
            
            status_icon = "✅" if coverage_percentage == 100 else "⚠️" if coverage_percentage >= 75 else "❌"
            print(f"{status_icon} {feature_area}: {coverage_percentage:.1f}% ({len(covered_tools)}/{len(expected_tools)})")
            
            if missing_tools:
                print(f"    Missing: {', '.join(missing_tools)}")
        
        self.results["coverage_analysis"] = coverage_results
        
        # Calculate overall coverage
        total_expected = sum(len(tools) for tools in expected_features.values())
        total_covered = sum(result["covered"] for result in coverage_results.values())
        overall_coverage = (total_covered / total_expected) * 100
        
        print(f"\n📊 Overall Library Coverage: {overall_coverage:.1f}% ({total_covered}/{total_expected})")
        
        return coverage_results
    
    def generate_report(self):
        """Generate a comprehensive verification report."""
        print("\n📄 Generating Verification Report...")
        print("=" * 60)
        
        # Calculate final statistics
        import_results = self.results["detailed_results"].get("imports", {})
        functionality_results = self.results["detailed_results"].get("functionality", {})
        
        total_imports_tested = sum(len(results) for results in import_results.values())
        total_imports_passed = sum(1 for results in import_results.values() 
                                  for result in results if result["status"] == "success")
        
        total_functionality_tested = sum(len(results) for results in functionality_results.values())
        total_functionality_passed = sum(1 for results in functionality_results.values() 
                                        for result in results if result.get("status") == "success")
        
        # Update final results
        self.results.update({
            "tools_tested": total_imports_tested,
            "tools_passed": total_imports_passed,
            "tools_failed": total_imports_tested - total_imports_passed,
            "functionality_tested": total_functionality_tested,
            "functionality_passed": total_functionality_passed
        })
        
        # Print summary
        print(f"📊 VERIFICATION SUMMARY")
        print(f"   Tools Discovered: {self.results['total_tools']}")
        print(f"   Import Tests: {total_imports_passed}/{total_imports_tested} passed ({total_imports_passed/total_imports_tested*100:.1f}%)")
        print(f"   Functionality Tests: {total_functionality_passed}/{total_functionality_tested} passed ({total_functionality_passed/total_functionality_tested*100:.1f}%)")
        
        # Save detailed report
        report_path = self.project_root / "mcp_tools_verification_report.json"
        with open(report_path, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        
        print(f"📄 Detailed report saved to: {report_path}")
        
        return self.results
    
    def run_comprehensive_verification(self):
        """Run the complete verification process."""
        print("🎯 COMPREHENSIVE MCP TOOLS VERIFICATION")
        print("=" * 80)
        
        success = True
        
        # Step 1: Discover all tools
        if not self.discover_all_tools():
            print("❌ Tool discovery failed")
            return False
        
        # Step 2: Test imports
        passed, tested = self.test_tool_imports()
        if passed < tested * 0.8:  # Require 80% import success
            print("⚠️ Low import success rate")
            success = False
        
        # Step 3: Test functionality
        self.test_tool_functionality()
        
        # Step 4: Test server startup
        if not self.test_mcp_server_startup():
            print("❌ Server startup test failed")
            success = False
        
        # Step 5: Analyze coverage
        self.analyze_library_coverage()
        
        # Step 6: Generate report
        self.generate_report()
        
        # Final assessment
        print("\n" + "=" * 80)
        if success:
            print("🎉 MCP TOOLS VERIFICATION COMPLETED SUCCESSFULLY")
        else:
            print("⚠️ MCP TOOLS VERIFICATION COMPLETED WITH ISSUES")
        print("=" * 80)
        
        return success

def main():
    """Main entry point."""
    verifier = MCPToolsVerifier()
    success = verifier.run_comprehensive_verification()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
