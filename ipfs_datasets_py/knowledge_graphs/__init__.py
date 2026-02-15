"""Knowledge graph extraction and reasoning for IPFS Datasets Python.

This module provides tools for building, querying, and reasoning over
knowledge graphs, including cross-document lineage and SPARQL templates.

⚠️ MIGRATION NOTICE:
The legacy IPLD knowledge graph API (ipld.py) is deprecated. Please migrate to
the new Neo4j-compatible API for better features and performance.

See docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for migration instructions.

New API Quick Start:
    from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase
    
    driver = GraphDatabase.driver("ipfs://localhost:5001")
    with driver.session() as session:
        # Use Neo4j-compatible API
        pass
    driver.close()
"""

import warnings

# Compatibility imports - emit warnings
def _deprecated_import(name, new_location):
    """Helper to create deprecated import warnings."""
    warnings.warn(
        f"Importing {name} from knowledge_graphs is deprecated. "
        f"Use 'from {new_location} import {name}' instead. "
        f"See docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for details.",
        DeprecationWarning,
        stacklevel=3
    )

# Re-export new API for convenience
try:
    from .neo4j_compat import GraphDatabase, IPFSDriver, IPFSSession
    from .core import GraphEngine, QueryExecutor
    from .storage import IPLDBackend, LRUCache, Entity, Relationship
    
    __all__ = [
        # New API (recommended)
        'GraphDatabase',
        'IPFSDriver', 
        'IPFSSession',
        'GraphEngine',
        'QueryExecutor',
        'IPLDBackend',
        'LRUCache',
        'Entity',
        'Relationship',
        # Legacy modules (deprecated)
        'knowledge_graph_extraction',
        'advanced_knowledge_extractor',
        'cross_document_lineage',
        'cross_document_lineage_enhanced',
        'cross_document_reasoning',
        'finance_graphrag',
        'query_knowledge_graph',
        'sparql_query_templates',
    ]
except ImportError as e:
    # If new modules not fully available yet, just export legacy
    warnings.warn(
        f"New knowledge graphs API not fully available: {e}. "
        f"Only legacy API will be available.",
        ImportWarning
    )
    __all__ = [
        'knowledge_graph_extraction',
        'advanced_knowledge_extractor',
        'cross_document_lineage',
        'cross_document_lineage_enhanced',
        'cross_document_reasoning',
        'finance_graphrag',
        'query_knowledge_graph',
        'sparql_query_templates',
    ]
