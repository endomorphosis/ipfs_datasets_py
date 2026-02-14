# ipfs_datasets_py/search/__init__.py
try:
    from .search_embeddings import search_embeddings
    __all__ = ['search_embeddings']
except ImportError as e:
    from .search_embeddings_mock import search_embeddings
    __all__ = ['search_embeddings']
    import warnings
    warnings.warn(f"search_embeddings using mock implementation due to missing dependencies: {e}")

# Also make the module available for patching
try:
    from . import search_embeddings as search_embeddings_module
except ImportError:
    from . import search_embeddings_mock as search_embeddings_module

# Export logic integration components
try:
    from ipfs_datasets_py.search.logic_integration import (
        LogicEnhancedRAG,
        RAGQueryResult,
        LogicAwareEntityExtractor,
        LogicalEntity,
        LogicalRelationship,
        LogicalEntityType,
        LogicAwareKnowledgeGraph,
        LogicNode,
        LogicEdge,
        TheoremAugmentedRAG
    )
    __all__.extend([
        'LogicEnhancedRAG',
        'RAGQueryResult',
        'LogicAwareEntityExtractor',
        'LogicalEntity',
        'LogicalRelationship',
        'LogicalEntityType',
        'LogicAwareKnowledgeGraph',
        'LogicNode',
        'LogicEdge',
        'TheoremAugmentedRAG'
    ])
except ImportError:
    pass

# Export graphrag integration components
try:
    from ipfs_datasets_py.search.graphrag_integration import (
        GraphRAGIntegration,
        HybridVectorGraphSearch,
        CrossDocumentReasoner,
        GraphRAGQueryEngine,
        GraphRAGFactory,
    )
    __all__.extend([
        'GraphRAGIntegration',
        'HybridVectorGraphSearch',
        'CrossDocumentReasoner',
        'GraphRAGQueryEngine',
        'GraphRAGFactory',
    ])
except ImportError:
    pass
