# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/resilient_operations.py'

Files last updated: 1748635923.4613795

Stub file last updated: 2025-07-07 02:11:02

## Checkpoint

```python
@dataclass
class Checkpoint:
    """
    Checkpoint for resumable operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CircuitBreaker

```python
@dataclass
class CircuitBreaker:
    """
    Implements the circuit breaker pattern to prevent cascading failures.

The circuit breaker has three states:
- CLOSED: Operations are allowed to proceed normally
- OPEN: Operations immediately fail without attempting execution
- HALF_OPEN: A limited number of operations are allowed to test if the system has recovered
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CircuitBreakerOpenError

```python
class CircuitBreakerOpenError(Exception):
    """
    Exception raised when a circuit breaker is open.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## HealthStatus

```python
class HealthStatus(Enum):
    """
    Health status of a node in the network.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## NodeHealth

```python
@dataclass
class NodeHealth:
    """
    Health information for a node.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## OperationResult

```python
@dataclass
class OperationResult:
    """
    Result of a distributed operation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## OperationStatus

```python
class OperationStatus(Enum):
    """
    Status of a distributed operation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ResilienceManager

```python
class ResilienceManager:
    """
    Manager for resilient operations across distributed nodes.

This class provides tools for enhanced resilience when working with
distributed IPFS nodes, including:
- Health checks and monitoring
- Circuit breakers for failing components
- Automatic retries with exponential backoff
- Operation tracking and recovery
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RetryConfig

```python
@dataclass
class RetryConfig:
    """
    Configuration for retry behavior.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __call__

```python
def __call__(self, func):
    """
    Apply the decorator to the function.
    """
```
* **Async:** False
* **Method:** True
* **Class:** resilient

## __init__

```python
def __init__(self, max_retries: int = DEFAULT_RETRY_COUNT, initial_backoff_ms: int = DEFAULT_INITIAL_BACKOFF_MS, max_backoff_ms: int = DEFAULT_MAX_BACKOFF_MS, backoff_factor: float = DEFAULT_BACKOFF_FACTOR, jitter_factor: float = DEFAULT_JITTER_FACTOR, retry_on_exceptions: List[type] = None):
    """
    Initialize the resilient decorator.

Args:
    max_retries: Maximum number of retry attempts
    initial_backoff_ms: Initial backoff time in milliseconds
    max_backoff_ms: Maximum backoff time in milliseconds
    backoff_factor: Factor to increase backoff time by
    jitter_factor: Random jitter factor to add to backoff
    retry_on_exceptions: List of exception types to retry on
    """
```
* **Async:** False
* **Method:** True
* **Class:** resilient

## __init__

```python
def __init__(self, node: LibP2PNode, storage_dir: Optional[str] = None, health_check_interval_sec: int = DEFAULT_HEALTH_CHECK_INTERVAL_SEC, circuit_breaker_config: Optional[Dict[str, Any]] = None, retry_config: Optional[RetryConfig] = None):
    """
    Initialize the resilience manager.

Args:
    node: The P2P node for network communication
    storage_dir: Directory for storing resilience data
    health_check_interval_sec: Interval for node health checks
    circuit_breaker_config: Circuit breaker configuration
    retry_config: Default retry configuration
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** RetryConfig

## _check_node_health

```python
async def _check_node_health(self, node_id: str):
    """
    Perform a health check on a node.

Args:
    node_id: ID of the node to check
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## _check_state

```python
def _check_state(self):
    """
    Check and update the circuit state.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CircuitBreaker

## _create_circuit_breakers

```python
def _create_circuit_breakers(self, config: Dict[str, Any]):
    """
    Create default circuit breakers for common operations.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## _execute_async

```python
async def _execute_async(self, func, args, kwargs):
    """
    Execute an asynchronous function with retries.
    """
```
* **Async:** True
* **Method:** True
* **Class:** resilient

## _execute_sync

```python
def _execute_sync(self, func, args, kwargs):
    """
    Execute a synchronous function with retries.
    """
```
* **Async:** False
* **Method:** True
* **Class:** resilient

## _get_load_metrics

```python
def _get_load_metrics(self) -> Dict[str, Any]:
    """
    Get load metrics for this node.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## _get_node_capabilities

```python
def _get_node_capabilities(self) -> Dict[str, Any]:
    """
    Get capabilities of this node.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## _handle_health_check

