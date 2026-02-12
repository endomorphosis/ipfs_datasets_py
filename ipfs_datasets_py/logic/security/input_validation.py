"""Input validation for logic module.

Provides validation functions to prevent:
- Injection attacks
- Resource exhaustion (DoS)
- Malformed input
- Excessively complex formulas
"""

import re
from typing import Any, List
from ipfs_datasets_py.logic.config import get_config


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


class InputValidator:
    """Validates inputs to prevent attacks and resource exhaustion."""
    
    def __init__(self):
        """Initialize validator with configuration."""
        config = get_config()
        self.max_text_length = config.security.max_text_length
        self.max_formula_depth = config.security.max_formula_depth
        self.max_formula_complexity = config.security.max_formula_complexity
    
    def validate_text(self, text: str) -> str:
        """Validate text input.
        
        Args:
            text: Input text to validate
            
        Returns:
            Validated text
            
        Raises:
            ValidationError: If validation fails
        """
        if not isinstance(text, str):
            raise ValidationError(f"Expected str, got {type(text).__name__}")
        
        if len(text) > self.max_text_length:
            raise ValidationError(
                f"Input too long: {len(text)} > {self.max_text_length} characters"
            )
        
        # Check for suspicious patterns
        if re.search(r'[^\x00-\x7F]{100,}', text):
            raise ValidationError("Suspicious non-ASCII pattern detected")
        
        # Check for null bytes
        if '\x00' in text:
            raise ValidationError("Null bytes not allowed in input")
        
        return text
    
    def validate_formula(self, formula: Any) -> None:
        """Validate formula complexity.
        
        Args:
            formula: Formula object to validate
            
        Raises:
            ValidationError: If formula is too complex
        """
        depth = self._get_formula_depth(formula)
        if depth > self.max_formula_depth:
            raise ValidationError(
                f"Formula too deep: {depth} > {self.max_formula_depth}"
            )
        
        complexity = self._get_formula_complexity(formula)
        if complexity > self.max_formula_complexity:
            raise ValidationError(
                f"Formula too complex: {complexity} > {self.max_formula_complexity}"
            )
    
    def validate_formula_list(self, formulas: List[Any]) -> None:
        """Validate a list of formulas.
        
        Args:
            formulas: List of formula objects
            
        Raises:
            ValidationError: If any formula is invalid
        """
        if not isinstance(formulas, list):
            raise ValidationError(f"Expected list, got {type(formulas).__name__}")
        
        if len(formulas) > 1000:
            raise ValidationError(f"Too many formulas: {len(formulas)} > 1000")
        
        for i, formula in enumerate(formulas):
            try:
                self.validate_formula(formula)
            except ValidationError as e:
                raise ValidationError(f"Formula {i} invalid: {e}")
    
    def _get_formula_depth(self, formula: Any, current_depth: int = 0) -> int:
        """Calculate formula depth recursively.
        
        Args:
            formula: Formula object
            current_depth: Current recursion depth
            
        Returns:
            Maximum depth of formula tree
        """
        if current_depth > self.max_formula_depth:
            # Stop early to prevent stack overflow
            return current_depth
        
        # Check for formula attributes
        if hasattr(formula, 'left') and hasattr(formula, 'right'):
            # Binary formula
            left_depth = self._get_formula_depth(formula.left, current_depth + 1)
            right_depth = self._get_formula_depth(formula.right, current_depth + 1)
            return max(left_depth, right_depth)
        elif hasattr(formula, 'formula'):
            # Unary formula (negation, deontic, temporal)
            return self._get_formula_depth(formula.formula, current_depth + 1)
        elif hasattr(formula, 'body'):
            # Quantified formula
            return self._get_formula_depth(formula.body, current_depth + 1)
        else:
            # Atomic formula (predicate, constant)
            return current_depth
    
    def _get_formula_complexity(self, formula: Any) -> int:
        """Calculate formula complexity (node count).
        
        Args:
            formula: Formula object
            
        Returns:
            Number of nodes in formula tree
        """
        count = 1  # Current node
        
        # Recursively count children
        if hasattr(formula, 'left') and hasattr(formula, 'right'):
            count += self._get_formula_complexity(formula.left)
            count += self._get_formula_complexity(formula.right)
        elif hasattr(formula, 'formula'):
            count += self._get_formula_complexity(formula.formula)
        elif hasattr(formula, 'body'):
            count += self._get_formula_complexity(formula.body)
        elif hasattr(formula, 'terms') and isinstance(formula.terms, (list, tuple)):
            for term in formula.terms:
                if hasattr(term, '__class__'):  # Is an object, not primitive
                    count += self._get_formula_complexity(term)
        
        return count


# Global validator instance
_validator = None


def get_validator() -> InputValidator:
    """Get global validator instance."""
    global _validator
    if _validator is None:
        _validator = InputValidator()
    return _validator


def validate_text(text: str) -> str:
    """Validate text input.
    
    Convenience function that uses global validator.
    
    Args:
        text: Input text
        
    Returns:
        Validated text
        
    Raises:
        ValidationError: If validation fails
    """
    return get_validator().validate_text(text)


def validate_formula(formula: Any) -> None:
    """Validate formula complexity.
    
    Convenience function that uses global validator.
    
    Args:
        formula: Formula object
        
    Raises:
        ValidationError: If formula is too complex
    """
    get_validator().validate_formula(formula)


def validate_formula_list(formulas: List[Any]) -> None:
    """Validate list of formulas.
    
    Convenience function that uses global validator.
    
    Args:
        formulas: List of formulas
        
    Raises:
        ValidationError: If any formula is invalid
    """
    get_validator().validate_formula_list(formulas)
