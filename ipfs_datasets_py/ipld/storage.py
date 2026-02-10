"""Legacy shim for IPLD storage.

Deprecated import path:
    `ipfs_datasets_py.ipld.storage`

Canonical import path:
    `ipfs_datasets_py.data_transformation.ipld.storage`
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.ipld.storage is deprecated; use ipfs_datasets_py.data_transformation.ipld.storage instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.ipld.storage import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
