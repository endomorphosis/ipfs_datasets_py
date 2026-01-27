#!/usr/bin/env python3
"""
Simplified MCP Integration Test Suite

A focused integration test suite for validating MCP dashboard functionality
and basic endpoint availability.
"""

import anyio
import json
import pytest
import requests
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class SimpleMCPTestSuite:
    """Simplified test suite for MCP endpoints validation."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8899"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.timeout = 30
        self.test_results = {}
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def wait_for_dashboard(self, timeout: int = 60) -> bool:
        """Wait for MCP dashboard to be ready."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = self.session.get(f"{self.base_url}/api/mcp/status")
                if response.status_code == 200:
                    self.logger.info("✅ MCP Dashboard is ready")
                    return True
            except requests.RequestException:
                pass
            time.sleep(2)
        
        self.logger.error("❌ MCP Dashboard failed to start within timeout")
        return False
    
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
                }
                
                # Check if JSON response is valid for API endpoints
                if endpoint.startswith('/api/') and response.status_code == 200:
                    try:
                        data = response.json()
                        results[endpoint]['json_valid'] = True
                        results[endpoint]['data'] = data
                    except json.JSONDecodeError:
                        results[endpoint]['json_valid'] = False
                
                status = "✅" if response.status_code == 200 else "❌"
                self.logger.info(f"{status} {name}: {response.status_code}")
                
            except Exception as e:
                results[endpoint] = {
                    'name': name,
                    'success': False,
                    'error': str(e)
                }
                self.logger.error(f"❌ {name}: {e}")
        
        return results
    
    def test_mcp_tools_api(self) -> Dict[str, Any]:
        """Test MCP tools API endpoint."""
        try:
            response = self.session.get(f"{self.base_url}/api/mcp/tools")
            if response.status_code != 200:
                return {
                    'success': False,
                    'error': f'Tools API returned {response.status_code}'
                }
            
            tools_data = response.json()

            normalized_tools: Dict[str, Dict[str, Any]] = {}
            if isinstance(tools_data, dict):
                if tools_data and all(isinstance(value, list) for value in tools_data.values()):
                    for category, tools in tools_data.items():
                        for tool in tools:
                            if isinstance(tool, dict):
                                tool_name = tool.get('name') or tool.get('tool')
                                if tool_name:
                                    tool_info = dict(tool)
                                    tool_info.setdefault('category', category)
                                    normalized_tools[tool_name] = tool_info
                else:
                    normalized_tools = tools_data
            elif isinstance(tools_data, list):
                for tool in tools_data:
                    if isinstance(tool, dict):
                        tool_name = tool.get('name') or tool.get('tool')
                        if tool_name:
                            normalized_tools[tool_name] = tool

            # Analyze tools
            tools_by_category = {}
            for tool_name, tool_info in normalized_tools.items():
                category = tool_info.get('category', 'uncategorized')
                if category not in tools_by_category:
                    tools_by_category[category] = []
                tools_by_category[category].append(tool_name)
            
            self.logger.info(f"✅ Found {len(normalized_tools)} MCP tools")
            self.logger.info(f"📊 Categories: {list(tools_by_category.keys())}")
            
            return {
                'success': True,
                'tools_count': len(normalized_tools),
                'tools_by_category': tools_by_category,
                'sample_tools': dict(list(normalized_tools.items())[:5]),
                'categories': list(tools_by_category.keys())
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_status_endpoint(self) -> Dict[str, Any]:
        """Test MCP status endpoint specifically."""
        try:
            response = self.session.get(f"{self.base_url}/api/mcp/status")
            if response.status_code != 200:
                return {
                    'success': False,
                    'error': f'Status API returned {response.status_code}'
                }
            
            status_data = response.json()
            
            self.logger.info(f"✅ Status: {status_data.get('status', 'unknown')}")
            self.logger.info(f"📊 Tools available: {status_data.get('tools_available', 0)}")
            
            return {
                'success': True,
                'status': status_data.get('status'),
                'tools_available': status_data.get('tools_available', 0),
                'version': status_data.get('version'),
                'data': status_data
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def test_performance(self, iterations: int = 5) -> Dict[str, Any]:
        """Test basic performance of key endpoints."""
        endpoints = [
            '/api/mcp/status',
            '/api/mcp/tools'
        ]
        
        performance_results = {}
        
        for endpoint in endpoints:
            times = []
            errors = 0
            
            self.logger.info(f"⚡ Testing performance of {endpoint}...")
            
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
                avg_time = sum(times) / len(times)
                performance_results[endpoint] = {
                    'avg_response_time': avg_time,
                    'min_response_time': min(times),
                    'max_response_time': max(times),
                    'successful_requests': len(times),
                    'failed_requests': errors,
                    'success_rate': len(times) / iterations
                }
                
                self.logger.info(f"  📈 Average: {avg_time:.3f}s, Success rate: {len(times)/iterations*100:.1f}%")
            else:
                performance_results[endpoint] = {
                    'successful_requests': 0,
                    'failed_requests': errors,
                    'success_rate': 0
                }
                self.logger.warning(f"  ⚠️  All requests failed for {endpoint}")
        
        return performance_results
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all integration tests."""
        self.logger.info("🧪 Starting MCP integration tests")
        
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
        self.logger.info("🔍 Testing basic endpoints...")
        test_results['basic_endpoints'] = self.test_basic_endpoints()
        
        # Test status endpoint specifically
        self.logger.info("📊 Testing status endpoint...")
        test_results['status_endpoint'] = self.test_status_endpoint()
        
        # Test MCP tools API
        self.logger.info("🔧 Testing MCP tools API...")
        test_results['mcp_tools_api'] = self.test_mcp_tools_api()
        
        # Test performance
        self.logger.info("⚡ Testing performance...")
        test_results['performance'] = self.test_performance()
        
        # Determine overall success
        failed_tests = []
        for test_name, results in test_results.items():
            if isinstance(results, dict) and not results.get('success', True):
                failed_tests.append(test_name)
        
        test_results['success'] = len(failed_tests) == 0
        test_results['failed_tests'] = failed_tests
        
        # Summary
        if test_results['success']:
            self.logger.info("🎉 All tests passed!")
        else:
            self.logger.warning(f"⚠️  Some tests failed: {failed_tests}")
        
        return test_results
    
    def save_results(self, results: Dict[str, Any], output_file: str = "simple_mcp_test_results.json"):
        """Save test results to a file."""
        output_path = Path(output_file)
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        self.logger.info(f"💾 Test results saved to {output_path}")
    
    def generate_summary(self, results: Dict[str, Any]) -> str:
        """Generate a summary report."""
        lines = []
        lines.append("# MCP Integration Test Summary")
        lines.append(f"**Timestamp:** {time.ctime(results.get('timestamp', time.time()))}")
        lines.append(f"**Overall Result:** {'✅ PASSED' if results.get('success', False) else '❌ FAILED'}")
        lines.append("")
        
        # Basic endpoints
        if 'basic_endpoints' in results:
            lines.append("## Endpoints")
            for endpoint, data in results['basic_endpoints'].items():
                status = "✅" if data.get('success', False) else "❌"
                name = data.get('name', endpoint)
                code = data.get('status_code', 'Error')
                lines.append(f"- {status} **{name}**: {code}")
            lines.append("")
        
        # Status info
        if 'status_endpoint' in results and results['status_endpoint'].get('success'):
            status_data = results['status_endpoint']
            lines.append("## Dashboard Status")
            lines.append(f"- **Status**: {status_data.get('status', 'unknown')}")
            lines.append(f"- **Tools Available**: {status_data.get('tools_available', 0)}")
            lines.append(f"- **Version**: {status_data.get('version', 'unknown')}")
            lines.append("")
        
        # Tools info
        if 'mcp_tools_api' in results and results['mcp_tools_api'].get('success'):
            tools_data = results['mcp_tools_api']
            lines.append("## MCP Tools")
            lines.append(f"- **Total Tools**: {tools_data.get('tools_count', 0)}")
            lines.append(f"- **Categories**: {', '.join(tools_data.get('categories', []))}")
            lines.append("")
        
        # Performance
        if 'performance' in results:
            lines.append("## Performance")
            for endpoint, perf_data in results['performance'].items():
                avg_time = perf_data.get('avg_response_time', 0)
                success_rate = perf_data.get('success_rate', 0)
                lines.append(f"- **{endpoint}**: {avg_time:.3f}s avg, {success_rate*100:.1f}% success")
            lines.append("")
        
        return "\\n".join(lines)


# pytest integration
class TestSimpleMCPIntegration:
    """Pytest-compatible test class."""

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    @pytest.fixture(scope="class")
    def dashboard_base_url(self) -> str:
        """Start the MCP dashboard for this test class and return its base URL."""
        port = self._find_free_port()
        base_url = f"http://127.0.0.1:{port}"

        env = os.environ.copy()
        env["MCP_DASHBOARD_HOST"] = "127.0.0.1"
        env["MCP_DASHBOARD_PORT"] = str(port)
        env["MCP_DASHBOARD_BLOCKING"] = "1"

        proc = subprocess.Popen(
            [sys.executable, "-m", "ipfs_datasets_py.mcp_dashboard"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        suite = SimpleMCPTestSuite(base_url=base_url)
        if not suite.wait_for_dashboard(timeout=60):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            pytest.skip("MCP Dashboard could not be started in this environment")

        yield base_url

        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    
    @pytest.fixture(scope="class")
    def test_suite(self, dashboard_base_url):
        """Create test suite instance."""
        return SimpleMCPTestSuite(base_url=dashboard_base_url)
    
    def test_dashboard_availability(self, test_suite):
        """Test that dashboard is available."""
        assert test_suite.wait_for_dashboard(), "MCP Dashboard is not available"
    
    def test_basic_endpoints(self, test_suite):
        """Test basic endpoints."""
        if not test_suite.wait_for_dashboard():
            pytest.skip("MCP Dashboard not available")
        
        results = test_suite.test_basic_endpoints()
        
        # Check critical endpoints
        critical_endpoints = ['/api/mcp/status', '/']
        for endpoint in critical_endpoints:
            assert endpoint in results, f"Critical endpoint {endpoint} not tested"
            assert results[endpoint].get('success', False), f"Critical endpoint {endpoint} failed: {results[endpoint].get('error', 'Unknown error')}"
    
    def test_status_endpoint(self, test_suite):
        """Test status endpoint specifically."""
        if not test_suite.wait_for_dashboard():
            pytest.skip("MCP Dashboard not available")
        
        results = test_suite.test_status_endpoint()
        assert results.get('success', False), f"Status endpoint failed: {results.get('error', 'Unknown error')}"
        assert results.get('status') == 'running', f"Dashboard not running: {results.get('status')}"
    
    def test_tools_api(self, test_suite):
        """Test MCP tools API."""
        if not test_suite.wait_for_dashboard():
            pytest.skip("MCP Dashboard not available")
        
        results = test_suite.test_mcp_tools_api()
        assert results.get('success', False), f"Tools API failed: {results.get('error', 'Unknown error')}"
        # Note: tools_count might be 0 if no tools are loaded, which is okay for basic testing


# CLI interface
def main():
    """Main function for standalone execution."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Simple MCP Integration Test Suite')
    parser.add_argument('--url', default='http://127.0.0.1:8899', help='MCP Dashboard URL')
    parser.add_argument('--output', default='simple_mcp_test_results.json', help='Output file for results')
    parser.add_argument('--summary', default='simple_mcp_test_summary.md', help='Summary report file')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, 
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Create test suite and run tests
    test_suite = SimpleMCPTestSuite(base_url=args.url)
    results = test_suite.run_all_tests()
    
    # Save results
    test_suite.save_results(results, args.output)
    
    # Generate summary
    summary = test_suite.generate_summary(results)
    with open(args.summary, 'w') as f:
        f.write(summary)
    
    print(f"💾 Results saved to {args.output}")
    print(f"📝 Summary saved to {args.summary}")
    print(f"🎯 Overall result: {'PASSED' if results.get('success', False) else 'FAILED'}")
    
    # Exit with appropriate code
    return 0 if results.get('success', False) else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)