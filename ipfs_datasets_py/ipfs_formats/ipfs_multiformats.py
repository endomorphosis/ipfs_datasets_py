"""Deprecated import surface for IPFS multiformats helpers.

Canonical implementation:
  ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats

This module exists to preserve backwards-compatible imports.
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.ipfs_formats.ipfs_multiformats is deprecated; "
    "use ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats import *  # noqa: F403

