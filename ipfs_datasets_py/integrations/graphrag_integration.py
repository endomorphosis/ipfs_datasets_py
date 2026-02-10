"""Compatibility wrapper for ipfs_datasets_py.logic.integrations.graphrag_integration."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integrations.graphrag_integration is deprecated; use ipfs_datasets_py.logic.integrations.graphrag_integration.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integrations.graphrag_integration import *  # noqa: F403
