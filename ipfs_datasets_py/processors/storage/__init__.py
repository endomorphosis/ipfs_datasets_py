"""
Storage module for IPFS Datasets Python.

This module provides storage backends including IPLD (InterPlanetary Linked Data)
support for decentralized storage of datasets, knowledge graphs, and vector stores.

Migrated from data_transformation.ipld in v2.0.0 migration.
"""

from .ipld import (
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
