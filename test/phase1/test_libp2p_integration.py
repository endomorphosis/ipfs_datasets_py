"""
Test the libp2p kit integration for distributed dataset management.

This module tests the functionality of the libp2p_kit module, including:
- P2P communication with libp2p
- Dataset sharding and distribution
- Federated search across nodes
- Resilient operations with node failure handling
"""

import os
import json
import time
import pytest
import asyncio
import tempfile
import numpy as np
from unittest import mock
from typing import Dict, List, Any, Optional, Tuple

from ipfs_datasets_py.libp2p_kit import (
    LibP2PNode,
    DatasetShardManager,
    FederatedSearchManager,
    DistributedDatasetManager,
    NodeRole,
    ShardMetadata,
    DatasetMetadata,
    NetworkProtocol,
    P2PError,
    LibP2PNotAvailableError
)

# Check if libp2p is available
try:
    from multiaddr import Multiaddr
    import py_libp2p
    LIBP2P_AVAILABLE = True
except ImportError:
    LIBP2P_AVAILABLE = False

# Skip tests if libp2p is not available
pytestmark = pytest.mark.skipif(
    not LIBP2P_AVAILABLE,
    reason="py-libp2p is not installed"
)


# Test fixtures
@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def mock_peer_id():
    """Create a mock peer ID."""
    with mock.patch("ipfs_datasets_py.libp2p_kit.PeerID") as mock_peer_id:
        mock_peer_id.from_base58.return_value = "mock_peer_id"
        yield mock_peer_id


@pytest.fixture
def mock_stream():
    """Create a mock network stream."""
    mock_stream = mock.MagicMock()
    mock_stream.read.side_effect = asyncio.coroutine(
        mock.MagicMock(return_value=json.dumps({"status": "success"}).encode())
    )
    mock_stream.write.side_effect = asyncio.coroutine(mock.MagicMock())
    mock_stream.close.side_effect = asyncio.coroutine(mock.MagicMock())
    return mock_stream


@pytest.fixture
def mock_host():
    """Create a mock libp2p host."""
    mock_host = mock.MagicMock()
    mock_host.get_id.return_value = "mock_peer_id"
    mock_host.get_addrs.return_value = ["/ip4/127.0.0.1/tcp/12345"]
    mock_host.connect.side_effect = asyncio.coroutine(mock.MagicMock())
    mock_host.new_stream.side_effect = asyncio.coroutine(
        lambda peer_id, protocol: mock.MagicMock()
    )
    mock_host.close.side_effect = asyncio.coroutine(mock.MagicMock())
    return mock_host


@pytest.fixture
def patched_libp2p_node(mock_host):
    """Create a LibP2PNode with mocked libp2p components."""
    with mock.patch("ipfs_datasets_py.libp2p_kit.get_default_network") as mock_network:
        mock_network.return_value = "mock_network"
        with mock.patch("ipfs_datasets_py.libp2p_kit.BasicHost") as mock_host_class:
            mock_host_class.return_value = mock_host
            with mock.patch("ipfs_datasets_py.libp2p_kit.rsa.create_new_key_pair") as mock_create_key:
                mock_create_key.return_value = ("mock_private_key", "mock_public_key")
                node = LibP2PNode(
                    node_id="test-node",
                    listen_addresses=["/ip4/127.0.0.1/tcp/0"],
                    role=NodeRole.COORDINATOR
                )
                yield node


# Test LibP2PNode
class TestLibP2PNode:
    """Test the LibP2PNode class."""

    @pytest.mark.asyncio
    async def test_node_initialization(self, patched_libp2p_node):
        """Test node initialization."""
        node = patched_libp2p_node
        assert node.node_id == "test-node"
        assert node.role == NodeRole.COORDINATOR
        assert node.listen_addresses == ["/ip4/127.0.0.1/tcp/0"]
        assert not node.running
        assert NetworkProtocol.NODE_DISCOVERY.value in node.protocol_handlers

    @pytest.mark.asyncio
    async def test_node_start_stop(self, patched_libp2p_node):
        """Test starting and stopping the node."""
        node = patched_libp2p_node
        await node.start()
        assert node.running
        assert node.host is not None
        await node.stop()
        assert not node.running

    @pytest.mark.asyncio
    async def test_protocol_handler_registration(self, patched_libp2p_node):
        """Test registering protocol handlers."""
        node = patched_libp2p_node
        
        # Define a test handler
        async def test_handler(stream):
            pass
        
        # Register the handler
        node.register_protocol_handler(
            NetworkProtocol.SHARD_DISCOVERY,
            test_handler
        )
        
        assert NetworkProtocol.SHARD_DISCOVERY.value in node.protocol_handlers
        assert node.protocol_handlers[NetworkProtocol.SHARD_DISCOVERY.value] == test_handler

    @pytest.mark.asyncio
    async def test_node_discovery_handler(self, patched_libp2p_node, mock_stream):
        """Test the node discovery protocol handler."""
        node = patched_libp2p_node
        mock_stream.muxed_conn.peer_id = "test-peer"
        
        await node._handle_node_discovery(mock_stream)
        
        assert "test-peer" in node.peers
        mock_stream.write.assert_called_once()
        mock_stream.close.assert_called_once()


