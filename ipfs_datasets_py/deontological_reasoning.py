"""Backwards-compatible import shim for deontological reasoning.

The implementation lives in :mod:`ipfs_datasets_py.logic.integration.deontological_reasoning`.
"""

from __future__ import annotations

import warnings

from ipfs_datasets_py.logic.integration.deontological_reasoning import *  # noqa: F401,F403

warnings.warn(
	"ipfs_datasets_py.deontological_reasoning is deprecated; "
	"use ipfs_datasets_py.logic.integration.deontological_reasoning instead.",
	DeprecationWarning,
	stacklevel=2,
)
