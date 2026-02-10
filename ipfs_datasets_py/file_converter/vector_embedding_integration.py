"""Legacy shim module (deprecated).

Deprecated import path:
  ipfs_datasets_py.file_converter.vector_embedding_integration

Canonical import path:
  ipfs_datasets_py.processors.file_converter.vector_embedding_integration
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.file_converter.vector_embedding_integration is deprecated; use ipfs_datasets_py.processors.file_converter.vector_embedding_integration instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.processors.file_converter.vector_embedding_integration import *  # noqa: F403

__all__ = [name for name in globals().keys() if not name.startswith("_")]
