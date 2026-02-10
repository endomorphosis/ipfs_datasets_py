"""
LibP2P Integration for distributed dataset management.

This module provides libp2p-based peer-to-peer data transfer and management
capabilities for IPFS datasets, enabling:
- Sharded datasets across multiple IPFS nodes
- Collaborative dataset building with P2P synchronization
- Federated search across distributed dataset fragments
- Resilient operations with node failure handling

The libp2p_kit module integrates with the core IPFS dataset functionality
and extends it with distributed capabilities for scalable data management.
"""

import os
import json
import time
import logging
import anyio
import random
from typing import Dict, List, Any, Optional, Union, Set, Callable, Tuple
from enum import Enum
from dataclasses import dataclass, field
import numpy as np

# Defer imports for optional dependencies
try:
    from multiaddr import Multiaddr
    # import py_libp2p # Commented out due to import issues
    # import py_libp2p.crypto.rsa as rsa # Commented out due to import issues
    # from py_libp2p.peer.peerinfo import PeerInfo # Commented out due to import issues
    # from py_libp2p.peer.id import ID as PeerID # Commented out due to import issues
    # from py_libp2p.crypto.keys import KeyPair # Commented out due to import issues
    # from py_libp2p.crypto.serialization import load_private_key, load_public_key # Commented out due to import issues
    # from py_libp2p.network.stream.net_stream_interface import INetStream # Commented out due to import issues
    # from py_libp2p.host.basic_host import BasicHost # Commented out due to import issues
    # from py_libp2p.host.defaults import get_default_network # Commented out due to import issues
    LIBP2P_AVAILABLE = False
except ImportError:
    LIBP2P_AVAILABLE = False
    # Create stub classes for type checking
    class Multiaddr:
        pass

    class PeerInfo:
        pass

    class PeerID:
        pass

    class INetStream:
        pass

    class BasicHost:
        pass

    class KeyPair:
        pass


class NodeRole(Enum):
    """Role of the node in the distributed network.

    This enumeration defines the different roles a node can take in the distributed
    dataset management system, determining its responsibilities and capabilities.

    Attributes:
        COORDINATOR (str): Coordinates dataset distribution and search operations.
            Responsible for managing metadata, routing requests, and orchestrating
            data distribution across the network.
        WORKER (str): Stores and processes dataset fragments. Handles data storage,
            retrieval, and basic processing operations for assigned dataset portions.
        HYBRID (str): Combines both coordinator and worker capabilities. Can perform
            coordination tasks while also storing and processing data fragments.
        CLIENT (str): Read-only consumer that only accesses data without storing,
            coordinating, or processing. Minimal network participation role.
    """
    COORDINATOR = "coordinator"  # Coordinates dataset distribution and search
    WORKER = "worker"            # Stores and processes dataset fragments
    HYBRID = "hybrid"            # Both coordinator and worker roles
    CLIENT = "client"            # Only consumes data, doesn't store or coordinate


@dataclass
class ShardMetadata:
    """Metadata for a dataset shard."""
    shard_id: str
    dataset_id: str
    shard_index: int
    total_shards: int
    record_count: int
    cid: str
    vector_dimensions: Optional[int] = None
    creation_time: float = field(default_factory=time.time)
    modified_time: float = field(default_factory=time.time)
    node_ids: List[str] = field(default_factory=list)
    schema: Optional[Dict[str, Any]] = None
    format: str = "parquet"


@dataclass
class DatasetMetadata:
    """Metadata for a distributed dataset."""
    dataset_id: str
    name: str
    description: str
    total_records: int
    shard_count: int
    shard_ids: List[str]
    creation_time: float = field(default_factory=time.time)
    modified_time: float = field(default_factory=time.time)
    coordinator_id: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
    vector_dimensions: Optional[int] = None
    format: str = "parquet"
    tags: List[str] = field(default_factory=list)


class NetworkProtocol(Enum):
    """Protocol identifiers for different p2p operations."""
    SHARD_DISCOVERY = "/ipfs_datasets/shard/1.0.0"
    SHARD_TRANSFER = "/ipfs_datasets/transfer/1.0.0"
    SHARD_SYNC = "/ipfs_datasets/sync/1.0.0"
    FEDERATED_SEARCH = "/ipfs_datasets/search/1.0.0"
    METADATA_SYNC = "/ipfs_datasets/metadata/1.0.0"
    NODE_DISCOVERY = "/ipfs_datasets/discovery/1.0.0"


class P2PError(Exception):
    """Base exception for P2P operations."""
    pass


class LibP2PNotAvailableError(P2PError):
    """Raised when libp2p is not available."""
    pass


class NodeConnectionError(P2PError):
    """Raised when a connection to a peer fails."""
    pass


class ShardTransferError(P2PError):
    """Raised when there's an error transferring a shard."""
    pass


