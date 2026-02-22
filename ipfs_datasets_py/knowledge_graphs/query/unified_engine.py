"""
Unified Query Engine

This module provides the central query execution engine for all GraphRAG operations.
It consolidates query logic from three previously fragmented implementations:

1. processors/graphrag/integration.py (~2,785 lines)
2. search/graphrag_integration/graphrag_integration.py (~3,141 lines)
3. search/graph_query/executor.py (~385 lines)

The unified engine provides:
- Single entry point for all query types (Cypher, IR, Hybrid, GraphRAG)
- Consistent budget management across all query types
- Reusable hybrid search (vector + graph)
- Simplified maintenance and extensibility
- Backward-compatible API

Key Components:
- UnifiedQueryEngine: Main query engine class
- Query execution methods for different query types
- Integration with existing components (Cypher compiler, IR executor, etc.)
- Budget enforcement via BudgetManager
- Hybrid search via HybridSearchEngine

Usage:
    from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
    from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset
    
    # Create engine
    engine = UnifiedQueryEngine(backend=backend)
    
    # Execute Cypher query
    budgets = budgets_from_preset('moderate')
    result = engine.execute_cypher(
        "MATCH (n:Person) RETURN n.name LIMIT 10",
        params={},
        budgets=budgets
    )
    
    # Execute hybrid search
    result = engine.execute_hybrid(
        query="What is IPFS?",
        k=10,
        budgets=budgets
    )
    
    # Execute full GraphRAG pipeline
    result = engine.execute_graphrag(
        question="Explain content addressing",
        context={'embeddings': embeddings},
        budgets=budgets
    )
"""

import asyncio
import logging
import anyio
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, asdict


def _cancelled_exc_class() -> type:
    """Return the current async framework's cancellation exception class.

    Falls back to asyncio.CancelledError when called outside an async context.
    """
    try:
        return anyio.get_cancelled_exc_class()
    except anyio.NoEventLoopError:
        return asyncio.CancelledError

from .budget_manager import BudgetManager, ExecutionBudgets, ExecutionCounters
from .hybrid_search import HybridSearchEngine, HybridSearchResult

# Import custom exceptions
from ..exceptions import (
    QueryError,
    QueryParseError,
    QueryExecutionError,
    QueryTimeoutError
)

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """
    Generic query result container.
    
    Attributes:
        items: List of result items
        stats: Execution statistics
        counters: Budget counters
        query_type: Type of query executed
        success: Whether query succeeded
        error: Error message if failed
    """
    items: List[Any]
    stats: Dict[str, Any]
    counters: Optional[ExecutionCounters] = None
    query_type: str = "unknown"
    success: bool = True
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        result = asdict(self)
        if self.counters:
            result['counters'] = asdict(self.counters)
        return result


@dataclass
class GraphRAGResult(QueryResult):
    """
    Extended result for GraphRAG queries including reasoning.
    
    Attributes:
        reasoning: LLM reasoning output
        evidence_chains: Supporting evidence from graph
        confidence: Confidence score (0-1)
    """
    reasoning: Optional[Dict[str, Any]] = None
    evidence_chains: Optional[List[Dict[str, Any]]] = None
    confidence: float = 0.0


