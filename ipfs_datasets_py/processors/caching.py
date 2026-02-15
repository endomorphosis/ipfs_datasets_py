"""
DEPRECATED: Caching module.

This module has been deprecated and moved to processors.infrastructure.caching.

.. deprecated:: 1.9.0
   This module is deprecated. Import from processors.infrastructure.caching instead.
   This file will be removed in v2.0.0 (August 2026).

Migration:
    OLD: from ipfs_datasets_py.processors.caching import CacheManager
    NEW: from ipfs_datasets_py.processors.infrastructure.caching import CacheManager

For more information, see: docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings
warnings.warn(
    "processors.caching is deprecated. Use processors.infrastructure.caching instead. "
    "This import will be removed in v2.0.0 (August 2026).",
    DeprecationWarning, stacklevel=2
)

# Re-export everything from new location
from ipfs_datasets_py.processors.infrastructure.caching import *
