"""Legacy shim for IPLD vector store.

Deprecated import path:
    `ipfs_datasets_py.ipld.vector_store`

Canonical import path:
    `ipfs_datasets_py.vector_stores.ipld`
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.ipld.vector_store is deprecated; use ipfs_datasets_py.vector_stores.ipld instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.vector_stores.ipld import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
