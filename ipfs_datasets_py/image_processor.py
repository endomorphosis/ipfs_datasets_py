"""Legacy shim module (deprecated).

Deprecated import path:
  ipfs_datasets_py.file_converter.image_processor

Canonical import path:
  ipfs_datasets_py.processors.file_converter.image_processor
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.file_converter.image_processor is deprecated; use ipfs_datasets_py.processors.file_converter.image_processor instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.processors.file_converter.image_processor import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
