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
        from .ast import UnionClause
        
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
        elif isinstance(clause, UnionClause):
            self._compile_union(clause)
        else:
            raise CypherCompileError(f"Unknown clause type: {type(clause)}")
    
    def _compile_match(self, match: MatchClause):
        """
        Compile MATCH or OPTIONAL MATCH clause.
        
        Generates:
        - ScanLabel operations for labeled nodes
        - ScanAll for unlabeled nodes
        - Expand operations for relationships (or OptionalExpand if optional)
        - Filter operations for WHERE
        """
        # Store whether this is an optional match for relationship compilation
        is_optional = match.optional
        
        for pattern in match.patterns:
            self._compile_pattern(pattern, is_optional=is_optional)
        
        # Compile WHERE if present
        if match.where:
            self._compile_where(match.where)
    
    def _compile_pattern(self, pattern: PatternNode, is_optional: bool = False):
        """
        Compile a graph pattern.
        
        Args:
            pattern: Pattern to compile
            is_optional: Whether this is from OPTIONAL MATCH
        """
        for i, element in enumerate(pattern.elements):
            if isinstance(element, NodePattern):
                self._compile_node_pattern(element, f"_n{i}")
            elif isinstance(element, RelationshipPattern):
                # Get previous and next node variables
                if i > 0 and i < len(pattern.elements) - 1:
                    start_var = element.variable or f"_n{i-1}"
                    end_var = f"_n{i+1}"
                    self._compile_relationship_pattern(element, start_var, end_var, is_optional=is_optional)
    
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
        end_var: str,
        is_optional: bool = False
    ):
        """
        Compile relationship pattern.
        
        Generates Expand or OptionalExpand operation.
        
        Args:
            rel: RelationshipPattern to compile
            start_var: Variable for start node
            end_var: Variable for end node
            is_optional: Whether this is from OPTIONAL MATCH
        """
        rel_var = rel.variable or f"_r{len(self.variables)}"
        self.variables[rel_var] = "relationship"
        
        # Choose operation type based on whether it's optional
        op_type = "OptionalExpand" if is_optional else "Expand"
        
        op = {
            "op": op_type,
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
        
        Generates Project/Aggregate, OrderBy, Limit operations.
        """
        # Check if any return items are aggregations
        has_aggregation = any(
            self._is_aggregation(return_item.expression)
            for return_item in ret.items
        )
        
        if has_aggregation:
            # Aggregate operation
            aggregations = []
            group_by = []
            
            for return_item in ret.items:
                if self._is_aggregation(return_item.expression):
                    # This is an aggregation function
                    agg_info = self._compile_aggregation(return_item.expression)
                    if return_item.alias:
                        agg_info["alias"] = return_item.alias
                    else:
                        agg_info["alias"] = self._expression_to_string(return_item.expression)
                    aggregations.append(agg_info)
                else:
                    # This is a grouping key
                    group_expr = self._expression_to_string(return_item.expression)
                    group_by.append({
                        "expression": group_expr,
                        "alias": return_item.alias or group_expr
                    })
            
            op = {
                "op": "Aggregate",
                "aggregations": aggregations,
                "group_by": group_by,
                "distinct": ret.distinct
            }
            self.operations.append(op)
        else:
            # Regular project operation
            items = []
            for return_item in ret.items:
                item_info = {
                    "expression": self._compile_expression(return_item.expression)
                }
                if return_item.alias:
                    item_info["alias"] = return_item.alias
                else:
                    # Generate default alias from expression
                    item_info["alias"] = self._expression_to_string(return_item.expression)
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
    
    def _compile_union(self, union_clause):
        """
        Compile UNION or UNION ALL clause.
        
        Generates Union operation to combine result sets.
        """
        from .ast import UnionClause
        
        op = {
            "op": "Union",
            "all": union_clause.all  # True for UNION ALL, False for UNION
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
        
        elif isinstance(expr, FunctionCallNode):
            # Compile function calls (e.g., toLower, toUpper, etc.)
            return {
                "function": expr.name,
                "args": [self._compile_expression(arg) for arg in expr.arguments]
            }
        
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
        from .ast import CaseExpressionNode
        
        if isinstance(expr, VariableNode):
            return expr.name
        
        elif isinstance(expr, PropertyAccessNode):
            obj_str = self._expression_to_string(expr.object)
            return f"{obj_str}.{expr.property}"
        
        elif isinstance(expr, LiteralNode):
            if isinstance(expr.value, str):
                return f"'{expr.value}'"
            return str(expr.value)
        
        elif isinstance(expr, FunctionCallNode):
            args = ", ".join(self._expression_to_string(arg) for arg in expr.arguments)
            return f"{expr.name}({args})"
        
        elif isinstance(expr, CaseExpressionNode):
            # Serialize CASE expression as a special format
            # CASE:[test_expr]|WHEN:cond:result|...|ELSE:else_result|END
            parts = ["CASE"]
            
            if expr.test_expression:
                parts.append(f"TEST:{self._expression_to_string(expr.test_expression)}")
            
            for when_clause in expr.when_clauses:
                cond_str = self._expression_to_string(when_clause.condition)
                result_str = self._expression_to_string(when_clause.result)
                parts.append(f"WHEN:{cond_str}:THEN:{result_str}")
            
            if expr.else_result:
                else_str = self._expression_to_string(expr.else_result)
                parts.append(f"ELSE:{else_str}")
            
            parts.append("END")
            return "|".join(parts)
        
        else:
            return str(expr)
    
    def _is_aggregation(self, expr) -> bool:
        """
        Check if an expression is an aggregation function.
        
        Args:
            expr: Expression node to check
            
        Returns:
            True if expression is an aggregation function
        """
        if not isinstance(expr, FunctionCallNode):
            return False
        
        aggregation_functions = {
            'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'COLLECT',
            'STDEV', 'STDEVP', 'PERCENTILECONT', 'PERCENTILEDISC'
        }
        
        return expr.name.upper() in aggregation_functions
    
    def _compile_aggregation(self, func_node: FunctionCallNode) -> Dict[str, Any]:
        """
        Compile an aggregation function.
        
        Args:
            func_node: FunctionCallNode representing aggregation
            
        Returns:
            Dictionary with aggregation info for IR
        """
        func_name = func_node.name.upper()
        
        # Handle special case: COUNT(*)
        if func_name == 'COUNT' and len(func_node.arguments) == 1:
            arg = func_node.arguments[0]
            if isinstance(arg, VariableNode) and arg.name == '*':
                return {
                    "function": "COUNT",
                    "expression": "*",
                    "distinct": func_node.distinct
                }
        
        # Regular aggregation
        if func_node.arguments:
            arg_expr = self._expression_to_string(func_node.arguments[0])
        else:
            arg_expr = "*"
        
        return {
            "function": func_name,
            "expression": arg_expr,
            "distinct": func_node.distinct
        }



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
