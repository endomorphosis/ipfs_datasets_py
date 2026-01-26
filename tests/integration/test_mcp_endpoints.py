"""
Comprehensive Integration Test Suite for MCP Endpoints

This module provides comprehensive integration tests for all MCP endpoints,
tools, and functionality across the IPFS Datasets ecosystem.
"""

import anyio
import json
import pytest
import requests
import time
import inspect
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging
from contextlib import asynccontextmanager

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# Import MCP server for tools access
try:
    from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
except ImportError:
    IPFSDatasetsMCPServer = None


class MCPIntegrationTestSuite:
    """Comprehensive test suite for MCP endpoints and tools."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8899"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.timeout = 30
        self.test_results = {}
        self.logger = logging.getLogger(__name__)
    
    def setup_logging(self):
        """Set up logging for test execution."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    def wait_for_dashboard(self, timeout: int = 60) -> bool:
        """Wait for MCP dashboard to be ready."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = self.session.get(f"{self.base_url}/api/mcp/status")
                if response.status_code == 200:
                    self.logger.info("MCP Dashboard is ready")
                    return True
            except requests.RequestException:
                pass
            time.sleep(2)
        
        self.logger.error("MCP Dashboard failed to start within timeout")
        return False


def _skip_reason_dashboard_unavailable(base_url: str, timeout_seconds: int) -> str:
    return (
        "MCP dashboard service is required for these integration tests but was not reachable. "
        "This test suite is service-dependent and will be skipped when the dashboard is not running.\n\n"
        f"Tried polling: {base_url}/api/mcp/status (timeout={timeout_seconds}s).\n\n"
        "To run locally, start the dashboard and re-run this test. For example:\n"
        "  - VS Code task: Start MCP Dashboard (8899)\n"
        "  - Or run: MCP_DASHBOARD_HOST=127.0.0.1 MCP_DASHBOARD_PORT=8899 MCP_DASHBOARD_BLOCKING=1 "
        "python -m ipfs_datasets_py.mcp_dashboard\n\n"
        "If the dashboard cannot be started in your environment (missing optional deps, port restrictions, etc.), "
        "keep this test skipped and run the unit test suites instead."
    )
    
    def test_basic_endpoints(self) -> Dict[str, Any]:
        """Test basic MCP dashboard endpoints."""
        endpoints = {
            '/': 'Main Dashboard',
            '/api/mcp/status': 'MCP Status API',
            '/api/mcp/tools': 'MCP Tools API',
            '/api/health': 'Health Check',
            '/mcp': 'MCP Interface'
        }
        
        results = {}
        for endpoint, name in endpoints.items():
            try:
                response = self.session.get(f"{self.base_url}{endpoint}")
                results[endpoint] = {
                    'name': name,
                    'status_code': response.status_code,
                    'success': response.status_code == 200,
                    'response_time': response.elapsed.total_seconds(),
                    'content_type': response.headers.get('content-type', ''),
                }
                
                # Additional checks for API endpoints
                if endpoint.startswith('/api/') and response.status_code == 200:
                    try:
                        data = response.json()
                        results[endpoint]['json_valid'] = True
                        results[endpoint]['data_keys'] = list(data.keys()) if isinstance(data, dict) else None
                    except json.JSONDecodeError:
                        results[endpoint]['json_valid'] = False
                
                self.logger.info(f"✅ {name}: {response.status_code}")
                
            except Exception as e:
                results[endpoint] = {
                    'name': name,
                    'success': False,
                    'error': str(e)
                }
                self.logger.error(f"❌ {name}: {e}")
        
        return results
    
    async def test_mcp_tools_loading(self) -> Dict[str, Any]:
        """Test MCP tools loading and availability."""
        try:
            # Test tools API endpoint
            response = self.session.get(f"{self.base_url}/api/mcp/tools")
            if response.status_code != 200:
                return {
                    'success': False,
                    'error': f'Tools API returned {response.status_code}'
                }
            
            tools_data = response.json()
            
            # Test direct tools import via MCP server
            direct_tools_count = 0
            if IPFSDatasetsMCPServer:
                try:
                    server = IPFSDatasetsMCPServer()
                    await server.register_tools()
                    direct_tools_count = len(server.tools)
                except Exception as e:
                    self.logger.warning(f"Direct MCP server tools loading failed: {e}")
            
            # Analyze tools by category
            tools_by_category = {}
            for tool_name, tool_info in tools_data.items():
                category = tool_info.get('category', 'uncategorized')
                if category not in tools_by_category:
                    tools_by_category[category] = []
                tools_by_category[category].append(tool_name)
            
            return {
                'success': True,
                'api_tools_count': len(tools_data),
                'direct_tools_count': direct_tools_count,
                'tools_by_category': tools_by_category,
                'sample_tools': dict(list(tools_data.items())[:10]),
                'categories': list(tools_by_category.keys())
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    async def test_mcp_tool_execution(self, tool_name: str, test_args: Dict) -> Dict[str, Any]:
        """Test execution of a specific MCP tool."""
        try:
            # Get tools from MCP server instance
            if not IPFSDatasetsMCPServer:
                return {
                    'success': False,
                    'error': 'MCP Server not available'
                }
            
            server = IPFSDatasetsMCPServer()
            await server.register_tools()
            
            if tool_name not in server.tools:
                return {
                    'success': False,
                    'error': f'Tool {tool_name} not found'
                }
            
            tool_func = server.tools[tool_name]
            
            # Execute the tool with test arguments
            start_time = time.time()
            if inspect.iscoroutinefunction(tool_func):
                result = await tool_func(**test_args)
            else:
                result = tool_func(**test_args)
            execution_time = time.time() - start_time
            
            return {
                'success': True,
                'execution_time': execution_time,
                'result_type': type(result).__name__,
                'result_keys': list(result.keys()) if isinstance(result, dict) else None,
                'result_size': len(str(result))
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }
    
    async def test_dataset_tools(self) -> Dict[str, Any]:
        """Test dataset-related MCP tools."""
        dataset_tests = [
            {
                'tool': 'list_datasets',
                'args': {'limit': 10}
            },
            {
                'tool': 'get_dataset_info',
                'args': {'dataset_id': 'test_dataset'}
            },
            {
                'tool': 'create_dataset',
                'args': {
                    'name': 'integration_test_dataset',
                    'description': 'Test dataset for integration testing',
                    'data_type': 'text'
                }
            }
        ]
        
        results = {}
        for test in dataset_tests:
            tool_name = test['tool']
            self.logger.info(f"Testing dataset tool: {tool_name}")
            result = await self.test_mcp_tool_execution(tool_name, test['args'])
            results[tool_name] = result
        
        return results
    
    async def test_ipfs_tools(self) -> Dict[str, Any]:
        """Test IPFS-related MCP tools."""
        ipfs_tests = [
            {
                'tool': 'ipfs_node_info',
                'args': {}
            },
            {
                'tool': 'ipfs_pin_list',
                'args': {'limit': 10}
            },
            {
                'tool': 'get_from_ipfs',
                'args': {'cid': 'QmTest123456789'}  # Test CID (will likely fail, but tests the function)
            }
        ]
        
        results = {}
        for test in ipfs_tests:
            tool_name = test['tool']
            self.logger.info(f"Testing IPFS tool: {tool_name}")
            result = await self.test_mcp_tool_execution(tool_name, test['args'])
            results[tool_name] = result
        
        return results
    
    async def test_vector_tools(self) -> Dict[str, Any]:
        """Test vector search and similarity tools."""
        vector_tests = [
            {
                'tool': 'create_vector_index',
                'args': {
                    'vectors': [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
                    'dimension': 3,
                    'metric': 'cosine',
                    'index_id': 'test_integration_index'
                }
            },
            {
                'tool': 'vector_similarity_search',
                'args': {
                    'query_vector': [0.2, 0.3, 0.4],
                    'index_id': 'test_integration_index',
                    'top_k': 5
                }
            }
        ]
        
        results = {}
        for test in vector_tests:
            tool_name = test['tool']
            self.logger.info(f"Testing vector tool: {tool_name}")
            result = await self.test_mcp_tool_execution(tool_name, test['args'])
            results[tool_name] = result
        
        return results
    
    async def test_audit_tools(self) -> Dict[str, Any]:
        """Test audit and logging tools."""
        audit_tests = [
            {
                'tool': 'generate_audit_report',
                'args': {'report_type': 'summary'}
            },
            {
                'tool': 'get_system_logs',
                'args': {'limit': 10}
            }
        ]
        
        results = {}
        for test in audit_tests:
            tool_name = test['tool']
            self.logger.info(f"Testing audit tool: {tool_name}")
            result = await self.test_mcp_tool_execution(tool_name, test['args'])
            results[tool_name] = result
        
        return results
    
    def test_api_performance(self, iterations: int = 10) -> Dict[str, Any]:
        """Test API endpoint performance."""
        endpoints = [
            '/api/mcp/status',
            '/api/mcp/tools',
            '/api/health'
        ]
        
        performance_results = {}
        
        for endpoint in endpoints:
            times = []
            errors = 0
            
            for i in range(iterations):
                try:
                    start_time = time.time()
                    response = self.session.get(f"{self.base_url}{endpoint}")
                    end_time = time.time()
                    
                    if response.status_code == 200:
                        times.append(end_time - start_time)
                    else:
                        errors += 1
                        
                except Exception:
                    errors += 1
            
            if times:
                performance_results[endpoint] = {
                    'avg_response_time': sum(times) / len(times),
                    'min_response_time': min(times),
                    'max_response_time': max(times),
                    'successful_requests': len(times),
                    'failed_requests': errors,
                    'success_rate': len(times) / iterations
                }
            else:
                performance_results[endpoint] = {
                    'successful_requests': 0,
                    'failed_requests': errors,
                    'success_rate': 0
                }
        
        return performance_results
    
    async def run_comprehensive_tests(self) -> Dict[str, Any]:
        """Run the complete integration test suite."""
        self.setup_logging()
        self.logger.info("Starting comprehensive MCP integration tests")
        
        # Wait for dashboard to be ready
        if not self.wait_for_dashboard():
            return {
                'success': False,
                'error': 'MCP Dashboard is not accessible'
            }
        
        test_results = {
            'timestamp': time.time(),
            'success': True,
            'errors': []
        }
        
        # Test basic endpoints
        self.logger.info("Testing basic endpoints...")
        test_results['basic_endpoints'] = self.test_basic_endpoints()
        
        # Test MCP tools loading
        self.logger.info("Testing MCP tools loading...")
        test_results['mcp_tools_loading'] = await self.test_mcp_tools_loading()
        
        # Test different tool categories
        self.logger.info("Testing dataset tools...")
        test_results['dataset_tools'] = await self.test_dataset_tools()
        
        self.logger.info("Testing IPFS tools...")
        test_results['ipfs_tools'] = await self.test_ipfs_tools()
        
        self.logger.info("Testing vector tools...")
        test_results['vector_tools'] = await self.test_vector_tools()
        
        self.logger.info("Testing audit tools...")
        test_results['audit_tools'] = await self.test_audit_tools()
        
        # Test API performance
        self.logger.info("Testing API performance...")
        test_results['performance'] = self.test_api_performance()
        
        # Calculate overall success
        failed_categories = []
        for category, results in test_results.items():
            if isinstance(results, dict) and not results.get('success', True):
                failed_categories.append(category)
        
        test_results['success'] = len(failed_categories) == 0
        test_results['failed_categories'] = failed_categories
        
        self.logger.info(f"Integration tests completed. Success: {test_results['success']}")
        
        return test_results
    
    def save_results(self, results: Dict[str, Any], output_file: str = "mcp_integration_test_results.json"):
        """Save test results to a file."""
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        self.logger.info(f"Test results saved to {output_path}")
    
    def generate_report(self, results: Dict[str, Any]) -> str:
        """Generate a human-readable test report."""
        report = []
        report.append("# MCP Integration Test Report")
        report.append(f"**Timestamp:** {time.ctime(results.get('timestamp', time.time()))}")
        report.append(f"**Overall Success:** {'✅ PASSED' if results.get('success', False) else '❌ FAILED'}")
        report.append("")
        
        # Basic endpoints
        if 'basic_endpoints' in results:
            report.append("## Basic Endpoints")
            for endpoint, data in results['basic_endpoints'].items():
                status = "✅" if data.get('success', False) else "❌"
                name = data.get('name', endpoint)
                report.append(f"- {status} **{name}**: {data.get('status_code', 'Error')}")
            report.append("")
        
        # MCP Tools
        if 'mcp_tools_loading' in results:
            tools_data = results['mcp_tools_loading']
            if tools_data.get('success', False):
                report.append("## MCP Tools")
                report.append(f"- **API Tools Count:** {tools_data.get('api_tools_count', 0)}")
                report.append(f"- **Direct Tools Count:** {tools_data.get('direct_tools_count', 0)}")
                report.append(f"- **Categories:** {', '.join(tools_data.get('categories', []))}")
            report.append("")
        
        # Tool Categories
        for category in ['dataset_tools', 'ipfs_tools', 'vector_tools', 'audit_tools']:
            if category in results:
                report.append(f"## {category.replace('_', ' ').title()}")
                for tool_name, tool_result in results[category].items():
                    status = "✅" if tool_result.get('success', False) else "❌"
                    exec_time = tool_result.get('execution_time', 0)
                    report.append(f"- {status} **{tool_name}**: {exec_time:.3f}s")
                report.append("")
        
        # Performance
        if 'performance' in results:
            report.append("## Performance")
            for endpoint, perf_data in results['performance'].items():
                avg_time = perf_data.get('avg_response_time', 0)
                success_rate = perf_data.get('success_rate', 0)
                report.append(f"- **{endpoint}**: {avg_time:.3f}s avg, {success_rate*100:.1f}% success rate")
            report.append("")
        
        # Failed categories
        if results.get('failed_categories'):
            report.append("## Failed Categories")
            for category in results['failed_categories']:
                report.append(f"- ❌ {category}")
            report.append("")
        
        return "\\n".join(report)


# pytest integration
class TestMCPIntegration:
    """Pytest-compatible test class for MCP integration tests."""
    
    @pytest.fixture(scope="class")
    def test_suite(self):
        """Create test suite instance."""
        return MCPIntegrationTestSuite()
    
    @pytest.mark.asyncio
    async def test_comprehensive_integration(self, test_suite):
        """Run comprehensive integration tests."""
        timeout_seconds = 60
        if not test_suite.wait_for_dashboard(timeout=timeout_seconds):
            pytest.skip(_skip_reason_dashboard_unavailable(test_suite.base_url, timeout_seconds))

        results = await test_suite.run_comprehensive_tests()
        
        # Save results
        test_suite.save_results(results)
        
        # Generate and save report
        report = test_suite.generate_report(results)
        with open("mcp_integration_test_report.md", "w") as f:
            f.write(report)
        
        # Assert overall success
        assert results['success'], f"Integration tests failed. Failed categories: {results.get('failed_categories', [])}"
    
    def test_basic_endpoints_only(self, test_suite):
        """Test only basic endpoints (synchronous)."""
        timeout_seconds = 60
        if not test_suite.wait_for_dashboard(timeout=timeout_seconds):
            pytest.skip(_skip_reason_dashboard_unavailable(test_suite.base_url, timeout_seconds))
        
        results = test_suite.test_basic_endpoints()
        
        # Check critical endpoints
        critical_endpoints = ['/api/mcp/status', '/']
        for endpoint in critical_endpoints:
            assert endpoint in results, f"Critical endpoint {endpoint} not tested"
            assert results[endpoint].get('success', False), f"Critical endpoint {endpoint} failed"
    
    @pytest.mark.asyncio
    async def test_mcp_tools_availability(self, test_suite):
        """Test MCP tools availability."""
        timeout_seconds = 60
        if not test_suite.wait_for_dashboard(timeout=timeout_seconds):
            pytest.skip(_skip_reason_dashboard_unavailable(test_suite.base_url, timeout_seconds))
        
        results = await test_suite.test_mcp_tools_loading()
        assert results.get('success', False), f"MCP tools loading failed: {results.get('error', 'Unknown error')}"
        assert results.get('api_tools_count', 0) > 0, "No MCP tools found via API"


# CLI interface for standalone execution
async def main():
    """Main function for standalone execution."""
    import argparse
    
    parser = argparse.ArgumentParser(description='MCP Integration Test Suite')
    parser.add_argument('--url', default='http://127.0.0.1:8899', help='MCP Dashboard URL')
    parser.add_argument('--output', default='mcp_integration_test_results.json', help='Output file for results')
    parser.add_argument('--report', default='mcp_integration_test_report.md', help='Output file for report')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create test suite and run tests
    test_suite = MCPIntegrationTestSuite(base_url=args.url)
    results = await test_suite.run_comprehensive_tests()
    
    # Save results and generate report
    test_suite.save_results(results, args.output)
    
    report = test_suite.generate_report(results)
    with open(args.report, 'w') as f:
        f.write(report)
    
    print(f"✅ Test results saved to {args.output}")
    print(f"📝 Test report saved to {args.report}")
    
    # Exit with appropriate code
    exit_code = 0 if results.get('success', False) else 1
    print(f"🎯 Overall result: {'PASSED' if exit_code == 0 else 'FAILED'}")
    
    return exit_code


if __name__ == "__main__":
    exit_code = anyio.run(main())
    sys.exit(exit_code)