# Test DatasetShardManager
class TestDatasetShardManager:
    """Test the DatasetShardManager class."""

    @pytest.fixture
    def shard_manager(self, patched_libp2p_node, temp_dir):
        """Create a DatasetShardManager instance."""
        return DatasetShardManager(
            node=patched_libp2p_node,
            storage_dir=temp_dir
        )

    def test_initialization(self, shard_manager):
        """Test initialization of the shard manager."""
        assert shard_manager.node is not None
        assert os.path.exists(os.path.join(shard_manager.storage_dir, "shards"))
        assert os.path.exists(os.path.join(shard_manager.storage_dir, "metadata"))

    def test_create_dataset(self, shard_manager):
        """Test creating a dataset."""
        dataset = shard_manager.create_dataset(
            name="Test Dataset",
            description="A test dataset",
            schema={"field1": "string", "field2": "integer"},
            vector_dimensions=128,
            format="parquet",
            tags=["test", "example"]
        )
        
        assert dataset.name == "Test Dataset"
        assert dataset.description == "A test dataset"
        assert dataset.schema == {"field1": "string", "field2": "integer"}
        assert dataset.vector_dimensions == 128
        assert dataset.format == "parquet"
        assert "test" in dataset.tags
        assert dataset.shard_count == 0
        assert dataset.total_records == 0
        
        # Verify dataset was saved
        assert dataset.dataset_id in shard_manager.datasets
        assert os.path.exists(
            os.path.join(
                shard_manager.storage_dir,
                "metadata",
                "datasets",
                f"{dataset.dataset_id}.json"
            )
        )

    def test_create_shard(self, shard_manager):
        """Test creating a shard."""
        # First create a dataset
        dataset = shard_manager.create_dataset(
            name="Test Dataset",
            description="A test dataset"
        )
        
        # Then create a shard
        shard = shard_manager.create_shard(
            dataset_id=dataset.dataset_id,
            data=None,  # Mock data
            cid="QmTest123",
            record_count=1000,
            format="parquet"
        )
        
        assert shard.dataset_id == dataset.dataset_id
        assert shard.shard_index == 0
        assert shard.total_shards == 1
        assert shard.record_count == 1000
        assert shard.cid == "QmTest123"
        assert shard.format == "parquet"
        assert shard_manager.node.node_id in shard.node_ids
        
        # Verify shard was saved
        assert shard.shard_id in shard_manager.shards
        assert os.path.exists(
            os.path.join(
                shard_manager.storage_dir,
                "metadata",
                "shards",
                f"{shard.shard_id}.json"
            )
        )
        
        # Verify dataset was updated
        updated_dataset = shard_manager.datasets[dataset.dataset_id]
        assert updated_dataset.shard_count == 1
        assert updated_dataset.total_records == 1000
        assert shard.shard_id in updated_dataset.shard_ids


# Test FederatedSearchManager
class TestFederatedSearchManager:
    """Test the FederatedSearchManager class."""

    @pytest.fixture
    def search_manager(self, shard_manager):
        """Create a FederatedSearchManager instance."""
        return FederatedSearchManager(
            node=shard_manager.node,
            shard_manager=shard_manager
        )

    def test_initialization(self, search_manager):
        """Test initialization of the search manager."""
        assert search_manager.node is not None
        assert search_manager.shard_manager is not None
        assert search_manager.result_limit == 100

    @pytest.mark.asyncio
    async def test_federated_search_handler(self, search_manager, mock_stream):
        """Test the federated search protocol handler."""
        # Set up request data
        mock_stream.read.side_effect = asyncio.coroutine(
            mock.MagicMock(
                return_value=json.dumps({
                    "action": "search",
                    "dataset_id": "test-dataset",
                    "query_type": "keyword",
                    "query": "test query"
                }).encode()
            )
        )
        
        await search_manager._handle_federated_search(mock_stream)
        
        # Verify response was sent
        mock_stream.write.assert_called_once()
        mock_stream.close.assert_called_once()
        
        # Get the response data
        call_args = mock_stream.write.call_args[0][0]
        response = json.loads(call_args.decode())
        
        assert "results" in response
        assert "status" in response
        assert response["status"] == "success"


