"""Backwards-compatible import shim for GraphRAG integration.

The implementation lives in :mod:`ipfs_datasets_py.logic.integrations.graphrag_integration`.
This module preserves the historical import path used by tests and downstream code.
"""

from ipfs_datasets_py.logic.integrations.graphrag_integration import GraphRAGIntegration  # noqa: F401

__all__ = ["GraphRAGIntegration"]
