"""
Query Executor for Graph Database

This module provides the query execution layer that routes queries to
appropriate backends and manages query lifecycle.

Phase 1: Basic routing between IR and Cypher (stub)
Phase 2: Full Cypher query parsing and execution
Phase 3: Query optimization and caching
"""

import logging
import re
from typing import Any, Dict, List, Optional

from ..neo4j_compat.result import Result, Record
from ..neo4j_compat.types import Node, Relationship, Path

logger = logging.getLogger(__name__)


class QueryExecutor:
    """
    Executes queries against the graph database.
    
    Handles query routing, parameter validation, and result formatting.
    
    Phase 1: Routes between IR queries and Cypher (stub)
    Phase 2: Full Cypher execution via parser
    Phase 3: Query optimization and plan caching
    """
    
    # Cypher keywords for detection
    CYPHER_KEYWORDS = {
        'MATCH', 'CREATE', 'MERGE', 'DELETE', 'REMOVE', 'SET',
        'RETURN', 'WITH', 'WHERE', 'ORDER BY', 'LIMIT', 'SKIP',
        'UNION', 'UNWIND', 'CALL', 'YIELD', 'FOREACH'
    }
    
    def __init__(self, graph_engine: Optional['GraphEngine'] = None):
        """
        Initialize the query executor.
        
        Args:
            graph_engine: GraphEngine instance for executing operations
        """
        self.graph_engine = graph_engine
        self._query_cache = {}
        logger.debug("QueryExecutor initialized")
    
    def execute(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        **options
    ) -> Result:
        """
        Execute a query and return results.
        
        Args:
            query: Query string (Cypher, IR, or simple pattern)
            parameters: Query parameters
            **options: Additional execution options
            
        Returns:
            Result object with records
            
        Example:
            result = executor.execute("MATCH (n) RETURN n LIMIT 10")
            for record in result:
                print(record["n"])
        """
        parameters = parameters or {}
        
        logger.info("Executing query: %s", query[:100])
        logger.debug("Parameters: %s", parameters)
        
        # Validate parameters
        self._validate_parameters(parameters)
        
        # Detect query type and route
        if self._is_cypher_query(query):
            return self._execute_cypher(query, parameters, **options)
        elif self._is_ir_query(query):
            return self._execute_ir(query, parameters, **options)
        else:
            return self._execute_simple(query, parameters, **options)
    
    def _is_cypher_query(self, query: str) -> bool:
        """
        Detect if query is Cypher syntax.
        
        Args:
            query: Query string
            
        Returns:
            True if Cypher query detected
        """
        query_upper = query.strip().upper()
        
        # Check for Cypher keywords at start
        for keyword in self.CYPHER_KEYWORDS:
            if query_upper.startswith(keyword):
                return True
        
        # Check for Cypher patterns (nodes and relationships)
        if '()' in query or '[]' in query or '-->' in query or '<--' in query:
            return True
        
        return False
    
    def _is_ir_query(self, query: str) -> bool:
        """
        Detect if query is IR (Intermediate Representation) syntax.
        
        Args:
            query: Query string
            
        Returns:
            True if IR query detected
        """
        # IR queries are typically JSON-like structures
        query_stripped = query.strip()
        return query_stripped.startswith('{') and query_stripped.endswith('}')
    
    def _execute_cypher(
        self,
        query: str,
        parameters: Dict[str, Any],
        **options
    ) -> Result:
        """
        Execute a Cypher query.
        
        Phase 2: Parses and executes via CypherParser + CypherCompiler
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            **options: Execution options
            
        Returns:
            Result object
        """
        logger.info("Executing Cypher query: %s", query[:50])
        
        try:
            # Import parser and compiler
            from ..cypher import CypherParser, CypherCompiler
            
            # Parse query to AST
            parser = CypherParser()
            ast = parser.parse(query)
            logger.debug("Parsed query into AST with %d clauses", len(ast.clauses))
            
            # Compile AST to IR
            compiler = CypherCompiler()
            ir_operations = compiler.compile(ast)
            logger.debug("Compiled to %d IR operations", len(ir_operations))
            
            # Execute IR operations
            records = self._execute_ir_operations(ir_operations, parameters)
            
            summary = {
                "query_type": "Cypher",
                "query": query[:100],
                "ir_operations": len(ir_operations),
                "records_returned": len(records)
            }
            
            return Result(records, summary=summary)
            
        except Exception as e:
            logger.error("Cypher execution failed: %s", e)
            # Return error as empty result with error info
            summary = {
                "query_type": "Cypher",
                "query": query[:100],
                "error": str(e)
            }
            return Result([], summary=summary)
    
    def _execute_ir(
        self,
        query: str,
        parameters: Dict[str, Any],
        **options
    ) -> Result:
        """
        Execute an IR (Intermediate Representation) query.
        
        Args:
            query: IR query (JSON format)
            parameters: Query parameters
            **options: Execution options
            
        Returns:
            Result object
        """
        logger.debug("Executing IR query")
        
        # Phase 1: Stub - return empty result
        # TODO: Integrate with existing IR executor in search/graphrag_query
        
        records = []
        summary = {
            "query_type": "IR",
            "query": query[:100],
            "execution_time_ms": 0
        }
        
        return Result(records, summary=summary)
    
    def _execute_simple(
        self,
        query: str,
        parameters: Dict[str, Any],
        **options
    ) -> Result:
        """
        Execute a simple query pattern.
        
        For basic operations like "get node by id".
        
        Args:
            query: Simple query string
            parameters: Query parameters
            **options: Execution options
            
        Returns:
            Result object
        """
        logger.debug("Executing simple query")
        
        # Phase 1: Return empty result
        records = []
        summary = {
            "query_type": "simple",
            "query": query[:100]
        }
        
        return Result(records, summary=summary)
    
    def _execute_ir_operations(
        self,
        operations: List[Dict[str, Any]],
        parameters: Dict[str, Any]
    ) -> List[Record]:
        """
        Execute IR operations using GraphEngine.
        
        Args:
            operations: List of IR operations
            parameters: Query parameters for substitution
            
        Returns:
            List of Record objects
        """
        if not self.graph_engine:
            logger.warning("No GraphEngine available, returning empty results")
            return []
        
        # Track intermediate results
        result_set = {}  # variable → values
        final_results = []
        
        for op in operations:
            op_type = op.get("op")
            
            if op_type == "ScanLabel":
                # Scan nodes by label
                label = op.get("label")
                variable = op.get("variable")
                nodes = self.graph_engine.find_nodes(labels=[label])
                result_set[variable] = nodes
                logger.debug("ScanLabel %s: found %d nodes", label, len(nodes))
            
            elif op_type == "ScanAll":
                # Scan all nodes
                variable = op.get("variable")
                nodes = self.graph_engine.find_nodes()
                result_set[variable] = nodes
                logger.debug("ScanAll: found %d nodes", len(nodes))
            
            elif op_type == "Filter":
                # Apply filter to variable
                # Check for complex expression format (new)
                if "expression" in op:
                    # Complex expression filter (e.g., function calls, complex operators)
                    expression = op["expression"]
                    
                    # Filter all variables in result_set
                    filtered_results = []
                    
                    # Get all current variable bindings
                    if hasattr(self, '_bindings') and self._bindings:
                        # Use bindings from Expand
                        for binding in self._bindings:
                            # Evaluate expression against this binding
                            result = self._evaluate_compiled_expression(expression, binding)
                            if result:  # If expression evaluates to truthy value
                                filtered_results.append(binding)
                        self._bindings = filtered_results
                    else:
                        # Single variable case
                        for var_name, items in list(result_set.items()):
                            filtered_items = []
                            for item in items:
                                binding = {var_name: item}
                                result_val = self._evaluate_compiled_expression(expression, binding)
                                if result_val:  # If expression evaluates to truthy value
                                    filtered_items.append(item)
                            result_set[var_name] = filtered_items
                    
                    logger.debug("Filter (complex expression): filtered to %d results", 
                               len(filtered_results) if filtered_results else sum(len(v) for v in result_set.values()))
                
                else:
                    # Simple property filter (old format)
                    variable = op.get("variable")
                    property_name = op.get("property")
                    operator = op.get("operator")
                    value = self._resolve_value(op.get("value"), parameters)
                    
                    if variable in result_set:
                        filtered = []
                        for item in result_set[variable]:
                            item_value = item.get(property_name)
                            if self._apply_operator(item_value, operator, value):
                                filtered.append(item)
                        result_set[variable] = filtered
                        logger.debug("Filter %s.%s %s %s: %d results",
                                   variable, property_name, operator, value, len(filtered))
            
            elif op_type == "Expand":
                # Expand relationships from nodes
                from_var = op.get("from_variable")
                to_var = op.get("to_variable")
                rel_var = op.get("rel_variable")
                direction = op.get("direction", "out")
                rel_types = op.get("rel_types")
                target_labels = op.get("target_labels")  # Labels for target node filtering
                
                # Convert Cypher direction to graph engine direction
                if direction == "right":
                    direction = "out"
                elif direction == "left":
                    direction = "in"
                
                if from_var not in result_set:
                    logger.warning("Expand: source variable %s not found", from_var)
                    continue
                
                # Collect new bindings with relationships
                new_results = []
                
                for from_node in result_set[from_var]:
                    # Get relationships for this node
                    rels = self.graph_engine.get_relationships(
                        from_node.id,
                        direction=direction,
                        rel_type=rel_types[0] if rel_types else None
                    )
                    
                    for rel in rels:
                        # Get target node
                        if direction == "in":
                            target_id = rel._start_node
                        else:
                            target_id = rel._end_node
                        
                        target_node = self.graph_engine.get_node(target_id)
                        if not target_node:
                            continue
                        
                        # Filter by target labels if specified
                        if target_labels:
                            node_labels = getattr(target_node, 'labels', [])
                            if not any(label in node_labels for label in target_labels):
                                continue
                        
                        # Create binding with relationship and target node
                        # Store as tuple (from_node, relationship, to_node)
                        new_results.append({
                            from_var: from_node,
                            rel_var: rel,
                            to_var: target_node
                        })
                
                # Update result_set with expanded results
                # Need to restructure result_set to handle multiple variables
                if new_results:
                    # Merge all variables into result_set
                    for binding in new_results:
                        for var, val in binding.items():
                            if var not in result_set:
                                result_set[var] = []
                            if val not in result_set[var]:
                                result_set[var].append(val)
                    
                    # Store bindings for projection
                    if not hasattr(self, '_bindings'):
                        self._bindings = []
                    self._bindings = new_results
                
                logger.debug("Expand %s-[%s]->%s: found %d relationships",
                           from_var, rel_var, to_var, len(new_results))
            
            elif op_type == "OptionalExpand":
                # Optional expand - left join semantics
                # Preserve rows even when no relationships match
                from_var = op.get("from_variable")
                to_var = op.get("to_variable")
                rel_var = op.get("rel_variable")
                direction = op.get("direction", "out")
                rel_types = op.get("rel_types")
                target_labels = op.get("target_labels")  # Labels for target node filtering
                
                # Convert Cypher direction to graph engine direction
                if direction == "right":
                    direction = "out"
                elif direction == "left":
                    direction = "in"
                
                if from_var not in result_set:
                    logger.warning("OptionalExpand: source variable %s not found", from_var)
                    continue
                
                # Collect new bindings with relationships
                new_results = []
                
                for from_node in result_set[from_var]:
                    # Get relationships for this node
                    rels = self.graph_engine.get_relationships(
                        from_node.id,
                        direction=direction,
                        rel_type=rel_types[0] if rel_types else None
                    )
                    
                    matched = False
                    if rels:
                        # Found relationships - add them
                        for rel in rels:
                            # Get target node
                            if direction == "in":
                                target_id = rel._start_node
                            else:
                                target_id = rel._end_node
                            
                            target_node = self.graph_engine.get_node(target_id)
                            if not target_node:
                                continue
                            
                            # Filter by target labels if specified
                            if target_labels:
                                node_labels = getattr(target_node, 'labels', [])
                                if not any(label in node_labels for label in target_labels):
                                    continue
                            
                            # Create binding with relationship and target node
                            new_results.append({
                                from_var: from_node,
                                rel_var: rel,
                                to_var: target_node
                            })
                            matched = True
                    
                    if not matched:
                        # No relationships found - preserve row with NULLs (left join)
                        new_results.append({
                            from_var: from_node,
                            rel_var: None,
                            to_var: None
                        })
                
                # Update result_set with expanded results
                if new_results:
                    # Merge all variables into result_set
                    for binding in new_results:
                        for var, val in binding.items():
                            if var not in result_set:
                                result_set[var] = []
                            if val is not None and val not in result_set[var]:
                                result_set[var].append(val)
                    
                    # Store bindings for projection
                    if not hasattr(self, '_bindings'):
                        self._bindings = []
                    self._bindings = new_results
                
                logger.debug("OptionalExpand %s-[%s]->%s: found %d relationships (including NULL rows)",
                           from_var, rel_var, to_var, len(new_results))
            
            elif op_type == "Aggregate":
                # Aggregate operation (COUNT, SUM, AVG, MIN, MAX, COLLECT)
                aggregations = op.get("aggregations", [])
                group_by = op.get("group_by", [])
                
                # Get all current bindings
                if hasattr(self, '_bindings') and self._bindings:
                    data_rows = self._bindings
                else:
                    # Create bindings from result_set
                    data_rows = []
                    if result_set:
                        # Combine all variables into rows
                        var_names = list(result_set.keys())
                        if var_names:
                            first_var = var_names[0]
                            for item in result_set[first_var]:
                                row = {first_var: item}
                                data_rows.append(row)
                
                # Group data
                if group_by:
                    # Group by specified keys
                    groups = {}
                    for row in data_rows:
                        # Build group key
                        group_key_parts = []
                        for group_spec in group_by:
                            expr = group_spec["expression"]
                            value = self._evaluate_expression(expr, row)
                            group_key_parts.append(str(value))
                        group_key = tuple(group_key_parts)
                        
                        if group_key not in groups:
                            groups[group_key] = []
                        groups[group_key].append(row)
                else:
                    # Single group (all rows)
                    groups = {(): data_rows}
                
                # Compute aggregations for each group
                agg_results = []
                for group_key, group_rows in groups.items():
                    result_row = {}
                    
                    # Add group by values
                    for i, group_spec in enumerate(group_by):
                        alias = group_spec["alias"]
                        expr = group_spec["expression"]
                        value = self._evaluate_expression(expr, group_rows[0])
                        result_row[alias] = value
                    
                    # Compute aggregations
                    for agg_spec in aggregations:
                        func = agg_spec["function"]
                        expr = agg_spec["expression"]
                        alias = agg_spec["alias"]
                        distinct = agg_spec.get("distinct", False)
                        
                        # Extract values for aggregation
                        if expr == "*":
                            values = group_rows
                        else:
                            values = [self._evaluate_expression(expr, row) for row in group_rows]
                            # Filter out None values
                            values = [v for v in values if v is not None]
                        
                        # Apply DISTINCT if requested
                        if distinct and expr != "*":
                            values = list(set(values))
                        
                        # Compute aggregation
                        agg_value = self._compute_aggregation(func, values)
                        result_row[alias] = agg_value
                    
                    agg_results.append(result_row)
                
                # Convert to Records
                for row in agg_results:
                    keys = list(row.keys())
                    values = list(row.values())
                    final_results.append(Record(keys, values))
                
                logger.debug("Aggregate: %d groups, %d results", len(groups), len(final_results))
            
            elif op_type == "Union":
                # Union operation - combines result sets
                # For UNION, remove duplicates; for UNION ALL, keep all
                all_flag = op.get("all", False)
                
                # Store current results as first part
                first_results = final_results.copy()
                
                # Clear for next part (operations after Union will populate)
                final_results = []
                
                # Mark that we need to merge later
                if not hasattr(self, '_union_parts'):
                    self._union_parts = []
                self._union_parts.append({
                    'results': first_results,
                    'all': all_flag
                })
                
                logger.debug("Union: stored %d results from first part (all=%s)",
                           len(first_results), all_flag)
            
            elif op_type == "Project":
                # Project fields
                items = op.get("items", [])
                
                # Use bindings if available (from Expand operations)
                if hasattr(self, '_bindings') and self._bindings:
                    for binding in self._bindings:
                        record_data = {}
                        for item in items:
                            expr = item.get("expression")
                            alias = item.get("alias", expr if isinstance(expr, str) else "result")
                            
                            # Evaluate expression against binding
                            value = self._evaluate_compiled_expression(expr, binding)
                            # Always add value, even if None
                            record_data[alias] = value
                        
                        # Always create record, even if all values are None
                        keys = list(record_data.keys())
                        values = list(record_data.values())
                        final_results.append(Record(keys, values))
                else:
                    # Fallback to old logic for simple queries
                    for var_name, values in result_set.items():
                        for value in values:
                            record_data = {}
                            for item in items:
                                expr = item.get("expression")
                                alias = item.get("alias", expr if isinstance(expr, str) else "result")
                                
                                # Create binding for evaluation
                                binding = {var_name: value}
                                result_value = self._evaluate_compiled_expression(expr, binding)
                                # Always add value, even if None
                                record_data[alias] = result_value
                            
                            # Always create record, even if all values are None
                            keys = list(record_data.keys())
                            values = list(record_data.values())
                            final_results.append(Record(keys, values))
                
                logger.debug("Project: %d results", len(final_results))
            
            elif op_type == "Limit":
                # Limit results
                count = op.get("count")
                final_results = final_results[:count]
                logger.debug("Limit: keeping %d results", len(final_results))
            
            elif op_type == "Skip":
                # Skip results
                count = op.get("count")
                final_results = final_results[count:]
                logger.debug("Skip: %d results remaining", len(final_results))
            
            elif op_type == "OrderBy":
                # Order results by specified expressions
                order_items = op.get("items", [])
                
                if not order_items:
                    logger.debug("OrderBy: no items specified")
                    continue
                
                # Sort final_results (which should be a list of Record objects)
                if not final_results:
                    logger.debug("OrderBy: no results to sort")
                    continue
                
                def make_sort_key(record):
                    """Create a sort key tuple for a record."""
                    key_parts = []
                    for item in order_items:
                        expr = item["expression"]
                        ascending = item.get("ascending", True)
                        
                        # Evaluate the expression - could be string or compiled dict
                        if isinstance(expr, dict):
                            # Check if it's a simple property expression
                            if 'property' in expr and len(expr) == 1:
                                # Simple property like {"property": "n.age"}
                                # Just get it directly from the record
                                prop_name = expr['property']
                                value = record.get(prop_name)
                            else:
                                # Complex expression (e.g., function call)
                                # Create binding from record data
                                binding = record._data.copy() if hasattr(record, '_data') else {}
                                
                                # Also add direct values if they're Node/Relationship objects
                                for key, val in binding.items():
                                    # If value is a Node/Relationship, add it as a variable too
                                    if hasattr(val, 'labels') or hasattr(val, 'type'):
                                        # Extract variable name (e.g., "n" from "n.name")
                                        if '.' in key:
                                            var_name = key.split('.')[0]
                                            binding[var_name] = val
                                
                                value = self._evaluate_compiled_expression(expr, binding)
                        elif isinstance(expr, str):
                            # String expression (legacy)
                            # Get the value for this expression
                            if '.' in expr:
                                # Property access like "n.age"
                                parts = expr.split('.', 1)
                                var_name = parts[0]
                                prop_name = parts[1]
                                
                                # Get the value from the record
                                try:
                                    value = record.get(expr)  # Try direct access first
                                    if value is None and var_name in record._values:
                                        # Try to access as object property
                                        obj = record._values.get(var_name)
                                        if hasattr(obj, 'properties') and prop_name in obj.properties:
                                            value = obj.properties[prop_name]
                                        elif hasattr(obj, prop_name):
                                            value = getattr(obj, prop_name)
                                except:
                                    value = None
                            else:
                                # Simple alias like "count"
                                value = record.get(expr)
                        else:
                            value = None
                        
                        # Handle None values (sort them to the end)
                        if value is None:
                            value = (1, None)  # Tuple to sort Nones last
                        else:
                            value = (0, value)
                        
                        # Invert for descending
                        if not ascending:
                            # For descending, we need to negate numbers or reverse strings
                            if isinstance(value[1], (int, float)):
                                value = (value[0], -value[1] if value[1] is not None else None)
                            elif isinstance(value[1], str):
                                # Reverse string comparison by using reversed tuple
                                value = (value[0], value[1])  # Will handle with reverse=True
                        
                        key_parts.append(value)
                    
                    return tuple(key_parts)
                
                # Sort the results
                try:
                    # Always sort ascending - we've already negated DESC values in make_sort_key
                    final_results.sort(key=make_sort_key)
                    
                    logger.debug("OrderBy: sorted %d results by %d expressions", 
                                len(final_results), len(order_items))
                except Exception as e:
                    logger.warning("OrderBy: failed to sort results: %s", e)
                    # Continue without sorting if there's an error
            
            elif op_type == "CreateNode":
                # Create node
                variable = op.get("variable")
                labels = op.get("labels", [])
                properties = op.get("properties", {})
                
                node = self.graph_engine.create_node(labels=labels, properties=properties)
                result_set[variable] = [node]
                logger.debug("CreateNode: created node %s", node.id)
            
            elif op_type == "Delete":
                # Delete node
                variable = op.get("variable")
                if variable in result_set:
                    for item in result_set[variable]:
                        self.graph_engine.delete_node(item.id)
                    logger.debug("Delete: deleted %d nodes", len(result_set[variable]))
            
            elif op_type == "SetProperty":
                # Set property
                variable = op.get("variable")
                property_name = op.get("property")
                value = self._resolve_value(op.get("value"), parameters)
                
                if variable in result_set:
                    for item in result_set[variable]:
                        self.graph_engine.update_node(item.id, {property_name: value})
                    logger.debug("SetProperty: updated %d nodes", len(result_set[variable]))
        
        # Handle UNION merging
        if hasattr(self, '_union_parts') and self._union_parts:
            # Merge all union parts with final_results
            all_parts = []
            for part in self._union_parts:
                all_parts.extend(part['results'])
            all_parts.extend(final_results)
            
            # Check if we should remove duplicates
            # Use the 'all' flag from the last union (or first if multiple)
            remove_duplicates = not self._union_parts[0]['all']
            
            if remove_duplicates:
                # Remove duplicate records
                seen = set()
                unique_results = []
                for record in all_parts:
                    # Create hashable representation
                    record_tuple = tuple(record._values)
                    if record_tuple not in seen:
                        seen.add(record_tuple)
                        unique_results.append(record)
                final_results = unique_results
                logger.debug("Union: removed duplicates, %d unique results", len(final_results))
            else:
                # UNION ALL - keep all results
                final_results = all_parts
                logger.debug("Union ALL: combined %d total results", len(final_results))
            
            # Clean up
            delattr(self, '_union_parts')
        
        return final_results
    
    def _resolve_value(self, value: Any, parameters: Dict[str, Any]) -> Any:
        """Resolve value, substituting parameters if needed."""
        if isinstance(value, dict):
            if "param" in value:
                param_name = value["param"]
                return parameters.get(param_name)
            elif "var" in value:
                return value  # Keep as reference
        return value
    
    def _evaluate_compiled_expression(self, expr: Any, binding: Dict[str, Any]) -> Any:
        """
        Evaluate a compiled expression (dict or string) against a binding.
        
        Args:
            expr: Compiled expression - can be:
                  - String: "n.age", "n"
                  - Dict with 'property': {'property': 'n.age'}
                  - Dict with 'function': {'function': 'toLower', 'args': [...]}
                  - Dict with 'var': {'var': 'n'}
                  - Other dict formats
            binding: Variable bindings (e.g., {'n': node_obj})
            
        Returns:
            Evaluated value
        """
        # Handle dict expressions (from compiler)
        if isinstance(expr, dict):
            if 'function' in expr:
                # Function call: {'function': 'toLower', 'args': [{'property': 'n.email'}]}
                func_name = expr['function']
                args = expr.get('args', [])
                
                # Recursively evaluate arguments
                eval_args = [self._evaluate_compiled_expression(arg, binding) for arg in args]
                
                # Call the function
                return self._call_function(func_name, eval_args)
            
            elif 'property' in expr:
                # Property access: {'property': 'n.email'}
                prop_path = expr['property']
                
                # First, check if the full property path is directly available in binding
                if prop_path in binding:
                    return binding[prop_path]
                
                # Otherwise, try to split and access as variable.property
                if '.' in prop_path:
                    var, prop = prop_path.split('.', 1)
                    if var in binding:
                        val = binding[var]
                        if hasattr(val, 'get'):
                            return val.get(prop)
                        elif hasattr(val, '_properties') and prop in val._properties:
                            return val._properties[prop]
                return None
            
            elif 'var' in expr:
                # Variable reference: {'var': 'n'}
                var_name = expr['var']
                return binding.get(var_name)
            
            elif 'op' in expr:
                # Binary operation: {'op': '>', 'left': ..., 'right': ...}
                left = self._evaluate_compiled_expression(expr['left'], binding)
                right = self._evaluate_compiled_expression(expr['right'], binding)
                return self._apply_operator(left, expr['op'], right)
        
        # Handle string expressions (legacy/simple cases)
        elif isinstance(expr, str):
            # Check if this looks like a property access expression (var.prop pattern)
            # Not just any string with a "." (which could be an email, URL, etc.)
            if expr in binding:
                # Variable name
                return self._evaluate_expression(expr, binding)
            elif "." in expr:
                # Could be property access like "n.age" or literal like "test@example.com"
                # Check if it looks like a valid property access pattern
                parts = expr.split(".")
                if len(parts) == 2 and parts[0].isidentifier():
                    # Looks like "n.age" - try to evaluate as expression
                    return self._evaluate_expression(expr, binding)
                else:
                    # Looks like a literal (e.g., "test@example.com", "1.5")
                    return expr
            else:
                # Simple string with no special meaning
                return expr
        
        # Handle literal values (numbers, strings, etc.)
        else:
            return expr
    
    def _apply_operator(self, left: Any, operator: str, right: Any) -> bool:
        """Apply comparison operator."""
        try:
            operator = operator.upper()
            
            # Equality operators
            if operator == "=":
                return left == right
            elif operator in ("<>", "!="):
                return left != right
            
            # Comparison operators
            elif operator == ">":
                return left > right
            elif operator == "<":
                return left < right
            elif operator == ">=":
                return left >= right
            elif operator == "<=":
                return left <= right
            
            # IN operator - check membership in list
            elif operator == "IN":
                if isinstance(right, list):
                    return left in right
                return False
            
            # String operators
            elif operator == "CONTAINS":
                if isinstance(left, str) and isinstance(right, str):
                    return right in left
                return False
            
            elif operator in ("STARTS", "STARTS WITH"):
                if isinstance(left, str) and isinstance(right, str):
                    return left.startswith(right)
                return False
            
            elif operator in ("ENDS", "ENDS WITH"):
                if isinstance(left, str) and isinstance(right, str):
                    return left.endswith(right)
                return False
            
            else:
                logger.warning("Unknown operator: %s", operator)
                return False
                
        except (TypeError, ValueError, AttributeError) as e:
            logger.debug("Operator %s failed: %s", operator, e)
            return False
    
    def _validate_parameters(self, parameters: Dict[str, Any]) -> None:
        """
        Validate query parameters.
        
        Args:
            parameters: Parameters to validate
            
        Raises:
            ValueError: If parameters are invalid
        """
        if not isinstance(parameters, dict):
            raise ValueError(f"Parameters must be a dict, got {type(parameters)}")
        
        # Check for reserved parameter names
        reserved = {'_id', '_type', '_internal'}
        for key in parameters.keys():
            if key in reserved:
                raise ValueError(f"Parameter name '{key}' is reserved")
        
        logger.debug("Parameters validated: %d params", len(parameters))
    
    def _evaluate_expression(self, expr: str, row: Dict[str, Any]) -> Any:
        """
        Evaluate an expression against a data row.
        
        Args:
            expr: Expression string (e.g., "n.age", "n", "toLower(n.name)", CASE expression)
            row: Data row (variable bindings)
            
        Returns:
            Evaluated value
        """
        # Check if it's a CASE expression
        if expr.startswith("CASE|"):
            return self._evaluate_case_expression(expr, row)
        
        # Check if it's a function call
        if "(" in expr and expr.endswith(")"):
            # Extract function name and arguments
            func_match = expr.find("(")
            func_name = expr[:func_match].strip()
            args_str = expr[func_match+1:-1].strip()
            
            # Parse arguments (simple comma-separated for now)
            if args_str:
                # Split by comma, but be careful with nested functions
                args = []
                current_arg = ""
                paren_depth = 0
                for char in args_str:
                    if char == "," and paren_depth == 0:
                        args.append(current_arg.strip())
                        current_arg = ""
                    else:
                        if char == "(":
                            paren_depth += 1
                        elif char == ")":
                            paren_depth -= 1
                        current_arg += char
                if current_arg:
                    args.append(current_arg.strip())
                
                # Evaluate each argument
                eval_args = []
                for arg in args:
                    # Try to parse as literal number
                    if arg.isdigit():
                        eval_args.append(int(arg))
                    # Try to parse as literal string (quoted)
                    elif (arg.startswith("'") and arg.endswith("'")) or \
                         (arg.startswith('"') and arg.endswith('"')):
                        eval_args.append(arg[1:-1])
                    else:
                        # Evaluate as expression
                        eval_args.append(self._evaluate_expression(arg, row))
            else:
                eval_args = []
            
            # Call the function
            return self._call_function(func_name, eval_args)
        
        # Property access: "n.age"
        if "." in expr:
            var, prop = expr.split(".", 1)
            if var in row:
                val = row[var]
                if hasattr(val, 'get'):
                    return val.get(prop)
                elif hasattr(val, '_properties') and prop in val._properties:
                    return val._properties[prop]
        # Variable access: "n"
        elif expr in row:
            return row[expr]
        
        return None
    
    def _evaluate_case_expression(self, case_expr: str, row: Dict[str, Any]) -> Any:
        """
        Evaluate a CASE expression.
        
        Format: CASE|[TEST:test_expr]|WHEN:cond:THEN:result|...|[ELSE:else_result]|END
        
        Args:
            case_expr: Serialized CASE expression
            row: Data row
            
        Returns:
            Result of CASE evaluation
        """
        # Parse the CASE expression
        parts = case_expr.split("|")
        
        if parts[0] != "CASE" or parts[-1] != "END":
            logger.warning("Invalid CASE expression format: %s", case_expr)
            return None
        
        test_expr = None
        when_clauses = []
        else_result = None
        
        i = 1
        while i < len(parts) - 1:
            part = parts[i]
            
            if part.startswith("TEST:"):
                test_expr = part[5:]  # Remove "TEST:" prefix
            
            elif part.startswith("WHEN:"):
                # Format: WHEN:condition:THEN:result
                when_parts = part.split(":")
                if len(when_parts) >= 4 and when_parts[2] == "THEN":
                    condition = when_parts[1]
                    result = ":".join(when_parts[3:])  # In case result contains ":"
                    when_clauses.append((condition, result))
            
            elif part.startswith("ELSE:"):
                else_result = part[5:]  # Remove "ELSE:" prefix
            
            i += 1
        
        # Evaluate the CASE expression
        if test_expr:
            # Simple CASE: compare test expression against each WHEN value
            test_value = self._evaluate_expression(test_expr, row)
            
            for condition, result in when_clauses:
                when_value = self._evaluate_expression(condition, row)
                if test_value == when_value:
                    return self._evaluate_expression(result, row)
        
        else:
            # Generic CASE: evaluate each WHEN condition
            for condition, result in when_clauses:
                # Parse condition (might be a comparison)
                if self._evaluate_condition(condition, row):
                    return self._evaluate_expression(result, row)
        
        # No WHEN matched, return ELSE or None
        if else_result:
            return self._evaluate_expression(else_result, row)
        
        return None
    
    def _evaluate_condition(self, condition: str, row: Dict[str, Any]) -> bool:
        """
        Evaluate a condition expression.
        
        Args:
            condition: Condition string (e.g., "n.age > 30")
            row: Data row
            
        Returns:
            Boolean result
        """
        # Simple evaluation for now - check for comparison operators
        for op in [" >= ", " <= ", " <> ", " != ", " = ", " > ", " < "]:
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) == 2:
                    left_val = self._evaluate_expression(parts[0].strip(), row)
                    right_val = self._evaluate_expression(parts[1].strip(), row)
                    return self._apply_operator(left_val, op.strip(), right_val)
        
        # If no operator, just evaluate as expression (truthy check)
        value = self._evaluate_expression(condition, row)
        return bool(value)
    
    def _call_function(self, func_name: str, args: List[Any]) -> Any:
        """
        Call a built-in function.
        
        Args:
            func_name: Function name (e.g., "toLower", "substring", "abs", "point")
            args: List of evaluated arguments
            
        Returns:
            Function result
        """
        func_name_lower = func_name.lower()
        
        # Try function registry first (math, spatial, temporal)
        from ..cypher.functions import FUNCTION_REGISTRY
        if func_name_lower in FUNCTION_REGISTRY:
            try:
                func = FUNCTION_REGISTRY[func_name_lower]
                # Handle single argument functions
                if len(args) == 1:
                    return func(args[0])
                # Handle multi-argument functions
                elif len(args) > 1:
                    return func(*args)
                # Handle no-argument functions
                else:
                    return func()
            except Exception as e:
                logger.warning("Function %s raised exception: %s", func_name, e)
                return None
        
        # String functions (existing implementation)
        if func_name_lower == "tolower":
            if args and isinstance(args[0], str):
                return args[0].lower()
            return None
        
        elif func_name_lower == "toupper":
            if args and isinstance(args[0], str):
                return args[0].upper()
            return None
        
        elif func_name_lower == "substring":
            if len(args) >= 2 and isinstance(args[0], str):
                string = args[0]
                start = args[1] if isinstance(args[1], int) else 0
                if len(args) >= 3 and isinstance(args[2], int):
                    length = args[2]
                    return string[start:start+length]
                else:
                    return string[start:]
            return None
        
        elif func_name_lower == "trim":
            if args and isinstance(args[0], str):
                return args[0].strip()
            return None
        
        elif func_name_lower == "ltrim":
            if args and isinstance(args[0], str):
                return args[0].lstrip()
            return None
        
        elif func_name_lower == "rtrim":
            if args and isinstance(args[0], str):
                return args[0].rstrip()
            return None
        
        elif func_name_lower == "replace":
            if len(args) >= 3 and isinstance(args[0], str):
                string = args[0]
                search = str(args[1]) if args[1] is not None else ""
                replace = str(args[2]) if args[2] is not None else ""
                return string.replace(search, replace)
            return None
        
        elif func_name_lower == "reverse":
            if args and isinstance(args[0], str):
                return args[0][::-1]
            return None
        
        elif func_name_lower == "size":
            if args:
                if isinstance(args[0], str):
                    return len(args[0])
                elif isinstance(args[0], (list, tuple)):
                    return len(args[0])
            return None
        
        elif func_name_lower == "split":
            if len(args) >= 2 and isinstance(args[0], str):
                string = args[0]
                delimiter = str(args[1]) if args[1] is not None else ","
                return string.split(delimiter)
            return None
        
        elif func_name_lower == "left":
            if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], int):
                return args[0][:args[1]]
            return None
        
        elif func_name_lower == "right":
            if len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], int):
                return args[0][-args[1]:]
            return None
        
        else:
            logger.warning("Unknown function: %s", func_name)
            return None
    
    def _compute_aggregation(self, func: str, values: List[Any]) -> Any:
        """
        Compute an aggregation function.
        
        Args:
            func: Aggregation function name (COUNT, SUM, AVG, etc.)
            values: Values to aggregate
            
        Returns:
            Aggregated result
        """
        func = func.upper()
        
        if func == "COUNT":
            return len(values)
        
        elif func == "SUM":
            # Filter numeric values
            numeric_values = [v for v in values if isinstance(v, (int, float))]
            return sum(numeric_values) if numeric_values else 0
        
        elif func == "AVG":
            # Filter numeric values
            numeric_values = [v for v in values if isinstance(v, (int, float))]
            if numeric_values:
                return sum(numeric_values) / len(numeric_values)
            return None
        
        elif func == "MIN":
            # Filter comparable values
            comparable_values = [v for v in values if v is not None]
            return min(comparable_values) if comparable_values else None
        
        elif func == "MAX":
            # Filter comparable values
            comparable_values = [v for v in values if v is not None]
            return max(comparable_values) if comparable_values else None
        
        elif func == "COLLECT":
            # Return list of all values
            return list(values)
        
        elif func in ("STDEV", "STDEVP"):
            # Standard deviation
            numeric_values = [v for v in values if isinstance(v, (int, float))]
            if len(numeric_values) < 2:
                return None
            
            mean = sum(numeric_values) / len(numeric_values)
            variance = sum((x - mean) ** 2 for x in numeric_values) / len(numeric_values)
            return variance ** 0.5
        
        else:
            logger.warning("Unknown aggregation function: %s", func)
            return None



