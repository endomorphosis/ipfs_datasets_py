#!/usr/bin/env python3
"""
MCP Dashboard Testing Utilities

This module provides utility functions and classes for testing the MCP dashboard,
including test data generation, mock services, and testing helpers.
"""

import anyio
import json
import random
import string
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from unittest.mock import Mock, AsyncMock

import pytest


class TestDataGenerator:
    """Generates test data for MCP dashboard testing."""
    
    @staticmethod
    def generate_tool_list() -> List[Dict[str, Any]]:
        """Generate mock tool list for testing."""
        tools = []
        categories = [
            "dataset_tools", "embedding_tools", "vector_tools", 
            "ipfs_tools", "analysis_tools", "monitoring_tools"
        ]
        
        for category in categories:
            for i in range(random.randint(2, 5)):
                tool = {
                    "name": f"{category}_tool_{i}",
                    "category": category,
                    "description": f"Test tool {i} for {category}",
                    "parameters": [
                        {
                            "name": "input_data",
                            "type": "string",
                            "required": True,
                            "description": "Input data for processing"
                        },
                        {
                            "name": "options",
                            "type": "object",
                            "required": False,
                            "description": "Optional parameters"
                        }
                    ],
                    "returns": {
                        "type": "object",
                        "description": "Tool execution result"
                    }
                }
                tools.append(tool)
        
        return tools
    
    @staticmethod
    def generate_execution_history() -> List[Dict[str, Any]]:
        """Generate mock execution history for testing."""
        history = []
        tools = TestDataGenerator.generate_tool_list()
        
        for i in range(random.randint(5, 15)):
            tool = random.choice(tools)
            execution = {
                "id": f"exec_{i}_{int(time.time())}",
                "tool_name": tool["name"],
                "category": tool["category"],
                "parameters": {
                    "input_data": f"test_input_{i}",
                    "options": {"test": True}
                },
                "status": random.choice(["completed", "running", "failed"]),
                "start_time": (datetime.now() - timedelta(hours=random.randint(1, 24))).isoformat(),
                "end_time": (datetime.now() - timedelta(hours=random.randint(0, 23))).isoformat(),
                "result": {
                    "success": True,
                    "data": f"result_data_{i}",
                    "metrics": {
                        "execution_time": random.uniform(0.1, 10.0),
                        "memory_usage": random.randint(100, 1000)
                    }
                }
            }
            history.append(execution)
        
        return sorted(history, key=lambda x: x["start_time"], reverse=True)
    
    @staticmethod
    def generate_server_status() -> Dict[str, Any]:
        """Generate mock server status for testing."""
        return {
            "status": "running",
            "uptime": random.randint(3600, 86400),
            "version": "1.0.0",
            "tools_available": random.randint(20, 35),
            "active_executions": random.randint(0, 5),
            "total_executions": random.randint(100, 1000),
            "performance": {
                "cpu_usage": random.uniform(10.0, 80.0),
                "memory_usage": random.uniform(200.0, 800.0),
                "disk_usage": random.uniform(50.0, 90.0)
            },
            "health_checks": {
                "database": "healthy",
                "ipfs": "healthy",
                "storage": "healthy"
            },
            "last_updated": datetime.now().isoformat()
        }


