"""Unified configuration for vector stores with router integration.

This module provides enhanced configuration classes that support IPLD/IPFS
operations and automatic router integration for embeddings and storage.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

# Import base config from ml/embeddings
try:
    from ..ml.embeddings.schema import VectorStoreConfig, VectorStoreType
except ImportError:
    # Fallback if ml/embeddings not available
    from enum import Enum
    
    class VectorStoreType(Enum):
        """Supported vector store types."""
        QDRANT = "qdrant"
        FAISS = "faiss"
        ELASTICSEARCH = "elasticsearch"
        CHROMA = "chroma"
        IPLD = "ipld"
    
    @dataclass
    class VectorStoreConfig:
        """Base configuration for vector store operations."""
        store_type: VectorStoreType
        collection_name: str
        host: Optional[str] = None
        port: Optional[int] = None
        index_name: Optional[str] = None
        dimension: Optional[int] = None
        distance_metric: str = "cosine"
        connection_params: Optional[Dict[str, Any]] = None


# Add IPLD to VectorStoreType if not present
if not hasattr(VectorStoreType, 'IPLD'):
    # Create new enum with IPLD
    VectorStoreType = Enum('VectorStoreType', {
        **{member.name: member.value for member in VectorStoreType},
        'IPLD': 'ipld'
    })


@dataclass
class UnifiedVectorStoreConfig(VectorStoreConfig):
    """Enhanced vector store configuration with router integration and IPLD support.
    
    This configuration extends the base VectorStoreConfig with:
    - Router integration flags for automatic embeddings and IPFS operations
    - IPLD-specific settings for content-addressed storage
    - Performance tuning parameters
    - Multi-store synchronization options
    """
    
    # Router Integration Settings
    use_embeddings_router: bool = True
    """Enable automatic embedding generation via embeddings_router"""
    
    use_ipfs_router: bool = True
    """Enable automatic IPFS storage via ipfs_backend_router"""
    
    embeddings_router_provider: Optional[str] = None
    """Preferred embeddings provider: 'openrouter', 'gemini', 'hf', or None for auto"""
    
    ipfs_router_backend: Optional[str] = None
    """Preferred IPFS backend: 'accelerate', 'kit', 'kubo', or None for auto"""
    
    router_cache_enabled: bool = True
    """Enable caching for router operations"""
    
    # IPLD-Specific Settings
    enable_ipld_export: bool = True
    """Enable automatic IPLD export capabilities"""
    
    auto_pin_to_ipfs: bool = False
    """Automatically pin data to IPFS after storage"""
    
    car_export_dir: Optional[str] = None
    """Directory for CAR file exports, None for temp directory"""
    
    ipld_chunk_size: int = 1000
    """Number of vectors per IPLD chunk (for large collections)"""
    
    ipld_compression: bool = False
    """Enable compression for IPLD blocks"""
    
    # Performance Settings
    batch_size: int = 1000
    """Default batch size for operations"""
    
    parallel_workers: int = 4
    """Number of parallel workers for batch operations"""
    
    cache_size: int = 10000
    """Maximum number of items to cache"""
    
    prefetch_enabled: bool = True
    """Enable prefetching for improved performance"""
    
    # Multi-Store Settings
    enable_multi_store_sync: bool = False
    """Enable synchronization across multiple stores"""
    
    sync_stores: Optional[List[str]] = field(default_factory=list)
    """List of store types to sync with"""
    
    sync_interval: int = 3600
    """Sync interval in seconds"""
    
    # Additional IPLD Settings
    ipld_storage_path: Optional[str] = None
    """Path for IPLD storage, None for default"""
    
    ipfs_gateway: Optional[str] = None
    """IPFS gateway URL for retrieval operations"""
    
    enable_dag_export: bool = True
    """Enable DAG export capabilities"""
    
    max_block_size: int = 800 * 1024  # 800KB
    """Maximum IPLD block size before chunking"""
    
    def __post_init__(self):
        """Initialize computed fields."""
        super().__post_init__() if hasattr(super(), '__post_init__') else None
        
        # Ensure sync_stores is a list
        if self.sync_stores is None:
            self.sync_stores = []
        
        # Set default connection params if not provided
        if self.connection_params is None:
            self.connection_params = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation.
        
        Returns:
            Dictionary containing all configuration parameters
        """
        base_dict = super().to_dict() if hasattr(super(), 'to_dict') else {}
        
        return {
            **base_dict,
            'use_embeddings_router': self.use_embeddings_router,
            'use_ipfs_router': self.use_ipfs_router,
            'embeddings_router_provider': self.embeddings_router_provider,
            'ipfs_router_backend': self.ipfs_router_backend,
            'router_cache_enabled': self.router_cache_enabled,
            'enable_ipld_export': self.enable_ipld_export,
            'auto_pin_to_ipfs': self.auto_pin_to_ipfs,
            'car_export_dir': self.car_export_dir,
            'ipld_chunk_size': self.ipld_chunk_size,
            'ipld_compression': self.ipld_compression,
            'batch_size': self.batch_size,
            'parallel_workers': self.parallel_workers,
            'cache_size': self.cache_size,
            'prefetch_enabled': self.prefetch_enabled,
            'enable_multi_store_sync': self.enable_multi_store_sync,
            'sync_stores': self.sync_stores,
            'sync_interval': self.sync_interval,
            'ipld_storage_path': self.ipld_storage_path,
            'ipfs_gateway': self.ipfs_gateway,
            'enable_dag_export': self.enable_dag_export,
            'max_block_size': self.max_block_size,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UnifiedVectorStoreConfig':
        """Create instance from dictionary.
        
        Args:
            data: Dictionary containing configuration parameters
            
        Returns:
            UnifiedVectorStoreConfig instance
        """
        # Handle store_type enum conversion
        if 'store_type' in data and isinstance(data['store_type'], str):
            data['store_type'] = VectorStoreType(data['store_type'])
        
        return cls(**data)
    
    def with_router_config(
        self,
        use_embeddings: bool = True,
        use_ipfs: bool = True,
        embeddings_provider: Optional[str] = None,
        ipfs_backend: Optional[str] = None
    ) -> 'UnifiedVectorStoreConfig':
        """Create a copy with updated router configuration.
        
        Args:
            use_embeddings: Enable embeddings router
            use_ipfs: Enable IPFS router
            embeddings_provider: Embeddings provider to use
            ipfs_backend: IPFS backend to use
            
        Returns:
            New configuration instance with updated router settings
        """
        config_dict = self.to_dict()
        config_dict.update({
            'use_embeddings_router': use_embeddings,
            'use_ipfs_router': use_ipfs,
            'embeddings_router_provider': embeddings_provider,
            'ipfs_router_backend': ipfs_backend,
        })
        return self.from_dict(config_dict)
    
    def with_ipld_config(
        self,
        enable_export: bool = True,
        auto_pin: bool = False,
        chunk_size: int = 1000,
        compression: bool = False
    ) -> 'UnifiedVectorStoreConfig':
        """Create a copy with updated IPLD configuration.
        
        Args:
            enable_export: Enable IPLD export
            auto_pin: Auto-pin to IPFS
            chunk_size: Vectors per IPLD chunk
            compression: Enable compression
            
        Returns:
            New configuration instance with updated IPLD settings
        """
        config_dict = self.to_dict()
        config_dict.update({
            'enable_ipld_export': enable_export,
            'auto_pin_to_ipfs': auto_pin,
            'ipld_chunk_size': chunk_size,
            'ipld_compression': compression,
        })
        return self.from_dict(config_dict)


def create_ipld_config(
    collection_name: str,
    dimension: int = 768,
    distance_metric: str = "cosine",
    use_embeddings_router: bool = True,
    use_ipfs_router: bool = True,
    **kwargs
) -> UnifiedVectorStoreConfig:
    """Create a configuration for IPLD vector store.
    
    Args:
        collection_name: Name of the collection
        dimension: Vector dimension
        distance_metric: Distance metric to use
        use_embeddings_router: Enable embeddings router
        use_ipfs_router: Enable IPFS router
        **kwargs: Additional configuration parameters
        
    Returns:
        UnifiedVectorStoreConfig configured for IPLD
    """
    return UnifiedVectorStoreConfig(
        store_type=VectorStoreType.IPLD,
        collection_name=collection_name,
        dimension=dimension,
        distance_metric=distance_metric,
        use_embeddings_router=use_embeddings_router,
        use_ipfs_router=use_ipfs_router,
        **kwargs
    )


def create_faiss_config(
    collection_name: str,
    dimension: int = 768,
    distance_metric: str = "cosine",
    **kwargs
) -> UnifiedVectorStoreConfig:
    """Create a configuration for FAISS vector store.
    
    Args:
        collection_name: Name of the collection
        dimension: Vector dimension
        distance_metric: Distance metric to use
        **kwargs: Additional configuration parameters
        
    Returns:
        UnifiedVectorStoreConfig configured for FAISS
    """
    return UnifiedVectorStoreConfig(
        store_type=VectorStoreType.FAISS,
        collection_name=collection_name,
        dimension=dimension,
        distance_metric=distance_metric,
        **kwargs
    )


def create_qdrant_config(
    collection_name: str,
    dimension: int = 768,
    host: str = "localhost",
    port: int = 6333,
    distance_metric: str = "cosine",
    **kwargs
) -> UnifiedVectorStoreConfig:
    """Create a configuration for Qdrant vector store.
    
    Args:
        collection_name: Name of the collection
        dimension: Vector dimension
        host: Qdrant host
        port: Qdrant port
        distance_metric: Distance metric to use
        **kwargs: Additional configuration parameters
        
    Returns:
        UnifiedVectorStoreConfig configured for Qdrant
    """
    return UnifiedVectorStoreConfig(
        store_type=VectorStoreType.QDRANT,
        collection_name=collection_name,
        dimension=dimension,
        host=host,
        port=port,
        distance_metric=distance_metric,
        **kwargs
    )
