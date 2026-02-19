"""Comprehensive tests for P2P Service Manager.

Tests the P2PServiceManager class which integrates Trio/libp2p TaskQueue service
into the anyio-based MCP server runtime. Tests cover service lifecycle, environment
management, MCP++ feature initialization, and error handling.

Phase 3 Week 9: P2P Integration Testing
Target: 10-12 tests for complete P2PServiceManager coverage
"""

import os
import time
from unittest.mock import Mock, MagicMock, patch, PropertyMock
import pytest

# Import the module under test
from ipfs_datasets_py.mcp_server.p2p_service_manager import (
    P2PServiceManager,
    P2PServiceState,
    _DEFAULT_QUEUE_PATH,
)


class TestP2PServiceManagerInitialization:
    """Test P2PServiceManager initialization and configuration."""
    
    def test_init_with_default_values(self):
        """
        GIVEN: No parameters
        WHEN: Creating a P2PServiceManager
        THEN: Default values are applied correctly
        """
        # GIVEN / WHEN
        manager = P2PServiceManager(enabled=True)
        
        # THEN
        assert manager.enabled is True
        assert manager.queue_path == _DEFAULT_QUEUE_PATH
        assert manager.listen_port is None
        assert manager.enable_tools is True
        assert manager.enable_cache is True
        assert manager.auth_mode == "mcp_token"
        assert manager.startup_timeout_s == 2.0
        assert manager.enable_workflow_scheduler is True
        assert manager.enable_peer_registry is True
        assert manager.enable_bootstrap is True
        assert manager.bootstrap_nodes == []
    
    def test_init_with_custom_values(self):
        """
        GIVEN: Custom configuration parameters
        WHEN: Creating a P2PServiceManager
        THEN: Custom values are stored correctly
        """
        # GIVEN / WHEN
        manager = P2PServiceManager(
            enabled=False,
            queue_path="/custom/path.db",
            listen_port=5555,
            enable_tools=False,
            enable_cache=False,
            auth_mode="signature",
            startup_timeout_s=5.0,
            enable_workflow_scheduler=False,
            enable_peer_registry=False,
            enable_bootstrap=False,
            bootstrap_nodes=["node1", "node2"],
        )
        
        # THEN
        assert manager.enabled is False
        assert manager.queue_path == "/custom/path.db"
        assert manager.listen_port == 5555
        assert manager.enable_tools is False
        assert manager.enable_cache is False
        assert manager.auth_mode == "signature"
        assert manager.startup_timeout_s == 5.0
        assert manager.enable_workflow_scheduler is False
        assert manager.enable_peer_registry is False
        assert manager.enable_bootstrap is False
        assert manager.bootstrap_nodes == ["node1", "node2"]
    
    def test_init_type_coercion(self):
        """
        GIVEN: Parameters with wrong types (e.g., strings for bools)
        WHEN: Creating a P2PServiceManager
        THEN: Types are coerced correctly
        """
        # GIVEN / WHEN
        manager = P2PServiceManager(
            enabled="true",  # String instead of bool
            listen_port="8080",  # String instead of int
            startup_timeout_s="3",  # String instead of float
        )
        
        # THEN
        assert isinstance(manager.enabled, bool)
        assert isinstance(manager.listen_port, int)
        assert isinstance(manager.startup_timeout_s, float)
        assert manager.listen_port == 8080
        assert manager.startup_timeout_s == 3.0


