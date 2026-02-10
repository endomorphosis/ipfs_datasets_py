"""Compatibility wrapper for ipfs_datasets_py.logic.integration.ipld_logic_storage."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.ipld_logic_storage is deprecated; use ipfs_datasets_py.logic.integration.ipld_logic_storage.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.ipld_logic_storage import *  # noqa: F403
