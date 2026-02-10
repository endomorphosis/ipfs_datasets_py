"""
Deprecation utilities for file_converter module.

This module provides utilities for marking backends and features as deprecated
while maintaining backward compatibility.
"""

import warnings
from functools import wraps
from typing import Optional, Callable, Any


class FileConverterDeprecationWarning(UserWarning):
    """Custom warning for deprecated file converter features."""
    pass


def deprecated(
    reason: str,
    alternative: Optional[str] = None,
    removal_version: Optional[str] = None,
    category: type = FileConverterDeprecationWarning
) -> Callable:
    """
    Decorator to mark functions/classes as deprecated.
    
    Args:
        reason: Explanation of why it's deprecated
        alternative: Suggested alternative to use
        removal_version: Version when it will be removed
        category: Warning category to use
    
    Returns:
        Decorator function
    
    Example:
        @deprecated(
            reason="Use NativeBackend instead",
            alternative="FileConverter(backend='native')",
            removal_version="0.5.0"
        )
        def old_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            message = f"{func.__name__} is deprecated. {reason}"
            
            if alternative:
                message += f"\nUse {alternative} instead."
            
            if removal_version:
                message += f"\nWill be removed in version {removal_version}."
            
            warnings.warn(message, category=category, stacklevel=2)
            return func(*args, **kwargs)
        
        # Mark as deprecated
        wrapper.__deprecated__ = True
        wrapper.__deprecation_reason__ = reason
        wrapper.__deprecation_alternative__ = alternative
        wrapper.__deprecation_removal_version__ = removal_version
        
        return wrapper
    return decorator


def warn_deprecated_backend(backend_name: str, alternative: str = "native") -> None:
    """
    Issue a deprecation warning for a backend.
    
    Args:
        backend_name: Name of the deprecated backend
        alternative: Name of the alternative backend
    """
    message = (
        f"The '{backend_name}' backend is deprecated and will be removed in version 0.5.0.\n"
        f"Please migrate to the '{alternative}' backend which provides:\n"
        f"  • Native implementation (no external dependencies)\n"
        f"  • Better performance and reliability\n"
        f"  • Full feature parity\n"
        f"  • IPFS and ML acceleration support\n\n"
        f"Migration: FileConverter(backend='{alternative}')\n"
        f"Documentation: See docs/FILE_CONVERSION_INTEGRATION_PLAN.md"
    )
    warnings.warn(message, FileConverterDeprecationWarning, stacklevel=3)


def check_deprecated_import(module_name: str) -> None:
    """
    Warn when a deprecated module is imported.
    
    Args:
        module_name: Name of the deprecated module
    """
    message = (
        f"Importing from {module_name} is deprecated.\n"
        f"This module will be removed in version 0.5.0.\n"
        f"Please update your imports to use the native implementation."
    )
    warnings.warn(message, FileConverterDeprecationWarning, stacklevel=3)


# Deprecation timeline
DEPRECATION_TIMELINE = {
    "markitdown_backend": {
        "deprecated_in": "0.3.0",
        "removal_in": "0.5.0",
        "alternative": "native",
        "reason": "Native implementation provides better performance and zero dependencies"
    },
    "omni_backend": {
        "deprecated_in": "0.3.0",
        "removal_in": "0.5.0",
        "alternative": "native",
        "reason": "Native implementation provides better performance and zero dependencies"
    }
}


def get_deprecation_info(feature: str) -> Optional[dict]:
    """
    Get deprecation information for a feature.
    
    Args:
        feature: Name of the feature
    
    Returns:
        Dictionary with deprecation info, or None if not deprecated
    """
    return DEPRECATION_TIMELINE.get(feature)


def is_deprecated(feature: str) -> bool:
    """
    Check if a feature is deprecated.
    
    Args:
        feature: Name of the feature
    
    Returns:
        True if deprecated, False otherwise
    """
    return feature in DEPRECATION_TIMELINE
