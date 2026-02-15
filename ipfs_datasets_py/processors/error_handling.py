"""
DEPRECATED: Error_handling module.

This module has been deprecated and moved to processors.infrastructure.error_handling.

.. deprecated:: 1.9.0
   This module is deprecated. Import from processors.infrastructure.error_handling instead.
   This file will be removed in v2.0.0 (August 2026).

Migration:
    OLD: from ipfs_datasets_py.processors.error_handling import *
    NEW: from ipfs_datasets_py.processors.infrastructure.error_handling import *

For more information, see: docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings
warnings.warn(
    "processors.error_handling is deprecated. Use processors.infrastructure.error_handling instead. "
    "This import will be removed in v2.0.0 (August 2026).",
    DeprecationWarning, stacklevel=2
)

# Re-export everything from new location
from ipfs_datasets_py.processors.infrastructure.error_handling import *
