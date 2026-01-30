"""
Async pipeline with monadic error handling.

Inspired by convert_to_txt_based_on_mime_type's functional approach.
Provides Result/Error types and composable pipeline stages.

Phase 2 Feature 3: Async Pipeline
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, TypeVar, Union, Callable, Optional, Any, AsyncIterator
from enum import Enum
import anyio
import inspect
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')
U = TypeVar('U')


class ErrorType(Enum):
    """Types of errors that can occur in pipeline."""
    FILE_NOT_FOUND = "file_not_found"
    FORMAT_UNSUPPORTED = "format_unsupported"
    EXTRACTION_FAILED = "extraction_failed"
    VALIDATION_FAILED = "validation_failed"
    IO_ERROR = "io_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Result(Generic[T]):
    """
    Success result with value (Right monad).
    
    Inspired by convert_to_txt's FileUnit pattern.
    Represents successful computation.
    """
    value: T
    
    def is_ok(self) -> bool:
        """Check if result is success."""
        return True
    
    def is_error(self) -> bool:
        """Check if result is error."""
        return False
    
    def map(self, func: Callable[[T], U]) -> 'Union[Result[U], Error]':
        """
        Map function over result value.
        
        Args:
            func: Function to apply to value
            
        Returns:
            Result with transformed value or Error if func raises
        """
        try:
            return Result(func(self.value))
        except Exception as e:
            logger.debug(f"Map failed: {e}")
            return Error(
                error_type=ErrorType.UNKNOWN,
                message=f"Map operation failed: {e}",
                context={'original_error': str(e)}
            )
    
    async def map_async(self, func: Callable[[T], Any]) -> 'Union[Result[U], Error]':
        """
        Map async function over result value.
        
        Args:
            func: Async function to apply
            
        Returns:
            Result with transformed value or Error if func raises
        """
        try:
            result = func(self.value)
            if inspect.iscoroutine(result) or inspect.isawaitable(result):
                result = await result
            return Result(result)
        except Exception as e:
            logger.debug(f"Async map failed: {e}")
            return Error(
                error_type=ErrorType.UNKNOWN,
                message=f"Async map operation failed: {e}",
                context={'original_error': str(e)}
            )
    
    def flat_map(self, func: Callable[[T], 'Union[Result[U], Error]']) -> 'Union[Result[U], Error]':
        """
        Bind operation for monadic chaining.
        
        Args:
            func: Function returning Result or Error
            
        Returns:
            Result from func or Error
        """
        try:
            return func(self.value)
        except Exception as e:
            logger.debug(f"Flat map failed: {e}")
            return Error(
                error_type=ErrorType.UNKNOWN,
                message=f"Flat map operation failed: {e}",
                context={'original_error': str(e)}
            )
    
    def unwrap(self) -> T:
        """Get value (safe because this is Result)."""
        return self.value
    
    def unwrap_or(self, default: T) -> T:
        """Get value or default."""
        return self.value
    
    def __repr__(self) -> str:
        return f"Result({self.value!r})"


@dataclass(frozen=True)
class Error:
    """
    Error result (Left monad).
    
    Represents failed computation with context.
    """
    error_type: ErrorType
    message: str
    context: dict = field(default_factory=dict)
    original_exception: Optional[Exception] = None
    
    def is_ok(self) -> bool:
        """Check if result is success."""
        return False
    
    def is_error(self) -> bool:
        """Check if result is error."""
        return True
    
    def map(self, func: Callable) -> 'Error':
        """Map over error (no-op, propagates error)."""
        return self
    
    async def map_async(self, func: Callable) -> 'Error':
        """Async map over error (no-op, propagates error)."""
        return self
    
    def flat_map(self, func: Callable) -> 'Error':
        """Flat map over error (no-op, propagates error)."""
        return self
    
    def unwrap(self) -> Any:
        """Raise exception (shouldn't unwrap error)."""
        raise ValueError(f"Called unwrap on Error: {self.message}")
    
    def unwrap_or(self, default: T) -> T:
        """Get default value."""
        return default
    
    def __repr__(self) -> str:
        return f"Error({self.error_type.value}: {self.message})"


# Type alias for Result or Error
Outcome = Union[Result[T], Error]


@dataclass
class FileUnit:
    """
    Represents a file in the processing pipeline.
    
    Inspired by convert_to_txt's FileUnit pattern.
    Carries file information and state through pipeline stages.
    """
    path: Path
    mime_type: Optional[str] = None
    text: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    category: Optional[str] = None
    
    @classmethod
    def from_path(cls, path: Union[str, Path]) -> 'FileUnit':
        """Create FileUnit from path."""
        return cls(path=Path(path))
    
    def with_mime_type(self, mime_type: str) -> 'FileUnit':
        """Create new FileUnit with MIME type set."""
        return FileUnit(
            path=self.path,
            mime_type=mime_type,
            text=self.text,
            metadata=self.metadata.copy(),
            category=self.category
        )
    
    def with_text(self, text: str) -> 'FileUnit':
        """Create new FileUnit with text set."""
        return FileUnit(
            path=self.path,
            mime_type=self.mime_type,
            text=text,
            metadata=self.metadata.copy(),
            category=self.category
        )
    
    def with_metadata(self, **kwargs) -> 'FileUnit':
        """Create new FileUnit with additional metadata."""
        new_metadata = self.metadata.copy()
        new_metadata.update(kwargs)
        return FileUnit(
            path=self.path,
            mime_type=self.mime_type,
            text=self.text,
            metadata=new_metadata,
            category=self.category
        )


class Pipeline:
    """
    Composable async processing pipeline.
    
    Chains operations that return Result[T] or Error.
    Provides functional, type-safe transformations.
    """
    
    def __init__(self):
        """Initialize pipeline."""
        self.stages: list[Callable] = []
        self._name = "Pipeline"
        logger.debug(f"Initialized {self._name}")
    
    def add_stage(self, func: Callable, name: Optional[str] = None) -> 'Pipeline':
        """
        Add processing stage to pipeline.
        
        Args:
            func: Function to add (should return Outcome)
            name: Optional stage name for debugging
            
        Returns:
            Self for chaining
        """
        stage_name = name or func.__name__
        logger.debug(f"Adding stage '{stage_name}' to {self._name}")
        self.stages.append((func, stage_name))
        return self
    
    async def process(self, initial: T) -> Outcome[T]:
        """
        Process value through all pipeline stages.
        
        Args:
            initial: Initial value
            
        Returns:
            Result or Error after all stages
        """
        current: Outcome = Result(initial)
        
        for i, (func, name) in enumerate(self.stages):
            if current.is_error():
                logger.debug(f"Stage {i} '{name}': Skipping (error propagated)")
                continue
            
            logger.debug(f"Stage {i} '{name}': Processing")
            
            try:
                # Handle async functions
                result = func(current.value)
                if inspect.iscoroutine(result) or inspect.isawaitable(result):
                    result = await result
                
                # Ensure result is Outcome type
                if not isinstance(result, (Result, Error)):
                    # Wrap raw values in Result
                    result = Result(result)
                
                current = result
                
            except Exception as e:
                logger.error(f"Stage {i} '{name}': Exception: {e}")
                current = Error(
                    error_type=ErrorType.UNKNOWN,
                    message=f"Stage '{name}' failed: {e}",
                    context={'stage': name, 'stage_index': i},
                    original_exception=e
                )
        
        return current
    
    def __repr__(self) -> str:
        stage_names = [name for _, name in self.stages]
        return f"Pipeline({len(self.stages)} stages: {', '.join(stage_names)})"


class StreamProcessor:
    """
    Process large files in chunks (streaming).
    
    Useful for files that don't fit in memory.
    """
    
    def __init__(self, chunk_size: int = 8192):
        """
        Initialize stream processor.
        
        Args:
            chunk_size: Size of chunks in bytes
        """
        self.chunk_size = chunk_size
        logger.debug(f"StreamProcessor initialized with chunk_size={chunk_size}")
    
    async def read_chunks(self, path: Path) -> AsyncIterator[bytes]:
        """
        Read file in chunks asynchronously.
        
        Args:
            path: File path to read
            
        Yields:
            Chunks of bytes
        """
        try:
            # Note: Python's builtin open doesn't support true async IO
            # For production, use aiofiles library
            # For now, use anyio.sleep to yield control
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(self.chunk_size)
                    if not chunk:
                        break
                    yield chunk
                    await anyio.sleep(0)  # Yield control
        except Exception as e:
            logger.error(f"Stream read error for {path}: {e}")
            raise
    
    async def process_stream(
        self,
        path: Path,
        processor: Callable[[bytes], Any]
    ) -> Outcome[list]:
        """
        Process file stream with function.
        
        Args:
            path: File path
            processor: Function to process each chunk
            
        Returns:
            Result with list of processed chunks or Error
        """
        try:
            results = []
            async for chunk in self.read_chunks(path):
                result = processor(chunk)
                if inspect.iscoroutine(result) or inspect.isawaitable(result):
                    result = await result
                results.append(result)
            
            return Result(results)
            
        except Exception as e:
            logger.error(f"Stream processing failed: {e}")
            return Error(
                error_type=ErrorType.IO_ERROR,
                message=f"Stream processing failed: {e}",
                context={'path': str(path)},
                original_exception=e
            )


# Convenience functions for creating Results/Errors

def ok(value: T) -> Result[T]:
    """Create success Result."""
    return Result(value)


def error(
    error_type: ErrorType,
    message: str,
    context: Optional[dict] = None,
    original_exception: Optional[Exception] = None
) -> Error:
    """Create Error."""
    return Error(
        error_type=error_type,
        message=message,
        context=context or {},
        original_exception=original_exception
    )


def wrap_exception(e: Exception) -> Error:
    """Wrap exception as Error."""
    return Error(
        error_type=ErrorType.UNKNOWN,
        message=str(e),
        context={},
        original_exception=e
    )


# Pipeline builder helpers

def validate_file_exists(file_unit: FileUnit) -> Outcome[FileUnit]:
    """Pipeline stage: Validate file exists."""
    if not file_unit.path.exists():
        return error(
            ErrorType.FILE_NOT_FOUND,
            f"File not found: {file_unit.path}",
            context={'path': str(file_unit.path)}
        )
    return ok(file_unit)


async def detect_format(file_unit: FileUnit) -> Outcome[FileUnit]:
    """Pipeline stage: Detect MIME type."""
    try:
        from .format_detector import detect_format as detect_mime
        mime_type = detect_mime(file_unit.path)
        if mime_type:
            return ok(file_unit.with_mime_type(mime_type))
        else:
            return error(
                ErrorType.FORMAT_UNSUPPORTED,
                f"Could not detect format for {file_unit.path}",
                context={'path': str(file_unit.path)}
            )
    except Exception as e:
        return wrap_exception(e)


async def extract_text(file_unit: FileUnit) -> Outcome[FileUnit]:
    """Pipeline stage: Extract text from file."""
    try:
        from .text_extractors import extract_text as do_extract
        
        # Try enhanced extractors first
        result = do_extract(file_unit.path)
        
        if result.success:
            return ok(
                file_unit
                .with_text(result.text)
                .with_metadata(**result.metadata)
            )
        
        # Fallback for basic text files (txt, md, etc.)
        suffix = file_unit.path.suffix.lower()
        if suffix in ['.txt', '.md', '.markdown', '.rst']:
            try:
                text = file_unit.path.read_text(encoding='utf-8', errors='ignore')
                return ok(
                    file_unit
                    .with_text(text)
                    .with_metadata(format=suffix[1:], size=file_unit.path.stat().st_size)
                )
            except Exception as e:
                return error(
                    ErrorType.IO_ERROR,
                    f"Failed to read text file: {e}",
                    context={'path': str(file_unit.path)}
                )
        
        # No extraction method available
        return error(
            ErrorType.EXTRACTION_FAILED,
            result.error or "Extraction failed",
            context={'path': str(file_unit.path)}
        )
    except Exception as e:
        return wrap_exception(e)
