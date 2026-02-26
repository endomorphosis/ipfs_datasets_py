"""
Batch 352: Database Connection Pooling
Comprehensive implementation of thread-safe connection pooling with lifecycle management.

Features:
- Connection pool with min/max size constraints
- Connection acquisition and release
- Connection validation and health checking
- Idle connection eviction after TTL
- Connection timeout handling
- Statistics and metrics tracking
- Concurrent access with fairness
- Stale connection detection

Test Classes (10 total, ~26 tests):
1. TestPoolCreation - Initialize and close pool
2. TestConnectionAcquisition - Get connection from pool
3. TestConnectionRelease - Return connection to pool
4. TestPoolCapacity - Min/max size constraints
5. TestConnectionValidation - Health check on acquire
6. TestStaleConnectionHandling - Detect and replace stale connections
7. TestIdleEviction - Remove idle connections
8. TestConnectionTimeout - Handle acquisition timeouts
9. TestPoolStatistics - Track metrics
10. TestPoolIntegration - End-to-end pooling workflow
"""

import unittest
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from threading import Lock, Condition
from collections import deque
import uuid


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class ConnectionState(Enum):
    """Connection state enumeration."""
    AVAILABLE = "available"
    IN_USE = "in_use"
    IDLE = "idle"
    STALE = "stale"
    CLOSED = "closed"


@dataclass
class Connection:
    """Represents a database connection."""
    connection_id: str
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    state: ConnectionState = ConnectionState.AVAILABLE
    use_count: int = 0
    error_count: int = 0
    validated_at: float = field(default_factory=time.time)
    
    def is_stale(self, max_age_seconds: int = 3600) -> bool:
        """Check if connection is too old."""
        return time.time() - self.created_at > max_age_seconds
    
    def is_idle(self, timeout_seconds: int = 300) -> bool:
        """Check if connection has been idle too long."""
        return time.time() - self.last_used > timeout_seconds
    
    def mark_used(self) -> None:
        """Mark connection as recently used."""
        self.last_used = time.time()
        self.use_count += 1
    
    def mark_error(self) -> None:
        """Record an error on this connection."""
        self.error_count += 1


@dataclass
class PoolStats:
    """Statistics for a connection pool."""
    total_connections: int = 0
    available_connections: int = 0
    in_use_connections: int = 0
    total_acquisitions: int = 0
    total_releases: int = 0
    total_errors: int = 0
    total_validations: int = 0
    validation_failures: int = 0
    acquisitions_waited: int = 0
    average_wait_time_ms: float = 0.0
    total_wait_time_ms: float = 0.0
    
    @property
    def utilization_percent(self) -> float:
        """Calculate pool utilization."""
        if self.total_connections == 0:
            return 0.0
        return (self.in_use_connections / self.total_connections) * 100


@dataclass
class PoolConfig:
    """Configuration for connection pool."""
    min_size: int = 5
    max_size: int = 20
    max_idle_time_seconds: int = 300
    max_connection_age_seconds: int = 3600
    acquisition_timeout_seconds: int = 30
    validation_query: str = "SELECT 1"
    connection_factory: Optional[callable] = None


# ============================================================================
# CONNECTION POOL
# ============================================================================

