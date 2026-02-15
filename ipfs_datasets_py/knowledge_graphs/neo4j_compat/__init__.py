"""
Neo4j Driver Compatibility Layer

This module provides a drop-in replacement for the Neo4j Python driver,
enabling existing Neo4j code to work with IPFS/IPLD-based graph storage
with minimal changes.

Usage:
    from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase
    
    # Change only the connection URI - everything else works as-is!
    driver = GraphDatabase.driver("ipfs://localhost:5001", auth=("user", "token"))
    
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN n LIMIT 10")
        for record in result:
            print(record["n"])
    
    driver.close()

Supported Features (Phase 1):
- Neo4j driver API (driver, session, result, record)
- Connection URI parsing (ipfs://, ipfs+embedded://)
- Session management (auto-commit, explicit transactions)
- Result handling (single, data, graph methods)
- Transaction support (begin, commit, rollback)
- Read/write transactions with retry logic
- Integration with ipfs_backend_router (Kubo, ipfs_kit_py, ipfs_accelerate_py)

Roadmap:
- Phase 1 (Weeks 1-2): Basic driver API and connection management ✅
- Phase 2 (Weeks 3-4): Cypher query language support
- Phase 3 (Weeks 5-6): ACID transactions with WAL
"""

# Phase 1 implementation complete
from .driver import IPFSDriver, GraphDatabase, create_driver
from .session import IPFSSession, IPFSTransaction
from .result import Result, Record
from .types import Node, Relationship, Path, GraphObject

__all__ = [
    # Main driver interface (Neo4j compatible)
    "GraphDatabase",
    "IPFSDriver",
    "create_driver",
    
    # Session and transaction management
    "IPFSSession",
    "IPFSTransaction",
    
    # Result handling
    "Result",
    "Record",
    
    # Graph types
    "Node",
    "Relationship",
    "Path",
    "GraphObject",
]

# Version info
__version__ = "0.1.0"
__author__ = "IPFS Datasets Team"
__description__ = "Neo4j-compatible graph database on IPFS/IPLD"
__status__ = "development"  # Phase 1 in progress
