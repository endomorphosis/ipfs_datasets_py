"""
Unified API for Natural Language to TDFOL Conversion.

This module provides a simple, unified interface for converting natural language
text to TDFOL (Temporal Deontic First-Order Logic) formulas.

Example:
    >>> from ipfs_datasets_py.logic.TDFOL.nl import parse_natural_language
    >>> result = parse_natural_language("All contractors must pay taxes.")
    >>> print(result.formulas[0].formula_string)
    ∀x0.(Contractors(x0) → O(Pay(x0)))
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import time

try:
    from .tdfol_nl_preprocessor import NLPreprocessor
    from .tdfol_nl_patterns import PatternMatcher
    from .tdfol_nl_generator import FormulaGenerator, GeneratedFormula
    from .tdfol_nl_context import ContextResolver, Context
    DEPENDENCIES_AVAILABLE = True
except ImportError:
    DEPENDENCIES_AVAILABLE = False


@dataclass
class ParseOptions:
    """Configuration options for natural language parsing."""
    
    min_confidence: float = 0.5
    """Minimum confidence threshold for pattern matches."""
    
    include_metadata: bool = True
    """Include metadata (entities, patterns, etc.) in results."""
    
    resolve_context: bool = True
    """Enable context resolution across sentences."""
    
    max_formulas: Optional[int] = None
    """Maximum number of formulas to return (None = unlimited)."""
    
    enable_caching: bool = True
    """Enable caching for repeated parsing."""


@dataclass
class ParseResult:
    """Result of natural language parsing."""
    
    success: bool
    """Whether parsing was successful."""
    
    formulas: List[GeneratedFormula] = field(default_factory=list)
    """Generated TDFOL formulas."""
    
    text: str = ""
    """Original input text."""
    
    num_formulas: int = 0
    """Number of formulas generated."""
    
    confidence: float = 0.0
    """Average confidence score across all formulas."""
    
    parse_time_ms: float = 0.0
    """Time taken to parse (milliseconds)."""
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional metadata (entities, patterns, etc.)."""
    
    errors: List[str] = field(default_factory=list)
    """Any errors encountered during parsing."""
    
    warnings: List[str] = field(default_factory=list)
    """Any warnings generated during parsing."""


