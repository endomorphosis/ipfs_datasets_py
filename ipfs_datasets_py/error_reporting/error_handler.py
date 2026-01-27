#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Error Handler Installation Module

This module provides functions to install and uninstall global error handlers
for automatic error reporting.
"""

import sys
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Any, Callable, Dict, Iterator

from .error_reporter import get_global_error_reporter
from .config import ErrorReportingConfig
from .issue_creator import GitHubIssueCreator

logger = logging.getLogger(__name__)


# Store original exception hook
_original_excepthook: Optional[Callable] = None
_error_handlers_installed = False


class ErrorHandler:
    """
    Central error handler for capturing and reporting runtime errors.

    Provides a singleton interface for error reporting, global exception
    hooks, and helper utilities to wrap functions or code blocks.
    """

    _instance: Optional["ErrorHandler"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "ErrorHandler":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        config: Optional[ErrorReportingConfig] = None,
        issue_creator: Optional[GitHubIssueCreator] = None,
    ) -> None:
        if getattr(self, "_initialized", False):
            return

        self.config = config or ErrorReportingConfig()
        self.issue_creator = issue_creator or GitHubIssueCreator(self.config)
        self._original_excepthook: Optional[Callable] = None
        self._initialized = True

    def report_error(
        self,
        error: Exception,
        *,
        source: str = "python",
        additional_info: Optional[str] = None,
        logs: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Report an error via GitHub issue creation.

        Args:
            error: Exception to report.
            source: Source identifier for the error.
            additional_info: Extra context to include in the report.
            logs: Log output to include (truncated).
            context: Additional structured context.

        Returns:
            URL of created issue or None if not created.
        """
        context_payload: Dict[str, Any] = dict(context or {})
        context_payload.setdefault("source", source)

        if additional_info:
            context_payload["additional_info"] = additional_info

        if logs:
            max_lines = self.config.max_log_lines
            log_lines = logs.splitlines()
            if len(log_lines) > max_lines:
                log_lines = log_lines[:max_lines]
                log_lines.append("...")
            context_payload["logs"] = "\n".join(log_lines)

        return self.issue_creator.create_issue(error, context_payload)

    def _handle_exception(self, exc_type: type, exc_value: BaseException, exc_traceback) -> None:
        if self._original_excepthook:
            self._original_excepthook(exc_type, exc_value, exc_traceback)

        if issubclass(exc_type, KeyboardInterrupt):
            return

        exception = exc_value if isinstance(exc_value, Exception) else Exception(str(exc_value))
        if exc_traceback:
            exception = exception.with_traceback(exc_traceback)

        try:
            self.report_error(exception, source="python", context={"uncaught": True})
        except Exception as e:
            logger.error(f"Failed to report exception: {e}")

    def install_global_handler(self) -> None:
        """Install a global exception handler for uncaught exceptions."""
        if self._original_excepthook is not None:
            return

        self._original_excepthook = sys.excepthook
        sys.excepthook = self._handle_exception

    def uninstall_global_handler(self) -> None:
        """Uninstall the global exception handler and restore the original hook."""
        if self._original_excepthook is None:
            return

        sys.excepthook = self._original_excepthook
        self._original_excepthook = None

    def wrap_function(self, source: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator that reports exceptions and re-raises them."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    self.report_error(exc, source=source)
                    raise
            return wrapper
        return decorator

    @contextmanager
    def context_manager(self, source: str) -> Iterator[None]:
        """Context manager that reports errors and re-raises them."""
        try:
            yield
        except Exception as exc:
            self.report_error(exc, source=source)
            raise


def get_recent_logs(log_file: Path, max_lines: int = 100) -> Optional[str]:
    """
    Get the most recent log lines from a log file.

    Args:
        log_file: Path to the log file.
        max_lines: Maximum number of lines to return.

    Returns:
        Recent log content or None if file is missing.
    """
    if not log_file.exists():
        return None

    try:
        content = log_file.read_text(encoding="utf-8")
    except Exception:
        return None

    lines = content.splitlines()
    if max_lines <= 0:
        return ""

    return "\n".join(lines[-max_lines:])


# Backwards-compatible alias for a global error handler instance
error_reporter = ErrorHandler()


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
