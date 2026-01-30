"""
Error handling module for file conversion.

This module provides a unified error handling system inspired by both
omni_converter_mk2 and convert_to_txt_based_on_mime_type, combining:
- Clear error type hierarchy
- Automatic fallback strategies
- Error recovery patterns
- Structured logging integration

Example:
    >>> from ipfs_datasets_py.file_converter.errors import FileConversionError, ErrorType
    >>> try:
    ...     result = extract_text("file.pdf")
    ... except FileConversionError as e:
    ...     print(f"Error: {e.message}")
    ...     print(f"Suggested fix: {e.suggested_fix}")
"""

from enum import Enum
from typing import Optional, Dict, Any, Callable, List, TypeVar, Awaitable
from dataclasses import dataclass, field
import logging
import asyncio
import time
from pathlib import Path

T = TypeVar('T')


class ErrorType(Enum):
    """Categorized error types for file conversion operations."""
    
    # File-related errors
    FILE_NOT_FOUND = "file_not_found"
    FILE_READ_ERROR = "file_read_error"
    FILE_WRITE_ERROR = "file_write_error"
    FILE_PERMISSION_ERROR = "file_permission_error"
    
    # Format-related errors
    UNSUPPORTED_FORMAT = "unsupported_format"
    FORMAT_DETECTION_FAILED = "format_detection_failed"
    INVALID_FILE_FORMAT = "invalid_file_format"
    
    # Extraction errors
    EXTRACTION_FAILED = "extraction_failed"
    EXTRACTION_LIBRARY_MISSING = "extraction_library_missing"
    EXTRACTION_TIMEOUT = "extraction_timeout"
    
    # Network errors
    NETWORK_ERROR = "network_error"
    DOWNLOAD_FAILED = "download_failed"
    
    # System errors
    MEMORY_ERROR = "memory_error"
    SYSTEM_ERROR = "system_error"
    UNKNOWN_ERROR = "unknown_error"
    
    # Validation errors
    VALIDATION_FAILED = "validation_failed"
    
    def get_category(self) -> str:
        """Get the category of this error type."""
        if self.value.startswith('file_'):
            return 'file'
        elif self.value.startswith('format_') or self.value in ['unsupported_format', 'invalid_file_format']:
            return 'format'
        elif self.value.startswith('extraction_'):
            return 'extraction'
        elif self.value.startswith('network_') or self.value == 'download_failed':
            return 'network'
        elif self.value in ['memory_error', 'system_error', 'unknown_error']:
            return 'system'
        elif self.value == 'validation_failed':
            return 'validation'
        return 'unknown'
    
    def get_suggested_fix(self) -> str:
        """Get a suggested fix for this error type."""
        fixes = {
            ErrorType.FILE_NOT_FOUND: "Check if the file path is correct and the file exists",
            ErrorType.FILE_READ_ERROR: "Ensure you have read permissions for the file",
            ErrorType.FILE_WRITE_ERROR: "Ensure you have write permissions for the destination",
            ErrorType.FILE_PERMISSION_ERROR: "Check file permissions and try running with appropriate access",
            ErrorType.UNSUPPORTED_FORMAT: "This file format is not supported. Check supported formats list",
            ErrorType.FORMAT_DETECTION_FAILED: "Unable to detect file format. Try specifying it explicitly",
            ErrorType.INVALID_FILE_FORMAT: "The file appears to be corrupted or in an invalid format",
            ErrorType.EXTRACTION_FAILED: "Extraction failed. Try using a different backend or check file integrity",
            ErrorType.EXTRACTION_LIBRARY_MISSING: "Install required library (see error message for details)",
            ErrorType.EXTRACTION_TIMEOUT: "File processing timed out. Try increasing timeout or splitting the file",
            ErrorType.NETWORK_ERROR: "Check your internet connection and try again",
            ErrorType.DOWNLOAD_FAILED: "Failed to download file. Check URL and network connection",
            ErrorType.MEMORY_ERROR: "Not enough memory. Try processing smaller files or increasing available memory",
            ErrorType.SYSTEM_ERROR: "A system error occurred. Check system logs for details",
            ErrorType.UNKNOWN_ERROR: "An unknown error occurred. Enable debug logging for more details",
            ErrorType.VALIDATION_FAILED: "Input validation failed. Check the input data and try again",
        }
        return fixes.get(self, "No specific fix available")


