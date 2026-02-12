"""
DCEC Parser Integration - Parse DCEC strings to TDFOL

This module provides integration with the CEC native DCEC parser,
allowing users to parse DCEC strings directly to TDFOL formulas.

Addresses the critical gap: "Cannot parse DCEC strings (users must code formulas)"
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .tdfol_core import (
    BinaryFormula,
    DeonticFormula,
    DeonticOperator,
    Formula,
    LogicOperator,
    Predicate,
    Quantifier,
    QuantifiedFormula,
    TemporalFormula,
    TemporalOperator,
    Term,
    UnaryFormula,
    Variable,
    Constant,
)

logger = logging.getLogger(__name__)


# Try to import CEC DCEC parser
try:
    from ipfs_datasets_py.logic.CEC.native import dcec_parsing, dcec_cleaning
    HAVE_DCEC_PARSER = True
except ImportError:
    HAVE_DCEC_PARSER = False
    logger.warning("CEC DCEC parser not available, using fallback")


# ============================================================================
# DCEC String Parser
# ============================================================================


class DCECStringParser:
    """Parse DCEC strings to TDFOL formulas."""
    
    def __init__(self):
        self.use_native = HAVE_DCEC_PARSER
    
    def parse(self, dcec_string: str) -> Formula:
        """
        Parse DCEC string to TDFOL formula.
        
        Args:
            dcec_string: DCEC string representation
        
        Returns:
            TDFOL Formula object
        
        Examples:
            >>> parser = DCECStringParser()
            >>> parser.parse("P(x)")
            Predicate('P', (Variable('x'),))
            
            >>> parser.parse("(and P Q)")
            BinaryFormula(LogicOperator.AND, Predicate('P'), Predicate('Q'))
            
            >>> parser.parse("(O P)")
            DeonticFormula(DeonticOperator.OBLIGATION, Predicate('P'))
        """
        if self.use_native:
            try:
                return self._parse_with_native(dcec_string)
            except Exception as e:
                logger.warning(f"Native DCEC parser failed: {e}, falling back")
        
        return self._parse_with_fallback(dcec_string)
    
    def _parse_with_native(self, dcec_string: str) -> Formula:
        """Parse using CEC native DCEC parser."""
        # Clean the string first
        cleaned = dcec_cleaning.clean_dcec_string(dcec_string)
        
        # Parse to DCEC formula
        dcec_formula = dcec_parsing.parse_dcec_string(cleaned)
        
        # Convert DCEC formula to TDFOL
        return self._dcec_to_tdfol(dcec_formula)
    
    def _dcec_to_tdfol(self, dcec_formula: Any) -> Formula:
        """Convert CEC DCEC formula to TDFOL formula."""
        # This would need the actual DCEC formula structure
        # For now, use string representation and fallback
        return self._parse_with_fallback(str(dcec_formula))
    
    def _parse_with_fallback(self, dcec_string: str) -> Formula:
        """Parse DCEC string using pattern-based fallback parser."""
        dcec_string = dcec_string.strip()
        
        # Handle parenthesized expressions
        if dcec_string.startswith('(') and dcec_string.endswith(')'):
            return self._parse_sexpr(dcec_string[1:-1])
        
        # Handle simple predicates
        if re.match(r'^[A-Z][a-zA-Z0-9_]*\(.*\)$', dcec_string):
            return self._parse_predicate(dcec_string)
        
        # Handle propositional atoms
        if re.match(r'^[A-Z][a-zA-Z0-9_]*$', dcec_string):
            return Predicate(dcec_string, ())
        
        # Try s-expression parsing
        return self._parse_sexpr(dcec_string)
    
    def _parse_sexpr(self, expr: str) -> Formula:
        """Parse s-expression format."""
        expr = expr.strip()
        
        # Split into operator and arguments
        parts = self._split_sexpr(expr)
        if not parts:
            raise ValueError(f"Empty expression: {expr}")
        
        operator = parts[0].lower()
        args = parts[1:]
        
        # Logical operators
        if operator == 'and':
            if len(args) < 2:
                raise ValueError(f"'and' requires at least 2 arguments")
            left = self._parse_with_fallback(args[0])
            right = self._parse_with_fallback(args[1])
            result = BinaryFormula(LogicOperator.AND, left, right)
            for arg in args[2:]:
                result = BinaryFormula(LogicOperator.AND, result, self._parse_with_fallback(arg))
            return result
        
        elif operator == 'or':
            if len(args) < 2:
                raise ValueError(f"'or' requires at least 2 arguments")
            left = self._parse_with_fallback(args[0])
            right = self._parse_with_fallback(args[1])
            result = BinaryFormula(LogicOperator.OR, left, right)
            for arg in args[2:]:
                result = BinaryFormula(LogicOperator.OR, result, self._parse_with_fallback(arg))
            return result
        
        elif operator == 'not':
            if len(args) != 1:
                raise ValueError(f"'not' requires exactly 1 argument")
            return UnaryFormula(LogicOperator.NOT, self._parse_with_fallback(args[0]))
        
        elif operator == 'implies' or operator == '->':
            if len(args) != 2:
                raise ValueError(f"'implies' requires exactly 2 arguments")
            return BinaryFormula(
                LogicOperator.IMPLIES,
                self._parse_with_fallback(args[0]),
                self._parse_with_fallback(args[1])
            )
        
        elif operator == 'iff' or operator == '<->':
            if len(args) != 2:
                raise ValueError(f"'iff' requires exactly 2 arguments")
            return BinaryFormula(
                LogicOperator.IFF,
                self._parse_with_fallback(args[0]),
                self._parse_with_fallback(args[1])
            )
        
        # Quantifiers
        elif operator == 'forall':
            if len(args) != 2:
                raise ValueError(f"'forall' requires exactly 2 arguments")
            var = Variable(args[0])
            formula = self._parse_with_fallback(args[1])
            return QuantifiedFormula(Quantifier.FORALL, var, formula)
        
        elif operator == 'exists':
            if len(args) != 2:
                raise ValueError(f"'exists' requires exactly 2 arguments")
            var = Variable(args[0])
            formula = self._parse_with_fallback(args[1])
            return QuantifiedFormula(Quantifier.EXISTS, var, formula)
        
        # Deontic operators
        elif operator == 'o':
            if len(args) != 1:
                raise ValueError(f"'O' requires exactly 1 argument")
            return DeonticFormula(
                DeonticOperator.OBLIGATION,
                self._parse_with_fallback(args[0])
            )
        
        elif operator == 'p':
            if len(args) != 1:
                raise ValueError(f"'P' requires exactly 1 argument")
            return DeonticFormula(
                DeonticOperator.PERMISSION,
                self._parse_with_fallback(args[0])
            )
        
        elif operator == 'f':
            if len(args) != 1:
                raise ValueError(f"'F' requires exactly 1 argument")
            return DeonticFormula(
                DeonticOperator.PROHIBITION,
                self._parse_with_fallback(args[0])
            )
        
        # Temporal operators
        elif operator == 'always' or operator == 'g':
            if len(args) != 1:
                raise ValueError(f"'always' requires exactly 1 argument")
            return TemporalFormula(
                TemporalOperator.ALWAYS,
                self._parse_with_fallback(args[0])
            )
        
        elif operator == 'eventually' or operator == 'f':
            if len(args) != 1:
                raise ValueError(f"'eventually' requires exactly 1 argument")
            return TemporalFormula(
                TemporalOperator.EVENTUALLY,
                self._parse_with_fallback(args[0])
            )
        
        elif operator == 'next' or operator == 'x':
            if len(args) != 1:
                raise ValueError(f"'next' requires exactly 1 argument")
            return TemporalFormula(
                TemporalOperator.NEXT,
                self._parse_with_fallback(args[0])
            )
        
        elif operator == 'until' or operator == 'u':
            if len(args) != 2:
                raise ValueError(f"'until' requires exactly 2 arguments")
            from .tdfol_core import BinaryTemporalFormula
            return BinaryTemporalFormula(
                TemporalOperator.UNTIL,
                self._parse_with_fallback(args[0]),
                self._parse_with_fallback(args[1])
            )
        
        else:
            # Unknown operator - treat as predicate application
            return self._parse_predicate_application(operator, args)
    
    def _split_sexpr(self, expr: str) -> List[str]:
        """Split s-expression into parts, respecting nested parens."""
        parts = []
        current = ""
        depth = 0
        
        for char in expr:
            if char == '(':
                depth += 1
                current += char
            elif char == ')':
                depth -= 1
                current += char
            elif char.isspace() and depth == 0:
                if current:
                    parts.append(current)
                    current = ""
            else:
                current += char
        
        if current:
            parts.append(current)
        
        return parts
    
    def _parse_predicate(self, pred_str: str) -> Predicate:
        """Parse predicate like P(x,y)."""
        match = re.match(r'^([A-Z][a-zA-Z0-9_]*)\((.*)\)$', pred_str)
        if not match:
            raise ValueError(f"Invalid predicate: {pred_str}")
        
        name = match.group(1)
        args_str = match.group(2).strip()
        
        if not args_str:
            return Predicate(name, ())
        
        # Parse arguments
        args = []
        for arg in args_str.split(','):
            arg = arg.strip()
            if arg:
                # Check if variable (lowercase) or constant (uppercase)
                if arg[0].islower():
                    args.append(Variable(arg))
                else:
                    args.append(Constant(arg))
        
        return Predicate(name, tuple(args))
    
    def _parse_predicate_application(self, name: str, args: List[str]) -> Predicate:
        """Parse predicate application from s-expression."""
        if not args:
            return Predicate(name, ())
        
        terms = []
        for arg in args:
            # Simple: treat as variable if lowercase, constant otherwise
            arg = arg.strip()
            if arg and arg[0].islower():
                terms.append(Variable(arg))
            else:
                terms.append(Constant(arg))
        
        return Predicate(name, tuple(terms))


# ============================================================================
# Public API
# ============================================================================


def parse_dcec(dcec_string: str) -> Formula:
    """
    Parse DCEC string to TDFOL formula.
    
    This function provides a convenient API for parsing DCEC strings,
    integrating with the CEC native parser when available, and falling
    back to a pattern-based parser otherwise.
    
    Args:
        dcec_string: DCEC string representation
    
    Returns:
        TDFOL Formula object
    
    Examples:
        >>> parse_dcec("P(x)")
        Predicate('P', (Variable('x'),))
        
        >>> parse_dcec("(and P(x) Q(y))")
        BinaryFormula(AND, Predicate('P', ...), Predicate('Q', ...))
        
        >>> parse_dcec("(O (always P))")
        DeonticFormula(OBLIGATION, TemporalFormula(ALWAYS, Predicate('P')))
        
        >>> parse_dcec("(forall x (implies P(x) Q(x)))")
        QuantifiedFormula(FORALL, Variable('x'), ...)
    """
    parser = DCECStringParser()
    return parser.parse(dcec_string)


def parse_dcec_safe(dcec_string: str) -> Optional[Formula]:
    """
    Safely parse DCEC string, returning None on error.
    
    Args:
        dcec_string: DCEC string representation
    
    Returns:
        TDFOL Formula object or None if parsing fails
    """
    try:
        return parse_dcec(dcec_string)
    except Exception as e:
        logger.error(f"Failed to parse DCEC string '{dcec_string}': {e}")
        return None
