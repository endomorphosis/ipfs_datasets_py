"""Compatibility wrapper for the legacy `ipfs_datasets_py.integrations` package.

Deprecated: use `ipfs_datasets_py.logic.integrations`.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.integrations is deprecated; use ipfs_datasets_py.logic.integrations instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integrations.graphrag_integration import *  # noqa: F403
from ipfs_datasets_py.logic.integrations.enhanced_graphrag_integration import *  # noqa: F403
from ipfs_datasets_py.logic.integrations.phase7_complete_integration import *  # noqa: F403
from ipfs_datasets_py.logic.integrations.unixfs_integration import *  # noqa: F403

__all__ = [
    "graphrag_integration",
    "enhanced_graphrag_integration",
    "phase7_complete_integration",
    "unixfs_integration",
]
