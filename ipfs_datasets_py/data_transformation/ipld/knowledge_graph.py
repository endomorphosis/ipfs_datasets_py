"""Compatibility shim for IPLD knowledge graph.

The canonical implementation now lives in `ipfs_datasets_py.knowledge_graphs.ipld`.
This module remains to preserve older imports from
`ipfs_datasets_py.data_transformation.ipld.knowledge_graph`.
"""

from __future__ import annotations

from ipfs_datasets_py.knowledge_graphs.ipld import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
