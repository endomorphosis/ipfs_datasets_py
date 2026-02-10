"""Compatibility wrapper for ipfs_datasets_py.logic.integration.symbolic_contracts."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.symbolic_contracts is deprecated; use ipfs_datasets_py.logic.integration.symbolic_contracts.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.symbolic_contracts import *  # noqa: F403
