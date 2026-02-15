"""
Cypher Query Language Module

This module provides Cypher query language support for the IPFS graph database,
enabling Neo4j-compatible queries to be executed on IPLD-stored graphs.

Architecture:
    Cypher Text → Lexer → Parser → AST → Compiler → IR → Executor
    
Components:
- Lexer: Tokenizes Cypher query text
- Parser: Builds Abstract Syntax Tree (AST) from tokens
- AST: Internal representation of query structure
- Compiler: Translates AST to IR (Intermediate Representation)
- Optimizer: Cost-based query optimization

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

Usage:
    from ipfs_datasets_py.knowledge_graphs.cypher import CypherParser, CypherCompiler
    
    # Parse Cypher query
    parser = CypherParser()
    ast = parser.parse("MATCH (n:Person) WHERE n.age > 25 RETURN n.name")
    
    # Compile to IR
    compiler = CypherCompiler()
    ir = compiler.compile(ast)
    
    # Execute via query engine
    result = executor.execute(ir, parameters={})
"""

# Phase 2 implementation (Weeks 3-4)
# from .lexer import CypherLexer
# from .parser import CypherParser
# from .ast import (
#     QueryNode, MatchNode, WhereNode, ReturnNode,
#     PatternNode, NodePatternNode, RelationshipPatternNode
# )
# from .compiler import CypherCompiler
# from .optimizer import CypherOptimizer

__all__ = [
    # Phase 2 exports will go here
    # "CypherLexer",
    # "CypherParser",
    # "CypherCompiler",
    # "CypherOptimizer",
]

# Version info
__version__ = "0.1.0"
__status__ = "planning"  # Will be "development" in Phase 2
