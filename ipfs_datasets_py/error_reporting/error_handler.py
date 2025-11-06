"""
Error handler for automatic error reporting.
"""
import functools
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .config import ErrorReportingConfig
from .issue_creator import GitHubIssueCreator


logger = logging.getLogger(__name__)


class ErrorHandler:
    """Global error handler for automatic reporting."""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        """Singleton pattern to ensure only one error handler."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config: Optional[ErrorReportingConfig] = None):
        """
        Initialize error handler.
        
        Args:
            config: Error reporting configuration
        """
        # Only initialize once
        if hasattr(self, '_initialized'):
            return
        
        self.config = config or ErrorReportingConfig()
        self.issue_creator = GitHubIssueCreator(self.config)
        self._initialized = True
        self._original_excepthook = None
    
    def report_error(
        self,
        error: Exception,
        source: str = "Unknown",
        additional_info: Optional[str] = None,
        logs: Optional[str] = None,
    ) -> Optional[str]:
        """
        Report an error to GitHub.
        
        Args:
            error: The exception to report
            source: Source of the error (e.g., "MCP Server", "Dashboard JS", "Docker Container")
            additional_info: Additional information about the error
            logs: Recent log output to include
            
        Returns:
            URL of created issue, or None if not created
        """
        context = {
            'source': source,
            'additional_info': additional_info,
        }
        
        # Add logs if provided
        if logs:
            # Limit log size
            log_lines = logs.split('\n')
            if len(log_lines) > self.config.max_log_lines:
                log_lines = log_lines[-self.config.max_log_lines:]
                logs = '\n'.join(['...', *log_lines])
            context['logs'] = logs
        
        return self.issue_creator.create_issue(error, context)
    
    def install_global_handler(self):
        """Install global exception handler for uncaught exceptions."""
        if self._original_excepthook is not None:
            logger.warning("Global exception handler already installed")
            return
        
        self._original_excepthook = sys.excepthook
        
        def custom_excepthook(exc_type, exc_value, exc_traceback):
            """Custom exception hook that reports to GitHub."""
            # Call original hook first
            self._original_excepthook(exc_type, exc_value, exc_traceback)
            
            # Report to GitHub if enabled
            if self.config.enabled:
                try:
                    self.report_error(
                        exc_value,
                        source="Python Interpreter (Uncaught Exception)",
                    )
                except Exception as e:
                    logger.error(f"Failed to report error to GitHub: {e}")
        
        sys.excepthook = custom_excepthook
        logger.info("Global exception handler installed")
    
    def uninstall_global_handler(self):
        """Uninstall global exception handler."""
        if self._original_excepthook is not None:
            sys.excepthook = self._original_excepthook
            self._original_excepthook = None
            logger.info("Global exception handler uninstalled")
    
    def wrap_function(self, source: str):
        """
        Decorator to wrap a function with error reporting.
        
        Args:
            source: Source identifier for the function
            
        Example:
            @error_reporter.wrap_function("MCP Tool: dataset_load")
            def load_dataset(name):
                # ... function code ...
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    # Report error
                    if self.config.enabled:
                        try:
                            self.report_error(e, source=source)
                        except Exception as report_error:
                            logger.error(f"Failed to report error: {report_error}")
                    # Re-raise the original exception
                    raise
            
            return wrapper
        return decorator
    
    def context_manager(self, source: str):
        """
        Context manager for error reporting.
        
        Args:
            source: Source identifier for the context
            
        Example:
            with error_reporter.context_manager("Data Processing"):
                # ... code that might raise errors ...
        """
        class ErrorReportingContext:
            def __init__(self, handler, source):
                self.handler = handler
                self.source = source
            
            def __enter__(self):
                return self
            
            def __exit__(self, exc_type, exc_value, exc_traceback):
                if exc_value is not None and self.handler.config.enabled:
                    try:
                        self.handler.report_error(exc_value, source=self.source)
                    except Exception as e:
                        logger.error(f"Failed to report error: {e}")
                # Don't suppress the exception
                return False
        
        return ErrorReportingContext(self, source)


# Global error reporter instance
error_reporter = ErrorHandler()


def get_recent_logs(log_file: Optional[Path] = None, max_lines: int = 100) -> Optional[str]:
    """
    Get recent log lines from a log file.
    
    Args:
        log_file: Path to log file. If None, tries to find MCP server log.
        max_lines: Maximum number of log lines to return
        
    Returns:
        Recent log content, or None if not available
    """
    if log_file is None:
        # Try to find MCP server log
        possible_logs = [
            Path(__file__).parent.parent / 'mcp_server' / 'mcp_server.log',
            Path.home() / '.ipfs_datasets' / 'mcp_server.log',
        ]
        
        for log_path in possible_logs:
            if log_path.exists():
                log_file = log_path
                break
    
    if log_file is None or not log_file.exists():
        return None
    
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
            # Get last N lines
            recent_lines = lines[-max_lines:] if len(lines) > max_lines else lines
            return ''.join(recent_lines)
    except Exception as e:
        logger.warning(f"Failed to read log file: {e}")
        return None
