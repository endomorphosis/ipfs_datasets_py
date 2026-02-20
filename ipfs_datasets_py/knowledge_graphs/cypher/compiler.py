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
    UnionClause,
    UnwindClause,
    WithClause,
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
    """Exception raised when Cypher compilation fails.
    
    This exception is raised when the compiler encounters invalid AST nodes,
    unsupported Cypher features, or semantic errors during compilation.
    """
    pass  # Simple exception class - no custom attributes needed


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
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as e:
            raise CypherCompileError(f"Compilation error: {e}") from e
    
    def _compile_clause(self, clause: Any) -> None:
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
        elif isinstance(clause, UnionClause):
            self._compile_union(clause)
        elif isinstance(clause, UnwindClause):
            self._compile_unwind(clause)
        elif isinstance(clause, WithClause):
            self._compile_with(clause)
        else:
            raise CypherCompileError(f"Unknown clause type: {type(clause)}")
    
    def _compile_match(self, match: MatchClause) -> None:
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
    
    def _compile_pattern(self, pattern: PatternNode, is_optional: bool = False) -> None:
        """
        Compile a graph pattern.
        
        Args:
            pattern: Pattern to compile
            is_optional: Whether this is from OPTIONAL MATCH
        """
        # First pass: track actual node variables used in pattern
        node_vars = []
        for i, element in enumerate(pattern.elements):
            if isinstance(element, NodePattern):
                # Determine the actual variable that will be used
                variable = element.variable or f"_n{i}"
                if not variable:
                    variable = f"_anon{len(self.variables)}"
                node_vars.append(variable)
            else:
                node_vars.append(None)  # Placeholder for non-node elements
        
        # Identify nodes that are targets of relationships (don't need ScanLabel)
        target_nodes = set()
        for i, element in enumerate(pattern.elements):
            if isinstance(element, RelationshipPattern):
                # The node after the relationship is a target
                if i + 1 < len(node_vars):
                    target_nodes.add(i + 1)
        
        # Second pass: compile elements with correct variable references
        node_index = 0
        for i, element in enumerate(pattern.elements):
            if isinstance(element, NodePattern):
                # Only compile node pattern if it's not a relationship target
                # OR if it has label/property constraints that need filtering
                is_target = i in target_nodes
                if not is_target or element.labels or element.properties:
                    # If it's a target with constraints, we still need to add filters
                    # but Expand will provide the nodes
                    if is_target:
                        # Register the variable but don't generate ScanLabel
                        variable = element.variable or f"_n{i}"
                        if not variable:
                            variable = f"_anon{len(self.variables)}"
                        self.variables[variable] = "node"
                        # Store the target node info for the relationship compilation
                        # Labels will be passed to Expand/OptionalExpand
                        # Property filters will be added after Expand
                        if element.properties:
                            for prop_name, prop_value in element.properties.items():
                                value = self._compile_expression(prop_value)
                                op = {
                                    "op": "Filter",
                                    "variable": variable,
                                    "property": prop_name,
                                    "operator": "=",
                                    "value": value
                                }
                                self.operations.append(op)
                    else:
                        # Not a target - compile normally with ScanLabel
                        self._compile_node_pattern(element, f"_n{i}", is_optional=is_optional)
                node_index += 1
            elif isinstance(element, RelationshipPattern):
                # Get previous and next node variables from tracked list
                if i > 0 and i < len(pattern.elements) - 1:
                    # Find the actual variable names from node patterns
                    start_var = node_vars[i-1] if i-1 < len(node_vars) else f"_n{i-1}"
                    end_var = node_vars[i+1] if i+1 < len(node_vars) else f"_n{i+1}"
                    # Get target node labels if target is a NodePattern
                    target_labels = None
                    if i + 1 < len(pattern.elements) and isinstance(pattern.elements[i+1], NodePattern):
                        target_labels = pattern.elements[i+1].labels
                    self._compile_relationship_pattern(element, start_var, end_var, 
                                                      is_optional=is_optional,
                                                      target_labels=target_labels)
    
    def _compile_node_pattern(self, node: NodePattern, default_var: Optional[str] = None, is_optional: bool = False) -> None:
        """
        Compile node pattern.
        
        Generates ScanLabel or ScanAll operation.
        
        Args:
            node: NodePattern to compile
            default_var: Default variable name if node doesn't have one
            is_optional: Whether this is from OPTIONAL MATCH
        """
        variable = node.variable or default_var
        
        if not variable:
            variable = f"_anon{len(self.variables)}"
        
        # Check if this variable already exists from a previous clause
        # Only skip scanning if:
        # 1. This is from an OPTIONAL MATCH (is_optional=True)
        # 2. AND the variable was already defined in a previous clause
        # This allows OPTIONAL MATCH to reuse variables from MATCH,
        # but doesn't break UNION queries where each branch is independent
        variable_exists = variable in self.variables
        should_skip_scan = variable_exists and is_optional
        
        if not should_skip_scan:
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
        
        # Add property filters (even if variable already exists)
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
        is_optional: bool = False,
        target_labels: Optional[List[str]] = None
    ) -> None:
        """
        Compile relationship pattern.
        
        Generates Expand or OptionalExpand operation.
        
        Args:
            rel: RelationshipPattern to compile
            start_var: Variable for start node
            end_var: Variable for end node
            is_optional: Whether this is from OPTIONAL MATCH
            target_labels: Labels for the target node (for filtering)
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
        
        # Add target node labels for filtering
        if target_labels:
            op["target_labels"] = target_labels
        
        self.operations.append(op)
    
    def _compile_where(self, where: WhereClause) -> None:
        """
        Compile WHERE clause.
        
        Generates Filter operations.
        """
        self._compile_where_expression(where.expression)
    
    def _compile_where_expression(self, expr: Any) -> None:
        """Compile WHERE expression into filter operations."""
        if isinstance(expr, BinaryOpNode):
            if expr.operator.upper() in ('AND', 'OR'):
                # Logical operators - compile both sides
                self._compile_where_expression(expr.left)
                if expr.operator.upper() == 'AND':
                    self._compile_where_expression(expr.right)
                # OR would need more complex handling
            else:
                # Comparison operator - can be complex expression
                left_info = self._analyze_expression(expr.left)
                
                # Check if it's a simple property comparison
                if left_info['type'] == 'property':
                    # Simple property comparison - use old format for backward compatibility
                    right_value = self._compile_expression(expr.right)
                    op = {
                        "op": "Filter",
                        "variable": left_info['variable'],
                        "property": left_info['property'],
                        "operator": expr.operator,
                        "value": right_value
                    }
                    self.operations.append(op)
                else:
                    # Complex expression (e.g., function call) - compile full expression
                    op = {
                        "op": "Filter",
                        "expression": {
                            "op": expr.operator,
                            "left": self._compile_expression(expr.left),
                            "right": self._compile_expression(expr.right)
                        }
                    }
                    self.operations.append(op)
        
        elif isinstance(expr, UnaryOpNode):
            if expr.operator.upper() == 'NOT':
                # NOT operation - compile as negated filter
                operand = expr.operand
                
                # Check if operand is a simple comparison
                if isinstance(operand, BinaryOpNode):
                    # Negate the comparison operator
                    negated_op = self._negate_operator(operand.operator)
                    if negated_op:
                        # Create negated filter directly
                        left_info = self._analyze_expression(operand.left)
                        
                        if left_info['type'] == 'property':
                            # Simple property comparison - use negated operator
                            right_value = self._compile_expression(operand.right)
                            op = {
                                "op": "Filter",
                                "variable": left_info['variable'],
                                "property": left_info['property'],
                                "operator": negated_op,
                                "value": right_value
                            }
                            self.operations.append(op)
                        else:
                            # Complex expression - wrap in NOT
                            op = {
                                "op": "Filter",
                                "expression": {
                                    "op": "NOT",
                                    "operand": self._compile_expression(operand)
                                }
                            }
                            self.operations.append(op)
                    else:
                        # Cannot negate this operator - use NOT wrapper
                        op = {
                            "op": "Filter",
                            "expression": {
                                "op": "NOT",
                                "operand": self._compile_expression(operand)
                            }
                        }
                        self.operations.append(op)
                else:
                    # Not a simple comparison - wrap entire expression in NOT
                    op = {
                        "op": "Filter",
                        "expression": {
                            "op": "NOT",
                            "operand": self._compile_expression(operand)
                        }
                    }
                    self.operations.append(op)
    
    def _compile_return(self, ret: ReturnClause) -> None:
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
                    "expression": self._compile_expression(order_item.expression),
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
    
    def _compile_create(self, create: CreateClause) -> None:
        """
        Compile CREATE clause.
        
        Generates CreateNode and CreateRelationship operations.
        """
        for pattern in create.patterns:
            # Track node variables as we process the pattern
            # Pattern elements alternate: node, rel, node, rel, node...
            prev_node_var = None
            
            for i, element in enumerate(pattern.elements):
                if isinstance(element, NodePattern):
                    props = {}
                    if element.properties:
                        props = {
                            k: self._compile_expression(v)
                            for k, v in element.properties.items()
                        }
                    
                    # Only create node if it has a variable (not anonymous)
                    # or if it's the first/last node in pattern
                    if element.variable:
                        op = {
                            "op": "CreateNode",
                            "variable": element.variable,
                            "labels": element.labels,
                            "properties": props
                        }
                        self.operations.append(op)
                        prev_node_var = element.variable
                    else:
                        # Anonymous node - generate variable
                        anon_var = f"_n{len(self.variables)}"
                        self.variables[anon_var] = "node"
                        op = {
                            "op": "CreateNode",
                            "variable": anon_var,
                            "labels": element.labels,
                            "properties": props
                        }
                        self.operations.append(op)
                        prev_node_var = anon_var
                
                elif isinstance(element, RelationshipPattern):
                    # Relationship creation in CREATE clause
                    # Need to get the next node (should be at i+1)
                    if i + 1 < len(pattern.elements) and isinstance(pattern.elements[i + 1], NodePattern):
                        next_node = pattern.elements[i + 1]
                        
                        # Determine end node variable
                        if next_node.variable:
                            end_node_var = next_node.variable
                        else:
                            # Will be created as anonymous in next iteration
                            end_node_var = f"_n{len(self.variables) + 1}"
                        
                        # Compile relationship properties
                        rel_props = {}
                        if element.properties:
                            rel_props = {
                                k: self._compile_expression(v)
                                for k, v in element.properties.items()
                            }
                        
                        # Determine relationship type
                        rel_type = element.types[0] if element.types else "RELATED_TO"
                        
                        # Create relationship operation
                        rel_var = element.variable or f"_r{len(self.variables)}"
                        
                        # Handle relationship direction
                        if element.direction == 'left':
                            # Pattern: (a)<-[r]-(b) means relationship from b to a
                            start_var = end_node_var
                            end_var = prev_node_var
                        else:
                            # Pattern: (a)-[r]->(b) or (a)-[r]-(b)
                            # Default: relationship from a to b
                            start_var = prev_node_var
                            end_var = end_node_var
                        
                        op = {
                            "op": "CreateRelationship",
                            "variable": rel_var,
                            "rel_type": rel_type,
                            "start_variable": start_var,
                            "end_variable": end_var,
                            "properties": rel_props
                        }
                        self.operations.append(op)
                        
                        # Track relationship variable
                        self.variables[rel_var] = "relationship"
                    else:
                        raise CypherCompileError(
                            "Relationship pattern must be followed by a node pattern in CREATE clause"
                        )
    
    def _compile_delete(self, delete: DeleteClause) -> None:
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
    
    def _compile_set(self, set_clause: SetClause) -> None:
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
    
    def _compile_union(self, union_clause: UnionClause) -> None:
        """
        Compile UNION or UNION ALL clause.
        
        Generates Union operation to combine result sets.
        """
        op = {
            "op": "Union",
            "all": union_clause.all  # True for UNION ALL, False for UNION
        }
        self.operations.append(op)

    def _compile_unwind(self, unwind: UnwindClause) -> None:
        """Compile UNWIND clause.

        Generates an ``Unwind`` IR operation that expands a list expression
        into individual rows, binding each element to ``unwind.variable``.

        IR emitted::

            {"op": "Unwind", "expression": <compiled-expr>, "variable": "<var>"}
        """
        op = {
            "op": "Unwind",
            "expression": self._compile_expression(unwind.expression),
            "variable": unwind.variable,
        }
        self.operations.append(op)

    def _compile_with(self, with_clause: WithClause) -> None:
        """Compile WITH clause.

        A WITH clause is semantically a RETURN-then-continue: it projects
        columns and (optionally) filters them before the next query part.

        IR emitted:

        * ``{"op": "WithProject", ...}`` — like Project but writes rows to
          *bindings* instead of *final_results*, so subsequent Filter/Project
          ops can see the projected names (e.g. ``age`` rather than ``n.age``).
        * Optional ``{"op": "Filter", ...}`` from the WHERE clause.
        """
        # Compile WITH items — compile expressions the same way as RETURN
        items = []
        for item in with_clause.items:
            expr = self._compile_expression(item.expression) if item.expression is not None else None
            alias = item.alias if item.alias else self._expression_to_string(item.expression)
            items.append({"expression": expr, "alias": alias})

        op: Dict[str, Any] = {
            "op": "WithProject",
            "items": items,
            "distinct": with_clause.distinct,
        }
        if with_clause.skip is not None:
            op["skip"] = with_clause.skip
        if with_clause.limit is not None:
            op["limit"] = with_clause.limit
        self.operations.append(op)

        # Apply WHERE if present (operates on the projected bindings)
        if with_clause.where is not None:
            self._compile_where(with_clause.where)

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
        
        elif isinstance(expr, UnaryOpNode):
            # Handle unary operators like NOT
            return {
                "op": expr.operator.upper(),
                "operand": self._compile_expression(expr.operand)
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
    
    def _negate_operator(self, operator: str) -> Optional[str]:
        """
        Get the negated form of a comparison operator.
        
        Args:
            operator: Original comparison operator
            
        Returns:
            Negated operator, or None if cannot be negated simply
            
        Examples:
            > becomes <=
            >= becomes <
            = becomes <>
            <> becomes =
        """
        negation_map = {
            '>': '<=',
            '>=': '<',
            '<': '>=',
            '<=': '>',
            '=': '<>',
            '==': '<>',
            '<>': '=',
            '!=': '='
        }
        return negation_map.get(operator)
    
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
