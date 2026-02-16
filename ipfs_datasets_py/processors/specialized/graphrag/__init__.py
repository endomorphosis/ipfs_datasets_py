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

# Optional imports with fallback
try:
    from .integration import GraphRAGIntegration, HybridVectorGraphSearch, GraphRAGFactory
    _integration_available = True
except ImportError as e:
    # Create stub classes for when dependencies are missing
    import warnings
    warnings.warn(f"GraphRAG integration features unavailable: {e}", ImportWarning)
    GraphRAGIntegration = None
    HybridVectorGraphSearch = None
    GraphRAGFactory = None
    _integration_available = False

try:
    from .website_system import WebsiteGraphRAGSystem, SearchResult
    _website_available = True
except ImportError as e:
    import warnings
    warnings.warn(f"GraphRAG website system unavailable: {e}", ImportWarning)
    WebsiteGraphRAGSystem = None
    SearchResult = None
    _website_available = False

try:
    from .adapter import GraphRAGAdapter, create_graphrag_adapter_from_dataset
    _adapter_available = True
except ImportError as e:
    import warnings
    warnings.warn(f"GraphRAG adapter unavailable: {e}", ImportWarning)
    GraphRAGAdapter = None
    create_graphrag_adapter_from_dataset = None
    _adapter_available = False

__all__ = [
    'UnifiedGraphRAGProcessor',
    'GraphRAGConfiguration',
    'GraphRAGIntegration',
    'HybridVectorGraphSearch',
    'GraphRAGFactory',
    'WebsiteGraphRAGSystem',
    'SearchResult',
    'GraphRAGAdapter',
    'create_graphrag_adapter_from_dataset',
]
