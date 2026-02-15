"""
DEPRECATED: PDF Processing module.

This module has been deprecated and moved to processors.specialized.pdf.

.. deprecated:: 1.9.0
   This module is deprecated. Use processors.specialized.pdf instead. 
   This file will be removed in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.pdf_processing import ...
    
    NEW:
        from ipfs_datasets_py.processors.specialized.pdf import ...

For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.pdf_processing is deprecated. "
    "Use processors.specialized.pdf instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.specialized.pdf.pdf_processing import *
except ImportError:
    # If specialized.pdf is not available, pass
    pass

__all__ = []
