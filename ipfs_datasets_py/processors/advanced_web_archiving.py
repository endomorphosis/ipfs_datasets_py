"""
DEPRECATED: Advanced Web Archiving module.

This module has been deprecated and moved to processors.specialized.web_archive.

.. deprecated:: 1.10.0
   This module is deprecated. Use AdvancedWebArchiver from 
   processors.specialized.web_archive instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.advanced_web_archiving import AdvancedWebArchiver
    
    NEW:
        from ipfs_datasets_py.processors.specialized.web_archive import AdvancedWebArchiver

For more information, see:
    docs/PROCESSORS_MIGRATION_GUIDE.md
    docs/PROCESSORS_COMPREHENSIVE_PLAN_2026.md
"""

import warnings

warnings.warn(
    "processors.advanced_web_archiving is deprecated. "
    "Use processors.specialized.web_archive.AdvancedWebArchiver instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.specialized.web_archive import (
        AdvancedWebArchiver,
        ArchivingConfig,
        WebResource,
        ArchiveCollection,
    )
except ImportError as e:
    # Create stubs if import fails
    class AdvancedWebArchiver:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "AdvancedWebArchiver requires dependencies that are not installed. "
                "Please install web archiving dependencies."
            )
    
    class ArchivingConfig:
        pass
    
    class WebResource:
        pass
    
    class ArchiveCollection:
        pass

__all__ = [
    'AdvancedWebArchiver',
    'ArchivingConfig',
    'WebResource',
    'ArchiveCollection',
]
