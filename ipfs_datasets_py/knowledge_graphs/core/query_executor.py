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

from ..exceptions import KnowledgeGraphError, QueryError, QueryExecutionError, QueryParseError, StorageError
from ..neo4j_compat.result import Result, Record
from ..neo4j_compat.types import Node, Relationship, Path
from .expression_evaluator import (
    apply_operator as _apply_operator,
    call_function as _call_function,
    evaluate_case_expression as _evaluate_case_expression,
    evaluate_compiled_expression as _evaluate_compiled_expression,
    evaluate_condition as _evaluate_condition,
    evaluate_expression as _evaluate_expression,
)
from .ir_executor import execute_ir_operations as _execute_ir_operations

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

        raise_on_error = bool(options.get("raise_on_error", False))
        
        try:
            # Import parser and compiler
            from ..cypher import CypherParser, CypherCompiler
            from ..cypher.compiler import CypherCompileError
            from ..cypher.parser import CypherParseError
            
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

        except CypherParseError as e:
            query_error = QueryParseError(str(e), details={"stage": "parse"})
            if raise_on_error:
                raise query_error from e

            logger.error("Cypher parse failed (%s): %s", type(e).__name__, e)
            summary = {
                "query_type": "Cypher",
                "query": query[:100],
                "error": str(e),
                "error_type": "parse",
                "error_stage": "parse",
                "error_class": type(query_error).__name__,
            }
            return Result([], summary=summary)

        except CypherCompileError as e:
            query_error = QueryParseError(str(e), details={"stage": "compile"})
            if raise_on_error:
                raise query_error from e

            logger.error("Cypher compile failed (%s): %s", type(e).__name__, e)
            summary = {
                "query_type": "Cypher",
                "query": query[:100],
                "error": str(e),
                "error_type": "parse",
                "error_stage": "compile",
                "error_class": type(query_error).__name__,
            }
            return Result([], summary=summary)

        except QueryError as e:
            if raise_on_error:
                raise

            logger.error("Cypher execution failed (%s): %s", type(e).__name__, e)
            error_type = "parse" if isinstance(e, QueryParseError) else "execution"
            summary = {
                "query_type": "Cypher",
                "query": query[:100],
                "error": str(e),
                "error_type": error_type,
                "error_stage": "execute",
                "error_class": type(e).__name__,
            }
            return Result([], summary=summary)

        except StorageError as e:
            query_error = QueryExecutionError(str(e), details={"stage": "execute", "error": str(e), "error_class": type(e).__name__})
            if raise_on_error:
                raise query_error from e

            logger.error("Cypher execution failed (%s): %s", type(e).__name__, e)
            summary = {
                "query_type": "Cypher",
                "query": query[:100],
                "error": str(e),
                "error_type": "execution",
                "error_stage": "execute",
                "error_class": type(query_error).__name__,
            }
            return Result([], summary=summary)

        except KnowledgeGraphError as e:
            if raise_on_error:
                raise

            # Keep the original error type in summary rather than losing taxonomy.
            logger.error("Cypher execution failed (%s): %s", type(e).__name__, e)
            summary = {
                "query_type": "Cypher",
                "query": query[:100],
                "error": str(e),
                "error_type": "execution",
                "error_stage": "execute",
                "error_class": type(e).__name__,
            }
            return Result([], summary=summary)

        except Exception as e:
            query_error = QueryExecutionError(str(e), details={"stage": "execute", "error": str(e), "error_class": type(e).__name__})
            if raise_on_error:
                raise query_error from e

            logger.error("Cypher execution failed (%s): %s", type(e).__name__, e)
            summary = {
                "query_type": "Cypher",
                "query": query[:100],
                "error": str(e),
                "error_type": "execution",
                "error_stage": "execute",
                "error_class": type(query_error).__name__,
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
        # IR Executor Integration planned
        # Current: GraphRAG query engine integration (when available)
        # Future Enhancement: Integrate with search/graphrag_query IR executor
        # This would enable hybrid graph + information retrieval queries
        # Reference: ipfs_datasets_py.search.graphrag_query
        
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
        return _execute_ir_operations(
            graph_engine=self.graph_engine,
            operations=operations,
            parameters=parameters,
            resolve_value=self._resolve_value,
            apply_operator=self._apply_operator,
            evaluate_compiled_expression=self._evaluate_compiled_expression,
            evaluate_expression=self._evaluate_expression,
            compute_aggregation=self._compute_aggregation,
        )
    
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
        return _evaluate_compiled_expression(expr, binding)
    
    def _apply_operator(self, left: Any, operator: str, right: Any) -> bool:
        """Apply comparison operator."""
        return _apply_operator(left, operator, right)
    
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
        return _evaluate_expression(expr, row)
    
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
        return _evaluate_case_expression(case_expr, row)
    
    def _evaluate_condition(self, condition: str, row: Dict[str, Any]) -> bool:
        """
        Evaluate a condition expression.
        
        Args:
            condition: Condition string (e.g., "n.age > 30")
            row: Data row
            
        Returns:
            Boolean result
        """
        return _evaluate_condition(condition, row)
    
    def _call_function(self, func_name: str, args: List[Any]) -> Any:
        """
        Call a built-in function.
        
        Args:
            func_name: Function name (e.g., "toLower", "substring", "abs", "point")
            args: List of evaluated arguments
            
        Returns:
            Function result
        """
        return _call_function(func_name, args)
    
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



# _LegacyGraphEngine extracted to a focused module (Workstream I — reduce god modules).
# Re-imported here so existing internal callers are unaffected.
from ._legacy_graph_engine import _LegacyGraphEngine  # noqa: F401


# Backwards compatibility: re-export GraphEngine from the extracted module.
from .graph_engine import GraphEngine as GraphEngine
