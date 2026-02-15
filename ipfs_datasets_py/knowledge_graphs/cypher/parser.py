"""
Cypher Query Parser - Phase 2 Implementation

This module provides a recursive descent parser for Cypher queries.
It converts tokenized Cypher text into an Abstract Syntax Tree (AST).

Phase 2 Task 2.3: Parser Implementation

Architecture:
    Tokens (from Lexer) → Parser → AST

Features:
- Recursive descent parsing
- Operator precedence handling
- Pattern matching (nodes and relationships)
- WHERE clause predicates
- RETURN projections with ORDER BY, LIMIT, SKIP
- CREATE, DELETE, SET operations
- Error recovery and helpful messages
"""

import logging
from typing import Any, Dict, List, Optional, Union

from .lexer import CypherLexer, Token, TokenType
from .ast import (
    ASTNode,
    QueryNode,
    MatchClause,
    WhereClause,
    ReturnClause,
    ReturnItem,
    OrderByClause,
    OrderItem,
    CreateClause,
    DeleteClause,
    SetClause,
    PatternNode,
    NodePattern,
    RelationshipPattern,
    ExpressionNode,
    BinaryOpNode,
    UnaryOpNode,
    PropertyAccessNode,
    FunctionCallNode,
    LiteralNode,
    VariableNode,
    ParameterNode,
    ListNode,
    MapNode,
)

logger = logging.getLogger(__name__)


class CypherParseError(Exception):
    """Exception raised when Cypher parsing fails."""
    
    def __init__(self, message: str, token: Optional[Token] = None):
        if token:
            super().__init__(f"{message} at line {token.line}, column {token.column}")
        else:
            super().__init__(message)
        self.token = token