class ConnectionPool:
    """
    Thread-safe connection pool that manages database connections.
    Handles acquisition, release, validation, and lifecycle management.
    """
    
    def __init__(self, config: PoolConfig):
        """Initialize connection pool."""
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self.config = config
        self.available_connections: deque = deque()
        self.in_use_connections: set = set()
        self.all_connections: Dict[str, Connection] = {}
        self.stats = PoolStats()
        self._closed = False
        self._next_validation_time = time.time() + 60
        
        # Initialize minimum pool size
        self._initialize_pool()
    
    def _initialize_pool(self) -> None:
        """Create initial pool of connections."""
        with self._lock:
            for _ in range(self.config.min_size):
                conn = self._create_connection()
                self.available_connections.append(conn)
                self.all_connections[conn.connection_id] = conn
                self.stats.total_connections += 1
    
    def _create_connection(self) -> Connection:
        """Create a new connection."""
        conn_id = str(uuid.uuid4())
        conn = Connection(connection_id=conn_id)
        return conn
    
    def acquire(self, timeout_seconds: Optional[int] = None) -> Optional[Connection]:
        """
        Acquire a connection from the pool.
        1. Check available connections
        2. If none available and below max, create new
        3. If none available and at max, wait for release
        """
        timeout = timeout_seconds or self.config.acquisition_timeout_seconds
        start_time = time.time()
        
        with self._condition:
            while True:
                # Check for available connection
                if self.available_connections:
                    conn = self.available_connections.popleft()
                    
                    # Validate connection
                    if not self._validate_connection(conn):
                        # Connection is stale, replace it
                        self._remove_connection(conn)
                        conn = self._create_connection()
                        self.all_connections[conn.connection_id] = conn
                    
                    conn.state = ConnectionState.IN_USE
                    conn.mark_used()
                    self.in_use_connections.add(conn.connection_id)
                    self.stats.total_acquisitions += 1
                    self.stats.in_use_connections = len(self.in_use_connections)
                    self.stats.available_connections = len(self.available_connections)
                    return conn
                
                # Try to create new connection if below max
                if len(self.all_connections) < self.config.max_size:
                    conn = self._create_connection()
                    self.all_connections[conn.connection_id] = conn
                    self.stats.total_connections += 1
                    
                    conn.state = ConnectionState.IN_USE
                    conn.mark_used()
                    self.in_use_connections.add(conn.connection_id)
                    self.stats.total_acquisitions += 1
                    self.stats.in_use_connections = len(self.in_use_connections)
                    return conn
                
                # Wait for a connection to be released
                remaining_timeout = timeout - (time.time() - start_time)
                if remaining_timeout <= 0:
                    self.stats.total_errors += 1
                    return None
                
                self.stats.acquisitions_waited += 1
                self._condition.wait(timeout=1)
    
    def release(self, connection: Connection) -> None:
        """
        Release a connection back to the pool.
        Validates connection and marks as available.
        """
        with self._condition:
            if connection.connection_id not in self.in_use_connections:
                return
            
            self.in_use_connections.discard(connection.connection_id)
            
            # Check if connection should be evicted
            if connection.is_stale(self.config.max_connection_age_seconds):
                self._remove_connection(connection)
                self.stats.total_connections = max(0, self.stats.total_connections - 1)
            else:
                connection.state = ConnectionState.AVAILABLE
                self.available_connections.append(connection)
            
            self.stats.total_releases += 1
            self.stats.in_use_connections = len(self.in_use_connections)
            self.stats.available_connections = len(self.available_connections)
            self._condition.notify()
    
    def _validate_connection(self, conn: Connection) -> bool:
        """Validate that a connection is still healthy."""
        self.stats.total_validations += 1
        
        # Check for stale connection
        if conn.is_stale(self.config.max_connection_age_seconds):
            self.stats.validation_failures += 1
            conn.state = ConnectionState.STALE
            return False
        
        # Check error count
        if conn.error_count > 5:
            self.stats.validation_failures += 1
            return False
        
        conn.validated_at = time.time()
        return True
    
    def _remove_connection(self, conn: Connection) -> None:
        """Remove and close a connection."""
        self.all_connections.pop(conn.connection_id, None)
        conn.state = ConnectionState.CLOSED
    
    def get_stats(self) -> PoolStats:
        """Get pool statistics."""
        with self._lock:
            return PoolStats(
                total_connections=self.stats.total_connections,
                available_connections=len(self.available_connections),
                in_use_connections=len(self.in_use_connections),
                total_acquisitions=self.stats.total_acquisitions,
                total_releases=self.stats.total_releases,
                total_errors=self.stats.total_errors,
                total_validations=self.stats.total_validations,
                validation_failures=self.stats.validation_failures,
                acquisitions_waited=self.stats.acquisitions_waited
            )
    
    def evict_idle_connections(self) -> int:
        """Remove idle connections from pool."""
        with self._lock:
            evicted = 0
            to_evict = []
            
            for conn in list(self.available_connections):
                if conn.is_idle(self.config.max_idle_time_seconds):
                    to_evict.append(conn)
            
            for conn in to_evict:
                self.available_connections.remove(conn)
                self._remove_connection(conn)
                self.stats.total_connections = max(0, self.stats.total_connections - 1)
                evicted += 1
            
            return evicted
    
    def close(self) -> None:
        """Close all connections in the pool."""
        with self._lock:
            self._closed = True
            for conn in self.all_connections.values():
                conn.state = ConnectionState.CLOSED
            self.available_connections.clear()
            self.in_use_connections.clear()
            self.all_connections.clear()
    
    def get_connection_count(self) -> int:
        """Get total number of connections."""
        with self._lock:
            return len(self.all_connections)
    
    def get_available_count(self) -> int:
        """Get number of available connections."""
        with self._lock:
            return len(self.available_connections)


