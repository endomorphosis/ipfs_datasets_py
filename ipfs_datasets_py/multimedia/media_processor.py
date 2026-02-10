"""Deprecated shim for `ipfs_datasets_py.multimedia.media_processor`."""

from __future__ import annotations

import warnings

warnings.warn(
    "`ipfs_datasets_py.multimedia.media_processor` is deprecated; use `ipfs_datasets_py.data_transformation.multimedia.media_processor`.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.multimedia.media_processor import MediaProcessor, make_media_processor

__all__ = ["MediaProcessor", "make_media_processor"]
