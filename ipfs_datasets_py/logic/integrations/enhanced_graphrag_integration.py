"""DEPRECATED compatibility shim.

Canonical location:
  ipfs_datasets_py.processors.graphrag.enhanced_integration

This module remains to preserve older import paths.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integrations.enhanced_graphrag_integration is deprecated; "
    "use ipfs_datasets_py.processors.graphrag.enhanced_integration instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.processors.graphrag.enhanced_integration import *  # noqa: F403