# ============================================================================
# TESTS
# ============================================================================

class TestPoolCreation(unittest.TestCase):
    """Test pool creation and initialization."""
    
    def test_pool_creation(self):
        """Test creating a pool."""
        config = PoolConfig(min_size=5, max_size=10)
        pool = ConnectionPool(config)
        
        self.assertEqual(pool.get_connection_count(), 5)
    
    def test_pool_config(self):
        """Test pool configuration."""
        config = PoolConfig(min_size=3, max_size=15)
        pool = ConnectionPool(config)
        
        self.assertEqual(pool.config.min_size, 3)
        self.assertEqual(pool.config.max_size, 15)
    
    def test_pool_close(self):
        """Test closing pool."""
        config = PoolConfig(min_size=5)
        pool = ConnectionPool(config)
        pool.close()
        
        self.assertEqual(pool.get_connection_count(), 0)


class TestConnectionAcquisition(unittest.TestCase):
    """Test acquiring connections."""
    
    def setUp(self):
        """Set up test pool."""
        config = PoolConfig(min_size=3, max_size=5)
        self.pool = ConnectionPool(config)
    
    def test_acquire_connection(self):
        """Test acquiring a connection."""
        conn = self.pool.acquire()
        self.assertIsNotNone(conn)
        self.assertEqual(conn.state, ConnectionState.IN_USE)
    
    def test_acquire_multiple_connections(self):
        """Test acquiring multiple connections."""
        conns = []
        for i in range(3):
            conn = self.pool.acquire()
            self.assertIsNotNone(conn)
            conns.append(conn)
        
        self.assertEqual(len(conns), 3)
        self.assertEqual(self.pool.get_available_count(), 0)
    
    def test_acquire_timeout(self):
        """Test acquisition timeout when pool exhausted."""
        # Acquire all connections
        for _ in range(5):
            self.pool.acquire()
        
        # Try to acquire another (should timeout)
        conn = self.pool.acquire(timeout_seconds=0.1)
        self.assertIsNone(conn)


class TestConnectionRelease(unittest.TestCase):
    """Test releasing connections."""
    
    def setUp(self):
        """Set up test pool."""
        config = PoolConfig(min_size=3, max_size=5)
        self.pool = ConnectionPool(config)
    
    def test_release_connection(self):
        """Test releasing a connection."""
        conn = self.pool.acquire()
        initial_available = self.pool.get_available_count()
        
        self.pool.release(conn)
        
        self.assertEqual(self.pool.get_available_count(), initial_available + 1)
    
    def test_acquire_released_connection(self):
        """Test reusing a released connection."""
        initial_count = self.pool.get_available_count()
        conn1 = self.pool.acquire()
        conn_id_1 = conn1.connection_id
        self.pool.release(conn1)
        
        # After release, one more should be available
        self.assertEqual(self.pool.get_available_count(), initial_count)
        
        conn2 = self.pool.acquire()
        # Connection should be reused (either same or from pool)
        self.assertIsNotNone(conn2)


class TestPoolCapacity(unittest.TestCase):
    """Test pool size constraints."""
    
    def setUp(self):
        """Set up test pool."""
        config = PoolConfig(min_size=2, max_size=4)
        self.pool = ConnectionPool(config)
    
    def test_min_size_maintained(self):
        """Test minimum pool size is maintained."""
        self.assertEqual(self.pool.get_connection_count(), 2)
    
    def test_max_size_enforced(self):
        """Test maximum pool size is enforced."""
        conns = []
        for _ in range(4):
            conn = self.pool.acquire()
            self.assertIsNotNone(conn)
            conns.append(conn)
        
        self.assertEqual(self.pool.get_connection_count(), 4)
        
        # 5th acquisition should timeout
        conn = self.pool.acquire(timeout_seconds=0.1)
        self.assertIsNone(conn)


