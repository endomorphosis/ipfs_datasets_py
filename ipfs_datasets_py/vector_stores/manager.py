"""Unified manager for multiple vector stores.

This module provides a centralized manager for coordinating multiple vector
store instances and performing cross-store operations.
"""

import logging
from typing import Dict, List, Optional, Any, Union
from enum import Enum

from .base import BaseVectorStore, VectorStoreError
from .config import UnifiedVectorStoreConfig, VectorStoreType
from .schema import EmbeddingResult, SearchResult
from .bridges import create_bridge, VectorStoreBridge

# Import store implementations
from .faiss_store import FAISSVectorStore
from .qdrant_store import QdrantVectorStore
from .ipld_vector_store import IPLDVectorStore

try:
    from .elasticsearch_store import ElasticsearchVectorStore
    HAVE_ELASTICSEARCH = True
except ImportError:
    HAVE_ELASTICSEARCH = False
    ElasticsearchVectorStore = None

logger = logging.getLogger(__name__)


class VectorStoreManager:
    """Centralized manager for multiple vector stores.
    
    Manages multiple vector store instances, coordinates cross-store operations,
    and provides a unified interface for multi-store workflows.
    
    Features:
    - Lazy initialization of stores
    - Cross-store migration
    - Multi-store search
    - Unified configuration management
    - Store health monitoring
    
    Example:
        ```python
        from ipfs_datasets_py.vector_stores import VectorStoreManager
        from ipfs_datasets_py.vector_stores.config import create_ipld_config, create_faiss_config
        
        manager = VectorStoreManager()
        
        # Register stores
        ipld_config = create_ipld_config("documents", 768)
        manager.register_store("ipld", ipld_config)
        
        faiss_config = create_faiss_config("documents", 768)
        manager.register_store("faiss", faiss_config)
        
        # Get store
        store = await manager.get_store("ipld")
        
        # Migrate between stores
        count = await manager.migrate("faiss", "ipld", "documents")
        
        # Search across multiple stores
        results = await manager.search_all(
            query_vector,
            stores=["ipld", "faiss"],
            top_k=5
        )
        ```
    """
    
    def __init__(self):
        """Initialize vector store manager."""
        self.stores: Dict[str, BaseVectorStore] = {}
        self.configs: Dict[str, UnifiedVectorStoreConfig] = {}
        self.bridges: Dict[tuple, VectorStoreBridge] = {}
        
        logger.info("Initialized VectorStoreManager")
    
    def register_store(
        self,
        name: str,
        config: UnifiedVectorStoreConfig,
        store_instance: Optional[BaseVectorStore] = None
    ) -> None:
        """Register a vector store with the manager.
        
        Args:
            name: Unique name for this store
            config: Store configuration
            store_instance: Optional pre-initialized store instance
        """
        if name in self.stores:
            logger.warning(f"Store '{name}' already registered, replacing")
        
        self.configs[name] = config
        
        if store_instance:
            self.stores[name] = store_instance
        
        logger.info(f"Registered store '{name}' ({config.store_type})")
    
    async def get_store(self, name: str) -> BaseVectorStore:
        """Get or create a vector store instance.
        
        Args:
            name: Name of the registered store
            
        Returns:
            Vector store instance
            
        Raises:
            VectorStoreError: If store not registered
        """
        if name not in self.configs:
            raise VectorStoreError(f"Store '{name}' not registered")
        
        # Return existing instance if available
        if name in self.stores:
            return self.stores[name]
        
        # Create new instance
        config = self.configs[name]
        store = self._create_store(config)
        self.stores[name] = store
        
        logger.info(f"Created store instance '{name}'")
        return store
    
    def _create_store(self, config: UnifiedVectorStoreConfig) -> BaseVectorStore:
        """Create a vector store instance from config.
        
        Args:
            config: Store configuration
            
        Returns:
            Vector store instance
            
        Raises:
            VectorStoreError: If store type not supported
        """
        store_type = config.store_type
        
        if store_type == VectorStoreType.IPLD or (isinstance(store_type, str) and store_type == "ipld"):
            return IPLDVectorStore(config)
        elif store_type == VectorStoreType.FAISS or (isinstance(store_type, str) and store_type == "faiss"):
            return FAISSVectorStore(config)
        elif store_type == VectorStoreType.QDRANT or (isinstance(store_type, str) and store_type == "qdrant"):
            return QdrantVectorStore(config)
        elif store_type == VectorStoreType.ELASTICSEARCH or (isinstance(store_type, str) and store_type == "elasticsearch"):
            if HAVE_ELASTICSEARCH and ElasticsearchVectorStore:
                return ElasticsearchVectorStore(config)
            else:
                raise VectorStoreError("Elasticsearch store not available")
        else:
            raise VectorStoreError(f"Unsupported store type: {store_type}")
    
    async def migrate(
        self,
        source_name: str,
        target_name: str,
        collection_name: str,
        target_collection_name: Optional[str] = None,
        batch_size: int = 1000,
        verify: bool = True
    ) -> int:
        """Migrate collection between stores.
        
        Args:
            source_name: Source store name
            target_name: Target store name
            collection_name: Collection to migrate
            target_collection_name: Target collection name (optional)
            batch_size: Batch size for migration
            verify: Whether to verify after migration
            
        Returns:
            Number of vectors migrated
        """
        # Get stores
        source_store = await self.get_store(source_name)
        target_store = await self.get_store(target_name)
        
        # Get or create bridge
        bridge_key = (source_name, target_name)
        if bridge_key not in self.bridges:
            self.bridges[bridge_key] = create_bridge(source_store, target_store)
        
        bridge = self.bridges[bridge_key]
        
        # Migrate
        logger.info(f"Migrating '{collection_name}' from {source_name} to {target_name}")
        count = await bridge.migrate_collection(
            collection_name,
            target_collection_name,
            batch_size=batch_size,
            verify=verify
        )
        
        logger.info(f"Migration complete: {count} vectors")
        return count
    
    async def search_all(
        self,
        query_vector: List[float],
        stores: Optional[List[str]] = None,
        collection_name: Optional[str] = None,
        top_k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> Dict[str, List[SearchResult]]:
        """Search across multiple stores.
        
        Args:
            query_vector: Query vector
            stores: List of store names to search (None = all)
            collection_name: Collection to search
            top_k: Number of results per store
            filter_dict: Optional metadata filters
            
        Returns:
            Dict mapping store names to search results
        """
        # Determine which stores to search
        store_names = stores or list(self.configs.keys())
        
        results = {}
        for name in store_names:
            try:
                store = await self.get_store(name)
                store_results = await store.search(
                    query_vector,
                    top_k=top_k,
                    collection_name=collection_name,
                    filter_dict=filter_dict
                )
                results[name] = store_results
                logger.debug(f"Search in '{name}': {len(store_results)} results")
            except Exception as e:
                logger.error(f"Search failed in store '{name}': {e}")
                results[name] = []
        
        return results
    
    async def get_store_health(self, name: str) -> Dict[str, Any]:
        """Get health status of a store.
        
        Args:
            name: Store name
            
        Returns:
            Health status dict
        """
        try:
            store = await self.get_store(name)
            info = await store.get_store_info()
            
            return {
                "name": name,
                "healthy": True,
                "info": info,
                "error": None
            }
        except Exception as e:
            return {
                "name": name,
                "healthy": False,
                "info": None,
                "error": str(e)
            }
    
    async def get_all_health(self) -> Dict[str, Dict[str, Any]]:
        """Get health status of all registered stores.
        
        Returns:
            Dict mapping store names to health status
        """
        health = {}
        for name in self.configs.keys():
            health[name] = await self.get_store_health(name)
        return health
    
    async def close_all(self):
        """Close all store connections."""
        for name, store in self.stores.items():
            try:
                await store.close()
                logger.info(f"Closed store '{name}'")
            except Exception as e:
                logger.error(f"Error closing store '{name}': {e}")
    
    def list_stores(self) -> List[str]:
        """List all registered store names.
        
        Returns:
            List of store names
        """
        return list(self.configs.keys())
    
    def get_config(self, name: str) -> Optional[UnifiedVectorStoreConfig]:
        """Get configuration for a store.
        
        Args:
            name: Store name
            
        Returns:
            Store configuration or None if not found
        """
        return self.configs.get(name)
    
    async def sync_collections(
        self,
        collection_name: str,
        primary_store: str,
        replica_stores: List[str],
        batch_size: int = 1000
    ) -> Dict[str, int]:
        """Synchronize a collection across multiple stores.
        
        Args:
            collection_name: Collection to sync
            primary_store: Primary store to sync from
            replica_stores: List of stores to sync to
            batch_size: Batch size for sync
            
        Returns:
            Dict mapping store names to number of vectors synced
        """
        results = {}
        
        for replica_name in replica_stores:
            try:
                count = await self.migrate(
                    primary_store,
                    replica_name,
                    collection_name,
                    batch_size=batch_size,
                    verify=True
                )
                results[replica_name] = count
                logger.info(f"Synced {count} vectors to '{replica_name}'")
            except Exception as e:
                logger.error(f"Sync to '{replica_name}' failed: {e}")
                results[replica_name] = -1
        
        return results


__all__ = ['VectorStoreManager']
