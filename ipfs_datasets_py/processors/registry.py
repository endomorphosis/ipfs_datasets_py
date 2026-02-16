"""
DEPRECATED: ProcessorRegistry module.

This module has been deprecated and consolidated into processors.core.registry.

.. deprecated:: 1.10.0
   This module is deprecated. Use ProcessorRegistry from 
   processors.core.registry instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.registry import ProcessorRegistry
        from ipfs_datasets_py.processors.registry import get_global_registry
    
    NEW:
        from ipfs_datasets_py.processors.core.registry import ProcessorRegistry
        from ipfs_datasets_py.processors.core.registry import get_global_registry

For more information, see:
    docs/PROCESSORS_MIGRATION_GUIDE.md
    docs/PROCESSORS_COMPREHENSIVE_PLAN_2026.md
"""

from __future__ import annotations

import warnings
import logging

# Issue deprecation warning
warnings.warn(
    "processors.registry is deprecated. "
    "Use processors.core.registry.ProcessorRegistry instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

logger = logging.getLogger(__name__)


# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.core.registry import (
        ProcessorRegistry,
        ProcessorEntry,
        get_global_registry,
    )
except ImportError as e:
    logger.error(f"Failed to import from core.registry: {e}")
    # Create stub classes if import fails
    class ProcessorEntry:
        """Stub for ProcessorEntry."""
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "ProcessorEntry requires processors.core.registry module. "
                "Please check your installation."
            )
    
    class ProcessorRegistry:
        """Stub for ProcessorRegistry."""
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "ProcessorRegistry requires processors.core.registry module. "
                "Please check your installation."
            )
    
    def get_global_registry():
        """Stub for get_global_registry."""
        raise ImportError(
            "get_global_registry requires processors.core.registry module. "
            "Please check your installation."
        )


__all__ = [
    'ProcessorRegistry',
    'ProcessorEntry',
    'get_global_registry',
]