class NLParser:
    """
    Stateful natural language parser with context tracking.
    
    This class maintains state across multiple parse calls, enabling
    context resolution and coreference tracking.
    
    Example:
        >>> parser = NLParser()
        >>> result1 = parser.parse("Contractors must submit reports.")
        >>> result2 = parser.parse("They shall do so within 30 days.")
        >>> # "They" is resolved to "contractors" via context
    """
    
    def __init__(self, options: Optional[ParseOptions] = None):
        """Initialize parser with options."""
        if not DEPENDENCIES_AVAILABLE:
            raise ImportError(
                "NL parsing dependencies not available. "
                "Install with: pip install ipfs_datasets_py[knowledge_graphs] && "
                "python -m spacy download en_core_web_sm"
            )
        
        self.options = options or ParseOptions()
        self.preprocessor = NLPreprocessor()
        self.matcher = PatternMatcher()
        self.generator = FormulaGenerator()
        self.resolver = ContextResolver()
        self.context = Context() if self.options.resolve_context else None
        self._cache: Dict[str, ParseResult] = {}
    
    def parse(self, text: str) -> ParseResult:
        """
        Parse natural language text to TDFOL formulas.
        
        Args:
            text: Natural language text to parse.
            
        Returns:
            ParseResult with formulas and metadata.
        """
        # Check cache
        if self.options.enable_caching and text in self._cache:
            cached = self._cache[text]
            return ParseResult(
                success=cached.success,
                formulas=cached.formulas.copy(),
                text=cached.text,
                num_formulas=cached.num_formulas,
                confidence=cached.confidence,
                parse_time_ms=0.0,  # Cached result
                metadata=cached.metadata.copy(),
                errors=cached.errors.copy(),
                warnings=cached.warnings.copy()
            )
        
        start_time = time.time()
        result = ParseResult(success=False, text=text)
        
        try:
            # Step 1: Preprocess
            doc = self.preprocessor.process(text)
            
            # Step 2: Match patterns
            matches = self.matcher.match(text, min_confidence=self.options.min_confidence)
            
            if not matches:
                result.warnings.append("No patterns matched in text")
            
            # Step 3: Update context (if enabled)
            if self.options.resolve_context and self.context:
                self.resolver.update_context(self.context, doc)
            
            # Step 4: Generate formulas
            formulas = self.generator.generate_from_matches(
                matches,
                context=self.context if self.options.resolve_context else None
            )
            
            # Apply max_formulas limit
            if self.options.max_formulas:
                formulas = formulas[:self.options.max_formulas]
            
            # Populate result
            result.success = True
            result.formulas = formulas
            result.num_formulas = len(formulas)
            result.confidence = (
                sum(f.confidence for f in formulas) / len(formulas)
                if formulas else 0.0
            )
            
            # Add metadata
            if self.options.include_metadata:
                result.metadata = {
                    'num_sentences': doc.num_sentences,
                    'num_entities': doc.num_entities,
                    'num_temporal': doc.num_temporal,
                    'num_patterns': len(matches),
                    'entities': [
                        {'text': e.text, 'type': e.type.value}
                        for e in doc.entities
                    ],
                    'temporal': [
                        {'text': t.text, 'type': t.type}
                        for t in doc.temporal
                    ],
                    'modalities': doc.modalities,
                }
            
        except Exception as e:
            result.success = False
            result.errors.append(f"Parsing error: {str(e)}")
        
        # Calculate parse time
        result.parse_time_ms = (time.time() - start_time) * 1000
        
        # Cache result
        if self.options.enable_caching:
            self._cache[text] = result
        
        return result
    
    def reset_context(self):
        """Reset the context tracker."""
        if self.context:
            self.context = Context()
    
    def clear_cache(self):
        """Clear the parsing cache."""
        self._cache.clear()


def parse_natural_language(
    text: str,
    min_confidence: float = 0.5,
    include_metadata: bool = True
) -> ParseResult:
    """
    Parse natural language text to TDFOL formulas (stateless).
    
    This is a convenience function for one-off parsing without maintaining state.
    For parsing multiple related sentences, use NLParser class.
    
    Args:
        text: Natural language text to parse.
        min_confidence: Minimum confidence threshold for pattern matches.
        include_metadata: Whether to include metadata in results.
        
    Returns:
        ParseResult with formulas and metadata.
        
    Example:
        >>> result = parse_natural_language("All contractors must pay taxes.")
        >>> print(result.formulas[0].formula_string)
        ∀x0.(Contractors(x0) → O(Pay(x0)))
    """
    options = ParseOptions(
        min_confidence=min_confidence,
        include_metadata=include_metadata,
        resolve_context=False  # Stateless parsing
    )
    parser = NLParser(options)
    return parser.parse(text)


def parse_natural_language_batch(
    texts: List[str],
    min_confidence: float = 0.5,
    include_metadata: bool = False,
    resolve_context: bool = True
) -> List[ParseResult]:
    """
    Parse multiple natural language texts with shared context.
    
    Args:
        texts: List of natural language texts to parse.
        min_confidence: Minimum confidence threshold for pattern matches.
        include_metadata: Whether to include metadata in results.
        resolve_context: Whether to resolve context across texts.
        
    Returns:
        List of ParseResults, one per input text.
        
    Example:
        >>> texts = [
        ...     "Contractors must submit reports.",
        ...     "They shall do so within 30 days."
        ... ]
        >>> results = parse_natural_language_batch(texts)
        >>> for i, result in enumerate(results):
        ...     print(f"Text {i+1}: {result.num_formulas} formulas")
    """
    options = ParseOptions(
        min_confidence=min_confidence,
        include_metadata=include_metadata,
        resolve_context=resolve_context
    )
    parser = NLParser(options)
    
    results = []
    for text in texts:
        result = parser.parse(text)
        results.append(result)
    
    return results


__all__ = [
    'ParseOptions',
    'ParseResult',
    'NLParser',
    'parse_natural_language',
    'parse_natural_language_batch',
]
