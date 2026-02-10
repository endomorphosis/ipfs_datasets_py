"""Compatibility wrapper for ipfs_datasets_py.logic.integration.deontic_query_engine."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.deontic_query_engine is deprecated; use ipfs_datasets_py.logic.integration.deontic_query_engine.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.deontic_query_engine import *  # noqa: F403
