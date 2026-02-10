"""Compatibility wrapper for the legacy `ipfs_datasets_py.logic_integration` package.

Deprecated: use `ipfs_datasets_py.logic.integration`.

This wrapper re-exports the public API and provides per-module shims so imports like
`ipfs_datasets_py.logic.integration.deontic_logic_core` continue to work.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic_integration is deprecated; use ipfs_datasets_py.logic.integration instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration import *  # noqa: F403
