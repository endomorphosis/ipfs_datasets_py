"""DEPRECATED compatibility shim.

Canonical location:
  ipfs_datasets_py.data_transformation.unixfs

This module remains to preserve older import paths.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integrations.unixfs_integration is deprecated; "
    "use ipfs_datasets_py.data_transformation.unixfs instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.unixfs import *  # noqa: F403
