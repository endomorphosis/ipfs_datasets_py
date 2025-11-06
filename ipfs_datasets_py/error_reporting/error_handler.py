#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Error Handler Installation Module

This module provides functions to install and uninstall global error handlers
for automatic error reporting.
"""

import sys
import logging
from typing import Optional, Any, Callable

from .error_reporter import get_global_error_reporter

logger = logging.getLogger(__name__)


# Store original exception hook
_original_excepthook: Optional[Callable] = None
_error_handlers_installed = False


def _custom_excepthook(exc_type, exc_value, exc_traceback):
    """
    Custom exception hook that reports uncaught exceptions.
    
    Args:
        exc_type: Exception type
        exc_value: Exception value
        exc_traceback: Exception traceback
    """
    # Call original exception hook first
    if _original_excepthook:
        _original_excepthook(exc_type, exc_value, exc_traceback)
    
    # Skip reporting for KeyboardInterrupt
    if issubclass(exc_type, KeyboardInterrupt):
        return
    
    # Report the exception
    try:
        reporter = get_global_error_reporter()
        if reporter.enabled:
            # Create a temporary exception object for reporting
            exception = exc_value if isinstance(exc_value, Exception) else Exception(str(exc_value))
            if exc_traceback:
                exception = exception.with_traceback(exc_traceback)
            
            reporter.report_exception(exception, source="python", context={
                'uncaught': True,
                'exception_type': exc_type.__name__
            })
    except Exception as e:
        logger.error(f"Failed to report exception: {e}")


def install_error_handlers() -> bool:
    """
    Install global error handlers for automatic error reporting.
    
    This function installs:
    - sys.excepthook for uncaught Python exceptions
    
    Returns:
        True if handlers were installed successfully
    """
    global _original_excepthook, _error_handlers_installed
    
    if _error_handlers_installed:
        logger.debug("Error handlers already installed")
        return True
    
    try:
        # Install exception hook
        _original_excepthook = sys.excepthook
        sys.excepthook = _custom_excepthook
        
        _error_handlers_installed = True
        logger.info("Global error handlers installed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to install error handlers: {e}")
        return False


def uninstall_error_handlers() -> bool:
    """
    Uninstall global error handlers.
    
    Returns:
        True if handlers were uninstalled successfully
    """
    global _original_excepthook, _error_handlers_installed
    
    if not _error_handlers_installed:
        logger.debug("Error handlers not installed")
        return True
    
    try:
        # Restore original exception hook
        if _original_excepthook:
            sys.excepthook = _original_excepthook
            _original_excepthook = None
        
        _error_handlers_installed = False
        logger.info("Global error handlers uninstalled successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to uninstall error handlers: {e}")
        return False


def are_error_handlers_installed() -> bool:
    """
    Check if error handlers are currently installed.
    
    Returns:
        True if handlers are installed
    """
    return _error_handlers_installed
