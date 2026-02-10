"""Compatibility wrapper for `ipfs_datasets_py.logic.fol.text_to_fol`."""

from __future__ import annotations

import warnings

from ipfs_datasets_py.logic.fol.text_to_fol import convert_text_to_fol

warnings.warn(
    "ipfs_datasets_py.logic.fol.text_to_fol is deprecated; use ipfs_datasets_py.logic.fol.text_to_fol.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["convert_text_to_fol"]
