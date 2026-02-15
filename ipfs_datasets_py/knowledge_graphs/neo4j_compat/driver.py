"""
Driver for Neo4j Compatibility

This module provides the main driver interface compatible with Neo4j's
Python driver, enabling seamless migration to IPFS-backed graph storage.

Usage:
    from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase
    
    # Connect to IPFS-backed graph database
    driver = GraphDatabase.driver("ipfs://localhost:5001", auth=("user", "token"))
    
    # Use exactly like Neo4j driver
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN n LIMIT 10")
        for record in result:
            print(record["n"])
    
    driver.close()
"""

import logging
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from .session import IPFSSession
from .connection_pool import ConnectionPool

try:
    from ipfs_datasets_py.router_deps import RouterDeps
    from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDBackend
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False
    RouterDeps = None  # type: ignore
    IPLDBackend = None  # type: ignore

logger = logging.getLogger(__name__)


class IPFSDriver:
    """
    Driver for IPFS-backed graph database.
    
    Compatible with neo4j.Driver.
    
    Manages connections and sessions for querying IPFS-stored graphs.
    """
    
    def __init__(
        self,
        uri: str,
        auth: Optional[Tuple[str, str]] = None,
        encrypted: bool = False,
        trust: bool = False,
        user_agent: Optional[str] = None,
        max_connection_lifetime: int = 3600,
        max_connection_pool_size: int = 100,
        connection_timeout: float = 30.0,
        keep_alive: bool = True,
        deps: Optional['RouterDeps'] = None,
        **config
    ):
        """
        Initialize the driver.
        
        Args:
            uri: Connection URI (ipfs://, ipfs+embedded://)
            auth: Authentication tuple (username, token)
            encrypted: Whether to use encryption (for future use)
            trust: Trust settings (for future use)
            user_agent: Custom user agent string
            max_connection_lifetime: Maximum connection lifetime in seconds
            max_connection_pool_size: Maximum pool size
            connection_timeout: Connection timeout in seconds
            keep_alive: Enable keep-alive
            deps: RouterDeps instance for shared state
            **config: Additional configuration
        """
        if not HAVE_DEPS:
            raise ImportError(
                "Required dependencies not available. "
                "Install ipfs_datasets_py with graph database support."
            )
        
        self.uri = uri
        self.auth = auth
        self.encrypted = encrypted
        self.trust = trust
        self.user_agent = user_agent or "ipfs-graph-database/0.1.0"
        self.max_connection_lifetime = max_connection_lifetime
        self.max_connection_pool_size = max_connection_pool_size
        self.connection_timeout = connection_timeout
        self.keep_alive = keep_alive
        self.config = config
        
        # Parse URI to determine mode and IPFS endpoint
        self._mode, self._ipfs_endpoint = self._parse_uri(uri)
        
        # Initialize RouterDeps and backend
        self.deps = deps if deps is not None else RouterDeps()
        self.backend = IPLDBackend(deps=self.deps)
        
        # Initialize connection pool
        self._connection_pool = ConnectionPool(
            max_size=max_connection_pool_size,
            max_connection_lifetime=max_connection_lifetime,
            connection_timeout=connection_timeout,
            keep_alive=keep_alive
        )
        
        self._closed = False
        
        logger.info("IPFSDriver initialized: uri=%s, mode=%s, pool_size=%d", 
                   uri, self._mode, max_connection_pool_size)
    
    def _parse_uri(self, uri: str) -> Tuple[str, Optional[str]]:
        """
        Parse the connection URI.
        
        Supported formats:
        - ipfs://localhost:5001 - Connect to IPFS daemon
        - ipfs+embedded://./data - Use embedded mode with local storage
        - ipfs://ipfs.example.com:443 - Remote IPFS API
        
        Args:
            uri: Connection URI
            
        Returns:
            Tuple of (mode, endpoint)
            
        Raises:
            ValueError: If URI format is invalid
        """
        parsed = urlparse(uri)
        
        if parsed.scheme == "ipfs":
            # Standard IPFS daemon connection
            host = parsed.hostname or "localhost"
            port = parsed.port or 5001
            return ("daemon", f"{host}:{port}")
        
        elif parsed.scheme == "ipfs+embedded":
            # Embedded mode with local storage
            path = parsed.path or "./ipfs_graph_data"
            return ("embedded", path)
        
        else:
            raise ValueError(
                f"Unsupported URI scheme: {parsed.scheme}. "
                f"Use 'ipfs://' or 'ipfs+embedded://'"
            )
    
    def session(
        self,
        database: Optional[str] = None,
        default_access_mode: str = "WRITE",
        bookmarks: Optional[Any] = None,
        **config
    ) -> IPFSSession:
        """
        Create a new session.
        
        Args:
            database: Database name (for multi-database support)
            default_access_mode: "READ" or "WRITE"
            bookmarks: Bookmarks for causal consistency (Phase 2)
            **config: Additional session configuration
            
        Returns:
            Session object
            
        Example:
            # Basic session
            with driver.session() as session:
                result = session.run("MATCH (n) RETURN n")
            
            # Session with bookmarks for causal consistency
            bookmark = session1.last_bookmark()
            with driver.session(bookmarks=[bookmark]) as session2:
                result = session2.run("MATCH (n) RETURN n")
        """
        if self._closed:
            raise RuntimeError("Driver is closed")
        
        return IPFSSession(
            driver=self,
            database=database,
            default_access_mode=default_access_mode,
            bookmarks=bookmarks
        )
    
    def close(self) -> None:
        """
        Close the driver and release resources.
        
        Should be called when the driver is no longer needed.
        """
        if not self._closed:
            self._closed = True
            # Close connection pool
            self._connection_pool.close()
            logger.info("IPFSDriver closed (pool stats: %s)", 
                       self._connection_pool.get_stats())
    
    def verify_connectivity(self) -> Dict[str, Any]:
        """
        Verify connectivity to the IPFS backend.
        
        Returns:
            Dictionary with connectivity information
            
        Raises:
            Exception: If connectivity check fails
        """
        if self._closed:
            raise RuntimeError("Driver is closed")
        
        try:
            # Try to get backend to verify IPFS is available
            backend_instance = self.backend._get_backend()
            backend_type = type(backend_instance).__name__
            
            return {
                "success": True,
                "backend_type": backend_type,
                "mode": self._mode,
                "endpoint": self._ipfs_endpoint
            }
        except Exception as e:
            logger.error("Connectivity check failed: %s", e)
            raise
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
    
    @property
    def closed(self) -> bool:
        """Check if driver is closed."""
        return self._closed
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """
        Get connection pool statistics.
        
        Returns:
            Dictionary with pool statistics including:
            - max_size: Maximum pool size
            - available: Available connections
            - in_use: Connections currently in use
            - total: Total connections in pool
            - stats: Detailed statistics (created, acquired, released, etc.)
        """
        return self._connection_pool.get_stats()
    
    def verify_authentication(self) -> bool:
        """
        Verify authentication credentials.
        
        Returns:
            True if authentication is valid, False otherwise
        """
        # Phase 2 will implement actual authentication
        # For now, always return True if auth was provided
        return self.auth is not None


