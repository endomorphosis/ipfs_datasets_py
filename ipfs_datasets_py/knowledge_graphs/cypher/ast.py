"""
Cypher AST (Abstract Syntax Tree) Definitions

This module defines the AST node types for Cypher queries.
The AST represents the syntactic structure of a Cypher query.

Phase 2 Task 2.4: AST Structure Definition
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from enum import Enum, auto


class ASTNodeType(Enum):
    """Types of AST nodes."""
    
    # Top-level
    QUERY = auto()
    
    # Clauses
    MATCH = auto()
    WHERE = auto()
    RETURN = auto()
    CREATE = auto()
    MERGE = auto()
    DELETE = auto()
    SET = auto()
    WITH = auto()
    
    # Patterns
    PATTERN = auto()
    NODE_PATTERN = auto()
    RELATIONSHIP_PATTERN = auto()
    
    # Expressions
    BINARY_OP = auto()
    UNARY_OP = auto()
    PROPERTY_ACCESS = auto()
    FUNCTION_CALL = auto()
    LITERAL = auto()
    VARIABLE = auto()
    PARAMETER = auto()
    LIST = auto()
    MAP = auto()
    
    # Projections
    RETURN_ITEM = auto()
    ORDER_BY = auto()
    ORDER_ITEM = auto()


@dataclass
class ASTNode:
    """Base class for all AST nodes."""
    
    node_type: ASTNodeType
    line: int = 0
    column: int = 0
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        """Accept a visitor (visitor pattern)."""
        method_name = f'visit_{self.node_type.name.lower()}'
        method = getattr(visitor, method_name, visitor.generic_visit)
        return method(self)


@dataclass
class QueryNode(ASTNode):
    """
    Represents a complete Cypher query.
    
    Example: MATCH (n) WHERE n.age > 30 RETURN n
    """
    
    clauses: List[ASTNode] = field(default_factory=list)
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.QUERY


@dataclass  
class MatchClause(ASTNode):
    """
    Represents a MATCH clause.
    
    Example: MATCH (n:Person)-[:KNOWS]->(m)
    """
    
    patterns: List['PatternNode'] = field(default_factory=list)
    optional: bool = False
    where: Optional['WhereClause'] = None
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.MATCH


@dataclass
class WhereClause(ASTNode):
    """
    Represents a WHERE clause.
    
    Example: WHERE n.age > 30 AND n.name = 'Alice'
    """
    
    expression: 'ExpressionNode' = None
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.WHERE


@dataclass
class ReturnClause(ASTNode):
    """
    Represents a RETURN clause.
    
    Example: RETURN n.name AS name, n.age ORDER BY n.age LIMIT 10
    """
    
    items: List['ReturnItem'] = field(default_factory=list)
    distinct: bool = False
    order_by: Optional['OrderByClause'] = None
    skip: Optional[int] = None
    limit: Optional[int] = None
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.RETURN


@dataclass
class ReturnItem(ASTNode):
    """
    Represents a single item in a RETURN clause.
    
    Example: n.name AS name
    """
    
    expression: 'ExpressionNode' = None
    alias: Optional[str] = None
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.RETURN_ITEM


@dataclass
class OrderByClause(ASTNode):
    """
    Represents an ORDER BY clause.
    
    Example: ORDER BY n.age DESC, n.name ASC
    """
    
    items: List['OrderItem'] = field(default_factory=list)
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.ORDER_BY


@dataclass
class OrderItem(ASTNode):
    """
    Represents a single ORDER BY item.
    
    Example: n.age DESC
    """
    
    expression: 'ExpressionNode' = None
    ascending: bool = True
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.ORDER_ITEM


@dataclass
class CreateClause(ASTNode):
    """
    Represents a CREATE clause.
    
    Example: CREATE (n:Person {name: 'Alice', age: 30})
    """
    
    patterns: List['PatternNode'] = field(default_factory=list)
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.CREATE


@dataclass
class DeleteClause(ASTNode):
    """
    Represents a DELETE clause.
    
    Example: DELETE n
    """
    
    expressions: List['ExpressionNode'] = field(default_factory=list)
    detach: bool = False
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.DELETE


@dataclass
class SetClause(ASTNode):
    """
    Represents a SET clause.
    
    Example: SET n.age = 31, n.updated = timestamp()
    """
    
    items: List[tuple] = field(default_factory=list)  # [(property, expression), ...]
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.SET


# Pattern nodes

@dataclass
class PatternNode(ASTNode):
    """
    Represents a graph pattern.
    
    Example: (n:Person)-[:KNOWS]->(m:Person)
    """
    
    elements: List[Union['NodePattern', 'RelationshipPattern']] = field(default_factory=list)
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.PATTERN


@dataclass
class NodePattern(ASTNode):
    """
    Represents a node pattern.
    
    Example: (n:Person {name: 'Alice', age: 30})
    """
    
    variable: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    properties: Optional[Dict[str, 'ExpressionNode']] = None
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.NODE_PATTERN


@dataclass
class RelationshipPattern(ASTNode):
    """
    Represents a relationship pattern.
    
    Example: -[:KNOWS {since: 2020}]->
    """
    
    variable: Optional[str] = None
    types: List[str] = field(default_factory=list)
    properties: Optional[Dict[str, 'ExpressionNode']] = None
    direction: str = 'right'  # 'left', 'right', 'both', 'none'
    min_hops: Optional[int] = None  # For variable-length: *1..5
    max_hops: Optional[int] = None
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.RELATIONSHIP_PATTERN


# Expression nodes

@dataclass
class ExpressionNode(ASTNode):
    """Base class for expression nodes."""
    pass


@dataclass
class BinaryOpNode(ExpressionNode):
    """
    Represents a binary operation.
    
    Example: n.age > 30, a AND b
    """
    
    operator: str = ''  # '+', '-', '*', '/', '=', '<>', '<', '>', '<=', '>=', 'AND', 'OR', etc.
    left: ExpressionNode = None
    right: ExpressionNode = None
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.BINARY_OP


@dataclass
class UnaryOpNode(ExpressionNode):
    """
    Represents a unary operation.
    
    Example: NOT n.active, -n.value
    """
    
    operator: str = ''  # 'NOT', '-', etc.
    operand: ExpressionNode = None
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.UNARY_OP


@dataclass
class PropertyAccessNode(ExpressionNode):
    """
    Represents property access.
    
    Example: n.name, person.address.city
    """
    
    object: ExpressionNode = None
    property: str = ''
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.PROPERTY_ACCESS


@dataclass
class FunctionCallNode(ExpressionNode):
    """
    Represents a function call.
    
    Example: count(*), avg(n.age), timestamp()
    """
    
    name: str = ''
    arguments: List[ExpressionNode] = field(default_factory=list)
    distinct: bool = False
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.FUNCTION_CALL


@dataclass
class LiteralNode(ExpressionNode):
    """
    Represents a literal value.
    
    Example: 42, 'hello', true, null
    """
    
    value: Any = None
    value_type: str = ''  # 'int', 'float', 'string', 'bool', 'null'
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.LITERAL


@dataclass
class VariableNode(ExpressionNode):
    """
    Represents a variable reference.
    
    Example: n, person, rel
    """
    
    name: str = ''
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.VARIABLE


@dataclass
class ParameterNode(ExpressionNode):
    """
    Represents a parameter.
    
    Example: $name, $age
    """
    
    name: str = ''
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.PARAMETER


@dataclass
class ListNode(ExpressionNode):
    """
    Represents a list literal.
    
    Example: [1, 2, 3], ['a', 'b', 'c']
    """
    
    elements: List[ExpressionNode] = field(default_factory=list)
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.LIST


@dataclass
class MapNode(ExpressionNode):
    """
    Represents a map literal.
    
    Example: {name: 'Alice', age: 30}
    """
    
    properties: Dict[str, ExpressionNode] = field(default_factory=dict)
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.MAP


# Visitor base class

class ASTVisitor:
    """
    Base class for AST visitors.
    
    Implements the visitor pattern for traversing and processing AST nodes.
    """
    
    def visit(self, node: ASTNode) -> Any:
        """Visit a node."""
        return node.accept(self)
    
    def generic_visit(self, node: ASTNode) -> Any:
        """Default visit method for nodes without specific visitor."""
        return None


class ASTPrettyPrinter(ASTVisitor):
    """
    Pretty prints an AST for debugging.
    
    Example:
        printer = ASTPrettyPrinter()
        print(printer.print(ast))
    """
    
    def __init__(self):
        self.indent_level = 0
    
    def print(self, node: ASTNode) -> str:
        """Print AST as formatted string."""
        self.indent_level = 0
        self.output = []
        self.visit(node)
        return '\n'.join(self.output)
    
    def _indent(self) -> str:
        return '  ' * self.indent_level
    
    def generic_visit(self, node: ASTNode) -> Any:
        """Default visitor that prints node type and recurses."""
        self.output.append(f"{self._indent()}{node.__class__.__name__}")
        
        self.indent_level += 1
        
        # Visit all fields
        for field_name, field_value in node.__dict__.items():
            if field_name in ('node_type', 'line', 'column'):
                continue
            
            if isinstance(field_value, ASTNode):
                self.visit(field_value)
            elif isinstance(field_value, list):
                for item in field_value:
                    if isinstance(item, ASTNode):
                        self.visit(item)
        
        self.indent_level -= 1
