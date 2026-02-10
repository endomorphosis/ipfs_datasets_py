"""Deprecated shim for `ipfs_datasets_py.multimedia.ffmpeg_wrapper`."""

from __future__ import annotations

import warnings

warnings.warn(
    "`ipfs_datasets_py.multimedia.ffmpeg_wrapper` is deprecated; use `ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper`.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper, FFMPEG_AVAILABLE

__all__ = ["FFmpegWrapper", "FFMPEG_AVAILABLE"]
