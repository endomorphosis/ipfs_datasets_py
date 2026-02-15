"""
DEPRECATED: This module has been moved to processors.domains.ml.classify_with_llm

This file provides backward compatibility but will be removed in v2.0.0 (August 2026).

Please update your imports:
    OLD: from ipfs_datasets_py.processors.classify_with_llm import ClassifyWithLLM
    NEW: from ipfs_datasets_py.processors.domains.ml import ClassifyWithLLM

For migration guide, see: docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.classify_with_llm is deprecated and will be removed in v2.0.0 (August 2026). "
    "Use processors.domains.ml.classify_with_llm instead. "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for migration guide.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from .domains.ml.classify_with_llm import *
except ImportError as e:
    warnings.warn(f"Could not import from new location: {e}")
