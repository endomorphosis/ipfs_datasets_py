"""Compatibility wrapper for ipfs_datasets_py.logic.integration.logic_verification."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.logic_verification is deprecated; use ipfs_datasets_py.logic.integration.logic_verification.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.logic_verification import *  # noqa: F403