class GraphDatabase:
    """
    Static factory for creating drivers.
    
    Compatible with neo4j.GraphDatabase.
    
    This is the main entry point for applications, providing a drop-in
    replacement for Neo4j's GraphDatabase class.
    """
    
    @staticmethod
    def driver(
        uri: str,
        auth: Optional[Tuple[str, str]] = None,
        **config
    ) -> IPFSDriver:
        """
        Create a new driver instance.
        
        Args:
            uri: Connection URI
            auth: Authentication credentials (username, token)
            **config: Additional driver configuration
            
        Returns:
            Driver instance
            
        Example:
            # Change from Neo4j to IPFS with just URI change!
            
            # Before (Neo4j):
            # driver = GraphDatabase.driver("bolt://localhost:7687",
            #                               auth=("neo4j", "password"))
            
            # After (IPFS Graph DB):
            driver = GraphDatabase.driver("ipfs://localhost:5001",
                                          auth=("user", "token"))
            
            # Rest of code stays the same!
            with driver.session() as session:
                result = session.run("MATCH (n) RETURN n LIMIT 10")
                for record in result:
                    print(record)
        """
        return IPFSDriver(uri, auth=auth, **config)
    
    @staticmethod
    def close_all_drivers() -> None:
        """
        Close all driver instances.
        
        Note: In this implementation, drivers are independent,
        so this is primarily for API compatibility.
        """
        logger.info("close_all_drivers called (no-op in current implementation)")


# For backward compatibility and convenience
def create_driver(uri: str, auth: Optional[Tuple[str, str]] = None, **config) -> IPFSDriver:
    """
    Create a driver instance.
    
    Convenience function equivalent to GraphDatabase.driver().
    
    Args:
        uri: Connection URI
        auth: Authentication credentials
        **config: Driver configuration
        
    Returns:
        Driver instance
    """
    return GraphDatabase.driver(uri, auth=auth, **config)
