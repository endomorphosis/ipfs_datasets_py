"""Compatibility wrapper for ipfs_datasets_py.logic.integrations.unixfs_integration."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integrations.unixfs_integration is deprecated; use ipfs_datasets_py.logic.integrations.unixfs_integration.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integrations.unixfs_integration import *  # noqa: F403
