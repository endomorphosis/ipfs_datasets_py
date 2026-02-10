"""Compatibility wrapper for ipfs_datasets_py.logic.integration.symbolic_fol_bridge."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.symbolic_fol_bridge is deprecated; use ipfs_datasets_py.logic.integration.symbolic_fol_bridge.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.symbolic_fol_bridge import *  # noqa: F403
