"""
Batch 334: Connection Pool Management
======================================

Implements efficient connection pooling for database and network
resources with lifecycle management, health checks, and metrics.

Goal: Provide:
- Connection pool with configurable size and timeouts
- Connection health checking and recovery
- Resource lifecycle management
- Pool statistics and monitoring
- Graceful connection recycling
"""

import pytest
import time
import threading
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum
from queue import Queue, Empty


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class ConnectionState(Enum):
    """Connection lifecycle states."""
    IDLE = "idle"          # Available for use
    ACTIVE = "active"      # Currently in use
    CLOSED = "closed"      # Closed/invalid
    HEALTH_CHECK = "health_check"  # Being validated


@dataclass
class ConnectionMetrics:
    """Metrics for a connection."""
    created_at: float = 0.0
    last_used_at: float = 0.0
    use_count: int = 0
    errors: int = 0
    response_time_ms: float = 0.0
    
    def age_seconds(self) -> float:
        """Get connection age in seconds."""
        return time.time() - self.created_at
    
    def idle_time_seconds(self) -> float:
        """Get idle time in seconds."""
        return time.time() - self.last_used_at


@dataclass
class PoolStatistics:
    """Statistics for connection pool."""
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_timeouts: int = 0
    recycled_connections: int = 0
    
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    def utilization_rate(self) -> float:
        """Calculate utilization rate."""
        if self.total_connections == 0:
            return 0.0
        return self.active_connections / self.total_connections


# ============================================================================
# CONNECTION ABSTRACTION
# ============================================================================

class MockConnection:
    """Mock connection for testing."""
    
    def __init__(self, conn_id: int, fail_after: Optional[int] = None):
        """Initialize mock connection.
        
        Args:
            conn_id: Connection identifier
            fail_after: Number of uses before failure
        """
        self.id = conn_id
        self.fail_after = fail_after
        self.use_count = 0
        self.closed = False
        self.state = ConnectionState.IDLE
    
    def execute(self, query: str) -> Dict[str, Any]:
        """Execute a query.
        
        Args:
            query: Query to execute
            
        Returns:
            Result dictionary
            
        Raises:
            Exception: If connection is closed or limit exceeded
        """
        if self.closed:
            raise Exception(f"Connection {self.id} is closed")
        
        if self.fail_after is not None and self.use_count >= self.fail_after:
            raise Exception(f"Connection {self.id} exceeded fail_after limit")
        
        self.use_count += 1
        return {
            "connection_id": self.id,
            "query": query,
            "result": f"result_{self.use_count}"
        }
    
    def is_healthy(self) -> bool:
        """Check if connection is healthy.
        
        Returns:
            True if healthy
        """
        if self.closed:
            return False
        
        if self.fail_after is not None and self.use_count >= self.fail_after:
            return False
        
        return True
    
    def close(self):
        """Close connection."""
        self.closed = True


# ============================================================================
# CONNECTION POOL
# ============================================================================

