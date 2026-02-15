"""
GraphRAG - Graph Retrieval-Augmented Generation.

This package provides comprehensive GraphRAG functionality including:
- Entity extraction and knowledge graph construction
- Vector embeddings and semantic search
- Website processing and archiving
- LLM-powered reasoning and query answering
- Advanced analytics and ML integration

Main Classes:
- UnifiedGraphRAGProcessor: Base GraphRAG processor
- GraphRAGIntegration: LLM reasoning and hybrid search
- WebsiteGraphRAGSystem: Website-specific search and query

Example:
    from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor
    
    processor = UnifiedGraphRAGProcessor()
    result = await processor.process("https://example.com")
"""

from .unified_graphrag import UnifiedGraphRAGProcessor, GraphRAGConfiguration
from .integration import GraphRAGIntegration, HybridVectorGraphSearch, GraphRAGFactory
from .website_system import WebsiteGraphRAGSystem, SearchResult

__all__ = [
    'UnifiedGraphRAGProcessor',
    'GraphRAGConfiguration',
    'GraphRAGIntegration',
    'HybridVectorGraphSearch',
    'GraphRAGFactory',
    'WebsiteGraphRAGSystem',
    'SearchResult',
]
