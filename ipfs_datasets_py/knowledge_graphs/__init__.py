"""Knowledge graph extraction and reasoning for IPFS Datasets Python.

This module provides tools for building, querying, and reasoning over
knowledge graphs, including cross-document lineage and SPARQL templates.
"""

# NOTE:
# Keep this package initializer lightweight.
# Some submodules have optional heavy dependencies (e.g., plotting libraries).
# Import those submodules directly where needed.

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