class TestP2PServiceManagerEnvironment:
    """Test environment variable management."""
    
    def test_apply_env_sets_variables(self):
        """
        GIVEN: A P2PServiceManager with configuration
        WHEN: Calling _apply_env
        THEN: Environment variables are set correctly
        """
        # GIVEN
        manager = P2PServiceManager(
            enabled=True,
            queue_path="/test/queue.db",
            enable_tools=False,
            enable_cache=True,
            auth_mode="signature",
        )
        
        # Save original env
        orig_env = os.environ.copy()
        
        try:
            # WHEN
            manager._apply_env()
            
            # THEN
            assert os.environ.get("IPFS_ACCELERATE_PY_TASK_QUEUE_PATH") == "/test/queue.db"
            assert os.environ.get("IPFS_DATASETS_PY_TASK_QUEUE_PATH") == "/test/queue.db"
            assert os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_ENABLE_TOOLS") == "0"
            assert os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_ENABLE_CACHE") == "1"
            assert os.environ.get("IPFS_DATASETS_PY_TASK_P2P_ENABLE_CACHE") == "1"
            assert os.environ.get("IPFS_ACCELERATE_PY_MCP_P2P_SERVICE") == "1"
            assert os.environ.get("IPFS_DATASETS_PY_TASK_P2P_AUTH_MODE") == "signature"
            assert os.environ.get("IPFS_ACCELERATE_PY_TASK_P2P_AUTH_MODE") == "signature"
        finally:
            # Restore
            os.environ.clear()
            os.environ.update(orig_env)
    
    def test_restore_env_cleans_up(self):
        """
        GIVEN: Environment variables set by _apply_env
        WHEN: Calling _restore_env
        THEN: Variables are restored to original state
        """
        # GIVEN
        manager = P2PServiceManager(enabled=True, queue_path="/test.db")
        
        # Save original
        orig_queue_path = os.environ.get("IPFS_ACCELERATE_PY_TASK_QUEUE_PATH")
        
        manager._apply_env()
        assert os.environ.get("IPFS_ACCELERATE_PY_TASK_QUEUE_PATH") == "/test.db"
        
        # WHEN
        manager._restore_env()
        
        # THEN
        assert os.environ.get("IPFS_ACCELERATE_PY_TASK_QUEUE_PATH") == orig_queue_path


class TestP2PServiceManagerLifecycle:
    """Test service start/stop lifecycle."""
    
    def test_start_when_disabled(self):
        """
        GIVEN: A disabled P2PServiceManager
        WHEN: Calling start()
        THEN: Returns False without starting anything
        """
        # GIVEN
        manager = P2PServiceManager(enabled=False)
        
        # WHEN
        result = manager.start()
        
        # THEN
        assert result is False
        assert manager._runtime is None
    
    @patch('ipfs_datasets_py.mcp_server.p2p_service_manager._ensure_ipfs_accelerate_on_path')
    def test_start_when_import_fails(self, mock_ensure_path):
        """
        GIVEN: ipfs_accelerate_py import fails
        WHEN: Calling start()
        THEN: Returns False gracefully
        """
        # GIVEN
        manager = P2PServiceManager(enabled=True)
        
        # Mock import failure by patching at module level
        with patch.dict('sys.modules', {'ipfs_accelerate_py.p2p_tasks.runtime': None}):
            # WHEN
            result = manager.start()
        
        # THEN
        assert result is False
    
    @patch('ipfs_datasets_py.mcp_server.p2p_service_manager._ensure_ipfs_accelerate_on_path')
    def test_start_success(self, mock_ensure_path):
        """
        GIVEN: A properly configured P2PServiceManager
        WHEN: Calling start() with mocked runtime
        THEN: Service starts successfully
        """
        # GIVEN
        manager = P2PServiceManager(enabled=True, startup_timeout_s=0.1)
        
        # Create mock runtime
        mock_runtime = MagicMock()
        mock_runtime.running = True
        mock_handle = MagicMock()
        mock_handle.started = MagicMock()
        mock_runtime.start.return_value = mock_handle
        
        # Mock the TaskQueueP2PServiceRuntime import inside the try block
        mock_module = MagicMock()
        mock_module.TaskQueueP2PServiceRuntime.return_value = mock_runtime
        
        with patch.dict('sys.modules', {'ipfs_accelerate_py.p2p_tasks.runtime': mock_module}):
            # WHEN
            result = manager.start()
        
        # THEN
        assert result is True
        assert manager._runtime == mock_runtime
        mock_runtime.start.assert_called_once()
    
    def test_stop_without_runtime(self):
        """
        GIVEN: A P2PServiceManager that was never started
        WHEN: Calling stop()
        THEN: Returns True (nothing to stop)
        """
        # GIVEN
        manager = P2PServiceManager(enabled=True)
        
        # WHEN
        result = manager.stop()
        
        # THEN
        assert result is True
    
    def test_stop_with_running_runtime(self):
        """
        GIVEN: A running P2PServiceManager
        WHEN: Calling stop()
        THEN: Runtime is stopped and environment restored
        """
        # GIVEN
        manager = P2PServiceManager(enabled=True)
        mock_runtime = MagicMock()
        mock_runtime.stop.return_value = True
        manager._runtime = mock_runtime
        
        # Add some env variables to restore
        manager._env_restore = {"TEST_VAR": None}
        
        # WHEN
        result = manager.stop()
        
        # THEN
        assert result is True
        mock_runtime.stop.assert_called_once_with(timeout_s=2.0)
        assert len(manager._env_restore) == 0  # Should be cleared


