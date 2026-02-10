"""Compatibility wrapper for the legacy `ipfs_datasets_py.logic_tools` package.

Deprecated: import from `ipfs_datasets_py.logic.*` instead.
"""

from __future__ import annotations

import warnings

from ipfs_datasets_py.logic.fol import convert_text_to_fol
from ipfs_datasets_py.logic.deontic import convert_legal_text_to_deontic

warnings.warn(
    "ipfs_datasets_py.logic_tools is deprecated; use ipfs_datasets_py.logic.* instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["convert_text_to_fol", "convert_legal_text_to_deontic"]
