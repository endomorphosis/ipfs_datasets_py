"""Compatibility wrapper for ipfs_datasets_py.logic.integration.prover_installer."""

from __future__ import annotations

import warnings

warnings.warn(
    "ipfs_datasets_py.logic.integration.prover_installer is deprecated; use ipfs_datasets_py.logic.integration.prover_installer.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.logic.integration.prover_installer import *  # noqa: F403
