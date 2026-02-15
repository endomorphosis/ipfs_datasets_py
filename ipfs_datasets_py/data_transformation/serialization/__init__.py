"""
DEPRECATED: This module has moved to processors.serialization

This import path is deprecated and will be removed in v2.0.0 (August 2026).
Please update your imports:

OLD:
    from ipfs_datasets_py.data_transformation.serialization import DatasetSerializer

NEW:
    from ipfs_datasets_py.processors.serialization import DatasetSerializer

For more information, see:
    docs/PROCESSORS_DATA_TRANSFORMATION_MIGRATION_GUIDE_V2.md
    docs/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md
"""

import warnings

warnings.warn(
    "Importing from 'ipfs_datasets_py.data_transformation.serialization' is deprecated. "
    "Use 'ipfs_datasets_py.processors.serialization' instead. "
    "This import path will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_DATA_TRANSFORMATION_MIGRATION_GUIDE_V2.md for details.",
    DeprecationWarning,
    stacklevel=2
)

from ipfs_datasets_py.processors.serialization import *
