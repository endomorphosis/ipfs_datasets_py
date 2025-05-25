#!/usr/bin/env python3
"""
Comprehensive MCP Tools Discovery and Testing Script

This script will:
1. Discover all available MCP tools
2. Test each tool's import capability
3. Test each tool's execution with sample parameters
4. Generate tests for tools that don't have tests
5. Provide a comprehensive report
"""

import sys
import os
import asyncio
import importlib
import inspect
import json
from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path

sys.path.insert(0, '.')

class MCPToolsTestFramework:
    def __init__(self):
        self.tools_base_path = Path("ipfs_datasets_py/mcp_server/tools")
        self.discovered_tools = {}
        self.test_results = {}
        self.tool_categories = [
            "audit_tools", "dataset_tools", "web_archive_tools", 
            "cli", "functions", "security_tools", "vector_tools",
            "graph_tools", "provenance_tools", "ipfs_tools"
        ]
    
    def discover_all_tools(self) -> Dict[str, List[str]]:
        """Discover all tools in each category."""
        print("=== Discovering MCP Tools ===")
        
        for category in self.tool_categories:
            category_path = self.tools_base_path / category
            if not category_path.exists():
                print(f"Category {category} not found")
                continue
                
            try:
                # Import the category module to see what's exported
                module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
                module = importlib.import_module(module_path)
                
                # Get all exported functions
                exported_functions = getattr(module, '__all__', [])
                if not exported_functions:
                    # If no __all__, get all non-private callables
                    exported_functions = [
                        name for name in dir(module) 
                        if not name.startswith('_') and callable(getattr(module, name))
                    ]
                
                self.discovered_tools[category] = exported_functions
                print(f"✓ {category}: {len(exported_functions)} tools - {exported_functions}")
                
            except Exception as e:
                print(f"✗ {category}: Error discovering - {e}")
                self.discovered_tools[category] = []
        
        total_tools = sum(len(tools) for tools in self.discovered_tools.values())
        print(f"\nTotal discovered tools: {total_tools}")
        return self.discovered_tools
    
    async def test_tool_import(self, category: str, tool_name: str) -> Tuple[bool, str]:
        """Test if a tool can be imported."""
        try:
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
            module = importlib.import_module(module_path)
            func = getattr(module, tool_name)
            return True, "Import successful"
        except ImportError as e:
            return False, f"Import error: {e}"
        except AttributeError as e:
            return False, f"Function not found: {e}"
        except Exception as e:
            return False, f"Other error: {e}"
    
    def get_function_signature(self, category: str, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get the function signature and parameters."""
        try:
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
            module = importlib.import_module(module_path)
            func = getattr(module, tool_name)
            
            sig = inspect.signature(func)
            params = {}
            for param_name, param in sig.parameters.items():
                params[param_name] = {
                    'type': str(param.annotation) if param.annotation != inspect.Parameter.empty else 'Any',
                    'default': param.default if param.default != inspect.Parameter.empty else None,
                    'required': param.default == inspect.Parameter.empty
                }
            
            return {
                'is_async': asyncio.iscoroutinefunction(func),
                'parameters': params,
                'docstring': func.__doc__
            }
        except Exception as e:
            return None
    
    def generate_test_parameters(self, category: str, tool_name: str) -> Dict[str, Any]:
        """Generate appropriate test parameters for a tool."""
        # Common test parameters based on common parameter names
        test_params = {}
        
        sig_info = self.get_function_signature(category, tool_name)
        if not sig_info:
            return {}
        
        for param_name, param_info in sig_info['parameters'].items():
            if param_info['required']:
                # Generate test values based on parameter names
                if 'id' in param_name.lower():
                    test_params[param_name] = f"test_{param_name}"
                elif 'path' in param_name.lower():
                    test_params[param_name] = f"/tmp/test_{param_name}"
                elif 'url' in param_name.lower():
                    test_params[param_name] = "https://example.com"
                elif 'query' in param_name.lower():
                    test_params[param_name] = "SELECT * LIMIT 5"
                elif 'command' in param_name.lower():
                    test_params[param_name] = "echo test"
                elif 'code' in param_name.lower():
                    test_params[param_name] = "print('test')"
                elif 'action' in param_name.lower():
                    test_params[param_name] = "test.operation"
                elif 'operation' in param_name.lower():
                    test_params[param_name] = "test_operation"
                elif 'vectors' in param_name.lower():
                    test_params[param_name] = [[1.0, 2.0], [3.0, 4.0]]
                elif 'data' in param_name.lower():
                    test_params[param_name] = {"test": "data"}
                elif param_info['type'] == 'str':
                    test_params[param_name] = f"test_{param_name}"
                elif param_info['type'] == 'int':
                    test_params[param_name] = 1
                elif param_info['type'] == 'bool':
                    test_params[param_name] = True
                elif 'List' in param_info['type']:
                    test_params[param_name] = ["test_item"]
                elif 'Dict' in param_info['type']:
                    test_params[param_name] = {"test": "value"}
                else:
                    test_params[param_name] = f"test_{param_name}"
        
        return test_params
    
    async def test_tool_execution(self, category: str, tool_name: str) -> Dict[str, Any]:
        """Test executing a tool function."""
        try:
            module_path = f"ipfs_datasets_py.mcp_server.tools.{category}"
            module = importlib.import_module(module_path)
            func = getattr(module, tool_name)
            
            # Generate test parameters
            test_params = self.generate_test_parameters(category, tool_name)
            
            # Call the function
            if asyncio.iscoroutinefunction(func):
                result = await func(**test_params)
            else:
                result = func(**test_params)
            
            status = "success"
            if isinstance(result, dict):
                status = result.get('status', 'success')
                if status == 'error':
                    return {
                        'success': False,
                        'status': status,
                        'result': result,
                        'test_params': test_params
                    }
            
            return {
                'success': True,
                'status': status,
                'result': str(result)[:200] + "..." if len(str(result)) > 200 else str(result),
                'test_params': test_params
            }
            
        except Exception as e:
            return {
                'success': False,
                'status': 'error',
                'error': str(e)[:200] + "..." if len(str(e)) > 200 else str(e),
                'test_params': self.generate_test_parameters(category, tool_name)
            }
    
    async def run_comprehensive_tests(self) -> Dict[str, Any]:
        """Run comprehensive tests on all discovered tools."""
        print("\n=== Running Comprehensive Tool Tests ===")
        
        results = {
            'import_tests': {},
            'execution_tests': {},
            'summary': {
                'total_tools': 0,
                'import_success': 0,
                'execution_success': 0,
                'categories': {}
            }
        }
        
        for category, tools in self.discovered_tools.items():
            print(f"\n--- Testing {category} ---")
            category_results = {
                'import_tests': {},
                'execution_tests': {},
                'summary': {'total': len(tools), 'import_success': 0, 'execution_success': 0}
            }
            
            for tool_name in tools:
                results['summary']['total_tools'] += 1
                
                # Test import
                import_success, import_message = await self.test_tool_import(category, tool_name)
                category_results['import_tests'][tool_name] = {
                    'success': import_success,
                    'message': import_message
                }
                
                if import_success:
                    results['summary']['import_success'] += 1
                    category_results['summary']['import_success'] += 1
                    
                    # Test execution
                    execution_result = await self.test_tool_execution(category, tool_name)
                    category_results['execution_tests'][tool_name] = execution_result
                    
                    if execution_result['success']:
                        results['summary']['execution_success'] += 1
                        category_results['summary']['execution_success'] += 1
                    
                    status_symbol = "✓" if execution_result['success'] else "✗"
                    print(f"  {status_symbol} {tool_name}: {execution_result['status']}")
                else:
                    print(f"  ✗ {tool_name}: Import failed - {import_message}")
            
            results['import_tests'][category] = category_results['import_tests']
            results['execution_tests'][category] = category_results['execution_tests']
            results['summary']['categories'][category] = category_results['summary']
        
        return results
    
    def generate_missing_tests(self, results: Dict[str, Any]) -> str:
        """Generate test code for tools that don't have proper tests."""
        test_code = '''#!/usr/bin/env python3
"""
Generated tests for MCP tools.

This file contains automatically generated tests for all MCP tools.
"""

import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
sys.path.insert(0, '.')

class MCPToolsTestSuite(unittest.TestCase):
    """Test suite for all MCP tools."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
    
    def tearDown(self):
        """Clean up after tests."""
        self.loop.close()
    
    def async_test(self, coro):
        """Helper to run async tests."""
        return self.loop.run_until_complete(coro)

'''
        
        for category, execution_tests in results['execution_tests'].items():
            test_code += f'''
class {category.title().replace('_', '')}Test(MCPToolsTestSuite):
    """Tests for {category} tools."""
'''
            
            for tool_name, test_result in execution_tests.items():
                test_params = test_result.get('test_params', {})
                params_str = ', '.join([f'{k}="{v}"' if isinstance(v, str) else f'{k}={v}' 
                                      for k, v in test_params.items()])
                
                test_code += f'''
    def test_{tool_name}(self):
        """Test {tool_name} tool."""
        async def run_test():
            from ipfs_datasets_py.mcp_server.tools.{category} import {tool_name}
            result = await {tool_name}({params_str})
            self.assertIsInstance(result, dict)
            # Add more specific assertions based on expected behavior
        
        self.async_test(run_test())
'''
        
        test_code += '''

if __name__ == '__main__':
    unittest.main()
'''
        
        return test_code
    
    def generate_report(self, results: Dict[str, Any]) -> str:
        """Generate a comprehensive test report."""
        summary = results['summary']
        
        report = f"""
# MCP Tools Comprehensive Test Report

## Summary
- **Total Tools Discovered**: {summary['total_tools']}
- **Import Success Rate**: {summary['import_success']}/{summary['total_tools']} ({(summary['import_success']/summary['total_tools']*100):.1f}%)
- **Execution Success Rate**: {summary['execution_success']}/{summary['total_tools']} ({(summary['execution_success']/summary['total_tools']*100):.1f}%)

## Category Breakdown
"""
        
        for category, cat_summary in summary['categories'].items():
            total = cat_summary['total']
            import_success = cat_summary['import_success']
            exec_success = cat_summary['execution_success']
            
            report += f"""
### {category.title().replace('_', ' ')}
- Tools: {total}
- Import Success: {import_success}/{total} ({(import_success/total*100):.1f}%)
- Execution Success: {exec_success}/{total} ({(exec_success/total*100):.1f}%)
"""
        
        report += "\n## Detailed Results\n"
        
        for category, execution_tests in results['execution_tests'].items():
            report += f"\n### {category}\n"
            for tool_name, test_result in execution_tests.items():
                status = "✅ PASS" if test_result['success'] else "❌ FAIL"
                report += f"- **{tool_name}**: {status}\n"
                if not test_result['success']:
                    error = test_result.get('error', 'Unknown error')
                    report += f"  - Error: {error}\n"
        
        return report

async def main():
    """Run the comprehensive MCP tools test framework."""
    framework = MCPToolsTestFramework()
    
    # Discover all tools
    discovered_tools = framework.discover_all_tools()
    
    # Run comprehensive tests
    results = await framework.run_comprehensive_tests()
    
    # Generate report
    report = framework.generate_report(results)
    print(report)
    
    # Save results
    with open('mcp_tools_comprehensive_test_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    with open('mcp_tools_test_report.md', 'w') as f:
        f.write(report)
    
    # Generate missing tests
    test_code = framework.generate_missing_tests(results)
    with open('generated_mcp_tools_tests.py', 'w') as f:
        f.write(test_code)
    
    print(f"\n📊 Results saved to mcp_tools_comprehensive_test_results.json")
    print(f"📋 Report saved to mcp_tools_test_report.md")
    print(f"🧪 Generated tests saved to generated_mcp_tools_tests.py")
    
    # Print final summary
    summary = results['summary']
    print(f"\n🎯 FINAL SUMMARY:")
    print(f"   Total Tools: {summary['total_tools']}")
    print(f"   Working Tools: {summary['execution_success']}")
    print(f"   Success Rate: {(summary['execution_success']/summary['total_tools']*100):.1f}%")

if __name__ == "__main__":
    asyncio.run(main())