class FileConversionError(Exception):
    """Base exception for file conversion errors."""
    
    def __init__(
        self,
        message: str,
        error_type: ErrorType = ErrorType.UNKNOWN_ERROR,
        original_exception: Optional[Exception] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize FileConversionError.
        
        Args:
            message: Error message
            error_type: Type of error
            original_exception: Original exception that caused this error
            context: Additional context information
        """
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.original_exception = original_exception
        self.context = context or {}
        self.suggested_fix = error_type.get_suggested_fix()
    
    def __str__(self) -> str:
        """String representation."""
        parts = [f"[{self.error_type.value}] {self.message}"]
        if self.original_exception:
            parts.append(f"Caused by: {str(self.original_exception)}")
        if self.context:
            parts.append(f"Context: {self.context}")
        return " | ".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for structured logging."""
        return {
            'error_type': self.error_type.value,
            'message': self.message,
            'category': self.error_type.get_category(),
            'suggested_fix': self.suggested_fix,
            'context': self.context,
            'original_exception': str(self.original_exception) if self.original_exception else None
        }


@dataclass
class FallbackStrategy:
    """
    Defines a fallback strategy for error recovery.
    
    Example:
        >>> def fallback_handler(context):
        ...     return extract_with_pypdf2(context['file_path'])
        >>> 
        >>> strategy = FallbackStrategy(
        ...     error_types=[ErrorType.EXTRACTION_FAILED],
        ...     handler=fallback_handler,
        ...     description="Fall back to PyPDF2"
        ... )
    """
    
    error_types: List[ErrorType]
    handler: Callable[[Dict[str, Any]], Awaitable[Any]]
    description: str
    max_retries: int = 1
    success_count: int = field(default=0, init=False)
    failure_count: int = field(default=0, init=False)
    
    async def execute(
        self,
        primary_func: Callable[[], Awaitable[Any]],
        context: Dict[str, Any]
    ) -> Any:
        """
        Execute primary function with fallback on specific errors.
        
        Args:
            primary_func: Primary function to execute
            context: Context information for fallback handler
            
        Returns:
            Result from primary function or fallback handler
            
        Raises:
            FileConversionError: If both primary and fallback fail
        """
        try:
            result = await primary_func()
            return result
        except FileConversionError as e:
            if e.error_type in self.error_types:
                logging.info(f"Primary method failed: {e.message}. Trying fallback: {self.description}")
                try:
                    result = await self.handler(context)
                    self.success_count += 1
                    logging.info(f"Fallback succeeded: {self.description}")
                    return result
                except Exception as fallback_error:
                    self.failure_count += 1
                    logging.error(f"Fallback also failed: {fallback_error}")
                    raise FileConversionError(
                        f"Both primary and fallback methods failed. Primary: {e.message}, Fallback: {str(fallback_error)}",
                        error_type=e.error_type,
                        original_exception=fallback_error,
                        context={'primary_error': str(e), 'fallback_error': str(fallback_error)}
                    )
            else:
                raise


class ErrorHandler:
    """
    Central error handler with multiple fallback strategies.
    
    Example:
        >>> handler = ErrorHandler()
        >>> handler.register_strategy(pdf_fallback_strategy)
        >>> handler.register_strategy(docx_fallback_strategy)
        >>> result = await handler.handle_error(error_type, context, error)
    """
    
    def __init__(self):
        """Initialize error handler."""
        self.strategies: Dict[ErrorType, List[FallbackStrategy]] = {}
        self.logger = logging.getLogger(__name__)
    
    def register_strategy(self, strategy: FallbackStrategy) -> None:
        """Register a fallback strategy."""
        for error_type in strategy.error_types:
            if error_type not in self.strategies:
                self.strategies[error_type] = []
            self.strategies[error_type].append(strategy)
            self.logger.info(f"Registered fallback strategy for {error_type.value}: {strategy.description}")
    
    async def handle_error(
        self,
        error_type: ErrorType,
        context: Dict[str, Any],
        primary_error: Optional[Exception] = None
    ) -> Any:
        """
        Handle an error using registered strategies.
        
        Args:
            error_type: Type of error that occurred
            context: Context information
            primary_error: Original error
            
        Returns:
            Result from successful fallback strategy
            
        Raises:
            FileConversionError: If no strategy succeeds
        """
        if error_type not in self.strategies:
            raise FileConversionError(
                f"No fallback strategy registered for {error_type.value}",
                error_type=error_type,
                original_exception=primary_error,
                context=context
            )
        
        strategies = self.strategies[error_type]
        last_error = primary_error
        
        for strategy in strategies:
            try:
                self.logger.info(f"Trying fallback strategy: {strategy.description}")
                result = await strategy.handler(context)
                strategy.success_count += 1
                self.logger.info(f"Fallback strategy succeeded: {strategy.description}")
                return result
            except Exception as e:
                strategy.failure_count += 1
                self.logger.warning(f"Fallback strategy failed: {strategy.description} - {e}")
                last_error = e
        
        raise FileConversionError(
            f"All fallback strategies failed for {error_type.value}",
            error_type=error_type,
            original_exception=last_error,
            context=context
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about fallback usage."""
        stats = {}
        for error_type, strategies in self.strategies.items():
            stats[error_type.value] = [
                {
                    'description': strategy.description,
                    'success_count': strategy.success_count,
                    'failure_count': strategy.failure_count,
                    'success_rate': (
                        strategy.success_count / (strategy.success_count + strategy.failure_count)
                        if (strategy.success_count + strategy.failure_count) > 0
                        else 0
                    )
                }
                for strategy in strategies
            ]
        return stats


# Error recovery utilities

async def with_fallback(
    primary: Callable[[], Awaitable[T]],
    fallback: Callable[[], Awaitable[T]],
    error_types: Optional[List[ErrorType]] = None
) -> T:
    """
    Execute primary function with fallback on specific errors.
    
    Args:
        primary: Primary function to execute
        fallback: Fallback function to execute on error
        error_types: Error types to trigger fallback (None = all errors)
        
    Returns:
        Result from primary or fallback function
        
    Example:
        >>> result = await with_fallback(
        ...     primary=lambda: extract_with_pdfplumber(path),
        ...     fallback=lambda: extract_with_pypdf2(path),
        ...     error_types=[ErrorType.EXTRACTION_FAILED]
        ... )
    """
    try:
        return await primary()
    except FileConversionError as e:
        if error_types is None or e.error_type in error_types:
            logging.info(f"Primary method failed ({e.error_type.value}), trying fallback")
            try:
                result = await fallback()
                logging.info("Fallback succeeded")
                return result
            except Exception as fallback_error:
                logging.error(f"Fallback also failed: {fallback_error}")
                raise FileConversionError(
                    f"Both primary and fallback failed. Primary: {e.message}",
                    error_type=e.error_type,
                    original_exception=fallback_error
                )
        else:
            raise


async def retry_with_backoff(
    func: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    error_types: Optional[List[ErrorType]] = None
) -> T:
    """
    Retry a function with exponential backoff.
    
    Args:
        func: Function to execute
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        backoff_factor: Multiplier for each retry
        error_types: Error types to retry (None = all errors)
        
    Returns:
        Result from function
        
    Example:
        >>> result = await retry_with_backoff(
        ...     func=lambda: download_file(url),
        ...     max_retries=3,
        ...     initial_delay=1.0
        ... )
    """
    delay = initial_delay
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except FileConversionError as e:
            last_error = e
            if error_types and e.error_type not in error_types:
                raise
            
            if attempt < max_retries:
                logging.info(f"Attempt {attempt + 1} failed: {e.message}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                logging.error(f"All {max_retries + 1} attempts failed")
                raise FileConversionError(
                    f"Failed after {max_retries + 1} attempts: {e.message}",
                    error_type=e.error_type,
                    original_exception=last_error
                )
    
    raise FileConversionError(
        f"Failed after {max_retries + 1} attempts",
        error_type=ErrorType.UNKNOWN_ERROR,
        original_exception=last_error
    )


async def ignore_errors(
    func: Callable[[], Awaitable[T]],
    error_types: List[ErrorType],
    default: Optional[T] = None
) -> Optional[T]:
    """
    Execute function and ignore specific errors, returning default value.
    
    Args:
        func: Function to execute
        error_types: Error types to ignore
        default: Default value to return on error
        
    Returns:
        Result from function or default value
        
    Example:
        >>> result = await ignore_errors(
        ...     func=lambda: extract_metadata(file),
        ...     error_types=[ErrorType.EXTRACTION_FAILED],
        ...     default={}
        ... )
    """
    try:
        return await func()
    except FileConversionError as e:
        if e.error_type in error_types:
            logging.debug(f"Ignoring error: {e.message}")
            return default
        raise


async def aggregate_errors(
    funcs: List[Callable[[], Awaitable[T]]],
    continue_on_error: bool = True
) -> tuple[List[T], List[FileConversionError]]:
    """
    Execute multiple functions and aggregate errors.
    
    Args:
        funcs: List of functions to execute
        continue_on_error: Whether to continue after errors
        
    Returns:
        Tuple of (results, errors)
        
    Example:
        >>> results, errors = await aggregate_errors([
        ...     lambda: convert_file('file1.pdf'),
        ...     lambda: convert_file('file2.pdf'),
        ...     lambda: convert_file('file3.pdf')
        ... ])
    """
    results = []
    errors = []
    
    for func in funcs:
        try:
            result = await func()
            results.append(result)
        except FileConversionError as e:
            errors.append(e)
            if not continue_on_error:
                break
    
    return results, errors
