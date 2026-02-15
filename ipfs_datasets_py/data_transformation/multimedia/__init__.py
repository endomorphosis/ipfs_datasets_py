"""
DEPRECATED: This module has moved to ipfs_datasets_py.processors.multimedia

This shim provides backward compatibility during the deprecation period.
All functionality has been moved to processors.multimedia.

Migration Guide:
    OLD: from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper
    NEW: from ipfs_datasets_py.processors.multimedia import FFmpegWrapper

This shim will be removed in version 2.0.0.
"""

import warnings
import sys

# Issue deprecation warning
warnings.warn(
    "ipfs_datasets_py.data_transformation.multimedia is deprecated and will be removed in version 2.0.0. "
    "Please update your imports to use ipfs_datasets_py.processors.multimedia instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from new location
try:
    from ipfs_datasets_py.processors.multimedia import *
    from ipfs_datasets_py.processors.multimedia import (
        FFmpegWrapper,
        YtDlpWrapper,
        MediaProcessor,
        MediaUtils,
        DiscordWrapper,
        EmailProcessor,
    )
except ImportError as e:
    # If new location doesn't exist yet, provide helpful error
    print(
        f"ERROR: Could not import from new location (processors.multimedia).\n"
        f"The multimedia migration may not be complete.\n"
        f"Original error: {e}",
        file=sys.stderr
    )
    raise
