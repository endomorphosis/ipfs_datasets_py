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
import asyncio
import random
from typing import Dict, List, Any, Optional, Union, Set, Callable, Tuple
from enum import Enum
from dataclasses import dataclass, field
import numpy as np

# Defer imports for optional dependencies
try:
    from multiaddr import Multiaddr
    import py_libp2p
    import py_libp2p.crypto.rsa as rsa
    from py_libp2p.peer.peerinfo import PeerInfo
    from py_libp2p.peer.id import ID as PeerID
    from py_libp2p.crypto.keys import KeyPair
    from py_libp2p.crypto.serialization import load_private_key, load_public_key
    from py_libp2p.network.stream.net_stream_interface import INetStream
    from py_libp2p.host.basic_host import BasicHost
    from py_libp2p.host.defaults import get_default_network
    LIBP2P_AVAILABLE = True
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


class NodeRole(Enum):
    """Role of the node in the distributed network."""
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
        
        # Event loop for async operations
        self.loop = asyncio.new_event_loop()
    
    def _register_default_handlers(self):
        """Register default protocol handlers."""
        self.register_protocol_handler(
            NetworkProtocol.NODE_DISCOVERY,
            self._handle_node_discovery
        )
    
    def register_protocol_handler(
        self,
        protocol: NetworkProtocol,
        handler: Callable[[INetStream], None]
    ):
        """
        Register a handler for a specific protocol.
        
        Args:
            protocol: The protocol to handle
            handler: The handler function
        """
        self.protocol_handlers[protocol.value] = handler
    
    async def _handle_node_discovery(self, stream: INetStream):
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
    
    def _load_or_create_key_pair(self) -> KeyPair:
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
        asyncio.run_coroutine_threadsafe(target, self.loop)


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
    
    async def _handle_shard_discovery(self, stream: INetStream):
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
    
    async def _handle_shard_transfer(self, stream: INetStream):
        """
        Handle shard transfer protocol.
        
        Args:
            stream: The network stream
        """
        # To be implemented: receive and store a shard from another node
        pass
    
    async def _handle_shard_sync(self, stream: INetStream):
        """
        Handle shard synchronization protocol.
        
        Args:
            stream: The network stream
        """
        # To be implemented: synchronize shard changes
        pass
    
    async def _handle_metadata_sync(self, stream: INetStream):
        """
        Handle metadata synchronization protocol.
        
        Args:
            stream: The network stream
        """
        # To be implemented: synchronize metadata changes
        pass
    
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
    
    async def _handle_federated_search(self, stream: INetStream):
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
            # Start event loop in a separate thread
            import threading
            
            def run_event_loop():
                asyncio.set_event_loop(self.node.loop)
                self.node.loop.run_until_complete(self.node.start())
                self.node.loop.run_forever()
            
            self._loop_thread = threading.Thread(target=run_event_loop, daemon=True)
            self._loop_thread.start()
            
            # Wait for node to start
            while not self.node.running:
                time.sleep(0.1)
    
    def stop(self):
        """Stop the distributed dataset manager."""
        if self.node.running:
            # Stop the node
            self.node.loop.create_task(self.node.stop())
            
            # Stop the event loop
            self.node.loop.call_soon_threadsafe(self.node.loop.stop)
            
            # Wait for thread to finish
            if self._loop_thread:
                self._loop_thread.join(timeout=5)
    
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
        replication_factor: int = 3
    ) -> List[ShardMetadata]:
        """
        Shard a dataset and distribute it across the network.
        
        Args:
            dataset_id: Dataset ID
            data: Dataset data
            format: Dataset format
            replication_factor: Number of nodes to replicate each shard to
            
        Returns:
            List[ShardMetadata]: Metadata for the created shards
        """
        # To be implemented: Split data into shards, create CIDs, and distribute
        # For now, this is a placeholder implementation
        return []
    
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