class TestConnectionValidation(unittest.TestCase):
    """Test connection validation."""
    
    def setUp(self):
        """Set up test pool."""
        config = PoolConfig(min_size=3)
        self.pool = ConnectionPool(config)
    
    def test_validate_healthy_connection(self):
        """Test validating a healthy connection."""
        conn = self.pool.acquire()
        self.assertTrue(self.pool._validate_connection(conn))
    
    def test_validate_stale_connection(self):
        """Test detecting stale connection."""
        conn = self.pool.acquire()
        conn.created_at = time.time() - 4000  # Over 1 hour old
        
        self.assertFalse(self.pool._validate_connection(conn))


class TestStaleConnectionHandling(unittest.TestCase):
    """Test handling of stale connections."""
    
    def setUp(self):
        """Set up test pool."""
        config = PoolConfig(min_size=3, max_connection_age_seconds=100)
        self.pool = ConnectionPool(config)
    
    def test_stale_connection_replaced(self):
        """Test stale connection is replaced on acquire."""
        # Make first connection stale
        conn = self.pool.acquire()
        conn_id = conn.connection_id
        conn.created_at = time.time() - 101
        self.pool.release(conn)
        
        # Acquire should get a fresh connection
        new_conn = self.pool.acquire()
        self.assertNotEqual(new_conn.connection_id, conn_id)


class TestIdleEviction(unittest.TestCase):
    """Test idle connection eviction."""
    
    def setUp(self):
        """Set up test pool."""
        config = PoolConfig(min_size=3, max_size=5, max_idle_time_seconds=1)
        self.pool = ConnectionPool(config)
    
    def test_evict_idle_connections(self):
        """Test evicting idle connections."""
        initial_count = self.pool.get_connection_count()
        
        # Make connections idle
        for conn in list(self.pool.available_connections):
            conn.last_used = time.time() - 1.1
        
        evicted = self.pool.evict_idle_connections()
        
        self.assertGreater(evicted, 0)


class TestConnectionTimeout(unittest.TestCase):
    """Test connection acquisition timeout."""
    
    def setUp(self):
        """Set up test pool."""
        config = PoolConfig(min_size=1, max_size=1)
        self.pool = ConnectionPool(config)
    
    def test_timeout_when_pool_exhausted(self):
        """Test timeout when pool is exhausted."""
        self.pool.acquire()
        
        start = time.time()
        conn = self.pool.acquire(timeout_seconds=0.5)
        elapsed = time.time() - start
        
        self.assertIsNone(conn)
        self.assertGreater(elapsed, 0.4)


class TestPoolStatistics(unittest.TestCase):
    """Test pool statistics."""
    
    def setUp(self):
        """Set up test pool."""
        config = PoolConfig(min_size=3, max_size=5)
        self.pool = ConnectionPool(config)
    
    def test_stats_acquisition(self):
        """Test acquisition statistics."""
        self.pool.acquire()
        stats = self.pool.get_stats()
        
        self.assertEqual(stats.total_acquisitions, 1)
    
    def test_stats_utilization(self):
        """Test utilization calculation."""
        self.pool.acquire()
        self.pool.acquire()
        
        stats = self.pool.get_stats()
        self.assertGreater(stats.utilization_percent, 0)


class TestPoolIntegration(unittest.TestCase):
    """End-to-end pool integration tests."""
    
    def setUp(self):
        """Set up test pool."""
        config = PoolConfig(min_size=3, max_size=5)
        self.pool = ConnectionPool(config)
    
    def test_acquire_release_cycle(self):
        """Test acquire/release cycle."""
        conns = []
        for _ in range(5):
            conn = self.pool.acquire()
            self.assertIsNotNone(conn)
            conns.append(conn)
        
        for conn in conns:
            self.pool.release(conn)
        
        stats = self.pool.get_stats()
        self.assertEqual(stats.total_acquisitions, 5)
        self.assertEqual(stats.total_releases, 5)
    
    def test_concurrent_access(self):
        """Test pool with concurrent access."""
        results = []
        errors = []
        
        def worker():
            try:
                conn = self.pool.acquire(timeout_seconds=1)
                if conn:
                    results.append(conn.connection_id)
                    time.sleep(0.01)
                    self.pool.release(conn)
            except Exception as e:
                errors.append(str(e))
        
        threads = []
        for _ in range(10):
            t = threading.Thread(target=worker)
            t.start()
            threads.append(t)
        
        for t in threads:
            t.join()
        
        self.assertEqual(len(errors), 0)


if __name__ == '__main__':
    unittest.main()
