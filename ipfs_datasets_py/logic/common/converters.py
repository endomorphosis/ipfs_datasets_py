"""
Base classes for logic conversion operations.

This module provides abstract base classes and common patterns for converting
between different logic representations (natural language, formal logic, theorem
prover formats, etc.).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Generic, TypeVar
from enum import Enum

from .errors import ConversionError, ValidationError
from .bounded_cache import BoundedCache

# Type variables for generic converter
InputType = TypeVar('InputType')
OutputType = TypeVar('OutputType')


class ConversionStatus(Enum):
    """Status of a conversion operation."""
    SUCCESS = "success"
    PARTIAL = "partial"  # Conversion succeeded with warnings
    FAILED = "failed"
    CACHED = "cached"  # Result from cache


@dataclass
class ConversionResult(Generic[OutputType]):
    """
    Result of a logic conversion operation.
    
    This standardized result format is used across all converters to provide
    consistent error handling, metadata, and caching support.
    """
    output: Optional[OutputType] = None
    status: ConversionStatus = ConversionStatus.FAILED
    confidence: float = 1.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def success(self) -> bool:
        """Check if conversion was successful (including partial success)."""
        return self.status in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL, ConversionStatus.CACHED)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "output": str(self.output) if self.output is not None else None,
            "status": self.status.value,
            "confidence": self.confidence,
            "success": self.success,
            "errors": self.errors,
            "warnings": self.warnings,
            "metadata": self.metadata
        }
    
    def add_error(self, error: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Add an error message to the result."""
        self.errors.append(error)
        if context:
            self.metadata.setdefault("error_contexts", []).append(context)
        self.status = ConversionStatus.FAILED
    
    def add_warning(self, warning: str) -> None:
        """Add a warning message to the result."""
        self.warnings.append(warning)
        if self.status == ConversionStatus.SUCCESS:
            self.status = ConversionStatus.PARTIAL


@dataclass
class ValidationResult:
    """Result of input validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_error(self, error: str) -> None:
        """Add a validation error."""
        self.errors.append(error)
        self.valid = False
    
    def add_warning(self, warning: str) -> None:
        """Add a validation warning."""
        self.warnings.append(warning)


class LogicConverter(ABC, Generic[InputType, OutputType]):
    """
    Abstract base class for logic converters.
    
    This class defines the standard interface for all logic conversion operations
    in the system. Subclasses should implement the core conversion logic while
    inheriting common functionality like caching, validation, and error handling.
    
    Type Parameters:
        InputType: The type of input to convert (e.g., str, DeonticFormula, KnowledgeGraph)
        OutputType: The type of output produced (e.g., str, TDFOLFormula, SMTFormula)
    
    Example:
        ```python
        class NaturalLanguageToFOLConverter(LogicConverter[str, FOLFormula]):
            def validate_input(self, text: str) -> ValidationResult:
                result = ValidationResult(valid=True)
                if not text or not text.strip():
                    result.add_error("Input text cannot be empty")
                return result
            
            def _convert_impl(self, text: str, options: Dict[str, Any]) -> FOLFormula:
                # Actual conversion logic
                return parse_to_fol(text)
        ```
    """
    
    def __init__(self, 
                 enable_caching: bool = True,
                 enable_validation: bool = True,
                 cache_maxsize: int = 1000,
                 cache_ttl: float = 3600) -> None:
        """
        Initialize the converter.
        
        Args:
            enable_caching: Whether to cache conversion results
            enable_validation: Whether to validate inputs before conversion
            cache_maxsize: Maximum cache size (0 = unlimited, default: 1000)
            cache_ttl: Cache TTL in seconds (0 = no expiration, default: 3600)
        """
        self.enable_caching = enable_caching
        self.enable_validation = enable_validation
        
        # Use bounded cache with TTL and LRU eviction
        if self.enable_caching:
            self._cache = BoundedCache[ConversionResult[OutputType]](
                maxsize=cache_maxsize,
                ttl=cache_ttl
            )
        else:
            self._cache = None
        
        # Legacy dict for backward compatibility (deprecated)
        self._conversion_cache: Dict[str, ConversionResult[OutputType]] = {}
    
    @abstractmethod
    def validate_input(self, input_data: InputType) -> ValidationResult:
        """
        Validate input before conversion.
        
        Args:
            input_data: The input to validate
            
        Returns:
            ValidationResult indicating if input is valid
        """
        pass
    
    @abstractmethod
    def _convert_impl(self, 
                      input_data: InputType, 
                      options: Dict[str, Any]) -> OutputType:
        """
        Implement the core conversion logic.
        
        This method should be overridden by subclasses to provide the actual
        conversion implementation. It should raise ConversionError on failure.
        
        Args:
            input_data: The input to convert
            options: Additional conversion options
            
        Returns:
            The converted output
            
        Raises:
            ConversionError: If conversion fails
        """
        pass
    
    def convert(self, 
                input_data: InputType, 
                options: Optional[Dict[str, Any]] = None,
                use_cache: bool = True) -> ConversionResult[OutputType]:
        """
        Convert input to output format.
        
        This is the main entry point for conversion. It handles validation,
        caching, error handling, and result packaging.
        
        Args:
            input_data: The input to convert
            options: Additional conversion options (default: {})
            use_cache: Whether to use cached results (default: True)
            
        Returns:
            ConversionResult with the output and metadata
        """
        options = options or {}
        result = ConversionResult[OutputType]()
        
        # Generate cache key
        cache_key = self._generate_cache_key(input_data, options)
        
        # Check cache (use bounded cache if available, fall back to legacy dict)
        if self.enable_caching and use_cache:
            if self._cache is not None:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    cached.status = ConversionStatus.CACHED
                    return cached
            elif cache_key in self._conversion_cache:
                # Legacy dict cache fallback
                cached = self._conversion_cache[cache_key]
                cached.status = ConversionStatus.CACHED
                return cached
        
        try:
            # Validate input
            if self.enable_validation:
                validation = self.validate_input(input_data)
                if not validation.valid:
                    result.status = ConversionStatus.FAILED
                    result.errors = validation.errors
                    result.warnings = validation.warnings
                    result.metadata["validation"] = validation.metadata
                    return result
                
                # Add validation warnings to result
                result.warnings.extend(validation.warnings)
            
            # Perform conversion
            output = self._convert_impl(input_data, options)
            result.output = output
            result.status = ConversionStatus.SUCCESS if not result.warnings else ConversionStatus.PARTIAL
            result.confidence = options.get("confidence", 1.0)
            
            # Cache successful result
            if self.enable_caching and result.success:
                if self._cache is not None:
                    self._cache.set(cache_key, result)
                else:
                    # Legacy dict cache fallback
                    self._conversion_cache[cache_key] = result
            
        except ConversionError as e:
            result.add_error(f"Conversion error: {str(e)}", e.context if hasattr(e, 'context') else None)
        except ValidationError as e:
            result.add_error(f"Validation error: {str(e)}", e.context if hasattr(e, 'context') else None)
        except Exception as e:
            result.add_error(f"Unexpected error during conversion: {str(e)}")
            result.metadata["exception_type"] = type(e).__name__
        
        return result
    
    def _generate_cache_key(self, input_data: InputType, options: Dict[str, Any]) -> str:
        """
        Generate a cache key for the input and options.
        
        Override this method to customize caching behavior.
        
        Args:
            input_data: The input data
            options: Conversion options
            
        Returns:
            A string cache key
        """
        input_str = str(input_data)
        options_str = str(sorted(options.items()))
        return f"{self.__class__.__name__}:{input_str}:{options_str}"
    
    def clear_cache(self) -> None:
        """Clear the conversion cache."""
        if self._cache is not None:
            self._cache.clear()
        self._conversion_cache.clear()
    
    def cleanup_expired_cache(self) -> int:
        """
        Clean up expired cache entries.
        
        Returns:
            Number of entries removed
        """
        if self._cache is not None:
            return self._cache.cleanup_expired()
        return 0
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics about cache usage.
        
        Returns:
            Dictionary with cache statistics including size, hits, misses, hit rate, etc.
        """
        if self._cache is not None:
            stats = self._cache.get_stats()
            # Backward-compat/stability: callers and tests expect `cache_size`.
            # BoundedCache reports `size`, so provide both.
            stats.setdefault("cache_size", stats.get("size", 0))
            stats["cache_enabled"] = self.enable_caching
            stats["cache_type"] = "bounded"
            return stats
        else:
            # Legacy dict cache stats
            return {
                "cache_size": len(self._conversion_cache),
                "cache_enabled": self.enable_caching,
                "cache_type": "legacy_dict"
            }