```python
async def _handle_health_check(self, stream):
    """
    Handle incoming health check requests.

Args:
    stream: The network stream
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## _health_check_loop

```python
def _health_check_loop(self):
    """
    Background loop for conducting health checks.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## _record_failure

```python
def _record_failure(self):
    """
    Record a failed operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CircuitBreaker

## _record_success

```python
def _record_success(self):
    """
    Record a successful operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CircuitBreaker

## _setup_protocol_handlers

```python
def _setup_protocol_handlers(self):
    """
    Set up protocol handlers for resilience operations.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## _start_health_checker

```python
def _start_health_checker(self):
    """
    Start the background health checker.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## add_failure

```python
def add_failure(self, node_id: str, error_message: str):
    """
    Add a failed node operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OperationResult

## add_success

```python
def add_success(self, node_id: str, result: Any = None):
    """
    Add a successful node operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OperationResult

## complete

```python
def complete(self, status: OperationStatus = OperationStatus.COMPLETED):
    """
    Mark the operation as complete.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OperationResult

## connect_to_peer_with_retry

```python
async def connect_to_peer_with_retry(self, peer_id: str, retry_config: Optional[RetryConfig] = None) -> bool:
    """
    Connect to a peer with automatic retries.

Args:
    peer_id: ID of the peer
    retry_config: Retry configuration

Returns:
    bool: True if connection successful

Raises:
    Exception: If connection fails after all retries
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## connect_with_circuit_breaker

```python
async def connect_with_circuit_breaker():
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## create_checkpoint

```python
def create_checkpoint(self, operation_id: str, completed_items: List[str], pending_items: List[str], metadata: Dict[str, Any] = None) -> Checkpoint:
    """
    Create a checkpoint for a long-running operation.

Args:
    operation_id: ID of the operation
    completed_items: IDs of completed items
    pending_items: IDs of pending items
    metadata: Additional metadata

Returns:
    Checkpoint: The created checkpoint
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## create_circuit_breaker

```python
def create_circuit_breaker(self, name: str, failure_threshold: int = DEFAULT_CIRCUIT_BREAKER_THRESHOLD, reset_timeout_sec: int = DEFAULT_CIRCUIT_BREAKER_RESET_TIMEOUT_SEC) -> CircuitBreaker:
    """
    Create a new circuit breaker.

Args:
    name: Name of the circuit breaker
    failure_threshold: Number of failures before opening the circuit
    reset_timeout_sec: Time in seconds before trying to close the circuit again

Returns:
    CircuitBreaker: The created circuit breaker
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## create_operation

```python
def create_operation(self, operation_type: str) -> OperationResult:
    """
    Create a new operation tracking object.

Args:
    operation_type: Type of operation

Returns:
    OperationResult: The created operation result
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## execute

```python
def execute(self, func: Callable[[], T]) -> T:
    """
    Execute a function with circuit breaker protection.

Args:
    func: Function to execute

Returns:
    The result of the function

Raises:
    Exception: If the circuit is open or the function fails
    """
```
* **Async:** False
* **Method:** True
* **Class:** CircuitBreaker

## execute_async

```python
async def execute_async(self, func: Callable[[], Awaitable[T]]) -> T:
    """
    Execute an async function with circuit breaker protection.

Args:
    func: Async function to execute

Returns:
    The result of the function

Raises:
    Exception: If the circuit is open or the function fails
    """
```
* **Async:** True
* **Method:** True
* **Class:** CircuitBreaker

## execute_on_healthy_nodes

```python
async def execute_on_healthy_nodes(self, func: Callable[[str], Awaitable[T]], min_success_count: int = 1, max_concurrent: int = 3, timeout_sec: int = 30) -> Dict[str, Union[T, Exception]]:
    """
    Execute a function on all healthy nodes.

Args:
    func: Async function to execute, taking node_id as parameter
    min_success_count: Minimum number of successful executions required
    max_concurrent: Maximum concurrent executions
    timeout_sec: Timeout in seconds

Returns:
    Dict[str, Union[T, Exception]]: Results for each node
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## execute_with_circuit_breaker

```python
def execute_with_circuit_breaker(self, circuit_name: str, func: Callable[[], T]) -> T:
    """
    Execute a function with circuit breaker protection.

Args:
    circuit_name: Name of the circuit breaker to use
    func: Function to execute

Returns:
    The result of the function

Raises:
    CircuitBreakerOpenError: If the circuit is open
    Exception: If the function fails
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## execute_with_circuit_breaker_async

```python
async def execute_with_circuit_breaker_async(self, circuit_name: str, func: Callable[[], Awaitable[T]]) -> T:
    """
    Execute an async function with circuit breaker protection.

