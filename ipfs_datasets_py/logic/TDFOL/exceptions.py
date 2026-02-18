"""
Custom exception hierarchy for TDFOL module.

This module defines a comprehensive exception hierarchy for the Temporal Deontic
First-Order Logic (TDFOL) module, providing better error handling, debugging,
and integration with ZKP (Zero-Knowledge Proof) functionality.

Exception Hierarchy:
    TDFOLError (base)
    ├── ParseError - Formula parsing failures
    ├── ProofError - Theorem proving failures
    │   ├── ProofTimeoutError - Proof exceeded timeout
    │   ├── ProofNotFoundError - No proof exists
    │   └── ZKPProofError - Zero-knowledge proof failures
    ├── ConversionError - Format conversion failures
    ├── InferenceError - Inference rule application failures
    ├── NLProcessingError - Natural language processing failures
    │   └── PatternMatchError - Pattern matching failures
    └── CacheError - Proof caching failures

Usage:
    >>> from ipfs_datasets_py.logic.TDFOL.exceptions import ParseError
    >>> 
    >>> try:
    ...     formula = parse_tdfol("invalid syntax")
    ... except ParseError as e:
    ...     print(f"Parse failed at line {e.line}, column {e.column}")
    ...     print(f"Error: {e.message}")
    ...     print(f"Suggestion: {e.suggestion}")

Integration with ZKP:
    The exception hierarchy includes ZKPProofError for handling zero-knowledge
    proof failures, enabling unified error handling across standard and ZKP proofs.
    
    >>> from ipfs_datasets_py.logic.TDFOL.exceptions import ZKPProofError
    >>> 
    >>> try:
    ...     zkp_proof = zkp_prover.generate_proof(theorem, private_axioms)
    ... except ZKPProofError as e:
    ...     print(f"ZKP proof generation failed: {e}")
    ...     # Fall back to standard proving
    ...     result = standard_prover.prove(theorem)
"""

from typing import Optional, List, Dict, Any


