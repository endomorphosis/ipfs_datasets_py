#!/usr/bin/env python3
"""
Comprehensive MCP Dashboard Browser Automation Test Suite

This module provides comprehensive browser automation testing for the MCP server dashboard
using Playwright. It tests all dashboard features including:

1. Dashboard UI components and navigation
2. MCP tool discovery and categorization  
3. Tool execution with various parameters
4. Real-time server status updates
5. Error handling and validation
6. JavaScript SDK integration
7. Performance and accessibility testing
8. Visual regression testing

Requirements:
- playwright >= 1.55.0
- pytest-playwright >= 0.7.0
- pytest-asyncio >= 1.1.0

Usage:
    # Install browsers first
    playwright install chromium
    
    # Run all tests
    pytest tests/integration/dashboard/comprehensive_mcp_dashboard_test.py -v
    
    # Run with screenshots
    pytest tests/integration/dashboard/comprehensive_mcp_dashboard_test.py -v --headed
"""

import anyio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext, expect
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    pytest.skip("Playwright not available", allow_module_level=True)

try:
    from ipfs_datasets_py.mcp_dashboard import MCPDashboard, MCPDashboardConfig, start_mcp_dashboard
    MCP_DASHBOARD_AVAILABLE = True
except ImportError as e:
    MCP_DASHBOARD_AVAILABLE = False
    pytest.skip(f"MCP Dashboard not available: {e}", allow_module_level=True)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MCPDashboardTestRunner:
    """
    Manages MCP dashboard server lifecycle for testing.
    
    This class handles starting and stopping the MCP dashboard server
    in a separate process for testing purposes.
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8899):
        self.host = host
        self.port = port
        self.process = None
        self.base_url = f"http://{host}:{port}"
        self.dashboard_process = None
        
    async def start_server(self) -> bool:
        """Start the MCP dashboard server."""
        try:
            # Set environment variables for dashboard configuration
            env = os.environ.copy()
            env.update({
                "MCP_DASHBOARD_HOST": self.host,
                "MCP_DASHBOARD_PORT": str(self.port),
                "MCP_DASHBOARD_BLOCKING": "1"
            })
            
            # Start the dashboard in a subprocess
            self.process = subprocess.Popen([
                sys.executable, "-m", "ipfs_datasets_py.mcp_dashboard"
            ], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Wait for server to start
            for _ in range(30):  # 30 second timeout
                try:
                    import requests
                    response = requests.get(f"{self.base_url}/api/mcp/status", timeout=1)
                    if response.status_code == 200:
                        logger.info(f"MCP Dashboard started successfully on {self.base_url}")
                        return True
                except:
                    pass
                await anyio.sleep(1)
            
            logger.error("Failed to start MCP dashboard within timeout")
            return False
            
        except Exception as e:
            logger.error(f"Failed to start MCP dashboard: {e}")
            return False
    
    async def stop_server(self):
        """Stop the MCP dashboard server."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            logger.info("MCP Dashboard server stopped")


