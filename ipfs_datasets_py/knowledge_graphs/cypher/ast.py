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
    UNWIND = auto()
    
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
    CASE_EXPRESSION = auto()
    
    # Projections
    RETURN_ITEM = auto()
    ORDER_BY = auto()
    ORDER_ITEM = auto()


@dataclass
class ASTNode:
    """Base class for all AST nodes."""
    
    node_type: Optional[ASTNodeType] = None
    line: int = 0
    column: int = 0
    
    def accept(self, visitor: 'ASTVisitor') -> Any:
        """Accept a visitor (visitor pattern)."""
        if self.node_type is None:
            raise ValueError(f"node_type not set for {self.__class__.__name__}")
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


@dataclass
class UnionClause(ASTNode):
    """
    Represents a UNION or UNION ALL clause.
    
    Combines results from two queries.
    UNION removes duplicates, UNION ALL keeps all results.
    
    Example: 
        MATCH (n) RETURN n UNION MATCH (m) RETURN m
        MATCH (n) RETURN n UNION ALL MATCH (m) RETURN m
    """
    
    all: bool = False  # True for UNION ALL, False for UNION (with DISTINCT)
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.SET  # Placeholder, can add UNION to enum later


@dataclass
class UnwindClause(ASTNode):
    """
    Represents an UNWIND clause.

    Unwinds a list into individual rows, one row per list element.

    Example::

        UNWIND [1, 2, 3] AS x RETURN x
        UNWIND n.tags AS tag RETURN tag

    Attributes:
        expression: The list expression to unwind.
        variable: The variable name to bind each element to.
    """

    expression: Any = None
    variable: str = ""

    def __post_init__(self):
        if not hasattr(self, "node_type") or self.node_type is None:
            self.node_type = ASTNodeType.UNWIND


@dataclass
class WithClause(ASTNode):
    """
    Represents a WITH clause.

    Projects results to the next query part, optionally with filtering.
    Semantically similar to RETURN but passes results to the next clause
    instead of the client.

    Example::

        MATCH (n:Person)
        WITH n.name AS name, n.age AS age
        WHERE age > 30
        RETURN name

    Attributes:
        items: List of :class:`ReturnItem` projections (same as RETURN).
        where: Optional WHERE clause applied after projection.
        distinct: Whether to apply DISTINCT.
        order_by: Optional ORDER BY clause.
        skip: Optional SKIP expression.
        limit: Optional LIMIT expression.
    """

    items: List[Any] = field(default_factory=list)
    where: Optional[Any] = None
    distinct: bool = False
    order_by: Optional[Any] = None
    skip: Optional[Any] = None
    limit: Optional[Any] = None

    def __post_init__(self):
        if not hasattr(self, "node_type") or self.node_type is None:
            self.node_type = ASTNodeType.WITH


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
    """Base class for expression nodes in Cypher AST.
    
    This is an abstract base class for all expression nodes (literals, variables,
    binary operations, unary operations, etc.). Concrete expression types inherit
    from this class.
    """
    pass  # Abstract base class - no additional attributes


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


@dataclass
class CaseExpressionNode(ExpressionNode):
    """Represents a CASE expression.
    
    Two forms:
    1. Simple CASE: CASE expr WHEN value1 THEN result1 ... ELSE default END
    2. Generic CASE: CASE WHEN condition1 THEN result1 ... ELSE default END
    """
    test_expression: Optional[ExpressionNode] = None  # For simple CASE
    when_clauses: List['WhenClause'] = field(default_factory=list)
    else_result: Optional[ExpressionNode] = None
    
    def __post_init__(self):
        if not hasattr(self, 'node_type') or self.node_type is None:
            self.node_type = ASTNodeType.CASE_EXPRESSION
    
    def __repr__(self) -> str:
        if self.test_expression:
            return f"CaseExpression(test={self.test_expression}, whens={len(self.when_clauses)})"
        return f"CaseExpression(whens={len(self.when_clauses)})"


@dataclass
class WhenClause:
    """Represents a WHEN clause in a CASE expression."""
    condition: ExpressionNode  # For generic CASE, or value for simple CASE
    result: ExpressionNode
    
    def __repr__(self) -> str:
        return f"When({self.condition} -> {self.result})"


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
