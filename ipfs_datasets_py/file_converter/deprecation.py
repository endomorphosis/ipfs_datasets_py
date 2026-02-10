"""Legacy shim module (deprecated).

Deprecated import path:
  ipfs_datasets_py.file_converter.deprecation

Canonical import path:
  ipfs_datasets_py.processors.file_converter.deprecation
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.file_converter.deprecation is deprecated; use ipfs_datasets_py.processors.file_converter.deprecation instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.processors.file_converter.deprecation import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
