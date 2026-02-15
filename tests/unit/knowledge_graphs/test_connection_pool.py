"""
Unit tests for Connection Pooling

Tests the connection pool implementation including:
- Connection acquisition and release
- Pool size limiting
- Connection lifetime management
- Idle timeout handling
- Thread safety
- Statistics tracking
"""

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

import time
import threading
from ipfs_datasets_py.knowledge_graphs.neo4j_compat.connection_pool import (
    ConnectionPool, PooledConnection
)


class MockBackend:
    """Mock backend for testing."""
    def __init__(self, name="mock"):
        self.name = name


class TestConnectionPool:
    """Test connection pool basic functionality."""
    
    def test_pool_creation(self):
        """Test pool can be created with config."""
        pool = ConnectionPool(
            max_size=10,
            max_connection_lifetime=3600,
            idle_timeout=300
        )
        assert pool is not None
        assert pool.max_size == 10
        assert pool.size == 0
        assert not pool.closed
    
    def test_acquire_connection(self):
        """Test connection can be acquired."""
        pool = ConnectionPool(max_size=5)
        backend = MockBackend("test1")
        
        conn = pool.acquire(backend)
        assert conn is not None
        assert conn.backend == backend
        assert conn.in_use
        assert pool.in_use_count == 1
        assert pool.available_count == 0
    
    def test_release_connection(self):
        """Test connection can be released."""
        pool = ConnectionPool(max_size=5)
        backend = MockBackend("test2")
        
        conn = pool.acquire(backend)
        pool.release(conn)
        
        assert not conn.in_use
        assert pool.in_use_count == 0
        assert pool.available_count == 1
    
    def test_connection_reuse(self):
        """Test connections are reused from pool."""
        pool = ConnectionPool(max_size=5)
        backend = MockBackend("test3")
        
        # Acquire and release
        conn1 = pool.acquire(backend)
        conn1_id = conn1.connection_id
        pool.release(conn1)
        
        # Acquire again - should get same connection
        conn2 = pool.acquire(backend)
        assert conn2.connection_id == conn1_id
    
    def test_pool_max_size(self):
        """Test pool respects max size limit."""
        pool = ConnectionPool(max_size=2)
        backend = MockBackend("test4")
        
        conn1 = pool.acquire(backend)
        conn2 = pool.acquire(backend)
        
        assert pool.size == 2
        
        # Try to acquire third connection with short timeout
        try:
            conn3 = pool.acquire(backend, timeout=0.1)
            assert False, "Should have timed out"
        except TimeoutError:
            pass  # Expected
    
    def test_pool_stats(self):
        """Test pool statistics tracking."""
        pool = ConnectionPool(max_size=5)
        backend = MockBackend("test5")
        
        conn1 = pool.acquire(backend)
        conn2 = pool.acquire(backend)
        pool.release(conn1)
        
        stats = pool.get_stats()
        assert stats['max_size'] == 5
        assert stats['in_use'] == 1
        assert stats['available'] == 1
        assert stats['total'] == 2
        assert stats['stats']['total_created'] == 2
        assert stats['stats']['total_acquired'] == 2
        assert stats['stats']['total_released'] == 1
    
    def test_pool_close(self):
        """Test pool can be closed."""
        pool = ConnectionPool(max_size=5)
        backend = MockBackend("test6")
        
        conn = pool.acquire(backend)
        pool.close()
        
        assert pool.closed
        assert pool.size == 0
        
        # Cannot acquire after close
        try:
            pool.acquire(backend)
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass  # Expected


class TestConnectionLifetime:
    """Test connection lifetime and expiration."""
    
    def test_connection_expiration(self):
        """Test connections expire after max lifetime."""
        pool = ConnectionPool(
            max_size=5,
            max_connection_lifetime=1  # 1 second
        )
        backend = MockBackend("expire1")
        
        conn = pool.acquire(backend)
        pool.release(conn)
        
        # Wait for expiration
        time.sleep(1.1)
        
        # Acquire again - should create new connection
        conn2 = pool.acquire(backend)
        assert conn2.connection_id != conn.connection_id
    
    def test_idle_timeout(self):
        """Test idle connections are cleaned up."""
        pool = ConnectionPool(
            max_size=5,
            idle_timeout=1  # 1 second
        )
        backend = MockBackend("idle1")
        
        conn = pool.acquire(backend)
        pool.release(conn)
        
        assert pool.available_count == 1
        
        # Wait for idle timeout
        time.sleep(1.1)
        
        # Trigger cleanup by acquiring new connection
        conn2 = pool.acquire(backend)
        
        # Old connection should be cleaned, new one created
        assert pool.size == 1


class TestPoolThreadSafety:
    """Test pool thread safety."""
    
    def test_concurrent_acquire(self):
        """Test concurrent connection acquisition."""
        pool = ConnectionPool(max_size=10)
        backend = MockBackend("thread1")
        acquired_conns = []
        errors = []
        
        def acquire_connection():
            try:
                conn = pool.acquire(backend)
                acquired_conns.append(conn)
                time.sleep(0.1)  # Hold connection briefly
                pool.release(conn)
            except Exception as e:
                errors.append(e)
        
        # Start 10 threads
        threads = [threading.Thread(target=acquire_connection) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(acquired_conns) == 10
        # All connections should have been released
        assert pool.in_use_count == 0
    
    def test_pool_full_blocking(self):
        """Test threads block when pool is full."""
        pool = ConnectionPool(max_size=2)
        backend = MockBackend("thread2")
        results = []
        
        def hold_connection(duration):
            conn = pool.acquire(backend)
            results.append(('acquired', conn.connection_id))
            time.sleep(duration)
            pool.release(conn)
            results.append(('released', conn.connection_id))
        
        # Start 3 threads (pool size 2)
        thread1 = threading.Thread(target=hold_connection, args=(0.2,))
        thread2 = threading.Thread(target=hold_connection, args=(0.2,))
        thread3 = threading.Thread(target=hold_connection, args=(0.1,))
        
        thread1.start()
        thread2.start()
        time.sleep(0.05)  # Let first two acquire
        thread3.start()
        
        thread1.join()
        thread2.join()
        thread3.join()
        
        # Should have 3 acquire and 3 release events
        acquired = [r for r in results if r[0] == 'acquired']
        released = [r for r in results if r[0] == 'released']
        assert len(acquired) == 3
        assert len(released) == 3


class TestPooledConnection:
    """Test PooledConnection class."""
    
    def test_pooled_connection_creation(self):
        """Test PooledConnection can be created."""
        backend = MockBackend("conn1")
        conn = PooledConnection(
            connection_id="test_conn",
            backend=backend
        )
        assert conn.connection_id == "test_conn"
        assert conn.backend == backend
        assert not conn.in_use
    
    def test_connection_use_tracking(self):
        """Test connection use is tracked."""
        backend = MockBackend("conn2")
        conn = PooledConnection(
            connection_id="test_conn",
            backend=backend
        )
        
        conn.mark_used()
        assert conn.in_use
        
        conn.mark_released()
        assert not conn.in_use
    
    def test_connection_expiration_check(self):
        """Test connection expiration checking."""
        backend = MockBackend("conn3")
        conn = PooledConnection(
            connection_id="test_conn",
            backend=backend
        )
        
        assert not conn.is_expired(max_lifetime=10)
        
        # Simulate old connection
        conn.created_at = time.time() - 20
        assert conn.is_expired(max_lifetime=10)


if __name__ == "__main__" and HAVE_PYTEST:
    pytest.main([__file__, "-v"])
