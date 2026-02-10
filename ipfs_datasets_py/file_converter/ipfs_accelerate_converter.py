"""Legacy shim module (deprecated).

Deprecated import path:
  ipfs_datasets_py.file_converter.ipfs_accelerate_converter

Canonical import path:
  ipfs_datasets_py.processors.file_converter.ipfs_accelerate_converter
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.file_converter.ipfs_accelerate_converter is deprecated; use ipfs_datasets_py.processors.file_converter.ipfs_accelerate_converter instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.processors.file_converter.ipfs_accelerate_converter import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
