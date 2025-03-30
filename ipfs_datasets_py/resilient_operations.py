"""
Resilient Operations Module for IPFS Datasets.

This module provides enhanced resilience mechanisms for distributed operations across
IPFS nodes, ensuring robust performance even in the face of node failures, network
partitions, and other distributed system challenges.

Key features:
- Automatic retry with exponential backoff for failed operations
- Circuit breaker pattern to prevent cascading failures
- Health checking and monitoring for connected nodes
- Graceful degradation with partial failure handling
- Timeout management and resource constraints
- Automatic recovery from interrupted operations
- Prioritized node selection based on reliability metrics
- Checkpointing for long-running operations
"""

import os
import time
import random
import logging
import asyncio
import heapq
import json
import threading
import socket
from typing import Dict, List, Any, Optional, Union, Set, Callable, Tuple, TypeVar, Awaitable
from dataclasses import dataclass, field, asdict
from enum import Enum
import concurrent.futures
from datetime import datetime, timedelta

# Import our own modules
from ipfs_datasets_py.libp2p_kit import (
    P2PError,
    NetworkProtocol,
    LibP2PNotAvailableError,
    NodeConnectionError,
    ShardTransferError,
    DatasetShardManager,
    LibP2PNode
)

# Type variables
T = TypeVar('T')
K = TypeVar('K')

# Constants
DEFAULT_RETRY_COUNT = 3
DEFAULT_INITIAL_BACKOFF_MS = 100
DEFAULT_MAX_BACKOFF_MS = 5000
DEFAULT_BACKOFF_FACTOR = 2
DEFAULT_JITTER_FACTOR = 0.1
DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 5
DEFAULT_CIRCUIT_BREAKER_RESET_TIMEOUT_SEC = 30
DEFAULT_HEALTH_CHECK_INTERVAL_SEC = 60
DEFAULT_HEALTH_CHECK_TIMEOUT_MS = 2000
DEFAULT_REQUEST_TIMEOUT_MS = 10000
DEFAULT_NODE_FAILURE_THRESHOLD = 3

# Logging configuration
logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status of a node in the network."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class OperationStatus(Enum):
    """Status of a distributed operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    RECOVERED = "recovered"


@dataclass
class NodeHealth:
    """Health information for a node."""
    node_id: str
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check_time: Optional[float] = None
    response_times_ms: List[int] = field(default_factory=list)
    avg_response_time_ms: float = 0
    failure_count: int = 0
    last_failure_time: Optional[float] = None
    availability_score: float = 0.0  # 0.0 to 1.0
    capabilities: Dict[str, Any] = field(default_factory=dict)
    load_metrics: Dict[str, Any] = field(default_factory=dict)

    def update_response_time(self, response_time_ms: int, max_samples: int = 10):
        """Update response time metrics."""
        self.response_times_ms.append(response_time_ms)
        
        # Keep only the most recent samples
        if len(self.response_times_ms) > max_samples:
            self.response_times_ms = self.response_times_ms[-max_samples:]
        
        # Update average
        self.avg_response_time_ms = sum(self.response_times_ms) / len(self.response_times_ms)
    
    def record_success(self):
        """Record a successful operation."""
        self.last_check_time = time.time()
        self.status = HealthStatus.HEALTHY
        
        # Improve availability score
        self.availability_score = min(1.0, self.availability_score + 0.1)
    
    def record_failure(self):
        """Record a failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        # Degrade availability score
        self.availability_score = max(0.0, self.availability_score - 0.2)
        
        # Update status based on failure count
        if self.failure_count >= DEFAULT_NODE_FAILURE_THRESHOLD:
            self.status = HealthStatus.UNHEALTHY
        else:
            self.status = HealthStatus.DEGRADED
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_id": self.node_id,
            "status": self.status.value,
            "last_check_time": self.last_check_time,
            "avg_response_time_ms": self.avg_response_time_ms,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "availability_score": self.availability_score,
            "capabilities": self.capabilities,
            "load_metrics": self.load_metrics
        }


@dataclass
class CircuitBreaker:
    """
    Implements the circuit breaker pattern to prevent cascading failures.
    
    The circuit breaker has three states:
    - CLOSED: Operations are allowed to proceed normally
    - OPEN: Operations immediately fail without attempting execution
    - HALF_OPEN: A limited number of operations are allowed to test if the system has recovered
    """
    name: str
    failure_threshold: int = DEFAULT_CIRCUIT_BREAKER_THRESHOLD
    reset_timeout_sec: int = DEFAULT_CIRCUIT_BREAKER_RESET_TIMEOUT_SEC
    
    # State
    failures: int = 0
    state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    trip_time: Optional[float] = None
    
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
        self._check_state()
        
        if self.state == "OPEN":
            raise CircuitBreakerOpenError(f"Circuit '{self.name}' is open")
        
        try:
            result = func()
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            raise
    
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
        self._check_state()
        
        if self.state == "OPEN":
            raise CircuitBreakerOpenError(f"Circuit '{self.name}' is open")
        
        try:
            result = await func()
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            raise
    
    def _check_state(self):
        """Check and update the circuit state."""
        now = time.time()
        
        if self.state == "OPEN":
            # Check if reset timeout has elapsed
            if self.trip_time and now - self.trip_time >= self.reset_timeout_sec:
                self.state = "HALF_OPEN"
                logger.info(f"Circuit '{self.name}' changed from OPEN to HALF_OPEN")
    
    def _record_success(self):
        """Record a successful operation."""
        self.last_success_time = time.time()
        
        if self.state == "HALF_OPEN":
            # Reset the circuit
            self.state = "CLOSED"
            self.failures = 0
            logger.info(f"Circuit '{self.name}' changed from HALF_OPEN to CLOSED")
    
    def _record_failure(self):
        """Record a failed operation."""
        now = time.time()
        self.last_failure_time = now
        
        if self.state == "CLOSED":
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.state = "OPEN"
                self.trip_time = now
                logger.warning(f"Circuit '{self.name}' tripped to OPEN after {self.failures} failures")
        elif self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.trip_time = now
            logger.warning(f"Circuit '{self.name}' returned to OPEN from HALF_OPEN due to failure")
    
    def reset(self):
        """Manually reset the circuit to closed state."""
        self.state = "CLOSED"
        self.failures = 0
        self.trip_time = None
        logger.info(f"Circuit '{self.name}' manually reset to CLOSED")