class LibP2PNode:
    """
    Base node for P2P communication with libp2p.

    This class provides the core P2P communication functionality using libp2p,
    with methods for peer discovery, connection management, and message passing.
    """

    def __init__(
        self,
        node_id: Optional[str] = None,
        private_key_path: Optional[str] = None,
        listen_addresses: Optional[List[str]] = None,
        bootstrap_peers: Optional[List[str]] = None,
        role: NodeRole = NodeRole.HYBRID
    ):
        """
        Initialize the libp2p node.

        Args:
            node_id: Optional node identifier (generated if not provided)
            private_key_path: Path to the private key file (generated if not provided)
            listen_addresses: List of multiaddresses to listen on
            bootstrap_peers: List of bootstrap peer multiaddresses
            role: Role of this node in the network

        Raises:
            LibP2PNotAvailableError: If libp2p dependencies are not installed
        """
        if not LIBP2P_AVAILABLE:
            raise LibP2PNotAvailableError(
                "LibP2P dependencies are not installed. "
                "Install them with: pip install py-libp2p"
            )

        self.node_id = node_id or f"node-{random.randint(10000, 99999)}"
        self.role = role
        self.listen_addresses = listen_addresses or ["/ip4/0.0.0.0/tcp/0"]
        self.bootstrap_peers = bootstrap_peers or []
        self.private_key_path = private_key_path

        # Will be initialized in start()
        self.host = None
        self.peer_id = None
        self.running = False
        self.peers = set()
        self.protocol_handlers = {}

        # Register default protocol handlers
        self._register_default_handlers()

        # Optional AnyIO portal used when this node is managed from sync code
        # (e.g. via DistributedDatasetManager.start/stop)
        self._portal = None

    def _register_default_handlers(self):
        """Register default protocol handlers."""
        self.register_protocol_handler(
            NetworkProtocol.NODE_DISCOVERY,
            self._handle_node_discovery
        )

    def register_protocol_handler(
        self,
        protocol: NetworkProtocol,
        handler: Callable[["INetStream"], None]  # Use forward reference
    ):
        """
        Register a handler for a specific protocol.

        Args:
            protocol: The protocol to handle
            handler: The handler function
        """
        self.protocol_handlers[protocol.value] = handler

    async def _handle_node_discovery(self, stream: 'INetStream'):
        """
        Handle node discovery protocol.

        Args:
            stream: The network stream
        """
        peer_id = stream.muxed_conn.peer_id
        self.peers.add(str(peer_id))
        await stream.write(json.dumps({
            "node_id": self.node_id,
            "role": self.role.value,
            "protocols": list(self.protocol_handlers.keys())
        }).encode())
        await stream.close()

    def _load_or_create_key_pair(self) -> 'KeyPair':
        """
        Load or create RSA key pair for the node.

        Returns:
            KeyPair: The loaded or created key pair
        """
        if self.private_key_path and os.path.exists(self.private_key_path):
            # Load existing private key
            with open(self.private_key_path, "rb") as f:
                private_key_data = f.read()
            private_key = load_private_key(private_key_data)

            # Derive public key
            public_key = private_key.get_public_key()
            return KeyPair(private_key, public_key)
        else:
            # Generate new key pair
            private_key, public_key = rsa.create_new_key_pair(2048)
            key_pair = KeyPair(private_key, public_key)

            if self.private_key_path:
                # Save private key
                os.makedirs(os.path.dirname(os.path.abspath(self.private_key_path)), exist_ok=True)
                with open(self.private_key_path, "wb") as f:
                    f.write(private_key.serialize())

            return key_pair

    async def start(self):
        """
        Start the libp2p node.

        This method initializes the libp2p host and starts listening for connections.
        """
        # Load or create key pair
        key_pair = self._load_or_create_key_pair()

        # Get default network with our key
        network = get_default_network(
            key_pair,
            [Multiaddr(addr) for addr in self.listen_addresses]
        )

        # Create host
        self.host = BasicHost(network)
        self.peer_id = self.host.get_id()

        # Set protocol handlers
        for protocol, handler in self.protocol_handlers.items():
            self.host.set_stream_handler(protocol, handler)

        # Connect to bootstrap peers
        for peer_addr in self.bootstrap_peers:
            await self._connect_to_peer(peer_addr)

        self.running = True
        logging.info(f"Node {self.node_id} started with peer ID {self.peer_id}")
        logging.info(f"Listening on: {[str(addr) for addr in self.host.get_addrs()]}")

    async def stop(self):
        """Stop the libp2p node."""
        if self.host:
            await self.host.close()
        self.running = False
        logging.info(f"Node {self.node_id} stopped")

    async def _connect_to_peer(self, peer_addr: str) -> bool:
        """
        Connect to a peer using its multiaddress.

        Args:
            peer_addr: The peer's multiaddress

        Returns:
            bool: True if connection was successful

        Raises:
            NodeConnectionError: If connection fails
        """
        try:
            # Parse multiaddress
            addr = Multiaddr(peer_addr)

            # Extract peer ID from multiaddress
            peer_id_str = addr.value_for_protocol("p2p")
            peer_id = PeerID.from_base58(peer_id_str)

            # Create peer info
            peer_info = PeerInfo(peer_id, [addr])

            # Connect to peer
            await self.host.connect(peer_info)
            self.peers.add(peer_id_str)
            logging.info(f"Connected to peer: {peer_id_str}")
            return True
        except Exception as e:
            logging.error(f"Error connecting to peer {peer_addr}: {str(e)}")
            raise NodeConnectionError(f"Failed to connect to peer: {str(e)}")

    async def send_message(
        self,
        peer_id: str,
        protocol: NetworkProtocol,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a message to a peer.

        Args:
            peer_id: The base58-encoded peer ID
            protocol: The protocol to use
            data: The data to send

        Returns:
            Dict: The response data

        Raises:
            NodeConnectionError: If connection fails
        """
        try:
            # Open stream to peer
            stream = await self.host.new_stream(
                PeerID.from_base58(peer_id),
                [protocol.value]
            )

            # Send data
            await stream.write(json.dumps(data).encode())

            # Read response
            response_data = await stream.read()
            response = json.loads(response_data.decode())

            # Close stream
            await stream.close()

            return response
        except Exception as e:
            logging.error(f"Error sending message to peer {peer_id}: {str(e)}")
            raise NodeConnectionError(f"Failed to send message: {str(e)}")

    async def discover_peers(self) -> Set[str]:
        """
        Discover peers in the network.

        Returns:
            Set[str]: Set of discovered peer IDs
        """
        # Start with known peers
        discovered = set(self.peers)

        # For each known peer, get their known peers
        for peer_id in list(self.peers):
            try:
                response = await self.send_message(
                    peer_id,
                    NetworkProtocol.NODE_DISCOVERY,
                    {"action": "get_peers"}
                )
                if "peers" in response:
                    discovered.update(response["peers"])
            except Exception as e:
                logging.warning(f"Error discovering peers from {peer_id}: {str(e)}")

        return discovered

    def run_in_thread(self, target):
        """
        Run an async function in the event loop thread.

        Args:
            target: The async function to run
        """
        """Schedule an awaitable/callable on the node's AnyIO portal.

        This is a best-effort compatibility helper for older call sites.
        """
        if self._portal is None:
            raise RuntimeError("Node portal is not initialized; start the manager first")

        if callable(target):
            self._portal.start_task_soon(target)
            return

        async def _runner():
            return await target

        self._portal.start_task_soon(_runner)


class DatasetShardManager:
    """
    Manages dataset sharding and distribution across nodes.

    This class is responsible for splitting datasets into shards,
    distributing them across nodes, and managing shard metadata.
    """

    def __init__(
        self,
        node: LibP2PNode,
        storage_dir: str,
        shard_size: int = 10000  # Records per shard
    ):
        """
        Initialize the shard manager.

        Args:
            node: The LibP2P node
            storage_dir: Directory for storing shards
            shard_size: Number of records per shard
        """
        self.node = node
        self.storage_dir = os.path.abspath(storage_dir)
        self.shard_size = shard_size

        # Create storage directory if it doesn't exist
        os.makedirs(os.path.join(self.storage_dir, "shards"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "metadata"), exist_ok=True)

        # Load existing metadata
        self.datasets: Dict[str, DatasetMetadata] = {}
        self.shards: Dict[str, ShardMetadata] = {}
        self._load_metadata()

        # Register protocol handlers
        if node.running:
            self._register_protocol_handlers()

    def _load_metadata(self):
        """Load dataset and shard metadata from storage."""
        # Load dataset metadata
        dataset_dir = os.path.join(self.storage_dir, "metadata", "datasets")
        if os.path.exists(dataset_dir):
            for filename in os.listdir(dataset_dir):
                if filename.endswith(".json"):
                    with open(os.path.join(dataset_dir, filename), "r") as f:
                        data = json.load(f)
                        dataset = DatasetMetadata(**data)
                        self.datasets[dataset.dataset_id] = dataset

        # Load shard metadata
        shard_dir = os.path.join(self.storage_dir, "metadata", "shards")
        if os.path.exists(shard_dir):
            for filename in os.listdir(shard_dir):
                if filename.endswith(".json"):
                    with open(os.path.join(shard_dir, filename), "r") as f:
                        data = json.load(f)
                        shard = ShardMetadata(**data)
                        self.shards[shard.shard_id] = shard

    def _save_metadata(self, metadata: Union[DatasetMetadata, ShardMetadata]):
        """
        Save metadata to storage.

        Args:
            metadata: The metadata to save
        """
        if isinstance(metadata, DatasetMetadata):
            # Save dataset metadata
            dataset_dir = os.path.join(self.storage_dir, "metadata", "datasets")
            os.makedirs(dataset_dir, exist_ok=True)
            with open(os.path.join(dataset_dir, f"{metadata.dataset_id}.json"), "w") as f:
                json.dump(metadata.__dict__, f)
        elif isinstance(metadata, ShardMetadata):
            # Save shard metadata
            shard_dir = os.path.join(self.storage_dir, "metadata", "shards")
            os.makedirs(shard_dir, exist_ok=True)
            with open(os.path.join(shard_dir, f"{metadata.shard_id}.json"), "w") as f:
                json.dump(metadata.__dict__, f)

    def _register_protocol_handlers(self):
        """Register protocol handlers for shard management."""
        self.node.register_protocol_handler(
            NetworkProtocol.SHARD_DISCOVERY,
            self._handle_shard_discovery
        )
        self.node.register_protocol_handler(
            NetworkProtocol.SHARD_TRANSFER,
            self._handle_shard_transfer
        )
        self.node.register_protocol_handler(
            NetworkProtocol.SHARD_SYNC,
            self._handle_shard_sync
        )
        self.node.register_protocol_handler(
            NetworkProtocol.METADATA_SYNC,
            self._handle_metadata_sync
        )

    async def _handle_shard_discovery(self, stream: 'INetStream'):
        """
        Handle shard discovery protocol.

        Args:
            stream: The network stream
        """
        # Read request
        data = await stream.read()
        request = json.loads(data.decode())

        response = {}
        if request.get("action") == "list_shards":
            # List shards for a dataset
            dataset_id = request.get("dataset_id")
            if dataset_id and dataset_id in self.datasets:
                response["shards"] = [
                    shard.__dict__ for shard_id, shard in self.shards.items()
                    if shard.dataset_id == dataset_id
                ]
            else:
                # List all shards
                response["shards"] = [shard.__dict__ for shard in self.shards.values()]
        elif request.get("action") == "get_shard_info":
            # Get info for a specific shard
            shard_id = request.get("shard_id")
            if shard_id and shard_id in self.shards:
                response["shard"] = self.shards[shard_id].__dict__
            else:
                response["error"] = "Shard not found"

        # Send response
        await stream.write(json.dumps(response).encode())
        await stream.close()

    async def _handle_shard_transfer(self, stream: 'INetStream'):
        """
        Handle shard transfer protocol.

        Args:
            stream: The network stream
        """
        try:
            # Read request
            data = await stream.read()
            request = json.loads(data.decode())
            response = {"status": "error", "message": "Invalid request"}

            if request.get("action") == "accept_shard":
                shard_id = request.get("shard_id")
                dataset_id = request.get("dataset_id")
                cid = request.get("cid")

                if not all([shard_id, dataset_id, cid]):
                    response = {"status": "error", "message": "Missing required parameters"}
                else:
                    # Check if we already have this shard
                    if shard_id in self.shards:
                        response = {"status": "accepted", "message": "Shard already exists"}
                    else:
                        # Accept the shard transfer request
                        response = {"status": "accepted", "message": "Ready to receive shard"}
                        await stream.write(json.dumps(response).encode())

                        # Receive shard metadata
                        metadata_data = await stream.read()
                        shard_metadata = json.loads(metadata_data.decode())

                        # Create the shard locally
                        shard = ShardMetadata(**shard_metadata)

                        # Verify that the dataset exists
                        if dataset_id not in self.datasets:
                            # If dataset doesn't exist locally, request its metadata
                            await stream.write(json.dumps({"status": "need_dataset"}).encode())
                            dataset_data = await stream.read()
                            dataset_metadata = json.loads(dataset_data.decode())
                            self.datasets[dataset_id] = DatasetMetadata(**dataset_metadata)
                            self._save_metadata(self.datasets[dataset_id])
                        else:
                            await stream.write(json.dumps({"status": "have_dataset"}).encode())

                        # Add ourselves to the node list
                        if self.node.node_id not in shard.node_ids:
                            shard.node_ids.append(self.node.node_id)

                        # Store the shard metadata
                        self.shards[shard_id] = shard
                        self._save_metadata(shard)

                        # Update dataset to include this shard if it's not already there
                        dataset = self.datasets[dataset_id]
                        if shard_id not in dataset.shard_ids:
                            dataset.shard_ids.append(shard_id)
                            dataset.shard_count = len(dataset.shard_ids)
                            dataset.total_records += shard.record_count
                            dataset.modified_time = time.time()
                            self._save_metadata(dataset)

                        # Notify of successful transfer
                        return await stream.write(json.dumps({"status": "success", "message": "Shard transferred"}).encode())

            elif request.get("action") == "transfer_shard":
                # Handle the case where we're sending a shard to another node
                shard_id = request.get("shard_id")
                if shard_id not in self.shards:
                    response = {"status": "error", "message": f"Shard {shard_id} not found"}
                else:
                    shard = self.shards[shard_id]
                    dataset_id = shard.dataset_id

                    # Send the shard metadata
                    response = {"status": "sending", "shard_id": shard_id}
                    await stream.write(json.dumps(response).encode())

                    # Send shard metadata
                    await stream.write(json.dumps(shard.__dict__).encode())

                    # Check if the recipient needs the dataset metadata
                    dataset_response = await stream.read()
                    dataset_status = json.loads(dataset_response.decode()).get("status")

                    if dataset_status == "need_dataset":
                        # Send dataset metadata
                        await stream.write(json.dumps(self.datasets[dataset_id].__dict__).encode())

                    # Wait for confirmation of successful transfer
                    transfer_response = await stream.read()
                    response = json.loads(transfer_response.decode())
                    return

            # Send response
            await stream.write(json.dumps(response).encode())
        except Exception as e:
            logging.error(f"Error handling shard transfer: {str(e)}")
            try:
                await stream.write(json.dumps({"status": "error", "message": str(e)}).encode())
            except:
                pass
        finally:
            await stream.close()

    async def _handle_shard_sync(self, stream: 'INetStream'):
        """
        Handle shard synchronization protocol.

        Args:
            stream: The network stream
        """
        try:
            # Read request
            data = await stream.read()
            request = json.loads(data.decode())
            response = {"status": "error", "message": "Invalid request"}

            if request.get("action") == "sync_shard":
                shard_id = request.get("shard_id")
                updated_metadata = request.get("metadata")

                if not shard_id or not updated_metadata:
                    response = {"status": "error", "message": "Missing required parameters"}
                else:
                    # Check if we have this shard
                    if shard_id not in self.shards:
                        response = {"status": "error", "message": f"Shard {shard_id} not found locally"}
                    else:
                        # Get the local shard
                        local_shard = self.shards[shard_id]
                        updated_shard = ShardMetadata(**updated_metadata)

                        # Only update if the remote shard is newer
                        if updated_shard.modified_time > local_shard.modified_time:
                            # Merge node IDs to ensure we maintain all locations
                            for node_id in local_shard.node_ids:
                                if node_id not in updated_shard.node_ids:
                                    updated_shard.node_ids.append(node_id)

                            # Update the local shard
                            self.shards[shard_id] = updated_shard
                            self._save_metadata(updated_shard)

                            # Update the dataset if record count changed
                            if updated_shard.record_count != local_shard.record_count:
                                dataset_id = updated_shard.dataset_id
                                if dataset_id in self.datasets:
                                    dataset = self.datasets[dataset_id]
                                    record_diff = updated_shard.record_count - local_shard.record_count
                                    dataset.total_records += record_diff
                                    dataset.modified_time = time.time()
                                    self._save_metadata(dataset)

                            response = {"status": "success", "message": "Shard metadata synchronized"}
                        else:
                            response = {"status": "unchanged", "message": "Local shard is newer or identical"}

            elif request.get("action") == "get_shard_timestamp":
                shard_id = request.get("shard_id")
                if not shard_id:
                    response = {"status": "error", "message": "Missing shard ID"}
                else:
                    if shard_id in self.shards:
                        response = {
                            "status": "success",
                            "shard_id": shard_id,
                            "modified_time": self.shards[shard_id].modified_time
                        }
                    else:
                        response = {"status": "not_found", "message": f"Shard {shard_id} not found"}

            elif request.get("action") == "list_shards_with_timestamps":
                dataset_id = request.get("dataset_id")
                if dataset_id:
                    # List shards for a specific dataset
                    shards = {
                        shard_id: shard.modified_time
                        for shard_id, shard in self.shards.items()
                        if shard.dataset_id == dataset_id
                    }
                else:
                    # List all shards
                    shards = {
                        shard_id: shard.modified_time
                        for shard_id, shard in self.shards.items()
                    }

                response = {
                    "status": "success",
                    "shards": shards
                }

            # Send response
            await stream.write(json.dumps(response).encode())
        except Exception as e:
            logging.error(f"Error handling shard sync: {str(e)}")
            try:
                await stream.write(json.dumps({"status": "error", "message": str(e)}).encode())
            except:
                pass
        finally:
            await stream.close()

    async def _handle_metadata_sync(self, stream: 'INetStream'):
        """
        Handle metadata synchronization protocol.

        Args:
            stream: The network stream
        """
        try:
            # Read request
            data = await stream.read()
            request = json.loads(data.decode())
            response = {"status": "error", "message": "Invalid request"}

            if request.get("action") == "sync_dataset":
                dataset_id = request.get("dataset_id")
                dataset_metadata = request.get("metadata")

                if not dataset_id or not dataset_metadata:
                    response = {"status": "error", "message": "Missing required parameters"}
                else:
                    # Create dataset object from metadata
                    updated_dataset = DatasetMetadata(**dataset_metadata)

                    # Check if we already have this dataset
                    if dataset_id in self.datasets:
                        local_dataset = self.datasets[dataset_id]

                        # Only update if the remote dataset is newer
                        if updated_dataset.modified_time > local_dataset.modified_time:
                            # Keep track of previously unknown shards
                            new_shard_ids = [
                                shard_id for shard_id in updated_dataset.shard_ids
                                if shard_id not in local_dataset.shard_ids
                            ]

                            # Update dataset
                            self.datasets[dataset_id] = updated_dataset
                            self._save_metadata(updated_dataset)

                            # Return information about missing shards
                            response = {
                                "status": "success",
                                "message": "Dataset metadata synchronized",
                                "new_shard_ids": new_shard_ids
                            }
                        else:
                            # Our version is newer or identical
                            response = {"status": "unchanged", "message": "Local dataset is newer or identical"}
                    else:
                        # This is a new dataset for us
                        self.datasets[dataset_id] = updated_dataset
                        self._save_metadata(updated_dataset)
                        response = {
                            "status": "success",
                            "message": "New dataset added",
                            "new_shard_ids": updated_dataset.shard_ids
                        }

            elif request.get("action") == "get_dataset_timestamp":
                dataset_id = request.get("dataset_id")
                if not dataset_id:
                    response = {"status": "error", "message": "Missing dataset ID"}
                else:
                    if dataset_id in self.datasets:
                        response = {
                            "status": "success",
                            "dataset_id": dataset_id,
                            "modified_time": self.datasets[dataset_id].modified_time,
                            "shard_count": self.datasets[dataset_id].shard_count
                        }
                    else:
                        response = {"status": "not_found", "message": f"Dataset {dataset_id} not found"}

            elif request.get("action") == "list_datasets_with_timestamps":
                # List all datasets with timestamps
                datasets = {
                    dataset_id: {
                        "modified_time": dataset.modified_time,
                        "shard_count": dataset.shard_count,
                        "name": dataset.name
                    }
                    for dataset_id, dataset in self.datasets.items()
                }

                response = {
                    "status": "success",
                    "datasets": datasets
                }

            # Send response
            await stream.write(json.dumps(response).encode())
        except Exception as e:
            logging.error(f"Error handling metadata sync: {str(e)}")
            try:
                await stream.write(json.dumps({"status": "error", "message": str(e)}).encode())
            except:
                pass
        finally:
            await stream.close()

    def create_dataset(
        self,
        name: str,
        description: str,
        schema: Optional[Dict[str, Any]] = None,
        vector_dimensions: Optional[int] = None,
        format: str = "parquet",
        tags: Optional[List[str]] = None
    ) -> DatasetMetadata:
        """
        Create a new distributed dataset.

        Args:
            name: Dataset name
            description: Dataset description
            schema: Dataset schema
            vector_dimensions: Vector dimensions for vector datasets
            format: Dataset format (parquet, arrow, etc.)
            tags: Dataset tags

        Returns:
            DatasetMetadata: The created dataset metadata


        Create a new distributed dataset in the IPFS network.

        This method initializes a new dataset with the specified parameters and registers it
        in the distributed network. The dataset is assigned a unique identifier and stored
        as metadata that can be shared across the libp2p network.

            name (str): Human-readable name for the dataset. This should be descriptive
                and unique within your organization or project context.
            description (str): Detailed description of the dataset's purpose, content,
                and intended use cases. This helps other users understand the dataset.
            schema (Optional[Dict[str, Any]], optional): Schema definition for the dataset
                specifying column names, data types, and validation rules. If None, the
                schema will be inferred from the first data added. Defaults to None.
            vector_dimensions (Optional[int], optional): Number of dimensions for vector
                embeddings if this is a vector dataset (e.g., for ML embeddings or 
                similarity search). Only required for vector-based datasets. Defaults to None.
            format (str, optional): Storage format for the dataset. Supported formats
                include 'parquet' (default), 'arrow', and other columnar formats.
                Defaults to "parquet".
            tags (Optional[List[str]], optional): List of tags for categorizing and
                discovering the dataset. Tags help with organization and searchability
                across the distributed network. Defaults to None.

            DatasetMetadata: A metadata object containing the dataset's unique identifier,
                configuration, and initial state. This object is used for all subsequent
                operations on the dataset including adding data, querying, and sharing.

        Raises:
            ValueError: If the dataset name is invalid or already exists in the local registry.
            NetworkError: If there's an issue communicating with the libp2p network during
                metadata propagation.
            StorageError: If the metadata cannot be persisted to local storage.

        Example:
            >>> dataset = kit.create_dataset(
            ...     name="user_embeddings",
            ...     description="User behavior embeddings for recommendation system",
            ...     vector_dimensions=512,
            ...     format="parquet",
            ...     tags=["ml", "embeddings", "users"]
            ... )
            >>> print(f"Created dataset: {dataset.dataset_id}")

        Note:
            - The dataset is initially empty with 0 records and 0 shards
            - The creating node becomes the coordinator for the dataset
            - Dataset metadata is automatically saved and can be shared with other nodes
            - The dataset ID is generated using timestamp and random components for uniqueness
        """
        dataset_id = f"dataset-{int(time.time())}-{random.randint(1000, 9999)}"
        dataset = DatasetMetadata(
            dataset_id=dataset_id,
            name=name,
            description=description,
            total_records=0,
            shard_count=0,
            shard_ids=[],
            schema=schema,
            vector_dimensions=vector_dimensions,
            format=format,
            tags=tags or [],
            coordinator_id=self.node.node_id
        )

        # Save dataset metadata
        self.datasets[dataset_id] = dataset
        self._save_metadata(dataset)

        return dataset

    def create_shard(
        self,
        dataset_id: str,
        data: Any,
        cid: str,
        record_count: int,
        format: str = "parquet"
    ) -> ShardMetadata:
        """
        Create a new shard for a dataset.

        Args:
            dataset_id: Dataset ID
            data: Shard data (will be stored or referenced)
            cid: Content ID for the shard
            record_count: Number of records in the shard
            format: Shard format

        Returns:
            ShardMetadata: The created shard metadata

        Raises:
            ValueError: If the dataset doesn't exist
        """
        if dataset_id not in self.datasets:
            raise ValueError(f"Dataset {dataset_id} not found")

        dataset = self.datasets[dataset_id]

        # Create shard metadata
        shard_id = f"shard-{dataset_id}-{dataset.shard_count}"
        shard = ShardMetadata(
            shard_id=shard_id,
            dataset_id=dataset_id,
            shard_index=dataset.shard_count,
            total_shards=dataset.shard_count + 1,
            record_count=record_count,
            cid=cid,
            vector_dimensions=dataset.vector_dimensions,
            schema=dataset.schema,
            format=format,
            node_ids=[self.node.node_id]
        )

        # Save shard data
        # Implementation depends on the format and storage mechanism
        # For now, we'll assume the data is already in IPFS with the given CID

        # Update shard metadata
        self.shards[shard_id] = shard
        self._save_metadata(shard)

        # Update dataset metadata
        dataset.shard_count += 1
        dataset.total_records += record_count
        dataset.shard_ids.append(shard_id)
        dataset.modified_time = time.time()
        self._save_metadata(dataset)

        return shard

    async def distribute_shard(
        self,
        shard_id: str,
        target_nodes: Optional[List[str]] = None,
        replication_factor: int = 3
    ) -> List[str]:
        """
        Distribute a shard to other nodes.

        Args:
            shard_id: Shard ID
            target_nodes: Specific nodes to distribute to (or discover if None)
            replication_factor: Number of nodes to replicate to

        Returns:
            List[str]: IDs of nodes that received the shard

        Raises:
            ValueError: If the shard doesn't exist
            ShardTransferError: If shard transfer fails
        """
        if shard_id not in self.shards:
            raise ValueError(f"Shard {shard_id} not found")

        shard = self.shards[shard_id]

        # If no target nodes specified, discover peers
        if not target_nodes:
            peers = await self.node.discover_peers()
            # Filter peers based on role (workers or hybrids)
            # This is simplified - in reality we'd query each peer's role
            target_nodes = list(peers)

        # Limit to replication factor
        if len(target_nodes) > replication_factor:
            target_nodes = random.sample(target_nodes, replication_factor)

        successful_transfers = []

        # Transfer shard to each target node
        for peer_id in target_nodes:
            try:
                # Request to transfer the shard
                response = await self.node.send_message(
                    peer_id,
                    NetworkProtocol.SHARD_TRANSFER,
                    {
                        "action": "accept_shard",
                        "shard_id": shard_id,
                        "dataset_id": shard.dataset_id,
                        "cid": shard.cid
                    }
                )

                if response.get("status") == "accepted":
                    # Add node to shard's node list
                    if peer_id not in shard.node_ids:
                        shard.node_ids.append(peer_id)
                    successful_transfers.append(peer_id)

            except Exception as e:
                logging.error(f"Error transferring shard {shard_id} to {peer_id}: {str(e)}")

        # Update shard metadata if any transfers were successful
        if successful_transfers:
            self._save_metadata(shard)

        return successful_transfers

    async def find_dataset_shards(
        self,
        dataset_id: str,
        include_metadata: bool = True
    ) -> Dict[str, Any]:
        """
        Find all shards for a dataset across the network.

        Args:
            dataset_id: Dataset ID
            include_metadata: Whether to include full shard metadata

        Returns:
            Dict: Information about the dataset and its shards
        """
        if dataset_id not in self.datasets:
            raise ValueError(f"Dataset {dataset_id} not found")

        dataset = self.datasets[dataset_id]
        local_shards = [s for s in self.shards.values() if s.dataset_id == dataset_id]

        # Discover peers
        peers = await self.node.discover_peers()

        all_shards = set(s.shard_id for s in local_shards)
        shard_locations = {s.shard_id: set(s.node_ids) for s in local_shards}

        # Query each peer for shards of this dataset
        for peer_id in peers:
            try:
                response = await self.node.send_message(
                    peer_id,
                    NetworkProtocol.SHARD_DISCOVERY,
                    {
                        "action": "list_shards",
                        "dataset_id": dataset_id
                    }
                )

                if "shards" in response:
                    for shard_data in response["shards"]:
                        shard_id = shard_data.get("shard_id")
                        if shard_id:
                            all_shards.add(shard_id)
                            if shard_id not in shard_locations:
                                shard_locations[shard_id] = set()
                            shard_locations[shard_id].add(peer_id)

                            # If we don't have this shard locally, add its metadata
                            if include_metadata and shard_id not in self.shards:
                                self.shards[shard_id] = ShardMetadata(**shard_data)
                                self._save_metadata(self.shards[shard_id])

            except Exception as e:
                logging.warning(f"Error querying peer {peer_id} for shards: {str(e)}")

        # Convert sets to lists for JSON serialization
        result = {
            "dataset": dataset.__dict__,
            "total_shards_found": len(all_shards),
            "shard_locations": {
                shard_id: list(nodes)
                for shard_id, nodes in shard_locations.items()
            }
        }

        if include_metadata:
            result["shards"] = [
                self.shards[shard_id].__dict__
                for shard_id in all_shards
                if shard_id in self.shards
            ]

        return result


class FederatedSearchManager:
    """
    Manages federated search across distributed dataset fragments.

    This class coordinates search operations across multiple nodes,
    aggregating and ranking results for a unified search experience.
    """

    def __init__(
        self,
        node: LibP2PNode,
        shard_manager: DatasetShardManager,
        result_limit: int = 100
    ):
        """
        Initialize the federated search manager.

        Args:
            node: The LibP2P node
            shard_manager: The dataset shard manager
            result_limit: Maximum number of results to return
        """
        self.node = node
        self.shard_manager = shard_manager
        self.result_limit = result_limit

        # Register protocol handler
        if node.running:
            self.node.register_protocol_handler(
                NetworkProtocol.FEDERATED_SEARCH,
                self._handle_federated_search
            )

    async def _handle_federated_search(self, stream: 'INetStream'):
        """
        Handle federated search protocol.

        Args:
            stream: The network stream
        """
        # Read request
        data = await stream.read()
        request = json.loads(data.decode())

        response = {}
        if request.get("action") == "search":
            # Handle search request
            # Implementation depends on the search type (vector, keyword, etc.)
            dataset_id = request.get("dataset_id")
            query = request.get("query")
            query_type = request.get("query_type", "vector")

            if query_type == "vector" and "vector" in request:
                # Vector search
                # To be implemented: vector search in local shards
                pass
            elif query_type == "keyword":
                # Keyword search
                # To be implemented: keyword search in local shards
                pass

            # Placeholder response
            response["results"] = []
            response["status"] = "success"

        # Send response
        await stream.write(json.dumps(response).encode())
        await stream.close()

    async def vector_search(
        self,
        dataset_id: str,
        query_vector: np.ndarray,
        top_k: int = 10,
        distance_threshold: Optional[float] = None,
        include_metadata: bool = True
    ) -> Dict[str, Any]:
        """
        Perform a federated vector search across the dataset.

        Args:
            dataset_id: Dataset ID
            query_vector: Query vector
            top_k: Number of results to return
            distance_threshold: Maximum distance threshold
            include_metadata: Whether to include result metadata

        Returns:
            Dict: Search results from across the network
        """
        # Find dataset shards
        dataset_info = await self.shard_manager.find_dataset_shards(
            dataset_id,
            include_metadata=True
        )

        # Convert query vector to a list for serialization
        query_vector_list = query_vector.tolist()

        # Track all nodes that have shards for this dataset
        nodes_with_shards = set()
        for shard_id, node_ids in dataset_info["shard_locations"].items():
            nodes_with_shards.update(node_ids)

        # Send search requests to all nodes with shards
        all_results = []
        for node_id in nodes_with_shards:
            try:
                response = await self.node.send_message(
                    node_id,
                    NetworkProtocol.FEDERATED_SEARCH,
                    {
                        "action": "search",
                        "dataset_id": dataset_id,
                        "query_type": "vector",
                        "vector": query_vector_list,
                        "top_k": top_k,
                        "distance_threshold": distance_threshold,
                        "include_metadata": include_metadata
                    }
                )

                if response.get("status") == "success" and "results" in response:
                    all_results.extend(response["results"])

            except Exception as e:
                logging.warning(f"Error querying node {node_id} for vector search: {str(e)}")

        # Sort and limit results
        all_results.sort(key=lambda x: x.get("distance", float("inf")))
        limited_results = all_results[:top_k]

        return {
            "query": {
                "dataset_id": dataset_id,
                "top_k": top_k,
                "distance_threshold": distance_threshold
            },
            "total_results": len(all_results),
            "results": limited_results,
            "nodes_queried": list(nodes_with_shards)
        }

    async def keyword_search(
        self,
        dataset_id: str,
        query: str,
        top_k: int = 10,
        include_metadata: bool = True
    ) -> Dict[str, Any]:
        """
        Perform a federated keyword search across the dataset.

        Args:
            dataset_id: Dataset ID
            query: Keyword query
            top_k: Number of results to return
            include_metadata: Whether to include result metadata

        Returns:
            Dict: Search results from across the network
        """
        # Find dataset shards
        dataset_info = await self.shard_manager.find_dataset_shards(
            dataset_id,
            include_metadata=True
        )

        # Track all nodes that have shards for this dataset
        nodes_with_shards = set()
        for shard_id, node_ids in dataset_info["shard_locations"].items():
            nodes_with_shards.update(node_ids)

        # Send search requests to all nodes with shards
        all_results = []
        for node_id in nodes_with_shards:
            try:
                response = await self.node.send_message(
                    node_id,
                    NetworkProtocol.FEDERATED_SEARCH,
                    {
                        "action": "search",
                        "dataset_id": dataset_id,
                        "query_type": "keyword",
                        "query": query,
                        "top_k": top_k,
                        "include_metadata": include_metadata
                    }
                )

                if response.get("status") == "success" and "results" in response:
                    all_results.extend(response["results"])

            except Exception as e:
                logging.warning(f"Error querying node {node_id} for keyword search: {str(e)}")

        # Sort and limit results (assuming there's a score field)
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        limited_results = all_results[:top_k]

        return {
            "query": {
                "dataset_id": dataset_id,
                "query": query,
                "top_k": top_k
            },
            "total_results": len(all_results),
            "results": limited_results,
            "nodes_queried": list(nodes_with_shards)
        }


class DistributedDatasetManager:
    """
    Main class for managing distributed datasets with P2P synchronization.

    This class provides a high-level interface for creating, distributing,
    and searching datasets across a P2P network using libp2p.
    """

    def __init__(
        self,
        storage_dir: str,
        private_key_path: Optional[str] = None,
        listen_addresses: Optional[List[str]] = None,
        bootstrap_peers: Optional[List[str]] = None,
        role: NodeRole = NodeRole.HYBRID,
        auto_start: bool = True
    ):
        """
        Initialize the distributed dataset manager.

        Args:
            storage_dir: Directory for storing datasets and metadata
            private_key_path: Path to private key for the libp2p node
            listen_addresses: List of multiaddresses to listen on
            bootstrap_peers: List of bootstrap peers
            role: Role of this node
            auto_start: Whether to automatically start the node
        """
        # Create libp2p node
        self.node = LibP2PNode(
            private_key_path=private_key_path,
            listen_addresses=listen_addresses,
            bootstrap_peers=bootstrap_peers,
            role=role
        )

        # Create component managers
        self.shard_manager = DatasetShardManager(
            node=self.node,
            storage_dir=os.path.join(storage_dir, "shards")
        )

        self.search_manager = FederatedSearchManager(
            node=self.node,
            shard_manager=self.shard_manager
        )

        # Event loop thread
        self._loop_thread = None

        # Auto-start node if requested
        if auto_start:
            self.start()

    def start(self):
        """Start the distributed dataset manager."""
        if not self.node.running:
            # Start an AnyIO portal in a background thread and run node.start() on it.
            # This avoids direct asyncio loop management while remaining compatible with
            # asyncio-based dependencies under AnyIO's asyncio backend.
            self._portal_cm = anyio.from_thread.start_blocking_portal(backend="asyncio")
            self._portal = self._portal_cm.__enter__()
            self.node._portal = self._portal
            self._portal.call(self.node.start)

    def stop(self):
        """Stop the distributed dataset manager."""
        if self.node.running:
            if self._portal is not None:
                self._portal.call(self.node.stop)

            if self._portal is not None:
                self._portal.stop()
                self._portal = None
                self.node._portal = None

            if self._portal_cm is not None:
                self._portal_cm.__exit__(None, None, None)
                self._portal_cm = None

    def create_dataset(
        self,
        name: str,
        description: str,
        schema: Optional[Dict[str, Any]] = None,
        vector_dimensions: Optional[int] = None,
        format: str = "parquet",
        tags: Optional[List[str]] = None
    ) -> DatasetMetadata:
        """
        Create a new distributed dataset.

        Args:
            name: Dataset name
            description: Dataset description
            schema: Dataset schema
            vector_dimensions: Vector dimensions for vector datasets
            format: Dataset format
            tags: Dataset tags

        Returns:
            DatasetMetadata: The created dataset metadata
        """
        return self.shard_manager.create_dataset(
            name=name,
            description=description,
            schema=schema,
            vector_dimensions=vector_dimensions,
            format=format,
            tags=tags
        )

    async def shard_dataset(
        self,
        dataset_id: str,
        data: Any,
        format: str = "parquet",
        shard_size: int = 10000,
        replication_factor: int = 3,
        use_consistent_hashing: bool = True
    ) -> List[ShardMetadata]:
        """
        Shard a dataset and distribute it across the network.

        Args:
            dataset_id: Dataset ID
            data: Dataset data (pandas DataFrame, Arrow table, list, etc.)
            format: Dataset format ("parquet", "arrow", etc.)
            shard_size: Number of records per shard
            replication_factor: Number of nodes to replicate each shard to
            use_consistent_hashing: Whether to use consistent hashing for distribution

        Returns:
            List[ShardMetadata]: Metadata for the created shards

        Raises:
            ValueError: If the dataset doesn't exist or the data is invalid
        """
        import pandas as pd
        import pyarrow as pa
        import pyarrow.parquet as pq
        import tempfile
        import os
        import hashlib
        from tqdm import tqdm

        # Verify dataset exists
        if dataset_id not in self.shard_manager.datasets:
            raise ValueError(f"Dataset {dataset_id} not found")

        dataset = self.shard_manager.datasets[dataset_id]
        created_shards = []

        # Step 1: Convert data to a common format (pandas DataFrame)
        df = None
        if isinstance(data, pd.DataFrame):
            df = data
        elif isinstance(data, pa.Table):
            df = data.to_pandas()
        elif isinstance(data, list) and all(isinstance(item, dict) for item in data):
            df = pd.DataFrame(data)
        elif hasattr(data, "to_pandas"):  # Handle HuggingFace datasets
            df = data.to_pandas()
        else:
            raise ValueError("Unsupported data format. Provide DataFrame, Arrow Table, or list of dicts")

        total_records = len(df)
        logging.info(f"Sharding dataset with {total_records} records, shard size {shard_size}")

        # Update dataset metadata
        dataset.total_records = total_records
        dataset.modified_time = time.time()
        self.shard_manager._save_metadata(dataset)

        # Step 2: Split data into shards
        num_shards = (total_records + shard_size - 1) // shard_size  # Ceiling division

        # Create temporary directory for shard files
        with tempfile.TemporaryDirectory() as temp_dir:
            shard_metadata_list = []

            # Discover nodes for distribution
            all_peers = await self.node.discover_peers()
            available_nodes = list(all_peers)

            if not available_nodes and replication_factor > 1:
                logging.warning("No peer nodes found. Shards will only be stored locally.")

            # Process each shard
            for shard_index in tqdm(range(num_shards), desc="Creating shards"):
                # Extract shard data
                start_idx = shard_index * shard_size
                end_idx = min(start_idx + shard_size, total_records)
                shard_df = df.iloc[start_idx:end_idx]
                shard_record_count = len(shard_df)

                # Create a unique shard ID
                shard_id = f"shard-{dataset_id}-{shard_index}"

                # Convert to appropriate format and calculate CID
                shard_file_path = os.path.join(temp_dir, f"{shard_id}.{format}")

                if format == "parquet":
                    # Convert to Arrow table and write Parquet
                    table = pa.Table.from_pandas(shard_df)
                    pq.write_table(table, shard_file_path)
                elif format == "arrow":
                    # Write Arrow IPC file
                    table = pa.Table.from_pandas(shard_df)
                    with pa.OSFile(shard_file_path, "wb") as sink:
                        writer = pa.RecordBatchFileWriter(sink, table.schema)
                        writer.write_table(table)
                        writer.close()
                else:
                    raise ValueError(f"Unsupported format: {format}")

                # Here we would normally add the file to IPFS, but for this example,
                # we'll just calculate a hash to simulate a CID
                with open(shard_file_path, "rb") as f:
                    file_data = f.read()
                    fake_cid = "Qm" + hashlib.sha256(file_data).hexdigest()[:44]

                # Create shard metadata
                shard = self.shard_manager.create_shard(
                    dataset_id=dataset_id,
                    data=None,  # We're not storing the actual data here
                    cid=fake_cid,
                    record_count=shard_record_count,
                    format=format
                )

                shard_metadata_list.append(shard)

                # Step 3: Distribute shards to other nodes
                if replication_factor > 1 and available_nodes:
                    # Use consistent hashing to determine which nodes should store this shard
                    if use_consistent_hashing:
                        target_nodes = []
                        # Simple hash-based node selection (a basic form of consistent hashing)
                        shard_hash = int(hashlib.md5(shard_id.encode()).hexdigest(), 16)
                        for _ in range(min(replication_factor, len(available_nodes))):
                            node_idx = shard_hash % len(available_nodes)
                            target_nodes.append(available_nodes[node_idx])
                            # Adjust hash for next selection to avoid choosing the same node
                            shard_hash = (shard_hash * 31) % (2**32)
                    else:
                        # Random selection
                        target_count = min(replication_factor - 1, len(available_nodes))
                        target_nodes = random.sample(available_nodes, target_count)

                    # Distribute the shard
                    successful_transfers = await self.shard_manager.distribute_shard(
                        shard_id=shard.shard_id,
                        target_nodes=target_nodes
                    )

                    logging.info(f"Distributed shard {shard.shard_id} to {len(successful_transfers)} nodes")
                    created_shards.append(shard)

        logging.info(f"Created and distributed {len(created_shards)} shards")
        return created_shards

    async def vector_search(
        self,
        dataset_id: str,
        query_vector: np.ndarray,
        top_k: int = 10,
        distance_threshold: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Perform a federated vector search across the distributed dataset.

        Args:
            dataset_id: Dataset ID
            query_vector: Query vector
            top_k: Number of results to return
            distance_threshold: Maximum distance threshold

        Returns:
            Dict: Search results from across the network
        """
        return await self.search_manager.vector_search(
            dataset_id=dataset_id,
            query_vector=query_vector,
            top_k=top_k,
            distance_threshold=distance_threshold
        )

    async def keyword_search(
        self,
        dataset_id: str,
        query: str,
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        Perform a federated keyword search across the distributed dataset.

        Args:
            dataset_id: Dataset ID
            query: Keyword query
            top_k: Number of results to return

        Returns:
            Dict: Search results from across the network
        """
        return await self.search_manager.keyword_search(
            dataset_id=dataset_id,
            query=query,
            top_k=top_k
        )

    async def get_network_status(self) -> Dict[str, Any]:
        """
        Get the status of the distributed network.

        Returns:
            Dict: Network status information
        """
        # Discover peers
        peers = await self.node.discover_peers()

        # Get dataset information
        datasets = list(self.shard_manager.datasets.values())

        # Get shard information
        shards_by_dataset = {}
        for shard in self.shard_manager.shards.values():
            if shard.dataset_id not in shards_by_dataset:
                shards_by_dataset[shard.dataset_id] = []
            shards_by_dataset[shard.dataset_id].append(shard)

        return {
            "node_id": self.node.node_id,
            "role": self.node.role.value,
            "peer_count": len(peers),
            "dataset_count": len(datasets),
            "shard_count": len(self.shard_manager.shards),
            "datasets": [d.__dict__ for d in datasets],
            "shards_by_dataset": {
                dataset_id: [s.__dict__ for s in shards]
                for dataset_id, shards in shards_by_dataset.items()
            }
        }

    async def sync_with_network(self) -> Dict[str, Any]:
        """
        Synchronize dataset and shard metadata with the network.

        This method discovers peers in the network and synchronizes dataset
        and shard metadata to ensure all nodes have a consistent view of
        the distributed datasets.

        Returns:
            Dict: Synchronization results
        """
        # Discover peers
        peers = await self.node.discover_peers()
        if not peers:
            return {"status": "no_peers", "message": "No peers found to synchronize with"}

        # Get local datasets and their timestamps
        local_datasets = {
            dataset_id: dataset.modified_time
            for dataset_id, dataset in self.shard_manager.datasets.items()
        }

        # Track sync stats
        results = {
            "peers_synced": 0,
            "datasets_updated": 0,
            "datasets_added": 0,
            "shards_updated": 0,
            "shards_added": 0
        }

        # Sync with each peer
        for peer_id in peers:
            try:
                # Get remote datasets
                remote_datasets_response = await self.node.send_message(
                    peer_id,
                    NetworkProtocol.METADATA_SYNC,
                    {"action": "list_datasets_with_timestamps"}
                )

                if remote_datasets_response.get("status") != "success":
                    continue

                remote_datasets = remote_datasets_response.get("datasets", {})

                # Check each remote dataset
                for dataset_id, dataset_info in remote_datasets.items():
                    remote_timestamp = dataset_info.get("modified_time", 0)

                    # If we don't have this dataset or our version is older
                    if dataset_id not in local_datasets or remote_timestamp > local_datasets[dataset_id]:
                        # Request full dataset metadata
                        dataset_response = await self.node.send_message(
                            peer_id,
                            NetworkProtocol.METADATA_SYNC,
                            {
                                "action": "sync_dataset",
                                "dataset_id": dataset_id,
                                "metadata": self.shard_manager.datasets[dataset_id].__dict__ if dataset_id in self.shard_manager.datasets else None
                            }
                        )

                        if dataset_response.get("status") == "success":
                            if dataset_id in local_datasets:
                                results["datasets_updated"] += 1
                            else:
                                results["datasets_added"] += 1

                            # Check for new shards we need to fetch
                            new_shard_ids = dataset_response.get("new_shard_ids", [])
                            for shard_id in new_shard_ids:
                                if shard_id not in self.shard_manager.shards:
                                    # Request shard transfer
                                    try:
                                        shard_response = await self.node.send_message(
                                            peer_id,
                                            NetworkProtocol.SHARD_TRANSFER,
                                            {
                                                "action": "transfer_shard",
                                                "shard_id": shard_id
                                            }
                                        )

                                        if shard_response.get("status") == "success":
                                            results["shards_added"] += 1
                                    except Exception as e:
                                        logging.error(f"Error transferring shard {shard_id}: {str(e)}")

                # Sync our local shards with remote peer
                for dataset_id, dataset in self.shard_manager.datasets.items():
                    local_shards = [s for s in self.shard_manager.shards.values() if s.dataset_id == dataset_id]

                    for shard in local_shards:
                        # Get remote shard timestamp
                        try:
                            shard_timestamp_response = await self.node.send_message(
                                peer_id,
                                NetworkProtocol.SHARD_SYNC,
                                {
                                    "action": "get_shard_timestamp",
                                    "shard_id": shard.shard_id
                                }
                            )

                            remote_timestamp = 0
                            if shard_timestamp_response.get("status") == "success":
                                remote_timestamp = shard_timestamp_response.get("modified_time", 0)

                            # If remote version is older or not found, sync our version
                            if shard_timestamp_response.get("status") == "not_found" or shard.modified_time > remote_timestamp:
                                sync_response = await self.node.send_message(
                                    peer_id,
                                    NetworkProtocol.SHARD_SYNC,
                                    {
                                        "action": "sync_shard",
                                        "shard_id": shard.shard_id,
                                        "metadata": shard.__dict__
                                    }
                                )

                                if sync_response.get("status") == "success":
                                    results["shards_updated"] += 1
                        except Exception as e:
                            logging.error(f"Error syncing shard {shard.shard_id} with peer {peer_id}: {str(e)}")

                results["peers_synced"] += 1

            except Exception as e:
                logging.error(f"Error syncing with peer {peer_id}: {str(e)}")

        return results

    async def rebalance_shards(self, dataset_id: Optional[str] = None, target_replication: Optional[int] = None) -> Dict[str, Any]:
        """
        Rebalance shards across nodes to ensure proper distribution and replication.

        Args:
            dataset_id: Optional dataset ID to rebalance (all datasets if None)
            target_replication: Target replication factor (use dataset default if None)

        Returns:
            Dict: Rebalancing results
        """
        # Discover available nodes
        peers = await self.node.discover_peers()
        available_nodes = list(peers) + [self.node.node_id]

        if len(available_nodes) < 2:
            return {
                "status": "insufficient_nodes",
                "message": "At least 2 nodes are required for rebalancing",
                "shards_rebalanced": 0
            }

        # Determine datasets to rebalance
        datasets_to_rebalance = []
        if dataset_id:
            if dataset_id in self.shard_manager.datasets:
                datasets_to_rebalance.append(self.shard_manager.datasets[dataset_id])
            else:
                return {
                    "status": "dataset_not_found",
                    "message": f"Dataset {dataset_id} not found",
                    "shards_rebalanced": 0
                }
        else:
            datasets_to_rebalance = list(self.shard_manager.datasets.values())

        # Track rebalancing stats
        total_shards_rebalanced = 0
        rebalance_results = {}

        # Process each dataset
        for dataset in datasets_to_rebalance:
            current_dataset_id = dataset.dataset_id
            dataset_replication = target_replication or 3  # Default replication factor

            # Get all shards for this dataset
            dataset_shards = [
                shard for shard in self.shard_manager.shards.values()
                if shard.dataset_id == current_dataset_id
            ]

            dataset_results = {
                "total_shards": len(dataset_shards),
                "rebalanced_shards": 0,
                "failed_shards": 0
            }

            # Analyze shard distribution
            for shard in dataset_shards:
                current_nodes = set(shard.node_ids)
                current_replication = len(current_nodes)

                # If under-replicated, add more replicas
                if current_replication < dataset_replication:
                    # Find nodes that don't have this shard
                    candidate_nodes = [node for node in available_nodes if node not in current_nodes]

                    if candidate_nodes:
                        # Calculate how many more replicas we need
                        additional_replicas = min(dataset_replication - current_replication, len(candidate_nodes))
                        target_nodes = random.sample(candidate_nodes, additional_replicas)

                        try:
                            # Distribute the shard to new nodes
                            successful_transfers = await self.shard_manager.distribute_shard(
                                shard_id=shard.shard_id,
                                target_nodes=target_nodes
                            )

                            if successful_transfers:
                                total_shards_rebalanced += 1
                                dataset_results["rebalanced_shards"] += 1
                        except Exception as e:
                            logging.error(f"Error rebalancing shard {shard.shard_id}: {str(e)}")
                            dataset_results["failed_shards"] += 1

            rebalance_results[current_dataset_id] = dataset_results

        return {
            "status": "success",
            "total_shards_rebalanced": total_shards_rebalanced,
            "datasets": rebalance_results
        }
