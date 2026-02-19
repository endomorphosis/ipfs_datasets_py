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

Component role guide (Workstream I — naming normalization)
----------------------------------------------------------
There are three distinct "engine" concepts in the knowledge-graphs stack; each
has a clearly bounded responsibility:

1. **GraphEngine** (``core.graph_engine.GraphEngine``)
   Low-level, CRUD-oriented graph store.  Creates/reads/updates/deletes nodes
   and relationships, and persists them to an IPLD storage backend.  Think of
   it as the "table-level" API of a graph database.

2. **QueryExecutor** (``core.query_executor.QueryExecutor``)
   Cypher query compiler and executor.  Takes a Cypher string, parses it with
   ``cypher.CypherParser``, compiles it to IR via ``cypher.CypherCompiler``, and
   hands the IR off to ``core.ir_executor`` which walks the ``GraphEngine`` to
   evaluate the query.  This is the "SQL-parser-level" layer.

3. **UnifiedQueryEngine** (``query.unified_engine.UnifiedQueryEngine``)
   Full-featured orchestration layer.  Wraps both ``GraphEngine`` +
   ``QueryExecutor`` and adds: vector search (``HybridSearchEngine``), budget
   enforcement (``BudgetManager``), GraphRAG integration, multi-hop reasoning,
   and a single ``execute_query()`` entry point that automatically picks the
   right execution path.  This is what application code should use.

Typical call chain::

    UnifiedQueryEngine.execute_query(query)
        → QueryExecutor.execute(query)          # Cypher path
              → CypherParser → CypherCompiler
              → ir_executor.execute_ir_operations
                    → GraphEngine.find_nodes / get_relationships
                          → IPLDBackend.store / retrieve
        → HybridSearchEngine.search(query)      # vector path
        → GraphRAGQueryOptimizer.optimize()     # GraphRAG path

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
