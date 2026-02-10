"""Compatibility wrapper for ipfs_datasets_py.logic.integration.deontic_logic_converter."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.deontic_logic_converter is deprecated; use ipfs_datasets_py.logic.integration.deontic_logic_converter.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.deontic_logic_converter import *  # noqa: F403
