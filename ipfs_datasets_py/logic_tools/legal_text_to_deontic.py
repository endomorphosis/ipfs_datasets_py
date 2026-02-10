"""Compatibility wrapper for `ipfs_datasets_py.logic.deontic.legal_text_to_deontic`."""

from __future__ import annotations

import warnings

from ipfs_datasets_py.logic.deontic.legal_text_to_deontic import convert_legal_text_to_deontic

warnings.warn(
    "ipfs_datasets_py.logic.deontic.legal_text_to_deontic is deprecated; use ipfs_datasets_py.logic.deontic.legal_text_to_deontic.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["convert_legal_text_to_deontic"]
