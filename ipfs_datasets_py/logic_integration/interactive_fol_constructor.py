"""Compatibility wrapper for ipfs_datasets_py.logic.integration.interactive_fol_constructor."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.interactive_fol_constructor is deprecated; use ipfs_datasets_py.logic.integration.interactive_fol_constructor.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.interactive_fol_constructor import *  # noqa: F403
