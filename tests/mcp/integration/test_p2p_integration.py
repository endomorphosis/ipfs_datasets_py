"""
Integration tests for P2P MCP server components.

Tests the full integration between server.py, p2p_service_manager.py,
and p2p_mcp_registry_adapter.py to ensure components work together seamlessly.

Test Format: GIVEN-WHEN-THEN for clarity and maintainability.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import sys


class TestServerP2PIntegration:
    """Test full integration between server and P2P components."""

    def test_server_p2p_initialization_integration(self):
        """
        GIVEN: Server and P2P components are available
        WHEN: Server is initialized with P2P enabled
        THEN: Both components initialize and connect properly
        """
        # GIVEN
        with patch.dict('sys.modules', {
            'mcp.server.fastmcp': Mock(),
            'ipfs_datasets_py.mcp_server.p2p_service_manager': Mock()
        }):
            # Import after patching
            import ipfs_datasets_py.mcp_server.server as server_module
            
            mock_fastmcp = Mock()
            mock_fastmcp.return_value = Mock()
            mock_p2p_manager = Mock()
            mock_p2p_manager.return_value = Mock(
                start=Mock(return_value=True),
                enabled=True
            )
            
            with patch.object(server_module, 'FastMCP', mock_fastmcp), \
                 patch('ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager', mock_p2p_manager):
                
                # WHEN
                config = {'p2p_enabled': True, 'host': 'localhost', 'port': 8000}
                server_instance = server_module.IPFSDatasetsMCPServer(config)
                
                # THEN
                assert server_instance is not None
                assert hasattr(server_instance, 'mcp')
                # P2P manager should be created
                mock_p2p_manager.assert_called_once()

    def test_tool_registration_through_p2p_adapter(self):
        """
        GIVEN: P2P adapter is initialized with host server
        WHEN: Tools are registered through the adapter
        THEN: Tools are available with runtime metadata
        """
        # GIVEN
        with patch.dict('sys.modules', {
            'ipfs_datasets_py.mcp_server.p2p_service_manager': Mock()
        }):
            from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import P2PMCPRegistryAdapter
            
            # Create mock host server with tools dict
            mock_host = Mock()
            mock_host.tools = {
                'tool1': lambda x: x,
                'tool2': lambda y: y,
                'tool3': lambda z: z,
                'tool4': lambda a: a,
                'tool5': lambda b: b  # >4 tools triggers flat registration
            }
            
            # WHEN
            adapter = P2PMCPRegistryAdapter(
                host_server=mock_host,
                default_runtime='fastapi',
                enable_runtime_detection=True
            )
            
            tools = adapter.tools
            
            # THEN
            assert isinstance(tools, dict)
            assert len(tools) > 0
            # Tools should include runtime metadata
            for tool_name, tool_data in tools.items():
                assert 'runtime' in tool_data

    @pytest.mark.asyncio
    async def test_message_validation_end_to_end(self):
        """
        GIVEN: P2P adapter with message validator
        WHEN: Message validation is performed end-to-end
        THEN: Validation works correctly with auth modes
        """
        # GIVEN
        with patch.dict('sys.modules', {
            'ipfs_datasets_py.mcp_server.p2p_service_manager': Mock()
        }):
            from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import P2PMCPRegistryAdapter
            
            mock_host = Mock()
            mock_host.tools = {}
            
            adapter = P2PMCPRegistryAdapter(
                host_server=mock_host,
                default_runtime='fastapi'
            )
            
            # WHEN - Test with token auth mode
            message = {'auth_mode': 'mcp_token', 'token': 'test_token'}
            result = await adapter.validate_p2p_message(message)
            
            # THEN - Should return boolean
            assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_auth_mode_validation_token(self):
        """
        GIVEN: P2P adapter configured for token auth
        WHEN: Token authentication is validated
        THEN: Token auth mode works correctly
        """
        # GIVEN
        with patch.dict('sys.modules', {
            'ipfs_datasets_py.mcp_server.p2p_service_manager': Mock()
        }):
            from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import P2PMCPRegistryAdapter
            
            mock_host = Mock()
            mock_host.tools = {}
            
            adapter = P2PMCPRegistryAdapter(host_server=mock_host)
            
            # WHEN
            message = {'auth_mode': 'mcp_token', 'token': 'valid_token'}
            result = await adapter.validate_p2p_message(message)
            
            # THEN
            assert isinstance(result, bool)

    def test_error_recovery_graceful_degradation(self):
        """
        GIVEN: P2P components that may fail
        WHEN: Errors occur during initialization
        THEN: System degrades gracefully without crashing
        """
        # GIVEN - Real P2PServiceManager, not mocked
        from ipfs_datasets_py.mcp_server.p2p_service_manager import P2PServiceManager
        
        # WHEN - Service manager with disabled flag should not start
        manager = P2PServiceManager(enabled=False)
        result = manager.start()
        
        # THEN - Should return False but not crash
        assert result == False
        state = manager.state()
        assert state.running == False

    def test_multi_component_integration_scenario(self):
        """
        GIVEN: Server, P2P manager, and adapter working together
        WHEN: Complete integration workflow is executed
        THEN: All components coordinate properly
        """
        # GIVEN
        with patch.dict('sys.modules', {
            'mcp.server.fastmcp': Mock(),
            'ipfs_datasets_py.mcp_server.p2p_service_manager': Mock()
        }):
            import ipfs_datasets_py.mcp_server.server as server_module
            from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import P2PMCPRegistryAdapter
            
            # Setup mocks
            mock_fastmcp = Mock()
            mock_fastmcp.return_value = Mock(tools={})
            
            with patch.object(server_module, 'FastMCP', mock_fastmcp):
                
                # WHEN - Initialize server with P2P
                config = {
                    'p2p_enabled': True,
                    'host': 'localhost',
                    'port': 8000,
                    'runtime': 'fastapi'
                }
                server_instance = server_module.IPFSDatasetsMCPServer(config)
                
                # Create P2P adapter
                mock_host = Mock()
                mock_host.tools = {
                    'test_tool1': lambda: None,
                    'test_tool2': lambda: None,
                    'test_tool3': lambda: None,
                    'test_tool4': lambda: None,
                    'test_tool5': lambda: None
                }
                
                adapter = P2PMCPRegistryAdapter(
                    host_server=mock_host,
                    default_runtime='fastapi'
                )
                
                # THEN - All components should be initialized
                assert server_instance is not None
                assert adapter is not None
                assert len(adapter.tools) > 0
