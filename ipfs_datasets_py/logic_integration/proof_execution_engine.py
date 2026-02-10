"""Compatibility wrapper for ipfs_datasets_py.logic.integration.proof_execution_engine."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.proof_execution_engine is deprecated; use ipfs_datasets_py.logic.integration.proof_execution_engine.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.proof_execution_engine import *  # noqa: F403
