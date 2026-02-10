"""Compatibility wrapper for ipfs_datasets_py.logic.integration.caselaw_bulk_processor."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.caselaw_bulk_processor is deprecated; use ipfs_datasets_py.logic.integration.caselaw_bulk_processor.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.caselaw_bulk_processor import *  # noqa: F403
