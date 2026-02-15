"""
Cypher Query Language Support Module

This module provides comprehensive Cypher query language support for the
IPFS graph database.

Components:
- lexer: Tokenization of Cypher queries
- ast: Abstract Syntax Tree definitions  
- parser: Cypher query parser
- compiler: AST to IR compiler ✅ **NEW**
- optimizer: Query plan optimization (Phase 3)

Phase 2 Progress:
- Task 2.1: Grammar definition ✅
- Task 2.2: Lexer implementation ✅
- Task 2.3: Parser implementation ✅
- Task 2.4: AST structure ✅
- Task 2.5: Compiler ✅ **COMPLETE**
- Task 2.6: Integration (in progress)

Usage:
    from ipfs_datasets_py.knowledge_graphs.cypher import CypherParser, CypherCompiler
    
    # Parse Cypher query
    parser = CypherParser()
    ast = parser.parse("MATCH (n:Person) WHERE n.age > 30 RETURN n")
    
    # Compile to IR
    compiler = CypherCompiler()
    ir = compiler.compile(ast)
    
    # Execute IR (via QueryExecutor)
    executor.execute_ir(ir)
"""

# Phase 2 completed components
from .lexer import CypherLexer, Token, TokenType
from .ast import (
    ASTNode,
    ASTNodeType,
    QueryNode,
    MatchClause,
    WhereClause,
    ReturnClause,
    ReturnItem,
    OrderByClause,
    OrderItem,
    CreateClause,
    DeleteClause,
    SetClause,
    PatternNode,
    NodePattern,
    RelationshipPattern,
    ExpressionNode,
    BinaryOpNode,
    UnaryOpNode,
    PropertyAccessNode,
    FunctionCallNode,
    LiteralNode,
    VariableNode,
    ParameterNode,
    ListNode,
    MapNode,
    CaseExpressionNode,
    WhenClause,
    ASTVisitor,
    ASTPrettyPrinter,
)
from .parser import CypherParser, CypherParseError, parse_cypher
from .compiler import CypherCompiler, CypherCompileError, compile_cypher

__all__ = [
    # Lexer
    'CypherLexer',
    'Token',
    'TokenType',
    
    # AST nodes
    'ASTNode',
    'ASTNodeType',
    'QueryNode',
    'MatchClause',
    'WhereClause',
    'ReturnClause',
    'ReturnItem',
    'OrderByClause',
    'OrderItem',
    'CreateClause',
    'DeleteClause',
    'SetClause',
    'PatternNode',
    'NodePattern',
    'RelationshipPattern',
    'ExpressionNode',
    'BinaryOpNode',
    'UnaryOpNode',
    'PropertyAccessNode',
    'FunctionCallNode',
    'LiteralNode',
    'VariableNode',
    'ParameterNode',
    'ListNode',
    'MapNode',
    'CaseExpressionNode',
    'WhenClause',
    
    # Visitors
    'ASTVisitor',
    'ASTPrettyPrinter',
    
    # Parser
    'CypherParser',
    'CypherParseError',
    'parse_cypher',
    
    # Compiler
    'CypherCompiler',
    'CypherCompileError',
    'compile_cypher',
]

__version__ = '0.2.5'  # Phase 2 nearly complete
