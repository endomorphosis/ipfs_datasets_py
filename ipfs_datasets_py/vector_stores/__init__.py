"""Vector store implementations for embeddings.

This module provides interfaces and implementations for various vector databases,
including IPLD/IPFS-native storage with content addressing.
"""

try:

    # Base classes and errors
    from .base import (
        BaseVectorStore,
        VectorStoreError,
        VectorStoreConnectionError,
        VectorStoreOperationError
    )

    # Configuration
    from .config import (
        UnifiedVectorStoreConfig,
        create_ipld_config,
        create_faiss_config,
        create_qdrant_config
    )

    # Schema
    from .schema import (
        EmbeddingResult,
        SearchResult,
        IPLDEmbeddingResult,
        IPLDSearchResult,
        CollectionMetadata,
        VectorBlock,
        VectorStoreType
    )

    # Router integration
    from .router_integration import RouterIntegration, create_router_integration

    # Vector store implementations
    from .faiss_store import FAISSVectorStore
    from .qdrant_store import QdrantVectorStore
    from .ipld_vector_store import IPLDVectorStore

    try:
        from .elasticsearch_store import ElasticsearchVectorStore
    except ImportError:
        ElasticsearchVectorStore = None

    # Bridges for cross-store migration
    from .bridges import create_bridge, VectorStoreBridge

    # Manager and high-level API
    from .manager import VectorStoreManager
    from .api import (
        create_vector_store,
        add_texts_to_store,
        search_texts,
        migrate_collection,
        export_collection_to_ipfs,
        import_collection_from_ipfs,
        create_manager
    )

    __all__ = [
        # Base classes and errors
        'BaseVectorStore',
        'VectorStoreError',
        'VectorStoreConnectionError',
        'VectorStoreOperationError',
        # Configuration
        'UnifiedVectorStoreConfig',
        'create_ipld_config',
        'create_faiss_config',
        'create_qdrant_config',
        # Schema
        'EmbeddingResult',
        'SearchResult',
        'IPLDEmbeddingResult',
        'IPLDSearchResult',
        'CollectionMetadata',
        'VectorBlock',
        'VectorStoreType',
        # Router integration
        'RouterIntegration',
        'create_router_integration',
        # Vector stores
        'FAISSVectorStore',
        'QdrantVectorStore',
        'IPLDVectorStore',
        'ElasticsearchVectorStore',
        # Bridges
        'create_bridge',
        'VectorStoreBridge',
        # Manager and API
        'VectorStoreManager',
        'create_vector_store',
        'add_texts_to_store',
        'search_texts',
        'migrate_collection',
        'export_collection_to_ipfs',
        'import_collection_from_ipfs',
        'create_manager',
    ]


except ImportError:
    pass  # Optional dependencies not installed
