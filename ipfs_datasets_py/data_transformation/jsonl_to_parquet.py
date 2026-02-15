"""
DEPRECATED: This module has moved to ipfs_datasets_py.processors.serialization.jsonl_to_parquet

This shim provides backward compatibility during the deprecation period.
All functionality has been moved to processors/serialization/.

Migration Guide:
    OLD: from ipfs_datasets_py.data_transformation.jsonl_to_parquet import JSONLToParquetConverter
    NEW: from ipfs_datasets_py.processors.serialization.jsonl_to_parquet import JSONLToParquetConverter

This shim will be removed in version 2.0.0 (August 2026).
"""

import warnings

# Issue deprecation warning
warnings.warn(
    "ipfs_datasets_py.data_transformation.jsonl_to_parquet is deprecated and will be removed in version 2.0.0. "
    "Please update your imports to use ipfs_datasets_py.processors.serialization.jsonl_to_parquet instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from new location
from ipfs_datasets_py.processors.serialization.jsonl_to_parquet import *