class GraphEngine:
    """
    Core graph engine for node and relationship operations.
    
    Provides CRUD operations for graph elements and integrates with
    IPLD storage backend.
    
    Phase 1: Basic CRUD operations
    Phase 2: Path traversal and pattern matching
    Phase 3: Advanced algorithms (shortest path, centrality, etc.)
    """
    
    def __init__(self, storage_backend: Optional['IPLDBackend'] = None):
        """
        Initialize the graph engine.
        
        Args:
            storage_backend: IPLD storage backend
        """
        self.storage = storage_backend
        self._node_cache = {}
        self._relationship_cache = {}
        self._node_id_counter = 0
        self._rel_id_counter = 0
        self._enable_persistence = storage_backend is not None
        logger.debug("GraphEngine initialized (persistence=%s)", self._enable_persistence)
    
    def create_node(
        self,
        labels: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create a new node.
        
        Args:
            labels: Node labels
            properties: Node properties
            
        Returns:
            Created Node object
            
        Example:
            node = engine.create_node(
                labels=["Person"],
                properties={"name": "Alice", "age": 30}
            )
        """
        # Generate node ID (Phase 1: simple counter, Phase 3: CID-based)
        node_id = self._generate_node_id()
        
        node = Node(
            node_id=node_id,
            labels=labels or [],
            properties=properties or {}
        )
        
        # Store in cache
        self._node_cache[node_id] = node
        
        # Persist to IPLD storage if available
        if self._enable_persistence and self.storage:
            try:
                node_data = {
                    "id": node_id,
                    "labels": labels or [],
                    "properties": properties or {}
                }
                cid = self.storage.store(node_data, pin=True, codec="dag-json")
                # Store CID mapping for retrieval
                self._node_cache[f"cid:{node_id}"] = cid
                logger.debug("Node %s persisted with CID: %s", node_id, cid)
            except Exception as e:
                logger.warning("Failed to persist node %s: %s", node_id, e)
        
        logger.info("Created node: %s (labels=%s)", node_id, labels)
        return node
    
    def get_node(self, node_id: str) -> Optional[Node]:
        """
        Retrieve a node by ID.
        
        Args:
            node_id: Node identifier
            
        Returns:
            Node object or None if not found
        """
        # Check cache first
        if node_id in self._node_cache:
            logger.debug("Node found in cache: %s", node_id)
            return self._node_cache[node_id]
        
        # Load from IPLD storage if available
        if self._enable_persistence and self.storage:
            try:
                # Try to get CID for this node
                cid_key = f"cid:{node_id}"
                if cid_key in self._node_cache:
                    cid = self._node_cache[cid_key]
                    node_data = self.storage.retrieve_json(cid)
                    node = Node(
                        node_id=node_data["id"],
                        labels=node_data.get("labels", []),
                        properties=node_data.get("properties", {})
                    )
                    # Cache the loaded node
                    self._node_cache[node_id] = node
                    logger.debug("Node %s loaded from IPLD (CID: %s)", node_id, cid)
                    return node
            except Exception as e:
                logger.debug("Failed to load node %s from storage: %s", node_id, e)
        
        logger.debug("Node not found: %s", node_id)
        return None
    
    def update_node(
        self,
        node_id: str,
        properties: Dict[str, Any]
    ) -> Optional[Node]:
        """
        Update node properties.
        
        Args:
            node_id: Node identifier
            properties: Properties to update
            
        Returns:
            Updated Node object or None if not found
        """
        node = self.get_node(node_id)
        if not node:
            logger.warning("Node not found: %s", node_id)
            return None
        
        # Update properties
        node._properties.update(properties)
        self._node_cache[node_id] = node
        
        # Update in IPLD storage if persistence is enabled
        if self._enable_persistence and self.storage:
            try:
                node_data = {
                    "id": node_id,
                    "labels": node._labels,
                    "properties": node._properties
                }
                cid = self.storage.store(node_data, pin=True, codec="dag-json")
                self._node_cache[f"cid:{node_id}"] = cid
                logger.debug("Node %s updated in storage (CID: %s)", node_id, cid)
            except Exception as e:
                logger.warning("Failed to update node %s in storage: %s", node_id, e)
        
        logger.info("Updated node: %s", node_id)
        return node
    
    def delete_node(self, node_id: str) -> bool:
        """
        Delete a node.
        
        Args:
            node_id: Node identifier
            
        Returns:
            True if deleted, False if not found
        """
        if node_id not in self._node_cache:
            return False
        
        del self._node_cache[node_id]
        
        # Also delete CID mapping if exists
        cid_key = f"cid:{node_id}"
        if cid_key in self._node_cache:
            del self._node_cache[cid_key]
        
        # Note: We don't unpin from IPFS as other references may exist
        logger.info("Deleted node: %s", node_id)
        return True
    
    def create_relationship(
        self,
        rel_type: str,
        start_node: str,
        end_node: str,
        properties: Optional[Dict[str, Any]] = None
    ) -> Relationship:
        """
        Create a relationship between two nodes.
        
        Args:
            rel_type: Relationship type
            start_node: Start node ID
            end_node: End node ID
            properties: Relationship properties
            
        Returns:
            Created Relationship object
        """
        rel_id = self._generate_relationship_id()
        
        relationship = Relationship(
            rel_id=rel_id,
            rel_type=rel_type,
            start_node=start_node,
            end_node=end_node,
            properties=properties or {}
        )
        
        self._relationship_cache[rel_id] = relationship
        
        # Persist to IPLD storage if available
        if self._enable_persistence and self.storage:
            try:
                rel_data = {
                    "id": rel_id,
                    "type": rel_type,
                    "start_node": start_node,
                    "end_node": end_node,
                    "properties": properties or {}
                }
                cid = self.storage.store(rel_data, pin=True, codec="dag-json")
                self._relationship_cache[f"cid:{rel_id}"] = cid
                logger.debug("Relationship %s persisted with CID: %s", rel_id, cid)
            except Exception as e:
                logger.warning("Failed to persist relationship %s: %s", rel_id, e)
        
        logger.info("Created relationship: %s -%s-> %s", start_node, rel_type, end_node)
        return relationship
    
    def get_relationship(self, rel_id: str) -> Optional[Relationship]:
        """
        Retrieve a relationship by ID.
        
        Args:
            rel_id: Relationship identifier
            
        Returns:
            Relationship object or None if not found
        """
        return self._relationship_cache.get(rel_id)
    
    def delete_relationship(self, rel_id: str) -> bool:
        """
        Delete a relationship.
        
        Args:
            rel_id: Relationship identifier
            
        Returns:
            True if deleted, False if not found
        """
        if rel_id not in self._relationship_cache:
            return False
        
        del self._relationship_cache[rel_id]
        
        # Also delete CID mapping if exists
        cid_key = f"cid:{rel_id}"
        if cid_key in self._relationship_cache:
            del self._relationship_cache[cid_key]
        
        logger.info("Deleted relationship: %s", rel_id)
        return True
    
    def find_nodes(
        self,
        labels: Optional[List[str]] = None,
        properties: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Node]:
        """
        Find nodes matching criteria.
        
        Args:
            labels: Labels to match
            properties: Properties to match
            limit: Maximum number of results
            
        Returns:
            List of matching nodes
        """
        results = []
        
        # Filter only Node objects (exclude CID mappings)
        for key, value in self._node_cache.items():
            if key.startswith("cid:"):
                continue  # Skip CID mapping entries
            
            node = value
            if not isinstance(node, Node):
                continue
            
            # Check labels
            if labels and not any(label in node.labels for label in labels):
                continue
            
            # Check properties
            if properties:
                if not all(node.get(k) == v for k, v in properties.items()):
                    continue
            
            results.append(node)
            
            if limit and len(results) >= limit:
                break
        
        logger.debug("Found %d nodes", len(results))
        return results
    
    def _generate_node_id(self) -> str:
        """Generate a unique node ID."""
        import uuid
        return f"node-{uuid.uuid4().hex[:12]}"
    
    def _generate_relationship_id(self) -> str:
        """Generate a unique relationship ID."""
        import uuid
        return f"rel-{uuid.uuid4().hex[:12]}"
    
    def save_graph(self) -> Optional[str]:
        """
        Save the entire graph to IPLD storage.
        
        Returns:
            Root CID of the saved graph, or None if persistence is disabled
            
        Example:
            cid = engine.save_graph()
            print(f"Graph saved with CID: {cid}")
        """
        if not self._enable_persistence or not self.storage:
            logger.warning("Graph persistence is disabled")
            return None
        
        try:
            # Extract nodes (exclude CID mappings)
            nodes = []
            for key, value in self._node_cache.items():
                if not key.startswith("cid:") and isinstance(value, Node):
                    nodes.append({
                        "id": value._id,
                        "labels": value._labels,
                        "properties": value._properties
                    })
            
            # Extract relationships (exclude CID mappings)
            relationships = []
            for key, value in self._relationship_cache.items():
                if not key.startswith("cid:") and isinstance(value, Relationship):
                    relationships.append({
                        "id": value._id,
                        "type": value._type,
                        "start_node": value._start_node,
                        "end_node": value._end_node,
                        "properties": value._properties
                    })
            
            # Save using storage backend
            cid = self.storage.store_graph(
                nodes=nodes,
                relationships=relationships,
                metadata={
                    "node_count": len(nodes),
                    "relationship_count": len(relationships),
                    "version": "1.0"
                }
            )
            
            logger.info("Graph saved with CID: %s (%d nodes, %d relationships)", 
                       cid, len(nodes), len(relationships))
            return cid
        except Exception as e:
            logger.error("Failed to save graph: %s", e)
            return None
    
    def load_graph(self, root_cid: str) -> bool:
        """
        Load a graph from IPLD storage.
        
        Args:
            root_cid: Root CID of the graph to load
            
        Returns:
            True if successful, False otherwise
            
        Example:
            success = engine.load_graph("bafybeig...")
        """
        if not self._enable_persistence or not self.storage:
            logger.warning("Graph persistence is disabled")
            return False
        
        try:
            # Retrieve graph data
            graph_data = self.storage.retrieve_graph(root_cid)
            
            # Clear current caches
            self._node_cache.clear()
            self._relationship_cache.clear()
            
            # Load nodes
            for node_data in graph_data.get("nodes", []):
                node = Node(
                    node_id=node_data["id"],
                    labels=node_data.get("labels", []),
                    properties=node_data.get("properties", {})
                )
                self._node_cache[node.id] = node
            
            # Load relationships
            for rel_data in graph_data.get("relationships", []):
                rel = Relationship(
                    rel_id=rel_data["id"],
                    rel_type=rel_data["type"],
                    start_node=rel_data["start_node"],
                    end_node=rel_data["end_node"],
                    properties=rel_data.get("properties", {})
                )
                self._relationship_cache[rel.id] = rel
            
            logger.info("Graph loaded from CID: %s (%d nodes, %d relationships)",
                       root_cid, len(self._node_cache), len(self._relationship_cache))
            return True
        except Exception as e:
            logger.error("Failed to load graph from %s: %s", root_cid, e)
            return False
    
    def get_relationships(
        self,
        node_id: str,
        direction: str = "out",
        rel_type: Optional[str] = None
    ) -> List[Relationship]:
        """
        Get relationships for a node with optional filtering.
        
        This is a critical method for graph traversal - enables MATCH queries
        to follow relationships between nodes.
        
        Args:
            node_id: Node identifier
            direction: Relationship direction - "out", "in", or "both"
            rel_type: Optional relationship type filter
            
        Returns:
            List of matching relationships
            
        Example:
            # Get all outgoing KNOWS relationships
            rels = engine.get_relationships("node-123", "out", "KNOWS")
            
            # Get all relationships (any direction)
            rels = engine.get_relationships("node-123", "both")
        """
        results = []
        
        for key, rel in self._relationship_cache.items():
            if key.startswith("cid:"):
                continue  # Skip CID mappings
            
            if not isinstance(rel, Relationship):
                continue
            
            # Check direction and node match
            match = False
            if direction == "out" and rel._start_node == node_id:
                match = True
            elif direction == "in" and rel._end_node == node_id:
                match = True
            elif direction == "both":
                if rel._start_node == node_id or rel._end_node == node_id:
                    match = True
            
            if not match:
                continue
            
            # Check relationship type if specified
            if rel_type and rel._type != rel_type:
                continue
            
            results.append(rel)
        
        logger.debug("Found %d relationships for node %s (direction=%s, type=%s)",
                    len(results), node_id, direction, rel_type)
        return results
    
    def traverse_pattern(
        self,
        start_nodes: List[Node],
        pattern: List[Dict[str, Any]],
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Traverse a graph pattern starting from given nodes.
        
        Implements pattern matching for MATCH clauses like:
        (n:Person)-[:KNOWS]->(f:Person)
        
        Args:
            start_nodes: Starting nodes for traversal
            pattern: Pattern specification as list of steps
            limit: Maximum results to return
            
        Returns:
            List of pattern matches, each as a dict of variable -> value
            
        Example pattern:
            [
                {"variable": "n", "labels": ["Person"]},
                {"rel_type": "KNOWS", "direction": "out", "variable": "r"},
                {"variable": "f", "labels": ["Person"]}
            ]
        """
        results = []
        
        for start_node in start_nodes:
            # Initialize bindings with start node
            bindings = {"start": start_node}
            
            # Process pattern steps
            current_matches = [bindings]
            
            for i, step in enumerate(pattern):
                if "rel_type" in step:
                    # Relationship traversal step
                    new_matches = []
                    for match in current_matches:
                        # Get last node in pattern
                        last_var = list(match.keys())[-1]
                        last_node = match[last_var]
                        
                        # Find relationships
                        rels = self.get_relationships(
                            last_node.id,
                            direction=step.get("direction", "out"),
                            rel_type=step.get("rel_type")
                        )
                        
                        for rel in rels:
                            # Get target node
                            if step.get("direction") == "in":
                                target_id = rel._start_node
                            else:
                                target_id = rel._end_node
                            
                            target_node = self.get_node(target_id)
                            if not target_node:
                                continue
                            
                            # Create new binding with relationship and target
                            new_match = match.copy()
                            if "variable" in step:
                                new_match[step["variable"]] = rel
                            
                            # Add target node (next step should be node)
                            if i + 1 < len(pattern):
                                next_step = pattern[i + 1]
                                if "variable" in next_step:
                                    # Check labels if specified
                                    if "labels" in next_step:
                                        if not any(label in target_node.labels 
                                                  for label in next_step["labels"]):
                                            continue
                                    new_match[next_step["variable"]] = target_node
                            
                            new_matches.append(new_match)
                    
                    current_matches = new_matches
            
            # Add matches to results
            results.extend(current_matches)
            
            if limit and len(results) >= limit:
                results = results[:limit]
                break
        
        logger.debug("Pattern traversal found %d matches", len(results))
        return results
    
    def find_paths(
        self,
        start_node_id: str,
        end_node_id: str,
        max_depth: int = 5,
        rel_type: Optional[str] = None
    ) -> List[List[Relationship]]:
        """
        Find paths between two nodes.
        
        Uses breadth-first search to find all paths up to max_depth.
        Includes cycle detection to prevent infinite loops.
        
        Args:
            start_node_id: Start node ID
            end_node_id: End node ID
            max_depth: Maximum path length
            rel_type: Optional relationship type filter
            
        Returns:
            List of paths, each path is a list of relationships
            
        Example:
            paths = engine.find_paths("node-1", "node-5", max_depth=3)
            print(f"Found {len(paths)} paths")
        """
        paths = []
        
        # BFS queue: (current_node_id, path_so_far, visited_nodes)
        queue = [(start_node_id, [], {start_node_id})]
        
        while queue:
            current_id, path, visited = queue.pop(0)
            
            # Check depth limit
            if len(path) >= max_depth:
                continue
            
            # Get outgoing relationships
            rels = self.get_relationships(current_id, "out", rel_type)
            
            for rel in rels:
                target_id = rel._end_node
                
                # Found target
                if target_id == end_node_id:
                    paths.append(path + [rel])
                    continue
                
                # Cycle detection
                if target_id in visited:
                    continue
                
                # Add to queue for further exploration
                new_visited = visited.copy()
                new_visited.add(target_id)
                queue.append((target_id, path + [rel], new_visited))
        
        logger.debug("Found %d paths from %s to %s", 
                    len(paths), start_node_id, end_node_id)
        return paths
