"""
Tests for MCP Server Core Functionality

Comprehensive coverage of server.py testing tool registration,
execution, P2P integration, configuration, and error handling.

Part of Phase 3 testing strategy to achieve 75%+ coverage on server.py.
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Dict, Any

# Test markers
pytestmark = [pytest.mark.unit]


class TestServerInitialization:
    """Tests for server initialization."""
    
    def test_server_can_be_imported(self):
        """
        Test that server module can be imported.
        
        GIVEN: The server module exists
        WHEN: We import it
        THEN: Import should succeed
        """
        # GIVEN & WHEN & THEN
        from ipfs_datasets_py.mcp_server import server
        assert server is not None
    
    def test_ipfs_datasets_mcp_server_class_exists(self):
        """
        Test that IPFSDatasetsMCPServer class exists.
        
        GIVEN: The server module
        WHEN: We check for the class
        THEN: Class should exist
        """
        # GIVEN & WHEN
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        # THEN
        assert IPFSDatasetsMCPServer is not None
        assert callable(IPFSDatasetsMCPServer)
    
    def test_server_initialization_basic(self):
        """
        Test basic server initialization.
        
        GIVEN: Mocked FastMCP and P2P
        WHEN: Server is initialized
        THEN: Server should be created with required attributes
        """
        # GIVEN - Import first, then patch
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', side_effect=ImportError):
                    # WHEN
                    mock_fastmcp.return_value = MagicMock()
                    server = IPFSDatasetsMCPServer()
                    
                    # THEN
                    assert hasattr(server, 'tools')
                    assert hasattr(server, 'mcp')
                    assert hasattr(server, 'configs')
                    assert isinstance(server.tools, dict)
    
    def test_server_tools_dict_initialization(self):
        """
        Test that tools dictionary is properly initialized.
        
        GIVEN: A new server instance
        WHEN: Server is initialized
        THEN: Tools dict should be empty
        """
        # GIVEN - Import first, then patch
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', side_effect=ImportError):
                    # WHEN
                    mock_fastmcp.return_value = MagicMock()
                    server = IPFSDatasetsMCPServer()
                    
                    # THEN
                    assert len(server.tools) == 0


class TestToolManagement:
    """Tests for tool management functionality."""
    
    def test_add_tool_to_registry(self):
        """
        Test adding a tool to the registry.
        
        GIVEN: A server with empty tools
        WHEN: A tool is added
        THEN: Tool should appear in registry
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', side_effect=ImportError):
                    mock_fastmcp.return_value = MagicMock()
                    server = IPFSDatasetsMCPServer()
                    
                    # WHEN
                    def sample_tool():
                        return "result"
                    
                    server.tools["sample_tool"] = sample_tool
                    
                    # THEN
                    assert "sample_tool" in server.tools
                    assert server.tools["sample_tool"] == sample_tool
    
    def test_multiple_tools_registration(self):
        """
        Test registering multiple tools.
        
        GIVEN: A server instance
        WHEN: Multiple tools are added
        THEN: All should be in registry
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', side_effect=ImportError):
                    mock_fastmcp.return_value = MagicMock()
                    server = IPFSDatasetsMCPServer()
                    
                    # WHEN
                    tools = {
                        "tool1": lambda: "result1",
                        "tool2": lambda: "result2",
                        "tool3": lambda: "result3"
                    }
                    server.tools.update(tools)
                    
                    # THEN
                    assert len(server.tools) == 3
                    for name in tools:
                        assert name in server.tools


class TestConfiguration:
    """Tests for server configuration."""
    
    def test_custom_config_usage(self):
        """
        Test that custom configuration is used.
        
        GIVEN: Custom config object
        WHEN: Server is initialized with it
        THEN: Server should use custom config
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        custom_config = Mock()
        custom_config.p2p_enabled = False
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', side_effect=ImportError):
                    # WHEN
                    mock_fastmcp.return_value = MagicMock()
                    server = IPFSDatasetsMCPServer(server_configs=custom_config)
                    
                    # THEN
                    assert server.configs is custom_config
    
    def test_default_config_fallback(self):
        """
        Test that default config is used when none provided.
        
        GIVEN: No custom config
        WHEN: Server is initialized
        THEN: Default config should be used
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch.object(server_module, 'configs') as mock_default_config:
                    with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', side_effect=ImportError):
                        # WHEN
                        mock_fastmcp.return_value = MagicMock()
                        server = IPFSDatasetsMCPServer()
                        
                        # THEN
                        assert server.configs == mock_default_config


class TestP2PIntegration:
    """Tests for P2P service integration."""
    
    def test_p2p_disabled_when_import_fails(self):
        """
        Test P2P gracefully disabled when unavailable.
        
        GIVEN: P2P import fails
        WHEN: Server initializes
        THEN: p2p should be None
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', side_effect=ImportError):
                    # WHEN
                    mock_fastmcp.return_value = MagicMock()
                    server = IPFSDatasetsMCPServer()
                    
                    # THEN
                    assert server.p2p is None
    
    def test_p2p_initialized_when_available(self):
        """
        Test P2P initialization when available.
        
        GIVEN: P2P service is available
        WHEN: Server initializes with P2P enabled
        THEN: P2P should be initialized
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        custom_config = Mock()
        custom_config.p2p_enabled = True
        custom_config.p2p_queue_path = ""
        custom_config.p2p_listen_port = None
        custom_config.p2p_enable_tools = True
        custom_config.p2p_enable_cache = True
        custom_config.p2p_auth_mode = "mcp_token"
        custom_config.p2p_startup_timeout_s = 2.0
        
        mock_p2p_instance = Mock()
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', return_value=mock_p2p_instance) as mock_p2p_manager:
                    # WHEN
                    mock_fastmcp.return_value = MagicMock()
                    server = IPFSDatasetsMCPServer(server_configs=custom_config)
                    
                    # THEN
                    assert server.p2p == mock_p2p_instance
                    mock_p2p_manager.assert_called_once()


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_fastmcp_none_raises_import_error(self):
        """
        Test that FastMCP None raises ImportError.
        
        GIVEN: FastMCP is None
        WHEN: Server tries to initialize
        THEN: ImportError should be raised
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        with patch.object(server_module, 'FastMCP', None):
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                # WHEN & THEN
                with pytest.raises(ImportError, match="MCP dependency is not available"):
                    server = IPFSDatasetsMCPServer()
    
    def test_p2p_exception_handled_gracefully(self):
        """
        Test that P2P exceptions are handled gracefully.
        
        GIVEN: P2P raises exception during init
        WHEN: Server initializes
        THEN: Server continues with p2p=None
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', side_effect=Exception("P2P error")):
                    # WHEN
                    mock_fastmcp.return_value = MagicMock()
                    server = IPFSDatasetsMCPServer()
                    
                    # THEN
                    assert server.p2p is None
                    assert server.mcp is not None  # Server still functional


class TestAsyncFunctionality:
    """Tests for async functionality."""
    
    @pytest.mark.asyncio
    async def test_validate_p2p_message_exists(self):
        """
        Test that validate_p2p_message method exists.
        
        GIVEN: A server instance
        WHEN: We call validate_p2p_message
        THEN: Method should exist and be callable
        """
        # GIVEN
        from ipfs_datasets_py.mcp_server import server as server_module
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        
        with patch.object(server_module, 'FastMCP') as mock_fastmcp:
            with patch.object(server_module, 'ERROR_REPORTING_AVAILABLE', False):
                with patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', side_effect=ImportError):
                    mock_fastmcp.return_value = MagicMock()
                    server = IPFSDatasetsMCPServer()
                    
                    # WHEN & THEN
                    assert hasattr(server, 'validate_p2p_message')
                    assert callable(server.validate_p2p_message)
                    
                    # Try calling it
                    result = await server.validate_p2p_message({"test": "message"})
                    assert isinstance(result, bool)


# Summary:
# - 6 test classes with 13 test methods
# - Tests cover: initialization, tool management, configuration, P2P, error handling, async
# - All use GIVEN-WHEN-THEN format
# - Comprehensive mocking to isolate units
# - Phase 3 Week 7 progress: 13/40-50 tests implemented (26-32%)
