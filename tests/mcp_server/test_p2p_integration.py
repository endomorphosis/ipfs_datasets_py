"""Integration tests for enhanced P2P service manager and registry adapter.

Tests the integration of MCP++ workflow scheduler, peer registry, and bootstrap
with the P2P service manager and registry adapter components.

Module: tests.mcp_server.test_p2p_integration
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from ipfs_datasets_py.mcp_server.p2p_service_manager import (
    P2PServiceManager,
    P2PServiceState,
)
from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import (
    P2PMCPRegistryAdapter,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
)
from ipfs_datasets_py.mcp_server import mcplusplus


class TestP2PServiceManagerIntegration:
    """Integration tests for P2P service manager with MCP++ features."""

    def test_service_manager_init_default(self):
        """Test service manager initialization with default settings."""
        # GIVEN: Default configuration
        # WHEN: Creating service manager
        manager = P2PServiceManager(enabled=False)

        # THEN: Manager is created with defaults
        assert manager is not None
        assert manager.enabled is False
        assert manager.enable_workflow_scheduler is True
        assert manager.enable_peer_registry is True
        assert manager.enable_bootstrap is True

    def test_service_manager_init_custom(self):
        """Test service manager initialization with custom settings."""
        # GIVEN: Custom configuration
        # WHEN: Creating service manager with custom settings
        manager = P2PServiceManager(
            enabled=True,
            queue_path="/custom/path",
            listen_port=5001,
            enable_workflow_scheduler=False,
            enable_peer_registry=False,
            enable_bootstrap=False,
        )

        # THEN: Custom settings are applied
        assert manager.enabled is True
        assert manager.queue_path == "/custom/path"
        assert manager.listen_port == 5001
        assert manager.enable_workflow_scheduler is False
        assert manager.enable_peer_registry is False
        assert manager.enable_bootstrap is False

    def test_service_manager_capabilities_without_mcplusplus(self):
        """Test capability reporting without MCP++ available."""
        # GIVEN: Service manager (MCP++ likely unavailable)
        manager = P2PServiceManager(enabled=False)

        # WHEN: Getting capabilities
        caps = manager.get_capabilities()

        # THEN: Capabilities reflect MCP++ availability
        assert "p2p_enabled" in caps
        assert "mcplusplus_available" in caps
        assert isinstance(caps["p2p_enabled"], bool)
        assert isinstance(caps["mcplusplus_available"], bool)

    def test_service_manager_has_advanced_features(self):
        """Test advanced features detection."""
        # GIVEN: Service manager
        manager = P2PServiceManager(enabled=False)

        # WHEN: Checking for advanced features
        has_features = manager.has_advanced_features()

        # THEN: Returns boolean
        assert isinstance(has_features, bool)

    def test_service_manager_get_workflow_scheduler(self):
        """Test workflow scheduler accessor."""
        # GIVEN: Service manager
        manager = P2PServiceManager(enabled=False)

        # WHEN: Getting workflow scheduler
        scheduler = manager.get_workflow_scheduler()

        # THEN: Returns None or scheduler instance
        # (None if MCP++ unavailable, scheduler if available)
        assert scheduler is None or hasattr(scheduler, "submit_workflow")

    def test_service_manager_get_peer_registry(self):
        """Test peer registry accessor."""
        # GIVEN: Service manager
        manager = P2PServiceManager(enabled=False)

        # WHEN: Getting peer registry
        registry = manager.get_peer_registry()

        # THEN: Returns None or registry instance
        assert registry is None or hasattr(registry, "discover_peers")

    def test_service_manager_bootstrap_nodes_config(self):
        """Test bootstrap nodes configuration."""
        # GIVEN: Custom bootstrap nodes
        bootstrap_nodes = [
            "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
            "/ip4/104.236.179.241/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM"
        ]

        # WHEN: Creating manager with bootstrap nodes
        manager = P2PServiceManager(
            enabled=False,
            bootstrap_nodes=bootstrap_nodes
        )

        # THEN: Bootstrap nodes are stored
        assert manager.bootstrap_nodes == bootstrap_nodes

    def test_service_manager_multiple_instances(self):
        """Test creating multiple service manager instances."""
        # GIVEN: Multiple configurations
        # WHEN: Creating multiple managers
        manager1 = P2PServiceManager(enabled=False, listen_port=4001)
        manager2 = P2PServiceManager(enabled=False, listen_port=4002)

        # THEN: Each instance is independent
        assert manager1.listen_port == 4001
        assert manager2.listen_port == 4002
        assert manager1 is not manager2

    @patch("ipfs_accelerate_py.p2p_tasks.service.get_local_service_state")
    @patch("ipfs_accelerate_py.p2p_tasks.service.list_known_peers")
    def test_state_reports_connected_peers(self, mock_list_peers, mock_state):
        """state() should report a best-effort connected peer count."""
        mock_state.return_value = {
            "running": True,
            "peer_id": "QmTestPeer",
            "listen_port": 4001,
            "started_at": 123.0,
        }
        mock_list_peers.return_value = [
            {"peer_id": "QmPeer1"},
            {"peer_id": "QmPeer2"},
            {"peer_id": "QmPeer3"},
        ]

        manager = P2PServiceManager(enabled=False)
        st = manager.state()
        assert st.connected_peers == 3


class TestP2PRegistryAdapterIntegration:
    """Integration tests for P2P registry adapter with service manager."""

    def test_registry_adapter_with_mock_server(self):
        """Test registry adapter with mock server."""
        # GIVEN: Mock server with tools
        server = MagicMock()
        server.tools = {
            "test_tool": lambda x: x,
            "async_tool": AsyncMock(),
        }

        # WHEN: Creating adapter
        adapter = P2PMCPRegistryAdapter(server)

        # THEN: Adapter works with server
        assert adapter is not None
        assert adapter.accelerate_instance is server

    def test_registry_adapter_tools_with_runtime_metadata(self):
        """Test registry adapter adds runtime metadata to tools."""
        # GIVEN: Mock server with tools
        server = MagicMock()
        
        def sync_tool(x):
            return x
        
        async def async_tool(x):
            return x
        
        server.tools = {
            "sync_tool": sync_tool,
            "async_tool": async_tool,
        }

        # WHEN: Creating adapter and getting tools
        adapter = P2PMCPRegistryAdapter(server)
        tools = adapter.tools

        # THEN: Tools have runtime metadata
        assert "sync_tool" in tools
        assert "async_tool" in tools
        assert "runtime" in tools["sync_tool"]
        assert "runtime_metadata" in tools["sync_tool"]
        assert "is_async" in tools["sync_tool"]["runtime_metadata"]
        assert "is_trio_native" in tools["sync_tool"]["runtime_metadata"]

    def test_registry_adapter_trio_tool_registration(self):
        """Test registering tools as Trio-native."""
        # GIVEN: Mock server with tools
        server = MagicMock()
        server.tools = {"test_tool": lambda x: x}
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Registering as Trio tool
        adapter.register_trio_tool("test_tool")
        tools = adapter.tools

        # THEN: Tool is marked as Trio-native
        assert tools["test_tool"]["runtime"] == RUNTIME_TRIO
        assert tools["test_tool"]["runtime_metadata"]["is_trio_native"] is True

    def test_registry_adapter_runtime_filtering(self):
        """Test filtering tools by runtime."""
        # GIVEN: Mock server with mixed tools
        server = MagicMock()
        server.tools = {
            "fastapi_tool": lambda x: x,
            "trio_tool": lambda x: x,
        }
        adapter = P2PMCPRegistryAdapter(server)
        adapter.register_trio_tool("trio_tool")

        # WHEN: Filtering by runtime
        trio_tools = adapter.get_trio_tools()
        fastapi_tools = adapter.get_fastapi_tools()

        # THEN: Tools are correctly filtered
        assert "trio_tool" in trio_tools
        assert "trio_tool" not in fastapi_tools
        assert "fastapi_tool" in fastapi_tools
        assert "fastapi_tool" not in trio_tools

    def test_registry_adapter_runtime_stats(self):
        """Test runtime statistics."""
        # GIVEN: Mock server with multiple tools
        server = MagicMock()
        server.tools = {
            "tool1": lambda x: x,
            "tool2": lambda x: x,
            "tool3": lambda x: x,
        }
        adapter = P2PMCPRegistryAdapter(server)
        adapter.register_trio_tool("tool1")
        adapter.register_trio_tool("tool2")

        # WHEN: Getting runtime stats
        stats = adapter.get_runtime_stats()

        # THEN: Stats are accurate
        assert stats["total_tools"] == 3
        assert stats["trio_tools"] == 2
        assert stats["fastapi_tools"] == 1


class TestEndToEndP2PIntegration:
    """End-to-end integration tests for P2P components."""

    def test_service_manager_and_adapter_integration(self):
        """Test service manager works with registry adapter."""
        # GIVEN: Service manager and mock server
        manager = P2PServiceManager(enabled=False)
        server = MagicMock()
        server.tools = {"test_tool": lambda x: x}

        # WHEN: Creating adapter with capabilities
        adapter = P2PMCPRegistryAdapter(server)
        tools = adapter.tools

        # THEN: Both components work together
        assert manager is not None
        assert adapter is not None
        assert "test_tool" in tools
        assert tools["test_tool"]["runtime"] in [RUNTIME_FASTAPI, RUNTIME_TRIO]

    def test_p2p_workflow_submission_simulation(self):
        """Test simulated P2P workflow submission."""
        # GIVEN: Service manager with workflow scheduler
        manager = P2PServiceManager(enabled=False)
        
        # WHEN: Attempting to get workflow scheduler
        scheduler = manager.get_workflow_scheduler()
        
        # THEN: Returns None if unavailable (graceful degradation)
        # or scheduler instance if available
        if scheduler is not None:
            # If MCP++ available, scheduler should have submit method
            assert hasattr(scheduler, "submit_workflow")
        else:
            # Graceful degradation - no exception raised
            assert scheduler is None

    def test_p2p_peer_discovery_simulation(self):
        """Test simulated P2P peer discovery."""
        # GIVEN: Service manager with peer registry
        manager = P2PServiceManager(enabled=False)
        
        # WHEN: Attempting to get peer registry
        registry = manager.get_peer_registry()
        
        # THEN: Returns None if unavailable or registry instance
        if registry is not None:
            # If MCP++ available, registry should have discovery method
            assert hasattr(registry, "discover_peers")
        else:
            # Graceful degradation
            assert registry is None

    def test_capability_consistency(self):
        """Test capability reporting is consistent."""
        # GIVEN: Service manager and capabilities
        manager = P2PServiceManager(enabled=False)
        
        # WHEN: Getting capabilities
        caps = manager.get_capabilities()
        has_advanced = manager.has_advanced_features()
        
        # THEN: Capabilities are consistent
        if has_advanced:
            # If has advanced features, MCP++ should be available
            assert caps["mcplusplus_available"] is True
        
        # Capabilities structure is always valid
        assert isinstance(caps, dict)
        assert "p2p_enabled" in caps
        assert "mcplusplus_available" in caps


class TestBackwardCompatibility:
    """Tests to ensure backward compatibility."""

    def test_p2p_service_manager_old_usage(self):
        """Test P2P service manager still works with old usage patterns."""
        # GIVEN: Old usage pattern (no new parameters)
        # WHEN: Creating manager with old parameters only
        manager = P2PServiceManager(
            enabled=False,
            queue_path="/tmp/queue"
        )

        # THEN: Manager works as before
        assert manager is not None
        assert manager.enabled is False
        assert manager.queue_path == "/tmp/queue"

    def test_registry_adapter_old_usage(self):
        """Test registry adapter still works with old usage patterns."""
        # GIVEN: Mock server
        server = MagicMock()
        server.tools = {"test_tool": lambda x: x}

        # WHEN: Creating adapter with old pattern
        adapter = P2PMCPRegistryAdapter(server)
        tools = adapter.tools

        # THEN: Old functionality still works
        assert "test_tool" in tools
        assert "function" in tools["test_tool"]
        assert "description" in tools["test_tool"]
        assert "input_schema" in tools["test_tool"]

    def test_no_breaking_changes_in_tool_format(self):
        """Test tool descriptor format is backward compatible."""
        # GIVEN: Mock server with tool
        server = MagicMock()
        server.tools = {"test_tool": lambda x: x}
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting tool descriptor
        tools = adapter.tools
        tool_desc = tools["test_tool"]

        # THEN: Old fields still exist
        assert "function" in tool_desc  # Old field
        assert "description" in tool_desc  # Old field
        assert "input_schema" in tool_desc  # Old field
        # New fields added non-intrusively
        assert "runtime" in tool_desc  # New field
        assert "runtime_metadata" in tool_desc  # New field


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    def test_service_manager_invalid_bootstrap_nodes(self):
        """Test service manager handles invalid bootstrap nodes gracefully."""
        # GIVEN: Invalid bootstrap nodes
        invalid_nodes = ["not-a-multiaddr", "another-invalid"]

        # WHEN: Creating manager with invalid nodes
        # THEN: Should not raise exception (graceful handling)
        manager = P2PServiceManager(
            enabled=False,
            bootstrap_nodes=invalid_nodes
        )
        assert manager is not None

    def test_registry_adapter_with_non_callable_tools(self):
        """Test registry adapter handles non-callable tools."""
        # GIVEN: Server with non-callable "tool"
        server = MagicMock()
        server.tools = {
            "real_tool": lambda x: x,
            "not_a_tool": "not callable",
        }

        # WHEN: Creating adapter
        adapter = P2PMCPRegistryAdapter(server)
        tools = adapter.tools

        # THEN: Only callable tools are included
        assert "real_tool" in tools
        assert "not_a_tool" not in tools

    def test_registry_adapter_with_no_tools(self):
        """Test registry adapter with server that has no tools."""
        # GIVEN: Server with no tools attribute
        server = MagicMock(spec=[])  # No tools attribute

        # WHEN: Creating adapter
        adapter = P2PMCPRegistryAdapter(server)
        tools = adapter.tools

        # THEN: Returns empty dict without error
        assert tools == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
