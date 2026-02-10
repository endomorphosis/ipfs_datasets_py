"""Legacy shim for IPLD knowledge graph.

Deprecated import path:
    `ipfs_datasets_py.ipld.knowledge_graph`

Canonical import path:
    `ipfs_datasets_py.knowledge_graphs.ipld`
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.ipld.knowledge_graph is deprecated; use ipfs_datasets_py.knowledge_graphs.ipld instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.knowledge_graphs.ipld import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