class TDFOLError(Exception):
    """Base exception for all TDFOL errors.
    
    All TDFOL-specific exceptions inherit from this base class, enabling
    easy error filtering and unified exception handling.
    
    Attributes:
        message: Human-readable error description
        suggestion: Optional suggestion for fixing the error
        context: Additional context information (e.g., formula, axioms)
    
    Example:
        >>> try:
        ...     # TDFOL operation
        ...     pass
        ... except TDFOLError as e:
        ...     logger.error(f"TDFOL error: {e}")
        ...     if e.suggestion:
        ...         logger.info(f"Suggestion: {e.suggestion}")
    """
    
    def __init__(
        self,
        message: str,
        suggestion: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Initialize TDFOL error.
        
        Args:
            message: Human-readable error description
            suggestion: Optional suggestion for fixing the error
            context: Additional context (formula, axioms, etc.)
        """
        self.message = message
        self.suggestion = suggestion
        self.context = context or {}
        
        # Build full error message
        full_message = message
        if suggestion:
            full_message += f"\nSuggestion: {suggestion}"
        
        super().__init__(full_message)
    
    def __str__(self) -> str:
        """String representation of error."""
        parts = [self.message]
        if self.suggestion:
            parts.append(f"Suggestion: {self.suggestion}")
        return "\n".join(parts)


class ParseError(TDFOLError):
    """Raised when parsing fails.
    
    This exception provides detailed information about parse failures,
    including the exact position (line, column) and the problematic text.
    
    Attributes:
        message: Error description
        position: Character position in input
        line: Line number (1-indexed)
        column: Column number (1-indexed)
        input_text: The input text that failed to parse
        token: The token that caused the error (if applicable)
    
    Example:
        >>> raise ParseError(
        ...     message="Unexpected token '}'",
        ...     position=42,
        ...     line=3,
        ...     column=15,
        ...     input_text="forall x. P(x) }",
        ...     suggestion="Missing opening parenthesis?"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        position: int,
        line: int,
        column: int,
        input_text: Optional[str] = None,
        token: Optional[str] = None,
        suggestion: Optional[str] = None
    ):
        """Initialize parse error.
        
        Args:
            message: Error description
            position: Character position (0-indexed)
            line: Line number (1-indexed)
            column: Column number (1-indexed)
            input_text: The problematic input text
            token: The problematic token
            suggestion: How to fix the error
        """
        self.position = position
        self.line = line
        self.column = column
        self.input_text = input_text
        self.token = token
        
        # Build detailed message
        detailed_message = f"{message} at line {line}, column {column}"
        if token:
            detailed_message += f" (token: '{token}')"
        
        context = {
            'position': position,
            'line': line,
            'column': column,
            'input_text': input_text,
            'token': token
        }
        
        super().__init__(detailed_message, suggestion, context)


class ProofError(TDFOLError):
    """Raised when proof fails.
    
    This exception is raised when theorem proving fails, providing information
    about why the proof failed and what was attempted.
    
    Attributes:
        formula: The formula that failed to prove
        method: The proving method that was attempted
        reason: Why the proof failed
    
    Example:
        >>> raise ProofError(
        ...     message="Failed to prove formula",
        ...     formula=goal_formula,
        ...     method="forward_chaining",
        ...     reason="No applicable inference rules",
        ...     suggestion="Add required axioms to knowledge base"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        formula: Optional[Any] = None,
        method: Optional[str] = None,
        reason: Optional[str] = None,
        suggestion: Optional[str] = None
    ):
        """Initialize proof error.
        
        Args:
            message: Error description
            formula: The formula that failed
            method: Proving method attempted
            reason: Why the proof failed
            suggestion: How to fix
        """
        self.formula = formula
        self.method = method
        self.reason = reason
        
        detailed_message = message
        if method:
            detailed_message += f" (method: {method})"
        if reason:
            detailed_message += f"\nReason: {reason}"
        
        context = {
            'formula': str(formula) if formula else None,
            'method': method,
            'reason': reason
        }
        
        super().__init__(detailed_message, suggestion, context)


class ProofTimeoutError(ProofError):
    """Raised when proof exceeds timeout.
    
    This exception indicates that the proving process took too long and was
    terminated. This often happens with complex formulas or large knowledge bases.
    
    Attributes:
        timeout: The timeout value (seconds)
        elapsed: Actual time elapsed before timeout
        iterations: Number of iterations completed
    
    Example:
        >>> raise ProofTimeoutError(
        ...     message="Proof exceeded timeout",
        ...     formula=complex_formula,
        ...     timeout=60.0,
        ...     elapsed=60.1,
        ...     iterations=150,
        ...     suggestion="Increase timeout or simplify formula"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        formula: Optional[Any] = None,
        timeout: float = 0.0,
        elapsed: float = 0.0,
        iterations: int = 0,
        suggestion: Optional[str] = None
    ):
        """Initialize timeout error.
        
        Args:
            message: Error description
            formula: The formula being proved
            timeout: Timeout limit (seconds)
            elapsed: Actual elapsed time
            iterations: Iterations completed
            suggestion: How to fix
        """
        self.timeout = timeout
        self.elapsed = elapsed
        self.iterations = iterations
        
        detailed_message = (
            f"{message} ({elapsed:.2f}s > {timeout:.2f}s timeout)"
        )
        if iterations > 0:
            detailed_message += f" after {iterations} iterations"
        
        super().__init__(
            message=detailed_message,
            formula=formula,
            method="timeout",
            reason=f"Exceeded {timeout}s limit",
            suggestion=suggestion or "Increase timeout or simplify formula"
        )
        
        self.context['timeout'] = timeout
        self.context['elapsed'] = elapsed
        self.context['iterations'] = iterations


class ProofNotFoundError(ProofError):
    """Raised when no proof exists.
    
    This exception indicates that the prover exhausted all possibilities and
    determined that no proof exists (or at least none could be found).
    
    Example:
        >>> raise ProofNotFoundError(
        ...     message="No proof found",
        ...     formula=unprovable_formula,
        ...     attempts=25,
        ...     suggestion="Check if formula is provable from axioms"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        formula: Optional[Any] = None,
        attempts: int = 0,
        suggestion: Optional[str] = None
    ):
        """Initialize proof not found error.
        
        Args:
            message: Error description
            formula: The formula that couldn't be proved
            attempts: Number of proof attempts
            suggestion: How to fix
        """
        self.attempts = attempts
        
        detailed_message = message
        if attempts > 0:
            detailed_message += f" after {attempts} attempts"
        
        super().__init__(
            message=detailed_message,
            formula=formula,
            method="exhaustive_search",
            reason="No applicable inference rules or axioms",
            suggestion=suggestion or "Add required axioms or check formula validity"
        )
        
        self.context['attempts'] = attempts


class ZKPProofError(ProofError):
    """Raised when zero-knowledge proof fails.
    
    This exception is specific to ZKP (zero-knowledge proof) generation or
    verification failures. It provides additional context about the ZKP backend,
    security level, and whether the failure was in proving or verification.
    
    Attributes:
        backend: ZKP backend used (e.g., "simulated", "groth16")
        security_level: Security bits (e.g., 128)
        operation: The operation that failed ("prove" or "verify")
    
    Example:
        >>> raise ZKPProofError(
        ...     message="ZKP proof generation failed",
        ...     formula=theorem,
        ...     backend="simulated",
        ...     security_level=128,
        ...     operation="prove",
        ...     reason="Private axioms contain invalid syntax",
        ...     suggestion="Validate axioms before ZKP generation"
        ... )
    
    Integration:
        This exception enables unified error handling for hybrid proving modes
        (standard + ZKP). Applications can catch ZKPProofError and fall back
        to standard proving if privacy is not required.
    """
    
    def __init__(
        self,
        message: str,
        formula: Optional[Any] = None,
        backend: str = "unknown",
        security_level: int = 0,
        operation: str = "prove",
        reason: Optional[str] = None,
        suggestion: Optional[str] = None
    ):
        """Initialize ZKP proof error.
        
        Args:
            message: Error description
            formula: The formula/theorem
            backend: ZKP backend ("simulated", "groth16", etc.)
            security_level: Security bits
            operation: "prove" or "verify"
            reason: Why it failed
            suggestion: How to fix
        """
        self.backend = backend
        self.security_level = security_level
        self.operation = operation
        
        detailed_message = (
            f"{message} (backend: {backend}, "
            f"security: {security_level}-bit, "
            f"operation: {operation})"
        )
        
        super().__init__(
            message=detailed_message,
            formula=formula,
            method=f"zkp_{operation}",
            reason=reason,
            suggestion=suggestion or "Check ZKP backend configuration and inputs"
        )
        
        self.context['backend'] = backend
        self.context['security_level'] = security_level
        self.context['operation'] = operation


class ConversionError(TDFOLError):
    """Raised when format conversion fails.
    
    This exception is raised when converting between different formula formats
    (e.g., TDFOL ↔ DCEC, TDFOL → FOL, TDFOL → TPTP).
    
    Attributes:
        source_format: The source format
        target_format: The target format
        formula: The formula that failed to convert
    
    Example:
        >>> raise ConversionError(
        ...     message="Cannot convert nested temporal operators to FOL",
        ...     source_format="TDFOL",
        ...     target_format="FOL",
        ...     formula=complex_temporal_formula,
        ...     suggestion="FOL does not support temporal operators"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        source_format: str,
        target_format: str,
        formula: Optional[Any] = None,
        suggestion: Optional[str] = None
    ):
        """Initialize conversion error.
        
        Args:
            message: Error description
            source_format: Source format name
            target_format: Target format name
            formula: The formula being converted
            suggestion: How to fix
        """
        self.source_format = source_format
        self.target_format = target_format
        self.formula = formula
        
        detailed_message = (
            f"{message} (converting {source_format} → {target_format})"
        )
        
        context = {
            'source_format': source_format,
            'target_format': target_format,
            'formula': str(formula) if formula else None
        }
        
        super().__init__(detailed_message, suggestion, context)


class InferenceError(TDFOLError):
    """Raised when inference rule application fails.
    
    This exception is raised when an inference rule cannot be applied or
    produces an invalid result.
    
    Attributes:
        rule_name: Name of the inference rule
        formula: The formula to which the rule was applied
        premises: The premises used
    
    Example:
        >>> raise InferenceError(
        ...     message="Modus ponens requires implication",
        ...     rule_name="modus_ponens",
        ...     formula=non_implication_formula,
        ...     suggestion="Use correct formula structure"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        rule_name: str,
        formula: Optional[Any] = None,
        premises: Optional[List[Any]] = None,
        suggestion: Optional[str] = None
    ):
        """Initialize inference error.
        
        Args:
            message: Error description
            rule_name: Name of inference rule
            formula: The formula
            premises: The premises
            suggestion: How to fix
        """
        self.rule_name = rule_name
        self.formula = formula
        self.premises = premises or []
        
        detailed_message = f"{message} (rule: {rule_name})"
        
        context = {
            'rule_name': rule_name,
            'formula': str(formula) if formula else None,
            'premises': [str(p) for p in premises] if premises else []
        }
        
        super().__init__(detailed_message, suggestion, context)


class NLProcessingError(TDFOLError):
    """Raised when natural language processing fails.
    
    This exception is raised when NL → TDFOL conversion fails, including
    preprocessing, pattern matching, formula generation, or context resolution.
    
    Attributes:
        stage: Processing stage that failed
        input_text: The input text
    
    Example:
        >>> raise NLProcessingError(
        ...     message="Failed to extract entities",
        ...     stage="preprocessing",
        ...     input_text="ambiguous sentence with no clear subject",
        ...     suggestion="Rewrite with clearer structure"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        stage: str,
        input_text: Optional[str] = None,
        suggestion: Optional[str] = None
    ):
        """Initialize NL processing error.
        
        Args:
            message: Error description
            stage: Processing stage ("preprocessing", "pattern_matching", etc.)
            input_text: The input text
            suggestion: How to fix
        """
        self.stage = stage
        self.input_text = input_text
        
        detailed_message = f"{message} (stage: {stage})"
        
        context = {
            'stage': stage,
            'input_text': input_text
        }
        
        super().__init__(detailed_message, suggestion, context)


class PatternMatchError(NLProcessingError):
    """Raised when pattern matching fails.
    
    This exception is raised when no NL patterns match the input text or when
    pattern matching produces ambiguous results.
    
    Attributes:
        patterns_tried: Number of patterns attempted
        best_match_confidence: Confidence of best match (if any)
    
    Example:
        >>> raise PatternMatchError(
        ...     message="No patterns matched input",
        ...     stage="pattern_matching",
        ...     input_text="unclear legal text",
        ...     patterns_tried=45,
        ...     best_match_confidence=0.35,
        ...     suggestion="Input does not match known legal patterns"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        input_text: Optional[str] = None,
        patterns_tried: int = 0,
        best_match_confidence: float = 0.0,
        suggestion: Optional[str] = None
    ):
        """Initialize pattern match error.
        
        Args:
            message: Error description
            input_text: The input text
            patterns_tried: Number of patterns attempted
            best_match_confidence: Confidence of best match
            suggestion: How to fix
        """
        self.patterns_tried = patterns_tried
        self.best_match_confidence = best_match_confidence
        
        detailed_message = message
        if patterns_tried > 0:
            detailed_message += f" (tried {patterns_tried} patterns)"
        if best_match_confidence > 0:
            detailed_message += f", best match: {best_match_confidence:.2f}"
        
        super().__init__(
            message=detailed_message,
            stage="pattern_matching",
            input_text=input_text,
            suggestion=suggestion or "Try rephrasing with clearer structure"
        )
        
        self.context['patterns_tried'] = patterns_tried
        self.context['best_match_confidence'] = best_match_confidence


class CacheError(TDFOLError):
    """Raised when proof caching fails.
    
    This exception is raised when proof cache operations fail, including
    cache misses, serialization errors, or cache corruption.
    
    Attributes:
        operation: Cache operation ("get", "set", "clear", etc.)
        cache_key: The cache key (CID)
    
    Example:
        >>> raise CacheError(
        ...     message="Failed to serialize proof for caching",
        ...     operation="set",
        ...     cache_key="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
        ...     suggestion="Check proof object serializability"
        ... )
    """
    
    def __init__(
        self,
        message: str,
        operation: str,
        cache_key: Optional[str] = None,
        suggestion: Optional[str] = None
    ):
        """Initialize cache error.
        
        Args:
            message: Error description
            operation: Cache operation
            cache_key: The cache key (CID)
            suggestion: How to fix
        """
        self.operation = operation
        self.cache_key = cache_key
        
        detailed_message = f"{message} (operation: {operation})"
        if cache_key:
            detailed_message += f", key: {cache_key[:16]}..."
        
        context = {
            'operation': operation,
            'cache_key': cache_key
        }
        
        super().__init__(detailed_message, suggestion, context)


# Export all exceptions
__all__ = [
    'TDFOLError',
    'ParseError',
    'ProofError',
    'ProofTimeoutError',
    'ProofNotFoundError',
    'ZKPProofError',
    'ConversionError',
    'InferenceError',
    'NLProcessingError',
    'PatternMatchError',
    'CacheError',
]
