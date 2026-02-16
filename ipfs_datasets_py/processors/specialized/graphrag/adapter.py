"""
GraphRAG Adapter

This module provides an adapter layer that bridges the existing GraphRAG processor
API to the new unified query engine. It maintains backward compatibility while
enabling gradual migration to the consolidated architecture.

The adapter:
- Wraps UnifiedQueryEngine with the old GraphRAGQueryEngine API
- Converts between old and new result formats
- Provides deprecation warnings for old usage patterns
- Enables incremental migration without breaking changes

Usage:
    # Old code continues to work
    from ipfs_datasets_py.processors.specialized.graphrag.adapter import GraphRAGAdapter
    
    adapter = GraphRAGAdapter(backend, vector_store, graph_store)
    result = adapter.query(
        query_text="What is IPFS?",
        top_k=10,
        include_cross_document_reasoning=True
    )
    
    # Internally uses UnifiedQueryEngine
"""

import logging
import warnings
from typing import Any, Dict, List, Optional
import numpy as np

from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine, HybridSearchEngine
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset, ExecutionBudgets

logger = logging.getLogger(__name__)


class GraphRAGAdapter:
    """
    Adapter bridging old GraphRAG API to unified query engine.
    
    This adapter provides backward compatibility for existing code that uses
    the processors/graphrag/ modules while internally using the new unified
    query engine architecture.
    
    Args:
        backend: Graph backend for storage/retrieval
        vector_stores: Dictionary of vector stores by model name
        graph_store: Knowledge graph store
        llm_processor: Optional LLM processor for reasoning
        enable_cross_document_reasoning: Enable cross-document reasoning
        default_budget_preset: Default budget preset ('strict', 'safe', 'debug')
    
    Example:
        adapter = GraphRAGAdapter(backend, vector_stores, graph_store)
        result = adapter.query("query text", top_k=10)
    """
    
    def __init__(
        self,
        backend: Any,
        vector_stores: Optional[Dict[str, Any]] = None,
        graph_store: Optional[Any] = None,
        llm_processor: Optional[Any] = None,
        enable_cross_document_reasoning: bool = True,
        default_budget_preset: str = 'safe'
    ):
        self.backend = backend
        self.vector_stores = vector_stores or {}
        self.graph_store = graph_store
        self.llm_processor = llm_processor
        self.enable_cross_document_reasoning = enable_cross_document_reasoning
        self.default_budget_preset = default_budget_preset
        
        # Get primary vector store (first one or None)
        self.primary_vector_store = None
        if self.vector_stores:
            self.primary_vector_store = next(iter(self.vector_stores.values()))
        
        # Create unified engine
        self.engine = UnifiedQueryEngine(
            backend=backend,
            vector_store=self.primary_vector_store,
            llm_processor=llm_processor,
            default_budgets=default_budget_preset
        )
        
        # Track metrics for compatibility
        self.metrics = {
            "queries_processed": 0,
            "total_query_time": 0.0,
            "avg_query_time": 0.0,
            "vector_searches": 0,
            "graph_traversals": 0,
            "cross_document_reasoning_uses": 0
        }
        
        logger.info("GraphRAGAdapter initialized (using UnifiedQueryEngine)")
    
    def query(
        self,
        query_text: str,
        query_embeddings: Optional[Dict[str, np.ndarray]] = None,
        top_k: int = 10,
        include_vector_results: bool = True,
        include_graph_results: bool = True,
        include_cross_document_reasoning: bool = True,
        entity_types: Optional[List[str]] = None,
        relationship_types: Optional[List[str]] = None,
        min_relevance: float = 0.5,
        max_graph_hops: int = 2,
        reasoning_depth: str = "moderate",
        return_trace: bool = False,
        budgets: Optional[ExecutionBudgets] = None
    ) -> Dict[str, Any]:
        """
        Perform a GraphRAG query (backward-compatible API).
        
        This method maintains the old API surface while internally using the
        unified query engine. It converts parameters and results to match
        the expected format.
        
        Args:
            query_text: Natural language query text
            query_embeddings: Optional pre-computed embeddings
            top_k: Number of results to return
            include_vector_results: Whether to include vector search
            include_graph_results: Whether to include graph traversal
            include_cross_document_reasoning: Whether to include reasoning
            entity_types: Entity types to filter (not yet supported)
            relationship_types: Relationship types to filter (not yet supported)
            min_relevance: Minimum relevance score (not yet supported)
            max_graph_hops: Maximum graph traversal hops
            reasoning_depth: Reasoning depth for LLM
            return_trace: Whether to return reasoning trace (not yet supported)
            budgets: Optional execution budgets
            
        Returns:
            Dictionary with query results matching old format
        """
        # Issue deprecation warning
        warnings.warn(
            "GraphRAGAdapter.query() is deprecated. "
            "Use UnifiedQueryEngine directly for new code.",
            DeprecationWarning,
            stacklevel=2
        )
        
        # Update metrics
        self.metrics["queries_processed"] += 1
        
        # Get or create budgets
        if budgets is None:
            budgets = budgets_from_preset(self.default_budget_preset)
        
        # Prepare embeddings context
        embeddings_context = None
        if query_embeddings:
            embeddings_context = {'query_embedding': query_embeddings}
        
        # Determine query type based on parameters
        if include_cross_document_reasoning and self.llm_processor:
            # Full GraphRAG with LLM reasoning
            self.metrics["cross_document_reasoning_uses"] += 1
            
            result = self.engine.execute_graphrag(
                question=query_text,
                context=embeddings_context or {},
                k=top_k,
                reasoning_depth=reasoning_depth,
                budgets=budgets
            )
            
            # Convert to old format
            return {
                "query_text": query_text,
                "hybrid_results": result.items,
                "reasoning_result": result.reasoning or {},
                "evidence_chains": result.evidence_chains or [],
                "confidence": result.confidence,
                "stats": result.stats,
                "success": result.success
            }
        
        elif include_vector_results or include_graph_results:
            # Hybrid search
            self.metrics["vector_searches"] += 1
            self.metrics["graph_traversals"] += 1
            
            # Calculate weights
            vector_weight = 0.6 if include_vector_results else 0.0
            graph_weight = 0.4 if include_graph_results else 0.0
            
            result = self.engine.execute_hybrid(
                query=query_text,
                k=top_k,
                vector_weight=vector_weight,
                graph_weight=graph_weight,
                max_hops=max_graph_hops,
                embeddings=embeddings_context,
                budgets=budgets
            )
            
            # Convert to old format
            return {
                "query_text": query_text,
                "hybrid_results": result.items,
                "vector_results": result.items if include_vector_results else [],
                "graph_results": result.items if include_graph_results else [],
                "stats": result.stats,
                "success": result.success
            }
        
        else:
            # No results requested?
            logger.warning("Query requested with no result types enabled")
            return {
                "query_text": query_text,
                "hybrid_results": [],
                "stats": {},
                "success": True
            }
    
    def visualize_query_result(
        self,
        result: Dict[str, Any],
        format: str = "mermaid"
    ) -> str:
        """
        Visualize query results (placeholder for compatibility).
        
        Args:
            result: Query result dictionary
            format: Output format ('mermaid', 'dot', 'json')
            
        Returns:
            Visualization string
        """
        warnings.warn(
            "visualize_query_result() is not yet implemented in adapter",
            DeprecationWarning,
            stacklevel=2
        )
        
        # Placeholder visualization
        if format == "mermaid":
            return f"```mermaid\ngraph TD\n  Q[{result.get('query_text', 'Query')}]\n```"
        elif format == "json":
            import json
            return json.dumps(result, indent=2, default=str)
        else:
            return str(result)
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get adapter metrics.
        
        Returns:
            Dictionary of metrics
        """
        # Update average query time
        if self.metrics["queries_processed"] > 0:
            self.metrics["avg_query_time"] = (
                self.metrics["total_query_time"] / 
                self.metrics["queries_processed"]
            )
        
        return self.metrics.copy()


# Convenience function for creating adapter from dataset
def create_graphrag_adapter_from_dataset(
    dataset: Any,
    llm_processor: Optional[Any] = None,
    **kwargs
) -> GraphRAGAdapter:
    """
    Create GraphRAGAdapter from a dataset object.
    
    Args:
        dataset: Dataset with backend, vector_stores, graph_store attributes
        llm_processor: Optional LLM processor
        **kwargs: Additional arguments to GraphRAGAdapter
        
    Returns:
        Configured GraphRAGAdapter instance
    """
    backend = getattr(dataset, 'backend', None) or getattr(dataset, 'graph_backend', None)
    vector_stores = getattr(dataset, 'vector_stores', {})
    graph_store = getattr(dataset, 'graph_store', None)
    
    if backend is None:
        raise ValueError("Dataset must have 'backend' or 'graph_backend' attribute")
    
    return GraphRAGAdapter(
        backend=backend,
        vector_stores=vector_stores,
        graph_store=graph_store,
        llm_processor=llm_processor,
        **kwargs
    )


__all__ = [
    'GraphRAGAdapter',
    'create_graphrag_adapter_from_dataset',
]
