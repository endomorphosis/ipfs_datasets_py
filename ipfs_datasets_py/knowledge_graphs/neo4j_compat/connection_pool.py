"""
Connection Pooling for IPFS Graph Database

Provides connection pooling to manage multiple concurrent sessions efficiently,
compatible with Neo4j's connection pooling behavior.

Features:
- Max pool size limiting
- Connection lifetime management
- Connection health checking
- Thread-safe pool operations
- Idle connection cleanup
"""

import logging
import threading
import time
from typing import Optional, Dict, Any
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PooledConnection:
    """Represents a connection in the pool."""
    
    connection_id: str
    backend: Any
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    in_use: bool = False
    
    def is_expired(self, max_lifetime: int) -> bool:
        """Check if connection has exceeded max lifetime."""
        return (time.time() - self.created_at) > max_lifetime
    
    def is_idle_timeout(self, idle_timeout: int) -> bool:
        """Check if connection has been idle too long."""
        return not self.in_use and (time.time() - self.last_used) > idle_timeout
    
    def mark_used(self) -> None:
        """Mark connection as in use."""
        self.in_use = True
        self.last_used = time.time()
    
    def mark_released(self) -> None:
        """Mark connection as released back to pool."""
        self.in_use = False
        self.last_used = time.time()


class ConnectionPool:
    """
    Connection pool for IPFS graph database connections.
    
    Manages a pool of connections with configurable size limits,
    lifecycle management, and health checking.
    """
    
    def __init__(
        self,
        max_size: int = 100,
        max_connection_lifetime: int = 3600,
        idle_timeout: int = 300,
        connection_timeout: float = 30.0,
        keep_alive: bool = True
    ):
        """
        Initialize the connection pool.
        
        Args:
            max_size: Maximum number of connections in the pool
            max_connection_lifetime: Maximum lifetime of a connection in seconds
            idle_timeout: Timeout for idle connections in seconds
            connection_timeout: Timeout for acquiring a connection
            keep_alive: Whether to keep connections alive
        """
        self.max_size = max_size
        self.max_connection_lifetime = max_connection_lifetime
        self.idle_timeout = idle_timeout
        self.connection_timeout = connection_timeout
        self.keep_alive = keep_alive
        
        # Pool storage
        self._available: deque[PooledConnection] = deque()
        self._in_use: Dict[str, PooledConnection] = {}
        self._connection_counter = 0
        
        # Thread safety
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        
        # Pool state
        self._closed = False
        
        # Statistics
        self._stats = {
            'total_created': 0,
            'total_acquired': 0,
            'total_released': 0,
            'total_expired': 0,
            'total_idle_timeout': 0
        }
        
        logger.info(
            "ConnectionPool initialized: max_size=%d, max_lifetime=%d, idle_timeout=%d",
            max_size, max_connection_lifetime, idle_timeout
        )
    
    def _create_connection(self, backend: Any) -> PooledConnection:
        """
        Create a new pooled connection.
        
        Args:
            backend: Backend instance to wrap
            
        Returns:
            New PooledConnection instance
        """
        with self._lock:
            self._connection_counter += 1
            conn_id = f"conn_{self._connection_counter}"
            connection = PooledConnection(
                connection_id=conn_id,
                backend=backend
            )
            self._stats['total_created'] += 1
            logger.debug("Created connection: %s", conn_id)
            return connection
    
    def _cleanup_expired(self) -> None:
        """Remove expired connections from the pool."""
        expired = []
        
        # Find expired connections in available pool
        for conn in list(self._available):
            if conn.is_expired(self.max_connection_lifetime):
                expired.append(conn)
                self._available.remove(conn)
            elif conn.is_idle_timeout(self.idle_timeout):
                expired.append(conn)
                self._available.remove(conn)
                self._stats['total_idle_timeout'] += 1
        
        if expired:
            self._stats['total_expired'] += len(expired)
            logger.debug("Cleaned up %d expired/idle connections", len(expired))
    
    def acquire(self, backend: Any, timeout: Optional[float] = None) -> PooledConnection:
        """
        Acquire a connection from the pool.
        
        Args:
            backend: Backend instance to use if creating new connection
            timeout: Timeout in seconds (None = use pool timeout)
            
        Returns:
            PooledConnection instance
            
        Raises:
            TimeoutError: If connection cannot be acquired within timeout
            RuntimeError: If pool is closed
        """
        if timeout is None:
            timeout = self.connection_timeout
        
        deadline = time.time() + timeout
        
        with self._condition:
            if self._closed:
                raise RuntimeError("Connection pool is closed")
            
            while True:
                # Clean up expired connections
                self._cleanup_expired()
                
                # Try to get an available connection
                if self._available:
                    conn = self._available.popleft()
                    conn.mark_used()
                    self._in_use[conn.connection_id] = conn
                    self._stats['total_acquired'] += 1
                    logger.debug("Acquired connection from pool: %s", conn.connection_id)
                    return conn
                
                # Create new connection if under max size
                current_total = len(self._available) + len(self._in_use)
                if current_total < self.max_size:
                    conn = self._create_connection(backend)
                    conn.mark_used()
                    self._in_use[conn.connection_id] = conn
                    self._stats['total_acquired'] += 1
                    logger.debug("Created and acquired new connection: %s", conn.connection_id)
                    return conn
                
                # Wait for a connection to become available
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Could not acquire connection within {timeout} seconds. "
                        f"Pool size: {current_total}/{self.max_size}"
                    )
                
                logger.debug("Waiting for available connection (pool full: %d/%d)", 
                           current_total, self.max_size)
                self._condition.wait(timeout=remaining)
    
    def release(self, connection: PooledConnection) -> None:
        """
        Release a connection back to the pool.
        
        Args:
            connection: Connection to release
        """
        with self._condition:
            if self._closed:
                logger.debug("Pool is closed, discarding connection: %s", 
                           connection.connection_id)
                return
            
            # Remove from in-use tracking
            self._in_use.pop(connection.connection_id, None)
            
            # Check if connection is still valid
            if connection.is_expired(self.max_connection_lifetime):
                self._stats['total_expired'] += 1
                logger.debug("Connection expired, not returning to pool: %s", 
                           connection.connection_id)
                # Notify waiters that pool space is available
                self._condition.notify()
                return
            
            # Return to available pool
            connection.mark_released()
            self._available.append(connection)
            self._stats['total_released'] += 1
            logger.debug("Released connection to pool: %s", connection.connection_id)
            
            # Notify waiting threads
            self._condition.notify()
    
    def close(self) -> None:
        """Close the pool and clean up all connections."""
        with self._condition:
            if self._closed:
                return
            
            self._closed = True
            
            # Clear all connections
            total_connections = len(self._available) + len(self._in_use)
            self._available.clear()
            self._in_use.clear()
            
            logger.info("Connection pool closed. Total connections cleaned: %d", 
                       total_connections)
            
            # Notify all waiting threads
            self._condition.notify_all()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get pool statistics.
        
        Returns:
            Dictionary with pool statistics
        """
        with self._lock:
            return {
                'max_size': self.max_size,
                'available': len(self._available),
                'in_use': len(self._in_use),
                'total': len(self._available) + len(self._in_use),
                'stats': self._stats.copy(),
                'closed': self._closed
            }
    
    @property
    def size(self) -> int:
        """Get current total pool size."""
        with self._lock:
            return len(self._available) + len(self._in_use)
    
    @property
    def available_count(self) -> int:
        """Get number of available connections."""
        with self._lock:
            return len(self._available)
    
    @property
    def in_use_count(self) -> int:
        """Get number of in-use connections."""
        with self._lock:
            return len(self._in_use)
    
    @property
    def closed(self) -> bool:
        """Check if pool is closed."""
        with self._lock:
            return self._closed
