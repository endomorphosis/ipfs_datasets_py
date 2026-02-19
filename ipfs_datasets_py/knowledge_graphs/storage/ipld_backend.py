"""
IPLD Storage Backend for Graph Database

This module provides IPLD-based storage with ipfs_backend_router integration,
ensuring compatibility with Kubo, ipfs_kit_py, and ipfs_accelerate_py backends.

All IPFS operations go through ipfs_backend_router for maximum compatibility.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from collections import OrderedDict

try:
    from ipfs_datasets_py.ipfs_backend_router import get_ipfs_backend
    from ipfs_datasets_py.router_deps import RouterDeps
    HAVE_ROUTER = True
except ImportError:
    HAVE_ROUTER = False
    RouterDeps = None  # type: ignore

# Import custom exceptions
from ..exceptions import (
    StorageError,
    IPLDStorageError,
    SerializationError,
    DeserializationError
)

logger = logging.getLogger(__name__)


class LRUCache:
    """
    Simple LRU (Least Recently Used) cache implementation.
    
    Provides O(1) get/set operations using an OrderedDict.
    """
    
    def __init__(self, capacity: int = 1000):
        """
        Initialize the LRU cache.
        
        Args:
            capacity: Maximum number of items to cache
        """
        self.capacity = capacity
        self.cache: OrderedDict = OrderedDict()
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        if key not in self.cache:
            return None
        
        # Move to end (most recently used)
        self.cache.move_to_end(key)
        return self.cache[key]
    
    def put(self, key: str, value: Any) -> None:
        """
        Put value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        if key in self.cache:
            # Update existing key
            self.cache.move_to_end(key)
        else:
            # Add new key
            if len(self.cache) >= self.capacity:
                # Remove least recently used (first item)
                self.cache.popitem(last=False)
        
        self.cache[key] = value
    
    def clear(self) -> None:
        """Clear all cached items."""
        self.cache.clear()
    
    def __len__(self) -> int:
        """Get current cache size."""
        return len(self.cache)


