"""
Base Parser Interface for CEC Multi-Language Support.

This module defines the abstract base class for language-specific parsers,
providing a common interface for parsing natural language into DCEC formulas.

Classes:
    ParseResult: Container for parsing results with metadata
    BaseParser: Abstract base class for language-specific parsers

Usage:
    >>> from ipfs_datasets_py.logic.CEC.nl.base_parser import BaseParser
    >>> from ipfs_datasets_py.logic.CEC.nl.language_detector import Language
    >>>
    >>> class MyParser(BaseParser):
    ...     def parse_impl(self, text: str) -> ParseResult:
    ...         # Implement parsing logic
    ...         pass
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from ..native.types import Formula


@dataclass
class ParseResult:
    """
    Result of natural language parsing.
    
    Attributes:
        formula: Parsed DCEC formula (None if parsing failed)
        confidence: Confidence score (0.0-1.0)
        success: Whether parsing was successful
        errors: List of error messages
        warnings: List of warning messages
        metadata: Additional parsing metadata
        
    Example:
        >>> result = ParseResult(
        ...     formula=some_formula,
        ...     confidence=0.95,
        ...     success=True
        ... )
    """
    
    formula: Optional[Formula] = None
    confidence: float = 0.0
    success: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_error(self, error: str) -> None:
        """Add error message.
        
        Args:
            error: Error message to add
        """
        self.errors.append(error)
        self.success = False
    
    def add_warning(self, warning: str) -> None:
        """Add warning message.
        
        Args:
            warning: Warning message to add
        """
        self.warnings.append(warning)
    
    def has_errors(self) -> bool:
        """Check if result has errors.
        
        Returns:
            True if errors exist
        """
        return len(self.errors) > 0
    
    def has_warnings(self) -> bool:
        """Check if result has warnings.
        
        Returns:
            True if warnings exist
        """
        return len(self.warnings) > 0
    
    def __str__(self) -> str:
        """String representation."""
        if self.success:
            return f"ParseResult(success=True, confidence={self.confidence:.2f})"
        else:
            return f"ParseResult(success=False, errors={len(self.errors)})"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return (
            f"ParseResult(formula={self.formula}, confidence={self.confidence}, "
            f"success={self.success}, errors={self.errors}, "
            f"warnings={self.warnings}, metadata={self.metadata})"
        )


class BaseParser(ABC):
    """
    Abstract base class for language-specific parsers.
    
    This class defines the common interface that all language-specific parsers
    must implement. It provides basic validation and error handling, while
    delegating the actual parsing logic to subclasses.
    
    Attributes:
        language: Language this parser handles
        confidence_threshold: Minimum confidence for successful parse
        max_input_length: Maximum allowed input length
        
    Example:
        >>> class EnglishParser(BaseParser):
        ...     def __init__(self):
        ...         super().__init__(Language.ENGLISH)
        ...
        ...     def parse_impl(self, text: str) -> ParseResult:
        ...         # Implement parsing logic
        ...         return ParseResult(success=True, confidence=0.9)
    """
    
    def __init__(
        self,
        language: str,
        confidence_threshold: float = 0.5,
        max_input_length: int = 10000
    ):
        """Initialize base parser.
        
        Args:
            language: Language code (e.g., 'en', 'es', 'fr', 'de')
            confidence_threshold: Minimum confidence for successful parse
            max_input_length: Maximum input length in characters
        """
        self.language = language
        self.confidence_threshold = confidence_threshold
        self.max_input_length = max_input_length
    
    def parse(self, text: str) -> ParseResult:
        """
        Parse natural language text into DCEC formula.
        
        This method performs validation and delegates to parse_impl()
        for the actual parsing logic.
        
        Args:
            text: Natural language text to parse
            
        Returns:
            ParseResult containing formula and metadata
            
        Example:
            >>> parser = SomeParser()
            >>> result = parser.parse("The agent must perform action")
            >>> result.success
            True
        """
        # Validate input
        validation_result = self._validate_input(text)
        if not validation_result.success:
            return validation_result
        
        # Normalize text
        text = self._normalize_text(text)
        
        try:
            # Delegate to subclass implementation
            result = self.parse_impl(text)
            
            # Check confidence threshold
            if result.confidence < self.confidence_threshold:
                result.add_warning(
                    f"Confidence {result.confidence:.2f} below threshold "
                    f"{self.confidence_threshold:.2f}"
                )
            
            return result
            
        except Exception as e:
            # Handle unexpected errors
            result = ParseResult()
            result.add_error(f"Parsing failed with exception: {str(e)}")
            return result
    
    @abstractmethod
    def parse_impl(self, text: str) -> ParseResult:
        """
        Implement language-specific parsing logic.
        
        This method must be implemented by subclasses to provide the actual
        parsing functionality for their specific language.
        
        Args:
            text: Normalized input text
            
        Returns:
            ParseResult with parsed formula
        """
        pass
    
    def _validate_input(self, text: str) -> ParseResult:
        """Validate input text.
        
        Args:
            text: Input text to validate
            
        Returns:
            ParseResult indicating validation success or failure
        """
        result = ParseResult(success=True)
        
        # Check if text is empty
        if not text or not text.strip():
            result.add_error("Input text is empty")
            return result
        
        # Check length
        if len(text) > self.max_input_length:
            result.add_error(
                f"Input text exceeds maximum length of {self.max_input_length} characters"
            )
            return result
        
        return result
    
    def _normalize_text(self, text: str) -> str:
        """Normalize input text.
        
        Performs basic text normalization:
        - Strips leading/trailing whitespace
        - Normalizes internal whitespace
        - Removes control characters
        
        Args:
            text: Input text
            
        Returns:
            Normalized text
        """
        # Strip whitespace
        text = text.strip()
        
        # Normalize internal whitespace
        text = ' '.join(text.split())
        
        return text
    
    def get_language(self) -> str:
        """Get parser language.
        
        Returns:
            Language code string
        """
        return self.language
    
    def get_supported_operators(self) -> List[str]:
        """Get list of supported operators.
        
        Can be overridden by subclasses to provide language-specific
        operator keywords.
        
        Returns:
            List of supported operator keywords
        """
        return []
    
    def __str__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}(language={self.language})"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return (
            f"{self.__class__.__name__}(language={self.language}, "
            f"confidence_threshold={self.confidence_threshold}, "
            f"max_input_length={self.max_input_length})"
        )


def get_parser(language: str) -> BaseParser:
    """
    Get parser for specified language.
    
    Factory function that returns the appropriate parser instance
    for the given language.
    
    Args:
        language: Language code or Language enum
        
    Returns:
        Parser instance for the language
        
    Raises:
        ValueError: If language is not supported
        
    Example:
        >>> from ipfs_datasets_py.logic.CEC.nl.language_detector import Language
        >>> parser = get_parser(Language.SPANISH)
        >>> result = parser.parse("El agente debe realizar la acción")
    """
    # Import here to avoid circular dependencies
    from .language_detector import Language
    
    # Convert to Language enum if string
    if isinstance(language, str):
        try:
            language = Language.from_code(language)
        except ValueError:
            raise ValueError(f"Unsupported language code: {language}")
    
    # Map languages to parser classes
    # For now, return a basic parser - will be replaced with actual implementations
    if language == Language.ENGLISH:
        # Import existing English parser from native module
        from ..native.nl_converter import NaturalLanguageConverter
        
        class EnglishParserAdapter(BaseParser):
            def __init__(self):
                super().__init__("en")
                self._converter = NaturalLanguageConverter()
            
            def parse_impl(self, text: str) -> ParseResult:
                try:
                    result = self._converter.convert_to_dcec(text)
                    if result.success:
                        return ParseResult(
                            formula=result.dcec_formula,
                            confidence=result.confidence,
                            success=True
                        )
                    else:
                        pr = ParseResult()
                        pr.add_error(result.error_message or "Conversion failed")
                        return pr
                except Exception as e:
                    pr = ParseResult()
                    pr.add_error(str(e))
                    return pr
        
        return EnglishParserAdapter()
    
    elif language == Language.SPANISH:
        # Placeholder - will be implemented in Phase 5 Week 2
        raise NotImplementedError(
            "Spanish parser not yet implemented. "
            "See Phase 5 Week 2 in CEC_PHASES_4_8_EXECUTION_GUIDE.md"
        )
    
    elif language == Language.FRENCH:
        # Placeholder - will be implemented in Phase 5 Week 3
        raise NotImplementedError(
            "French parser not yet implemented. "
            "See Phase 5 Week 3 in CEC_PHASES_4_8_EXECUTION_GUIDE.md"
        )
    
    elif language == Language.GERMAN:
        # Placeholder - will be implemented in Phase 5 Week 4
        raise NotImplementedError(
            "German parser not yet implemented. "
            "See Phase 5 Week 4 in CEC_PHASES_4_8_EXECUTION_GUIDE.md"
        )
    
    else:
        raise ValueError(f"Unsupported language: {language}")
