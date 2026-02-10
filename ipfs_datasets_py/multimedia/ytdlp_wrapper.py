"""Deprecated shim for `ipfs_datasets_py.multimedia.ytdlp_wrapper`."""

from __future__ import annotations

import warnings

warnings.warn(
    "`ipfs_datasets_py.multimedia.ytdlp_wrapper` is deprecated; use `ipfs_datasets_py.data_transformation.multimedia.ytdlp_wrapper`.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.multimedia.ytdlp_wrapper import YtDlpWrapper, YTDLP_AVAILABLE

__all__ = ["YtDlpWrapper", "YTDLP_AVAILABLE"]
