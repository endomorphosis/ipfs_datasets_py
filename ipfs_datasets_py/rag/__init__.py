"""RAG (Retrieval-Augmented Generation) components with logic integration.

DEPRECATED: Logic integration components have been moved to ipfs_datasets_py.search.logic_integration.
This module provides backward compatibility.
"""

from ipfs_datasets_py.search.logic_integration import (
    LogicEnhancedRAG,
    RAGQueryResult
)

__all__ = [
    'LogicEnhancedRAG',
    'RAGQueryResult'
]
