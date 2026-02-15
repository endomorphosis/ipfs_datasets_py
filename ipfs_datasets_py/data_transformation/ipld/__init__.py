"""
DEPRECATED: This module has moved to processors.storage.ipld

This import path is deprecated and will be removed in v2.0.0 (August 2026).
Please update your imports:

OLD:
    from ipfs_datasets_py.data_transformation.ipld import IPLDStorage

NEW:
    from ipfs_datasets_py.processors.storage.ipld import IPLDStorage

For more information, see:
    docs/PROCESSORS_DATA_TRANSFORMATION_MIGRATION_GUIDE_V2.md
    docs/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md
"""

import warnings

# Import from new location
from ipfs_datasets_py.processors.storage.ipld import (
    IPLDStorage,
    create_dag_node,
    parse_dag_node,
    PBNode,
    PBLink,
    OptimizedEncoder,
    OptimizedDecoder,
    BatchProcessor,
    create_batch_processor,
    optimize_node_structure,
    IPLDVectorStore,
    SearchResult,
    IPLDKnowledgeGraph,
    Entity,
    Relationship,
    HAVE_IPLD_DAG_PB,
    HAVE_IPLD_CAR
)

# Issue deprecation warning
warnings.warn(
    "Importing from 'ipfs_datasets_py.data_transformation.ipld' is deprecated. "
    "Use 'ipfs_datasets_py.processors.storage.ipld' instead. "
    "This import path will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_DATA_TRANSFORMATION_MIGRATION_GUIDE_V2.md for details.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = [
    'IPLDStorage',
    'create_dag_node',
    'parse_dag_node',
    'PBNode',
    'PBLink',
    'OptimizedEncoder',
    'OptimizedDecoder',
    'BatchProcessor',
    'create_batch_processor',
    'optimize_node_structure',
    'IPLDVectorStore',
    'SearchResult',
    'IPLDKnowledgeGraph',
    'Entity',
    'Relationship',
    'HAVE_IPLD_DAG_PB',
    'HAVE_IPLD_CAR'
]
