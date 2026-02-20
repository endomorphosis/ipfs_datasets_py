"""
Custom exception hierarchy for CEC (Cognitive Event Calculus) module.

This module defines a comprehensive exception hierarchy for all CEC operations,
providing meaningful error messages with context for debugging and error recovery.
"""

from typing import Optional, Any, Dict


class CECError(Exception):
    """Base exception for all CEC-related errors."""
    
    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """
        Initialize CEC error with context and suggestions.
        
        Args:
            message: Error message describing what went wrong
            context: Optional dictionary with contextual information (formula, location, etc.)
            suggestion: Optional suggestion for how to fix the error
            
        Examples:
            >>> raise CECError(
            ...     "Operation failed",
            ...     context={"formula": "O(p)", "operation": "prove"},
            ...     suggestion="Check formula syntax"
            ... )
        """
        self.context = context or {}
        self.suggestion = suggestion
        
        full_message = message
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            full_message += f" [Context: {context_str}]"
        if self.suggestion:
            full_message += f" [Suggestion: {self.suggestion}]"
        
        super().__init__(full_message)


class ParsingError(CECError):
    """Raised when parsing DCEC formulas or expressions fails."""
    
    def __init__(
        self,
        message: str,
        expression: Optional[str] = None,
        position: Optional[int] = None,
        expected: Optional[str] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """
        Initialize parsing error with expression context.
        
        Args:
            message: Error message
            expression: The expression being parsed
            position: Character position where error occurred
            expected: What was expected at this position
            suggestion: How to fix the error
            
        Examples:
            >>> raise ParsingError(
            ...     "Invalid operator",
            ...     expression="O((p)",
            ...     position=4,
            ...     expected="closing parenthesis",
            ...     suggestion="Add closing ')' at end"
            ... )
        """
        context: Dict[str, Any] = {}
        if expression is not None:
            context["expression"] = expression
        if position is not None:
            context["position"] = position  # type: ignore[assignment]
        if expected is not None:
            context["expected"] = expected
        
        super().__init__(message, context=context, suggestion=suggestion)


class ProvingError(CECError, ValueError):
    """Raised when theorem proving operations fail."""
    
    def __init__(
        self,
        message: str,
        formula: Optional[str] = None,
        proof_step: Optional[int] = None,
        rule: Optional[str] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """
        Initialize proving error with proof context.
        
        Args:
            message: Error message
            formula: The formula being proved
            proof_step: Step number where error occurred
            rule: Inference rule that failed
            suggestion: How to fix the error
            
        Examples:
            >>> raise ProvingError(
            ...     "Inference rule not applicable",
            ...     formula="O(p) -> P(p)",
            ...     proof_step=3,
            ...     rule="modus_ponens",
            ...     suggestion="Check premises are available"
            ... )
        """
        context: Dict[str, Any] = {}
        if formula is not None:
            context["formula"] = formula
        if proof_step is not None:
            context["proof_step"] = proof_step  # type: ignore[assignment]
        if rule is not None:
            context["rule"] = rule
        
        super().__init__(message, context=context, suggestion=suggestion)


class ConversionError(CECError):
    """Raised when natural language to DCEC conversion fails."""
    
    def __init__(
        self,
        message: str,
        text: Optional[str] = None,
        language: str = "en",
        pattern: Optional[str] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """
        Initialize conversion error with NL context.
        
        Args:
            message: Error message
            text: The natural language text being converted
            language: Language code (default: en)
            pattern: Pattern that failed to match
            suggestion: How to fix the error
            
        Examples:
            >>> raise ConversionError(
            ...     "No pattern matched",
            ...     text="The agent should do something",
            ...     pattern="obligation_pattern",
            ...     suggestion="Use 'must' for obligations"
            ... )
        """
        context = {"language": language}
        if text is not None:
            context["text"] = text
        if pattern is not None:
            context["pattern"] = pattern
        
        super().__init__(message, context=context, suggestion=suggestion)


class ValidationError(CECError, ValueError):
    """Raised when formula or input validation fails."""
    
    def __init__(
        self,
        message: str,
        value: Optional[Any] = None,
        expected_type: Optional[str] = None,
        constraint: Optional[str] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """
        Initialize validation error with validation context.
        
        Args:
            message: Error message
            value: The value that failed validation
            expected_type: Expected type or format
            constraint: Constraint that was violated
            suggestion: How to fix the error
            
        Examples:
            >>> raise ValidationError(
            ...     "Invalid sort",
            ...     value="unknown_sort",
            ...     expected_type="Sort",
            ...     constraint="Sort must be defined in namespace",
            ...     suggestion="Define sort before use"
            ... )
        """
        context = {}
        if value is not None:
            context["value"] = str(value)
        if expected_type is not None:
            context["expected_type"] = expected_type
        if constraint is not None:
            context["constraint"] = constraint
        
        super().__init__(message, context=context, suggestion=suggestion)


class NamespaceError(CECError, ValueError):
    """Raised when namespace operations fail (symbol not found, duplicate definition, etc.)."""
    
    def __init__(
        self,
        message: str,
        symbol: Optional[str] = None,
        operation: Optional[str] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """
        Initialize namespace error with symbol context.
        
        Args:
            message: Error message
            symbol: The symbol name causing the error
            operation: Operation being performed (define, lookup, etc.)
            suggestion: How to fix the error
            
        Examples:
            >>> raise NamespaceError(
            ...     "Symbol not found",
            ...     symbol="predicate_p",
            ...     operation="lookup",
            ...     suggestion="Define predicate before using"
            ... )
        """
        context = {}
        if symbol is not None:
            context["symbol"] = symbol
        if operation is not None:
            context["operation"] = operation
        
        super().__init__(message, context=context, suggestion=suggestion)


class GrammarError(CECError):
    """Raised when grammar processing fails."""
    
    def __init__(
        self,
        message: str,
        rule: Optional[str] = None,
        input_text: Optional[str] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """
        Initialize grammar error with grammar context.
        
        Args:
            message: Error message
            rule: Grammar rule that failed
            input_text: Input being processed
            suggestion: How to fix the error
            
        Examples:
            >>> raise GrammarError(
            ...     "Grammar rule failed",
            ...     rule="obligation_rule",
            ...     input_text="must do action",
            ...     suggestion="Check grammar definition"
            ... )
        """
        context = {}
        if rule is not None:
            context["rule"] = rule
        if input_text is not None:
            context["input_text"] = input_text
        
        super().__init__(message, context=context, suggestion=suggestion)


class KnowledgeBaseError(CECError):
    """Raised when knowledge base operations fail."""
    
    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        formula_id: Optional[str] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """
        Initialize knowledge base error with KB context.
        
        Args:
            message: Error message
            operation: KB operation (add, remove, query, etc.)
            formula_id: ID of formula involved
            suggestion: How to fix the error
            
        Examples:
            >>> raise KnowledgeBaseError(
            ...     "Formula already exists",
            ...     operation="add",
            ...     formula_id="f123",
            ...     suggestion="Use update instead of add"
            ... )
        """
        context = {}
        if operation is not None:
            context["operation"] = operation
        if formula_id is not None:
            context["formula_id"] = formula_id
        
        super().__init__(message, context=context, suggestion=suggestion)


# Convenient aliases for backward compatibility
DCECParsingError = ParsingError  # Used in some existing code
DCECError = CECError  # Alternative name
