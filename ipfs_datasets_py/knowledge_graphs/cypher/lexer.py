"""
Cypher Lexer - Token Definitions and Tokenization

This module provides the lexical analysis (tokenization) for Cypher queries.
It converts raw Cypher text into a stream of tokens for the parser.

Phase 2 Task 2.2: Lexer Implementation
"""

import re
import logging
from typing import Iterator, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum, auto

logger = logging.getLogger(__name__)


class TokenType(Enum):
    """Token types for Cypher language."""
    
    # Keywords (case-insensitive)
    MATCH = auto()
    WHERE = auto()
    RETURN = auto()
    CREATE = auto()
    MERGE = auto()
    DELETE = auto()
    REMOVE = auto()
    SET = auto()
    WITH = auto()
    ORDER = auto()
    BY = auto()
    LIMIT = auto()
    SKIP = auto()
    AS = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    XOR = auto()
    IN = auto()
    CONTAINS = auto()
    STARTS = auto()
    ENDS = auto()
    IS = auto()
    NULL = auto()
    TRUE = auto()
    FALSE = auto()
    UNION = auto()
    ALL = auto()
    DISTINCT = auto()
    OPTIONAL = auto()
    UNWIND = auto()
    CALL = auto()
    YIELD = auto()
    
    # Operators
    EQ = auto()          # =
    NEQ = auto()         # <> or !=
    LT = auto()          # <
    GT = auto()          # >
    LTE = auto()         # <=
    GTE = auto()         # >=
    PLUS = auto()        # +
    MINUS = auto()       # -
    STAR = auto()        # *
    SLASH = auto()       # /
    PERCENT = auto()     # %
    CARET = auto()       # ^
    
    # Delimiters
    LPAREN = auto()      # (
    RPAREN = auto()      # )
    LBRACKET = auto()    # [
    RBRACKET = auto()    # ]
    LBRACE = auto()      # {
    RBRACE = auto()      # }
    COLON = auto()       # :
    COMMA = auto()       # ,
    DOT = auto()         # .
    SEMICOLON = auto()   # ;
    PIPE = auto()        # |
    
    # Arrows for relationships
    ARROW_LEFT = auto()       # <-
    ARROW_RIGHT = auto()      # ->
    ARROW_BOTH = auto()       # <->
    DASH = auto()             # -
    
    # Literals
    IDENTIFIER = auto()
    NUMBER = auto()
    STRING = auto()
    PARAMETER = auto()   # $param
    
    # Special
    EOF = auto()
    NEWLINE = auto()


@dataclass
class Token:
    """Represents a single token from the lexer."""
    
    type: TokenType
    value: str
    line: int
    column: int
    
    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.column})"