class MockMCPServer:
    """Mock MCP server for testing purposes."""
    
    def __init__(self, port: int = 8000):
        self.port = port
        self.tools = TestDataGenerator.generate_tool_list()
        self.history = TestDataGenerator.generate_execution_history()
        self.status = TestDataGenerator.generate_server_status()
        self.executions = {}
    
    async def start(self):
        """Start the mock server."""
        # In a real implementation, this would start an actual HTTP server
        pass
    
    async def stop(self):
        """Stop the mock server."""
        pass
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """Get available tools."""
        return self.tools
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        return self.status
    
    def get_history(self) -> List[Dict[str, Any]]:
        """Get execution history."""
        return self.history
    
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool (mock implementation)."""
        execution_id = f"exec_{int(time.time())}_{random.randint(1000, 9999)}"
        
        execution = {
            "id": execution_id,
            "tool_name": tool_name,
            "parameters": parameters,
            "status": "running",
            "start_time": datetime.now().isoformat()
        }
        
        self.executions[execution_id] = execution
        
        # Simulate execution completion after a delay
        asyncio.create_task(self._complete_execution(execution_id))
        
        return execution
    
    async def _complete_execution(self, execution_id: str):
        """Complete a mock execution after a delay."""
        await anyio.sleep(random.uniform(1.0, 5.0))
        
        if execution_id in self.executions:
            self.executions[execution_id].update({
                "status": "completed",
                "end_time": datetime.now().isoformat(),
                "result": {
                    "success": True,
                    "data": f"mock_result_{execution_id}",
                    "metrics": {
                        "execution_time": random.uniform(1.0, 5.0),
                        "memory_usage": random.randint(100, 500)
                    }
                }
            })


class TestEnvironmentManager:
    """Manages test environment setup and teardown."""
    
    def __init__(self, test_dir: Path = None):
        self.test_dir = test_dir or Path("test_outputs")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.mock_server = None
        self.cleanup_tasks = []
    
    async def setup_test_environment(self):
        """Set up the test environment."""
        # Create test directories
        (self.test_dir / "screenshots").mkdir(exist_ok=True)
        (self.test_dir / "logs").mkdir(exist_ok=True)
        (self.test_dir / "reports").mkdir(exist_ok=True)
        
        # Start mock server if needed
        self.mock_server = MockMCPServer()
        await self.mock_server.start()
        
        return self
    
    async def teardown_test_environment(self):
        """Clean up the test environment."""
        # Stop mock server
        if self.mock_server:
            await self.mock_server.stop()
        
        # Run cleanup tasks
        for cleanup_task in self.cleanup_tasks:
            try:
                if asyncio.iscoroutinefunction(cleanup_task):
                    await cleanup_task()
                else:
                    cleanup_task()
            except Exception as e:
                print(f"Cleanup task failed: {e}")
    
    def register_cleanup(self, cleanup_task):
        """Register a cleanup task to run during teardown."""
        self.cleanup_tasks.append(cleanup_task)
    
    def get_test_data_file(self, filename: str) -> Path:
        """Get path to a test data file."""
        return self.test_dir / filename


class BrowserTestHelpers:
    """Helper functions for browser testing with Playwright."""
    
    @staticmethod
    async def wait_for_element_with_timeout(page, selector: str, timeout: int = 10000):
        """Wait for an element to appear with a timeout."""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            return True
        except:
            return False
    
    @staticmethod
    async def safe_click(page, selector: str, timeout: int = 5000):
        """Safely click an element with error handling."""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            await page.click(selector)
            return True
        except Exception as e:
            print(f"Failed to click {selector}: {e}")
            return False
    
    @staticmethod
    async def safe_type(page, selector: str, text: str, timeout: int = 5000):
        """Safely type text into an element."""
        try:
            await page.wait_for_selector(selector, timeout=timeout)
            await page.fill(selector, text)
            return True
        except Exception as e:
            print(f"Failed to type into {selector}: {e}")
            return False
    
    @staticmethod
    async def get_element_text(page, selector: str, default: str = ""):
        """Get text content of an element safely."""
        try:
            element = await page.query_selector(selector)
            if element:
                return await element.text_content()
            return default
        except:
            return default
    
    @staticmethod
    async def take_comparison_screenshot(page, name: str, test_dir: Path):
        """Take a screenshot for visual comparison testing."""
        screenshot_path = test_dir / "screenshots" / f"{name}.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        return screenshot_path
    
    @staticmethod
    async def check_console_errors(page) -> List[str]:
        """Check for console errors on the page."""
        errors = []
        
        def handle_console(msg):
            if msg.type == "error":
                errors.append(msg.text)
        
        page.on("console", handle_console)
        await page.wait_for_timeout(1000)
        page.remove_listener("console", handle_console)
        
        return errors
    
    @staticmethod
    async def measure_page_performance(page, url: str) -> Dict[str, Any]:
        """Measure page load performance."""
        start_time = time.time()
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        load_time = time.time() - start_time
        
        # Get performance metrics from browser
        metrics = await page.evaluate("""
            () => {
                const performance = window.performance;
                const navigation = performance.getEntriesByType('navigation')[0];
                
                return {
                    loadEventEnd: navigation.loadEventEnd,
                    domContentLoadedEventEnd: navigation.domContentLoadedEventEnd,
                    connectTime: navigation.connectEnd - navigation.connectStart,
                    responseTime: navigation.responseEnd - navigation.requestStart,
                    renderTime: navigation.loadEventEnd - navigation.fetchStart
                };
            }
        """)
        
        return {
            "total_load_time": load_time,
            "browser_metrics": metrics,
            "url": url,
            "timestamp": datetime.now().isoformat()
        }


# Pytest fixtures for testing

@pytest.fixture(scope="session")
async def test_environment():
    """Set up and tear down test environment."""
    env = TestEnvironmentManager()
    await env.setup_test_environment()
    yield env
    await env.teardown_test_environment()


@pytest.fixture
def test_data_generator():
    """Provide test data generator."""
    return TestDataGenerator()


@pytest.fixture
async def mock_mcp_server():
    """Provide mock MCP server."""
    server = MockMCPServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def browser_helpers():
    """Provide browser testing helpers."""
    return BrowserTestHelpers()


# Test data constants
SAMPLE_TOOL_CATEGORIES = [
    "dataset_tools", "embedding_tools", "vector_tools", 
    "ipfs_tools", "analysis_tools", "monitoring_tools",
    "workflow_tools", "auth_tools", "cache_tools"
]

SAMPLE_API_ENDPOINTS = [
    "/api/mcp/status",
    "/api/mcp/tools", 
    "/api/mcp/history",
    "/api/mcp/health",
    "/static/js/mcp-sdk.js"
]

RESPONSIVE_VIEWPORTS = [
    {"width": 1920, "height": 1080, "name": "desktop_large"},
    {"width": 1366, "height": 768, "name": "desktop_medium"}, 
    {"width": 1024, "height": 768, "name": "tablet_landscape"},
    {"width": 768, "height": 1024, "name": "tablet_portrait"},
    {"width": 414, "height": 896, "name": "mobile_large"},
    {"width": 375, "height": 667, "name": "mobile_medium"},
    {"width": 320, "height": 568, "name": "mobile_small"}
]