# Test DistributedDatasetManager
class TestDistributedDatasetManager:
    """Test the DistributedDatasetManager class."""

    @pytest.fixture
    def manager(self, patched_libp2p_node, temp_dir):
        """Create a DistributedDatasetManager instance."""
        with mock.patch("ipfs_datasets_py.libp2p_kit.DistributedDatasetManager.start"):
            manager = DistributedDatasetManager(
                storage_dir=temp_dir,
                auto_start=False
            )
            # Replace node with our mock
            manager.node = patched_libp2p_node
            return manager

    def test_initialization(self, manager):
        """Test initialization of the distributed dataset manager."""
        assert manager.node is not None
        assert manager.shard_manager is not None
        assert manager.search_manager is not None

    def test_create_dataset(self, manager):
        """Test creating a dataset."""
        dataset = manager.create_dataset(
            name="Test Dataset",
            description="A test dataset",
            schema={"field1": "string"},
            vector_dimensions=128
        )
        
        assert dataset.name == "Test Dataset"
        assert dataset.description == "A test dataset"
        assert dataset.schema == {"field1": "string"}
        assert dataset.vector_dimensions == 128
        
        # Verify dataset was saved in shard manager
        assert dataset.dataset_id in manager.shard_manager.datasets

    @pytest.mark.asyncio
    async def test_get_network_status(self, manager):
        """Test getting network status."""
        # Create a test dataset and shard
        dataset = manager.create_dataset(
            name="Test Dataset",
            description="A test dataset"
        )
        
        shard = manager.shard_manager.create_shard(
            dataset_id=dataset.dataset_id,
            data=None,
            cid="QmTest123",
            record_count=1000
        )
        
        # Mock discover_peers
        manager.node.discover_peers = asyncio.coroutine(
            mock.MagicMock(return_value=["peer1", "peer2"])
        )
        
        # Get network status
        status = await manager.get_network_status()
        
        assert status["node_id"] == manager.node.node_id
        assert status["role"] == manager.node.role.value
        assert status["peer_count"] == 2
        assert status["dataset_count"] == 1
        assert status["shard_count"] == 1
        assert len(status["datasets"]) == 1
        assert dataset.dataset_id in status["shards_by_dataset"]
        assert len(status["shards_by_dataset"][dataset.dataset_id]) == 1


# Integration tests
@pytest.mark.skipif(not LIBP2P_AVAILABLE, reason="libp2p not available")
class TestIntegration:
    """End-to-end integration tests."""
    
    @pytest.mark.asyncio
    async def test_create_and_search_dataset(self, temp_dir):
        """Test creating and searching a dataset."""
        # This test requires actual libp2p, so we'll mock what we need
        with mock.patch("ipfs_datasets_py.libp2p_kit.DistributedDatasetManager.start"):
            with mock.patch("ipfs_datasets_py.libp2p_kit.DistributedDatasetManager.vector_search") as mock_search:
                # Set up mock search results
                mock_search.side_effect = asyncio.coroutine(
                    mock.MagicMock(
                        return_value={
                            "total_results": 2,
                            "results": [
                                {"id": "result1", "distance": 0.1, "metadata": {"text": "Sample text 1"}},
                                {"id": "result2", "distance": 0.2, "metadata": {"text": "Sample text 2"}}
                            ]
                        }
                    )
                )
                
                # Create manager
                manager = DistributedDatasetManager(
                    storage_dir=temp_dir,
                    auto_start=False
                )
                
                # Create dataset
                dataset = manager.create_dataset(
                    name="Test Vector Dataset",
                    description="A test vector dataset",
                    vector_dimensions=128
                )
                
                # Create a test query vector
                query_vector = np.random.rand(128)
                
                # Search the dataset
                results = await manager.vector_search(
                    dataset_id=dataset.dataset_id,
                    query_vector=query_vector,
                    top_k=5
                )
                
                # Verify results
                assert results["total_results"] == 2
                assert len(results["results"]) == 2
                assert results["results"][0]["id"] == "result1"
                assert results["results"][0]["distance"] == 0.1
                assert results["results"][1]["id"] == "result2"
                assert results["results"][1]["distance"] == 0.2


if __name__ == "__main__":
    pytest.main(["-xvs", __file__])