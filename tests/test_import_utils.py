"""
Centralized import utility for test files to handle PyArrow and other import conflicts.

This module provides a safe import mechanism that prevents re-importing modules
that register global state (like PyArrow extension types). It follows the same
pattern as ipfs_datasets_py.mcp_server.utils._dependencies.

The SafeImporter class caches imported modules in sys.modules and reuses them
on subsequent import attempts, preventing conflicts from re-registration of
global state like PyArrow extension types.

Examples:
    >>> from tests.test_import_utils import safe_importer
    >>> 
    >>> # Try to import a module safely
    >>> ipld_module = safe_importer.import_module('ipfs_datasets_py.ipld')
    >>> if ipld_module is None:
    ...     pytest.skip("ipld module not available")
    >>> 
    >>> # Or use the decorator
    >>> @safe_importer.skip_if_unavailable('ipfs_datasets_py.pdf_processing')
    >>> def test_pdf_processing():
    ...     from ipfs_datasets_py.pdf_processing import PDFProcessor
    ...     # test code here
"""

import sys
from importlib import import_module as _import_module
from typing import Optional, Any
import functools


class SafeImporter:
    """
    Lazy loading of modules with caching to prevent re-import conflicts.
    
    This class provides safe module importing that:
    - Checks sys.modules before importing to reuse already-loaded modules
    - Prevents PyArrow extension types from being re-registered
    - Returns cached module if already imported, avoiding re-import
    - Handles ImportError and PyArrow conflicts gracefully
    
    The class maintains a cache of module paths and their import status,
    allowing tests to skip gracefully when modules are unavailable or
    when PyArrow conflicts occur.
    """
    
    def __init__(self):
        """Initialize the safe importer with an empty cache."""
        self._cache = {}
    
    def import_module(self, module_path: str) -> Optional[Any]:
        """
        Safely import a module, checking if it's already loaded to avoid
        PyArrow extension type re-registration issues.
        
        Args:
            module_path: Dotted path to the module (e.g., 'ipfs_datasets_py.ipld')
        
        Returns:
            The imported module or None if import fails
            
        Examples:
            >>> importer = SafeImporter()
            >>> module = importer.import_module('ipfs_datasets_py.ipld')
            >>> if module is None:
            ...     print("Module not available")
        """
        # Check if we've already tried to import this module
        if module_path in self._cache:
            return self._cache[module_path]
        
        # Check if module is already loaded in sys.modules
        if module_path in sys.modules:
            module = sys.modules[module_path]
            self._cache[module_path] = module
            return module
        
        try:
            module = _import_module(module_path)
            self._cache[module_path] = module
            return module
        except ImportError as e:
            # Module is not installed or has import errors
            self._cache[module_path] = None
            return None
        except Exception as e:
            # Handle PyArrow extension type registration errors and other import issues
            error_msg = str(e)
            error_type = str(type(e).__name__)
            
            if 'ArrowKeyError' in error_type or 'already defined' in error_msg:
                # PyArrow extension type conflict - this is expected in test environments
                # Return None to allow tests to skip gracefully
                self._cache[module_path] = None
                return None
            else:
                # Re-raise unexpected errors for debugging
                raise
    
    def is_available(self, module_path: str) -> bool:
        """
        Check if a module is available for import.
        
        Args:
            module_path: Dotted path to the module
            
        Returns:
            True if the module can be imported, False otherwise
            
        Examples:
            >>> importer = SafeImporter()
            >>> if importer.is_available('ipfs_datasets_py.ipld'):
            ...     from ipfs_datasets_py.ipld import IPLDStorage
        """
        module = self.import_module(module_path)
        return module is not None
    
    def skip_if_unavailable(self, module_path: str):
        """
        Decorator to skip a test if a module is unavailable.
        
        Args:
            module_path: Dotted path to the module
            
        Returns:
            Decorator function that skips the test if module is unavailable
            
        Examples:
            >>> @safe_importer.skip_if_unavailable('ipfs_datasets_py.pdf_processing')
            >>> def test_pdf_processing():
            ...     from ipfs_datasets_py.pdf_processing import PDFProcessor
            ...     assert PDFProcessor is not None
        """
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                if not self.is_available(module_path):
                    import pytest
                    pytest.skip(f"Module {module_path} not available")
                return func(*args, **kwargs)
            return wrapper
        return decorator


# Global instance for use across all test files
safe_importer = SafeImporter()
