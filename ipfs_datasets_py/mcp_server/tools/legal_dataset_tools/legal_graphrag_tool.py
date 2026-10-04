"""
Legal GraphRAG Integration MCP Tool — thin shim.

Business logic lives in:
    ipfs_datasets_py.processors.legal_scrapers.legal_graphrag_engine

This file re-exports the canonical standalone functions so the MCP tool
registry discovers them at the expected module path.
"""

from ipfs_datasets_py.processors.legal_scrapers.legal_graphrag_engine import (  # noqa: F401
    create_legal_knowledge_graph,
    search_legal_graph,
    visualize_legal_graph,
)

__all__ = [
    "create_legal_knowledge_graph",
    "search_legal_graph",
    "visualize_legal_graph",
]
