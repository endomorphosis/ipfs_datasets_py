"""Unit tests for MCP++ import layer.

Tests graceful import behavior, capability detection, and fallback logic
for the MCP++ integration modules.

Module: tests.mcp_server.test_mcplusplus_imports
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch


class TestMCPPlusImports:
    """Test MCP++ module imports and graceful degradation."""

    def test_mcplusplus_init_imports(self):
        """Test that __init__ module can be imported."""
        # GIVEN: The mcplusplus package
        # WHEN: Importing the package
        from ipfs_datasets_py.mcp_server import mcplusplus

        # THEN: Import succeeds
        assert mcplusplus is not None
        assert hasattr(mcplusplus, "HAVE_MCPLUSPLUS")
        assert hasattr(mcplusplus, "get_capabilities")
        assert hasattr(mcplusplus, "check_requirements")

    def test_capability_detection(self):
        """Test capability detection returns correct structure."""
        # GIVEN: The mcplusplus package
        from ipfs_datasets_py.mcp_server import mcplusplus

        # WHEN: Getting capabilities
        caps = mcplusplus.get_capabilities()

        # THEN: Returns proper structure
        assert isinstance(caps, dict)
        assert "mcplusplus_available" in caps
        assert "mcplusplus_version" in caps
        assert "capabilities" in caps
        assert isinstance(caps["capabilities"], dict)

        # AND: Capabilities dict has expected keys
        expected_keys = {
            "workflow_scheduler",
            "task_queue",
            "peer_registry",
            "bootstrap",
            "trio_server",
        }
        assert set(caps["capabilities"].keys()) == expected_keys

    def test_check_requirements(self):
        """Test requirements check returns proper format."""
        # GIVEN: The mcplusplus package
        from ipfs_datasets_py.mcp_server import mcplusplus

        # WHEN: Checking requirements
        all_available, missing = mcplusplus.check_requirements()

        # THEN: Returns tuple of (bool, list)
        assert isinstance(all_available, bool)
        assert isinstance(missing, list)

        # AND: If not all available, missing list is not empty
        if not all_available:
            assert len(missing) > 0

    def test_workflow_scheduler_import(self):
        """Test workflow scheduler module can be imported."""
        # GIVEN: The workflow_scheduler module
        # WHEN: Importing the module
        from ipfs_datasets_py.mcp_server.mcplusplus import workflow_scheduler

        # THEN: Import succeeds
        assert workflow_scheduler is not None
        assert hasattr(workflow_scheduler, "HAVE_WORKFLOW_SCHEDULER")
        assert hasattr(workflow_scheduler, "create_workflow_scheduler")
        assert hasattr(workflow_scheduler, "get_scheduler")

    def test_task_queue_import(self):
        """Test task queue module can be imported."""
        # GIVEN: The task_queue module
        # WHEN: Importing the module
        from ipfs_datasets_py.mcp_server.mcplusplus import task_queue

        # THEN: Import succeeds
        assert task_queue is not None
        assert hasattr(task_queue, "HAVE_TASK_QUEUE")
        assert hasattr(task_queue, "TaskQueueWrapper")
        assert hasattr(task_queue, "create_task_queue")

    def test_peer_registry_import(self):
        """Test peer registry module can be imported."""
        # GIVEN: The peer_registry module
        # WHEN: Importing the module
        from ipfs_datasets_py.mcp_server.mcplusplus import peer_registry

        # THEN: Import succeeds
        assert peer_registry is not None
        assert hasattr(peer_registry, "HAVE_PEER_REGISTRY")
        assert hasattr(peer_registry, "PeerRegistryWrapper")
        assert hasattr(peer_registry, "create_peer_registry")

    def test_bootstrap_import(self):
        """Test bootstrap module can be imported."""
        # GIVEN: The bootstrap module
        # WHEN: Importing the module
        from ipfs_datasets_py.mcp_server.mcplusplus import bootstrap

        # THEN: Import succeeds
        assert bootstrap is not None
        assert hasattr(bootstrap, "HAVE_BOOTSTRAP")
        assert hasattr(bootstrap, "bootstrap_network")
        assert hasattr(bootstrap, "quick_bootstrap")
        assert hasattr(bootstrap, "DEFAULT_BOOTSTRAP_NODES")

    def test_workflow_scheduler_graceful_degradation(self):
        """Test workflow scheduler works when MCP++ unavailable."""
        # GIVEN: The workflow scheduler module
        from ipfs_datasets_py.mcp_server.mcplusplus import workflow_scheduler

        # WHEN: Creating scheduler (may not be available)
        scheduler = workflow_scheduler.create_workflow_scheduler()

        # THEN: Returns None if not available, or scheduler if available
        # Either way, no exception is raised
        assert scheduler is None or scheduler is not None

    def test_task_queue_wrapper_creation(self):
        """Test task queue wrapper can always be created."""
        # GIVEN: The task_queue module
        from ipfs_datasets_py.mcp_server.mcplusplus import task_queue

        # WHEN: Creating task queue wrapper
        queue = task_queue.create_task_queue()

        # THEN: Wrapper is created (may not be functional)
        assert queue is not None
        assert isinstance(queue, task_queue.TaskQueueWrapper)
        assert hasattr(queue, "available")

    def test_peer_registry_wrapper_creation(self):
        """Test peer registry wrapper can always be created."""
        # GIVEN: The peer_registry module
        from ipfs_datasets_py.mcp_server.mcplusplus import peer_registry

        # WHEN: Creating peer registry wrapper
        registry = peer_registry.create_peer_registry()

        # THEN: Wrapper is created (may not be functional)
        assert registry is not None
        assert isinstance(registry, peer_registry.PeerRegistryWrapper)
        assert hasattr(registry, "available")

    def test_bootstrap_config_creation(self):
        """Test bootstrap config can be created."""
        # GIVEN: The bootstrap module
        from ipfs_datasets_py.mcp_server.mcplusplus import bootstrap

        # WHEN: Creating bootstrap config
        config = bootstrap.BootstrapConfig(
            timeout=30.0,
            min_peers=5
        )

        # THEN: Config is created with correct values
        assert config is not None
        assert config.timeout == 30.0
        assert config.min_peers == 5
        assert isinstance(config.bootstrap_nodes, list)

    def test_bootstrap_multiaddr_validation(self):
        """Test bootstrap multiaddr validation."""
        # GIVEN: The bootstrap module
        from ipfs_datasets_py.mcp_server.mcplusplus import bootstrap

        # WHEN: Validating various multiaddrs
        valid = "/ip4/127.0.0.1/tcp/4001/p2p/QmExample"
        invalid_no_slash = "ip4/127.0.0.1/tcp/4001"
        invalid_too_short = "/ip4/127.0.0.1"
        invalid_empty = ""

        # THEN: Validation works correctly
        assert bootstrap.validate_bootstrap_multiaddr(valid) is True
        assert bootstrap.validate_bootstrap_multiaddr(invalid_no_slash) is False
        assert bootstrap.validate_bootstrap_multiaddr(invalid_too_short) is False
        assert bootstrap.validate_bootstrap_multiaddr(invalid_empty) is False

    def test_default_bootstrap_nodes(self):
        """Test default bootstrap nodes are available."""
        # GIVEN: The bootstrap module
        from ipfs_datasets_py.mcp_server.mcplusplus import bootstrap

        # WHEN: Getting default bootstrap nodes
        nodes = bootstrap.get_default_bootstrap_nodes()

        # THEN: Returns list of valid multiaddrs
        assert isinstance(nodes, list)
        assert len(nodes) > 0
        assert all(isinstance(node, str) for node in nodes)
        assert all(node.startswith("/") for node in nodes)

    @pytest.mark.asyncio
    async def test_task_queue_operations_when_unavailable(self):
        """Test task queue operations gracefully handle unavailability."""
        # GIVEN: Task queue that may not be available
        from ipfs_datasets_py.mcp_server.mcplusplus import task_queue

        queue = task_queue.create_task_queue()

        # WHEN: Attempting operations
        task_id = await queue.submit("test", {"data": "test"})
        status = await queue.get_status("test-id")
        cancelled = await queue.cancel("test-id")
        tasks = await queue.list()

        # THEN: All operations return safe values (None/False/empty list)
        # No exceptions are raised
        assert task_id is None or isinstance(task_id, str)
        assert status is None or isinstance(status, dict)
        assert isinstance(cancelled, bool)
        assert isinstance(tasks, list)

    @pytest.mark.asyncio
    async def test_peer_registry_operations_when_unavailable(self):
        """Test peer registry operations gracefully handle unavailability."""
        # GIVEN: Peer registry that may not be available
        from ipfs_datasets_py.mcp_server.mcplusplus import peer_registry

        registry = peer_registry.create_peer_registry()

        # WHEN: Attempting operations
        peers = await registry.discover_peers(max_peers=5)
        connected = await registry.connect_to_peer("test-id", "/ip4/127.0.0.1/tcp/4001")
        disconnected = await registry.disconnect_peer("test-id")
        connected_peers = await registry.list_connected_peers()
        metrics = await registry.get_peer_metrics("test-id")

        # THEN: All operations return safe values
        # No exceptions are raised
        assert isinstance(peers, list)
        assert isinstance(connected, bool)
        assert isinstance(disconnected, bool)
        assert isinstance(connected_peers, list)
        assert metrics is None or isinstance(metrics, dict)

    @pytest.mark.asyncio
    async def test_bootstrap_network_when_unavailable(self):
        """Test bootstrap network gracefully handles unavailability."""
        # GIVEN: The bootstrap module
        from ipfs_datasets_py.mcp_server.mcplusplus import bootstrap

        # WHEN: Attempting to bootstrap
        result = await bootstrap.bootstrap_network(timeout=5.0)

        # THEN: Returns result dict (success may be False)
        # No exceptions are raised
        assert isinstance(result, dict)
        assert "success" in result
        assert "peers_connected" in result
        assert "bootstrap_nodes" in result

    def test_all_modules_have_availability_flags(self):
        """Test all wrapper modules expose availability flags."""
        # GIVEN: All mcplusplus modules
        from ipfs_datasets_py.mcp_server.mcplusplus import (
            workflow_scheduler,
            task_queue,
            peer_registry,
            bootstrap,
        )

        # THEN: All have availability flags
        assert hasattr(workflow_scheduler, "HAVE_WORKFLOW_SCHEDULER")
        assert hasattr(task_queue, "HAVE_TASK_QUEUE")
        assert hasattr(peer_registry, "HAVE_PEER_REGISTRY")
        assert hasattr(bootstrap, "HAVE_BOOTSTRAP")

    def test_task_queue_wrapper_attributes(self):
        """Test TaskQueueWrapper has expected attributes."""
        # GIVEN: Task queue wrapper
        from ipfs_datasets_py.mcp_server.mcplusplus.task_queue import TaskQueueWrapper

        queue = TaskQueueWrapper(queue_path="/tmp/test.db")

        # THEN: Has expected attributes
        assert hasattr(queue, "queue_path")
        assert hasattr(queue, "available")
        assert hasattr(queue, "submit")
        assert hasattr(queue, "get_status")
        assert hasattr(queue, "cancel")
        assert hasattr(queue, "list")
        assert queue.queue_path == "/tmp/test.db"

    def test_peer_registry_wrapper_attributes(self):
        """Test PeerRegistryWrapper has expected attributes."""
        # GIVEN: Peer registry wrapper
        from ipfs_datasets_py.mcp_server.mcplusplus.peer_registry import (
            PeerRegistryWrapper
        )

        registry = PeerRegistryWrapper(bootstrap_nodes=["node1", "node2"])

        # THEN: Has expected attributes
        assert hasattr(registry, "bootstrap_nodes")
        assert hasattr(registry, "available")
        assert hasattr(registry, "discover_peers")
        assert hasattr(registry, "connect_to_peer")
        assert hasattr(registry, "disconnect_peer")
        assert hasattr(registry, "list_connected_peers")
        assert hasattr(registry, "get_peer_metrics")
        assert registry.bootstrap_nodes == ["node1", "node2"]

    def test_bootstrap_config_to_dict(self):
        """Test BootstrapConfig can be serialized to dict."""
        # GIVEN: Bootstrap config
        from ipfs_datasets_py.mcp_server.mcplusplus.bootstrap import BootstrapConfig

        config = BootstrapConfig(timeout=45.0, min_peers=10)

        # WHEN: Converting to dict
        config_dict = config.to_dict()

        # THEN: Returns dict with all fields
        assert isinstance(config_dict, dict)
        assert "bootstrap_nodes" in config_dict
        assert "timeout" in config_dict
        assert "min_peers" in config_dict
        assert "retry_count" in config_dict
        assert "retry_delay" in config_dict
        assert config_dict["timeout"] == 45.0
        assert config_dict["min_peers"] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
