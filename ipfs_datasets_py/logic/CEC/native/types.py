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
from dataclasses import dataclass, field


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
FormulaDict = Dict[str, Formula]  # type: ignore[misc]
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


# ============================================================================
# Proof Statistics
# ============================================================================

@dataclass
class ProofStatistics:
    """
    Unified statistics tracking for theorem proving.
    
    This dataclass consolidates proof statistics tracking that was previously
    duplicated across multiple modules (prover_core, shadow_prover, etc.) into
    a single, type-safe structure.
    
    Attributes:
        attempts: Total number of proof attempts
        succeeded: Number of successful proofs
        failed: Number of failed proofs
        steps_taken: Total inference steps across all proofs
        avg_time: Average time per proof in seconds
        cache_hits: Number of cache hits (if caching enabled)
        rules_applied: Count of each rule application by rule name
    
    Methods:
        record_success(steps, time): Record a successful proof
        record_failure(time): Record a failed proof
        record_rule(rule_name): Record an inference rule application
        get_success_rate(): Calculate success rate percentage
        get_stats_dict(): Export as dictionary for compatibility
    
    Examples:
        >>> stats = ProofStatistics()
        >>> stats.record_success(steps=5, time=0.1)
        >>> stats.record_rule("Modus Ponens")
        >>> print(stats.get_success_rate())
        100.0
    
    Notes:
        - This replaces duplicate dict-based statistics tracking
        - Type-safe with dataclass validation
        - Provides consistent API across all provers
    """
    attempts: int = 0
    succeeded: int = 0
    failed: int = 0
    steps_taken: int = 0
    avg_time: float = 0.0
    cache_hits: int = 0
    rules_applied: Dict[str, int] = field(default_factory=dict)
    
    def record_success(self, steps: int, time: float) -> None:
        """
        Record a successful proof.
        
        Args:
            steps: Number of inference steps taken
            time: Time taken in seconds
        """
        self.attempts += 1
        self.succeeded += 1
        self.steps_taken += steps
        self._update_avg_time(time)
    
    def record_failure(self, time: float) -> None:
        """
        Record a failed proof.
        
        Args:
            time: Time taken in seconds
        """
        self.attempts += 1
        self.failed += 1
        self._update_avg_time(time)
    
    def record_rule(self, rule_name: str) -> None:
        """
        Record an inference rule application.
        
        Args:
            rule_name: Name of the inference rule that was applied
        """
        self.rules_applied[rule_name] = self.rules_applied.get(rule_name, 0) + 1
    
    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self.cache_hits += 1
    
    def get_success_rate(self) -> float:
        """
        Calculate success rate percentage.
        
        Returns:
            Success rate as percentage (0-100), or 0 if no attempts
        """
        if self.attempts == 0:
            return 0.0
        return (self.succeeded / self.attempts) * 100.0
    
    def get_stats_dict(self) -> Dict[str, Any]:
        """
        Export statistics as dictionary for backward compatibility.
        
        Returns:
            Dictionary with all statistics
        """
        return {
            "total_attempts": self.attempts,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "steps_taken": self.steps_taken,
            "average_time": self.avg_time,
            "cache_hits": self.cache_hits,
            "rules_applied": self.rules_applied.copy(),
            "success_rate": self.get_success_rate(),
        }
    
    def _update_avg_time(self, time: float) -> None:
        """
        Update average time using incremental mean formula.
        
        Args:
            time: Time for this proof attempt in seconds
        """
        if self.attempts == 1:
            self.avg_time = time
        else:
            self.avg_time = (self.avg_time * (self.attempts - 1) + time) / self.attempts
    
    def reset(self) -> None:
        """Reset all statistics to initial state."""
        self.attempts = 0
        self.succeeded = 0
        self.failed = 0
        self.steps_taken = 0
        self.avg_time = 0.0
        self.cache_hits = 0
        self.rules_applied.clear()
