"""Compatibility shim for the deprecated `ipfs_datasets_py.multimedia` namespace.

The canonical implementation lives under `ipfs_datasets_py.data_transformation.multimedia`.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "`ipfs_datasets_py.multimedia` is deprecated; use `ipfs_datasets_py.data_transformation.multimedia`.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.multimedia.media_processor import MediaProcessor, make_media_processor
from ipfs_datasets_py.data_transformation.multimedia.ytdlp_wrapper import YtDlpWrapper, YTDLP_AVAILABLE
from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper, FFMPEG_AVAILABLE

__all__ = [
    "MediaProcessor",
    "make_media_processor",
    "YtDlpWrapper",
    "YTDLP_AVAILABLE",
    "FFmpegWrapper",
    "FFMPEG_AVAILABLE",
]
