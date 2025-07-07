# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/libp2p_kit_full.py'

Files last updated: 1751500451.6012971

Stub file last updated: 2025-07-07 02:11:02

## BasicHost

```python
class BasicHost:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DatasetMetadata

```python
@dataclass
class DatasetMetadata:
    """
    Metadata for a distributed dataset.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DatasetShardManager

```python
class DatasetShardManager:
    """
    Manages dataset sharding and distribution across nodes.

This class is responsible for splitting datasets into shards,
distributing them across nodes, and managing shard metadata.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DistributedDatasetManager

```python
class DistributedDatasetManager:
    """
    Main class for managing distributed datasets with P2P synchronization.

This class provides a high-level interface for creating, distributing,
and searching datasets across a P2P network using libp2p.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FederatedSearchManager

```python
class FederatedSearchManager:
    """
    Manages federated search across distributed dataset fragments.

This class coordinates search operations across multiple nodes,
aggregating and ranking results for a unified search experience.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## INetStream

```python
class INetStream:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## KeyPair

```python
class KeyPair:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LibP2PNode

```python
class LibP2PNode:
    """
    Base node for P2P communication with libp2p.

This class provides the core P2P communication functionality using libp2p,
with methods for peer discovery, connection management, and message passing.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LibP2PNotAvailableError

```python
class LibP2PNotAvailableError(P2PError):
    """
    Raised when libp2p is not available.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Multiaddr

```python
class Multiaddr:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## NetworkProtocol

```python
class NetworkProtocol(Enum):
    """
    Protocol identifiers for different p2p operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## NodeConnectionError

```python
class NodeConnectionError(P2PError):
    """
    Raised when a connection to a peer fails.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## NodeRole

```python
class NodeRole(Enum):
    """
    Role of the node in the distributed network.

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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## P2PError

```python
class P2PError(Exception):
    """
    Base exception for P2P operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PeerID

```python
class PeerID:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PeerInfo

```python
class PeerInfo:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ShardMetadata

```python
@dataclass
class ShardMetadata:
    """
    Metadata for a dataset shard.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ShardTransferError

```python
class ShardTransferError(P2PError):
    """
    Raised when there's an error transferring a shard.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, node_id: Optional[str] = None, private_key_path: Optional[str] = None, listen_addresses: Optional[List[str]] = None, bootstrap_peers: Optional[List[str]] = None, role: NodeRole = NodeRole.HYBRID):
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
```
* **Async:** False
* **Method:** True
* **Class:** LibP2PNode

## __init__

```python
def __init__(self, node: LibP2PNode, storage_dir: str, shard_size: int = 10000):
    """
    Initialize the shard manager.

Args:
    node: The LibP2P node
    storage_dir: Directory for storing shards
    shard_size: Number of records per shard
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetShardManager

## __init__

```python
def __init__(self, node: LibP2PNode, shard_manager: DatasetShardManager, result_limit: int = 100):
    """
    Initialize the federated search manager.

Args:
    node: The LibP2P node
    shard_manager: The dataset shard manager
    result_limit: Maximum number of results to return
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearchManager

## __init__

```python
def __init__(self, storage_dir: str, private_key_path: Optional[str] = None, listen_addresses: Optional[List[str]] = None, bootstrap_peers: Optional[List[str]] = None, role: NodeRole = NodeRole.HYBRID, auto_start: bool = True):
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
```
* **Async:** False
* **Method:** True
* **Class:** DistributedDatasetManager

## _connect_to_peer

```python
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
```
* **Async:** True
* **Method:** True
* **Class:** LibP2PNode

## _handle_federated_search

```python
async def _handle_federated_search(self, stream: "INetStream"):
    """
    Handle federated search protocol.

Args:
    stream: The network stream
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearchManager

## _handle_metadata_sync

```python
async def _handle_metadata_sync(self, stream: "INetStream"):
    """
    Handle metadata synchronization protocol.

Args:
    stream: The network stream
    """
```
* **Async:** True
* **Method:** True
* **Class:** DatasetShardManager

## _handle_node_discovery

```python
async def _handle_node_discovery(self, stream: "INetStream"):
    """
    Handle node discovery protocol.

Args:
    stream: The network stream
    """
```
* **Async:** True
* **Method:** True
* **Class:** LibP2PNode

## _handle_shard_discovery

```python
async def _handle_shard_discovery(self, stream: "INetStream"):
    """
    Handle shard discovery protocol.

Args:
    stream: The network stream
    """
```
* **Async:** True
* **Method:** True
* **Class:** DatasetShardManager

## _handle_shard_sync

```python
async def _handle_shard_sync(self, stream: "INetStream"):
    """
    Handle shard synchronization protocol.

Args:
    stream: The network stream
    """
```
* **Async:** True
* **Method:** True
* **Class:** DatasetShardManager

## _handle_shard_transfer

```python
async def _handle_shard_transfer(self, stream: "INetStream"):
    """
    Handle shard transfer protocol.

Args:
    stream: The network stream
    """
```
* **Async:** True
* **Method:** True
* **Class:** DatasetShardManager

## _load_metadata

```python
def _load_metadata(self):
    """
    Load dataset and shard metadata from storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetShardManager

## _load_or_create_key_pair

```python
def _load_or_create_key_pair(self) -> "KeyPair":
    """
    Load or create RSA key pair for the node.

Returns:
    KeyPair: The loaded or created key pair
    """
```
* **Async:** False
* **Method:** True
* **Class:** LibP2PNode

## _register_default_handlers

```python
def _register_default_handlers(self):
    """
    Register default protocol handlers.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LibP2PNode

## _register_protocol_handlers