class UnifiedQueryEngine:
    """
    Unified query engine for all GraphRAG operations.
    
    This engine consolidates query execution logic from multiple fragmented
    implementations, providing a single entry point for:
    - Cypher queries (via knowledge_graphs Cypher engine)
    - IR queries (Intermediate Representation)
    - Hybrid search (vector + graph)
    - Full GraphRAG pipeline (hybrid search + LLM reasoning)
    
    The engine handles:
    - Budget enforcement for all query types
    - Consistent error handling and logging
    - Performance monitoring and metrics
    - Backward compatibility with existing APIs
    
    Args:
        backend: Graph backend for storage/retrieval
        vector_store: Optional vector store for similarity search
        llm_processor: Optional LLM processor for reasoning
        enable_caching: Whether to enable query caching
        default_budgets: Default budget preset ('strict', 'moderate', 'permissive')
    
    Example:
        engine = UnifiedQueryEngine(backend=ipld_backend)
        
        # Simple query
        result = engine.execute_query("MATCH (n) RETURN n LIMIT 10")
        
        # With budgets
        budgets = budgets_from_preset('strict')
        result = engine.execute_query(query, budgets=budgets)
    """
    
    def __init__(
        self,
        backend: Any,
        vector_store: Optional[Any] = None,
        llm_processor: Optional[Any] = None,
        enable_caching: bool = True,
        default_budgets: str = 'safe'
    ):
        self.backend = backend
        self.vector_store = vector_store
        self.llm_processor = llm_processor
        self.enable_caching = enable_caching
        self.default_budgets_preset = default_budgets
        
        # Initialize components
        self.budget_manager = BudgetManager()
        self.hybrid_search = HybridSearchEngine(
            backend=backend,
            vector_store=vector_store
        )
        
        # Lazy-load heavy components
        self._cypher_compiler = None
        self._cypher_parser = None
        self._ir_executor = None
        self._graph_engine = None
        
        logger.info("UnifiedQueryEngine initialized")
    
    @property
    def cypher_compiler(self):
        """Lazy-load Cypher compiler."""
        if self._cypher_compiler is None:
            try:
                from ipfs_datasets_py.knowledge_graphs.cypher import CypherCompiler
                self._cypher_compiler = CypherCompiler()
            except ImportError as e:
                logger.error(f"Failed to load Cypher compiler: {e}")
                raise
        return self._cypher_compiler

    @property
    def cypher_parser(self):
        """Lazy-load Cypher parser."""
        if self._cypher_parser is None:
            try:
                from ipfs_datasets_py.knowledge_graphs.cypher import CypherParser
                self._cypher_parser = CypherParser()
            except ImportError as e:
                logger.error(f"Failed to load Cypher parser: {e}")
                raise
        return self._cypher_parser
    
    @property
    def ir_executor(self):
        """Lazy-load IR executor."""
        if self._ir_executor is None:
            try:
                from ipfs_datasets_py.search.graph_query.executor import GraphQueryExecutor
                self._ir_executor = GraphQueryExecutor(backend=self.backend)
            except ImportError as e:
                logger.error(f"Failed to load IR executor: {e}")
                raise
        return self._ir_executor
    
    @property
    def graph_engine(self):
        """Lazy-load graph engine."""
        if self._graph_engine is None:
            try:
                from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
                self._graph_engine = GraphEngine(storage_backend=self.backend)
            except ImportError as e:
                logger.error(f"Failed to load graph engine: {e}")
                raise
        return self._graph_engine
    
    def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        budgets: Optional[ExecutionBudgets] = None,
        query_type: str = 'auto'
    ) -> QueryResult:
        """
        Execute a query with automatic type detection.
        
        This is a convenience method that detects query type and routes
        to the appropriate execution method.
        
        Args:
            query: Query string
            params: Query parameters
            budgets: Execution budgets (uses defaults if None)
            query_type: Query type ('auto', 'cypher', 'ir', 'hybrid')
            
        Returns:
            QueryResult with results and stats
        """
        params = params or {}
        budgets = budgets or self.budget_manager.create_preset_budgets(
            self.default_budgets_preset
        )
        
        # Auto-detect query type
        if query_type == 'auto':
            query_type = self._detect_query_type(query)
        
        # Route to appropriate executor
        if query_type == 'cypher':
            return self.execute_cypher(query, params, budgets)
        elif query_type == 'hybrid':
            return self.execute_hybrid(query, budgets=budgets)
        else:
            logger.warning(f"Unknown query type: {query_type}, defaulting to Cypher")
            return self.execute_cypher(query, params, budgets)
    
    def execute_cypher(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        budgets: Optional[ExecutionBudgets] = None
    ) -> QueryResult:
        """
        Execute a Cypher query.
        
        Args:
            query: Cypher query string
            params: Query parameters
            budgets: Execution budgets
            
        Returns:
            QueryResult with results and stats
        """
        params = params or {}
        budgets = budgets or self.budget_manager.create_preset_budgets(
            self.default_budgets_preset
        )
        
        logger.debug(f"Executing Cypher query: {query[:100]}")
        
        with self.budget_manager.track(budgets) as tracker:
            try:
                # Compile Cypher to IR
                ast = self.cypher_parser.parse(query)
                ir = self.cypher_compiler.compile(ast)
                
                # Execute IR
                result = self.ir_executor.execute(ir, budgets=budgets)
                
                return QueryResult(
                    items=result.items if hasattr(result, 'items') else [],
                    stats=result.stats if hasattr(result, 'stats') else {},
                    counters=tracker.counters,
                    query_type='cypher',
                    success=True
                )
                
            except (ValueError, SyntaxError) as e:
                logger.error(f"Cypher query parsing failed: {e}")
                raise QueryParseError(
                    f"Failed to parse Cypher query: {e}",
                    details={'query': query[:100], 'params': params}
                ) from e
            except (TimeoutError,) as e:
                logger.error(f"Cypher query timeout: {e}")
                raise QueryTimeoutError(
                    f"Cypher query execution timed out: {e}",
                    details={'query': query[:100]}
                ) from e
            except QueryError:
                raise
            except _cancelled_exc_class():
                raise
            except Exception as e:
                logger.error(f"Cypher query execution failed: {e}")
                raise QueryExecutionError(
                    f"Failed to execute Cypher query: {e}",
                    details={
                        'query': query[:100],
                        'counters': tracker.counters,
                        'error': str(e),
                        'error_class': type(e).__name__,
                    }
                ) from e
    
    def execute_ir(
        self,
        ir: Any,
        budgets: Optional[ExecutionBudgets] = None
    ) -> QueryResult:
        """
        Execute an IR (Intermediate Representation) query.
        
        Args:
            ir: QueryIR object
            budgets: Execution budgets
            
        Returns:
            QueryResult with results and stats
        """
        budgets = budgets or self.budget_manager.create_preset_budgets(
            self.default_budgets_preset
        )
        
        logger.debug("Executing IR query")
        
        with self.budget_manager.track(budgets) as tracker:
            try:
                result = self.ir_executor.execute(ir, budgets=budgets)
                
                return QueryResult(
                    items=result.items if hasattr(result, 'items') else [],
                    stats=result.stats if hasattr(result, 'stats') else {},
                    counters=tracker.counters,
                    query_type='ir',
                    success=True
                )
                
            except (ValueError, SyntaxError) as e:
                logger.error(f"IR query parsing failed: {e}")
                raise QueryParseError(
                    f"Failed to parse IR query: {e}",
                    details={
                        'ir_type': type(ir).__name__,
                        'ir_preview': str(ir)[:100],
                    }
                ) from e
            except (TimeoutError,) as e:
                logger.error(f"IR query timeout: {e}")
                raise QueryTimeoutError(
                    f"IR query execution timed out: {e}",
                    details={
                        'ir_type': type(ir).__name__,
                        'ir_preview': str(ir)[:100],
                    }
                ) from e
            except QueryError:
                raise
            except _cancelled_exc_class():
                raise
            except Exception as e:
                logger.error(f"IR query execution failed: {e}")
                raise QueryExecutionError(
                    f"Failed to execute IR query: {e}",
                    details={
                        'ir_type': type(ir).__name__,
                        'ir_preview': str(ir)[:100],
                        'counters': tracker.counters,
                        'error': str(e),
                        'error_class': type(e).__name__,
                    }
                ) from e
    
    def execute_hybrid(
        self,
        query: str,
        k: int = 10,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        max_hops: int = 2,
        embeddings: Optional[Dict[str, Any]] = None,
        budgets: Optional[ExecutionBudgets] = None
    ) -> QueryResult:
        """
        Execute hybrid search (vector + graph).
        
        Args:
            query: Search query text
            k: Number of results to return
            vector_weight: Weight for vector scores (0-1)
            graph_weight: Weight for graph scores (0-1)
            max_hops: Maximum graph traversal hops
            embeddings: Optional pre-computed embeddings
            budgets: Execution budgets
            
        Returns:
            QueryResult with hybrid search results
        """
        budgets = budgets or self.budget_manager.create_preset_budgets(
            self.default_budgets_preset
        )
        
        logger.debug(f"Executing hybrid search: {query[:100]}")
        
        with self.budget_manager.track(budgets) as tracker:
            try:
                results = self.hybrid_search.search(
                    query=query,
                    k=k,
                    vector_weight=vector_weight,
                    graph_weight=graph_weight,
                    max_hops=max_hops,
                    embeddings=embeddings
                )
                
                return QueryResult(
                    items=[asdict(r) for r in results],
                    stats=tracker.get_stats(),
                    counters=tracker.counters,
                    query_type='hybrid',
                    success=True
                )
                
            except (ValueError, KeyError) as e:
                logger.error(f"Hybrid search configuration error: {e}")
                raise QueryExecutionError(
                    f"Invalid hybrid search configuration: {e}",
                    details={'query': query, 'k': k, 'vector_weight': vector_weight}
                ) from e
            except (TimeoutError,) as e:
                logger.error(f"Hybrid search timeout: {e}")
                raise QueryTimeoutError(
                    f"Hybrid search timed out: {e}",
                    details={'query': query}
                ) from e
            except QueryError:
                raise
            except _cancelled_exc_class():
                raise
            except Exception as e:
                logger.error(f"Hybrid search execution failed: {e}")
                raise QueryExecutionError(
                    f"Failed to execute hybrid search: {e}",
                    details={
                        'query': query,
                        'k': k,
                        'error': str(e),
                        'error_class': type(e).__name__,
                    }
                ) from e
    
    def execute_graphrag(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        k: int = 10,
        reasoning_depth: str = 'moderate',
        budgets: Optional[ExecutionBudgets] = None
    ) -> GraphRAGResult:
        """
        Execute full GraphRAG pipeline (hybrid search + LLM reasoning).
        
        Args:
            question: User question
            context: Context including embeddings, metadata
            k: Number of search results
            reasoning_depth: Reasoning depth ('light', 'moderate', 'deep')
            budgets: Execution budgets
            
        Returns:
            GraphRAGResult with reasoning and evidence
        """
        context = context or {}
        budgets = budgets or self.budget_manager.create_preset_budgets(
            self.default_budgets_preset
        )
        
        logger.debug(f"Executing GraphRAG: {question[:100]}")
        
        with self.budget_manager.track(budgets) as tracker:
            try:
                # Step 1: Hybrid search
                search_result = self.execute_hybrid(
                    query=question,
                    k=k,
                    embeddings=context.get('embeddings'),
                    budgets=budgets
                )
                
                if not search_result.success:
                    return GraphRAGResult(
                        items=[],
                        stats=tracker.get_stats(),
                        counters=tracker.counters,
                        query_type='graphrag',
                        success=False,
                        error=f"Hybrid search failed: {search_result.error}"
                    )
                
                # Step 2: LLM reasoning (if available)
                reasoning = None
                evidence_chains = []
                confidence = 0.5
                
                if self.llm_processor:
                    try:
                        reasoning = self.llm_processor.reason(
                            question=question,
                            context=search_result.items,
                            depth=reasoning_depth
                        )
                        confidence = reasoning.get('confidence', 0.5)
                        evidence_chains = reasoning.get('evidence', [])
                    except (ImportError, AttributeError, ValueError) as e:
                        logger.warning(f"LLM reasoning failed (degrading gracefully): {e}")
                        reasoning = {
                            'answer': "Reasoning unavailable - using search results only",
                            'error': str(e)
                        }
                    except _cancelled_exc_class():
                        raise
                    except Exception as e:
                        logger.error(f"Unexpected LLM reasoning error: {e}")
                        raise QueryExecutionError(
                            f"LLM reasoning failed: {e}",
                            details={
                                'question': question,
                                'depth': reasoning_depth,
                                'error': str(e),
                                'error_class': type(e).__name__,
                            }
                        ) from e
                
                return GraphRAGResult(
                    items=search_result.items,
                    stats=tracker.get_stats(),
                    counters=tracker.counters,
                    query_type='graphrag',
                    success=True,
                    reasoning=reasoning,
                    evidence_chains=evidence_chains,
                    confidence=confidence
                )
                
            except QueryExecutionError:
                # Re-raise query execution errors
                raise
            except QueryTimeoutError:
                # Re-raise timeout errors
                raise
            except QueryError:
                raise
            except (TimeoutError,) as e:
                logger.error(f"GraphRAG query timeout: {e}")
                raise QueryTimeoutError(
                    f"GraphRAG query timed out: {e}",
                    details={'question': question, 'depth': reasoning_depth}
                ) from e
            except _cancelled_exc_class():
                raise
            except Exception as e:
                logger.error(f"GraphRAG execution failed: {e}")
                raise QueryExecutionError(
                    f"Failed to execute GraphRAG query: {e}",
                    details={
                        'question': question,
                        'depth': reasoning_depth,
                        'k': k,
                        'error': str(e),
                        'error_class': type(e).__name__,
                    }
                ) from e
    
    def _detect_query_type(self, query: str) -> str:
        """
        Detect query type from query string.
        
        Args:
            query: Query string
            
        Returns:
            Query type ('cypher', 'hybrid', 'unknown')
        """
        query_upper = query.strip().upper()
        
        # Check for Cypher keywords
        cypher_keywords = ['MATCH', 'CREATE', 'MERGE', 'DELETE', 'SET', 'REMOVE', 'RETURN', 'WITH']
        if any(keyword in query_upper for keyword in cypher_keywords):
            return 'cypher'
        
        # If no Cypher keywords, assume hybrid search
        return 'hybrid'
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get engine statistics.
        
        Returns:
            Dictionary of statistics
        """
        return {
            'backend': str(type(self.backend).__name__),
            'vector_store_enabled': self.vector_store is not None,
            'llm_processor_enabled': self.llm_processor is not None,
            'caching_enabled': self.enable_caching,
            'default_budgets_preset': self.default_budgets_preset,
            'hybrid_search_cache_size': len(self.hybrid_search._cache),
        }

    async def execute_async(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        budgets: Optional[ExecutionBudgets] = None,
        query_type: str = 'auto',
    ) -> QueryResult:
        """Execute a query asynchronously.

        This is a thin async wrapper around :meth:`execute_query`.  It allows
        ``UnifiedQueryEngine`` to be used inside ``async``/``await`` code and
        async web frameworks (FastAPI, aiohttp, etc.) **without blocking the
        event loop**.

        The actual query execution is synchronous (Python graph traversal is
        CPU-bound, not I/O-bound).  The implementation delegates to
        :func:`asyncio.get_event_loop().run_in_executor` to offload the work
        to a thread-pool so the event loop remains unblocked.

        Args:
            query: Query string (Cypher, IR, or hybrid).
            params: Query parameters (substituted into the query).
            budgets: Execution budgets (uses engine defaults if ``None``).
            query_type: ``'auto'`` (default), ``'cypher'``, ``'ir'``, or
                ``'hybrid'``.

        Returns:
            :class:`QueryResult` with results and execution statistics.

        Example::

            import asyncio
            from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

            engine = UnifiedQueryEngine(backend=backend)
            result = asyncio.run(
                engine.execute_async("MATCH (p:Person) WHERE p.age > 30 RETURN p")
            )
        """
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.execute_query(query, params, budgets, query_type),
        )


__all__ = [
    'UnifiedQueryEngine',
    'QueryResult',
    'GraphRAGResult',
]
