"""
Cypher Query Language Module

This module provides Cypher query language support for the IPFS graph database,
enabling Neo4j-compatible queries to be executed on IPLD-stored graphs.

Architecture:
    Cypher Text → Lexer → Parser → AST → Compiler → IR → Executor
    
Components:
- Lexer: Tokenizes Cypher query text (Phase 2)
- Parser: Builds Abstract Syntax Tree (AST) from tokens (Phase 1 stub complete)
- AST: Internal representation of query structure (Phase 2)
- Compiler: Translates AST to IR (Intermediate Representation) (Phase 2)
- Optimizer: Cost-based query optimization (Phase 3)

Supported Cypher Features (Phase 2 - Weeks 3-4):
- MATCH patterns (nodes and relationships)
- WHERE clauses (filters and predicates)
- RETURN projections (with aliases)
- CREATE nodes and relationships
- SET properties
- DELETE operations
- ORDER BY, LIMIT, SKIP

Future Features (Post v1.0):
- WITH clause (query piping)
- MERGE (upsert operations)
- OPTIONAL MATCH
- Aggregations (COUNT, SUM, AVG, etc.)
- Path functions (shortestPath, allShortestPaths)
- List operations (UNWIND)
- Pattern comprehensions

Usage (Phase 2+):
    from ipfs_datasets_py.knowledge_graphs.cypher import CypherParser
    
    # Parse Cypher query
    parser = CypherParser()
    ast = parser.parse("MATCH (n:Person) WHERE n.age > 25 RETURN n.name")
    
    # Phase 2 will add compilation
    # compiler = CypherCompiler()
    # ir = compiler.compile(ast)
"""

# Phase 1 implementation (stub)
from .parser import CypherParser, CypherParseError, parse_cypher

__all__ = [
    "CypherParser",
    "CypherParseError",
    "parse_cypher",
]

# Version info
__version__ = "0.1.0"
__status__ = "development"  # Phase 1 stub complete
