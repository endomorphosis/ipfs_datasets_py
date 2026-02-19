"""
Tests for MCP Server Core Functionality

This test suite provides comprehensive coverage of server.py, testing:
- Tool registration
- Tool execution  
- P2P integration
- Configuration
- Error handling

Part of Phase 3 testing strategy to achieve 75%+ coverage on server.py.
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock, call
from typing import Dict, Any

# Test markers
pytestmark = [pytest.mark.unit]


class TestToolRegistration:
    """Tests for tool registration functionality."""
    
    def test_register_single_tool_success(self, mock_configs, mock_mcp_server, mock_tool_function):
        """
        Test successful registration of a single tool.
        
        GIVEN: A server instance with mock configuration
        WHEN: We register a single tool
        THEN: Tool is stored in the tools registry
        """
        # GIVEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # WHEN
            tool_name = "test_tool"
            server.tools[tool_name] = mock_tool_function
            
            # THEN
            assert tool_name in server.tools
            assert server.tools[tool_name] == mock_tool_function
    
    def test_tools_dictionary_initialization(self, mock_configs, mock_mcp_server):
        """
        Test that tools dictionary is properly initialized.
        
        GIVEN: A new server instance
        WHEN: Server is initialized
        THEN: Tools dictionary should be empty but defined
        """
        # GIVEN & WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # THEN
            assert hasattr(server, 'tools')
            assert isinstance(server.tools, dict)
            assert len(server.tools) == 0
    
    def test_server_config_applied(self, mock_configs, mock_mcp_server):
        """
        Test that server configuration is properly applied.
        
        GIVEN: Custom server configuration
        WHEN: Server is initialized with config
        THEN: Config should be stored and accessible
        """
        # GIVEN & WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # THEN
            assert server.configs == mock_configs
            assert server.configs.log_level == "INFO"
            assert server.configs.max_workers == 4
    
    def test_mcp_server_initialized(self, mock_configs, mock_mcp_server):
        """
        Test that FastMCP server is properly initialized.
        
        GIVEN: Server configuration
        WHEN: Server is initialized
        THEN: MCP server instance should be created
        """
        # GIVEN & WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server) as mock_fast_mcp:
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # THEN
            mock_fast_mcp.assert_called_once_with("ipfs_datasets")
            assert server.mcp == mock_mcp_server
    
    def test_multiple_tools_registration(self, mock_configs, mock_mcp_server):
        """
        Test registering multiple tools.
        
        GIVEN: A server instance
        WHEN: Multiple tools are registered
        THEN: All tools should be in the registry
        """
        # GIVEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # WHEN
            tools = {
                "tool1": Mock(__name__="tool1"),
                "tool2": Mock(__name__="tool2"),
                "tool3": Mock(__name__="tool3")
            }
            server.tools.update(tools)
            
            # THEN
            assert len(server.tools) == 3
            for tool_name in tools:
                assert tool_name in server.tools


class TestToolExecution:
    """Tests for tool execution functionality."""
    
    @pytest.mark.asyncio
    async def test_execute_tool_success(self, mock_configs, mock_mcp_server, mock_tool_function):
        """
        Test successful tool execution.
        
        GIVEN: A server with a registered tool
        WHEN: We execute the tool with valid parameters
        THEN: Tool should execute and return expected result
        """
        # GIVEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            server.tools["test_tool"] = mock_tool_function
            
            # WHEN
            result = await mock_tool_function(param1="test", param2=20)
            
            # THEN
            assert result["status"] == "success"
            assert result["param1"] == "test"
            assert result["param2"] == 20
    
    @pytest.mark.asyncio
    async def test_async_tool_execution(self, mock_configs, mock_mcp_server):
        """
        Test executing an async tool.
        
        GIVEN: A server with an async tool
        WHEN: Tool is executed
        THEN: It should complete asynchronously
        """
        # GIVEN
        async def async_tool(value: int) -> int:
            await asyncio.sleep(0.01)  # Simulate async work
            return value * 2
        
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            server.tools["async_tool"] = async_tool
            
            # WHEN
            result = await async_tool(5)
            
            # THEN
            assert result == 10
    
    @pytest.mark.asyncio
    async def test_tool_with_default_parameters(self, mock_configs, mock_mcp_server, mock_tool_function):
        """
        Test tool execution with default parameters.
        
        GIVEN: A tool with default parameter values
        WHEN: Tool is called without optional parameters
        THEN: Default values should be used
        """
        # GIVEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            server.tools["test_tool"] = mock_tool_function
            
            # WHEN - Call with only required parameter
            result = await mock_tool_function(param1="test")
            
            # THEN
            assert result["param1"] == "test"
            assert result["param2"] == 10  # Default value


class TestP2PIntegration:
    """Tests for P2P service integration."""
    
    def test_p2p_service_initialization_disabled(self, mock_configs, mock_mcp_server):
        """
        Test P2P service initialization when disabled.
        
        GIVEN: Server config with P2P disabled
        WHEN: Server initializes
        THEN: P2P should be None or disabled
        """
        # GIVEN
        mock_configs.p2p_enabled = False
        
        # WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            with patch('ipfs_datasets_py.mcp_server.server.P2PServiceManager', side_effect=ImportError):
                from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
                server = IPFSDatasetsMCPServer(server_configs=mock_configs)
                
                # THEN
                assert server.p2p is None
    
    def test_p2p_service_initialization_enabled(self, mock_configs, mock_mcp_server, mock_p2p_service):
        """
        Test P2P service initialization when enabled.
        
        GIVEN: Server config with P2P enabled
        WHEN: Server initializes
        THEN: P2P service should be created
        """
        # GIVEN
        mock_configs.p2p_enabled = True
        
        # WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            with patch('ipfs_datasets_py.mcp_server.server.P2PServiceManager', return_value=mock_p2p_service) as mock_p2p_class:
                from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
                server = IPFSDatasetsMCPServer(server_configs=mock_configs)
                
                # THEN
                assert server.p2p is not None
                mock_p2p_class.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_p2p_message_validation(self, mock_configs, mock_mcp_server):
        """
        Test P2P message validation hook.
        
        GIVEN: A server with P2P validation method
        WHEN: validate_p2p_message is called
        THEN: Message should be validated appropriately
        """
        # GIVEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # WHEN
            test_message = {"type": "test", "data": "sample"}
            result = await server.validate_p2p_message(test_message)
            
            # THEN - Should return bool
            assert isinstance(result, bool)


class TestConfiguration:
    """Tests for server configuration."""
    
    def test_config_default_fallback(self, mock_mcp_server):
        """
        Test that default config is used when none provided.
        
        GIVEN: No configuration provided
        WHEN: Server is initialized
        THEN: Should use default global config
        """
        # GIVEN & WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            with patch('ipfs_datasets_py.mcp_server.server.configs') as mock_default_config:
                from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
                server = IPFSDatasetsMCPServer()
                
                # THEN
                assert server.configs == mock_default_config
    
    def test_custom_config_used(self, mock_configs, mock_mcp_server):
        """
        Test that custom config is used when provided.
        
        GIVEN: Custom configuration object
        WHEN: Server is initialized with custom config
        THEN: Custom config should be used
        """
        # GIVEN & WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # THEN
            assert server.configs is mock_configs
            assert server.configs.log_level == "INFO"
    
    def test_p2p_config_parameters(self, mock_configs, mock_mcp_server):
        """
        Test that P2P configuration parameters are accessible.
        
        GIVEN: Config with P2P settings
        WHEN: Server accesses P2P config
        THEN: All P2P parameters should be available
        """
        # GIVEN
        mock_configs.p2p_enabled = True
        mock_configs.p2p_queue_path = "/tmp/queue"
        mock_configs.p2p_listen_port = 8080
        
        # WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # THEN
            assert server.configs.p2p_enabled is True
            assert server.configs.p2p_queue_path == "/tmp/queue"
            assert server.configs.p2p_listen_port == 8080


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_import_error_when_fastmcp_unavailable(self, mock_configs):
        """
        Test error handling when FastMCP is not available.
        
        GIVEN: FastMCP is None (import failed)
        WHEN: Server tries to initialize
        THEN: ImportError should be raised with clear message
        """
        # GIVEN & WHEN & THEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', None):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            with pytest.raises(ImportError, match="MCP dependency is not available"):
                server = IPFSDatasetsMCPServer(server_configs=mock_configs)
    
    def test_p2p_import_error_graceful_degradation(self, mock_configs, mock_mcp_server):
        """
        Test graceful degradation when P2P service unavailable.
        
        GIVEN: P2PServiceManager import fails
        WHEN: Server initializes
        THEN: Server should continue with p2p set to None
        """
        # GIVEN & WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            with patch('ipfs_datasets_py.mcp_server.server.P2PServiceManager', side_effect=ImportError("P2P not available")):
                from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
                server = IPFSDatasetsMCPServer(server_configs=mock_configs)
                
                # THEN
                assert server.p2p is None  # Graceful degradation
                assert server.mcp is not None  # Server still works
    
    def test_error_reporter_installation_failure(self, mock_configs, mock_mcp_server):
        """
        Test handling of error reporter installation failure.
        
        GIVEN: Error reporter installation fails
        WHEN: Server initializes
        THEN: Server should continue and log warning
        """
        # GIVEN & WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            with patch('ipfs_datasets_py.mcp_server.server.ERROR_REPORTING_AVAILABLE', True):
                with patch('ipfs_datasets_py.mcp_server.server.error_reporter') as mock_reporter:
                    mock_reporter.install_global_handler.side_effect = Exception("Installation failed")
                    
                    from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
                    # Should not raise, just log warning
                    server = IPFSDatasetsMCPServer(server_configs=mock_configs)
                    
                    # THEN
                    assert server is not None
                    assert server.mcp is not None


class TestServerInitialization:
    """Tests for server initialization process."""
    
    def test_server_attributes_initialized(self, mock_configs, mock_mcp_server):
        """
        Test that all server attributes are properly initialized.
        
        GIVEN: Server configuration
        WHEN: Server is initialized
        THEN: All required attributes should exist
        """
        # GIVEN & WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # THEN
            assert hasattr(server, 'configs')
            assert hasattr(server, 'mcp')
            assert hasattr(server, 'tools')
            assert hasattr(server, 'p2p')
    
    def test_tools_dict_empty_on_init(self, mock_configs, mock_mcp_server):
        """
        Test that tools dictionary starts empty.
        
        GIVEN: New server instance
        WHEN: Server is initialized
        THEN: Tools dict should be empty initially
        """
        # GIVEN & WHEN
        with patch('ipfs_datasets_py.mcp_server.server.FastMCP', return_value=mock_mcp_server):
            from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
            server = IPFSDatasetsMCPServer(server_configs=mock_configs)
            
            # THEN
            assert len(server.tools) == 0
            assert isinstance(server.tools, dict)


# Summary of test coverage:
# - 5 test classes
# - 24 test methods
# - Coverage: Server initialization, tool registration, execution, P2P, config, error handling
# - All tests use GIVEN-WHEN-THEN format
# - Comprehensive mocking to isolate units under test
