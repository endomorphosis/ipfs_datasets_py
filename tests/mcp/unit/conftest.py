"""
Test fixtures for MCP server unit tests.

Provides reusable fixtures for testing server functionality.
"""
import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from typing import Dict, Any


@pytest.fixture
def mock_configs():
    """Create mock server configuration."""
    mock_config = Mock()
    mock_config.log_level = "INFO"
    mock_config.max_workers = 4
    mock_config.timeout = 30
    mock_config.p2p_enabled = False
    mock_config.p2p_enable_tools = True
    mock_config.p2p_enable_cache = True
    mock_config.p2p_auth_mode = "mcp_token"
    mock_config.p2p_startup_timeout_s = 2.0
    mock_config.p2p_queue_path = ""
    mock_config.p2p_listen_port = None
    return mock_config


@pytest.fixture
def mock_mcp_server():
    """Create mock FastMCP server instance."""
    mock_server = MagicMock()
    mock_server.tool = Mock(side_effect=lambda: lambda f: f)  # Decorator passthrough
    mock_server.list_tools = AsyncMock(return_value=[])
    mock_server.call_tool = AsyncMock(return_value={"result": "success"})
    return mock_server


@pytest.fixture
def mock_tool_function():
    """Create a mock tool function."""
    async def mock_tool(param1: str, param2: int = 10) -> Dict[str, Any]:
        """Mock tool for testing."""
        return {"status": "success", "param1": param1, "param2": param2}
    
    mock_tool.__name__ = "mock_tool"
    mock_tool.__doc__ = "Mock tool for testing"
    return mock_tool


@pytest.fixture
def sample_tool_schema():
    """Create a sample tool schema for testing."""
    return {
        "name": "test_tool",
        "description": "A test tool",
        "input_schema": {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
                "count": {"type": "integer", "default": 1}
            },
            "required": ["input"]
        }
    }


@pytest.fixture
def mock_p2p_service():
    """Create mock P2P service manager."""
    mock_p2p = Mock()
    mock_p2p.enabled = True
    mock_p2p.is_running = True
    mock_p2p.workflow_scheduler = Mock()
    mock_p2p.task_queue = Mock()
    mock_p2p.peer_registry = Mock()
    return mock_p2p