```python
def _register_protocol_handlers(self):
    """
    Register protocol handlers for shard management.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetShardManager

## _save_metadata

```python
def _save_metadata(self, metadata: Union[DatasetMetadata, ShardMetadata]):
    """
    Save metadata to storage.

Args:
    metadata: The metadata to save
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetShardManager

## create_dataset

```python
def create_dataset(self, name: str, description: str, schema: Optional[Dict[str, Any]] = None, vector_dimensions: Optional[int] = None, format: str = "parquet", tags: Optional[List[str]] = None) -> DatasetMetadata:
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
```
* **Async:** False
* **Method:** True
* **Class:** DatasetShardManager

## create_dataset

```python
def create_dataset(self, name: str, description: str, schema: Optional[Dict[str, Any]] = None, vector_dimensions: Optional[int] = None, format: str = "parquet", tags: Optional[List[str]] = None) -> DatasetMetadata:
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
```
* **Async:** False
* **Method:** True
* **Class:** DistributedDatasetManager

## create_shard

```python
def create_shard(self, dataset_id: str, data: Any, cid: str, record_count: int, format: str = "parquet") -> ShardMetadata:
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
```
* **Async:** False
* **Method:** True
* **Class:** DatasetShardManager

## discover_peers

```python
async def discover_peers(self) -> Set[str]:
    """
    Discover peers in the network.

Returns:
    Set[str]: Set of discovered peer IDs
    """
```
* **Async:** True
* **Method:** True
* **Class:** LibP2PNode

## distribute_shard

```python
async def distribute_shard(self, shard_id: str, target_nodes: Optional[List[str]] = None, replication_factor: int = 3) -> List[str]:
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
```
* **Async:** True
* **Method:** True
* **Class:** DatasetShardManager

## find_dataset_shards

```python
async def find_dataset_shards(self, dataset_id: str, include_metadata: bool = True) -> Dict[str, Any]:
    """
    Find all shards for a dataset across the network.

Args:
    dataset_id: Dataset ID
    include_metadata: Whether to include full shard metadata

Returns:
    Dict: Information about the dataset and its shards
    """
```
* **Async:** True
* **Method:** True
* **Class:** DatasetShardManager

## get_network_status

```python
async def get_network_status(self) -> Dict[str, Any]:
    """
    Get the status of the distributed network.

Returns:
    Dict: Network status information
    """
```
* **Async:** True
* **Method:** True
* **Class:** DistributedDatasetManager

## keyword_search

```python
async def keyword_search(self, dataset_id: str, query: str, top_k: int = 10, include_metadata: bool = True) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearchManager

## keyword_search

```python
async def keyword_search(self, dataset_id: str, query: str, top_k: int = 10) -> Dict[str, Any]:
    """
    Perform a federated keyword search across the distributed dataset.

Args:
    dataset_id: Dataset ID
    query: Keyword query
    top_k: Number of results to return

Returns:
    Dict: Search results from across the network
    """
```
* **Async:** True
* **Method:** True
* **Class:** DistributedDatasetManager

## rebalance_shards

```python
async def rebalance_shards(self, dataset_id: Optional[str] = None, target_replication: Optional[int] = None) -> Dict[str, Any]:
    """
    Rebalance shards across nodes to ensure proper distribution and replication.

Args:
    dataset_id: Optional dataset ID to rebalance (all datasets if None)
    target_replication: Target replication factor (use dataset default if None)

Returns:
    Dict: Rebalancing results
    """
```
* **Async:** True
* **Method:** True
* **Class:** DistributedDatasetManager

## register_protocol_handler

```python
def register_protocol_handler(self, protocol: NetworkProtocol, handler: Callable[['INetStream'], None]):
    """
    Register a handler for a specific protocol.

Args:
    protocol: The protocol to handle
    handler: The handler function
    """
```
* **Async:** False
* **Method:** True
* **Class:** LibP2PNode

## run_event_loop

```python
def run_event_loop():
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## run_in_thread

```python
def run_in_thread(self, target):
    """
    Run an async function in the event loop thread.

Args:
    target: The async function to run
    """
```
* **Async:** False
* **Method:** True
* **Class:** LibP2PNode

## send_message

```python
async def send_message(self, peer_id: str, protocol: NetworkProtocol, data: Dict[str, Any]) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** True
* **Class:** LibP2PNode

## shard_dataset

```python
async def shard_dataset(self, dataset_id: str, data: Any, format: str = "parquet", shard_size: int = 10000, replication_factor: int = 3, use_consistent_hashing: bool = True) -> List[ShardMetadata]:
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
```
* **Async:** True
* **Method:** True
* **Class:** DistributedDatasetManager

## start

```python
async def start(self):
    """
    Start the libp2p node.

This method initializes the libp2p host and starts listening for connections.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LibP2PNode

## start

```python
def start(self):
    """
    Start the distributed dataset manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DistributedDatasetManager

## stop

```python
async def stop(self):
    """
    Stop the libp2p node.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LibP2PNode

## stop

```python
def stop(self):
    """
    Stop the distributed dataset manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DistributedDatasetManager

## sync_with_network

```python
async def sync_with_network(self) -> Dict[str, Any]:
    """
    Synchronize dataset and shard metadata with the network.

This method discovers peers in the network and synchronizes dataset
and shard metadata to ensure all nodes have a consistent view of
the distributed datasets.

Returns:
    Dict: Synchronization results
    """
```
* **Async:** True
* **Method:** True
* **Class:** DistributedDatasetManager

## vector_search

```python
async def vector_search(self, dataset_id: str, query_vector: np.ndarray, top_k: int = 10, distance_threshold: Optional[float] = None, include_metadata: bool = True) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearchManager

## vector_search

```python
async def vector_search(self, dataset_id: str, query_vector: np.ndarray, top_k: int = 10, distance_threshold: Optional[float] = None) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** True
* **Class:** DistributedDatasetManager