class ChainedConverter(LogicConverter[InputType, OutputType]):
    """
    A converter that chains multiple converters together.
    
    This allows for multi-step conversions, e.g., NL → FOL → TDFOL → SMT.
    
    Example:
        ```python
        converter = ChainedConverter([
            NaturalLanguageToFOLConverter(),
            FOLToTDFOLConverter(),
            TDFOLToSMTConverter()
        ])
        result = converter.convert("Alice must pay Bob")
        ```
    """
    
    def __init__(self, 
                 converters: List[LogicConverter],
                 enable_caching: bool = True,
                 enable_validation: bool = True,
                 cache_maxsize: int = 1000,
                 cache_ttl: float = 3600) -> None:
        """
        Initialize the chained converter.
        
        Args:
            converters: List of converters to chain in order
            enable_caching: Whether to cache conversion results
            enable_validation: Whether to validate inputs
            cache_maxsize: Maximum cache size
            cache_ttl: Cache TTL in seconds
        """
        super().__init__(enable_caching, enable_validation, cache_maxsize, cache_ttl)
        self.converters = converters
    
    def validate_input(self, input_data: InputType) -> ValidationResult:
        """Validate using the first converter in the chain."""
        if not self.converters:
            result = ValidationResult(valid=False)
            result.add_error("No converters in chain")
            return result
        return self.converters[0].validate_input(input_data)
    
    def _convert_impl(self, input_data: InputType, options: Dict[str, Any]) -> OutputType:
        """
        Apply converters in sequence.
        
        Args:
            input_data: The initial input
            options: Conversion options
            
        Returns:
            The final output after all conversions
            
        Raises:
            ConversionError: If any conversion in the chain fails
        """
        current_data = input_data
        
        for i, converter in enumerate(self.converters):
            result = converter.convert(current_data, options)
            
            if not result.success:
                raise ConversionError(
                    f"Conversion failed at step {i+1}/{len(self.converters)}",
                    context={
                        "step": i+1,
                        "converter": converter.__class__.__name__,
                        "errors": result.errors
                    }
                )
            
            current_data = result.output
        
        return current_data
