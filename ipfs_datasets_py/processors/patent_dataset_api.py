"""
DEPRECATED: This module has been moved to processors.domains.patent.patent_dataset_api

This file provides backward compatibility but will be removed in v2.0.0 (August 2026).

Please update your imports:
    OLD: from ipfs_datasets_py.processors.patent_dataset_api import PatentDatasetAPI
    NEW: from ipfs_datasets_py.processors.domains.patent import PatentDatasetAPI

For migration guide, see: docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.patent_dataset_api is deprecated and will be removed in v2.0.0 (August 2026). "
    "Use processors.domains.patent.patent_dataset_api instead. "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for migration guide.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from .domains.patent.patent_dataset_api import *
except ImportError as e:
    warnings.warn(f"Could not import from new location: {e}")