class CypherParser:
    """
    Recursive descent parser for Cypher queries.
    
    Converts a stream of tokens into an Abstract Syntax Tree (AST).
    
    Example:
        lexer = CypherLexer()
        tokens = lexer.tokenize("MATCH (n:Person) WHERE n.age > 30 RETURN n")
        
        parser = CypherParser()
        ast = parser.parse(tokens)
        # Returns QueryNode with MatchClause, WhereClause, ReturnClause
    """
    
    def __init__(self):
        """Initialize the parser."""
        self.tokens: List[Token] = []
        self.pos = 0
        self.current_token: Optional[Token] = None
        
    def parse(self, query: Union[str, List[Token]]) -> QueryNode:
        """
        Parse a Cypher query into an AST.
        
        Args:
            query: Either a query string or list of tokens
            
        Returns:
            QueryNode representing the parsed query
            
        Raises:
            CypherParseError: If parsing fails
        """
        # Handle both string and token list inputs
        if isinstance(query, str):
            lexer = CypherLexer()
            self.tokens = lexer.tokenize(query)
        else:
            self.tokens = query
        
        self.pos = 0
        self.current_token = self.tokens[0] if self.tokens else None
        
        logger.debug("Parsing %d tokens", len(self.tokens))
        
        try:
            ast = self._parse_query()
            logger.info("Successfully parsed query")
            return ast
        except CypherParseError:
            raise
        except Exception as e:
            raise CypherParseError(f"Unexpected parsing error: {e}", self.current_token)
    
    def _current(self) -> Token:
        """Get current token."""
        if self.current_token is None:
            raise CypherParseError("Unexpected end of input")
        return self.current_token
    
    def _peek(self, offset: int = 1) -> Optional[Token]:
        """Peek ahead at token."""
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return None
    
    def _advance(self) -> Token:
        """Advance to next token and return current."""
        token = self._current()
        self.pos += 1
        if self.pos < len(self.tokens):
            self.current_token = self.tokens[self.pos]
        else:
            self.current_token = None
        return token
    
    def _expect(self, token_type: TokenType) -> Token:
        """Expect a specific token type and advance."""
        if self._current().type != token_type:
            raise CypherParseError(
                f"Expected {token_type.name}, got {self._current().type.name}",
                self._current()
            )
        return self._advance()
    
    def _match(self, *token_types: TokenType) -> bool:
        """Check if current token matches any of the given types."""
        if self.current_token is None:
            return False
        return self.current_token.type in token_types
    
    def _parse_query(self) -> QueryNode:
        """Parse a complete query."""
        clauses = []
        
        while self.current_token and self.current_token.type != TokenType.EOF:
            if self._match(TokenType.MATCH):
                clauses.append(self._parse_match())
            elif self._match(TokenType.CREATE):
                clauses.append(self._parse_create())
            elif self._match(TokenType.RETURN):
                clauses.append(self._parse_return())
            elif self._match(TokenType.WHERE):
                # WHERE can appear standalone in some contexts
                clauses.append(self._parse_where())
            elif self._match(TokenType.DELETE):
                clauses.append(self._parse_delete())
            elif self._match(TokenType.SET):
                clauses.append(self._parse_set())
            elif self._match(TokenType.SEMICOLON):
                self._advance()  # Skip semicolons
            else:
                raise CypherParseError(
                    f"Unexpected token {self._current().type.name} at start of clause",
                    self._current()
                )
        
        return QueryNode(clauses=clauses)
    
    def _parse_match(self) -> MatchClause:
        """Parse MATCH clause."""
        self._expect(TokenType.MATCH)
        
        # Check for OPTIONAL
        optional = False
        # Note: OPTIONAL MATCH would need lookahead, simplified here
        
        # Parse patterns
        patterns = self._parse_patterns()
        
        # Parse optional WHERE
        where = None
        if self._match(TokenType.WHERE):
            where = self._parse_where()
        
        return MatchClause(patterns=patterns, optional=optional, where=where)
    
    def _parse_patterns(self) -> List[PatternNode]:
        """Parse one or more patterns separated by commas."""
        patterns = [self._parse_pattern()]
        
        while self._match(TokenType.COMMA):
            self._advance()
            patterns.append(self._parse_pattern())
        
        return patterns
    
    def _parse_pattern(self) -> PatternNode:
        """Parse a single pattern (nodes and relationships)."""
        elements = []
        
        # Parse first node
        elements.append(self._parse_node_pattern())
        
        # Parse relationships and additional nodes
        while self._match(TokenType.ARROW_LEFT, TokenType.ARROW_RIGHT, TokenType.DASH, TokenType.LT):
            rel = self._parse_relationship_pattern()
            elements.append(rel)
            
            # Must have a node after relationship
            if not self._match(TokenType.LPAREN):
                raise CypherParseError(
                    "Expected node pattern after relationship",
                    self._current()
                )
            elements.append(self._parse_node_pattern())
        
        return PatternNode(elements=elements)
    
    def _parse_node_pattern(self) -> NodePattern:
        """Parse node pattern: (variable:Label {props})."""
        self._expect(TokenType.LPAREN)
        
        # Parse optional variable
        variable = None
        if self._match(TokenType.IDENTIFIER) and self._peek() and self._peek().type in (TokenType.COLON, TokenType.LBRACE, TokenType.RPAREN):
            variable = self._advance().value
        
        # Parse optional labels
        labels = []
        while self._match(TokenType.COLON):
            self._advance()
            if not self._match(TokenType.IDENTIFIER):
                raise CypherParseError("Expected label after :", self._current())
            labels.append(self._advance().value)
        
        # Parse optional properties
        properties = None
        if self._match(TokenType.LBRACE):
            properties = self._parse_map()
        
        self._expect(TokenType.RPAREN)
        
        return NodePattern(variable=variable, labels=labels, properties=properties)
    
    def _parse_relationship_pattern(self) -> RelationshipPattern:
        """Parse relationship pattern: -[:TYPE {props}]->."""
        direction = 'none'
        variable = None
        types = []
        properties = None
        
        # Parse direction and relationship details
        if self._match(TokenType.ARROW_LEFT):
            direction = 'left'
            self._advance()
        elif self._match(TokenType.LT):
            self._advance()
            self._expect(TokenType.DASH)
            direction = 'left'
        elif self._match(TokenType.DASH):
            self._advance()
        
        # Parse relationship details in brackets
        if self._match(TokenType.LBRACKET):
            self._advance()
            
            # Optional variable
            if self._match(TokenType.IDENTIFIER) and self._peek() and self._peek().type in (TokenType.COLON, TokenType.LBRACE, TokenType.RBRACKET):
                variable = self._advance().value
            
            # Optional types
            while self._match(TokenType.COLON):
                self._advance()
                if not self._match(TokenType.IDENTIFIER):
                    raise CypherParseError("Expected relationship type after :", self._current())
                types.append(self._advance().value)
            
            # Optional properties
            if self._match(TokenType.LBRACE):
                properties = self._parse_map()
            
            self._expect(TokenType.RBRACKET)
        
        # Check for right arrow
        if self._match(TokenType.DASH):
            self._advance()
        
        if self._match(TokenType.ARROW_RIGHT):
            direction = 'right' if direction == 'none' else 'both'
            self._advance()
        elif self._match(TokenType.GT):
            direction = 'right' if direction == 'none' else 'both'
            self._advance()
        
        return RelationshipPattern(
            variable=variable,
            types=types,
            properties=properties,
            direction=direction
        )
    
    def _parse_where(self) -> WhereClause:
        """Parse WHERE clause."""
        self._expect(TokenType.WHERE)
        expression = self._parse_expression()
        return WhereClause(expression=expression)
    
    def _parse_return(self) -> ReturnClause:
        """Parse RETURN clause."""
        self._expect(TokenType.RETURN)
        
        # Check for DISTINCT
        distinct = False
        if self._match(TokenType.DISTINCT):
            self._advance()
            distinct = True
        
        # Parse return items
        items = self._parse_return_items()
        
        # Parse optional ORDER BY
        order_by = None
        if self._match(TokenType.ORDER):
            order_by = self._parse_order_by()
        
        # Parse optional SKIP
        skip = None
        if self._match(TokenType.SKIP):
            self._advance()
            skip_token = self._expect(TokenType.NUMBER)
            skip = int(skip_token.value)
        
        # Parse optional LIMIT
        limit = None
        if self._match(TokenType.LIMIT):
            self._advance()
            limit_token = self._expect(TokenType.NUMBER)
            limit = int(limit_token.value)
        
        return ReturnClause(
            items=items,
            distinct=distinct,
            order_by=order_by,
            skip=skip,
            limit=limit
        )
    
    def _parse_return_items(self) -> List[ReturnItem]:
        """Parse return items."""
        items = [self._parse_return_item()]
        
        while self._match(TokenType.COMMA):
            self._advance()
            items.append(self._parse_return_item())
        
        return items
    
    def _parse_return_item(self) -> ReturnItem:
        """Parse single return item: expression [AS alias]."""
        expression = self._parse_expression()
        
        # Check for AS alias
        alias = None
        if self._match(TokenType.AS):
            self._advance()
            if not self._match(TokenType.IDENTIFIER):
                raise CypherParseError("Expected identifier after AS", self._current())
            alias = self._advance().value
        
        return ReturnItem(expression=expression, alias=alias)
    
    def _parse_order_by(self) -> OrderByClause:
        """Parse ORDER BY clause."""
        self._expect(TokenType.ORDER)
        self._expect(TokenType.BY)
        
        items = []
        items.append(self._parse_order_item())
        
        while self._match(TokenType.COMMA):
            self._advance()
            items.append(self._parse_order_item())
        
        return OrderByClause(items=items)
    
    def _parse_order_item(self) -> OrderItem:
        """Parse single order item: expression [ASC|DESC]."""
        expression = self._parse_expression()
        
        # Check for ASC/DESC
        ascending = True
        if self._match(TokenType.IDENTIFIER):
            direction = self._current().value.upper()
            if direction == 'ASC':
                self._advance()
                ascending = True
            elif direction == 'DESC':
                self._advance()
                ascending = False
        
        return OrderItem(expression=expression, ascending=ascending)
    
    def _parse_create(self) -> CreateClause:
        """Parse CREATE clause."""
        self._expect(TokenType.CREATE)
        patterns = self._parse_patterns()
        return CreateClause(patterns=patterns)
    
    def _parse_delete(self) -> DeleteClause:
        """Parse DELETE clause."""
        # Check for DETACH
        detach = False
        if self._match(TokenType.IDENTIFIER) and self._current().value.upper() == 'DETACH':
            detach = True
            self._advance()
        
        self._expect(TokenType.DELETE)
        
        expressions = [self._parse_expression()]
        while self._match(TokenType.COMMA):
            self._advance()
            expressions.append(self._parse_expression())
        
        return DeleteClause(expressions=expressions, detach=detach)
    
    def _parse_set(self) -> SetClause:
        """Parse SET clause."""
        self._expect(TokenType.SET)
        
        items = []
        items.append(self._parse_set_item())
        
        while self._match(TokenType.COMMA):
            self._advance()
            items.append(self._parse_set_item())
        
        return SetClause(items=items)
    
    def _parse_set_item(self) -> tuple:
        """Parse single SET item: property = expression."""
        # Parse property (variable.property)
        prop = self._parse_expression()
        
        self._expect(TokenType.EQ)
        
        # Parse value expression
        value = self._parse_expression()
        
        return (prop, value)
    
    def _parse_expression(self) -> ExpressionNode:
        """Parse expression with operator precedence."""
        return self._parse_or()
    
    def _parse_or(self) -> ExpressionNode:
        """Parse OR expressions."""
        left = self._parse_and()
        
        while self._match(TokenType.OR):
            op = self._advance().value
            right = self._parse_and()
            left = BinaryOpNode(operator=op, left=left, right=right)
        
        return left
    
    def _parse_and(self) -> ExpressionNode:
        """Parse AND expressions."""
        left = self._parse_not()
        
        while self._match(TokenType.AND):
            op = self._advance().value
            right = self._parse_not()
            left = BinaryOpNode(operator=op, left=left, right=right)
        
        return left
    
    def _parse_not(self) -> ExpressionNode:
        """Parse NOT expressions."""
        if self._match(TokenType.NOT):
            op = self._advance().value
            operand = self._parse_not()
            return UnaryOpNode(operator=op, operand=operand)
        
        return self._parse_comparison()
    
    def _parse_comparison(self) -> ExpressionNode:
        """Parse comparison expressions."""
        left = self._parse_additive()
        
        while self._match(TokenType.EQ, TokenType.NEQ, TokenType.LT, TokenType.GT, TokenType.LTE, TokenType.GTE):
            op = self._advance().value
            right = self._parse_additive()
            left = BinaryOpNode(operator=op, left=left, right=right)
        
        return left
    
    def _parse_additive(self) -> ExpressionNode:
        """Parse addition/subtraction."""
        left = self._parse_multiplicative()
        
        while self._match(TokenType.PLUS, TokenType.DASH):
            op = self._advance().value
            right = self._parse_multiplicative()
            left = BinaryOpNode(operator=op, left=left, right=right)
        
        return left
    
    def _parse_multiplicative(self) -> ExpressionNode:
        """Parse multiplication/division."""
        left = self._parse_unary()
        
        while self._match(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op = self._advance().value
            right = self._parse_unary()
            left = BinaryOpNode(operator=op, left=left, right=right)
        
        return left
    
    def _parse_unary(self) -> ExpressionNode:
        """Parse unary expressions."""
        if self._match(TokenType.DASH):
            op = self._advance().value
            operand = self._parse_unary()
            return UnaryOpNode(operator=op, operand=operand)
        
        return self._parse_postfix()
    
    def _parse_postfix(self) -> ExpressionNode:
        """Parse postfix expressions (property access)."""
        expr = self._parse_primary()
        
        while self._match(TokenType.DOT):
            self._advance()
            if not self._match(TokenType.IDENTIFIER):
                raise CypherParseError("Expected property name after .", self._current())
            prop = self._advance().value
            expr = PropertyAccessNode(object=expr, property=prop)
        
        return expr
    
    def _parse_primary(self) -> ExpressionNode:
        """Parse primary expressions."""
        # Numbers
        if self._match(TokenType.NUMBER):
            value = self._advance().value
            # Try to parse as int first, then float
            try:
                int_val = int(value)
                return LiteralNode(value=int_val, value_type='int')
            except ValueError:
                float_val = float(value)
                return LiteralNode(value=float_val, value_type='float')
        
        # Strings
        if self._match(TokenType.STRING):
            value = self._advance().value
            return LiteralNode(value=value, value_type='string')
        
        # Booleans
        if self._match(TokenType.TRUE):
            self._advance()
            return LiteralNode(value=True, value_type='bool')
        
        if self._match(TokenType.FALSE):
            self._advance()
            return LiteralNode(value=False, value_type='bool')
        
        # NULL
        if self._match(TokenType.NULL):
            self._advance()
            return LiteralNode(value=None, value_type='null')
        
        # Parameters
        if self._match(TokenType.PARAMETER):
            name = self._advance().value
            return ParameterNode(name=name)
        
        # Lists
        if self._match(TokenType.LBRACKET):
            return self._parse_list()
        
        # Maps
        if self._match(TokenType.LBRACE):
            return self._parse_map()
        
        # Parenthesized expressions
        if self._match(TokenType.LPAREN):
            self._advance()
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN)
            return expr
        
        # Identifiers (variables or functions)
        if self._match(TokenType.IDENTIFIER):
            name = self._advance().value
            
            # Check for function call
            if self._match(TokenType.LPAREN):
                return self._parse_function_call(name)
            
            # Variable reference
            return VariableNode(name=name)
        
        raise CypherParseError(
            f"Unexpected token {self._current().type.name} in expression",
            self._current()
        )
    
    def _parse_function_call(self, name: str) -> FunctionCallNode:
        """Parse function call."""
        self._expect(TokenType.LPAREN)
        
        arguments = []
        distinct = False
        
        # Check for DISTINCT
        if self._match(TokenType.DISTINCT):
            distinct = True
            self._advance()
        
        # Parse arguments
        if not self._match(TokenType.RPAREN):
            # Handle * for count(*)
            if self._match(TokenType.STAR):
                self._advance()
                arguments.append(VariableNode(name='*'))
            else:
                arguments.append(self._parse_expression())
                
                while self._match(TokenType.COMMA):
                    self._advance()
                    arguments.append(self._parse_expression())
        
        self._expect(TokenType.RPAREN)
        
        return FunctionCallNode(name=name, arguments=arguments, distinct=distinct)
    
    def _parse_list(self) -> ListNode:
        """Parse list literal."""
        self._expect(TokenType.LBRACKET)
        
        elements = []
        if not self._match(TokenType.RBRACKET):
            elements.append(self._parse_expression())
            
            while self._match(TokenType.COMMA):
                self._advance()
                elements.append(self._parse_expression())
        
        self._expect(TokenType.RBRACKET)
        
        return ListNode(elements=elements)
    
    def _parse_map(self) -> Dict[str, ExpressionNode]:
        """Parse map literal (returns dict for compatibility with NodePattern)."""
        self._expect(TokenType.LBRACE)
        
        properties = {}
        if not self._match(TokenType.RBRACE):
            # Parse key-value pairs
            key = self._expect(TokenType.IDENTIFIER).value
            self._expect(TokenType.COLON)
            value = self._parse_expression()
            properties[key] = value
            
            while self._match(TokenType.COMMA):
                self._advance()
                key = self._expect(TokenType.IDENTIFIER).value
                self._expect(TokenType.COLON)
                value = self._parse_expression()
                properties[key] = value
        
        self._expect(TokenType.RBRACE)
        
        return properties


# Convenience function
def parse_cypher(query: str) -> QueryNode:
    """
    Convenience function to parse a Cypher query.
    
    Args:
        query: Cypher query string
        
    Returns:
        QueryNode AST
    """
    parser = CypherParser()
    return parser.parse(query)
