"""Deterministic Legal IR knowledge-graph compiler helpers.

This namespace is intentionally dependency-light.  It complements the general
``ipfs_datasets_py.knowledge_graphs`` package with compiler primitives whose
outputs satisfy the canonical Legal IR graph contract.
"""

from .legal_roles import (
    LEGAL_ROLE_GRAPH_SCHEMA_VERSION,
    compile_legal_role_graph,
)

__all__ = [
    "LEGAL_ROLE_GRAPH_SCHEMA_VERSION",
    "compile_legal_role_graph",
]
