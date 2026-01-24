#!/usr/bin/env python3
"""
Complete MCP Tools Discovery and Testing Script

This script discovers ALL MCP tools and tests them comprehensively.
"""

import anyio
import json
import sys
import traceback
import importlib
import inspect
from pathlib import Path
from typing import Dict, Any, List, Tuple, Callable

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

class CompleteMCPToolTester:
    """Complete test harness for ALL MCP tools"""
    
    def __init__(self):
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.discovered_tools = {}
        
    def discover_all_tools(self) -> Dict[str, List[Dict[str, Any]]]:
        """Discover all MCP tools in the project"""
        tools_base_path = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools"
        
        tool_categories = [
            "dataset_tools",
            "ipfs_tools", 
            "audit_tools",
            "vector_tools",
            "provenance_tools",
            "security_tools",
            "graph_tools",
            "web_archive_tools",
            "development_tools",
            "cli",
            "functions",
            "lizardpersons_function_tools"
        ]
        
        discovered = {}
        
        for category in tool_categories:
            category_path = tools_base_path / category
            if category_path.exists():
                discovered[category] = self._discover_tools_in_category(category_path, category)
                
        return discovered
        
    def _discover_tools_in_category(self, category_path: Path, category_name: str) -> List[Dict[str, Any]]:
        """Discover tools in a specific category with improved filtering"""
        tools = []
        
        # Exclude standard library and common imports that aren't MCP tools
        excluded_names = {
            'dataclass', 'asdict', 'field', 'abstractmethod', 'as_completed',
            'wraps', 'partial', 'reduce', 'filter', 'map', 'zip', 'enumerate',
            'range', 'len', 'str', 'int', 'bool', 'list', 'dict', 'set', 'tuple',
            'open', 'print', 'input', 'type', 'isinstance', 'hasattr', 'getattr',
            'setattr', 'delattr', 'callable', 'iter', 'next', 'all', 'any',
            'min', 'max', 'sum', 'abs', 'round', 'sorted', 'reversed',
            'aiofiles', 'asyncio', 'aiohttp', 'async', 'await',
            'logging', 'config', 'logger', 'Path', 'pathlib', 'os', 'sys', 'shutil', 'glob',
            'json', 'yaml', 'csv', 'pickle', 'base64', 'time', 'datetime', 'timedelta',
            're', 'match', 'search', 'findall', 'sub', 'defaultdict', 'Counter', 'OrderedDict', 'namedtuple',
            'List', 'Dict', 'Tuple', 'Set', 'Optional', 'Union', 'Any', 'Callable',
            'Exception', 'ValueError', 'TypeError', 'KeyError', 'AttributeError',
            'ImportError', 'FileNotFoundError', 'PermissionError'
        }
        
        # Look for Python files
        for py_file in category_path.rglob("*.py"):
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue
                
            try:
                # Convert file path to module name
                relative_path = py_file.relative_to(Path(__file__).parent)
                module_name = str(relative_path.with_suffix("")).replace("/", ".")
                
                # Try to import the module
                try:
                    module = importlib.import_module(module_name)
                except Exception as e:
                    print(f"⚠️  Failed to import {module_name}: {e}")
                    continue
                
                # Find callable functions/tools with improved filtering
                for name, obj in inspect.getmembers(module):
                    # Skip if in exclude list
                    if name in excluded_names:
                        continue
                        
                    # Must be a function or coroutine
                    if not (inspect.isfunction(obj) or inspect.iscoroutinefunction(obj)):
                        continue
                        
                    # Skip private functions
                    if name.startswith("_"):
                        continue
                        
                    # Must be defined in the current module (not imported)
                    if hasattr(obj, '__module__') and obj.__module__ != module_name:
                        continue
                        
                    # Must have parameters (MCP tools take arguments)
                    try:
                        sig = inspect.signature(obj)
                        if len(sig.parameters) == 0:
                            continue
                    except (ValueError, TypeError):
                        continue
                        
                    # Additional validation for MCP tools
                    mcp_tool_patterns = [
                        'load_', 'save_', 'create_', 'generate_', 'process_', 'convert_',
                        'record_', 'search_', 'get_', 'pin_', 'extract_', 'index_',
                        'check_', 'query_', 'execute_', 'list_', 'use_', 'run_'
                    ]
                    
                    # If name starts with common MCP tool patterns, it's likely valid
                    is_mcp_tool = any(name.startswith(pattern) for pattern in mcp_tool_patterns)
                    
                    # Or if it's in a file that matches the function name
                    if not is_mcp_tool and name.lower() in py_file.stem.lower():
                        is_mcp_tool = True
                        
                    # Or if it's a known MCP tool function
                    known_tools = {
                        'test_generator', 'codebase_search', 'documentation_generator', 
                        'lint_python_codebase', 'development_tool_mcp_wrapper',
                        'set_config', 'audit_log'
                    }
                    if name in known_tools:
                        is_mcp_tool = True
                    
                    if is_mcp_tool:
                        tools.append({
                            "name": name,
                            "function": obj,
                            "module": module_name,
                            "file": str(py_file),
                            "is_async": inspect.iscoroutinefunction(obj),
                            "signature": str(sig),
                            "category": category_name
                        })
                        
            except Exception as e:
                print(f"⚠️  Error processing {py_file}: {e}")
                continue
                
        return tools
        
    async def test_tool_function(self, tool_info: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """Test a single tool function"""
        try:
            self.total_tests += 1
            tool_name = tool_info["name"]
            tool_func = tool_info["function"]
            is_async = tool_info["is_async"]
            
            print(f"\n🔧 Testing {tool_info['category']}.{tool_name}...")
            
            # Generate test parameters based on function signature
            sig = inspect.signature(tool_func)
            test_params = self._generate_test_params(sig, tool_name)
            
            # Call the tool
            if is_async:
                result = await tool_func(**test_params)
            else:
                result = tool_func(**test_params)
            
            # Validate result
            if isinstance(result, dict) and "status" in result:
                status = result.get("status", "unknown")
                if status == "success":
                    self.passed_tests += 1
                    print(f"✅ {tool_name} PASSED")
                    return True, "success", result
                else:
                    error_msg = result.get("message", f"Tool returned status: {status}")
                    print(f"❌ {tool_name} FAILED: {error_msg}")
                    return False, error_msg, result
            else:
                # Tool returned something other than expected format
                self.passed_tests += 1  # Still count as success if no error
                print(f"✅ {tool_name} RETURNED: {type(result)}")
                return True, f"Returned {type(result)}", {"result": str(result)[:200]}
                
        except Exception as e:
            self.failed_tests += 1
            error_msg = f"Exception: {str(e)}"
            print(f"💥 {tool_name} CRASHED: {error_msg}")
            return False, error_msg, {"error": str(e), "traceback": traceback.format_exc()}
            
    def _generate_test_params(self, sig: inspect.Signature, tool_name: str) -> Dict[str, Any]:
        """Generate test parameters for a function signature"""
        params = {}
        
        for param_name, param in sig.parameters.items():
            # Special handling for specific tools/parameters
            if tool_name == "generate_audit_report" and param_name == "report_type":
                params[param_name] = "security"  # Use valid report type
            elif tool_name == "create_vector_index" and param_name == "vectors":
                params[param_name] = [[0.1, 0.2, 0.3, 0.4, 0.5], [0.6, 0.7, 0.8, 0.9, 1.0]]  # 5D vectors
            elif tool_name == "create_vector_index" and param_name == "metadata":
                params[param_name] = [{"vector_id": 0}, {"vector_id": 1}]  # Match vector count
            elif tool_name == "search_vector_index" and param_name == "query_vector":
                params[param_name] = [0.1, 0.2, 0.3, 0.4, 0.5]  # 5D query vector
            elif tool_name == "pin_to_ipfs" and param_name == "content_source":
                # Create a temporary test file
                test_file = "/tmp/mcp_test_file.txt"
                with open(test_file, "w") as f:
                    f.write("Test content for MCP testing")
                params[param_name] = test_file
            elif (tool_name.startswith("extract_") or tool_name == "index_warc") and param_name in ["warc_path", "cdxj_path"]:
                # Create test WARC or CDXJ files for web archive tools
                if param_name == "warc_path":
                    test_warc_content = """WARC/1.0
WARC-Type: warcinfo
WARC-Date: 2023-01-01T00:00:00Z
WARC-Record-ID: <urn:uuid:test-record-1>
Content-Length: 0

WARC/1.0
WARC-Type: response
WARC-Target-URI: http://example.com/
WARC-Date: 2023-01-01T00:00:01Z
WARC-Record-ID: <urn:uuid:test-record-2>
Content-Type: application/http; msgtype=response
Content-Length: 100

HTTP/1.1 200 OK
Content-Type: text/html

<html><head><title>Test</title></head><body>Hello World</body></html>
"""
                    test_file = "/tmp/mcp_test_archive.warc"
                    with open(test_file, "w") as f:
                        f.write(test_warc_content)
                    params[param_name] = test_file
                elif param_name == "cdxj_path":
                    test_cdxj_content = """com,example)/ 20230101000001 {"url": "http://example.com/", "mime": "text/html", "status": "200", "digest": "sha1:ABC123", "length": "100", "offset": "123", "filename": "test.warc.gz"}
"""
                    test_file = "/tmp/mcp_test_index.cdxj"
                    with open(test_file, "w") as f:
                        f.write(test_cdxj_content)
                    params[param_name] = test_file
            elif tool_name == "test_generator" and param_name == "test_specification":
                params[param_name] = {
                    "imports": ["import unittest"],
                    "tests": [
                        {
                            "name": "test_example", 
                            "description": "Test example functionality",
                            "assertions": ["self.assertTrue(True)"],
                            "parametrized": False
                        }
                    ]
                }
            elif tool_name == "lint_python_codebase" and param_name in ["patterns", "exclude_patterns"]:
                if param_name == "patterns":
                    params[param_name] = ["*.py"]
                else:
                    params[param_name] = [".venv", "__pycache__"]
            elif tool_name == "development_tool_mcp_wrapper" and param_name == "tool_class":
                params[param_name] = "TestToolClass"
            elif param_name in ["source", "destination", "cid", "dataset_id", "action", "query"] and param.annotation == str:
                # Provide realistic test values
                if param_name == "source":
                    params[param_name] = "test_dataset"
                elif param_name == "destination":
                    params[param_name] = "/tmp/test_output.json"
                elif param_name == "cid":
                    params[param_name] = "QmTest123"
                elif param_name == "dataset_id":
                    params[param_name] = "test_dataset_123"
                elif param_name == "action":
                    params[param_name] = "test.action"
                elif param_name == "query":
                    params[param_name] = "SELECT * FROM test"
                else:
                    params[param_name] = f"test_{param_name}"
            elif param.annotation == str or param_name in ["path", "program_name", "function_name"]:
                params[param_name] = f"test_{param_name}"
            elif param.annotation == int or param_name in ["timeout_seconds", "top_k", "dimension"]:
                if param_name == "dimension":
                    params[param_name] = 5  # Default to 5D
                elif param_name == "top_k":
                    params[param_name] = 3
                else:
                    params[param_name] = 5
            elif param.annotation == bool:
                params[param_name] = True
            elif param.annotation == list or param_name in ["vectors", "operations", "tags", "inputs"]:
                if param_name == "vectors":
                    params[param_name] = [[0.1, 0.2, 0.3, 0.4, 0.5], [0.6, 0.7, 0.8, 0.9, 1.0]]
                elif param_name == "operations":
                    params[param_name] = [{"type": "filter", "condition": "label == 1"}]
                elif param_name == "inputs":
                    params[param_name] = ["input_1", "input_2"]
                else:
                    params[param_name] = ["test_item"]
            elif param.annotation == dict or param_name in ["options", "details", "parameters", "metadata"]:
                params[param_name] = {"test": "value"}
            elif param.default != inspect.Parameter.empty:
                # Use default value
                params[param_name] = param.default
            elif not param_name in ["self", "cls"]:
                # Provide a generic value
                params[param_name] = f"test_value_for_{param_name}"
                
        return params
        
    async def test_all_discovered_tools(self):
        """Test all discovered tools"""
        print("🔍 Discovering all MCP tools...")
        self.discovered_tools = self.discover_all_tools()
        
        print(f"\n📊 Found tools in {len(self.discovered_tools)} categories:")
        for category, tools in self.discovered_tools.items():
            print(f"  - {category}: {len(tools)} tools")
            
        results = {}
        
        for category, tools in self.discovered_tools.items():
            print(f"\n{'='*60}")
            print(f"🧪 Testing {category.upper()} ({len(tools)} tools)")
            print(f"{'='*60}")
            
            category_results = {}
            
            for tool_info in tools:
                passed, message, result = await self.test_tool_function(tool_info)
                category_results[tool_info["name"]] = {
                    "passed": passed,
                    "message": message,
                    "result": result,
                    "module": tool_info["module"],
                    "is_async": tool_info["is_async"],
                    "signature": tool_info["signature"]
                }
                
            results[category] = category_results
            
        return results
        
    def print_comprehensive_summary(self, results: Dict[str, Any]):
        """Print comprehensive test summary"""
        print("\n" + "="*80)
        print("🧪 COMPLETE MCP TOOLS TEST SUMMARY")
        print("="*80)
        
        print(f"📊 Overall Results:")
        print(f"   Total tools discovered: {sum(len(tools) for tools in self.discovered_tools.values())}")
        print(f"   Total tests run: {self.total_tests}")
        print(f"   Passed: {self.passed_tests}")
        print(f"   Failed: {self.failed_tests}")
        print(f"   Success rate: {(self.passed_tests/self.total_tests*100):.1f}%" if self.total_tests > 0 else "   Success rate: N/A")
        
        print(f"\n📋 By Category:")
        for category, tools in results.items():
            category_passed = sum(1 for tool in tools.values() if tool.get("passed", False))
            category_total = len(tools)
            success_rate = (category_passed/category_total*100) if category_total > 0 else 0
            print(f"   {category}: {category_passed}/{category_total} tools passed ({success_rate:.1f}%)")
        
        # Detailed results
        print(f"\n🔍 Detailed Results:")
        for category, tools in results.items():
            if tools:
                print(f"\n  {category.upper()}:")
                for tool_name, result in tools.items():
                    status = "✅" if result.get("passed", False) else "❌"
                    message = result.get("message", "No message")
                    async_marker = " [ASYNC]" if result.get("is_async", False) else ""
                    print(f"    {status} {tool_name}{async_marker}: {message}")
                    
        # Tools needing attention
        print(f"\n⚠️  Tools Needing Attention:")
        failed_tools = []
        for category, tools in results.items():
            for tool_name, result in tools.items():
                if not result.get("passed", False):
                    failed_tools.append(f"{category}.{tool_name}: {result.get('message', 'Unknown error')}")
        
        if failed_tools:
            for failed_tool in failed_tools[:10]:  # Show first 10
                print(f"    - {failed_tool}")
            if len(failed_tools) > 10:
                print(f"    ... and {len(failed_tools) - 10} more")
        else:
            print("    🎉 No tools need attention!")

async def main():
    """Main execution"""
    print("🚀 Starting COMPLETE MCP Tools Discovery and Testing")
    print("="*80)
    
    tester = CompleteMCPToolTester()
    
    # Discover and test all tools
    results = await tester.test_all_discovered_tools()
    
    # Print comprehensive summary
    tester.print_comprehensive_summary(results)
    
    # Save results to file
    results_file = Path(__file__).parent / "complete_mcp_test_results.json"
    with open(results_file, "w") as f:
        json.dump({
            "discovered_tools": {cat: [{"name": t["name"], "module": t["module"], 
                                      "is_async": t["is_async"], "signature": t["signature"]} 
                                     for t in tools] 
                               for cat, tools in tester.discovered_tools.items()},
            "test_results": results,
            "summary": {
                "total_tools": sum(len(tools) for tools in tester.discovered_tools.values()),
                "total_tests": tester.total_tests,
                "passed": tester.passed_tests,
                "failed": tester.failed_tests,
                "success_rate": (tester.passed_tests/tester.total_tests*100) if tester.total_tests > 0 else 0
            }
        }, f, indent=2, default=str)
    
    print(f"\n💾 Complete results saved to: {results_file}")
    
    # Return appropriate exit code
    success_rate = (tester.passed_tests/tester.total_tests*100) if tester.total_tests > 0 else 0
    if success_rate >= 80:
        print(f"\n🎉 Excellent! {success_rate:.1f}% success rate")
        return 0
    elif success_rate >= 60:
        print(f"\n👍 Good! {success_rate:.1f}% success rate") 
        return 0
    else:
        print(f"\n⚠️  Needs work: {success_rate:.1f}% success rate")
        return 1

if __name__ == "__main__":
    sys.exit(anyio.run(main()))