Args:
    circuit_name: Name of the circuit breaker to use
    func: Async function to execute

Returns:
    The result of the function

Raises:
    CircuitBreakerOpenError: If the circuit is open
    Exception: If the function fails
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## execute_with_timeout

```python
async def execute_with_timeout(node_id):
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## find_consistent_data

```python
async def find_consistent_data(self, protocol: NetworkProtocol, request: Dict[str, Any], quorum_percentage: int = 51, timeout_ms: int = 5000) -> Tuple[Any, int]:
    """
    Query multiple nodes and return the data that a quorum agrees on.

Useful for ensuring consistency in a distributed system.

Args:
    protocol: Protocol to use
    request: Request data to send
    quorum_percentage: Percentage of nodes required for quorum
    timeout_ms: Timeout in milliseconds

Returns:
    Tuple[Any, int]: (consensus_data, agreement_count)
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## find_latest

```python
@classmethod
def find_latest(cls, directory: str, operation_id: str) -> Optional['Checkpoint']:
    """
    Find the latest checkpoint for an operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Checkpoint

## get_all_node_health

```python
def get_all_node_health(self) -> Dict[str, NodeHealth]:
    """
    Get health information for all known nodes.

Returns:
    Dict[str, NodeHealth]: Mapping of node IDs to health information
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## get_circuit_breaker

```python
def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
    """
    Get a circuit breaker by name.

Args:
    name: Name of the circuit breaker

Returns:
    CircuitBreaker: The circuit breaker or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## get_healthy_nodes

```python
def get_healthy_nodes(self) -> List[str]:
    """
    Get a list of healthy node IDs.

Returns:
    List[str]: List of healthy node IDs
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## get_latest_checkpoint

```python
def get_latest_checkpoint(self, operation_id: str) -> Optional[Checkpoint]:
    """
    Get the latest checkpoint for an operation.

Args:
    operation_id: ID of the operation

Returns:
    Checkpoint: The latest checkpoint or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## get_node_health

```python
def get_node_health(self, node_id: str) -> Optional[NodeHealth]:
    """
    Get health information for a node.

Args:
    node_id: ID of the node

Returns:
    NodeHealth: Health information or None if not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## get_operation

```python
def get_operation(self, operation_id: str) -> Optional[OperationResult]:
    """
    Get an operation by ID.

Args:
    operation_id: ID of the operation

Returns:
    OperationResult: The operation or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## get_operations_by_status

```python
def get_operations_by_status(self, status: OperationStatus) -> List[OperationResult]:
    """
    Get operations by status.

Args:
    status: Status to filter by

Returns:
    List[OperationResult]: Matching operations
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## is_partially_successful

```python
def is_partially_successful(self) -> bool:
    """
    Check if the operation was at least partially successful.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OperationResult

## is_successful

```python
def is_successful(self) -> bool:
    """
    Check if the operation was successful overall.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OperationResult

## lazy_broadcast

```python
async def lazy_broadcast(self, protocol: NetworkProtocol, data: Any, min_reach: int = 3, timeout_ms: int = 5000) -> Tuple[int, int]:
    """
    Broadcast a message with a lazy propagation strategy.

Instead of sending to all nodes, this sends to a subset and
lets the P2P network propagate the message.

Args:
    protocol: Protocol to use
    data: Data to send
    min_reach: Minimum number of nodes to reach directly
    timeout_ms: Timeout in milliseconds

Returns:
    Tuple[int, int]: (success_count, failure_count)
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## load

```python
@classmethod
def load(cls, filename: str) -> "Checkpoint":
    """
    Load checkpoint from file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Checkpoint

## query_node

```python
async def query_node(node_id):
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## rebalance_with_circuit_breaker

```python
async def rebalance_with_circuit_breaker():
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## record_failure

```python
def record_failure(self):
    """
    Record a failed operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** NodeHealth

## record_success

```python
def record_success(self):
    """
    Record a successful operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** NodeHealth

## reset

```python
def reset(self):
    """
    Manually reset the circuit to closed state.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CircuitBreaker

## resilient

```python
class resilient(object):
    """
    Decorator for making functions resilient with automatic retries.

