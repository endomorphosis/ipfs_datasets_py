"""
MOCK MODEL CONTEXT PROTOCOL PACKAGE FOR TESTING ONLY

This is a mock implementation of the modelcontextprotocol package that does not exist.
This mock is created solely for testing purposes and provides stub implementations
of the classes and methods that the codebase expects to import.

DO NOT USE THIS IN PRODUCTION - IT'S A TESTING MOCK ONLY
"""

from typing import Any, Dict, List, Optional, Union, Callable
import anyio
import logging

logger = logging.getLogger(__name__)


class MockMCPClientForTesting:
    """
    MOCK MCP CLIENT FOR TESTING ONLY - NOT A REAL IMPLEMENTATION
    
    This is a stub implementation that allows tests to run without 
    the actual modelcontextprotocol package.
    """
    
    def __init__(self, *args, **kwargs):
        self.connected = False
        self.tools = []
        logger.warning("Using MOCK MCP Client - this is for testing only!")
    
    async def connect(self):
        """Mock connect method"""
        self.connected = True
        return True
    
    async def disconnect(self):
        """Mock disconnect method"""
        self.connected = False
    
    async def list_tools(self):
        """Mock list_tools method"""
        return self.tools
    
    async def call_tool(self, name: str, arguments: Dict[str, Any] = None):
        """Mock call_tool method"""
        return {
            "result": f"Mock result for tool {name}",
            "success": True,
            "mock": True
        }


class MockFastMCPForTesting:
    """
    MOCK FAST MCP SERVER FOR TESTING ONLY - NOT A REAL IMPLEMENTATION
    
    This is a stub implementation that allows tests to run without 
    the actual modelcontextprotocol package.
    """
    
    def __init__(self, name: str = "mock_server"):
        self.name = name
        self.tools = {}
        self.running = False
        logger.warning("Using MOCK FastMCP Server - this is for testing only!")
    
    def tool(self, name: str = None):
        """Mock tool decorator"""
        def decorator(func: Callable):
            tool_name = name or func.__name__
            self.tools[tool_name] = func
            return func
        return decorator
    
    async def start(self):
        """Mock start method"""
        self.running = True
        logger.info(f"Mock MCP server '{self.name}' started (TESTING ONLY)")
    
    async def stop(self):
        """Mock stop method"""
        self.running = False
        logger.info(f"Mock MCP server '{self.name}' stopped")


# Mock the expected module structure
class MockModelContextProtocolClient:
    MCPClient = MockMCPClientForTesting


class MockModelContextProtocolServer:
    FastMCP = MockFastMCPForTesting


# Create the mock module structure that the imports expect
client = MockModelContextProtocolClient()
server = MockModelContextProtocolServer()
