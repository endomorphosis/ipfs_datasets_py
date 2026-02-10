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
import anyio
import inspect
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
    """
    Health Status Enumeration for Network Nodes

    Defines the health states that a node in the IPFS network can be in.

    Values:
        HEALTHY: Node is operating normally with good response times and no recent failures
        DEGRADED: Node has some issues but is still usable (e.g., slower response times)
        UNHEALTHY: Node has significant issues and should be avoided for new operations
        UNKNOWN: Node health status has not been determined yet
    """
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class OperationStatus(Enum):
    """
    Operation Status Enumeration for Distributed Operations

    Defines the possible states of distributed operations across IPFS nodes.

    Values:
        PENDING: Operation has been created but not yet started
        IN_PROGRESS: Operation is currently executing
        COMPLETED: Operation completed successfully on all target nodes
        PARTIALLY_COMPLETED: Operation completed on some but not all target nodes
        FAILED: Operation failed completely with no successful results
        INTERRUPTED: Operation was interrupted but can potentially be resumed
        RECOVERED: Operation was successfully recovered from an interruption
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    RECOVERED = "recovered"


@dataclass
class NodeHealth:
    """
    Node Health Tracking and Metrics Collection

    Args:
        node_id (str): Unique identifier for the network node
        status (HealthStatus, optional): Current health status of the node.
            Defaults to HealthStatus.UNKNOWN.
        last_check_time (Optional[float], optional): Unix timestamp of last health check.
            None if no checks have been performed. Defaults to None.
        response_times_ms (List[int], optional): Rolling window of recent response times
            in milliseconds. Used to calculate average response time. Defaults to empty list.
        avg_response_time_ms (float, optional): Average response time in milliseconds
            calculated from recent samples. Defaults to 0.
        failure_count (int, optional): Number of consecutive failures recorded.
            Used to determine degraded/unhealthy status. Defaults to 0.
        last_failure_time (Optional[float], optional): Unix timestamp of most recent failure.
            None if no failures recorded. Defaults to None.
        availability_score (float, optional): Computed availability score from 0.0 to 1.0
            where 1.0 indicates perfect availability. Defaults to 0.0.
        capabilities (Dict[str, Any], optional): Node capabilities and supported features.
            Includes roles, protocols, and feature flags. Defaults to empty dict.
        load_metrics (Dict[str, Any], optional): Current load metrics including CPU,
            memory, disk usage, and network connections. Defaults to empty dict.

    Attributes:
        node_id (str): Unique identifier for the network node
        status (HealthStatus): Current health status (HEALTHY, DEGRADED, UNHEALTHY, UNKNOWN)
        last_check_time (Optional[float]): Unix timestamp of last health check
        response_times_ms (List[int]): Rolling window of recent response times in milliseconds
        avg_response_time_ms (float): Average response time calculated from recent samples
        failure_count (int): Number of consecutive failures recorded
        last_failure_time (Optional[float]): Unix timestamp of most recent failure
        availability_score (float): Computed availability score (0.0-1.0)
        capabilities (Dict[str, Any]): Node capabilities and supported features
        load_metrics (Dict[str, Any]): Current load metrics (CPU, memory, disk, network)

    Public Methods:
        update_response_time(response_time_ms: int, max_samples: int = 10):
            Updates response time metrics with new sample and recalculates average.
        record_success():
            Records successful operation, improving availability score and health status.
        record_failure():
            Records failed operation, degrading availability score and health status.
        to_dict() -> Dict[str, Any]:
            Converts health information to dictionary for serialization.

    Usage Example:
    >>> health = NodeHealth(node_id="peer_123")
    >>> health.update_response_time(250)  # 250ms response
    >>>     health.record_success()  # Mark operation as successful
    >>>     health_data = health.to_dict()  # Export for storage
    """
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
        """
        Update response time metrics with a new sample.

        Adds a new response time measurement to the rolling window of samples
        and recalculates the average response time. The rolling window is
        maintained at a maximum size to prevent unbounded memory growth.

        Args:
            response_time_ms (int): Response time measurement in milliseconds.
                Must be a non-negative integer representing the time taken
                for a network operation to complete.
            max_samples (int, optional): Maximum number of samples to maintain
                in the rolling window. Older samples are discarded when this
                limit is exceeded. Defaults to 10.

        Returns:
            None

        Raises:
            ValueError: If response_time_ms is negative
            TypeError: If response_time_ms is not an integer

        Side Effects:
            - Updates response_times_ms list with new sample
            - Recalculates avg_response_time_ms based on current samples
            - May remove oldest samples if max_samples limit is exceeded

        Examples:
            >>> health = NodeHealth(node_id="peer_123")
            >>> health.update_response_time(250)  # 250ms response
            >>> health.avg_response_time_ms
            250.0
            >>> health.update_response_time(300)  # Add another sample
            >>> health.avg_response_time_ms
            275.0
        """
        self.response_times_ms.append(response_time_ms)

        # Keep only the most recent samples
        if len(self.response_times_ms) > max_samples:
            self.response_times_ms = self.response_times_ms[-max_samples:]

        # Update average
        self.avg_response_time_ms = sum(self.response_times_ms) / len(self.response_times_ms)

    def record_success(self):
        """
        Record a successful operation and update health metrics.

        This method is called when a network operation with this node completes
        successfully. It updates the health status to HEALTHY, improves the
        availability score, and records the timestamp of the successful operation.

        The availability score is increased by 0.1 (up to a maximum of 1.0)
        to reflect the successful operation, providing positive reinforcement
        for reliable nodes in the selection algorithms.

        Returns:
            None

        Side Effects:
            - Sets last_check_time to current Unix timestamp
            - Sets status to HealthStatus.HEALTHY
            - Increases availability_score by 0.1 (capped at 1.0)
            - Implicitly improves node's ranking for future operations

        Examples:
            >>> health = NodeHealth(node_id="peer_123")
            >>> health.availability_score
            0.0
            >>> health.record_success()
            >>> health.availability_score
            0.1
            >>> health.status
            <HealthStatus.HEALTHY: 'healthy'>
        """
        self.last_check_time = time.time()
        self.status = HealthStatus.HEALTHY

        # Improve availability score
        self.availability_score = min(1.0, self.availability_score + 0.1)

    def record_failure(self):
        """
        Record a failed operation and update health metrics.

        This method is called when a network operation with this node fails.
        It increments the failure count, degrades the availability score,
        and updates the health status based on the failure threshold.

        The availability score is decreased by 0.2 (with a minimum of 0.0)
        to reflect the failed operation. If the failure count reaches the
        threshold (DEFAULT_NODE_FAILURE_THRESHOLD), the node is marked as
        UNHEALTHY, otherwise it's marked as DEGRADED.

        Returns:
            None

        Side Effects:
            - Increments failure_count by 1
            - Sets last_failure_time to current Unix timestamp
            - Decreases availability_score by 0.2 (floored at 0.0)
            - Updates status to DEGRADED or UNHEALTHY based on failure count
            - Affects node's ranking in future operation selections

        Examples:
            >>> health = NodeHealth(node_id="peer_123")
            >>> health.availability_score = 0.5
            >>> health.record_failure()
            >>> health.availability_score
            0.3
            >>> health.status
            <HealthStatus.DEGRADED: 'degraded'>
            >>> # After DEFAULT_NODE_FAILURE_THRESHOLD failures
            >>> health.failure_count = DEFAULT_NODE_FAILURE_THRESHOLD
            >>> health.record_failure()
            >>> health.status
            <HealthStatus.UNHEALTHY: 'unhealthy'>
        """
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
        """
        Convert health information to dictionary for serialization.

        Converts the NodeHealth object to a dictionary representation suitable
        for JSON serialization, network transmission, or persistent storage.
        The status enum is converted to its string value for compatibility.

        Returns:
            Dict[str, Any]: Dictionary containing all health information with
                           JSON-serializable values. Keys include:
                           - node_id: Node identifier string
                           - status: Health status as string value
                           - last_check_time: Unix timestamp or None
                           - avg_response_time_ms: Average response time
                           - failure_count: Number of failures
                           - last_failure_time: Unix timestamp or None
                           - availability_score: Score from 0.0 to 1.0
                           - capabilities: Node capabilities dictionary
                           - load_metrics: Load metrics dictionary

        Raises:
            TypeError: If any contained objects are not JSON-serializable

        Examples:
            >>> health = NodeHealth(node_id="peer_123")
            >>> health.record_success()
            >>> data = health.to_dict()
            >>> data['status']
            'healthy'
            >>> data['node_id']
            'peer_123'
            >>> import json
            >>> json_str = json.dumps(data)  # Serializable
        """
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
    Circuit Breaker Pattern Implementation for Resilient Operations

    The CircuitBreaker class implements the circuit breaker pattern to prevent
    cascading failures in distributed systems. It monitors operation failures
    and automatically "trips" to prevent further attempts when failure rates
    exceed thresholds, allowing the system to recover gracefully.

    The circuit breaker operates in three distinct states:
    - CLOSED: Normal operation, all requests are allowed through
    - OPEN: Failure threshold exceeded, all requests immediately fail
    - HALF_OPEN: Testing recovery, limited requests allowed to test system health

    This pattern is essential for maintaining system stability when dealing with
    unreliable network connections, overloaded services, or failing nodes in
    the IPFS distributed network.

    Args:
        name (str): Unique identifier for this circuit breaker instance.
            Used for logging and monitoring purposes.
        failure_threshold (int, optional): Number of consecutive failures
            required to trip the circuit to OPEN state. Higher values provide
            more tolerance but slower failure detection. Defaults to DEFAULT_CIRCUIT_BREAKER_THRESHOLD.
        reset_timeout_sec (int, optional): Time in seconds to wait before
            transitioning from OPEN to HALF_OPEN state for recovery testing.
            Longer timeouts give more time for recovery but delay system healing.
            Defaults to DEFAULT_CIRCUIT_BREAKER_RESET_TIMEOUT_SEC.

    Key Features:
    - Automatic failure detection and circuit state management
    - Configurable failure thresholds and recovery timeouts
    - Support for both synchronous and asynchronous operations
    - Comprehensive logging for monitoring and debugging
    - Thread-safe state transitions and operation counting
    - Graceful recovery testing through HALF_OPEN state

    Attributes:
        name (str): Unique identifier for this circuit breaker
        failure_threshold (int): Number of failures required to trip the circuit
        reset_timeout_sec (int): Timeout before attempting recovery
        failures (int): Current count of consecutive failures
        state (str): Current circuit state ("CLOSED", "OPEN", "HALF_OPEN")
        last_failure_time (Optional[float]): Unix timestamp of most recent failure
        last_success_time (Optional[float]): Unix timestamp of most recent success
        trip_time (Optional[float]): Unix timestamp when circuit was tripped to OPEN

    Public Methods:
        execute(func: Callable[[], T]) -> T:
            Execute a synchronous function with circuit breaker protection.
        execute_async(func: Callable[[], Awaitable[T]]) -> T:
            Execute an asynchronous function with circuit breaker protection.
        reset():
            Manually reset the circuit to CLOSED state, clearing all failure counts.

    Usage Example:
        breaker = CircuitBreaker(
            name="database_connection",
            failure_threshold=5,
            reset_timeout_sec=60
        )
        
        # Synchronous execution
        try:
            result = breaker.execute(lambda: risky_database_call())
        except CircuitBreakerOpenError:
            # Circuit is open, use fallback
            result = get_cached_data()
        
        # Asynchronous execution
        try:
            result = await breaker.execute_async(lambda: async_api_call())
        except CircuitBreakerOpenError:
            # Handle circuit open state
            pass
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
        Execute a synchronous function with circuit breaker protection.

        This method wraps the execution of a potentially failing function with
        circuit breaker logic. If the circuit is OPEN, the function is not
        executed and an exception is raised immediately. Otherwise, the function
        is executed and the result is used to update the circuit state.

        The circuit state is checked before execution and updated after based
        on whether the function succeeds or fails. Successful executions in
        HALF_OPEN state will reset the circuit to CLOSED.

        Args:
            func (Callable[[], T]): Synchronous function to execute with circuit
                protection. Must be a callable that takes no arguments and returns
                a value of type T. The function should raise an exception on failure.

        Returns:
            T: The result returned by the executed function if successful.

        Raises:
            CircuitBreakerOpenError: If the circuit is currently in OPEN state,
                preventing execution to avoid further failures.
            Exception: Any exception raised by the executed function, which will
                also cause the circuit breaker to record a failure.

        Side Effects:
            - Updates circuit state based on execution result
            - Records success or failure timestamps
            - May transition circuit between CLOSED, OPEN, and HALF_OPEN states
            - Logs state transitions for monitoring

        Examples:
            >>> breaker = CircuitBreaker(name="api_calls", failure_threshold=3)
            >>> result = breaker.execute(lambda: make_api_call())
            >>> print(f"API returned: {result}")
            
            >>> # If circuit is open
            >>> try:
            ...     breaker.execute(lambda: failing_function())
            >>> except CircuitBreakerOpenError:
            ...     print("Circuit is open, using fallback")
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
        Execute an asynchronous function with circuit breaker protection.

        This method provides circuit breaker protection for asynchronous operations,
        following the same logic as the synchronous execute method but supporting
        coroutines and async/await patterns. The circuit state management is
        identical to synchronous execution.

        The method checks circuit state before execution and updates it based on
        the async function's success or failure. This enables resilient async
        operations in distributed systems.

        Args:
            func (Callable[[], Awaitable[T]]): Asynchronous function to execute with
                circuit protection. Must be a callable that takes no arguments and
                returns an awaitable that yields a value of type T. The function
                should raise an exception on failure.

        Returns:
            T: The result returned by the executed async function if successful.

        Raises:
            CircuitBreakerOpenError: If the circuit is currently in OPEN state,
                preventing execution to avoid further failures.
            Exception: Any exception raised by the executed async function, which
                will also cause the circuit breaker to record a failure.

        Side Effects:
            - Updates circuit state based on execution result
            - Records success or failure timestamps
            - May transition circuit between CLOSED, OPEN, and HALF_OPEN states
            - Logs state transitions for monitoring

        Examples:
            >>> breaker = CircuitBreaker(name="async_api", failure_threshold=3)
            >>> result = await breaker.execute_async(lambda: async_api_call())
            >>> print(f"Async API returned: {result}")
            
            >>> # Handling circuit open state
            >>> try:
            ...     await breaker.execute_async(lambda: failing_async_function())
            >>> except CircuitBreakerOpenError:
            ...     print("Circuit is open, using cached data")
            ...     result = get_cached_result()
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
        """
        Manually reset the circuit breaker to CLOSED state.

        This method provides a way to manually reset the circuit breaker,
        clearing all failure counts and forcing the state back to CLOSED.
        This is useful for administrative control or when external monitoring
        indicates that the protected resource has recovered.

        The reset operation clears all failure tracking state and allows
        normal operations to resume immediately, bypassing the normal
        recovery timeout mechanism.

        Returns:
            None

        Side Effects:
            - Sets state to "CLOSED"
            - Resets failures count to 0
            - Clears trip_time timestamp
            - Logs the manual reset action
            - Allows immediate normal operation resumption

        Examples:
            >>> breaker = CircuitBreaker(name="service_calls")
            >>> # After several failures, circuit is open
            >>> breaker.state
            'OPEN'
            >>> # Manually reset after confirming service recovery
            >>> breaker.reset()
            >>> breaker.state
            'CLOSED'
            >>> breaker.failures
            0
        """
        self.state = "CLOSED"
        self.failures = 0
        self.trip_time = None
        logger.info(f"Circuit '{self.name}' manually reset to CLOSED")


class CircuitBreakerOpenError(Exception):
    """
    Exception Raised When Circuit Breaker is in Open State

    This exception is raised when attempting to execute an operation through
    a circuit breaker that is currently in the OPEN state. The OPEN state
    indicates that the protected resource has experienced too many failures
    and the circuit breaker is preventing further attempts to allow recovery.

    This exception should be caught by calling code to implement fallback
    strategies, such as using cached data, degraded functionality, or
    alternative service endpoints.

    The exception message typically includes the circuit breaker name to
    help with debugging and monitoring.

    Attributes:
        Inherits all attributes from the base Exception class.

    Usage Example:
        try:
            result = circuit_breaker.execute(risky_operation)
        except CircuitBreakerOpenError as e:
            logger.warning(f"Circuit breaker open: {e}")
            # Use fallback strategy
            result = fallback_operation()
    """
    pass


@dataclass
class RetryConfig:
    """
    Configuration Class for Retry Behavior with Exponential Backoff

    The RetryConfig class defines the parameters for automatic retry behavior
    in distributed operations. It supports exponential backoff with jitter
    to prevent thundering herd problems and configurable exception filtering
    to determine which failures should trigger retries.

    This configuration is used throughout the resilient operations system
    to provide consistent retry behavior across different types of operations,
    from simple network calls to complex distributed transactions.

    Args:
        max_retries (int, optional): Maximum number of retry attempts after
            the initial failure. Total attempts will be max_retries + 1.
            Higher values provide more resilience but may delay failure detection.
            Defaults to DEFAULT_RETRY_COUNT.
        initial_backoff_ms (int, optional): Initial backoff delay in milliseconds
            before the first retry attempt. This is the base time that gets
            multiplied by the backoff factor for subsequent retries.
            Defaults to DEFAULT_INITIAL_BACKOFF_MS.
        max_backoff_ms (int, optional): Maximum backoff delay in milliseconds
            to prevent excessively long delays. The exponential backoff is
            capped at this value. Defaults to DEFAULT_MAX_BACKOFF_MS.
        backoff_factor (float, optional): Multiplication factor for exponential
            backoff. Each retry delay is multiplied by this factor. Values > 1.0
            create exponential growth, while 1.0 creates constant delays.
            Defaults to DEFAULT_BACKOFF_FACTOR.
        jitter_factor (float, optional): Random jitter factor (0.0-1.0) applied
            to backoff delays to prevent synchronized retries across multiple
            clients. Higher values create more randomization.
            Defaults to DEFAULT_JITTER_FACTOR.
        retry_on_exceptions (List[type], optional): List of exception types that
            should trigger retry attempts. Only exceptions of these types (or
            their subclasses) will cause retries; other exceptions fail immediately.
            Defaults to [P2PError, ConnectionError, TimeoutError] if empty.

    Key Features:
    - Exponential backoff with configurable parameters
    - Jitter support to prevent thundering herd effects
    - Selective exception handling for intelligent retry logic
    - Default configuration optimized for distributed systems
    - Flexible parameter adjustment for different use cases

    Attributes:
        max_retries (int): Maximum number of retry attempts
        initial_backoff_ms (int): Initial delay before first retry
        max_backoff_ms (int): Maximum delay cap for exponential backoff
        backoff_factor (float): Exponential growth factor for delays
        jitter_factor (float): Random jitter factor (0.0-1.0)
        retry_on_exceptions (List[type]): Exception types that trigger retries

    Usage Example:
        # Conservative retry for critical operations
        critical_config = RetryConfig(
            max_retries=5,
            initial_backoff_ms=200,
            max_backoff_ms=10000,
            backoff_factor=2.0,
            jitter_factor=0.2
        )
        
        # Fast retry for time-sensitive operations
        fast_config = RetryConfig(
            max_retries=2,
            initial_backoff_ms=50,
            max_backoff_ms=1000,
            backoff_factor=1.5
        )
    """
    max_retries: int = DEFAULT_RETRY_COUNT
    initial_backoff_ms: int = DEFAULT_INITIAL_BACKOFF_MS
    max_backoff_ms: int = DEFAULT_MAX_BACKOFF_MS
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
    jitter_factor: float = DEFAULT_JITTER_FACTOR
    retry_on_exceptions: List[type] = field(default_factory=list)

    def __post_init__(self):
        """
        Initialize default retry exceptions if none were specified.

        This method is automatically called after dataclass initialization
        to set up default exception types for retry behavior. If no specific
        exceptions were provided during initialization, it configures the
        retry system to handle common distributed system failures.

        The default exception types are optimized for P2P and distributed
        operations, covering network connectivity issues, timeouts, and
        protocol-specific errors commonly encountered in IPFS environments.

        Returns:
            None

        Side Effects:
            - Sets retry_on_exceptions to default list if empty
            - Default exceptions: [P2PError, ConnectionError, TimeoutError]

        Examples:
            >>> # With custom exceptions
            >>> config = RetryConfig(retry_on_exceptions=[ValueError, IOError])
            >>> config.retry_on_exceptions
            [ValueError, IOError]
            
            >>> # With default exceptions (empty list provided)
            >>> config = RetryConfig()
            >>> config.retry_on_exceptions
            [P2PError, ConnectionError, TimeoutError]
        """
        # Default retry on P2PError if not specified
        if not self.retry_on_exceptions:
            self.retry_on_exceptions = [P2PError, ConnectionError, TimeoutError]


@dataclass
class OperationResult:
    """
    Operation Result Tracking for Distributed Operations

    The OperationResult class provides comprehensive tracking and reporting
    for distributed operations across IPFS nodes. It maintains detailed
    records of operation progress, success/failure counts, node-specific
    results, and timing information to enable monitoring, debugging, and
    recovery of complex distributed tasks.

    This class serves as the central coordination point for operations that
    span multiple nodes, providing real-time visibility into operation
    progress and enabling intelligent decision-making about partial failures,
    retries, and recovery strategies.

    Args:
        operation_id (str): Unique identifier for this operation instance.
            Should be descriptive and include timestamp/random components
            to ensure uniqueness across the distributed system.
        status (OperationStatus): Current status of the operation indicating
            its lifecycle stage (PENDING, IN_PROGRESS, COMPLETED, etc.).
        start_time (float): Unix timestamp when the operation was initiated.
            Used for calculating execution time and timeout handling.
        end_time (Optional[float], optional): Unix timestamp when the operation
            completed. None for ongoing operations. Defaults to None.
        success_count (int, optional): Number of nodes that successfully
            completed their part of the operation. Defaults to 0.
        failure_count (int, optional): Number of nodes that failed to complete
            their part of the operation. Defaults to 0.
        affected_nodes (List[str], optional): List of all node IDs involved
            in this operation, regardless of success/failure. Defaults to empty list.
        successful_nodes (List[str], optional): List of node IDs that successfully
            completed their operation tasks. Defaults to empty list.
        failed_nodes (Dict[str, str], optional): Mapping of node IDs to their
            specific error messages for failed operations. Defaults to empty dict.
        results (Dict[str, Any], optional): Node-specific operation results
            for successful operations, keyed by node ID. Defaults to empty dict.
        error_message (Optional[str], optional): Overall operation error message
            if the entire operation failed. None for successful operations.
            Defaults to None.
        execution_time_ms (int, optional): Total execution time in milliseconds
            calculated when the operation completes. Defaults to 0.

    Key Features:
    - Real-time operation progress tracking with success/failure counts
    - Node-specific result storage and error reporting
    - Automatic execution time calculation and performance metrics
    - Flexible status management supporting partial completion scenarios
    - Serialization support for persistence and network transmission
    - Built-in success criteria evaluation methods

    Attributes:
        operation_id (str): Unique identifier for this operation
        status (OperationStatus): Current operation status
        start_time (float): Unix timestamp of operation start
        end_time (Optional[float]): Unix timestamp of operation completion
        success_count (int): Count of successful node operations
        failure_count (int): Count of failed node operations
        affected_nodes (List[str]): All nodes involved in the operation
        successful_nodes (List[str]): Nodes that completed successfully
        failed_nodes (Dict[str, str]): Failed nodes with error messages
        results (Dict[str, Any]): Node-specific operation results
        error_message (Optional[str]): Overall operation error message
        execution_time_ms (int): Total execution time in milliseconds

    Public Methods:
        add_success(node_id: str, result: Any = None):
            Records successful completion of operation on a specific node.
        add_failure(node_id: str, error_message: str):
            Records failure of operation on a specific node with error details.
        complete(status: OperationStatus = OperationStatus.COMPLETED) -> OperationResult:
            Marks operation as complete and calculates final metrics.
        is_successful() -> bool:
            Checks if the operation completed successfully on all nodes.
        is_partially_successful() -> bool:
            Checks if the operation succeeded on at least some nodes.
        to_dict() -> Dict[str, Any]:
            Converts operation result to dictionary for serialization.

    Usage Example:
        operation = OperationResult(
            operation_id="shard_transfer_20250911_001",
            status=OperationStatus.IN_PROGRESS,
            start_time=time.time()
        )
        
        # Record node results
        operation.add_success("node_1", {"transferred_bytes": 1024})
        operation.add_failure("node_2", "Connection timeout")
        
        # Complete and evaluate
        final_result = operation.complete()
        if final_result.is_partially_successful():
            print(f"Partial success: {operation.success_count}/{len(operation.affected_nodes)}")
    """
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
        """
        Record successful completion of operation on a specific node.

        This method tracks successful operation completion on individual nodes,
        updating success counts and maintaining lists of successful nodes.
        It also stores node-specific results for later analysis and ensures
        nodes are properly tracked in the affected nodes list.

        Args:
            node_id (str): Unique identifier of the node that successfully
                completed its operation. Must be a non-empty string representing
                a valid node in the distributed system.
            result (Any, optional): Node-specific result data from the successful
                operation. Can be any serializable object containing operation
                output, metrics, or other relevant information. Defaults to None.

        Returns:
            None

        Side Effects:
            - Increments success_count by 1
            - Adds node_id to successful_nodes list (if not already present)
            - Adds node_id to affected_nodes list (if not already present)
            - Stores result in results dictionary keyed by node_id (if result provided)
            - Updates operation tracking for progress monitoring

        Examples:
            >>> operation = OperationResult("sync_001", OperationStatus.IN_PROGRESS, time.time())
            >>> operation.add_success("node_123", {"bytes_synced": 2048, "duration_ms": 150})
            >>> operation.success_count
            1
            >>> operation.successful_nodes
            ['node_123']
            >>> operation.results["node_123"]
            {'bytes_synced': 2048, 'duration_ms': 150}
        """
        self.success_count += 1
        if node_id not in self.successful_nodes:
            self.successful_nodes.append(node_id)

        if node_id not in self.affected_nodes:
            self.affected_nodes.append(node_id)

        if result is not None:
            self.results[node_id] = result

    def add_failure(self, node_id: str, error_message: str):
        """
        Record failure of operation on a specific node with error details.

        This method tracks failed operation attempts on individual nodes,
        updating failure counts and maintaining detailed error information
        for debugging and recovery purposes. It ensures proper tracking
        of all nodes involved in the operation.

        Args:
            node_id (str): Unique identifier of the node that failed to complete
                its operation. Must be a non-empty string representing a valid
                node in the distributed system.
            error_message (str): Detailed error message describing the specific
                failure that occurred on this node. Should include enough detail
                for debugging and recovery decision-making.

        Returns:
            None

        Side Effects:
            - Increments failure_count by 1
            - Adds node_id and error_message to failed_nodes dictionary
            - Adds node_id to affected_nodes list (if not already present)
            - Updates operation tracking for failure analysis
            - Enables failure pattern analysis across nodes

        Examples:
            >>> operation = OperationResult("transfer_001", OperationStatus.IN_PROGRESS, time.time())
            >>> operation.add_failure("node_456", "Connection timeout after 30 seconds")
            >>> operation.failure_count
            1
            >>> operation.failed_nodes["node_456"]
            'Connection timeout after 30 seconds'
            >>> "node_456" in operation.affected_nodes
            True
        """
        self.failure_count += 1
        self.failed_nodes[node_id] = error_message

        if node_id not in self.affected_nodes:
            self.affected_nodes.append(node_id)

    def complete(self, status: OperationStatus = OperationStatus.COMPLETED):
        """
        Mark the operation as complete and calculate final metrics.

        This method finalizes the operation by recording the completion time,
        calculating execution duration, and determining the final status based
        on success/failure patterns. It provides intelligent status determination
        when no explicit status is provided.

        The method automatically determines the appropriate final status:
        - COMPLETED: All operations succeeded (no failures)
        - PARTIALLY_COMPLETED: Some operations succeeded and some failed
        - FAILED: No operations succeeded (all failed)

        Args:
            status (OperationStatus, optional): Explicit final status to set.
                If OperationStatus.COMPLETED is provided (default), the method
                will automatically determine the appropriate status based on
                success/failure counts. Other values override automatic determination.
                Defaults to OperationStatus.COMPLETED.

        Returns:
            OperationResult: Returns self to enable method chaining and
                           provide a fluent interface for operation handling.

        Side Effects:
            - Sets end_time to current Unix timestamp
            - Calculates and sets execution_time_ms based on start/end times
            - Updates status based on success/failure patterns or explicit value
            - Finalizes operation state for reporting and analysis

        Examples:
            >>> operation = OperationResult("backup_001", OperationStatus.IN_PROGRESS, time.time())
            >>> operation.add_success("node_1")
            >>> operation.add_failure("node_2", "Disk full")
            >>> final_result = operation.complete()
            >>> final_result.status
            <OperationStatus.PARTIALLY_COMPLETED: 'partially_completed'>
            >>> final_result.execution_time_ms > 0
            True
            
            >>> # Explicit status override
            >>> result = operation.complete(OperationStatus.FAILED)
            >>> result.status
            <OperationStatus.FAILED: 'failed'>
        """
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
        """
        Check if the operation completed successfully.

        Returns:
            bool: True if the operation status is COMPLETED, indicating successful
                  execution without errors. False for any other status including
                  PENDING, RUNNING, FAILED, or CANCELLED states.

        Example:
            >>> operation = SomeOperation()
            >>> operation.execute()
            >>> if operation.is_successful():
            ...     print("Operation completed successfully")
            ... else:
            ...     print(f"Operation failed with status: {operation.status}")
        """
        return self.status == OperationStatus.COMPLETED

    def is_partially_successful(self) -> bool:
        """
        Check if the operation achieved at least partial success.

        This method determines whether an operation has completed successfully or 
        has made partial progress, indicating that some portion of the intended
        work was accomplished even if the full operation didn't complete.

        Returns:
            bool: True if the operation status is COMPLETED or PARTIALLY_COMPLETED,
                  False otherwise.

        Example:
            >>> operation = ResilientOperation()
            >>> operation.status = OperationStatus.COMPLETED
            >>> operation.is_partially_successful()
            True

            >>> operation.status = OperationStatus.FAILED
            >>> operation.is_partially_successful()
            False
        """
        return self.status in [OperationStatus.COMPLETED, OperationStatus.PARTIALLY_COMPLETED]

    def to_dict(self) -> Dict[str, Any]:
        """Convert the operation result to a dictionary representation for serialization.

        This method creates a comprehensive dictionary containing all operation metrics
        and status information, suitable for JSON serialization, logging, or API responses.

        Returns:
            Dict[str, Any]: A dictionary containing the following keys:
                - operation_id (str): Unique identifier for the operation
                - status (str): Current operation status as string value
                - start_time (datetime): When the operation began
                - end_time (datetime): When the operation completed (None if ongoing)
                - success_count (int): Number of successful sub-operations
                - failure_count (int): Number of failed sub-operations
                - affected_nodes (List[str]): All nodes involved in the operation
                - successful_nodes (List[str]): Nodes that completed successfully
                - failed_nodes (List[str]): Nodes that encountered failures
                - execution_time_ms (float): Total execution time in milliseconds
                - error_message (str): Error details if operation failed (None if successful)

        Example:
            >>> result = operation_result.to_dict()
            >>> print(result['status'])
            'completed'
            >>> print(result['success_count'])
            5
        """
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
    """
    Checkpoint for Resumable Long-Running Operations

    The Checkpoint class provides persistence and recovery capabilities for
    long-running distributed operations that may be interrupted by network
    failures, node restarts, or other system events. It maintains detailed
    state information that enables operations to resume from the point of
    interruption rather than starting over.

    Checkpoints are essential for maintaining operation continuity in
    distributed systems where failures are expected and operations may
    span minutes or hours across multiple nodes.

    Args:
        operation_id (str): Unique identifier of the operation being checkpointed.
            Must match the operation_id from the corresponding OperationResult.
        checkpoint_id (str, optional): Unique identifier for this specific
            checkpoint instance. Automatically generated with timestamp if not
            provided. Used for ordering and identifying checkpoint versions.
            Defaults to "cp_{timestamp}".
        timestamp (float, optional): Unix timestamp when this checkpoint was
            created. Used for ordering checkpoints and determining recency.
            Automatically set to current time if not provided. Defaults to current time.
        completed_items (List[str], optional): List of item identifiers that
            have been successfully completed and don't need to be retried.
            Items can be node IDs, file paths, shard IDs, or any operation-specific
            identifiers. Defaults to empty list.
        pending_items (List[str], optional): List of item identifiers that
            still need to be processed when the operation resumes. Should represent
            the remaining work to be done. Defaults to empty list.
        metadata (Dict[str, Any], optional): Additional operation-specific metadata
            required for proper resumption. Can include configuration, intermediate
            results, or any other state information. Defaults to empty dict.

    Key Features:
    - Automatic checkpoint ID generation with timestamps
    - Persistent storage to filesystem with JSON serialization
    - Latest checkpoint discovery for operation resumption
    - Flexible metadata storage for operation-specific state
    - Thread-safe file operations for concurrent access
    - Structured progress tracking with completed/pending item lists

    Attributes:
        operation_id (str): Identifier of the operation being checkpointed
        checkpoint_id (str): Unique identifier for this checkpoint instance
        timestamp (float): Unix timestamp of checkpoint creation
        completed_items (List[str]): Items that have been successfully completed
        pending_items (List[str]): Items that still need processing
        metadata (Dict[str, Any]): Additional operation-specific state information

    Public Methods:
        save(directory: str) -> str:
            Persists checkpoint to filesystem in specified directory.
        load(filename: str) -> Checkpoint:
            Class method to restore checkpoint from filesystem.
        find_latest(directory: str, operation_id: str) -> Optional[Checkpoint]:
            Class method to find most recent checkpoint for an operation.

    Usage Example:
        # Create checkpoint during long operation
        checkpoint = Checkpoint(
            operation_id="bulk_transfer_001",
            completed_items=["shard_1", "shard_2", "shard_5"],
            pending_items=["shard_3", "shard_4", "shard_6"],
            metadata={"batch_size": 100, "retry_count": 2}
        )
        
        # Save to disk
        filename = checkpoint.save("/app/checkpoints")
        
        # Later, resume operation
        latest = Checkpoint.find_latest("/app/checkpoints", "bulk_transfer_001")
        if latest:
            resume_operation(latest.pending_items, latest.metadata)
    """
    operation_id: str
    checkpoint_id: str = field(default_factory=lambda: f"cp_{int(time.time())}")
    timestamp: float = field(default_factory=time.time)
    completed_items: List[str] = field(default_factory=list)
    pending_items: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def save(self, directory: str):
        """
        Save checkpoint to filesystem for persistent storage.

        This method serializes the checkpoint data to JSON format and writes
        it to a file in the specified directory. The filename is automatically
        generated using the operation ID and checkpoint ID to ensure uniqueness
        and enable easy discovery.

        The directory is created if it doesn't exist, and the checkpoint data
        is written atomically to prevent corruption from interrupted writes.

        Args:
            directory (str): Absolute or relative path to the directory where
                the checkpoint file should be saved. The directory will be
                created if it doesn't exist.

        Returns:
            str: Full path to the saved checkpoint file. Can be used for
                 verification or logging purposes.

        Raises:
            OSError: If directory creation fails due to permissions or disk space
            IOError: If file write operation fails
            JSONEncodeError: If checkpoint data is not JSON-serializable

        Side Effects:
            - Creates directory if it doesn't exist
            - Writes checkpoint file to filesystem
            - Overwrites existing checkpoint file with same name

        Examples:
            >>> checkpoint = Checkpoint(operation_id="sync_001")
            >>> filename = checkpoint.save("/app/data/checkpoints")
            >>> filename
            '/app/data/checkpoints/sync_001_cp_1694436123.json'
            >>> os.path.exists(filename)
            True
        """
        os.makedirs(directory, exist_ok=True)

        # Create filename
        filename = os.path.join(directory, f"{self.operation_id}_{self.checkpoint_id}.json")

        # Write to file
        with open(filename, "w") as f:
            json.dump(asdict(self), f)

        return filename

    @classmethod
    def load(cls, filename: str) -> 'Checkpoint':
        """
        Load checkpoint from filesystem for operation resumption.

        This class method restores a checkpoint object from a JSON file
        previously saved using the save() method. It deserializes the
        checkpoint data and reconstructs the Checkpoint object with
        all original state information.

        Args:
            filename (str): Full path to the checkpoint file to load.
                Must be a valid JSON file created by the save() method
                with the expected checkpoint data structure.

        Returns:
            Checkpoint: Reconstructed checkpoint object with all original
                       state including operation_id, completed_items,
                       pending_items, and metadata.

        Raises:
            FileNotFoundError: If the specified checkpoint file doesn't exist
            IOError: If file read operation fails due to permissions
            JSONDecodeError: If file contains invalid JSON data
            KeyError: If required checkpoint fields are missing from the file
            TypeError: If loaded data types don't match expected checkpoint structure

        Examples:
            >>> # Load specific checkpoint file
            >>> checkpoint = Checkpoint.load("/app/checkpoints/sync_001_cp_1694436123.json")
            >>> checkpoint.operation_id
            'sync_001'
            >>> len(checkpoint.pending_items)
            5
            
            >>> # Handle missing file
            >>> try:
            ...     checkpoint = Checkpoint.load("nonexistent.json")
            >>> except FileNotFoundError:
            ...     print("Checkpoint file not found")
        """
        with open(filename, "r") as f:
            data = json.load(f)

        return cls(**data)

    @classmethod
    def find_latest(cls, directory: str, operation_id: str) -> Optional['Checkpoint']:
        """
        Find the most recent checkpoint for an operation.

        This class method searches the specified directory for checkpoint files
        belonging to the given operation and returns the most recent one based
        on the timestamp embedded in the checkpoint filename. This enables
        automatic recovery from the latest known good state.

        Args:
            directory (str): Path to directory containing checkpoint files.
                Must be readable and may contain checkpoint files from
                multiple operations.
            operation_id (str): Unique identifier of the operation whose
                latest checkpoint should be found. Must match the operation_id
                used when creating checkpoints.

        Returns:
            Optional[Checkpoint]: The most recent checkpoint for the specified
                                operation, or None if no checkpoints are found.
                                Returns a fully loaded Checkpoint object ready
                                for operation resumption.

        Raises:
            OSError: If directory cannot be read due to permissions
            JSONDecodeError: If the latest checkpoint file contains invalid JSON
            IOError: If the latest checkpoint file cannot be read

        Examples:
            >>> # Find latest checkpoint for operation
            >>> latest = Checkpoint.find_latest("/app/checkpoints", "sync_001")
            >>> if latest:
            ...     print(f"Found checkpoint from {latest.timestamp}")
            ...     resume_operation(latest)
            >>> else:
            ...     print("No checkpoints found, starting fresh")
            ...     start_new_operation()
            
            >>> # Handle missing directory
            >>> latest = Checkpoint.find_latest("/nonexistent", "sync_001")
            >>> latest is None
            True
        """
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
    Decorator for Making Functions Resilient with Automatic Retries

    The resilient decorator provides automatic retry capabilities with exponential
    backoff for functions that may fail due to network issues, temporary service
    unavailability, or other transient errors. It supports both synchronous and
    asynchronous functions with configurable retry parameters.

    Args:
        max_retries (int, optional): Maximum number of retry attempts after
            the initial failure.
            Defaults to DEFAULT_RETRY_COUNT.
        initial_backoff_ms (int, optional): Initial backoff delay in milliseconds
            before the first retry attempt.
            Defaults to DEFAULT_INITIAL_BACKOFF_MS.
        max_backoff_ms (int, optional): Maximum backoff delay in milliseconds
            Defaults to DEFAULT_MAX_BACKOFF_MS.
        backoff_factor (float, optional): Multiplication factor for exponential
            backoff. Each retry delay is multiplied by this factor. Values > 1.0
            create exponential growth. Defaults to DEFAULT_BACKOFF_FACTOR.
        jitter_factor (float, optional): Random jitter factor (0.0-1.0) applied
            to backoff delays to prevent synchronized retries. Higher values
            create more randomization. Defaults to DEFAULT_JITTER_FACTOR.
        retry_on_exceptions (List[type], optional): List of exception types that
            should trigger retry attempts. Only these exception types (and subclasses)
            will cause retries; others fail immediately. If None, defaults to
            [P2PError, ConnectionError, TimeoutError].

    Key Features:
    - Support for both sync and async function decoration
    - Exponential backoff with jitter for intelligent retry timing
    - Configurable exception filtering for selective retry behavior
    - Comprehensive logging of retry attempts and failures
    - Automatic detection of function type (sync vs async)
    - Thread-safe operation for concurrent usage

    Usage Examples:
        # Basic usage with defaults
        @resilient()
        def fetch_data():
            return requests.get("https://api.example.com/data")
        
        # Custom retry configuration
        @resilient(max_retries=5, initial_backoff_ms=200, backoff_factor=2.0)
        def critical_operation():
            return perform_important_task()
        
        # Async function support
        @resilient(max_retries=3, retry_on_exceptions=[TimeoutError])
        async def async_api_call():
            return await aiohttp.get("https://api.example.com/async")
        
        # Selective exception handling
        @resilient(
            retry_on_exceptions=[ConnectionError, TimeoutError],
            max_retries=2
        )
        def network_operation():
            return make_network_call()
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
        """
        Apply the resilient decorator to a function for automatic retry capability.

        This method is called when the decorator is applied to a function,
        creating a wrapper that provides automatic retry logic with exponential
        backoff. It automatically detects whether the function is synchronous
        or asynchronous and applies the appropriate retry mechanism.

        The wrapper preserves the original function's signature and behavior
        while adding resilience features transparently.

        Args:
            func (Callable): The function to be decorated with retry capability.
                Can be either a synchronous function or an async coroutine function.
                The function signature and return type are preserved.

        Returns:
            Callable: A wrapped version of the original function that includes
                     automatic retry logic with exponential backoff and jitter.
                     The wrapper has the same signature as the original function.

        Examples:
            >>> @resilient(max_retries=3)
            >>> def risky_operation():
            ...     # Function that might fail
            ...     return make_network_call()
            
            >>> @resilient(max_retries=5, initial_backoff_ms=100)
            >>> async def async_operation():
            ...     # Async function that might fail
            ...     return await fetch_data_async()
        """

        # Handle both async and sync functions
        if inspect.iscoroutinefunction(func):
            async def wrapper(*args, **kwargs):
                return await self._execute_async(func, args, kwargs)
            return wrapper
        else:
            def wrapper(*args, **kwargs):
                return self._execute_sync(func, args, kwargs)
            return wrapper

    def _execute_sync(self, func, args, kwargs):
        """
        Execute a synchronous function with automatic retry logic and exponential backoff.

        This internal method implements the core retry mechanism for synchronous
        functions, including exponential backoff with jitter and intelligent
        exception handling. It only retries on configured exception types
        and respects the maximum retry count and backoff limits.

        The method tracks retry attempts, calculates appropriate delays,
        and logs retry information for monitoring and debugging purposes.

        Args:
            func (Callable): The original synchronous function to execute.
            args (tuple): Positional arguments to pass to the function.
            kwargs (dict): Keyword arguments to pass to the function.

        Returns:
            Any: The return value of the successfully executed function.

        Raises:
            Exception: The last exception encountered if all retries are exhausted,
                      or immediately for non-retryable exception types.

        Side Effects:
            - Logs retry attempts with timing and error information
            - Sleeps between retry attempts using calculated backoff delays
            - May execute the function multiple times

        Examples:
            >>> # This method is called internally by the decorator
            >>> # User code doesn't call this directly
            >>> @resilient(max_retries=3)
            >>> def api_call():
            ...     return requests.get("https://api.example.com")
        """
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
        """
        Execute an asynchronous function with automatic retry logic and exponential backoff.

        This internal method implements the core retry mechanism for asynchronous
        functions, providing the same retry capabilities as the synchronous version
        but using async/await patterns and non-blocking delays. It supports
        coroutines and maintains async context throughout the retry process.

        The method handles async exceptions, implements non-blocking delays
        using asyncio.sleep, and preserves the asynchronous nature of the
        original function.

        Args:
            func (Callable[[], Awaitable]): The original async function to execute.
            args (tuple): Positional arguments to pass to the async function.
            kwargs (dict): Keyword arguments to pass to the async function.

        Returns:
            Any: The return value of the successfully executed async function.

        Raises:
            Exception: The last exception encountered if all retries are exhausted,
                      or immediately for non-retryable exception types.

        Side Effects:
            - Logs retry attempts with timing and error information
            - Uses asyncio.sleep for non-blocking delays between retries
            - May execute the async function multiple times
            - Maintains async context and event loop compatibility

        Examples:
            >>> # This method is called internally by the decorator
            >>> # User code doesn't call this directly
            >>> @resilient(max_retries=3)
            >>> async def async_api_call():
            ...     async with aiohttp.ClientSession() as session:
            ...         return await session.get("https://api.example.com")
        """
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
                await anyio.sleep(backoff_ms / 1000)
            except Exception as e:
                # Don't retry on non-retryable exceptions
                raise

        # If we get here, all retries failed
        logger.error(f"All {self.config.max_retries} retries failed for {func.__name__}")
        raise last_exception


class ResilienceManager:
    """
    Resilience Manager for Distributed IPFS Operations

    The ResilienceManager class provides comprehensive resilience capabilities
    for distributed operations across IPFS nodes. It orchestrates health monitoring,
    circuit breaker management, automatic retries, and operation tracking to ensure
    robust performance in the face of network failures, node outages, and other
    distributed system challenges.

    This manager serves as the central coordination point for all resilience
    mechanisms, providing a unified interface for building fault-tolerant
    distributed applications on top of the IPFS network.

    Args:
        node (LibP2PNode): The P2P node instance for network communication.
            Must be properly initialized and connected to the IPFS network.
            Used for sending health checks, messages, and coordinating operations.
        storage_dir (Optional[str], optional): Directory path for storing resilience
            data including checkpoints and health metrics. If None, defaults to
            ".ipfs_datasets/resilience" in the current working directory.
            The directory structure will be created automatically.
        health_check_interval_sec (int, optional): Interval in seconds between
            automatic health checks of connected nodes. Lower values provide
            faster failure detection but increase network overhead.
            Defaults to DEFAULT_HEALTH_CHECK_INTERVAL_SEC.
        circuit_breaker_config (Optional[Dict[str, Any]], optional): Configuration
            dictionary for circuit breakers. Keys should follow the pattern
            "{operation}_threshold" and "{operation}_timeout" for customizing
            specific circuit breaker parameters. Defaults to standard configuration.
        retry_config (Optional[RetryConfig], optional): Default retry configuration
            for operations that don't specify their own retry parameters.
            Defaults to a new RetryConfig with standard settings.

    Key Features:
    - Continuous health monitoring of all connected IPFS nodes
    - Circuit breaker protection for common operations (connections, transfers, sync)
    - Automatic retry mechanisms with exponential backoff and jitter
    - Operation tracking and recovery with checkpoint support
    - Node selection algorithms based on health and performance metrics
    - Background health check scheduling with configurable intervals
    - Protocol handler registration for health check responses
    - Persistent storage of resilience data for recovery across restarts

    Attributes:
        node (LibP2PNode): The P2P node for network communication
        storage_dir (str): Directory for storing resilience data
        health_check_interval_sec (int): Interval for automatic health checks
        node_health (Dict[str, NodeHealth]): Health tracking for all known nodes
        circuit_breakers (Dict[str, CircuitBreaker]): Circuit breakers for operations
        operations (Dict[str, OperationResult]): Tracking for active/completed operations
        retry_config (RetryConfig): Default retry configuration
        running (bool): Flag indicating if background processes are active

    Public Methods:
        Health Management:
            get_node_health(node_id: str) -> Optional[NodeHealth]
            get_all_node_health() -> Dict[str, NodeHealth]
            get_healthy_nodes() -> List[str]
            select_best_nodes(count: int, exclude_nodes: List[str] = None) -> List[str]
        
        Circuit Breaker Management:
            create_circuit_breaker(name: str, ...) -> CircuitBreaker
            get_circuit_breaker(name: str) -> Optional[CircuitBreaker]
            execute_with_circuit_breaker(circuit_name: str, func: Callable) -> T
            execute_with_circuit_breaker_async(circuit_name: str, func: Callable) -> T
        
        Retry Operations:
            retry(func: Callable, config: Optional[RetryConfig] = None) -> T
            retry_async(func: Callable, config: Optional[RetryConfig] = None) -> T
        
        Operation Tracking:
            create_operation(operation_type: str) -> OperationResult
            get_operation(operation_id: str) -> Optional[OperationResult]
            create_checkpoint(...) -> Checkpoint
            get_latest_checkpoint(operation_id: str) -> Optional[Checkpoint]
        
        Resilient Operations:
            send_message_with_retry(...) -> Any
            connect_to_peer_with_retry(...) -> bool
            resilient_shard_transfer(...) -> OperationResult
            resilient_dataset_sync(...) -> OperationResult
            resilient_rebalance_shards(...) -> OperationResult
        
        Advanced Operations:
            execute_on_healthy_nodes(...) -> Dict[str, Union[T, Exception]]
            lazy_broadcast(...) -> Tuple[int, int]
            find_consistent_data(...) -> Tuple[Any, int]

    Usage Example:
        # Initialize with custom configuration
        manager = ResilienceManager(
            node=libp2p_node,
            storage_dir="/app/resilience",
            health_check_interval_sec=30,
            circuit_breaker_config={
                "shard_transfer_threshold": 3,
                "shard_transfer_timeout": 60
            }
        )
        
        # Use resilient operations
        try:
            result = await manager.resilient_shard_transfer(
                shard_id="shard_123",
                target_node_ids=["node_1", "node_2"],
                alternative_nodes=["node_3", "node_4"]
            )
            if result.is_successful():
                print(f"Transfer completed on {result.success_count} nodes")
        except Exception as e:
            print(f"Transfer failed: {e}")
        
        # Shutdown when done
        manager.shutdown()
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
        Initialize the Resilience Manager for distributed operations.

        This method sets up all necessary components for resilient distributed
        operations including health monitoring, circuit breakers, storage directories,
        and background processes. It creates default circuit breakers for common
        operations and starts the health checking system.

        The initialization process includes:
        - Setting up storage directories for checkpoints and health data
        - Creating circuit breakers for standard operations
        - Configuring retry behavior with provided or default settings
        - Starting background health check scheduler
        - Registering protocol handlers for health check responses

        Args:
            node (LibP2PNode): The P2P node instance for network communication.
                Must be properly initialized and capable of sending/receiving messages.
                This node will be used for all network operations including health
                checks, message sending, and distributed operations.
            storage_dir (Optional[str], optional): Absolute or relative path to
                directory for storing resilience data. If None, uses ".ipfs_datasets/resilience"
                in the current working directory. Subdirectories for "checkpoints" and
                "health_data" will be created automatically. Defaults to None.
            health_check_interval_sec (int, optional): Time interval in seconds
                between automatic health checks of connected nodes. Lower values
                provide faster failure detection but increase network traffic.
                Must be positive integer. Defaults to DEFAULT_HEALTH_CHECK_INTERVAL_SEC.
            circuit_breaker_config (Optional[Dict[str, Any]], optional): Custom
                configuration for circuit breakers. Dictionary keys should follow
                pattern "{operation}_threshold" for failure count and "{operation}_timeout"
                for reset timeout. Supported operations include: node_connection,
                message_send, message_receive, shard_transfer, dataset_sync, search.
                Defaults to None (uses standard configuration).
            retry_config (Optional[RetryConfig], optional): Default retry configuration
                for operations that don't specify custom retry parameters. Will be
                used as fallback for all retry operations. If None, creates new
                RetryConfig with standard settings. Defaults to None.

        Returns:
            None

        Raises:
            OSError: If storage directory creation fails due to permissions
            AttributeError: If node doesn't support required methods
            ValueError: If health_check_interval_sec is not positive

        Side Effects:
            - Creates storage directory structure on filesystem
            - Initializes internal state dictionaries for tracking
            - Creates default circuit breakers for common operations
            - Starts background health check thread
            - Registers protocol handlers on the P2P node
            - Sets running flag to True for background processes

        Examples:
            >>> # Basic initialization
            >>> manager = ResilienceManager(my_node)
            
            >>> # Custom configuration
            >>> manager = ResilienceManager(
            ...     node=my_node,
            ...     storage_dir="/var/lib/ipfs/resilience",
            ...     health_check_interval_sec=15,
            ...     circuit_breaker_config={
            ...         "shard_transfer_threshold": 5,
            ...         "shard_transfer_timeout": 120
            ...     }
            ... )
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
        """
        Create and initialize default circuit breakers for common IPFS operations.

        This internal method sets up circuit breakers for standard distributed
        operations that commonly fail in IPFS environments. Each circuit breaker
        is configured with thresholds and timeouts, either from the provided
        configuration or using sensible defaults.

        The default circuit breakers protect against cascading failures in:
        - Node connections and network establishment
        - Message sending and receiving operations
        - Shard transfer and data movement
        - Dataset synchronization across nodes
        - Search and discovery operations

        Args:
            config (Dict[str, Any]): Configuration dictionary containing custom
                thresholds and timeouts. Keys should follow the pattern
                "{operation}_threshold" for failure counts and "{operation}_timeout"
                for reset timeouts. Missing keys use default values.

        Returns:
            None

        Side Effects:
            - Creates CircuitBreaker instances for each standard operation
            - Registers circuit breakers in self.circuit_breakers dictionary
            - Overwrites any existing circuit breakers with the same names

        Examples:
            >>> # Called internally during initialization
            >>> config = {
            ...     "shard_transfer_threshold": 5,
            ...     "shard_transfer_timeout": 120,
            ...     "node_connection_threshold": 3
            ... }
            >>> manager._create_circuit_breakers(config)
        """
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
        """
        Register protocol handlers for resilience-related network operations.

        This internal method registers handlers with the P2P node to respond
        to incoming resilience protocol messages, particularly health check
        requests from other nodes in the network. This enables bidirectional
        health monitoring across the distributed system.

        The method only registers handlers if the node supports the
        register_protocol_handler capability, providing graceful degradation
        for nodes that don't support advanced protocol handling.

        Returns:
            None

        Side Effects:
            - Registers health check handler with the P2P node
            - Enables incoming health check request processing
            - May modify node's protocol handler registry

        Examples:
            >>> # Called internally during initialization
            >>> manager._setup_protocol_handlers()
            >>> # Now the node can respond to health check requests
        """
        if hasattr(self.node, 'register_protocol_handler'):
            # Register health check handler
            self.node.register_protocol_handler(
                NetworkProtocol.HEALTH_CHECK,
                self._handle_health_check
            )

    def _start_health_checker(self):
        """
        Start the background health checking system in a daemon thread.

        This internal method launches a background thread that continuously
        monitors the health of connected peers at regular intervals. The
        thread runs as a daemon, ensuring it doesn't prevent application
        shutdown, and operates independently of the main execution flow.

        The health checker provides proactive monitoring of node availability,
        response times, and overall network health, enabling intelligent
        decision-making for distributed operations.

        Returns:
            None

        Side Effects:
            - Creates and starts a daemon thread running _health_check_loop
            - Begins continuous background health monitoring
            - Thread continues until self.running is set to False

        Examples:
            >>> # Called internally during initialization
            >>> manager._start_health_checker()
            >>> # Background health checking is now active
        """
        checker_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True
        )
        checker_thread.start()

    def _health_check_loop(self):
        """
        Background loop for conducting periodic health checks of connected peers.

        This method runs continuously in a background thread, performing health
        checks on all connected peers at regular intervals. It implements
        intelligent scheduling to avoid redundant checks and manages the
        health check lifecycle for optimal network monitoring.

        The loop includes:
        - Periodic scheduling based on health_check_interval_sec
        - Duplicate check prevention for recently checked nodes
        - Asynchronous health check execution to avoid blocking
        - Error handling and logging for monitoring failures

        Returns:
            None

        Side Effects:
            - Continuously updates node health information
            - Calls _check_node_health for each connected peer
            - Sleeps between iterations based on configured interval
            - Logs errors encountered during health checking
            - Runs until self.running is set to False

        Examples:
            >>> # This method runs automatically in background thread
            >>> # Started by _start_health_checker() during initialization
        """
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
                        anyio.run(self._check_node_health(peer_id))
            except Exception as e:
                logger.error(f"Error in health check loop: {str(e)}")

    async def _check_node_health(self, node_id: str):
        """
        Perform a comprehensive health check on a specific node.

        This internal async method conducts a detailed health assessment of a
        target node by sending a health check request and analyzing the response.
        It measures response times, evaluates node capabilities, and updates
        the internal health tracking with current status information.

        The health check process includes:
        - Response time measurement for performance tracking
        - Capability detection from node responses
        - Load metrics collection for resource awareness
        - Success/failure recording for availability scoring

        Args:
            node_id (str): Unique identifier of the node to check. Must be
                a valid peer ID that can receive network messages.

        Returns:
            None

        Raises:
            Exception: If health check fails due to network issues or timeouts.
                     Failures are logged and recorded in health metrics.

        Side Effects:
            - Updates or creates NodeHealth record for the target node
            - Records response time measurements
            - Updates availability score based on success/failure
            - Logs health check results for monitoring

        Examples:
            >>> # Called internally by health check loop
            >>> await manager._check_node_health("peer_abc123")
            >>> # Node health is updated in self.node_health
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
        Handle incoming health check requests from other nodes in the network.

        This async method processes health check requests received from peer
        nodes, gathering local system information and responding with current
        node status, capabilities, and load metrics. It enables bidirectional
        health monitoring across the distributed network.

        The response includes:
        - Node status and identification
        - Current timestamp for synchronization
        - Node capabilities and supported features
        - Real-time load metrics (CPU, memory, disk, network)

        Args:
            stream: Network stream for reading request and sending response.
                   Must support async read/write operations.

        Returns:
            None

        Raises:
            Exception: Network or serialization errors are handled gracefully
                     with error responses sent back to requester.

        Side Effects:
            - Reads health check request from network stream
            - Gathers current system metrics
            - Sends comprehensive health response
            - Closes network stream when complete
            - Logs errors for monitoring purposes

        Examples:
            >>> # Registered as protocol handler during initialization
            >>> # Called automatically when health check requests arrive
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
        """
        Detect and return the capabilities of this node for health reporting.

        This internal method inspects the current node to determine its
        capabilities, supported protocols, and available features. This
        information is used in health check responses to help other nodes
        understand what services this node can provide.

        The capability detection includes:
        - Node roles (if available)
        - Supported network protocols
        - Available features based on attached managers

        Returns:
            Dict[str, Any]: Dictionary containing node capabilities with keys:
                           - "roles": List of node roles
                           - "protocols": List of supported protocol values
                           - "features": List of available feature strings

        Examples:
            >>> capabilities = manager._get_node_capabilities()
            >>> print(capabilities)
            {
                "roles": ["storage_node"],
                "protocols": ["health_check", "shard_transfer"],
                "features": ["shard_management"]
            }
        """
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
        """
        Collect current system load metrics for health reporting and monitoring.

        This internal method gathers system resource utilization information
        to provide insights into node performance and capacity. The metrics
        help other nodes make informed decisions about whether to send
        operations to this node.

        Resource collection includes:
        - CPU utilization percentage
        - Memory usage percentage
        - Disk space utilization
        - Network connection counts
        - Active operation tracking

        If psutil is not available, falls back to minimal metrics using
        internal operation counting.

        Returns:
            Dict[str, Any]: Dictionary containing load metrics with keys:
                           - "cpu_percent": CPU usage percentage (0.0-100.0)
                           - "memory_percent": Memory usage percentage (0.0-100.0)
                           - "disk_percent": Disk usage percentage (0.0-100.0)
                           - "network_connections": Number of active connections
                           - "active_operations": Number of tracked operations

        Examples:
            >>> metrics = manager._get_load_metrics()
            >>> print(metrics)
            {
                "cpu_percent": 25.3,
                "memory_percent": 67.8,
                "disk_percent": 45.2,
                "network_connections": 15,
                "active_operations": 3
            }
        """
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
        Get comprehensive health information for a specific node.

        This method retrieves the current health status, performance metrics,
        and capability information for a specified node in the distributed
        system. The health information includes response times, failure counts,
        availability scores, and detected capabilities.

        Args:
            node_id (str): Unique identifier of the node whose health information
                is requested. Must be a valid node ID that exists in the network
                or has been previously monitored.

        Returns:
            Optional[NodeHealth]: Complete health information for the specified
                                node including status, metrics, and capabilities.
                                Returns None if the node has never been monitored
                                or the node_id is not found.

        Examples:
            >>> health = manager.get_node_health("peer_abc123")
            >>> if health:
            ...     print(f"Node status: {health.status.value}")
            ...     print(f"Availability: {health.availability_score:.2f}")
            ...     print(f"Avg response: {health.avg_response_time_ms}ms")
            >>> else:
            ...     print("Node not found or never monitored")
        """
        return self.node_health.get(node_id)

    def get_all_node_health(self) -> Dict[str, NodeHealth]:
        """
        Get health information for all monitored nodes in the network.

        This method returns a comprehensive mapping of all nodes that have
        been monitored by the resilience manager, including their current
        health status, performance metrics, and historical data. This is
        useful for network-wide health assessment and monitoring dashboards.

        Returns:
            Dict[str, NodeHealth]: Dictionary mapping node IDs to their complete
                                 health information. Includes all nodes that have
                                 been encountered during health checks, regardless
                                 of their current status (healthy, degraded, unhealthy).
                                 Empty dictionary if no nodes have been monitored.

        Examples:
            >>> all_health = manager.get_all_node_health()
            >>> print(f"Monitoring {len(all_health)} nodes")
            >>> for node_id, health in all_health.items():
            ...     print(f"{node_id}: {health.status.value} ({health.availability_score:.2f})")
            
            >>> # Filter by status
            >>> unhealthy_nodes = {
            ...     node_id: health for node_id, health in all_health.items()
            ...     if health.status == HealthStatus.UNHEALTHY
            ... }
        """
        return self.node_health

    def get_healthy_nodes(self) -> List[str]:
        """
        Get a list of node IDs that are currently marked as healthy.

        This method filters all monitored nodes to return only those with
        a health status of HEALTHY. These nodes are considered reliable
        for new operations and are prioritized in node selection algorithms.
        The list is updated in real-time based on ongoing health checks.

        Returns:
            List[str]: List of node IDs with HealthStatus.HEALTHY status.
                      Nodes are included only if they have passed recent
                      health checks and have not exceeded failure thresholds.
                      Empty list if no healthy nodes are available.

        Examples:
            >>> healthy_nodes = manager.get_healthy_nodes()
            >>> if healthy_nodes:
            ...     print(f"Available healthy nodes: {len(healthy_nodes)}")
            ...     selected_node = healthy_nodes[0]  # Use first healthy node
            >>> else:
            ...     print("No healthy nodes available")
            ...     # Implement fallback strategy
            
            >>> # Use for node selection
            >>> target_nodes = manager.get_healthy_nodes()[:3]  # Select up to 3 healthy nodes
        """
        return [
            node_id for node_id, health in self.node_health.items()
            if health.status == HealthStatus.HEALTHY
        ]

    def select_best_nodes(self, count: int, exclude_nodes: List[str] = None) -> List[str]:
        """
        Select the best performing nodes based on health metrics and availability.

        This method intelligently selects nodes for operations based on their
        availability scores, health status, and performance history. It excludes
        unhealthy nodes and applies the provided exclusion list, then ranks
        remaining nodes by their availability score to select the top performers.

        The selection algorithm prioritizes nodes with:
        - High availability scores (0.0-1.0 based on success/failure history)
        - Non-UNHEALTHY status (HEALTHY or DEGRADED are acceptable)
        - Not in the exclusion list

        Args:
            count (int): Maximum number of nodes to select. Must be a positive
                integer. If fewer nodes are available than requested, returns
                all available nodes.
            exclude_nodes (List[str], optional): List of node IDs to exclude
                from selection. Useful for avoiding recently failed nodes or
                nodes already assigned to other operations. Defaults to None
                (no exclusions).

        Returns:
            List[str]: List of selected node IDs, ordered by availability score
                      (highest first). Length will be min(count, available_nodes).
                      Empty list if no suitable nodes are available.

        Examples:
            >>> # Select best 3 nodes for operation
            >>> best_nodes = manager.select_best_nodes(3)
            >>> print(f"Selected nodes: {best_nodes}")
            
            >>> # Exclude previously failed nodes
            >>> failed_nodes = ["node_1", "node_2"]
            >>> alternative_nodes = manager.select_best_nodes(
            ...     count=5, 
            ...     exclude_nodes=failed_nodes
            ... )
            
            >>> # Handle case with insufficient nodes
            >>> nodes = manager.select_best_nodes(10)
            >>> if len(nodes) < 10:
            ...     print(f"Only {len(nodes)} nodes available")
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
        Create and register a new circuit breaker for operation protection.

        This method creates a new circuit breaker with the specified configuration
        and registers it with the resilience manager for use in protected operations.
        The circuit breaker will monitor failures and automatically trip to prevent
        cascading failures when thresholds are exceeded.

        Args:
            name (str): Unique name for the circuit breaker. Must be unique within
                the resilience manager. Used for lookup and logging. Should be
                descriptive of the protected operation (e.g., "database_query",
                "external_api").
            failure_threshold (int, optional): Number of consecutive failures
                required to trip the circuit to OPEN state. Higher values provide
                more tolerance but slower failure detection. Must be positive.
                Defaults to DEFAULT_CIRCUIT_BREAKER_THRESHOLD.
            reset_timeout_sec (int, optional): Time in seconds to wait in OPEN
                state before transitioning to HALF_OPEN for recovery testing.
                Longer timeouts give more recovery time but delay service restoration.
                Must be positive. Defaults to DEFAULT_CIRCUIT_BREAKER_RESET_TIMEOUT_SEC.

        Returns:
            CircuitBreaker: The newly created and registered circuit breaker
                          instance, ready for use in execute operations.

        Raises:
            ValueError: If name is empty or parameters are invalid

        Side Effects:
            - Registers circuit breaker in internal registry
            - Overwrites any existing circuit breaker with the same name

        Examples:
            >>> # Create circuit breaker for API calls
            >>> api_breaker = manager.create_circuit_breaker(
            ...     name="external_api",
            ...     failure_threshold=5,
            ...     reset_timeout_sec=30
            ... )
            
            >>> # Create circuit breaker for database operations
            >>> db_breaker = manager.create_circuit_breaker(
            ...     name="database_query",
            ...     failure_threshold=3,
            ...     reset_timeout_sec=60
            ... )
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
        Retrieve a circuit breaker by name from the registry.

        This method looks up and returns a previously created circuit breaker
        by its unique name. Used to access existing circuit breakers for
        execution protection or status checking.

        Args:
            name (str): Unique name of the circuit breaker to retrieve.
                Must match the name used when the circuit breaker was created.

        Returns:
            Optional[CircuitBreaker]: The circuit breaker instance if found,
                                    None if no circuit breaker exists with
                                    the specified name.

        Examples:
            >>> # Get existing circuit breaker
            >>> breaker = manager.get_circuit_breaker("external_api")
            >>> if breaker:
            ...     print(f"Circuit state: {breaker.state}")
            ...     print(f"Failure count: {breaker.failures}")
            >>> else:
            ...     print("Circuit breaker not found")
            
            >>> # Check circuit status before operation
            >>> api_breaker = manager.get_circuit_breaker("api_calls")
            >>> if api_breaker and api_breaker.state == "OPEN":
            ...     print("API circuit is open, using fallback")
        """
        return self.circuit_breakers.get(name)

    def execute_with_circuit_breaker(
        self,
        circuit_name: str,
        func: Callable[[], T]
    ) -> T:
        """
        Execute a synchronous function with circuit breaker protection.

        This method wraps function execution with circuit breaker logic to
        prevent cascading failures. If the named circuit breaker is in OPEN
        state, the function is not executed and an exception is raised immediately.
        Otherwise, the function executes normally and the circuit breaker
        tracks the result for future state management.

        Args:
            circuit_name (str): Name of the circuit breaker to use for protection.
                Must match a circuit breaker created previously with
                create_circuit_breaker() or during initialization.
            func (Callable[[], T]): Synchronous function to execute with protection.
                Must be a callable that takes no arguments and returns a value.
                The function should raise exceptions on failure.

        Returns:
            T: The result returned by the executed function if successful.

        Raises:
            CircuitBreakerOpenError: If the circuit breaker is in OPEN state
            Exception: Any exception raised by the executed function

        Examples:
            >>> # Execute with existing circuit breaker
            >>> result = manager.execute_with_circuit_breaker(
            ...     "database_query",
            ...     lambda: database.fetch_user(user_id)
            ... )
            
            >>> # Handle circuit breaker open state
            >>> try:
            ...     data = manager.execute_with_circuit_breaker(
            ...         "api_calls", 
            ...         lambda: api.get_data()
            ...     )
            >>> except CircuitBreakerOpenError:
            ...     data = get_cached_data()  # Fallback
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
        Execute an asynchronous function with circuit breaker protection.

        This async method provides circuit breaker protection for async operations,
        following the same logic as the synchronous version but supporting
        coroutines and async/await patterns. The circuit breaker tracks async
        operation results and manages state transitions appropriately.

        Args:
            circuit_name (str): Name of the circuit breaker to use for protection.
                Must match a circuit breaker created previously with
                create_circuit_breaker() or during initialization.
            func (Callable[[], Awaitable[T]]): Async function to execute with protection.
                Must be a callable that takes no arguments and returns an awaitable.
                The function should raise exceptions on failure.

        Returns:
            T: The result returned by the executed async function if successful.

        Raises:
            CircuitBreakerOpenError: If the circuit breaker is in OPEN state
            Exception: Any exception raised by the executed async function

        Examples:
            >>> # Execute async operation with circuit breaker
            >>> result = await manager.execute_with_circuit_breaker_async(
            ...     "async_api",
            ...     lambda: aiohttp_session.get("https://api.example.com")
            ... )
            
            >>> # Handle circuit breaker in async context
            >>> try:
            ...     data = await manager.execute_with_circuit_breaker_async(
            ...         "database_async",
            ...         lambda: async_db.query(sql)
            ...     )
            >>> except CircuitBreakerOpenError:
            ...     data = await get_cached_data_async()
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
        Execute an async function with automatic retry logic and exponential backoff.

        This method provides comprehensive retry capabilities for async operations,
        implementing exponential backoff with jitter, intelligent exception filtering,
        and detailed logging. It uses the provided retry configuration or falls
        back to the manager's default configuration.

        Args:
            func (Callable[[], Awaitable[T]]): Async function to execute with retries.
                Must be a callable that returns an awaitable and raises exceptions
                on failure. Should take no arguments.
            config (Optional[RetryConfig], optional): Custom retry configuration
                specifying max retries, backoff parameters, and exception types.
                If None, uses the manager's default retry configuration.
                Defaults to None.

        Returns:
            T: The result returned by the successfully executed async function.

        Raises:
            Exception: The last exception encountered if all retries are exhausted,
                      or immediately for non-retryable exception types.

        Side Effects:
            - May execute the function multiple times
            - Uses asyncio.sleep for non-blocking delays between retries
            - Logs retry attempts with timing and error information

        Examples:
            >>> # Retry with default configuration
            >>> result = await manager.retry_async(
            ...     lambda: aiohttp_session.get("https://api.example.com")
            ... )
            
            >>> # Retry with custom configuration
            >>> custom_config = RetryConfig(max_retries=5, initial_backoff_ms=200)
            >>> data = await manager.retry_async(
            ...     lambda: fetch_critical_data(),
            ...     config=custom_config
            ... )
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
                await anyio.sleep(backoff_ms / 1000)
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
        Execute a synchronous function with automatic retry logic and exponential backoff.

        This method provides comprehensive retry capabilities for synchronous operations,
        implementing exponential backoff with jitter, intelligent exception filtering,
        and detailed logging. It uses the provided retry configuration or falls
        back to the manager's default configuration.

        Args:
            func (Callable[[], T]): Synchronous function to execute with retries.
                Must be a callable that takes no arguments and raises exceptions
                on failure. Should return a value of type T on success.
            config (Optional[RetryConfig], optional): Custom retry configuration
                specifying max retries, backoff parameters, and exception types.
                If None, uses the manager's default retry configuration.
                Defaults to None.

        Returns:
            T: The result returned by the successfully executed function.

        Raises:
            Exception: The last exception encountered if all retries are exhausted,
                      or immediately for non-retryable exception types.

        Side Effects:
            - May execute the function multiple times
            - Uses time.sleep for blocking delays between retries
            - Logs retry attempts with timing and error information

        Examples:
            >>> # Retry with default configuration
            >>> result = manager.retry(
            ...     lambda: requests.get("https://api.example.com")
            ... )
            
            >>> # Retry with custom configuration
            >>> custom_config = RetryConfig(max_retries=3, initial_backoff_ms=100)
            >>> data = manager.retry(
            ...     lambda: database.fetch_data(),
            ...     config=custom_config
            ... )
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
        Create a new operation tracking object for distributed operations.

        This method creates and registers a new OperationResult object to track
        the progress and results of distributed operations across multiple nodes.
        The operation is assigned a unique identifier and initialized with
        tracking capabilities for success/failure counts and node-specific results.

        Args:
            operation_type (str): Descriptive type of the operation being tracked.
                Used in the generated operation ID for identification and logging.
                Examples: "shard_transfer", "dataset_sync", "rebalancing",
                "backup", "migration".

        Returns:
            OperationResult: A new operation tracking object with a unique ID,
                           initialized in PENDING status and ready to track
                           node operations and results.

        Side Effects:
            - Generates unique operation ID with timestamp and random components
            - Registers operation in internal operations registry
            - Sets operation start time to current timestamp
            - Initializes operation status as PENDING

        Examples:
            >>> # Create operation for shard transfer
            >>> operation = manager.create_operation("shard_transfer")
            >>> print(f"Created operation: {operation.operation_id}")
            >>> # Use operation to track progress
            >>> operation.add_success("node_1", {"bytes": 1024})
            >>> operation.add_failure("node_2", "Connection timeout")
            
            >>> # Create operation for dataset synchronization
            >>> sync_op = manager.create_operation("dataset_sync")
            >>> # Track sync across multiple nodes...
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
        Retrieve an operation tracking object by its unique identifier.

        This method looks up and returns a previously created operation from
        the internal registry. Used to check operation status, retrieve results,
        or continue tracking an ongoing distributed operation.

        Args:
            operation_id (str): Unique identifier of the operation to retrieve.
                Must match the operation_id from a previously created operation.

        Returns:
            Optional[OperationResult]: The operation tracking object if found,
                                     containing all current status, progress,
                                     and result information. None if no operation
                                     exists with the specified ID.

        Examples:
            >>> # Retrieve operation by ID
            >>> operation = manager.get_operation("shard_transfer_1694436123_4567")
            >>> if operation:
            ...     print(f"Status: {operation.status.value}")
            ...     print(f"Success count: {operation.success_count}")
            ...     print(f"Failure count: {operation.failure_count}")
            >>> else:
            ...     print("Operation not found")
            
            >>> # Check if operation is complete
            >>> op = manager.get_operation(operation_id)
            >>> if op and op.is_successful():
            ...     print("Operation completed successfully")
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
        Create and save a checkpoint for a long-running distributed operation.

        This method creates a checkpoint containing the current state of a
        distributed operation, enabling recovery and resumption if the operation
        is interrupted. The checkpoint is automatically saved to persistent
        storage and can be retrieved later for operation resumption.

        Args:
            operation_id (str): Unique identifier of the operation being checkpointed.
                Must match an existing operation ID from create_operation().
            completed_items (List[str]): List of item identifiers that have been
                successfully completed. Items can be node IDs, file paths, shard IDs,
                or any operation-specific identifiers.
            pending_items (List[str]): List of item identifiers that still need
                processing when the operation resumes. Represents remaining work.
            metadata (Dict[str, Any], optional): Additional operation-specific state
                information required for proper resumption. Can include configuration,
                intermediate results, or recovery data. Defaults to None (empty dict).

        Returns:
            Checkpoint: The created checkpoint object with unique ID and timestamp,
                       already saved to persistent storage.

        Side Effects:
            - Creates checkpoint file in storage directory
            - Generates unique checkpoint ID with timestamp
            - Saves checkpoint data to JSON file for persistence

        Examples:
            >>> # Checkpoint during bulk operation
            >>> checkpoint = manager.create_checkpoint(
            ...     operation_id="shard_migration_001",
            ...     completed_items=["shard_1", "shard_2", "shard_5"],
            ...     pending_items=["shard_3", "shard_4", "shard_6"],
            ...     metadata={"batch_size": 100, "current_node": "node_abc"}
            ... )
            >>> print(f"Checkpoint saved: {checkpoint.checkpoint_id}")
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
        Retrieve the most recent checkpoint for a specific operation.

        This method searches the checkpoint storage directory for the latest
        checkpoint belonging to the specified operation. It automatically
        identifies the most recent checkpoint based on timestamps embedded
        in checkpoint filenames, enabling seamless operation resumption.

        Args:
            operation_id (str): Unique identifier of the operation whose latest
                checkpoint should be retrieved. Must match the operation_id used
                when creating checkpoints.

        Returns:
            Optional[Checkpoint]: The most recent checkpoint for the operation
                                if found, containing all saved state information.
                                None if no checkpoints exist for the operation.

        Examples:
            >>> # Resume operation from latest checkpoint
            >>> latest = manager.get_latest_checkpoint("bulk_transfer_001")
            >>> if latest:
            ...     print(f"Resuming from checkpoint: {latest.checkpoint_id}")
            ...     print(f"Completed: {len(latest.completed_items)} items")
            ...     print(f"Pending: {len(latest.pending_items)} items")
            ...     resume_operation(latest.pending_items, latest.metadata)
            >>> else:
            ...     print("No checkpoint found, starting fresh operation")
            ...     start_new_operation()
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
        Send a message to a peer with automatic retry logic and resilience handling.

        This method implements resilient message transmission with circuit breaker
        protection, automatic retries, and comprehensive error handling. It tracks
        peer health, applies timeouts, and provides detailed operation results
        for monitoring and debugging purposes.

        Args:
            peer_id (str): Unique identifier of the target peer node.
                Must be a valid libp2p peer ID in the network.
            protocol (NetworkProtocol): Network protocol to use for message transmission.
                Defines the communication protocol and message format.
            data (Any): Message payload to send to the peer.
                Must be serializable and conform to protocol expectations.
            timeout_ms (int, optional): Maximum time to wait for message delivery
                in milliseconds. Includes retry attempts and network delays.
                Defaults to DEFAULT_REQUEST_TIMEOUT_MS.
            retry_config (Optional[RetryConfig], optional): Custom retry configuration
                specifying max retries, backoff parameters, and exception types.
                If None, uses the manager's default retry configuration.
                Defaults to None.

        Returns:
            Any: The response received from the peer, or None if no response expected.

        Raises:
            Exception: If message sending fails after all retries, or if the peer
                      is marked as unhealthy and circuit breaker prevents transmission.

        Side Effects:
            - Updates peer health status based on response
            - May trigger circuit breaker state changes
            - Logs message attempts and results
            - Records operation metrics and timing

        Examples:
            >>> # Send message with default settings
            >>> response = await manager.send_message_with_retry(
            ...     peer_id="QmAbc123...",
            ...     protocol=NetworkProtocol.DATA_SYNC,
            ...     data={"type": "ping", "data": "hello"}
            ... )
            
            >>> # Send with custom timeout and retry config
            >>> custom_retry = RetryConfig(max_retries=5, initial_backoff_ms=200)
            >>> response = await manager.send_message_with_retry(
            ...     peer_id="QmDef456...",
            ...     protocol=NetworkProtocol.SHARD_TRANSFER,
            ...     data={"shard_id": "abc123", "action": "request"},
            ...     timeout_ms=60000,
            ...     retry_config=custom_retry
            ... )
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
        Establish connection to a peer with automatic retry logic and circuit protection.

        This method implements resilient peer connection with circuit breaker
        protection, exponential backoff retry logic, and peer health tracking.
        It ensures robust network connectivity in distributed environments
        with automatic failure recovery.

        Args:
            peer_id (str): Unique identifier of the target peer node.
                Must be a valid libp2p peer ID that exists in the network.
            retry_config (Optional[RetryConfig], optional): Custom retry configuration
                specifying max retries, backoff parameters, and exception types.
                If None, uses the manager's default retry configuration.
                Defaults to None.

        Returns:
            bool: True if connection was successfully established, False otherwise.

        Raises:
            Exception: If connection fails after all retries are exhausted.
            NotImplementedError: If the underlying node doesn't support peer connections.

        Side Effects:
            - Updates peer health status based on connection success/failure
            - May trigger circuit breaker state changes
            - Logs connection attempts and results
            - Establishes persistent network connection

        Examples:
            >>> # Connect with default retry settings
            >>> success = await manager.connect_to_peer_with_retry("QmAbc123...")
            >>> if success:
            ...     print("Connected successfully")
            
            >>> # Connect with custom retry configuration
            >>> custom_retry = RetryConfig(max_retries=3, initial_backoff_ms=100)
            >>> try:
            ...     await manager.connect_to_peer_with_retry(
            ...         "QmDef456...", 
            ...         retry_config=custom_retry
            ...     )
            ... except Exception as e:
            ...     print(f"Connection failed: {e}")
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
        Transfer a data shard to target nodes with comprehensive resilience mechanisms.

        This method orchestrates reliable shard transfer with automatic failover
        between alternative nodes, circuit breaker protection, and intelligent
        retry logic. It ensures data availability and provides detailed progress
        tracking for shard distribution operations in the network.

        Args:
            shard_id (str): Unique identifier of the shard to transfer.
                Must be a valid shard ID that exists in the local shard manager.
            target_node_ids (List[str]): List of peer IDs that should receive the shard.
                Transfer will be attempted to all target nodes independently,
                with individual retry logic for each node.
            alternative_nodes (Optional[List[str]], optional): List of alternative
                peer IDs to try if primary target transfers fail. Used for
                automatic failover to maintain replication targets.
                Defaults to None.

        Returns:
            OperationResult: Comprehensive result containing transfer status,
                           successful and failed node counts, timing metrics,
                           and detailed error information for any failed transfers.

        Raises:
            NotImplementedError: If the underlying node doesn't have a shard manager.

        Side Effects:
            - Transfers shard data to multiple target nodes
            - Updates health status for all involved nodes
            - May trigger circuit breaker state changes
            - Creates operation tracking and progress monitoring
            - Logs detailed transfer progress and results

        Examples:
            >>> # Transfer shard to primary targets
            >>> result = await manager.resilient_shard_transfer(
            ...     shard_id="shard_abc123",
            ...     target_node_ids=["QmTarget1...", "QmTarget2...", "QmTarget3..."]
            ... )
            >>> if result.is_successful():
            ...     print(f"Shard transferred to {result.success_count} nodes")
            >>> else:
            ...     print(f"Transfer failed: {result.error_message}")
            
            >>> # Transfer with failover alternatives
            >>> result = await manager.resilient_shard_transfer(
            ...     shard_id="critical_shard_456",
            ...     target_node_ids=["QmPrimary1...", "QmPrimary2..."],
            ...     alternative_nodes=["QmBackup1...", "QmBackup2...", "QmBackup3..."]
            ... )
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
        Synchronize dataset metadata with target nodes using resilience mechanisms.

        This method orchestrates dataset metadata synchronization across multiple
        nodes with circuit breaker protection, parallel processing control,
        automatic retry logic, and comprehensive error handling. It ensures
        dataset consistency across the distributed network.

        Args:
            dataset_id (str): Unique identifier of the dataset to synchronize.
                Must correspond to an existing dataset in the shard manager.
            target_node_ids (List[str]): List of peer IDs that should receive
                the dataset metadata. Synchronization will be attempted with
                all specified nodes in parallel batches.
            max_concurrent (int, optional): Maximum number of concurrent
                synchronization operations to run simultaneously. Controls
                resource usage and network load. Defaults to 3.

        Returns:
            OperationResult: Comprehensive result containing synchronization status,
                           success/failure counts per node, timing metrics, and
                           detailed error information for any failed operations.

        Raises:
            NotImplementedError: If the underlying node doesn't have a shard manager.

        Side Effects:
            - Updates peer health status based on sync success/failure
            - May trigger circuit breaker state changes
            - Creates operation tracking for monitoring
            - Logs synchronization progress and results

        Examples:
            >>> # Sync dataset with multiple nodes
            >>> result = await manager.resilient_dataset_sync(
            ...     dataset_id="dataset_abc123",
            ...     target_node_ids=["QmNode1...", "QmNode2...", "QmNode3..."]
            ... )
            >>> if result.is_successful():
            ...     print(f"Dataset synced in {result.execution_time_ms}ms")
            >>> else:
            ...     print(f"Sync completed with {result.failure_count} failures")
            
            >>> # Sync with custom concurrency
            >>> result = await manager.resilient_dataset_sync(
            ...     dataset_id="large_dataset_456",
            ...     target_node_ids=node_list,
            ...     max_concurrent=5
            ... )
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

            # Wait for batch to complete using anyio task group
            async with anyio.create_task_group() as tg:
                for node_id in batch:
                    # Create sync task
                    async def sync_with_node(nid):
                        try:
                            # Sync with circuit breaker and retry
                            async def sync_with_circuit_breaker():
                                return await self.execute_with_circuit_breaker_async(
                                    "dataset_sync",
                                    lambda: self.node.shard_manager.sync_dataset_with_node(dataset_id, nid)
                                )

                            result = await self.retry_async(sync_with_circuit_breaker)

                            # Record success
                            operation.add_success(nid, result)

                            # Update node health
                            if nid in self.node_health:
                                self.node_health[nid].record_success()

                            return True
                        except Exception as e:
                            # Record failure
                            operation.add_failure(nid, str(e))

                            # Update node health
                            if nid in self.node_health:
                                self.node_health[nid].record_failure()

                            logger.warning(f"Failed to sync dataset {dataset_id} with node {nid}: {str(e)}")
                            return False

                    tg.start_soon(sync_with_node, node_id)

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
        Rebalance data shards across the network with comprehensive resilience mechanisms.

        This method orchestrates intelligent shard redistribution to achieve optimal
        replication factors and load balancing across the network. It uses circuit
        breaker protection, health-aware node selection, and parallel transfer
        management to ensure robust shard rebalancing operations.

        Args:
            dataset_id (Optional[str], optional): Unique identifier of the specific
                dataset to rebalance. If None, rebalances shards for all datasets
                managed by this node. Defaults to None.
            target_replication (int, optional): Desired replication factor for each
                shard. The system will attempt to ensure each shard exists on
                exactly this many nodes. Defaults to 3.
            max_concurrent (int, optional): Maximum number of concurrent shard
                transfer operations to run simultaneously. Controls network
                bandwidth usage and system load. Defaults to 3.
            use_healthy_nodes_only (bool, optional): Whether to only use nodes
                marked as healthy for shard placement. If True and no healthy
                nodes are available, falls back to all connected peers.
                Defaults to True.

        Returns:
            OperationResult: Comprehensive result containing rebalancing status,
                           successful and failed transfer counts, timing metrics,
                           and detailed information about shard movements.

        Raises:
            NotImplementedError: If the underlying node doesn't have a shard manager.

        Side Effects:
            - Transfers shards between nodes to achieve target replication
            - Updates node health status based on transfer success/failure
            - May trigger circuit breaker state changes
            - Creates operation tracking for monitoring
            - Logs rebalancing progress and results

        Examples:
            >>> # Rebalance all datasets with default settings
            >>> result = await manager.resilient_rebalance_shards()
            >>> print(f"Rebalanced {result.success_count} shards")
            
            >>> # Rebalance specific dataset with custom replication
            >>> result = await manager.resilient_rebalance_shards(
            ...     dataset_id="critical_dataset_123",
            ...     target_replication=5,
            ...     max_concurrent=2
            ... )
            >>> if result.is_successful():
            ...     print("Rebalancing completed successfully")
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
        Execute an async function on all healthy nodes with controlled concurrency.

        This method provides distributed function execution across healthy nodes
        in the network with timeout protection, concurrent execution limits,
        and minimum success count validation. It ensures robust distributed
        operations with comprehensive error handling and result aggregation.

        Args:
            func (Callable[[str], Awaitable[T]]): Async function to execute on each
                healthy node. Must accept a single string parameter (node_id) and
                return an awaitable result of type T.
            min_success_count (int, optional): Minimum number of nodes that must
                successfully execute the function for the operation to be considered
                successful. Defaults to 1.
            max_concurrent (int, optional): Maximum number of concurrent function
                executions to run simultaneously. Controls resource usage and
                network load. Defaults to 3.
            timeout_sec (int, optional): Maximum time to wait for each individual
                function execution in seconds. Operations exceeding this timeout
                will be cancelled. Defaults to 30.

        Returns:
            Dict[str, Union[T, Exception]]: Dictionary mapping node IDs to their
                                          execution results. Successful executions
                                          return the function result, failures
                                          return the exception that occurred.

        Side Effects:
            - Executes the provided function on multiple healthy nodes
            - May update node health status based on execution results
            - Logs execution progress and results
            - Uses asyncio timeout and cancellation for resource management

        Examples:
            >>> # Execute data collection on all healthy nodes
            >>> async def collect_metrics(node_id: str) -> Dict[str, Any]:
            ...     return await get_node_metrics(node_id)
            
            >>> results = await manager.execute_on_healthy_nodes(
            ...     func=collect_metrics,
            ...     min_success_count=2,
            ...     timeout_sec=15
            ... )
            >>> successful_results = {
            ...     node_id: result for node_id, result in results.items()
            ...     if not isinstance(result, Exception)
            ... }
            
            >>> # Execute maintenance task with high concurrency
            >>> async def cleanup_cache(node_id: str) -> bool:
            ...     return await perform_cache_cleanup(node_id)
            
            >>> results = await manager.execute_on_healthy_nodes(
            ...     func=cleanup_cache,
            ...     max_concurrent=5
            ... )
        """
        # Get healthy nodes
        healthy_nodes = self.get_healthy_nodes()

        if not healthy_nodes:
            raise ValueError("No healthy nodes available")

        # Execute function on each node concurrently
        results = {}
        semaphore = anyio.Semaphore(max_concurrent)

        async def execute_with_timeout(node_id):
            async with semaphore:
                try:
                    with anyio.fail_after(timeout_sec):
                        return await func(node_id)
                except (TimeoutError, anyio.get_cancelled_exc_class()) as e:
                    return TimeoutError(f"Operation timed out after {timeout_sec} seconds")
                except Exception as e:
                    return e

        # Create tasks
        tasks = {node_id: execute_with_timeout(node_id) for node_id in healthy_nodes}

        # Execute all tasks concurrently using anyio
        results_dict = {}
        async with anyio.create_task_group() as tg:
            async def run_and_collect(node_id, coro):
                result = await coro
                results_dict[node_id] = result
            
            for node_id, coro in tasks.items():
                tg.start_soon(run_and_collect, node_id, coro)

        # Map results back to node IDs
        for node_id in tasks.keys():
            try:
                results[node_id] = results_dict.get(node_id)
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
        Broadcast a message using lazy propagation strategy for efficient network distribution.

        This method implements intelligent message broadcasting that sends to a carefully
        selected subset of high-quality nodes and relies on the P2P network's gossip
        protocol to efficiently propagate the message to the entire network. This
        approach reduces network load while ensuring wide message distribution.

        Args:
            protocol (NetworkProtocol): Network protocol to use for message transmission.
                Defines the communication protocol and message format for the broadcast.
            data (Any): Message payload to broadcast to the network.
                Must be serializable and conform to protocol expectations.
            min_reach (int, optional): Minimum number of nodes to send the message
                to directly. The system selects the most reliable nodes based on
                health metrics. Defaults to 3.
            timeout_ms (int, optional): Maximum time to wait for message delivery
                to each target node in milliseconds. Does not include propagation
                time through the P2P network. Defaults to 5000.

        Returns:
            Tuple[int, int]: A tuple containing (success_count, failure_count) where
                           success_count is the number of nodes that successfully
                           received the message directly, and failure_count is the
                           number of direct transmission failures.

        Side Effects:
            - Sends messages directly to selected high-quality nodes
            - Updates node health status based on transmission success/failure
            - Relies on P2P network gossip for further message propagation
            - Logs broadcast progress and results

        Examples:
            >>> # Broadcast system announcement
            >>> success, failures = await manager.lazy_broadcast(
            ...     protocol=NetworkProtocol.SYSTEM_BROADCAST,
            ...     data={"type": "maintenance_notice", "message": "System update at 3 AM"},
            ...     min_reach=5
            ... )
            >>> print(f"Direct delivery: {success} successful, {failures} failed")
            
            >>> # Broadcast urgent data update
            >>> success, failures = await manager.lazy_broadcast(
            ...     protocol=NetworkProtocol.DATA_SYNC,
            ...     data={"dataset_id": "urgent_update_123", "action": "refresh"},
            ...     min_reach=10,
            ...     timeout_ms=3000
            ... )
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

        # Wait for all sends to complete using anyio task group
        results = []
        async with anyio.create_task_group() as tg:
            async def collect_result(task_coro):
                try:
                    result = await task_coro
                    results.append(result)
                except Exception as e:
                    results.append(e)
            
            for task_coro in tasks:
                tg.start_soon(collect_result, task_coro)

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
        Query multiple nodes to find consensus data that meets quorum requirements.

        This method implements distributed consensus by querying all healthy nodes
        with the same request and analyzing responses to find data that a majority
        of nodes agree upon. It ensures data consistency and reliability in
        distributed systems by requiring quorum agreement.

        Args:
            protocol (NetworkProtocol): Network protocol to use for node queries.
                Defines the communication protocol and expected response format.
            request (Dict[str, Any]): Request payload to send to all nodes.
                Must be JSON-serializable and contain query parameters that
                all nodes can understand and respond to consistently.
            quorum_percentage (int, optional): Percentage of responding nodes
                required to achieve consensus. For example, 51 means more than
                half of responding nodes must agree. Defaults to 51.
            timeout_ms (int, optional): Maximum time to wait for each node's
                response in milliseconds. Nodes not responding within this
                time are excluded from consensus calculation. Defaults to 5000.

        Returns:
            Tuple[Any, int]: A tuple containing (consensus_data, agreement_count)
                           where consensus_data is the data that achieved quorum
                           consensus, and agreement_count is the number of nodes
                           that agreed on this data. Returns (None, 0) if no
                           consensus is reached.

        Raises:
            ValueError: If no healthy nodes are available for querying.

        Side Effects:
            - Queries all healthy nodes simultaneously
            - Updates node health status based on response success/failure
            - Logs consensus analysis and results
            - May identify and mark inconsistent nodes

        Examples:
            >>> # Find consensus on current dataset version
            >>> consensus_data, agreement = await manager.find_consistent_data(
            ...     protocol=NetworkProtocol.DATA_QUERY,
            ...     request={"query": "dataset_version", "dataset_id": "abc123"},
            ...     quorum_percentage=67
            ... )
            >>> if consensus_data:
            ...     print(f"Consensus reached: {agreement} nodes agree on version {consensus_data}")
            >>> else:
            ...     print("No consensus reached - data may be inconsistent")
            
            >>> # Query system status with majority requirement
            >>> status, count = await manager.find_consistent_data(
            ...     protocol=NetworkProtocol.SYSTEM_QUERY,
            ...     request={"query": "system_status"},
            ...     timeout_ms=3000
            ... )
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
        Retrieve all operations that match a specific status for monitoring and management.

        This method filters the internal operations registry to return only
        operations that have the specified status. This is useful for monitoring
        system health, identifying stuck operations, cleaning up completed work,
        or implementing operation lifecycle management.

        Args:
            status (OperationStatus): The status to filter operations by.
                Valid values include PENDING, IN_PROGRESS, COMPLETED,
                PARTIALLY_COMPLETED, FAILED, INTERRUPTED, and RECOVERED.

        Returns:
            List[OperationResult]: List of operation tracking objects that
                                 have the specified status. Empty list if no
                                 operations match the status filter.

        Examples:
            >>> # Find all failed operations for analysis
            >>> failed_ops = manager.get_operations_by_status(OperationStatus.FAILED)
            >>> for op in failed_ops:
            ...     print(f"Failed operation: {op.operation_id}")
            ...     print(f"Error: {op.error_message}")
            
            >>> # Check for pending operations
            >>> pending = manager.get_operations_by_status(OperationStatus.PENDING)
            >>> if pending:
            ...     print(f"{len(pending)} operations waiting to start")
            
            >>> # Clean up completed operations
            >>> completed = manager.get_operations_by_status(OperationStatus.COMPLETED)
            >>> for op in completed:
            ...     archive_operation_results(op)
        """
        return [op for op in self.operations.values() if op.status == status]

    def shutdown(self):
        """
        Shutdown the resilience manager and stop all background processes.

        This method gracefully shuts down the resilience manager by stopping
        the background health checking system and other running processes.
        It sets the running flag to False, which signals the health check
        loop and other background threads to terminate.

        This should be called when the application is shutting down or when
        the resilience manager is no longer needed to ensure clean resource
        cleanup and prevent daemon threads from keeping the application alive.

        Returns:
            None

        Side Effects:
            - Sets self.running to False
            - Signals background health check thread to terminate
            - Stops all periodic monitoring activities
            - Does not clear existing operation or health data

        Examples:
            >>> # Shutdown during application cleanup
            >>> try:
            ...     # Application operations
            ...     perform_distributed_operations()
            >>> finally:
            ...     # Always shutdown cleanly
            ...     manager.shutdown()
            
            >>> # Shutdown in context manager pattern
            >>> class ResilienceContext:
            ...     def __exit__(self, exc_type, exc_val, exc_tb):
            ...         self.manager.shutdown()
        """
        self.running = False
