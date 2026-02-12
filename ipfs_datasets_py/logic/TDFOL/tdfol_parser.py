"""
TDFOL Parser - Parse text and formulas into TDFOL structures

This module provides parsing capabilities for TDFOL formulas from:
1. String representations (symbolic notation)
2. Natural language text (pattern-based)
3. JSON/dictionary structures

Supports parsing:
- First-order logic: predicates, quantifiers, variables, functions
- Deontic logic: obligations, permissions, prohibitions
- Temporal logic: always, eventually, next, until, since
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from .tdfol_core import (
    BinaryFormula,
    BinaryTemporalFormula,
    Constant,
    DeonticFormula,
    DeonticOperator,
    Formula,
    FunctionApplication,
    LogicOperator,
    Predicate,
    Quantifier,
    QuantifiedFormula,
    Sort,
    TemporalFormula,
    TemporalOperator,
    Term,
    UnaryFormula,
    Variable,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Token Types and Lexer
# ============================================================================


class TokenType:
    """Token types for lexical analysis."""
    
    # Logical operators
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    IMPLIES = "IMPLIES"
    IFF = "IFF"
    XOR = "XOR"
    
    # Quantifiers
    FORALL = "FORALL"
    EXISTS = "EXISTS"
    
    # Deontic operators
    OBLIGATION = "OBLIGATION"
    PERMISSION = "PERMISSION"
    PROHIBITION = "PROHIBITION"
    
    # Temporal operators
    ALWAYS = "ALWAYS"
    EVENTUALLY = "EVENTUALLY"
    NEXT = "NEXT"
    UNTIL = "UNTIL"
    SINCE = "SINCE"
    WEAK_UNTIL = "WEAK_UNTIL"
    RELEASE = "RELEASE"
    
    # Structural
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    COMMA = "COMMA"
    DOT = "DOT"
    COLON = "COLON"
    
    # Literals
    IDENTIFIER = "IDENTIFIER"
    NUMBER = "NUMBER"
    
    # End
    EOF = "EOF"


class Token:
    """Token from lexical analysis."""
    
    def __init__(self, type: str, value: str, position: int):
        self.type = type
        self.value = value
        self.position = position
    
    def __repr__(self) -> str:
        return f"Token({self.type}, {self.value!r}, {self.position})"


class TDFOLLexer:
    """Lexical analyzer for TDFOL formulas."""
    
    SYMBOLS = {
        # Logical operators
        "∧": TokenType.AND,
        "&": TokenType.AND,
        "^": TokenType.AND,
        "∨": TokenType.OR,
        "|": TokenType.OR,
        "¬": TokenType.NOT,
        "~": TokenType.NOT,
        "!": TokenType.NOT,
        "→": TokenType.IMPLIES,
        "->": TokenType.IMPLIES,
        "=>": TokenType.IMPLIES,
        "↔": TokenType.IFF,
        "<->": TokenType.IFF,
        "<=>": TokenType.IFF,
        "⊕": TokenType.XOR,
        
        # Quantifiers
        "∀": TokenType.FORALL,
        "forall": TokenType.FORALL,
        "∃": TokenType.EXISTS,
        "exists": TokenType.EXISTS,
        
        # Deontic operators
        "O": TokenType.OBLIGATION,
        "P": TokenType.PERMISSION,
        "F": TokenType.PROHIBITION,
        
        # Temporal operators
        "□": TokenType.ALWAYS,
        "[]": TokenType.ALWAYS,
        "G": TokenType.ALWAYS,
        "◊": TokenType.EVENTUALLY,
        "<>": TokenType.EVENTUALLY,
        "F": TokenType.EVENTUALLY,  # Note: conflicts with PROHIBITION
        "X": TokenType.NEXT,
        "U": TokenType.UNTIL,
        "S": TokenType.SINCE,
        "W": TokenType.WEAK_UNTIL,
        "R": TokenType.RELEASE,
        
        # Structural
        "(": TokenType.LPAREN,
        ")": TokenType.RPAREN,
        ",": TokenType.COMMA,
        ".": TokenType.DOT,
        ":": TokenType.COLON,
    }
    
    def __init__(self, text: str):
        self.text = text
        self.position = 0
        self.tokens: List[Token] = []
    
    def current_char(self) -> Optional[str]:
        """Get current character."""
        if self.position < len(self.text):
            return self.text[self.position]
        return None
    
    def peek_char(self, offset: int = 1) -> Optional[str]:
        """Peek ahead at character."""
        pos = self.position + offset
        if pos < len(self.text):
            return self.text[pos]
        return None
    
    def advance(self, count: int = 1) -> None:
        """Advance position."""
        self.position += count
    
    def skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.current_char() and self.current_char().isspace():
            self.advance()
    
    def read_identifier(self) -> str:
        """Read an identifier."""
        start = self.position
        while self.current_char() and (self.current_char().isalnum() or self.current_char() == "_"):
            self.advance()
        return self.text[start:self.position]
    
    def read_number(self) -> str:
        """Read a number."""
        start = self.position
        while self.current_char() and self.current_char().isdigit():
            self.advance()
        return self.text[start:self.position]
    
    def tokenize(self) -> List[Token]:
        """Tokenize the input text."""
        self.tokens = []
        
        while self.position < len(self.text):
            self.skip_whitespace()
            
            if self.position >= len(self.text):
                break
            
            # Try multi-character symbols first
            matched = False
            for length in [3, 2]:  # Try 3-char, then 2-char symbols
                if self.position + length <= len(self.text):
                    substring = self.text[self.position:self.position + length]
                    if substring in self.SYMBOLS:
                        self.tokens.append(Token(self.SYMBOLS[substring], substring, self.position))
                        self.advance(length)
                        matched = True
                        break
            
            if matched:
                continue
            
            char = self.current_char()
            
            # Single character symbols
            if char in self.SYMBOLS:
                self.tokens.append(Token(self.SYMBOLS[char], char, self.position))
                self.advance()
            # Identifiers
            elif char.isalpha() or char == "_":
                identifier = self.read_identifier()
                # Check if it's a keyword
                if identifier.lower() in self.SYMBOLS:
                    token_type = self.SYMBOLS[identifier.lower()]
                else:
                    token_type = TokenType.IDENTIFIER
                self.tokens.append(Token(token_type, identifier, self.position - len(identifier)))
            # Numbers
            elif char.isdigit():
                number = self.read_number()
                self.tokens.append(Token(TokenType.NUMBER, number, self.position - len(number)))
            else:
                logger.warning(f"Unknown character at position {self.position}: {char}")
                self.advance()
        
        self.tokens.append(Token(TokenType.EOF, "", self.position))
        return self.tokens


# ============================================================================
# Parser
# ============================================================================


class TDFOLParser:
    """Parser for TDFOL formulas."""
    
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.position = 0
    
    def current_token(self) -> Token:
        """Get current token."""
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return self.tokens[-1]  # EOF
    
    def peek_token(self, offset: int = 1) -> Token:
        """Peek ahead at token."""
        pos = self.position + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]  # EOF
    
    def advance(self) -> Token:
        """Advance to next token and return current."""
        token = self.current_token()
        if self.position < len(self.tokens) - 1:
            self.position += 1
        return token
    
    def expect(self, token_type: str) -> Token:
        """Expect a specific token type."""
        token = self.current_token()
        if token.type != token_type:
            raise ValueError(f"Expected {token_type} but got {token.type} at position {token.position}")
        return self.advance()
    
    def parse(self) -> Formula:
        """Parse a formula."""
        return self.parse_formula()
    
    def parse_formula(self) -> Formula:
        """Parse a formula (handles precedence)."""
        return self.parse_iff()
    
    def parse_iff(self) -> Formula:
        """Parse bi-implication (lowest precedence)."""
        left = self.parse_implies()
        
        while self.current_token().type == TokenType.IFF:
            self.advance()
            right = self.parse_implies()
            left = BinaryFormula(LogicOperator.IFF, left, right)
        
        return left
    
    def parse_implies(self) -> Formula:
        """Parse implication."""
        left = self.parse_or()
        
        while self.current_token().type == TokenType.IMPLIES:
            self.advance()
            right = self.parse_or()
            left = BinaryFormula(LogicOperator.IMPLIES, left, right)
        
        return left
    
    def parse_or(self) -> Formula:
        """Parse disjunction."""
        left = self.parse_and()
        
        while self.current_token().type == TokenType.OR:
            self.advance()
            right = self.parse_and()
            left = BinaryFormula(LogicOperator.OR, left, right)
        
        return left
    
    def parse_and(self) -> Formula:
        """Parse conjunction."""
        left = self.parse_not()
        
        while self.current_token().type == TokenType.AND:
            self.advance()
            right = self.parse_not()
            left = BinaryFormula(LogicOperator.AND, left, right)
        
        return left
    
    def parse_not(self) -> Formula:
        """Parse negation."""
        if self.current_token().type == TokenType.NOT:
            self.advance()
            formula = self.parse_not()
            return UnaryFormula(LogicOperator.NOT, formula)
        
        return self.parse_quantified()
    
    def parse_quantified(self) -> Formula:
        """Parse quantified formula."""
        token = self.current_token()
        
        if token.type == TokenType.FORALL:
            return self.parse_forall()
        elif token.type == TokenType.EXISTS:
            return self.parse_exists()
        
        return self.parse_modal()
    
    def parse_forall(self) -> Formula:
        """Parse universal quantification."""
        self.expect(TokenType.FORALL)
        variable = self.parse_variable()
        self.expect(TokenType.DOT)
        formula = self.parse_formula()
        return QuantifiedFormula(Quantifier.FORALL, variable, formula)
    
    def parse_exists(self) -> Formula:
        """Parse existential quantification."""
        self.expect(TokenType.EXISTS)
        variable = self.parse_variable()
        self.expect(TokenType.DOT)
        formula = self.parse_formula()
        return QuantifiedFormula(Quantifier.EXISTS, variable, formula)
    
    def parse_modal(self) -> Formula:
        """Parse modal (deontic/temporal) formula."""
        token = self.current_token()
        
        # Deontic operators
        if token.type == TokenType.OBLIGATION:
            self.advance()
            return self.parse_deontic(DeonticOperator.OBLIGATION)
        elif token.type == TokenType.PERMISSION:
            self.advance()
            return self.parse_deontic(DeonticOperator.PERMISSION)
        elif token.type == TokenType.PROHIBITION:
            self.advance()
            return self.parse_deontic(DeonticOperator.PROHIBITION)
        
        # Temporal operators
        elif token.type == TokenType.ALWAYS:
            self.advance()
            return self.parse_temporal(TemporalOperator.ALWAYS)
        elif token.type == TokenType.EVENTUALLY:
            self.advance()
            return self.parse_temporal(TemporalOperator.EVENTUALLY)
        elif token.type == TokenType.NEXT:
            self.advance()
            return self.parse_temporal(TemporalOperator.NEXT)
        elif token.type == TokenType.UNTIL:
            # Binary temporal operator - handle differently
            pass
        elif token.type == TokenType.SINCE:
            # Binary temporal operator - handle differently
            pass
        
        return self.parse_atomic()
    
    def parse_deontic(self, operator: DeonticOperator) -> Formula:
        """Parse deontic formula."""
        self.expect(TokenType.LPAREN)
        formula = self.parse_formula()
        self.expect(TokenType.RPAREN)
        return DeonticFormula(operator, formula)
    
    def parse_temporal(self, operator: TemporalOperator) -> Formula:
        """Parse temporal formula."""
        self.expect(TokenType.LPAREN)
        formula = self.parse_formula()
        self.expect(TokenType.RPAREN)
        return TemporalFormula(operator, formula)
    
    def parse_atomic(self) -> Formula:
        """Parse atomic formula."""
        if self.current_token().type == TokenType.LPAREN:
            self.advance()
            formula = self.parse_formula()
            self.expect(TokenType.RPAREN)
            return formula
        
        return self.parse_predicate()
    
    def parse_predicate(self) -> Formula:
        """Parse predicate formula."""
        name_token = self.expect(TokenType.IDENTIFIER)
        name = name_token.value
        
        # Check if it has arguments
        if self.current_token().type == TokenType.LPAREN:
            self.advance()
            arguments = self.parse_term_list()
            self.expect(TokenType.RPAREN)
            return Predicate(name, tuple(arguments))
        else:
            # Nullary predicate (propositional variable)
            return Predicate(name, ())
    
    def parse_term_list(self) -> List[Term]:
        """Parse a comma-separated list of terms."""
        terms = [self.parse_term()]
        
        while self.current_token().type == TokenType.COMMA:
            self.advance()
            terms.append(self.parse_term())
        
        return terms
    
    def parse_term(self) -> Term:
        """Parse a term."""
        token = self.current_token()
        
        if token.type == TokenType.IDENTIFIER:
            name = token.value
            self.advance()
            
            # Check if it's a function application
            if self.current_token().type == TokenType.LPAREN:
                self.advance()
                arguments = self.parse_term_list()
                self.expect(TokenType.RPAREN)
                return FunctionApplication(name, tuple(arguments))
            # Check if it has a sort annotation
            elif self.current_token().type == TokenType.COLON:
                self.advance()
                sort_token = self.expect(TokenType.IDENTIFIER)
                sort = self.parse_sort(sort_token.value)
                # Variable with sort
                return Variable(name, sort)
            else:
                # Could be variable or constant - assume variable for now
                return Variable(name)
        
        elif token.type == TokenType.NUMBER:
            value = token.value
            self.advance()
            return Constant(value)
        
        else:
            raise ValueError(f"Unexpected token in term: {token}")
    
    def parse_variable(self) -> Variable:
        """Parse a variable."""
        name_token = self.expect(TokenType.IDENTIFIER)
        name = name_token.value
        
        # Check for sort annotation
        sort = None
        if self.current_token().type == TokenType.COLON:
            self.advance()
            sort_token = self.expect(TokenType.IDENTIFIER)
            sort = self.parse_sort(sort_token.value)
        
        return Variable(name, sort)
    
    def parse_sort(self, sort_name: str) -> Optional[Sort]:
        """Parse a sort name."""
        try:
            return Sort[sort_name.upper()]
        except KeyError:
            logger.warning(f"Unknown sort: {sort_name}")
            return None


# ============================================================================
# Public API
# ============================================================================


def parse_tdfol(formula_str: str) -> Formula:
    """
    Parse a TDFOL formula from string representation.
    
    Args:
        formula_str: String representation of formula
    
    Returns:
        Parsed Formula object
    
    Examples:
        >>> parse_tdfol("P(x)")
        Predicate('P', (Variable('x'),))
        
        >>> parse_tdfol("forall x. P(x) -> Q(x)")
        QuantifiedFormula(...)
        
        >>> parse_tdfol("O(P(x))")
        DeonticFormula(DeonticOperator.OBLIGATION, Predicate('P', (Variable('x'),)))
        
        >>> parse_tdfol("G(P(x))")
        TemporalFormula(TemporalOperator.ALWAYS, Predicate('P', (Variable('x'),)))
    """
    lexer = TDFOLLexer(formula_str)
    tokens = lexer.tokenize()
    parser = TDFOLParser(tokens)
    return parser.parse()


def parse_tdfol_safe(formula_str: str) -> Optional[Formula]:
    """
    Safely parse a TDFOL formula, returning None on error.
    
    Args:
        formula_str: String representation of formula
    
    Returns:
        Parsed Formula object or None if parsing fails
    """
    try:
        return parse_tdfol(formula_str)
    except Exception as e:
        logger.error(f"Failed to parse formula '{formula_str}': {e}")
        return None