class IPLDBackend:
    """
    IPLD storage backend using ipfs_backend_router.
    
    Provides storage and retrieval operations for graph data using IPFS,
    with automatic backend selection (Kubo, ipfs_kit_py, or ipfs_accelerate_py).
    
    Environment Variables:
        IPFS_DATASETS_PY_IPFS_BACKEND: Force specific backend
        IPFS_DATASETS_PY_ENABLE_IPFS_KIT: Enable ipfs_kit_py
        IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE: Enable acceleration
    
    Example:
        from ipfs_datasets_py.router_deps import RouterDeps
        from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend
        
        deps = RouterDeps()
        backend = IPLDBackend(deps=deps)
        
        # Store data
        cid = backend.store(b"graph data", pin=True)
        
        # Retrieve data
        data = backend.retrieve(cid)
    """
    
    def __init__(
        self,
        deps: Optional['RouterDeps'] = None,
        database: str = "neo4j",
        pin_by_default: bool = True,
        cache_capacity: int = 1000
    ):
        """
        Initialize the IPLD backend.
        
        Args:
            deps: RouterDeps instance for shared state (creates new if None)
            database: Database name for namespace isolation
            pin_by_default: Whether to pin content by default
            cache_capacity: Maximum number of items to cache (0 to disable)
        """
        if not HAVE_ROUTER:
            raise ImportError(
                "ipfs_backend_router not available. "
                "Install ipfs_datasets_py with IPFS support."
            )
        
        self.deps = deps if deps is not None else RouterDeps()
        self.database = database
        self._namespace = f"kg:db:{database}:"
        self.pin_by_default = pin_by_default
        self._backend = None
        self._cache = LRUCache(cache_capacity) if cache_capacity > 0 else None
        
        logger.debug("IPLDBackend initialized (deps=%s, database=%s, cache=%s)", 
                    self.deps, database, cache_capacity if self._cache else "disabled")
    
    def _get_backend(self):
        """
        Get the IPFS backend instance.
        
        Uses ipfs_backend_router to automatically select the best backend
        (Kubo, ipfs_kit_py, or ipfs_accelerate_py) based on environment.
        
        Returns:
            IPFS backend instance
        """
        if self._backend is None:
            self._backend = get_ipfs_backend(deps=self.deps)
            logger.debug("IPFS backend initialized: %s", type(self._backend).__name__)
        return self._backend

    @property
    def backend_name(self) -> str:
        backend = getattr(self, "_backend", None)
        if backend is None:
            return "uninitialized"
        return type(backend).__name__
    
    def _make_key(self, key: str) -> str:
        """
        Add database namespace to key for multi-database isolation.
        
        Args:
            key: Storage key
            
        Returns:
            Namespaced key (e.g., "kg:db:neo4j:nodes:123")
            
        Example:
            >>> backend._make_key("nodes:123")
            'kg:db:neo4j:nodes:123'
        """
        return f"{self._namespace}{key}"
    
    def store(
        self,
        data: Union[bytes, str, Dict, List],
        pin: Optional[bool] = None,
        codec: str = "dag-json"
    ) -> str:
        """
        Store data on IPFS and return CID.
        
        Args:
            data: Data to store (bytes, string, or JSON-serializable object)
            pin: Whether to pin the content (uses default if None)
            codec: IPLD codec to use ("dag-json", "raw", "dag-cbor")
            
        Returns:
            CID of the stored data
            
        Example:
            cid = backend.store({"name": "Alice", "age": 30})
        """
        pin = pin if pin is not None else self.pin_by_default
        backend = self._get_backend()
        
        try:
            # Convert data to bytes
            if isinstance(data, str):
                data_bytes = data.encode('utf-8')
            elif isinstance(data, (dict, list)):
                data_bytes = json.dumps(data, separators=(',', ':')).encode('utf-8')
            elif isinstance(data, bytes):
                data_bytes = data
            else:
                raise TypeError(f"Unsupported data type: {type(data)}")
            
            # Store using ipfs_backend_router
            if codec == "raw":
                cid = backend.add_bytes(data_bytes, pin=pin)
            else:
                # Use block_put for dag-json and other codecs
                cid = backend.block_put(data_bytes, codec=codec)
                if pin:
                    backend.pin(cid)
            
            logger.debug("Stored data with CID: %s (pinned=%s)", cid, pin)
            return cid
            
        except (TypeError, ValueError, UnicodeEncodeError) as e:
            logger.error(f"Failed to serialize data: {e}")
            raise SerializationError(
                f"Failed to serialize data for IPFS storage: {e}",
                details={'data_type': type(data).__name__, 'codec': codec}
            ) from e
        except (SerializationError, IPLDStorageError, StorageError):
            raise
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.error(f"IPFS connection error: {e}")
            raise IPLDStorageError(
                f"IPFS connection failed: {e}",
                details={'backend': self.backend_name, 'operation': 'store'}
            ) from e
        except Exception as e:
            logger.error(f"Failed to store on IPFS: {e}")
            raise IPLDStorageError(
                "Failed to store data on IPFS",
                details={'backend': self.backend_name, 'codec': codec, 'operation': 'store'}
            ) from e
    
    def retrieve(self, cid: str) -> bytes:
        """
        Retrieve data from IPFS by CID.
        
        Args:
            cid: Content identifier
            
        Returns:
            Raw bytes of the content
            
        Example:
            data = backend.retrieve("bafybeig...")
        """
        backend = self._get_backend()
        
        # Check cache first
        if self._cache:
            cached_data = self._cache.get(cid)
            if cached_data is not None:
                logger.debug("Cache hit for CID: %s", cid)
                return cached_data
        
        try:
            # Try block_get first (works for all codecs)
            data = backend.block_get(cid)
        except (AttributeError, KeyError) as e:
            logger.debug("block_get failed (expected), trying cat: %s", e)
            # Fallback to cat for compatibility
            try:
                data = backend.cat(cid)
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.error(f"IPFS connection error retrieving {cid}: {e}")
                raise IPLDStorageError(
                    f"IPFS connection failed: {e}",
                    details={'backend': self.backend_name, 'cid': cid, 'operation': 'retrieve'}
                ) from e
            except Exception as e:
                logger.error(f"Failed to retrieve CID {cid}: {e}")
                raise IPLDStorageError(
                    "Failed to retrieve data from IPFS",
                    details={'backend': self.backend_name, 'cid': cid, 'operation': 'retrieve'}
                ) from e
        except (SerializationError, DeserializationError, IPLDStorageError, StorageError):
            raise
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.error(f"IPFS connection error: {e}")
            raise IPLDStorageError(
                f"IPFS connection failed: {e}",
                details={'backend': self.backend_name, 'cid': cid}
            ) from e
        except Exception as e:
            logger.error(f"Failed to retrieve from IPFS: {e}")
            raise IPLDStorageError(
                "Failed to retrieve data from IPFS",
                details={'backend': self.backend_name, 'cid': cid, 'operation': 'retrieve'}
            ) from e
        
        # Store in cache
        if self._cache:
            self._cache.put(cid, data)
        
        logger.debug("Retrieved %d bytes for CID: %s", len(data), cid)
        return data
    
    def retrieve_json(self, cid: str) -> Union[Dict, List]:
        """
        Retrieve and parse JSON data from IPFS.
        
        Args:
            cid: Content identifier
            
        Returns:
            Parsed JSON object (dict or list)
            
        Example:
            data = backend.retrieve_json("bafybeig...")
        """
        # Check cache for parsed JSON
        cache_key = f"json:{cid}"
        if self._cache:
            cached_json = self._cache.get(cache_key)
            if cached_json is not None:
                logger.debug("Cache hit for JSON CID: %s", cid)
                return cached_json
        
        data_bytes = self.retrieve(cid)
        try:
            json_data = json.loads(data_bytes.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as e:
            raise DeserializationError(
                "Failed to deserialize JSON from IPFS",
                details={'backend': self.backend_name, 'cid': cid, 'operation': 'retrieve_json'}
            ) from e
        
        # Cache the parsed JSON
        if self._cache:
            self._cache.put(cache_key, json_data)
        
        return json_data
    
    def pin(self, cid: str) -> None:
        """
        Pin content on IPFS.
        
        Args:
            cid: Content identifier to pin
        """
        backend = self._get_backend()
        backend.pin(cid)
        logger.debug("Pinned CID: %s", cid)
    
    def unpin(self, cid: str) -> None:
        """
        Unpin content on IPFS.
        
        Args:
            cid: Content identifier to unpin
        """
        backend = self._get_backend()
        backend.unpin(cid)
        
        # Clear from cache
        if self._cache:
            self._cache.get(cid)  # This will not return anything, just checking
            # Note: We don't actively remove from cache as it's LRU and will expire naturally
        
        logger.debug("Unpinned CID: %s", cid)
    
    def list_directory(self, cid: str) -> List[str]:
        """
        List contents of a directory CID.
        
        Args:
            cid: Directory CID
            
        Returns:
            List of entry names
        """
        backend = self._get_backend()
        return backend.ls(cid)
    
    def export_car(self, root_cid: str) -> bytes:
        """
        Export DAG as CAR file bytes.
        
        Args:
            root_cid: Root CID of the DAG
            
        Returns:
            CAR file contents as bytes
            
        Example:
            car_bytes = backend.export_car("bafybeig...")
            with open("graph.car", "wb") as f:
                f.write(car_bytes)
        """
        backend = self._get_backend()
        return backend.dag_export(root_cid)
    
    def store_graph(
        self,
        nodes: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Store a complete graph structure on IPFS.
        
        Args:
            nodes: List of node dictionaries
            relationships: List of relationship dictionaries
            metadata: Optional graph metadata
            
        Returns:
            Root CID of the graph
            
        Example:
            cid = backend.store_graph(
                nodes=[{"id": "1", "name": "Alice"}],
                relationships=[{"type": "KNOWS", "start": "1", "end": "2"}],
                metadata={"created": "2024-01-01"}
            )
        """
        graph_data = {
            "nodes": nodes,
            "relationships": relationships,
            "metadata": metadata or {}
        }
        
        return self.store(graph_data, pin=True, codec="dag-json")
    
    def retrieve_graph(self, root_cid: str) -> Dict[str, Any]:
        """
        Retrieve a complete graph structure from IPFS.
        
        Args:
            root_cid: Root CID of the graph
            
        Returns:
            Graph data with nodes, relationships, and metadata
            
        Example:
            graph = backend.retrieve_graph("bafybeig...")
            nodes = graph["nodes"]
            relationships = graph["relationships"]
        """
        return self.retrieve_json(root_cid)
    
    def clear_cache(self) -> None:
        """
        Clear the LRU cache.
        
        Useful for freeing memory or forcing fresh data retrieval.
        """
        if self._cache:
            self._cache.clear()
            logger.debug("Cache cleared")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache size and capacity
        """
        if not self._cache:
            return {"enabled": False}
        
        return {
            "enabled": True,
            "size": len(self._cache),
            "capacity": self._cache.capacity
        }


# Convenience function for creating backend with defaults
def create_backend(deps: Optional['RouterDeps'] = None) -> IPLDBackend:
    """
    Create an IPLD backend with default settings.
    
    Args:
        deps: Optional RouterDeps instance
        
    Returns:
        Configured IPLDBackend instance
        
    Example:
        backend = create_backend()
        cid = backend.store({"hello": "world"})
    """
    return IPLDBackend(deps=deps)
