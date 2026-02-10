"""Compatibility shim for IPLD vector store.

The canonical implementation now lives in `ipfs_datasets_py.vector_stores.ipld`.
This module remains to preserve older imports from
`ipfs_datasets_py.data_transformation.ipld.vector_store`.
"""

from __future__ import annotations

from ipfs_datasets_py.vector_stores.ipld import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
