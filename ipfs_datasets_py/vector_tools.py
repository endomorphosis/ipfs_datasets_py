"""Compatibility shim for vector utilities.

Some MCP server tools historically imported vector helpers from
`ipfs_datasets_py.vector_tools`. The canonical implementation currently lives
in `ipfs_datasets_py.search.vector_tools`.

This module re-exports the public symbols used by MCP tools/tests to keep
imports stable.
"""

from ipfs_datasets_py.search.vector_tools import (  # noqa: F401
    VectorSimilarityCalculator,
    VectorStore,
    create_vector_store,
)

__all__ = [
    "VectorSimilarityCalculator",
    "VectorStore",
    "create_vector_store",
]