class CypherLexer:
    """
    Lexical analyzer for Cypher queries.
    
    Converts Cypher query text into a stream of tokens.
    
    Example:
        lexer = CypherLexer()
        tokens = lexer.tokenize("MATCH (n:Person) RETURN n")
        for token in tokens:
            print(token)
    """
    
    # Keywords mapping (case-insensitive)
    KEYWORDS = {
        'MATCH': TokenType.MATCH,
        'WHERE': TokenType.WHERE,
        'RETURN': TokenType.RETURN,
        'CREATE': TokenType.CREATE,
        'MERGE': TokenType.MERGE,
        'DELETE': TokenType.DELETE,
        'REMOVE': TokenType.REMOVE,
        'SET': TokenType.SET,
        'WITH': TokenType.WITH,
        'ORDER': TokenType.ORDER,
        'BY': TokenType.BY,
        'LIMIT': TokenType.LIMIT,
        'SKIP': TokenType.SKIP,
        'AS': TokenType.AS,
        'AND': TokenType.AND,
        'OR': TokenType.OR,
        'NOT': TokenType.NOT,
        'XOR': TokenType.XOR,
        'IN': TokenType.IN,
        'CONTAINS': TokenType.CONTAINS,
        'STARTS': TokenType.STARTS,
        'ENDS': TokenType.ENDS,
        'IS': TokenType.IS,
        'NULL': TokenType.NULL,
        'TRUE': TokenType.TRUE,
        'FALSE': TokenType.FALSE,
        'UNION': TokenType.UNION,
        'ALL': TokenType.ALL,
        'DISTINCT': TokenType.DISTINCT,
        'OPTIONAL': TokenType.OPTIONAL,
        'UNWIND': TokenType.UNWIND,
        'CALL': TokenType.CALL,
        'YIELD': TokenType.YIELD,
    }
    
    def __init__(self):
        """Initialize the lexer."""
        self.text = ""
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: List[Token] = []
        
    def tokenize(self, text: str) -> List[Token]:
        """
        Tokenize Cypher query text.
        
        Args:
            text: Cypher query string
            
        Returns:
            List of tokens
            
        Raises:
            SyntaxError: If invalid token encountered
        """
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens = []
        
        while self.pos < len(self.text):
            # Skip whitespace
            if self._current_char() in ' \t':
                self._advance()
                continue
            
            # Handle newlines
            if self._current_char() == '\n':
                self._advance()
                self.line += 1
                self.column = 1
                continue
            
            # Skip comments
            if self._current_char() == '/' and self._peek() == '/':
                self._skip_line_comment()
                continue
            
            if self._current_char() == '/' and self._peek() == '*':
                self._skip_block_comment()
                continue
            
            # Numbers
            if self._current_char().isdigit():
                self.tokens.append(self._read_number())
                continue
            
            # Strings
            if self._current_char() in '"\'':
                self.tokens.append(self._read_string())
                continue
            
            # Parameters
            if self._current_char() == '$':
                self.tokens.append(self._read_parameter())
                continue
            
            # Identifiers and keywords
            if self._current_char().isalpha() or self._current_char() == '_':
                self.tokens.append(self._read_identifier())
                continue
            
            # Backtick-quoted identifiers
            if self._current_char() == '`':
                self.tokens.append(self._read_quoted_identifier())
                continue
            
            # Operators and delimiters
            token = self._read_operator()
            if token:
                self.tokens.append(token)
                continue
            
            # Unknown character
            raise SyntaxError(
                f"Unexpected character '{self._current_char()}' "
                f"at line {self.line}, column {self.column}"
            )
        
        # Add EOF token
        self.tokens.append(Token(TokenType.EOF, '', self.line, self.column))
        
        logger.debug("Tokenized %d tokens", len(self.tokens))
        return self.tokens
    
    def _current_char(self) -> str:
        """Get current character."""
        if self.pos >= len(self.text):
            return ''
        return self.text[self.pos]
    
    def _peek(self, offset: int = 1) -> str:
        """Peek ahead at character."""
        pos = self.pos + offset
        if pos >= len(self.text):
            return ''
        return self.text[pos]
    
    def _advance(self) -> str:
        """Advance position and return current character."""
        char = self._current_char()
        self.pos += 1
        self.column += 1
        return char
    
    def _skip_line_comment(self):
        """Skip // comment until end of line."""
        while self._current_char() and self._current_char() != '\n':
            self._advance()
    
    def _skip_block_comment(self):
        """Skip /* ... */ comment."""
        self._advance()  # Skip /
        self._advance()  # Skip *
        
        while self.pos < len(self.text) - 1:
            if self._current_char() == '*' and self._peek() == '/':
                self._advance()  # Skip *
                self._advance()  # Skip /
                return
            if self._current_char() == '\n':
                self.line += 1
                self.column = 1
            self._advance()
    
    def _read_number(self) -> Token:
        """Read numeric literal."""
        start_line = self.line
        start_col = self.column
        num_str = ''
        
        # Integer part
        while self._current_char().isdigit():
            num_str += self._advance()
        
        # Decimal part
        if self._current_char() == '.' and self._peek().isdigit():
            num_str += self._advance()  # .
            while self._current_char().isdigit():
                num_str += self._advance()
        
        # Scientific notation
        if self._current_char() in 'eE':
            num_str += self._advance()  # e or E
            if self._current_char() in '+-':
                num_str += self._advance()
            while self._current_char().isdigit():
                num_str += self._advance()
        
        return Token(TokenType.NUMBER, num_str, start_line, start_col)
    
    def _read_string(self) -> Token:
        """Read string literal."""
        start_line = self.line
        start_col = self.column
        quote = self._advance()  # " or '
        string_val = ''
        
        while self._current_char() and self._current_char() != quote:
            if self._current_char() == '\\':
                self._advance()
                # Handle escape sequences
                escape_char = self._current_char()
                if escape_char == 'n':
                    string_val += '\n'
                elif escape_char == 't':
                    string_val += '\t'
                elif escape_char == 'r':
                    string_val += '\r'
                elif escape_char == '\\':
                    string_val += '\\'
                elif escape_char == quote:
                    string_val += quote
                else:
                    string_val += escape_char
                self._advance()
            else:
                string_val += self._advance()
        
        if self._current_char() != quote:
            raise SyntaxError(f"Unterminated string at line {start_line}, column {start_col}")
        
        self._advance()  # closing quote
        return Token(TokenType.STRING, string_val, start_line, start_col)
    
    def _read_parameter(self) -> Token:
        """Read parameter ($param)."""
        start_line = self.line
        start_col = self.column
        self._advance()  # Skip $
        
        param_name = ''
        while self._current_char().isalnum() or self._current_char() == '_':
            param_name += self._advance()
        
        return Token(TokenType.PARAMETER, param_name, start_line, start_col)
    
    def _read_identifier(self) -> Token:
        """Read identifier or keyword."""
        start_line = self.line
        start_col = self.column
        ident = ''
        
        while self._current_char().isalnum() or self._current_char() == '_':
            ident += self._advance()
        
        # Check if it's a keyword
        upper_ident = ident.upper()
        token_type = self.KEYWORDS.get(upper_ident, TokenType.IDENTIFIER)
        
        return Token(token_type, ident, start_line, start_col)
    
    def _read_quoted_identifier(self) -> Token:
        """Read backtick-quoted identifier."""
        start_line = self.line
        start_col = self.column
        self._advance()  # Skip opening `
        
        ident = ''
        while self._current_char() and self._current_char() != '`':
            ident += self._advance()
        
        if self._current_char() != '`':
            raise SyntaxError(f"Unterminated identifier at line {start_line}, column {start_col}")
        
        self._advance()  # Skip closing `
        return Token(TokenType.IDENTIFIER, ident, start_line, start_col)
    
    def _read_operator(self) -> Optional[Token]:
        """Read operator or delimiter."""
        start_line = self.line
        start_col = self.column
        char = self._current_char()
        
        # Two-character operators
        if char == '<' and self._peek() == '-':
            if self._peek(2) == '>':
                self._advance()
                self._advance()
                self._advance()
                return Token(TokenType.ARROW_BOTH, '<->', start_line, start_col)
            self._advance()
            self._advance()
            return Token(TokenType.ARROW_LEFT, '<-', start_line, start_col)
        
        if char == '-' and self._peek() == '>':
            self._advance()
            self._advance()
            return Token(TokenType.ARROW_RIGHT, '->', start_line, start_col)
        
        if char == '<' and self._peek() == '=':
            self._advance()
            self._advance()
            return Token(TokenType.LTE, '<=', start_line, start_col)
        
        if char == '>' and self._peek() == '=':
            self._advance()
            self._advance()
            return Token(TokenType.GTE, '>=', start_line, start_col)
        
        if char == '<' and self._peek() == '>':
            self._advance()
            self._advance()
            return Token(TokenType.NEQ, '<>', start_line, start_col)
        
        if char == '!' and self._peek() == '=':
            self._advance()
            self._advance()
            return Token(TokenType.NEQ, '!=', start_line, start_col)
        
        # Single-character operators
        single_char_tokens = {
            '=': TokenType.EQ,
            '<': TokenType.LT,
            '>': TokenType.GT,
            '+': TokenType.PLUS,
            '-': TokenType.DASH,  # Could be MINUS or part of arrow
            '*': TokenType.STAR,
            '/': TokenType.SLASH,
            '%': TokenType.PERCENT,
            '^': TokenType.CARET,
            '(': TokenType.LPAREN,
            ')': TokenType.RPAREN,
            '[': TokenType.LBRACKET,
            ']': TokenType.RBRACKET,
            '{': TokenType.LBRACE,
            '}': TokenType.RBRACE,
            ':': TokenType.COLON,
            ',': TokenType.COMMA,
            '.': TokenType.DOT,
            ';': TokenType.SEMICOLON,
            '|': TokenType.PIPE,
        }
        
        if char in single_char_tokens:
            self._advance()
            return Token(single_char_tokens[char], char, start_line, start_col)
        
        return None
