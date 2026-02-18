"""
Type aliases and protocols for CEC (Cognitive Event Calculus) module.

This module provides type aliases, protocols, and TypedDicts to improve
type safety and code clarity across the CEC implementation.
"""

from typing import (
    Dict, List, Set, Tuple, Optional, Union, Any,
    Protocol, TypeVar, Callable, TypedDict
)
from typing_extensions import NotRequired
from abc import abstractmethod


# ============================================================================
# Basic Type Aliases
# ============================================================================

# Formula-related types
FormulaString = str  # A formula represented as a string (e.g., "O(p)", "B(agent, φ)")
SymbolName = str  # Name of a symbol (variable, function, predicate, etc.)
SortName = str  # Name of a sort/type

# Namespace types
NamespaceDict = Dict[str, Any]  # Generic namespace dictionary
SymbolTable = Dict[SymbolName, Any]  # Symbol table mapping names to definitions

# Proof types
ProofStepId = int  # Unique identifier for a proof step
RuleName = str  # Name of an inference rule
ProofCache = Dict[str, Any]  # Cache for proof results

# Grammar types
GrammarRule = str  # Grammar rule definition
LexicalEntry = str  # Lexical entry in grammar
PatternString = str  # Pattern for NL conversion

# Configuration types
ConfigValue = Union[str, int, float, bool, List[Any], Dict[str, Any]]
ConfigDict = Dict[str, ConfigValue]


# ============================================================================
# TypedDict Definitions
# ============================================================================

class FormulaDict(TypedDict, total=False):
    """Dictionary representation of a formula."""
    type: str  # Formula type (atomic, deontic, cognitive, etc.)
    operator: NotRequired[str]  # Operator (O, P, B, K, etc.)
    arguments: NotRequired[List[Any]]  # Formula arguments
    variables: NotRequired[List[str]]  # Free variables
    bound_variables: NotRequired[List[str]]  # Bound variables
    body: NotRequired[Any]  # Body of quantified formula
    metadata: NotRequired[Dict[str, Any]]  # Additional metadata


class ProofResultDict(TypedDict, total=False):
    """Dictionary representation of a proof result."""
    is_valid: bool  # Whether proof succeeded
    proof_tree: NotRequired[Any]  # Tree of proof steps
    steps: NotRequired[List[Dict[str, Any]]]  # List of proof steps
    time_taken: NotRequired[float]  # Proof time in seconds
    rules_used: NotRequired[List[str]]  # Inference rules used
    cached: NotRequired[bool]  # Whether result was cached
    error: NotRequired[str]  # Error message if proof failed


class ConversionResultDict(TypedDict, total=False):
    """Dictionary representation of NL conversion result."""
    formula: Any  # Converted formula
    confidence: float  # Confidence score (0-1)
    patterns_matched: List[str]  # Patterns that matched
    text: str  # Original text
    language: str  # Language code
    metadata: NotRequired[Dict[str, Any]]  # Additional metadata


class NamespaceExport(TypedDict, total=False):
    """Dictionary representation of namespace export."""
    sorts: Dict[str, Any]  # Sort definitions
    variables: Dict[str, Any]  # Variable definitions
    functions: Dict[str, Any]  # Function definitions
    predicates: Dict[str, Any]  # Predicate definitions
    constants: NotRequired[Dict[str, Any]]  # Constant definitions
    metadata: NotRequired[Dict[str, Any]]  # Additional metadata


class GrammarConfig(TypedDict, total=False):
    """Configuration for grammar engine."""
    language: str  # Language code (en, es, fr, etc.)
    lexicon_file: NotRequired[str]  # Path to lexicon file
    rules_file: NotRequired[str]  # Path to rules file
    enable_caching: NotRequired[bool]  # Enable grammar caching
    max_cache_size: NotRequired[int]  # Maximum cache size
    strict_mode: NotRequired[bool]  # Strict parsing mode


class ProverConfig(TypedDict, total=False):
    """Configuration for theorem prover."""
    max_depth: int  # Maximum proof depth
    timeout: NotRequired[float]  # Timeout in seconds
    enable_caching: NotRequired[bool]  # Enable proof caching
    strategy: NotRequired[str]  # Proof strategy (forward, backward, bidirectional)
    verbose: NotRequired[bool]  # Verbose logging
    parallel: NotRequired[bool]  # Enable parallel proving


# ============================================================================
# Protocols
# ============================================================================

class Formula(Protocol):
    """Protocol for formula objects."""
    
    @abstractmethod
    def __str__(self) -> str:
        """Return string representation of formula."""
        ...
    
    @abstractmethod
    def __eq__(self, other: Any) -> bool:
        """Check formula equality."""
        ...
    
    @abstractmethod
    def free_variables(self) -> Set[str]:
        """Return set of free variables in formula."""
        ...