Usage:
@resilient()
def my_function():
    # Function that might fail

@resilient(max_retries=5, initial_backoff_ms=200)
async def my_async_function():
    # Async function that might fail
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## resilient_dataset_sync

```python
async def resilient_dataset_sync(self, dataset_id: str, target_node_ids: List[str], max_concurrent: int = 3) -> OperationResult:
    """
    Synchronize dataset metadata with target nodes with resilience to failures.

Args:
    dataset_id: ID of the dataset to sync
    target_node_ids: IDs of target nodes
    max_concurrent: Maximum concurrent sync operations

Returns:
    OperationResult: Result of the operation
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## resilient_rebalance_shards

```python
async def resilient_rebalance_shards(self, dataset_id: Optional[str] = None, target_replication: int = 3, max_concurrent: int = 3, use_healthy_nodes_only: bool = True) -> OperationResult:
    """
    Rebalance shards with resilience to failures.

Args:
    dataset_id: ID of the dataset to rebalance (all datasets if None)
    target_replication: Target replication factor
    max_concurrent: Maximum concurrent transfers
    use_healthy_nodes_only: Only use nodes marked as healthy

Returns:
    OperationResult: Result of the operation
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## resilient_shard_transfer

```python
async def resilient_shard_transfer(self, shard_id: str, target_node_ids: List[str], alternative_nodes: Optional[List[str]] = None) -> OperationResult:
    """
    Transfer a shard to target nodes with resilience to failures.

Args:
    shard_id: ID of the shard to transfer
    target_node_ids: IDs of target nodes
    alternative_nodes: Alternative nodes to try if primary targets fail

Returns:
    OperationResult: Result of the operation
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## retry

```python
def retry(self, func: Callable[[], T], config: Optional[RetryConfig] = None) -> T:
    """
    Execute a function with automatic retries.

Args:
    func: Function to execute
    config: Retry configuration (uses default if None)

Returns:
    The result of the function

Raises:
    Exception: If all retries fail
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## retry_async

```python
async def retry_async(self, func: Callable[[], Awaitable[T]], config: Optional[RetryConfig] = None) -> T:
    """
    Execute an async function with automatic retries.

Args:
    func: Async function to execute
    config: Retry configuration (uses default if None)

Returns:
    The result of the function

Raises:
    Exception: If all retries fail
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## save

```python
def save(self, directory: str):
    """
    Save checkpoint to file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Checkpoint

## select_best_nodes

```python
def select_best_nodes(self, count: int, exclude_nodes: List[str] = None) -> List[str]:
    """
    Select the best nodes based on health metrics.

Args:
    count: Number of nodes to select
    exclude_nodes: Nodes to exclude from selection

Returns:
    List[str]: Selected node IDs
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## send_message_with_retry

```python
async def send_message_with_retry(self, peer_id: str, protocol: NetworkProtocol, data: Any, timeout_ms: int = DEFAULT_REQUEST_TIMEOUT_MS, retry_config: Optional[RetryConfig] = None) -> Any:
    """
    Send a message to a peer with automatic retries.

Args:
    peer_id: ID of the peer
    protocol: Protocol to use
    data: Data to send
    timeout_ms: Timeout in milliseconds
    retry_config: Retry configuration

Returns:
    The response from the peer

Raises:
    Exception: If sending fails after all retries
    """
```
* **Async:** True
* **Method:** True
* **Class:** ResilienceManager

## send_to_node

```python
async def send_to_node(node_id):
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## send_with_circuit_breaker

```python
async def send_with_circuit_breaker():
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## shutdown

```python
def shutdown(self):
    """
    Shutdown the resilience manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResilienceManager

## sync_with_circuit_breaker

```python
async def sync_with_circuit_breaker():
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## sync_with_node

```python
async def sync_with_node(node_id):
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary for serialization.
    """
```
* **Async:** False
* **Method:** True
* **Class:** NodeHealth

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary for serialization.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OperationResult

## transfer_with_circuit_breaker

```python
async def transfer_with_circuit_breaker():
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## transfer_with_circuit_breaker

```python
async def transfer_with_circuit_breaker():
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## update_response_time

```python
def update_response_time(self, response_time_ms: int, max_samples: int = 10):
    """
    Update response time metrics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** NodeHealth

## wrapper

```python
@asyncio.coroutine
async def wrapper(*args, **kwargs):
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## wrapper

```python
def wrapper(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A
