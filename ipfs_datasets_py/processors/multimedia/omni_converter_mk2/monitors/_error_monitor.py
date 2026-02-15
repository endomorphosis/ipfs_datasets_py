"""
Error handler module for the Omni-Converter.

This module provides the ErrorMonitor class for centralizing error handling and reporting.
"""
from types_ import Any, Optional, Callable, Type, Logger, Configs, Path


class ErrorMonitor:
    """
    Error handler for the Omni-Converter.

    This class centralizes error handling and reporting, providing consistent
    error management across the application.

    Attributes:
        logger: The logger to use for error logging.
        error_counters (dict[str, int]): Counters for different error types.
        error_types (set[str]): set of known error types.
        suppress_errors (bool): Whether to suppress errors.
    """

    def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
        """
        Initialize an error handler.

        Args:
            resource: A dictionary of callables, including:
                - logger: A logger instance for logging errors.
            configs: Configuration object containing settings for error handling, including:
                - processing.suppress_errors: Whether to suppress errors (default: False).
                - paths.ROOT_DIR: The program's root directory.
        """
        self.configs = configs
        self.resources = resources

        self.traceback = self.resources['traceback']
        self.datetime = self.resources['datetime']

        self._logger = self.resources["logger"]
        self._suppress_errors: bool = self.configs.processing.suppress_errors
        self._root_dir: Path = self.configs.paths.ROOT_DIR

        self._error_counters: dict[str, int] = {}
        self._error_types: set[str] = set()

    @property
    def logger(self) -> Logger:
        """Get the logger for this error handler.

        Returns:
            The logger instance.
        """
        return self._logger

    def handle_error(self, error: Exception | str, context: Optional[dict[str, Any]] = {}) -> None:
        """Handle an error.

        Args:
            error: The error to handle.
            context: Additional context for the error.

        Returns:
            None

        Raises:
            Exception: If suppress_errors is False and error is an exception.
        """
        # Log the error (this will also update counters)
        self.log_error(error, context)

        # Raise the error if not suppressing
        if not self._suppress_errors and isinstance(error, Exception):
            try:
                self.core_dump()
            finally:
                raise error

    def log_error(self, error: Exception | str, context: Optional[dict[str, Any]] = {}) -> None:
        """
        Log an error that occurred when running the pipeline.

        Args:
            error: The error to log.
            context: Additional context for the error.
        """
        # Ensure context is a dictionary
        if context is None:
            context = {}

        # Get error type and update counters
        error_type = type(error).__name__ if isinstance(error, Exception) else str(error)
        self._error_types.add(error_type)
        self._error_counters[error_type] = self._error_counters.get(error_type, 0) + 1

        # Create error message
        error_traceback = None
        error_message = ""
        match error:
            case Exception() as e:
                error_message = f"{type(e).__name__}: {str(e)}"
                error_traceback = self.traceback.format_exc()
                context["error_type"] = type(error).__name__ 
            case str() as e:
                error_message = e
                error_traceback = ""
                context["error_type"] = str(error)

        # Add traceback to context if specified.
        if error_traceback:
            context["traceback"] = error_traceback

        # Log the error
        self.logger.error(error_message, context)

    @property
    def error_statistics(self) -> dict[str, Any]:
        """Get error statistics.

        Returns:
            A dictionary of error statistics.
            - total_errors: Total number of errors handled.
            - error_types: List of unique error types encountered.
            - error_counts: Dictionary of error types and their counts.
        """
        return {
            "total_errors": sum(self._error_counters.values()),
            "error_types": list(self._error_types),
            "error_counts": self._error_counters.copy()
        }

    def core_dump(self) -> None:
        """
        Writes the error monitor's current state to a file to the logs directory.

        The file contains:
        - The total number of errors recorded.
        - A list of all error types encountered.
        - A detailed breakdown of error counts by type.

        If the error count is zero (i.e. no errors detected) when the function is run, no log will be created.

        Raises:
            Exception: If an unexpected error occurs while attempting to write to the log file.
        """
        if not self.has_errors:
            return

        date = self.datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        core_log_file = self._root_dir / "logs" / f"error_monitor_core_dump_{date}.log"

        # Ensure the logs directory exists
        core_log_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(core_log_file, "w") as f:
                f.write(
                    f"Error Monitor Core Dump\n"
                    f"========================\n"
                    f"Log created at: {date}\n"
                    f"Total Errors: {self.error_statistics['total_errors']}\n"
                    f"Error Types: {', '.join(self.error_statistics['error_types'])}\n"
                    f"Error Counts:\n"
                )
                f.writelines(f"  {etype}: {count}\n" for etype, count in self.error_statistics["error_counts"].items())
        except Exception as e:
            self.logger.error(f"Failed to write core dump to {core_log_file}: {e}")
            raise

    def reset_error_counters(self) -> None:
        """Reset error counters."""
        self._error_counters = {}
        self._error_types = set()

    def set_error_suppression(self, suppress: bool) -> None:
        """
        Set error suppression.
        
        Args:
            suppress: Whether to suppress errors.
        """
        self._suppress_errors = suppress
    
    def get_most_common_errors(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get the most common errors.

        Args:
            limit: Maximum number of errors to return.

        Returns:
            A list of dictionaries with error type and count.
        """
        # Sort error types by count (descending)
        sorted_errors = sorted(
            self._error_counters.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Return the top N errors
        return [
            {"type": error_type, "count": count}
            for error_type, count in sorted_errors[:limit]
        ]

    @property
    def has_errors(self) -> bool:
        """Check if any errors have been handled.
        
        Returns:
            True if errors have been handled, False otherwise.
        """
        return sum(self._error_counters.values()) > 0

    def get_error_count(self, error_type: Optional[Type[Exception] | str] = None) -> int:
        """Get the count of a specific error type or total errors.

        Args:
            error_type (str|Exception|None): The error type to get the count for. If None, total errors are returned.

        Returns:
            The count of the specified error type or total errors.
        """
        if error_type is None:
            return sum(self._error_counters.values())

        if isinstance(error_type, type) and issubclass(error_type, Exception):
            error_type = error_type.__name__

        count = self._error_counters.get(error_type, 0)
        return count

