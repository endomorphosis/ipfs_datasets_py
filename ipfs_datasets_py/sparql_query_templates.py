"""Backwards-compatible import shim for SPARQL query templates.

The implementation lives in :mod:`ipfs_datasets_py.knowledge_graphs.sparql_query_templates`.
This module preserves the historical import path used by tests and downstream code.
"""

from ipfs_datasets_py.knowledge_graphs.sparql_query_templates import *  # noqa: F403

# Re-exported names come from the target module.