class TestP2PServiceManagerState:
    """Test state reporting functionality."""
    
    @patch('ipfs_datasets_py.mcp_server.p2p_service_manager._ensure_ipfs_accelerate_on_path')
    def test_state_when_service_unavailable(self, mock_ensure_path):
        """
        GIVEN: P2P service import fails
        WHEN: Calling state()
        THEN: Returns fallback state with running=False
        """
        # GIVEN
        manager = P2PServiceManager(enabled=True)
        
        # WHEN
        with patch.dict('sys.modules', {'ipfs_accelerate_py.p2p_tasks.service': None}):
            state = manager.state()
        
        # THEN
        assert isinstance(state, P2PServiceState)
        assert state.running is False
        assert state.peer_id == ""
        assert state.listen_port is None
    
    @patch('ipfs_datasets_py.mcp_server.p2p_service_manager._ensure_ipfs_accelerate_on_path')
    def test_state_with_mock_service_data(self, mock_ensure_path):
        """
        GIVEN: A running P2P service with mock data
        WHEN: Calling state()
        THEN: Returns populated state from service
        """
        # GIVEN
        manager = P2PServiceManager(enabled=True)
        mock_runtime = MagicMock()
        mock_runtime.running = True
        mock_runtime.last_error = ""
        manager._runtime = mock_runtime
        
        # Mock service state
        mock_service_state = {
            "running": True,
            "peer_id": "QmTest123",
            "listen_port": 4001,
            "started_at": 1234567890.0,
        }
        
        # Mock the service module
        mock_service_module = MagicMock()
        mock_service_module.get_local_service_state.return_value = mock_service_state
        
        # WHEN
        with patch.dict('sys.modules', {'ipfs_accelerate_py.p2p_tasks.service': mock_service_module}):
            state = manager.state()
        
        # THEN
        assert state.running is True
        assert state.peer_id == "QmTest123"
        assert state.listen_port == 4001
        assert state.started_at == 1234567890.0
    
    def test_state_with_mcplusplus_features(self):
        """
        GIVEN: Manager with MCP++ features initialized
        WHEN: Calling state()
        THEN: State includes MCP++ availability flags
        """
        # GIVEN
        manager = P2PServiceManager(enabled=True)
        manager._workflow_scheduler = MagicMock()
        manager._peer_registry = MagicMock()
        manager._mcplusplus_available = True
        
        mock_runtime = MagicMock()
        mock_runtime.running = True
        manager._runtime = mock_runtime
        
        # Mock the service module
        mock_service_module = MagicMock()
        mock_service_module.get_local_service_state.return_value = {"running": True}
        
        # WHEN
        with patch.dict('sys.modules', {'ipfs_accelerate_py.p2p_tasks.service': mock_service_module}):
            with patch('ipfs_datasets_py.mcp_server.p2p_service_manager._ensure_ipfs_accelerate_on_path'):
                state = manager.state()
        
        # THEN
        assert state.workflow_scheduler_available is True
        assert state.peer_registry_available is True
        assert state.bootstrap_available is True


class TestP2PServiceManagerMCPPlusPlus:
    """Test MCP++ feature integration."""
    
    def test_mcplusplus_disabled_by_config(self):
        """
        GIVEN: Manager with MCP++ features disabled
        WHEN: Features would be initialized
        THEN: They remain None/unavailable
        """
        # GIVEN
        manager = P2PServiceManager(
            enabled=True,
            enable_workflow_scheduler=False,
            enable_peer_registry=False,
            enable_bootstrap=False,
        )
        
        # THEN
        assert manager.enable_workflow_scheduler is False
        assert manager.enable_peer_registry is False
        assert manager.enable_bootstrap is False
    
    def test_bootstrap_nodes_configuration(self):
        """
        GIVEN: Custom bootstrap nodes
        WHEN: Manager is initialized
        THEN: Bootstrap nodes are stored
        """
        # GIVEN / WHEN
        nodes = ["/ip4/1.2.3.4/tcp/4001/p2p/QmNode1", "/dns/node2.example.com/tcp/4001/p2p/QmNode2"]
        manager = P2PServiceManager(
            enabled=True,
            bootstrap_nodes=nodes,
        )
        
        # THEN
        assert manager.bootstrap_nodes == nodes
        assert len(manager.bootstrap_nodes) == 2


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
