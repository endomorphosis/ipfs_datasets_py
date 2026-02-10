"""Compatibility wrapper for ipfs_datasets_py.logic.integration.symbolic_logic_primitives."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.symbolic_logic_primitives is deprecated; use ipfs_datasets_py.logic.integration.symbolic_logic_primitives.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.symbolic_logic_primitives import *  # noqa: F403
