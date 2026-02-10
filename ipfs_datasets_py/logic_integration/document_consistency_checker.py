"""Compatibility wrapper for ipfs_datasets_py.logic.integration.document_consistency_checker."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.document_consistency_checker is deprecated; use ipfs_datasets_py.logic.integration.document_consistency_checker.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.document_consistency_checker import *  # noqa: F403