class CircuitBreakerOpenError(Exception):
    """Exception raised when a circuit breaker is open."""
    pass


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = DEFAULT_RETRY_COUNT
    initial_backoff_ms: int = DEFAULT_INITIAL_BACKOFF_MS
    max_backoff_ms: int = DEFAULT_MAX_BACKOFF_MS
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
    jitter_factor: float = DEFAULT_JITTER_FACTOR
    retry_on_exceptions: List[type] = field(default_factory=list)
    
    def __post_init__(self):
        # Default retry on P2PError if not specified
        if not self.retry_on_exceptions:
            self.retry_on_exceptions = [P2PError, ConnectionError, TimeoutError]


@dataclass
class OperationResult:
    """Result of a distributed operation."""
    operation_id: str
    status: OperationStatus
    start_time: float
    end_time: Optional[float] = None
    success_count: int = 0
    failure_count: int = 0
    affected_nodes: List[str] = field(default_factory=list)
    successful_nodes: List[str] = field(default_factory=list)
    failed_nodes: Dict[str, str] = field(default_factory=dict)  # node_id -> error message
    results: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    execution_time_ms: int = 0
    
    def add_success(self, node_id: str, result: Any = None):
        """Add a successful node operation."""
        self.success_count += 1
        if node_id not in self.successful_nodes:
            self.successful_nodes.append(node_id)
        
        if node_id not in self.affected_nodes:
            self.affected_nodes.append(node_id)
        
        if result is not None:
            self.results[node_id] = result
    
    def add_failure(self, node_id: str, error_message: str):
        """Add a failed node operation."""
        self.failure_count += 1
        self.failed_nodes[node_id] = error_message
        
        if node_id not in self.affected_nodes:
            self.affected_nodes.append(node_id)
    
    def complete(self, status: OperationStatus = OperationStatus.COMPLETED):
        """Mark the operation as complete."""
        self.end_time = time.time()
        self.execution_time_ms = int((self.end_time - self.start_time) * 1000)
        
        # Determine final status if not specified
        if status == OperationStatus.COMPLETED:
            if self.failure_count == 0:
                self.status = OperationStatus.COMPLETED
            elif self.success_count > 0:
                self.status = OperationStatus.PARTIALLY_COMPLETED
            else:
                self.status = OperationStatus.FAILED
        else:
            self.status = status
        
        return self
    
    def is_successful(self) -> bool:
        """Check if the operation was successful overall."""
        return self.status == OperationStatus.COMPLETED
    
    def is_partially_successful(self) -> bool:
        """Check if the operation was at least partially successful."""
        return self.status in [OperationStatus.COMPLETED, OperationStatus.PARTIALLY_COMPLETED]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "operation_id": self.operation_id,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "affected_nodes": self.affected_nodes,
            "successful_nodes": self.successful_nodes,
            "failed_nodes": self.failed_nodes,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message
        }


