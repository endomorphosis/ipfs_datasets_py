"""Compatibility wrapper for ipfs_datasets_py.logic.integration.deontic_logic_core."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.deontic_logic_core is deprecated; use ipfs_datasets_py.logic.integration.deontic_logic_core.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.deontic_logic_core import *  # noqa: F403