class Term(Protocol):
    """Protocol for term objects."""
    
    @abstractmethod
    def __str__(self) -> str:
        """Return string representation of term."""
        ...
    
    @abstractmethod
    def __eq__(self, other: Any) -> bool:
        """Check term equality."""
        ...


class Prover(Protocol):
    """Protocol for theorem prover implementations."""
    
    @abstractmethod
    def prove(self, formula: Any, premises: Optional[List[Any]] = None) -> Any:
        """
        Prove a formula given optional premises.
        
        Args:
            formula: Formula to prove
            premises: Optional list of premise formulas
            
        Returns:
            ProofResult object
        """
        ...
    
    @abstractmethod
    def is_provable(self, formula: Any, premises: Optional[List[Any]] = None) -> bool:
        """
        Check if formula is provable without generating full proof.
        
        Args:
            formula: Formula to check
            premises: Optional list of premise formulas
            
        Returns:
            True if provable, False otherwise
        """
        ...


class Converter(Protocol):
    """Protocol for NL to DCEC converters."""
    
    @abstractmethod
    def convert(self, text: str, language: str = "en") -> Any:
        """
        Convert natural language text to DCEC formula.
        
        Args:
            text: Natural language text
            language: Language code (default: en)
            
        Returns:
            ConversionResult object
        """
        ...
    
    @abstractmethod
    def add_pattern(self, pattern: str, template: str) -> None:
        """
        Add a new conversion pattern.
        
        Args:
            pattern: Regex pattern for matching
            template: Formula template for conversion
        """
        ...


class KnowledgeBase(Protocol):
    """Protocol for knowledge base implementations."""
    
    @abstractmethod
    def add(self, formula: Any) -> str:
        """
        Add formula to knowledge base.
        
        Args:
            formula: Formula to add
            
        Returns:
            Formula ID
        """
        ...
    
    @abstractmethod
    def query(self, pattern: Any) -> List[Any]:
        """
        Query knowledge base for matching formulas.
        
        Args:
            pattern: Query pattern
            
        Returns:
            List of matching formulas
        """
        ...
    
    @abstractmethod
    def remove(self, formula_id: str) -> bool:
        """
        Remove formula from knowledge base.
        
        Args:
            formula_id: ID of formula to remove
            
        Returns:
            True if removed, False if not found
        """
        ...


# ============================================================================
# Generic Type Variables
# ============================================================================

T = TypeVar('T')  # Generic type variable
F = TypeVar('F', bound=Formula)  # Formula type variable
T_co = TypeVar('T_co', covariant=True)  # Covariant type variable
T_contra = TypeVar('T_contra', contravariant=True)  # Contravariant type variable


# ============================================================================
# Callable Type Aliases
# ============================================================================

# Validation functions
Validator = Callable[[Any], bool]  # Function that validates input
ValidatorWithContext = Callable[[Any, Dict[str, Any]], bool]  # Validator with context

# Transformation functions
Transformer = Callable[[T], T]  # Function that transforms a value
Parser = Callable[[str], Any]  # Function that parses a string
Formatter = Callable[[Any], str]  # Function that formats to string

# Cache key generators
CacheKeyGenerator = Callable[[Any], str]  # Function that generates cache key

# Error handlers
ErrorHandler = Callable[[Exception], Any]  # Function that handles errors
ErrorRecovery = Callable[[Exception, Any], Any]  # Function for error recovery


# ============================================================================
# Complex Type Aliases
# ============================================================================

# Optional types (frequently used)
OptionalFormula = Optional[Formula]
OptionalProver = Optional[Prover]
OptionalConverter = Optional[Converter]

# List types
FormulaList = List[Formula]
TermList = List[Term]
StringList = List[str]

# Dict types
FormulaDict = Dict[str, Formula]
ProofDict = Dict[str, Any]

# Union types
FormulaOrString = Union[Formula, str]
TermOrString = Union[Term, str]
ConfigValueType = Union[str, int, float, bool, None]

# Tuple types
VariableBinding = Tuple[str, Any]  # (variable_name, value)
ProofStep = Tuple[int, RuleName, Formula]  # (step_id, rule_name, conclusion)
PatternMatch = Tuple[PatternString, float]  # (pattern, confidence)


# ============================================================================
# Utility Types
# ============================================================================

# Result types
class Result(TypedDict, total=False):
    """Generic result type for operations."""
    success: bool
    value: NotRequired[Any]
    error: NotRequired[str]
    metadata: NotRequired[Dict[str, Any]]


# Cache entry
class CacheEntry(TypedDict):
    """Cache entry with value and metadata."""
    value: Any
    timestamp: float
    hits: int
    size: int


# Statistics
class Statistics(TypedDict, total=False):
    """Statistics for operations."""
    total_operations: int
    successful: int
    failed: int
    average_time: float
    cache_hits: NotRequired[int]
    cache_misses: NotRequired[int]
