"""Legacy shim for optimized IPLD encoding/decoding.

Deprecated import path:
    `ipfs_datasets_py.ipld.optimized_codec`

Canonical import path:
    `ipfs_datasets_py.data_transformation.ipld.optimized_codec`
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.ipld.optimized_codec is deprecated; use ipfs_datasets_py.data_transformation.ipld.optimized_codec instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.ipld.optimized_codec import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
