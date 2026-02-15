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

Supported Features (v1.0):
- Neo4j driver API (driver, session, result, record)
- Connection URI parsing (ipfs://, ipfs+embedded://)
- Session management (auto-commit, explicit transactions)
- Query execution (Cypher queries translated to IR)
- Result handling (single, data, graph methods)
- Transaction support (begin, commit, rollback)
- Read/write transactions with retry logic

Roadmap:
- Phase 1 (Weeks 1-2): Basic driver API and connection management
- Phase 2 (Weeks 3-4): Cypher query language support
- Phase 3 (Weeks 5-6): ACID transactions with WAL
"""

# Phase 1 implementation (Weeks 1-2)
# from .driver import IPFSGraphDatabase, GraphDatabase
# from .session import IPFSSession, IPFSTransaction
# from .result import Result, Record
# from .types import Node, Relationship, Path

__all__ = [
    # Phase 1 exports will go here
    # "GraphDatabase",
    # "IPFSGraphDatabase",
    # "IPFSSession",
    # "IPFSTransaction",
    # "Result",
    # "Record",
    # "Node",
    # "Relationship",
    # "Path",
]

# Version info
__version__ = "0.1.0"
__author__ = "IPFS Datasets Team"
__description__ = "Neo4j-compatible graph database on IPFS/IPLD"
__status__ = "planning"  # Will be "development" in Phase 1
