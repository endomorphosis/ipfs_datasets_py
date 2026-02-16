"""
Knowledge Graphs Query Module

This module provides a unified query engine for GraphRAG operations, consolidating
previously fragmented implementations from:
- processors/graphrag/
- search/graphrag_integration/
- search/graph_query/

The unified architecture provides:
- Single entry point for all query types
- Consistent budget management
- Reusable hybrid search (vector + graph)
- Simplified maintenance and extensibility

Main Components:
- UnifiedQueryEngine: Central query execution engine
- HybridSearchEngine: Vector + graph search fusion
- BudgetManager: Budget enforcement wrapper

Usage:
    from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
    from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset
    
    engine = UnifiedQueryEngine(backend=backend)
    budgets = budgets_from_preset('moderate')
    result = engine.execute_query(query, budgets=budgets)
"""

from .unified_engine import UnifiedQueryEngine
from .hybrid_search import HybridSearchEngine  
from .budget_manager import BudgetManager

__all__ = [
    'UnifiedQueryEngine',
    'HybridSearchEngine',
    'BudgetManager',
]
