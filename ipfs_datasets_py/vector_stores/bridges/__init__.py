"""Vector store bridges for cross-store migration.

This package provides bridge implementations for migrating vector collections
between different vector store types.
"""

from typing import Optional
import logging

from ..base import BaseVectorStore
from .base_bridge import VectorStoreBridge, SimpleBridge

logger = logging.getLogger(__name__)


def create_bridge(
    source_store: BaseVectorStore,
    target_store: BaseVectorStore,
    bridge_type: Optional[str] = None
) -> VectorStoreBridge:
    """Factory function to create appropriate bridge.
    
    Creates a bridge between source and target stores. If bridge_type is not
    specified, attempts to select the best bridge based on store types.
    
    Args:
        source_store: Source vector store
        target_store: Target vector store
        bridge_type: Optional bridge type override
        
    Returns:
        VectorStoreBridge instance
        
    Example:
        ```python
        from ipfs_datasets_py.vector_stores import FAISSVectorStore, IPLDVectorStore
        from ipfs_datasets_py.vector_stores.bridges import create_bridge
        
        faiss_store = FAISSVectorStore(faiss_config)
        ipld_store = IPLDVectorStore(ipld_config)
        
        bridge = create_bridge(faiss_store, ipld_store)
        count = await bridge.migrate_collection("documents")
        ```
    """
    # Get store type names
    source_type = source_store.__class__.__name__
    target_type = target_store.__class__.__name__
    
    logger.info(f"Creating bridge: {source_type} → {target_type}")
    
    # For now, use SimpleBridge for all combinations
    # Specific bridges can be implemented as needed
    return SimpleBridge(source_store, target_store)


__all__ = [
    'VectorStoreBridge',
    'SimpleBridge',
    'create_bridge',
]
