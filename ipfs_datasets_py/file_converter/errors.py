"""Legacy shim module (deprecated).

Deprecated import path:
  ipfs_datasets_py.file_converter.errors

Canonical import path:
  ipfs_datasets_py.processors.file_converter.errors
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.file_converter.errors is deprecated; use ipfs_datasets_py.processors.file_converter.errors instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.processors.file_converter.errors import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