@dataclass
class Checkpoint:
    """Checkpoint for resumable operations."""
    operation_id: str
    checkpoint_id: str = field(default_factory=lambda: f"cp_{int(time.time())}")
    timestamp: float = field(default_factory=time.time)
    completed_items: List[str] = field(default_factory=list)
    pending_items: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def save(self, directory: str):
        """Save checkpoint to file."""
        os.makedirs(directory, exist_ok=True)
        
        # Create filename
        filename = os.path.join(directory, f"{self.operation_id}_{self.checkpoint_id}.json")
        
        # Write to file
        with open(filename, "w") as f:
            json.dump(asdict(self), f)
        
        return filename
    
    @classmethod
    def load(cls, filename: str) -> 'Checkpoint':
        """Load checkpoint from file."""
        with open(filename, "r") as f:
            data = json.load(f)
        
        return cls(**data)
    
    @classmethod
    def find_latest(cls, directory: str, operation_id: str) -> Optional['Checkpoint']:
        """Find the latest checkpoint for an operation."""
        prefix = f"{operation_id}_cp_"
        checkpoint_files = [
            f for f in os.listdir(directory)
            if f.startswith(prefix) and f.endswith(".json")
        ]
        
        if not checkpoint_files:
            return None
        
        # Sort by timestamp in filename
        checkpoint_files.sort(reverse=True)
        latest_file = os.path.join(directory, checkpoint_files[0])
        
        return cls.load(latest_file)


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
    
    def __init__(
        self,
        max_retries: int = DEFAULT_RETRY_COUNT,
        initial_backoff_ms: int = DEFAULT_INITIAL_BACKOFF_MS,
        max_backoff_ms: int = DEFAULT_MAX_BACKOFF_MS,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        jitter_factor: float = DEFAULT_JITTER_FACTOR,
        retry_on_exceptions: List[type] = None
    ):
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
        self.config = RetryConfig(
            max_retries=max_retries,
            initial_backoff_ms=initial_backoff_ms,
            max_backoff_ms=max_backoff_ms,
            backoff_factor=backoff_factor,
            jitter_factor=jitter_factor,
            retry_on_exceptions=retry_on_exceptions or []
        )
    
    def __call__(self, func):
        """Apply the decorator to the function."""
        
        # Handle both async and sync functions
        if asyncio.iscoroutinefunction(func):
            @asyncio.coroutine
            async def wrapper(*args, **kwargs):
                return await self._execute_async(func, args, kwargs)
            return wrapper
        else:
            def wrapper(*args, **kwargs):
                return self._execute_sync(func, args, kwargs)
            return wrapper
    
    def _execute_sync(self, func, args, kwargs):
        """Execute a synchronous function with retries."""
        retry_count = 0
        last_exception = None
        
        while retry_count <= self.config.max_retries:
            try:
                return func(*args, **kwargs)
            except tuple(self.config.retry_on_exceptions) as e:
                last_exception = e
                retry_count += 1
                
                if retry_count > self.config.max_retries:
                    break
                
                # Calculate backoff time
                backoff_ms = min(
                    self.config.initial_backoff_ms * (self.config.backoff_factor ** (retry_count - 1)),
                    self.config.max_backoff_ms
                )
                
                # Add jitter
                jitter = random.uniform(-self.config.jitter_factor, self.config.jitter_factor)
                backoff_ms = backoff_ms * (1 + jitter)
                
                # Log retry attempt
                logger.info(
                    f"Retrying {func.__name__} after error: {str(e)}. "
                    f"Retry {retry_count}/{self.config.max_retries} in {backoff_ms:.1f}ms"
                )
                
                # Sleep for backoff time
                time.sleep(backoff_ms / 1000)
            except Exception as e:
                # Don't retry on non-retryable exceptions
                raise
        
        # If we get here, all retries failed
        logger.error(f"All {self.config.max_retries} retries failed for {func.__name__}")
        raise last_exception
    
    async def _execute_async(self, func, args, kwargs):
        """Execute an asynchronous function with retries."""
        retry_count = 0
        last_exception = None
        
        while retry_count <= self.config.max_retries:
            try:
                return await func(*args, **kwargs)
            except tuple(self.config.retry_on_exceptions) as e:
                last_exception = e
                retry_count += 1
                
                if retry_count > self.config.max_retries:
                    break
                
                # Calculate backoff time
                backoff_ms = min(
                    self.config.initial_backoff_ms * (self.config.backoff_factor ** (retry_count - 1)),
                    self.config.max_backoff_ms
                )
                
                # Add jitter
                jitter = random.uniform(-self.config.jitter_factor, self.config.jitter_factor)
                backoff_ms = backoff_ms * (1 + jitter)
                
                # Log retry attempt
                logger.info(
                    f"Retrying {func.__name__} after error: {str(e)}. "
                    f"Retry {retry_count}/{self.config.max_retries} in {backoff_ms:.1f}ms"
                )
                
                # Sleep for backoff time
                await asyncio.sleep(backoff_ms / 1000)
            except Exception as e:
                # Don't retry on non-retryable exceptions
                raise
        
        # If we get here, all retries failed
        logger.error(f"All {self.config.max_retries} retries failed for {func.__name__}")
        raise last_exception


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
    
    def __init__(
        self,
        node: LibP2PNode,
        storage_dir: Optional[str] = None,
        health_check_interval_sec: int = DEFAULT_HEALTH_CHECK_INTERVAL_SEC,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
        retry_config: Optional[RetryConfig] = None
    ):
        """
        Initialize the resilience manager.
        
        Args:
            node: The P2P node for network communication
            storage_dir: Directory for storing resilience data
            health_check_interval_sec: Interval for node health checks
            circuit_breaker_config: Circuit breaker configuration
            retry_config: Default retry configuration
        """
        self.node = node
        self.storage_dir = storage_dir or os.path.join(
            os.getcwd(), ".ipfs_datasets", "resilience"
        )
        self.health_check_interval_sec = health_check_interval_sec
        
        # Create storage directories
        os.makedirs(os.path.join(self.storage_dir, "checkpoints"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "health_data"), exist_ok=True)
        
        # Initialize state
        self.node_health: Dict[str, NodeHealth] = {}
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.operations: Dict[str, OperationResult] = {}
        
        # Create circuit breakers
        cb_config = circuit_breaker_config or {}
        self._create_circuit_breakers(cb_config)
        
        # Set default retry config
        self.retry_config = retry_config or RetryConfig()
        
        # Start health check scheduler
        self._start_health_checker()
        
        # Register protocol handlers
        self._setup_protocol_handlers()
        
        # Status
        self.running = True
    
    def _create_circuit_breakers(self, config: Dict[str, Any]):
        """Create default circuit breakers for common operations."""
        default_circuits = [
            "node_connection",
            "message_send",
            "message_receive",
            "shard_transfer",
            "dataset_sync",
            "search"
        ]
        
        for circuit_name in default_circuits:
            threshold = config.get(f"{circuit_name}_threshold", DEFAULT_CIRCUIT_BREAKER_THRESHOLD)
            timeout = config.get(f"{circuit_name}_timeout", DEFAULT_CIRCUIT_BREAKER_RESET_TIMEOUT_SEC)
            
            self.circuit_breakers[circuit_name] = CircuitBreaker(
                name=circuit_name,
                failure_threshold=threshold,
                reset_timeout_sec=timeout
            )
    
    def _setup_protocol_handlers(self):
        """Set up protocol handlers for resilience operations."""
        if hasattr(self.node, 'register_protocol_handler'):
            # Register health check handler
            self.node.register_protocol_handler(
                NetworkProtocol.HEALTH_CHECK,
                self._handle_health_check
            )
    
    def _start_health_checker(self):
        """Start the background health checker."""
        checker_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True
        )
        checker_thread.start()
    
    def _health_check_loop(self):
        """Background loop for conducting health checks."""
        while self.running:
            # Sleep first to allow initialization to complete
            time.sleep(self.health_check_interval_sec)
            
            try:
                # Get all known peers
                if hasattr(self.node, 'get_connected_peers'):
                    peers = self.node.get_connected_peers()
                    
                    # Check each peer
                    for peer_id in peers:
                        # Skip check if too recent
                        if peer_id in self.node_health:
                            last_check = self.node_health[peer_id].last_check_time
                            if last_check and time.time() - last_check < self.health_check_interval_sec:
                                continue
                        
                        # Perform health check asynchronously
                        asyncio.run(self._check_node_health(peer_id))
            except Exception as e:
                logger.error(f"Error in health check loop: {str(e)}")
    
    async def _check_node_health(self, node_id: str):
        """
        Perform a health check on a node.
        
        Args:
            node_id: ID of the node to check
        """
        # Initialize health record if needed
        if node_id not in self.node_health:
            self.node_health[node_id] = NodeHealth(node_id=node_id)
        
        try:
            # Measure response time
            start_time = time.time()
            
            # Send health check request
            response = await self.node.send_message(
                peer_id=node_id,
                protocol=NetworkProtocol.HEALTH_CHECK,
                data={"action": "health_check", "requester_id": self.node.node_id},
                timeout_ms=DEFAULT_HEALTH_CHECK_TIMEOUT_MS
            )
            
            # Calculate response time
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Update health record
            health_record = self.node_health[node_id]
            health_record.update_response_time(response_time_ms)
            health_record.record_success()
            
            # Update with capabilities and load info from response
            if isinstance(response, dict):
                if "capabilities" in response:
                    health_record.capabilities = response["capabilities"]
                if "load_metrics" in response:
                    health_record.load_metrics = response["load_metrics"]
            
            logger.debug(f"Health check for {node_id} successful: {response_time_ms}ms")
            
        except Exception as e:
            # Record failure
            health_record = self.node_health[node_id]
            health_record.record_failure()
            
            logger.warning(f"Health check for {node_id} failed: {str(e)}")
    
    async def _handle_health_check(self, stream):
        """
        Handle incoming health check requests.
        
        Args:
            stream: The network stream
        """
        try:
            # Read request data
            data = await stream.read()
            request = json.loads(data.decode())
            
            # Prepare response with capabilities and load metrics
            response = {
                "status": "healthy",
                "node_id": self.node.node_id,
                "timestamp": time.time(),
                "capabilities": self._get_node_capabilities(),
                "load_metrics": self._get_load_metrics()
            }
            
            # Send response
            await stream.write(json.dumps(response).encode())
        except Exception as e:
            # Handle errors
            logger.error(f"Error handling health check: {str(e)}")
            try:
                error_response = {
                    "status": "error",
                    "message": str(e),
                    "node_id": self.node.node_id
                }
                await stream.write(json.dumps(error_response).encode())
            except:
                pass
        finally:
            # Always close the stream
            await stream.close()
    
    def _get_node_capabilities(self) -> Dict[str, Any]:
        """Get capabilities of this node."""
        capabilities = {
            "roles": [],
            "protocols": [],
            "features": []
        }
        
        # Detect node role
        if hasattr(self.node, 'role'):
            capabilities["roles"].append(self.node.role)
        
        # Detect protocols
        if hasattr(self.node, 'supported_protocols'):
            capabilities["protocols"] = [p.value for p in self.node.supported_protocols]
        
        # Detect features based on available managers
        if hasattr(self.node, 'shard_manager'):
            capabilities["features"].append("shard_management")
        
        return capabilities
    
    def _get_load_metrics(self) -> Dict[str, Any]:
        """Get load metrics for this node."""
        metrics = {
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "disk_percent": 0.0,
            "network_connections": 0,
            "active_operations": 0
        }
        
        try:
            import psutil
            
            # CPU
            metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            
            # Memory
            memory = psutil.virtual_memory()
            metrics["memory_percent"] = memory.percent
            
            # Disk
            disk = psutil.disk_usage('/')
            metrics["disk_percent"] = disk.percent
            
            # Network connections
            metrics["network_connections"] = len(psutil.net_connections())
            
        except ImportError:
            # psutil not available, use minimal metrics
            metrics["active_operations"] = len(self.operations)
        
        return metrics
    
    def get_node_health(self, node_id: str) -> Optional[NodeHealth]:
        """
        Get health information for a node.
        
        Args:
            node_id: ID of the node
            
        Returns:
            NodeHealth: Health information or None if not available
        """
        return self.node_health.get(node_id)
    
    def get_all_node_health(self) -> Dict[str, NodeHealth]:
        """
        Get health information for all known nodes.
        
        Returns:
            Dict[str, NodeHealth]: Mapping of node IDs to health information
        """
        return self.node_health
    
    def get_healthy_nodes(self) -> List[str]:
        """
        Get a list of healthy node IDs.
        
        Returns:
            List[str]: List of healthy node IDs
        """
        return [
            node_id for node_id, health in self.node_health.items()
            if health.status == HealthStatus.HEALTHY
        ]
    
    def select_best_nodes(self, count: int, exclude_nodes: List[str] = None) -> List[str]:
        """
        Select the best nodes based on health metrics.
        
        Args:
            count: Number of nodes to select
            exclude_nodes: Nodes to exclude from selection
            
        Returns:
            List[str]: Selected node IDs
        """
        exclude_set = set(exclude_nodes or [])
        
        # Sort nodes by availability score (descending)
        sorted_nodes = sorted(
            [
                (node_id, health) for node_id, health in self.node_health.items()
                if node_id not in exclude_set and health.status != HealthStatus.UNHEALTHY
            ],
            key=lambda x: x[1].availability_score,
            reverse=True
        )
        
        # Take the top nodes
        return [node_id for node_id, _ in sorted_nodes[:count]]
    
    def create_circuit_breaker(
        self,
        name: str,
        failure_threshold: int = DEFAULT_CIRCUIT_BREAKER_THRESHOLD,
        reset_timeout_sec: int = DEFAULT_CIRCUIT_BREAKER_RESET_TIMEOUT_SEC
    ) -> CircuitBreaker:
        """
        Create a new circuit breaker.
        
        Args:
            name: Name of the circuit breaker
            failure_threshold: Number of failures before opening the circuit
            reset_timeout_sec: Time in seconds before trying to close the circuit again
            
        Returns:
            CircuitBreaker: The created circuit breaker
        """
        breaker = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            reset_timeout_sec=reset_timeout_sec
        )
        
        self.circuit_breakers[name] = breaker
        return breaker
    
    def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """
        Get a circuit breaker by name.
        
        Args:
            name: Name of the circuit breaker
            
        Returns:
            CircuitBreaker: The circuit breaker or None if not found
        """
        return self.circuit_breakers.get(name)
    
    def execute_with_circuit_breaker(
        self,
        circuit_name: str,
        func: Callable[[], T]
    ) -> T:
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
        breaker = self.get_circuit_breaker(circuit_name)
        if not breaker:
            # No circuit breaker, execute directly
            return func()
        
        return breaker.execute(func)
    
    async def execute_with_circuit_breaker_async(
        self,
        circuit_name: str,
        func: Callable[[], Awaitable[T]]
    ) -> T:
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
        breaker = self.get_circuit_breaker(circuit_name)
        if not breaker:
            # No circuit breaker, execute directly
            return await func()
        
        return await breaker.execute_async(func)
    
    async def retry_async(
        self,
        func: Callable[[], Awaitable[T]],
        config: Optional[RetryConfig] = None
    ) -> T:
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
        retry_config = config or self.retry_config
        retry_count = 0
        last_exception = None
        
        while retry_count <= retry_config.max_retries:
            try:
                return await func()
            except tuple(retry_config.retry_on_exceptions) as e:
                last_exception = e
                retry_count += 1
                
                if retry_count > retry_config.max_retries:
                    break
                
                # Calculate backoff time
                backoff_ms = min(
                    retry_config.initial_backoff_ms * (retry_config.backoff_factor ** (retry_count - 1)),
                    retry_config.max_backoff_ms
                )
                
                # Add jitter
                jitter = random.uniform(-retry_config.jitter_factor, retry_config.jitter_factor)
                backoff_ms = backoff_ms * (1 + jitter)
                
                # Log retry attempt
                logger.info(
                    f"Retrying after error: {str(e)}. "
                    f"Retry {retry_count}/{retry_config.max_retries} in {backoff_ms:.1f}ms"
                )
                
                # Sleep for backoff time
                await asyncio.sleep(backoff_ms / 1000)
            except Exception as e:
                # Don't retry on non-retryable exceptions
                raise
        
        # If we get here, all retries failed
        logger.error(f"All {retry_config.max_retries} retries failed")
        raise last_exception
    
    def retry(
        self,
        func: Callable[[], T],
        config: Optional[RetryConfig] = None
    ) -> T:
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
        retry_config = config or self.retry_config
        retry_count = 0
        last_exception = None
        
        while retry_count <= retry_config.max_retries:
            try:
                return func()
            except tuple(retry_config.retry_on_exceptions) as e:
                last_exception = e
                retry_count += 1
                
                if retry_count > retry_config.max_retries:
                    break
                
                # Calculate backoff time
                backoff_ms = min(
                    retry_config.initial_backoff_ms * (retry_config.backoff_factor ** (retry_count - 1)),
                    retry_config.max_backoff_ms
                )
                
                # Add jitter
                jitter = random.uniform(-retry_config.jitter_factor, retry_config.jitter_factor)
                backoff_ms = backoff_ms * (1 + jitter)
                
                # Log retry attempt
                logger.info(
                    f"Retrying after error: {str(e)}. "
                    f"Retry {retry_count}/{retry_config.max_retries} in {backoff_ms:.1f}ms"
                )
                
                # Sleep for backoff time
                time.sleep(backoff_ms / 1000)
            except Exception as e:
                # Don't retry on non-retryable exceptions
                raise
        
        # If we get here, all retries failed
        logger.error(f"All {retry_config.max_retries} retries failed")
        raise last_exception
    
    def create_operation(self, operation_type: str) -> OperationResult:
        """
        Create a new operation tracking object.
        
        Args:
            operation_type: Type of operation
            
        Returns:
            OperationResult: The created operation result
        """
        operation_id = f"{operation_type}_{int(time.time())}_{random.randint(1000, 9999)}"
        operation = OperationResult(
            operation_id=operation_id,
            status=OperationStatus.PENDING,
            start_time=time.time()
        )
        
        self.operations[operation_id] = operation
        return operation
    
    def get_operation(self, operation_id: str) -> Optional[OperationResult]:
        """
        Get an operation by ID.
        
        Args:
            operation_id: ID of the operation
            
        Returns:
            OperationResult: The operation or None if not found
        """
        return self.operations.get(operation_id)
    
    def create_checkpoint(
        self,
        operation_id: str,
        completed_items: List[str],
        pending_items: List[str],
        metadata: Dict[str, Any] = None
    ) -> Checkpoint:
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
        checkpoint = Checkpoint(
            operation_id=operation_id,
            completed_items=completed_items,
            pending_items=pending_items,
            metadata=metadata or {}
        )
        
        # Save to disk
        checkpoint_dir = os.path.join(self.storage_dir, "checkpoints")
        checkpoint.save(checkpoint_dir)
        
        return checkpoint
    
    def get_latest_checkpoint(self, operation_id: str) -> Optional[Checkpoint]:
        """
        Get the latest checkpoint for an operation.
        
        Args:
            operation_id: ID of the operation
            
        Returns:
            Checkpoint: The latest checkpoint or None if not found
        """
        checkpoint_dir = os.path.join(self.storage_dir, "checkpoints")
        return Checkpoint.find_latest(checkpoint_dir, operation_id)
    
    async def send_message_with_retry(
        self,
        peer_id: str,
        protocol: NetworkProtocol,
        data: Any,
        timeout_ms: int = DEFAULT_REQUEST_TIMEOUT_MS,
        retry_config: Optional[RetryConfig] = None
    ) -> Any:
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
        # Mark node as unhealthy if recent failures exceed threshold
        if peer_id in self.node_health:
            health = self.node_health[peer_id]
            if health.status == HealthStatus.UNHEALTHY:
                logger.warning(f"Node {peer_id} is marked as unhealthy, using circuit breaker")
        
        # Create circuit breaker function
        async def send_with_circuit_breaker():
            return await self.execute_with_circuit_breaker_async(
                "message_send",
                lambda: self.node.send_message(peer_id, protocol, data, timeout_ms)
            )
        
        # Execute with retries
        return await self.retry_async(send_with_circuit_breaker, retry_config)
    
    async def connect_to_peer_with_retry(
        self,
        peer_id: str,
        retry_config: Optional[RetryConfig] = None
    ) -> bool:
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
        if not hasattr(self.node, 'connect_to_peer'):
            raise NotImplementedError("Node does not support connect_to_peer")
        
        # Create circuit breaker function
        async def connect_with_circuit_breaker():
            return await self.execute_with_circuit_breaker_async(
                "node_connection",
                lambda: self.node.connect_to_peer(peer_id)
            )
        
        # Execute with retries
        return await self.retry_async(connect_with_circuit_breaker, retry_config)
    
    async def resilient_shard_transfer(
        self,
        shard_id: str,
        target_node_ids: List[str],
        alternative_nodes: Optional[List[str]] = None
    ) -> OperationResult:
        """
        Transfer a shard to target nodes with resilience to failures.
        
        Args:
            shard_id: ID of the shard to transfer
            target_node_ids: IDs of target nodes
            alternative_nodes: Alternative nodes to try if primary targets fail
            
        Returns:
            OperationResult: Result of the operation
        """
        if not hasattr(self.node, 'shard_manager'):
            raise NotImplementedError("Node does not have a shard manager")
        
        # Create operation tracker
        operation = self.create_operation("shard_transfer")
        
        # Get shard from manager
        shard = self.node.shard_manager.get_shard(shard_id)
        if not shard:
            operation.error_message = f"Shard {shard_id} not found"
            return operation.complete(OperationStatus.FAILED)
        
        # Try transfer to each target node
        for node_id in target_node_ids:
            try:
                # Send with circuit breaker and retry
                async def transfer_with_circuit_breaker():
                    return await self.execute_with_circuit_breaker_async(
                        "shard_transfer",
                        lambda: self.node.shard_manager.transfer_shard(shard_id, node_id)
                    )
                
                result = await self.retry_async(transfer_with_circuit_breaker)
                
                # Record success
                operation.add_success(node_id, result)
                
                # Update node health
                if node_id in self.node_health:
                    self.node_health[node_id].record_success()
                
            except Exception as e:
                # Record failure
                operation.add_failure(node_id, str(e))
                
                # Update node health
                if node_id in self.node_health:
                    self.node_health[node_id].record_failure()
                
                logger.warning(f"Failed to transfer shard {shard_id} to node {node_id}: {str(e)}")
        
        # If any primary targets failed, try alternatives
        if operation.failure_count > 0 and alternative_nodes:
            failed_count = operation.failure_count
            logger.info(f"Trying alternative nodes for {failed_count} failed transfers")
            
            # Get untried alternatives
            untried_alternatives = [
                node for node in alternative_nodes
                if node not in operation.affected_nodes
            ]
            
            # Try transferring to alternatives (up to the number of failures)
            alternatives_to_try = untried_alternatives[:failed_count]
            
            for node_id in alternatives_to_try:
                try:
                    # Send with circuit breaker and retry
                    async def transfer_with_circuit_breaker():
                        return await self.execute_with_circuit_breaker_async(
                            "shard_transfer",
                            lambda: self.node.shard_manager.transfer_shard(shard_id, node_id)
                        )
                    
                    result = await self.retry_async(transfer_with_circuit_breaker)
                    
                    # Record success
                    operation.add_success(node_id, result)
                    
                    # Update node health
                    if node_id in self.node_health:
                        self.node_health[node_id].record_success()
                    
                except Exception as e:
                    # Record failure
                    operation.add_failure(node_id, str(e))
                    
                    # Update node health
                    if node_id in self.node_health:
                        self.node_health[node_id].record_failure()
                    
                    logger.warning(f"Failed to transfer shard {shard_id} to alternative node {node_id}: {str(e)}")
        
        # Complete operation
        return operation.complete()
    
    async def resilient_dataset_sync(
        self,
        dataset_id: str,
        target_node_ids: List[str],
        max_concurrent: int = 3
    ) -> OperationResult:
        """
        Synchronize dataset metadata with target nodes with resilience to failures.
        
        Args:
            dataset_id: ID of the dataset to sync
            target_node_ids: IDs of target nodes
            max_concurrent: Maximum concurrent sync operations
            
        Returns:
            OperationResult: Result of the operation
        """
        if not hasattr(self.node, 'shard_manager'):
            raise NotImplementedError("Node does not have a shard manager")
        
        # Create operation tracker
        operation = self.create_operation("dataset_sync")
        
        # Get dataset from manager
        dataset = self.node.shard_manager.get_dataset(dataset_id)
        if not dataset:
            operation.error_message = f"Dataset {dataset_id} not found"
            return operation.complete(OperationStatus.FAILED)
        
        # Run sync operations concurrently in batches
        for i in range(0, len(target_node_ids), max_concurrent):
            batch = target_node_ids[i:i+max_concurrent]
            tasks = []
            
            for node_id in batch:
                # Create sync task
                async def sync_with_node(node_id):
                    try:
                        # Sync with circuit breaker and retry
                        async def sync_with_circuit_breaker():
                            return await self.execute_with_circuit_breaker_async(
                                "dataset_sync",
                                lambda: self.node.shard_manager.sync_dataset_with_node(dataset_id, node_id)
                            )
                        
                        result = await self.retry_async(sync_with_circuit_breaker)
                        
                        # Record success
                        operation.add_success(node_id, result)
                        
                        # Update node health
                        if node_id in self.node_health:
                            self.node_health[node_id].record_success()
                        
                        return True
                    except Exception as e:
                        # Record failure
                        operation.add_failure(node_id, str(e))
                        
                        # Update node health
                        if node_id in self.node_health:
                            self.node_health[node_id].record_failure()
                        
                        logger.warning(f"Failed to sync dataset {dataset_id} with node {node_id}: {str(e)}")
                        return False
                
                tasks.append(sync_with_node(node_id))
            
            # Wait for batch to complete
            await asyncio.gather(*tasks)
        
        # Complete operation
        return operation.complete()
    
    async def resilient_rebalance_shards(
        self,
        dataset_id: Optional[str] = None,
        target_replication: int = 3,
        max_concurrent: int = 3,
        use_healthy_nodes_only: bool = True
    ) -> OperationResult:
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
        if not hasattr(self.node, 'shard_manager'):
            raise NotImplementedError("Node does not have a shard manager")
        
        # Create operation tracker
        operation = self.create_operation("rebalance_shards")
        
        try:
            # Get all connected peers
            all_peers = self.node.get_connected_peers()
            
            # Filter to healthy nodes if requested
            target_nodes = all_peers
            if use_healthy_nodes_only:
                target_nodes = self.get_healthy_nodes()
                
                # If no healthy nodes, use all connected peers
                if not target_nodes:
                    logger.warning("No healthy nodes found, using all connected peers")
                    target_nodes = all_peers
            
            # Rebalance with circuit breaker
            async def rebalance_with_circuit_breaker():
                return await self.execute_with_circuit_breaker_async(
                    "shard_transfer",
                    lambda: self.node.shard_manager.rebalance_shards(
                        dataset_id=dataset_id,
                        target_replication=target_replication,
                        target_nodes=target_nodes,
                        max_concurrent=max_concurrent
                    )
                )
            
            # Execute with retries
            result = await self.retry_async(rebalance_with_circuit_breaker)
            
            # Process result
            if isinstance(result, dict):
                # Record successful transfers
                for shard_id, node_results in result.get("successful_transfers", {}).items():
                    for node_id in node_results:
                        operation.add_success(node_id, {"shard_id": shard_id})
                
                # Record failed transfers
                for shard_id, node_results in result.get("failed_transfers", {}).items():
                    for node_id, error in node_results.items():
                        operation.add_failure(node_id, error)
                
                # Add to operation results
                operation.results.update(result)
            
        except Exception as e:
            # Record overall failure
            operation.error_message = str(e)
            logger.error(f"Failed to rebalance shards: {str(e)}")
        
        # Complete operation
        return operation.complete()
    
    async def execute_on_healthy_nodes(
        self,
        func: Callable[[str], Awaitable[T]],
        min_success_count: int = 1,
        max_concurrent: int = 3,
        timeout_sec: int = 30
    ) -> Dict[str, Union[T, Exception]]:
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
        # Get healthy nodes
        healthy_nodes = self.get_healthy_nodes()
        
        if not healthy_nodes:
            raise ValueError("No healthy nodes available")
        
        # Execute function on each node concurrently
        results = {}
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def execute_with_timeout(node_id):
            async with semaphore:
                try:
                    return await asyncio.wait_for(func(node_id), timeout_sec)
                except asyncio.TimeoutError:
                    return TimeoutError(f"Operation timed out after {timeout_sec} seconds")
                except Exception as e:
                    return e
        
        # Create tasks
        tasks = {node_id: execute_with_timeout(node_id) for node_id in healthy_nodes}
        
        # Wait for all tasks to complete or until min_success_count is reached
        pending = set(asyncio.create_task(coro) for coro in tasks.values())
        success_count = 0
        
        while pending and success_count < min_success_count:
            done, pending = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Process completed tasks
            for task in done:
                result = task.result()
                # Count successes (not exceptions)
                if not isinstance(result, Exception):
                    success_count += 1
        
        # Cancel any pending tasks if we have enough successes
        if success_count >= min_success_count and pending:
            for task in pending:
                task.cancel()
        
        # Wait for all tasks to complete
        done, pending = await asyncio.wait(tasks.values(), return_when=asyncio.ALL_COMPLETED)
        
        # Map results back to node IDs
        for node_id, task in zip(tasks.keys(), tasks.values()):
            try:
                results[node_id] = task.result()
            except Exception as e:
                results[node_id] = e
        
        return results
    
    async def lazy_broadcast(
        self,
        protocol: NetworkProtocol,
        data: Any,
        min_reach: int = 3,
        timeout_ms: int = 5000
    ) -> Tuple[int, int]:
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
        # Get healthy nodes
        healthy_nodes = self.get_healthy_nodes()
        
        if not healthy_nodes:
            logger.warning("No healthy nodes available for broadcast")
            return (0, 0)
        
        # Select nodes to send to (prioritize most reliable nodes)
        target_nodes = sorted(
            [(node_id, self.node_health[node_id].availability_score) for node_id in healthy_nodes],
            key=lambda x: x[1],
            reverse=True
        )
        
        # Take top nodes based on min_reach
        target_count = min(min_reach, len(target_nodes))
        success_count = 0
        failure_count = 0
        
        # Send messages asynchronously
        tasks = []
        for i in range(target_count):
            node_id = target_nodes[i][0]
            
            async def send_to_node(node_id):
                try:
                    await self.send_message_with_retry(
                        peer_id=node_id,
                        protocol=protocol,
                        data=data,
                        timeout_ms=timeout_ms
                    )
                    return True
                except Exception as e:
                    logger.warning(f"Failed to broadcast to node {node_id}: {str(e)}")
                    return False
            
            tasks.append(send_to_node(node_id))
        
        # Wait for all sends to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count successes and failures
        for result in results:
            if result is True:
                success_count += 1
            else:
                failure_count += 1
        
        return (success_count, failure_count)
    
    async def find_consistent_data(
        self,
        protocol: NetworkProtocol,
        request: Dict[str, Any],
        quorum_percentage: int = 51,
        timeout_ms: int = 5000
    ) -> Tuple[Any, int]:
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
        # Get healthy nodes
        healthy_nodes = self.get_healthy_nodes()
        
        if not healthy_nodes:
            raise ValueError("No healthy nodes available")
        
        # Calculate quorum count
        quorum_count = max(1, (len(healthy_nodes) * quorum_percentage) // 100)
        
        # Query all nodes asynchronously
        async def query_node(node_id):
            try:
                return await self.send_message_with_retry(
                    peer_id=node_id,
                    protocol=protocol,
                    data=request,
                    timeout_ms=timeout_ms
                )
            except Exception as e:
                logger.warning(f"Failed to query node {node_id}: {str(e)}")
                return None
        
        # Create tasks for all nodes
        tasks = {node_id: query_node(node_id) for node_id in healthy_nodes}
        
        # Wait for all to complete
        results = {}
        for node_id, coro in tasks.items():
            try:
                result = await coro
                results[node_id] = result
            except Exception:
                pass
        
        # Count occurrences of each distinct result
        result_counts = {}
        for result in results.values():
            if result is not None:
                # Convert to string for comparison
                result_str = json.dumps(result, sort_keys=True)
                if result_str not in result_counts:
                    result_counts[result_str] = (0, result)
                
                count, value = result_counts[result_str]
                result_counts[result_str] = (count + 1, value)
        
        # Find the most common result
        best_count = 0
        consensus_data = None
        
        for count, value in result_counts.values():
            if count > best_count:
                best_count = count
                consensus_data = value
        
        # Check if quorum was reached
        if best_count >= quorum_count:
            return (consensus_data, best_count)
        else:
            raise ValueError(f"No quorum reached. Best agreement: {best_count}/{len(healthy_nodes)}, required: {quorum_count}")
    
    def get_operations_by_status(self, status: OperationStatus) -> List[OperationResult]:
        """
        Get operations by status.
        
        Args:
            status: Status to filter by
            
        Returns:
            List[OperationResult]: Matching operations
        """
        return [op for op in self.operations.values() if op.status == status]
    
    def shutdown(self):
        """Shutdown the resilience manager."""
        self.running = False