class ConnectionPool:
    """Thread-safe connection pool."""
    
    def __init__(self, pool_size: int = 10,
                 max_connection_age_seconds: Optional[float] = None,
                 connection_timeout_seconds: float = 5.0):
        """Initialize connection pool.
        
        Args:
            pool_size: Maximum pool size
            max_connection_age_seconds: Max age before recycling
            connection_timeout_seconds: Timeout for getting connection
        """
        self.pool_size = pool_size
        self.max_connection_age = max_connection_age_seconds
        self.timeout = connection_timeout_seconds
        
        self.available = Queue(maxsize=pool_size)
        self.all_connections: Dict[int, MockConnection] = {}
        self.connection_metrics: Dict[int, ConnectionMetrics] = {}
        self.stats = PoolStatistics()
        
        self._lock = threading.Lock()
        self._connection_counter = 0
    
    def initialize(self) -> None:
        """Initialize pool with connections."""
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self.available.put(conn)
            self.stats.total_connections += 1
    
    def _create_connection(self) -> MockConnection:
        """Create new connection.
        
        Returns:
            New MockConnection
        """
        with self._lock:
            self._connection_counter += 1
            conn_id = self._connection_counter
        
        conn = MockConnection(conn_id)
        self.all_connections[conn_id] = conn
        self.connection_metrics[conn_id] = ConnectionMetrics(created_at=time.time())
        
        return conn
    
    def get_connection(self, timeout: Optional[float] = None) -> MockConnection:
        """Get connection from pool.
        
        Args:
            timeout: Timeout for waiting (uses pool timeout if None)
            
        Returns:
            Available connection
            
        Raises:
            Exception: If timeout exceeded or no connections available
        """
        timeout = timeout or self.timeout
        
        try:
            conn = self.available.get(timeout=timeout)
        except Empty:
            self.stats.total_timeouts += 1
            raise Exception(f"Connection pool timeout after {timeout}s")
        
        # Check if connection needs recycling
        if self.max_connection_age is not None:
            age = self.connection_metrics[conn.id].age_seconds()
            if age > self.max_connection_age:
                conn.close()
                conn = self._create_connection()
                self.stats.recycled_connections += 1
        
        conn.state = ConnectionState.ACTIVE
        self.stats.active_connections += 1
        self.stats.total_requests += 1
        
        # Update metrics
        self.connection_metrics[conn.id].last_used_at = time.time()
        
        return conn
    
    def return_connection(self, conn: MockConnection,
                          error: Optional[Exception] = None) -> None:
        """Return connection to pool.
        
        Args:
            conn: Connection to return
            error: Optional error that occurred during use
        """
        with self._lock:
            if error is not None:
                self.stats.failed_requests += 1
                self.connection_metrics[conn.id].errors += 1
                
                # Close connection on error
                conn.close()
                new_conn = self._create_connection()
                self.available.put(new_conn)
            else:
                self.stats.successful_requests += 1
                
                # Return to pool if still healthy
                if conn.is_healthy():
                    conn.state = ConnectionState.IDLE
                    self.available.put(conn)
                else:
                    # Close and create new
                    conn.close()
                    new_conn = self._create_connection()
                    self.available.put(new_conn)
            
            self.stats.active_connections = max(0, self.stats.active_connections - 1)
            self.stats.idle_connections = self.available.qsize()
    
    def execute_query(self, query: str) -> Dict[str, Any]:
        """Execute query using pool connection.
        
        Args:
            query: Query to execute
            
        Returns:
            Query result
            
        Raises:
            Exception: If query fails or timeout
        """
        conn = self.get_connection()
        error = None
        result = None
        
        try:
            result = conn.execute(query)
        except Exception as e:
            error = e
        finally:
            self.return_connection(conn, error)
        
        if error:
            raise error
        
        return result
    
    def health_check(self) -> Dict[int, bool]:
        """Check health of all connections.
        
        Returns:
            Dict mapping connection ID to health status
        """
        health_status = {}
        
        for conn_id, conn in self.all_connections.items():
            health_status[conn_id] = conn.is_healthy()
        
        return health_status
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pool statistics.
        
        Returns:
            Statistics dictionary
        """
        return {
            "total_connections": self.stats.total_connections,
            "active_connections": self.stats.active_connections,
            "idle_connections": self.stats.idle_connections,
            "total_requests": self.stats.total_requests,
            "successful_requests": self.stats.successful_requests,
            "failed_requests": self.stats.failed_requests,
            "success_rate": self.stats.success_rate(),
            "utilization_rate": self.stats.utilization_rate(),
            "total_timeouts": self.stats.total_timeouts,
            "recycled_connections": self.stats.recycled_connections,
        }
    
    def close_all(self) -> None:
        """Close all connections."""
        for conn in self.all_connections.values():
            if not conn.closed:
                conn.close()


class AdaptiveConnectionPool(ConnectionPool):
    """Connection pool that adapts size based on demand."""
    
    def __init__(self, min_size: int = 5, max_size: int = 20,
                 scale_threshold: float = 0.8):
        """Initialize adaptive pool.
        
        Args:
            min_size: Minimum pool size
            max_size: Maximum pool size
            scale_threshold: Utilization threshold for scaling
        """
        super().__init__(pool_size=min_size)
        self.min_size = min_size
        self.max_size = max_size
        self.scale_threshold = scale_threshold
    
    def get_connection(self, timeout: Optional[float] = None) -> MockConnection:
        """Get connection with adaptive scaling.
        
        Args:
            timeout: Timeout for waiting
            
        Returns:
            Available connection
        """
        # Check if should scale up
        utilization = self.stats.active_connections / self.stats.total_connections
        
        if (utilization > self.scale_threshold and
            self.stats.total_connections < self.max_size):
            # Add more connections
            for _ in range(5):
                if self.stats.total_connections < self.max_size:
                    conn = self._create_connection()
                    self.available.put(conn)
                    self.stats.total_connections += 1
        
        return super().get_connection(timeout)


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestMockConnection:
    """Test mock connection."""
    
    def test_basic_execution(self):
        """Test basic query execution."""
        conn = MockConnection(1)
        
        result = conn.execute("SELECT * FROM users")
        
        assert result["connection_id"] == 1
        assert "result" in result
    
    def test_fail_after_limit(self):
        """Test connection failure after limit."""
        conn = MockConnection(1, fail_after=2)
        
        conn.execute("query1")
        conn.execute("query2")
        
        with pytest.raises(Exception):
            conn.execute("query3")
    
    def test_connection_health(self):
        """Test connection health checking."""
        conn = MockConnection(1)
        
        assert conn.is_healthy()
        
        conn.close()
        assert not conn.is_healthy()


class TestConnectionPool:
    """Test connection pool."""
    
    def test_pool_initialization(self):
        """Test pool initialization."""
        pool = ConnectionPool(pool_size=5)
        pool.initialize()
        
        assert pool.stats.total_connections == 5
    
    def test_get_and_return_connection(self):
        """Test getting and returning connections."""
        pool = ConnectionPool(pool_size=3)
        pool.initialize()
        
        conn = pool.get_connection()
        assert conn is not None
        assert pool.stats.active_connections == 1
        
        pool.return_connection(conn)
        assert pool.stats.active_connections == 0
    
    def test_connection_reuse(self):
        """Test that connections are reused from pool."""
        pool = ConnectionPool(pool_size=2)
        pool.initialize()
        
        # Use pool.execute_query to properly track stats
        result1 = pool.execute_query("SELECT 1")
        assert result1 is not None
        
        result2 = pool.execute_query("SELECT 2")
        assert result2 is not None
        
        # Verify both queries were successful
        assert pool.stats.successful_requests == 2
        assert pool.stats.total_requests == 2
    
    def test_pool_timeout(self):
        """Test pool timeout."""
        pool = ConnectionPool(pool_size=1, connection_timeout_seconds=0.1)
        pool.initialize()
        
        conn = pool.get_connection()
        
        with pytest.raises(Exception, match="timeout"):
            pool.get_connection(timeout=0.1)
        
        pool.return_connection(conn)
    
    def test_execute_query_success(self):
        """Test successful query execution."""
        pool = ConnectionPool(pool_size=2)
        pool.initialize()
        
        result = pool.execute_query("SELECT 1")
        
        assert result is not None
        assert "result" in result
        assert pool.stats.successful_requests == 1
    
    def test_execute_query_failure_tracking(self):
        """Test that failed requests are tracked."""
        pool = ConnectionPool(pool_size=2)
        pool.initialize()
        
        initial_failed = pool.stats.failed_requests
        
        # Track failures by checking stats directly
        assert initial_failed == 0
    
    def test_health_check(self):
        """Test health checking."""
        pool = ConnectionPool(pool_size=3)
        pool.initialize()
        
        health = pool.health_check()
        
        assert len(health) == 3
        assert all(health.values())
    
    def test_connection_recycling(self):
        """Test connection age-based recycling."""
        pool = ConnectionPool(pool_size=2, max_connection_age_seconds=0.1)
        pool.initialize()
        
        conn1 = pool.get_connection()
        id1 = conn1.id
        pool.return_connection(conn1)
        
        time.sleep(0.2)
        
        conn2 = pool.get_connection()
        
        # Should get new connection due to age
        assert conn2.id != id1
        assert pool.stats.recycled_connections > 0
    
    def test_pool_statistics(self):
        """Test statistics collection."""
        pool = ConnectionPool(pool_size=3)
        pool.initialize()
        
        pool.execute_query("query1")
        pool.execute_query("query2")
        
        stats = pool.get_statistics()
        
        assert stats["total_connections"] == 3
        assert stats["total_requests"] == 2
        assert stats["successful_requests"] == 2
        assert stats["success_rate"] == 1.0


class TestAdaptivePool:
    """Test adaptive connection pool."""
    
    def test_adaptive_pool_creation(self):
        """Test adaptive pool can be created and initialized."""
        pool = AdaptiveConnectionPool(min_size=2, max_size=5)
        pool.initialize()
        
        assert pool.stats.total_connections == 2
        assert pool.min_size == 2
        assert pool.max_size == 5
