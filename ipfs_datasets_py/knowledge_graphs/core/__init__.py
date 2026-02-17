"""
Core Graph Database Engine

This module provides the core graph database engine that coordinates
all components of the IPFS graph database system.

Components:
- GraphEngine: Main engine coordinating all operations
- QueryExecutor: Executes queries against IPLD graphs
- IndexManager: Manages B-tree and full-text indexes (Phase 5)
- ConstraintManager: Enforces uniqueness and existence constraints (Phase 5)

Architecture Flow:
    Driver API → Session → QueryExecutor → GraphEngine → StorageBackend → IPFS
                                      ↓
                              TransactionManager
                                      ↓
                                    WAL

Features:
- Unified query execution interface
- Transaction coordination
- Index-accelerated queries
- Constraint validation
- Performance monitoring

Usage:
    from ipfs_datasets_py.knowledge_graphs.core import GraphEngine, QueryExecutor
    
    # Create graph engine
    from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend
    storage = IPLDBackend()
    engine = GraphEngine(storage_backend=storage)
    
    # Create query executor
    executor = QueryExecutor(graph_engine=engine)
    result = executor.execute("MATCH (n) RETURN n")

Roadmap:
- Phase 1 (Weeks 1-2): Basic query routing and execution ✅ (in progress)
- Phase 2 (Weeks 3-4): Cypher query compilation integration
- Phase 3 (Weeks 5-6): Transaction integration
- Phase 5 (Week 8): Index and constraint management
"""

# Phase 1 implementation complete
from .graph_engine import GraphEngine
from .query_executor import QueryExecutor

__all__ = [
    "GraphEngine",
    "QueryExecutor",
]

# Version info
__version__ = "0.1.0"
__status__ = "development"  # Phase 1 in progress
