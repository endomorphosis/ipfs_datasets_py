"""
Cypher AST to IR Compiler

This module compiles Cypher AST into an Intermediate Representation (IR)
that can be executed by the GraphEngine.

Phase 2 Task 2.5: Compiler Implementation

IR Format:
    List of operations that the executor can process.
    Each operation is a dict with "op" and parameters.
    
Example IR:
    [
        {"op": "ScanLabel", "label": "Person", "variable": "n"},
        {"op": "Filter", "variable": "n", "property": "age", "operator": ">", "value": 30},
        {"op": "Project", "items": [{"expression": "n.name", "alias": "name"}]}
    ]
"""

import logging
from typing import Any, Dict, List, Optional, Union

from .ast import (
    QueryNode,
    MatchClause,
    WhereClause,
    ReturnClause,
    ReturnItem,
    CreateClause,
    DeleteClause,
    SetClause,
    PatternNode,
    NodePattern,
    RelationshipPattern,
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


class CypherCompileError(Exception):
    """Exception raised when compilation fails."""
    pass


class CypherCompiler:
    """
    Compiles Cypher AST into Intermediate Representation (IR).
    
    The IR is a list of operations that can be executed sequentially
    by the GraphEngine.
    
    Example:
        from .parser import CypherParser
        from .compiler import CypherCompiler
        
        parser = CypherParser()
        ast = parser.parse("MATCH (n:Person) WHERE n.age > 30 RETURN n")
        
        compiler = CypherCompiler()
        ir = compiler.compile(ast)
        # Returns list of IR operations
    """
    
    def __init__(self):
        """Initialize the compiler."""
        self.variables = {}  # Track variable bindings
        self.operations = []
        
    def compile(self, ast: QueryNode) -> List[Dict[str, Any]]:
        """
        Compile AST to IR.
        
        Args:
            ast: QueryNode from parser
            
        Returns:
            List of IR operations
            
        Raises:
            CypherCompileError: If compilation fails
        """
        self.variables = {}
        self.operations = []
        
        logger.debug("Compiling AST with %d clauses", len(ast.clauses))
        
        try:
            for clause in ast.clauses:
                self._compile_clause(clause)
            
            logger.info("Compiled %d operations", len(self.operations))
            return self.operations
            
        except CypherCompileError:
            raise
        except Exception as e:
            raise CypherCompileError(f"Compilation error: {e}")
    
    def _compile_clause(self, clause):
        """Compile a single clause."""
        if isinstance(clause, MatchClause):
            self._compile_match(clause)
        elif isinstance(clause, WhereClause):
            self._compile_where(clause)
        elif isinstance(clause, ReturnClause):
            self._compile_return(clause)
        elif isinstance(clause, CreateClause):
            self._compile_create(clause)
        elif isinstance(clause, DeleteClause):
            self._compile_delete(clause)
        elif isinstance(clause, SetClause):
            self._compile_set(clause)
        else:
            raise CypherCompileError(f"Unknown clause type: {type(clause)}")
    
    def _compile_match(self, match: MatchClause):
        """
        Compile MATCH clause.
        
        Generates:
        - ScanLabel operations for labeled nodes
        - ScanAll for unlabeled nodes
        - Expand operations for relationships
        - Filter operations for WHERE
        """
        for pattern in match.patterns:
            self._compile_pattern(pattern)
        
        # Compile WHERE if present
        if match.where:
            self._compile_where(match.where)
    
    def _compile_pattern(self, pattern: PatternNode):
        """Compile a graph pattern."""
        for i, element in enumerate(pattern.elements):
            if isinstance(element, NodePattern):
                self._compile_node_pattern(element, f"_n{i}")
            elif isinstance(element, RelationshipPattern):
                # Get previous and next node variables
                if i > 0 and i < len(pattern.elements) - 1:
                    start_var = element.variable or f"_n{i-1}"
                    end_var = f"_n{i+1}"
                    self._compile_relationship_pattern(element, start_var, end_var)
    
    def _compile_node_pattern(self, node: NodePattern, default_var: str = None):
        """
        Compile node pattern.
        
        Generates ScanLabel or ScanAll operation.
        """
        variable = node.variable or default_var
        
        if not variable:
            variable = f"_anon{len(self.variables)}"
        
        self.variables[variable] = "node"
        
        # Generate scan operation
        if node.labels:
            # Scan by label
            for label in node.labels:
                op = {
                    "op": "ScanLabel",
                    "label": label,
                    "variable": variable
                }
                self.operations.append(op)
        else:
            # Scan all nodes
            op = {
                "op": "ScanAll",
                "type": "node",
                "variable": variable
            }
            self.operations.append(op)
        
        # Add property filters
        if node.properties:
            for prop_name, prop_value in node.properties.items():
                value = self._compile_expression(prop_value)
                op = {
                    "op": "Filter",
                    "variable": variable,
                    "property": prop_name,
                    "operator": "=",
                    "value": value
                }
                self.operations.append(op)
    
    def _compile_relationship_pattern(
        self,
        rel: RelationshipPattern,
        start_var: str,
        end_var: str
    ):
        """
        Compile relationship pattern.
        
        Generates Expand operation.
        """
        rel_var = rel.variable or f"_r{len(self.variables)}"
        self.variables[rel_var] = "relationship"
        
        op = {
            "op": "Expand",
            "from_variable": start_var,
            "to_variable": end_var,
            "rel_variable": rel_var,
            "direction": rel.direction
        }
        
        if rel.types:
            op["rel_types"] = rel.types
        
        if rel.properties:
            op["rel_properties"] = {
                k: self._compile_expression(v)
                for k, v in rel.properties.items()
            }
        
        self.operations.append(op)
    
    def _compile_where(self, where: WhereClause):
        """
        Compile WHERE clause.
        
        Generates Filter operations.
        """
        self._compile_where_expression(where.expression)
    
    def _compile_where_expression(self, expr):
        """Compile WHERE expression into filter operations."""
        if isinstance(expr, BinaryOpNode):
            if expr.operator.upper() in ('AND', 'OR'):
                # Logical operators - compile both sides
                self._compile_where_expression(expr.left)
                if expr.operator.upper() == 'AND':
                    self._compile_where_expression(expr.right)
                # OR would need more complex handling
            else:
                # Comparison operator
                left_info = self._analyze_expression(expr.left)
                right_value = self._compile_expression(expr.right)
                
                if left_info['type'] == 'property':
                    op = {
                        "op": "Filter",
                        "variable": left_info['variable'],
                        "property": left_info['property'],
                        "operator": expr.operator,
                        "value": right_value
                    }
                    self.operations.append(op)
        
        elif isinstance(expr, UnaryOpNode):
            if expr.operator.upper() == 'NOT':
                # NOT operation - would need negation support
                pass
    
    def _compile_return(self, ret: ReturnClause):
        """
        Compile RETURN clause.
        
        Generates Project, OrderBy, Limit operations.
        """
        # Project operation
        items = []
        for return_item in ret.items:
            item_info = {
                "expression": self._expression_to_string(return_item.expression)
            }
            if return_item.alias:
                item_info["alias"] = return_item.alias
            items.append(item_info)
        
        op = {
            "op": "Project",
            "items": items,
            "distinct": ret.distinct
        }
        self.operations.append(op)
        
        # OrderBy operation
        if ret.order_by:
            order_items = []
            for order_item in ret.order_by.items:
                order_items.append({
                    "expression": self._expression_to_string(order_item.expression),
                    "ascending": order_item.ascending
                })
            
            op = {
                "op": "OrderBy",
                "items": order_items
            }
            self.operations.append(op)
        
        # Skip operation
        if ret.skip is not None:
            op = {
                "op": "Skip",
                "count": ret.skip
            }
            self.operations.append(op)
        
        # Limit operation
        if ret.limit is not None:
            op = {
                "op": "Limit",
                "count": ret.limit
            }
            self.operations.append(op)
    
    def _compile_create(self, create: CreateClause):
        """
        Compile CREATE clause.
        
        Generates CreateNode and CreateRelationship operations.
        """
        for pattern in create.patterns:
            for element in pattern.elements:
                if isinstance(element, NodePattern):
                    props = {}
                    if element.properties:
                        props = {
                            k: self._compile_expression(v)
                            for k, v in element.properties.items()
                        }
                    
                    op = {
                        "op": "CreateNode",
                        "variable": element.variable,
                        "labels": element.labels,
                        "properties": props
                    }
                    self.operations.append(op)
                
                elif isinstance(element, RelationshipPattern):
                    # Would need to track start/end nodes
                    pass
    
    def _compile_delete(self, delete: DeleteClause):
        """
        Compile DELETE clause.
        
        Generates Delete operations.
        """
        for expr in delete.expressions:
            if isinstance(expr, VariableNode):
                op = {
                    "op": "Delete",
                    "variable": expr.name,
                    "detach": delete.detach
                }
                self.operations.append(op)
    
    def _compile_set(self, set_clause: SetClause):
        """
        Compile SET clause.
        
        Generates SetProperty operations.
        """
        for prop_expr, value_expr in set_clause.items:
            prop_info = self._analyze_expression(prop_expr)
            value = self._compile_expression(value_expr)
            
            if prop_info['type'] == 'property':
                op = {
                    "op": "SetProperty",
                    "variable": prop_info['variable'],
                    "property": prop_info['property'],
                    "value": value
                }
                self.operations.append(op)
    
    def _compile_expression(self, expr) -> Any:
        """
        Compile expression to a value.
        
        Returns the evaluated value or expression string.
        """
        if isinstance(expr, LiteralNode):
            return expr.value
        
        elif isinstance(expr, VariableNode):
            return {"var": expr.name}
        
        elif isinstance(expr, ParameterNode):
            return {"param": expr.name}
        
        elif isinstance(expr, PropertyAccessNode):
            obj = self._compile_expression(expr.object)
            if isinstance(obj, dict) and "var" in obj:
                return {"property": f"{obj['var']}.{expr.property}"}
            return {"property": f"{expr.property}"}
        
        elif isinstance(expr, BinaryOpNode):
            return {
                "op": expr.operator,
                "left": self._compile_expression(expr.left),
                "right": self._compile_expression(expr.right)
            }
        
        elif isinstance(expr, ListNode):
            return [self._compile_expression(e) for e in expr.elements]
        
        elif isinstance(expr, dict):
            # Already a map from parser
            return {k: self._compile_expression(v) for k, v in expr.items()}
        
        else:
            return str(expr)
    
    def _analyze_expression(self, expr) -> Dict[str, Any]:
        """
        Analyze expression to extract variable and property info.
        
        For example: n.age → {"type": "property", "variable": "n", "property": "age"}
        """
        if isinstance(expr, PropertyAccessNode):
            if isinstance(expr.object, VariableNode):
                return {
                    "type": "property",
                    "variable": expr.object.name,
                    "property": expr.property
                }
        
        elif isinstance(expr, VariableNode):
            return {
                "type": "variable",
                "variable": expr.name
            }
        
        return {"type": "unknown"}
    
    def _expression_to_string(self, expr) -> str:
        """Convert expression to string representation."""
        if isinstance(expr, VariableNode):
            return expr.name
        
        elif isinstance(expr, PropertyAccessNode):
            obj_str = self._expression_to_string(expr.object)
            return f"{obj_str}.{expr.property}"
        
        elif isinstance(expr, LiteralNode):
            return str(expr.value)
        
        elif isinstance(expr, FunctionCallNode):
            args = ", ".join(self._expression_to_string(arg) for arg in expr.arguments)
            return f"{expr.name}({args})"
        
        else:
            return str(expr)


# Convenience function
def compile_cypher(ast: QueryNode) -> List[Dict[str, Any]]:
    """
    Convenience function to compile Cypher AST to IR.
    
    Args:
        ast: QueryNode from parser
        
    Returns:
        List of IR operations
    """
    compiler = CypherCompiler()
    return compiler.compile(ast)
