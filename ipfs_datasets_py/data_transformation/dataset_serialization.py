"""
DEPRECATED: This module has moved to ipfs_datasets_py.data_transformation.serialization.dataset_serialization

This shim provides backward compatibility during the deprecation period.
All functionality has been moved to data_transformation/serialization/.

Migration Guide:
    OLD: from ipfs_datasets_py.data_transformation.dataset_serialization import DatasetSerializer
    NEW: from ipfs_datasets_py.data_transformation.serialization.dataset_serialization import DatasetSerializer

This shim will be removed in version 2.0.0.
"""

import warnings

# Issue deprecation warning
warnings.warn(
    "ipfs_datasets_py.data_transformation.dataset_serialization is deprecated and will be removed in version 2.0.0. "
    "Please update your imports to use ipfs_datasets_py.data_transformation.serialization.dataset_serialization instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export from new location
from ipfs_datasets_py.data_transformation.serialization.dataset_serialization import *
