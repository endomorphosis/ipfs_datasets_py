"""
DEPRECATED: This module has been moved to processors.domains.geospatial.geospatial_analysis

This file provides backward compatibility but will be removed in v2.0.0 (August 2026).

Please update your imports:
    OLD: from ipfs_datasets_py.processors.geospatial_analysis import GeospatialAnalysis
    NEW: from ipfs_datasets_py.processors.domains.geospatial import GeospatialAnalysis

For migration guide, see: docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.geospatial_analysis is deprecated and will be removed in v2.0.0 (August 2026). "
    "Use processors.domains.geospatial.geospatial_analysis instead. "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for migration guide.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from .domains.geospatial.geospatial_analysis import *
except ImportError as e:
    warnings.warn(f"Could not import from new location: {e}")