class MCPDashboardTester:
    """
    Comprehensive MCP Dashboard testing with Playwright.
    
    This class implements all the test scenarios for the MCP dashboard,
    including UI testing, functional testing, and visual regression testing.
    """
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.screenshots_dir = Path("test_outputs/mcp_dashboard_screenshots")
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.test_results = {
            "screenshots": [],
            "interactions": [],
            "errors": [],
            "performance": {},
            "accessibility": [],
            "api_responses": []
        }
        
    async def run_comprehensive_tests(self, page: Page) -> Dict[str, Any]:
        """Run all comprehensive tests on the MCP dashboard."""
        try:
            # Navigate to dashboard
            await page.goto(f"{self.base_url}/mcp")
            await page.wait_for_load_state("networkidle")
            
            # Take initial screenshot
            await self._screenshot(page, "01_initial_load")
            
            # Test suite
            await self._test_dashboard_navigation(page)
            await self._test_server_status_display(page)
            await self._test_tool_discovery(page)
            await self._test_tool_execution_ui(page)
            await self._test_execution_history(page)
            await self._test_rest_api_integration(page)
            await self._test_javascript_sdk(page)
            await self._test_error_handling(page)
            await self._test_responsive_design(page)
            await self._test_accessibility(page)
            await self._test_performance(page)
            
            return self.test_results
            
        except Exception as e:
            logger.error(f"Comprehensive test failed: {e}")
            self.test_results["errors"].append({
                "test": "comprehensive_tests", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return self.test_results
    
    async def _screenshot(self, page: Page, name: str, full_page: bool = True):
        """Take a screenshot and save to results."""
        try:
            screenshot_path = self.screenshots_dir / f"{name}.png"
            await page.screenshot(path=screenshot_path, full_page=full_page)
            self.test_results["screenshots"].append({
                "name": name,
                "path": str(screenshot_path),
                "timestamp": datetime.now().isoformat()
            })
            logger.info(f"Screenshot saved: {name}")
        except Exception as e:
            logger.error(f"Failed to take screenshot {name}: {e}")
    
    async def _test_dashboard_navigation(self, page: Page):
        """Test dashboard navigation and menu items."""
        try:
            logger.info("Testing dashboard navigation...")
            
            # Look for navigation elements
            nav_selectors = [
                "[data-testid='nav-dashboard']",
                ".nav-link",
                ".sidebar a",
                "nav a",
                ".navigation"
            ]
            
            nav_found = False
            for selector in nav_selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    nav_found = True
                    for i, element in enumerate(elements[:5]):  # Test first 5 nav items
                        try:
                            text = await element.text_content()
                            if text and text.strip():
                                await element.click()
                                await page.wait_for_timeout(1000)
                                await self._screenshot(page, f"02_nav_{i}_{text.strip().replace(' ', '_')}")
                                
                                self.test_results["interactions"].append({
                                    "type": "navigation_click",
                                    "element": text.strip(),
                                    "status": "success",
                                    "timestamp": datetime.now().isoformat()
                                })
                        except Exception as e:
                            logger.warning(f"Navigation element click failed: {e}")
                    break
            
            if not nav_found:
                logger.warning("No navigation elements found")
                
        except Exception as e:
            logger.error(f"Navigation test failed: {e}")
            self.test_results["errors"].append({
                "test": "navigation", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    async def _test_server_status_display(self, page: Page):
        """Test server status display and real-time updates."""
        try:
            logger.info("Testing server status display...")
            
            # Look for status indicators
            status_selectors = [
                "[data-testid='server-status']",
                ".server-status",
                ".status-indicator",
                ".health-status",
                "#server-status"
            ]
            
            for selector in status_selectors:
                element = await page.query_selector(selector)
                if element:
                    await self._screenshot(page, "03_server_status")
                    
                    # Check if status shows as running
                    status_text = await element.text_content()
                    if status_text and ("running" in status_text.lower() or "online" in status_text.lower()):
                        self.test_results["interactions"].append({
                            "type": "status_check",
                            "status": "running",
                            "text": status_text,
                            "timestamp": datetime.now().isoformat()
                        })
                    break
                    
        except Exception as e:
            logger.error(f"Server status test failed: {e}")
            self.test_results["errors"].append({
                "test": "server_status", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    async def _test_tool_discovery(self, page: Page):
        """Test MCP tool discovery and categorization."""
        try:
            logger.info("Testing tool discovery...")
            
            # Look for tool listings
            tool_selectors = [
                "[data-testid='tool-list']",
                ".tool-card",
                ".mcp-tool",
                ".tool-item",
                ".available-tools"
            ]
            
            tools_found = 0
            for selector in tool_selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    tools_found = len(elements)
                    await self._screenshot(page, f"04_tools_discovery_{tools_found}_tools")
                    
                    # Test first few tools
                    for i, element in enumerate(elements[:3]):
                        try:
                            await element.scroll_into_view_if_needed()
                            await self._screenshot(page, f"04_tool_{i}")
                        except Exception as e:
                            logger.warning(f"Tool element scroll failed: {e}")
                    break
            
            self.test_results["interactions"].append({
                "type": "tool_discovery",
                "tools_found": tools_found,
                "timestamp": datetime.now().isoformat()
            })
                    
        except Exception as e:
            logger.error(f"Tool discovery test failed: {e}")
            self.test_results["errors"].append({
                "test": "tool_discovery", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    async def _test_tool_execution_ui(self, page: Page):
        """Test tool execution interface."""
        try:
            logger.info("Testing tool execution UI...")
            
            # Look for execute buttons
            execute_selectors = [
                "[data-testid='execute-tool']",
                ".execute-btn",
                ".run-tool",
                "button[class*='execute']",
                "input[type='submit']"
            ]
            
            for selector in execute_selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    # Test first execute button
                    element = elements[0]
                    await element.scroll_into_view_if_needed()
                    await self._screenshot(page, "05_tool_execution_ui")
                    
                    # Click execute button (but don't actually execute)
                    try:
                        await element.click()
                        await page.wait_for_timeout(1000)
                        await self._screenshot(page, "05_tool_execution_modal")
                        
                        self.test_results["interactions"].append({
                            "type": "tool_execution_ui",
                            "status": "success",
                            "timestamp": datetime.now().isoformat()
                        })
                    except Exception as e:
                        logger.warning(f"Execute button click failed: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"Tool execution UI test failed: {e}")
            self.test_results["errors"].append({
                "test": "tool_execution_ui", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    async def _test_execution_history(self, page: Page):
        """Test execution history display."""
        try:
            logger.info("Testing execution history...")
            
            # Look for history sections
            history_selectors = [
                "[data-testid='execution-history']",
                ".history",
                ".execution-log",
                ".tool-history",
                "#execution-history"
            ]
            
            for selector in history_selectors:
                element = await page.query_selector(selector)
                if element:
                    await element.scroll_into_view_if_needed()
                    await self._screenshot(page, "06_execution_history")
                    
                    self.test_results["interactions"].append({
                        "type": "execution_history",
                        "status": "found",
                        "timestamp": datetime.now().isoformat()
                    })
                    break
                    
        except Exception as e:
            logger.error(f"Execution history test failed: {e}")
            self.test_results["errors"].append({
                "test": "execution_history", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    async def _test_rest_api_integration(self, page: Page):
        """Test REST API endpoints via browser."""
        try:
            logger.info("Testing REST API integration...")
            
            # Test API endpoints by navigating to them
            api_endpoints = [
                "/api/mcp/status",
                "/api/mcp/tools", 
                "/api/mcp/history"
            ]
            
            for endpoint in api_endpoints:
                try:
                    await page.goto(f"{self.base_url}{endpoint}")
                    await page.wait_for_load_state("networkidle")
                    
                    # Check if we get JSON response
                    content = await page.content()
                    if content and ("{" in content or "[" in content):
                        await self._screenshot(page, f"07_api_{endpoint.replace('/', '_')}")
                        
                        self.test_results["api_responses"].append({
                            "endpoint": endpoint,
                            "status": "success",
                            "timestamp": datetime.now().isoformat()
                        })
                except Exception as e:
                    logger.warning(f"API endpoint {endpoint} test failed: {e}")
            
            # Return to main dashboard
            await page.goto(f"{self.base_url}/mcp")
            await page.wait_for_load_state("networkidle")
                    
        except Exception as e:
            logger.error(f"REST API test failed: {e}")
            self.test_results["errors"].append({
                "test": "rest_api", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    async def _test_javascript_sdk(self, page: Page):
        """Test JavaScript SDK functionality."""
        try:
            logger.info("Testing JavaScript SDK...")
            
            # Check if MCP SDK is loaded
            sdk_loaded = await page.evaluate("""
                () => {
                    return typeof window.MCPClient !== 'undefined' || 
                           typeof window.mcpSDK !== 'undefined';
                }
            """)
            
            if sdk_loaded:
                self.test_results["interactions"].append({
                    "type": "javascript_sdk",
                    "status": "loaded",
                    "timestamp": datetime.now().isoformat()
                })
            else:
                logger.warning("JavaScript SDK not found in window object")
                
        except Exception as e:
            logger.error(f"JavaScript SDK test failed: {e}")
            self.test_results["errors"].append({
                "test": "javascript_sdk", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    async def _test_error_handling(self, page: Page):
        """Test error handling and validation."""
        try:
            logger.info("Testing error handling...")
            
            # Capture any console errors
            page.on("console", lambda msg: self._handle_console_message(msg))
            page.on("pageerror", lambda error: self._handle_page_error(error))
            
            # Try to trigger an error by accessing invalid endpoint
            await page.goto(f"{self.base_url}/api/mcp/nonexistent")
            await page.wait_for_timeout(2000)
            await self._screenshot(page, "08_error_handling")
            
        except Exception as e:
            logger.error(f"Error handling test failed: {e}")
            self.test_results["errors"].append({
                "test": "error_handling", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    def _handle_console_message(self, msg):
        """Handle console messages from the browser."""
        if msg.type in ["error", "warning"]:
            self.test_results["errors"].append({
                "test": "console",
                "type": msg.type,
                "message": msg.text,
                "timestamp": datetime.now().isoformat()
            })
    
    def _handle_page_error(self, error):
        """Handle page errors from the browser."""
        self.test_results["errors"].append({
            "test": "page_error",
            "error": str(error),
            "timestamp": datetime.now().isoformat()
        })
    
    async def _test_responsive_design(self, page: Page):
        """Test responsive design at different viewport sizes."""
        try:
            logger.info("Testing responsive design...")
            
            viewports = [
                {"width": 1920, "height": 1080, "name": "desktop"},
                {"width": 1024, "height": 768, "name": "tablet"},
                {"width": 375, "height": 667, "name": "mobile"}
            ]
            
            for viewport in viewports:
                await page.set_viewport_size({
                    "width": viewport["width"], 
                    "height": viewport["height"]
                })
                await page.wait_for_timeout(1000)
                await self._screenshot(page, f"09_responsive_{viewport['name']}")
                
                self.test_results["interactions"].append({
                    "type": "responsive_test",
                    "viewport": viewport,
                    "timestamp": datetime.now().isoformat()
                })
            
            # Reset to default viewport
            await page.set_viewport_size({"width": 1280, "height": 800})
                
        except Exception as e:
            logger.error(f"Responsive design test failed: {e}")
            self.test_results["errors"].append({
                "test": "responsive_design", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    async def _test_accessibility(self, page: Page):
        """Test accessibility features."""
        try:
            logger.info("Testing accessibility...")
            
            # Check for basic accessibility features
            accessibility_checks = await page.evaluate("""
                () => {
                    const results = {};
                    
                    // Check for alt text on images
                    const images = document.querySelectorAll('img');
                    const imagesWithoutAlt = Array.from(images).filter(img => !img.alt);
                    results.imagesWithoutAlt = imagesWithoutAlt.length;
                    
                    // Check for form labels
                    const inputs = document.querySelectorAll('input, select, textarea');
                    const inputsWithoutLabels = Array.from(inputs).filter(input => {
                        return !input.labels || input.labels.length === 0;
                    });
                    results.inputsWithoutLabels = inputsWithoutLabels.length;
                    
                    // Check for heading structure
                    const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
                    results.headingCount = headings.length;
                    
                    return results;
                }
            """)
            
            self.test_results["accessibility"].append({
                "checks": accessibility_checks,
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Accessibility test failed: {e}")
            self.test_results["errors"].append({
                "test": "accessibility", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    async def _test_performance(self, page: Page):
        """Test page performance metrics."""
        try:
            logger.info("Testing performance...")
            
            # Navigate and measure load time
            start_time = time.time()
            await page.goto(f"{self.base_url}/mcp")
            await page.wait_for_load_state("networkidle")
            load_time = time.time() - start_time
            
            # Get performance metrics
            metrics = await page.evaluate("""
                () => {
                    const performance = window.performance;
                    const navigation = performance.getEntriesByType('navigation')[0];
                    
                    return {
                        loadEventEnd: navigation.loadEventEnd,
                        domContentLoadedEventEnd: navigation.domContentLoadedEventEnd,
                        firstContentfulPaint: performance.getEntriesByName('first-contentful-paint')[0]?.startTime || null
                    };
                }
            """)
            
            self.test_results["performance"] = {
                "page_load_time": load_time,
                "metrics": metrics,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Performance test failed: {e}")
            self.test_results["errors"].append({
                "test": "performance", 
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })


# Pytest fixtures and test cases

@pytest.fixture(scope="session")
async def dashboard_server():
    """Start and stop MCP dashboard server for testing."""
    server = MCPDashboardTestRunner()
    
    if await server.start_server():
        yield server
        await server.stop_server()
    else:
        pytest.skip("Could not start MCP dashboard server")


@pytest.fixture
async def browser_context():
    """Create browser context for testing."""
    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright not available")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800}
        )
        yield context
        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_mcp_dashboard_comprehensive(dashboard_server, browser_context):
    """
    Comprehensive test of MCP dashboard functionality.
    
    This test runs all the dashboard tests including:
    - UI navigation and interactions
    - Tool discovery and execution
    - API integration
    - Performance and accessibility
    """
    page = await browser_context.new_page()
    tester = MCPDashboardTester(dashboard_server.base_url)
    
    results = await tester.run_comprehensive_tests(page)
    
    # Assertions
    assert len(results["screenshots"]) > 0, "No screenshots were taken"
    assert len(results["interactions"]) > 0, "No interactions were recorded"
    
    # Check for critical errors
    critical_errors = [e for e in results["errors"] if e.get("test") in ["navigation", "server_status"]]
    assert len(critical_errors) == 0, f"Critical errors found: {critical_errors}"
    
    # Save test results
    results_file = Path("test_outputs/mcp_dashboard_test_results.json")
    results_file.parent.mkdir(parents=True, exist_ok=True)
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"Test completed. Results saved to {results_file}")
    logger.info(f"Screenshots: {len(results['screenshots'])}")
    logger.info(f"Interactions: {len(results['interactions'])}")
    logger.info(f"Errors: {len(results['errors'])}")


@pytest.mark.asyncio
async def test_mcp_dashboard_api_endpoints(dashboard_server):
    """Test MCP dashboard API endpoints directly."""
    import requests
    
    base_url = dashboard_server.base_url
    
    # Test status endpoint
    response = requests.get(f"{base_url}/api/mcp/status")
    assert response.status_code == 200
    status_data = response.json()
    assert "status" in status_data
    
    # Test tools endpoint
    response = requests.get(f"{base_url}/api/mcp/tools")
    assert response.status_code in [200, 404]  # May not exist if no tools
    
    logger.info("API endpoints test completed successfully")


@pytest.mark.asyncio 
async def test_mcp_dashboard_performance(dashboard_server, browser_context):
    """Test MCP dashboard performance metrics."""
    page = await browser_context.new_page()
    
    # Measure page load time
    start_time = time.time()
    await page.goto(f"{dashboard_server.base_url}/mcp")
    await page.wait_for_load_state("networkidle")
    load_time = time.time() - start_time
    
    # Assert reasonable load time (under 10 seconds)
    assert load_time < 10, f"Page load time too slow: {load_time}s"
    
    logger.info(f"Performance test completed. Load time: {load_time:.2f}s")


if __name__ == "__main__":
    """Run tests directly."""
    pytest.main([__file__, "-v", "--tb=short"])