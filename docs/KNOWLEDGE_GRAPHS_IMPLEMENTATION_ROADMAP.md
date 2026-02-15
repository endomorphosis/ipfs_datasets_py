# Knowledge Graphs Refactoring: Implementation Roadmap

**Version:** 1.0  
**Date:** 2026-02-15  
**Estimated Duration:** 8-10 weeks

---

## Overview

This roadmap breaks down the comprehensive refactoring plan into actionable tasks with dependencies, priorities, and estimated effort.

---

## Phase 1: Foundation (Weeks 1-2)

**Goal**: Set up core architecture and Neo4j compatibility layer

### Week 1: Module Structure & Driver API

#### Task 1.1: Create Module Structure (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: None

**Subtasks**:
- [ ] Create `knowledge_graphs/neo4j_compat/` directory
- [ ] Create `knowledge_graphs/cypher/` directory
- [ ] Create `knowledge_graphs/transactions/` directory
- [ ] Create `knowledge_graphs/core/` directory
- [ ] Create `knowledge_graphs/storage/` directory
- [ ] Create `knowledge_graphs/jsonld/` directory
- [ ] Update `knowledge_graphs/__init__.py` with exports

**Files to Create**:
```
knowledge_graphs/
├── neo4j_compat/
│   ├── __init__.py
│   ├── driver.py
│   ├── session.py
│   ├── result.py
│   └── types.py
├── cypher/
│   ├── __init__.py
│   ├── lexer.py
│   ├── parser.py
│   ├── ast.py
│   ├── compiler.py
│   └── optimizer.py
├── transactions/
│   ├── __init__.py
│   ├── manager.py
│   ├── wal.py
│   └── isolation.py
├── core/
│   ├── __init__.py
│   ├── graph_engine.py
│   └── query_executor.py
├── storage/
│   ├── __init__.py
│   ├── ipld_backend.py
│   └── cache.py
└── jsonld/
    ├── __init__.py
    └── translator.py
```

**Acceptance Criteria**:
- All directories created
- `__init__.py` files with proper exports
- Documentation stubs in place

---

#### Task 1.2: Implement Driver API (3 days)
- **Priority**: P0
- **Effort**: 24 hours
- **Dependencies**: Task 1.1

**Subtasks**:
- [ ] Implement `IPFSGraphDatabase` class (driver factory)
- [ ] Implement `IPFSDriver` class (connection management)
- [ ] Implement `IPFSSession` class (session management)
- [ ] Implement `Result` class (query results)
- [ ] Implement `Record` class (single result row)
- [ ] Add connection URI parsing (`ipfs://`, `ipfs+embedded://`)
- [ ] Add authentication handling

**Code Skeleton**:
```python
# neo4j_compat/driver.py
class IPFSGraphDatabase:
    @staticmethod
    def driver(uri: str, auth: tuple = None, **config):
        """Create driver compatible with neo4j.GraphDatabase.driver()"""
        pass

# neo4j_compat/session.py
class IPFSSession:
    def run(self, query: str, parameters: dict = None) -> Result:
        """Execute Cypher query"""
        pass
    
    def begin_transaction(self, **kwargs) -> Transaction:
        """Start explicit transaction"""
        pass
    
    def read_transaction(self, func, *args, **kwargs):
        """Read transaction with retry"""
        pass
    
    def write_transaction(self, func, *args, **kwargs):
        """Write transaction with retry"""
        pass
```

**Tests**:
- [ ] Test driver creation
- [ ] Test session creation
- [ ] Test connection URI parsing
- [ ] Test authentication
- [ ] Test resource cleanup

**Acceptance Criteria**:
- Driver API is Neo4j-compatible
- All unit tests pass
- Documentation complete

---

#### Task 1.3: Implement Query Routing (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: Task 1.2

**Subtasks**:
- [ ] Create query router that sends queries to appropriate backend
- [ ] Add temporary stub for Cypher parser (returns error)
- [ ] Integrate with existing IR query executor
- [ ] Add query parameter validation
- [ ] Add result formatting

**Code Skeleton**:
```python
# core/query_executor.py
class QueryExecutor:
    def execute(self, query: str, parameters: dict = None) -> Result:
        """Route query to appropriate backend"""
        if self._is_cypher_query(query):
            # Phase 2: Parse and execute
            return self._execute_cypher(query, parameters)
        else:
            # Fallback to existing IR executor
            return self._execute_ir(query, parameters)
```

**Acceptance Criteria**:
- Query routing works for IR queries
- Cypher queries return helpful error message
- All tests pass

---

### Week 2: Storage Integration & Testing

#### Task 1.4: Integrate Existing IPLD Storage (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: Task 1.3

**Subtasks**:
- [ ] Move IPLD storage code to `knowledge_graphs/storage/`
- [ ] Create unified storage backend interface
- [ ] Add caching layer
- [ ] Add connection pooling
- [ ] Update imports across codebase

**Code Skeleton**:
```python
# storage/ipld_backend.py
class IPLDStorageBackend:
    def __init__(self, ipfs_uri: str, cache_config: CacheConfig = None):
        self.ipld_storage = IPLDStorage(ipfs_uri)
        self.cache = Cache(cache_config)
    
    def get_graph(self, cid: str) -> IPLDKnowledgeGraph:
        """Load graph from CID with caching"""
        pass
    
    def save_graph(self, graph: IPLDKnowledgeGraph) -> str:
        """Save graph and return root CID"""
        pass
```

**Acceptance Criteria**:
- IPLD storage is accessible through driver API
- Caching works correctly
- All existing tests still pass

---

#### Task 1.5: Add Backward Compatibility (1 day)
- **Priority**: P1
- **Effort**: 8 hours
- **Dependencies**: Task 1.4

**Subtasks**:
- [ ] Add deprecation warnings to old APIs
- [ ] Create migration guide for existing code
- [ ] Update examples to use new API
- [ ] Add compatibility shims

**Acceptance Criteria**:
- All existing code still works with warnings
- Migration guide is clear
- Examples are updated

---

#### Task 1.6: Phase 1 Testing (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: Tasks 1.1-1.5

**Subtasks**:
- [ ] Write 50+ unit tests for driver API
- [ ] Write 20+ integration tests
- [ ] Add performance benchmarks
- [ ] Test with existing IR queries
- [ ] Test connection management
- [ ] Test error handling

**Test Files**:
```
tests/unit/knowledge_graphs/
├── test_driver.py
├── test_session.py
├── test_result.py
├── test_storage_backend.py
└── test_query_executor.py

tests/integration/knowledge_graphs/
├── test_driver_integration.py
└── test_storage_integration.py
```

**Acceptance Criteria**:
- All tests pass
- Test coverage >90%
- Performance benchmarks establish baseline

---

## Phase 2: Cypher Parser (Weeks 3-4)

**Goal**: Implement working Cypher parser and compiler

### Week 3: Lexer & Parser

#### Task 2.1: Define Cypher Grammar (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: Phase 1

**Subtasks**:
- [ ] Choose parser generator (PLY, ANTLR, or manual)
- [ ] Define Cypher 5.0 grammar subset (P0 features)
- [ ] Create lexer tokens
- [ ] Define parser rules
- [ ] Add syntax error handling

**Grammar Subset (P0)**:
```
query: match_clause where_clause? return_clause
     | create_clause
     | match_clause set_clause
     | match_clause delete_clause

match_clause: MATCH pattern (COMMA pattern)*
pattern: node_pattern (relationship_pattern node_pattern)*
node_pattern: LPAREN variable? node_labels? properties? RPAREN
relationship_pattern: (left_arrow? relationship_detail? right_arrow?)
where_clause: WHERE expression
return_clause: RETURN return_items (ORDER BY order_items)? (LIMIT number)? (SKIP number)?
```

**Acceptance Criteria**:
- Grammar is complete for P0 features
- Parser can parse basic queries
- Syntax errors are helpful

---

#### Task 2.2: Implement Lexer (1 day)
- **Priority**: P0
- **Effort**: 8 hours
- **Dependencies**: Task 2.1

**Subtasks**:
- [ ] Implement token definitions
- [ ] Add keyword recognition
- [ ] Add operator tokenization
- [ ] Add string literal handling
- [ ] Add number parsing
- [ ] Add identifier rules

**Code Skeleton**:
```python
# cypher/lexer.py
class CypherLexer:
    tokens = [
        'MATCH', 'WHERE', 'RETURN', 'CREATE', 'DELETE', 'SET',
        'LPAREN', 'RPAREN', 'LBRACKET', 'RBRACKET', 'LBRACE', 'RBRACE',
        'IDENTIFIER', 'NUMBER', 'STRING',
        'ARROW_LEFT', 'ARROW_RIGHT', 'COLON', 'COMMA', 'DOT'
    ]
    
    def tokenize(self, text: str) -> Iterator[Token]:
        """Convert Cypher text to tokens"""
        pass
```

**Tests**:
- [ ] Test keyword recognition
- [ ] Test identifier parsing
- [ ] Test string escaping
- [ ] Test number formats (int, float, scientific)

**Acceptance Criteria**:
- All Cypher keywords are recognized
- Edge cases handled (Unicode, special chars)
- All tests pass

---

#### Task 2.3: Implement Parser (3 days)
- **Priority**: P0
- **Effort**: 24 hours
- **Dependencies**: Task 2.2

**Subtasks**:
- [ ] Implement recursive descent parser
- [ ] Add precedence handling
- [ ] Add error recovery
- [ ] Build AST during parsing
- [ ] Add helpful error messages

**Code Skeleton**:
```python
# cypher/parser.py
class CypherParser:
    def parse(self, tokens: List[Token]) -> AST:
        """Parse tokens into AST"""
        pass
    
    def parse_match(self) -> MatchNode:
        """Parse MATCH clause"""
        pass
    
    def parse_pattern(self) -> PatternNode:
        """Parse graph pattern"""
        pass
    
    def parse_where(self) -> WhereNode:
        """Parse WHERE clause"""
        pass
```

**Tests**:
- [ ] Test basic MATCH queries (50 tests)
- [ ] Test pattern variations (30 tests)
- [ ] Test WHERE predicates (30 tests)
- [ ] Test RETURN projections (20 tests)
- [ ] Test error cases (20 tests)

**Acceptance Criteria**:
- Parser handles all P0 queries
- AST is well-structured
- Error messages are clear
- All tests pass

---

### Week 4: AST → IR Compiler

#### Task 2.4: Define AST Structure (1 day)
- **Priority**: P0
- **Effort**: 8 hours
- **Dependencies**: Task 2.3

**Subtasks**:
- [ ] Define AST node classes
- [ ] Add type hints
- [ ] Add visitor pattern support
- [ ] Add AST validation
- [ ] Add pretty printing for debugging

**Code Skeleton**:
```python
# cypher/ast.py
@dataclass
class ASTNode:
    """Base AST node"""
    pass

@dataclass
class QueryNode(ASTNode):
    clauses: List[ClauseNode]

@dataclass
class MatchNode(ClauseNode):
    patterns: List[PatternNode]
    where: Optional[WhereNode]

@dataclass
class PatternNode(ASTNode):
    nodes: List[NodePatternNode]
    relationships: List[RelationshipPatternNode]
```

**Acceptance Criteria**:
- All AST nodes are defined
- Type hints are complete
- Visitor pattern works

---

#### Task 2.5: Implement AST → IR Compiler (3 days)
- **Priority**: P0
- **Effort**: 24 hours
- **Dependencies**: Task 2.4

**Subtasks**:
- [ ] Implement compiler that converts AST to existing IR format
- [ ] Add pattern matching logic
- [ ] Add predicate translation
- [ ] Add projection translation
- [ ] Add optimization hints

**Code Skeleton**:
```python
# cypher/compiler.py
class CypherCompiler:
    def compile(self, ast: AST) -> QueryIR:
        """Convert AST to IR"""
        pass
    
    def compile_match(self, match: MatchNode) -> List[IROperation]:
        """Compile MATCH to ScanType + Expand operations"""
        pass
    
    def compile_where(self, where: WhereNode) -> List[IROperation]:
        """Compile WHERE to Filter operations"""
        pass
    
    def compile_return(self, ret: ReturnNode) -> List[IROperation]:
        """Compile RETURN to Project + OrderBy + Limit"""
        pass
```

**Translation Examples**:
```cypher
MATCH (p:Person {name: "Alice"})
RETURN p.age
```

Compiles to IR:
```python
[
    {"op": "ScanType", "type": "Person", "filters": {"name": "Alice"}},
    {"op": "Project", "fields": ["age"]}
]
```

**Tests**:
- [ ] Test MATCH compilation (40 tests)
- [ ] Test WHERE compilation (30 tests)
- [ ] Test RETURN compilation (20 tests)
- [ ] Test CREATE compilation (20 tests)
- [ ] Test complex queries (20 tests)

**Acceptance Criteria**:
- All P0 queries compile correctly
- Generated IR is optimized
- All tests pass

---

#### Task 2.6: Integrate Parser with Driver (1 day)
- **Priority**: P0
- **Effort**: 8 hours
- **Dependencies**: Task 2.5

**Subtasks**:
- [ ] Update query executor to use parser
- [ ] Add fallback to IR for non-Cypher queries
- [ ] Add query caching
- [ ] Add execution tracing

**Code Skeleton**:
```python
# core/query_executor.py (updated)
class QueryExecutor:
    def execute(self, query: str, parameters: dict = None) -> Result:
        # Try to parse as Cypher
        try:
            ast = self.cypher_parser.parse(query)
            ir = self.cypher_compiler.compile(ast)
            return self._execute_ir(ir, parameters)
        except CypherSyntaxError:
            # Fallback to IR if not Cypher
            return self._execute_ir(query, parameters)
```

**Acceptance Criteria**:
- Cypher queries execute correctly
- IR queries still work
- Performance is acceptable

---

## Phase 3: Transaction System (Weeks 5-6)

**Goal**: Implement ACID-compliant transaction layer

### Week 5: Write-Ahead Logging

#### Task 3.1: Design WAL Structure (1 day)
- **Priority**: P0
- **Effort**: 8 hours
- **Dependencies**: Phase 2

**Subtasks**:
- [ ] Define WAL entry format on IPLD
- [ ] Design transaction log structure
- [ ] Add CID-based versioning
- [ ] Design commit protocol

**WAL Entry Format**:
```python
@dataclass
class WALEntry:
    txn_id: str
    timestamp: int
    operations: List[Operation]
    prev_wal_cid: Optional[str]
    
    # Each operation is:
    # {"type": "write_node", "node": {...}}
    # {"type": "write_relationship", "rel": {...}}
    # {"type": "delete_node", "node_id": "..."}
```

**Acceptance Criteria**:
- WAL structure is defined
- Documentation is complete

---

#### Task 3.2: Implement WAL (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: Task 3.1

**Subtasks**:
- [ ] Implement WAL writer
- [ ] Implement WAL reader
- [ ] Add WAL compaction
- [ ] Add WAL recovery
- [ ] Store WAL on IPLD

**Code Skeleton**:
```python
# transactions/wal.py
class WriteAheadLog:
    def append(self, entry: WALEntry) -> str:
        """Append entry to WAL and return CID"""
        pass
    
    def read(self, from_cid: str) -> Iterator[WALEntry]:
        """Read WAL entries from CID"""
        pass
    
    def compact(self, checkpoint_cid: str):
        """Compact WAL up to checkpoint"""
        pass
    
    def recover(self, wal_head_cid: str) -> List[Operation]:
        """Recover operations from WAL"""
        pass
```

**Tests**:
- [ ] Test WAL append
- [ ] Test WAL read
- [ ] Test WAL recovery
- [ ] Test WAL compaction

**Acceptance Criteria**:
- WAL operations work correctly
- Recovery handles edge cases
- All tests pass

---

#### Task 3.3: Implement Transaction Manager (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: Task 3.2

**Subtasks**:
- [ ] Implement transaction begin/commit/rollback
- [ ] Add isolation level support
- [ ] Add conflict detection
- [ ] Add retry logic
- [ ] Add deadlock detection (future)

**Code Skeleton**:
```python
# transactions/manager.py
class TransactionManager:
    def begin(self, isolation_level: IsolationLevel = IsolationLevel.REPEATABLE_READ) -> Transaction:
        """Start new transaction"""
        pass
    
    def commit(self, txn: Transaction) -> str:
        """Commit transaction and return root CID"""
        pass
    
    def rollback(self, txn: Transaction):
        """Rollback transaction"""
        pass
    
    def detect_conflicts(self, txn: Transaction) -> bool:
        """Detect write-write conflicts"""
        pass
```

**Tests**:
- [ ] Test begin/commit/rollback (20 tests)
- [ ] Test conflict detection (15 tests)
- [ ] Test isolation levels (15 tests)
- [ ] Test concurrent transactions (10 tests)

**Acceptance Criteria**:
- Transactions work correctly
- Conflicts are detected
- All tests pass

---

### Week 6: Integration & Testing

#### Task 3.4: Integrate Transactions with Driver (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: Task 3.3

**Subtasks**:
- [ ] Update session to support transactions
- [ ] Add transaction context management
- [ ] Add read_transaction/write_transaction
- [ ] Update query executor to use transactions

**Code Skeleton**:
```python
# neo4j_compat/session.py (updated)
class IPFSSession:
    def begin_transaction(self, **kwargs) -> Transaction:
        return self.txn_manager.begin(**kwargs)
    
    def write_transaction(self, func, *args, **kwargs):
        """Execute function in transaction with retry"""
        for attempt in range(MAX_RETRIES):
            txn = self.begin_transaction()
            try:
                result = func(txn, *args, **kwargs)
                txn.commit()
                return result
            except TransactionConflict:
                txn.rollback()
                if attempt == MAX_RETRIES - 1:
                    raise
```

**Acceptance Criteria**:
- Transactions integrate with session API
- Retry logic works
- All tests pass

---

#### Task 3.5: Add Isolation Levels (1 day)
- **Priority**: P1
- **Effort**: 8 hours
- **Dependencies**: Task 3.4

**Subtasks**:
- [ ] Implement READ_UNCOMMITTED
- [ ] Implement READ_COMMITTED
- [ ] Implement REPEATABLE_READ (default)
- [ ] Implement SERIALIZABLE

**Tests**:
- [ ] Test each isolation level (20 tests)
- [ ] Test concurrent behavior (10 tests)

**Acceptance Criteria**:
- All isolation levels work
- Behavior matches Neo4j
- All tests pass

---

#### Task 3.6: Phase 3 Testing (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: Tasks 3.1-3.5

**Subtasks**:
- [ ] Write 50+ transaction tests
- [ ] Add concurrency tests
- [ ] Add stress tests
- [ ] Performance benchmarks

**Acceptance Criteria**:
- All tests pass
- Performance is acceptable
- Stress tests show stability

---

## Phase 4: JSON-LD Translation (Week 7)

**Goal**: Enable JSON-LD to IPLD conversion

### Task 4.1: Implement Context Expansion (1 day)
- **Priority**: P0
- **Effort**: 8 hours
- **Dependencies**: Phase 3

**Subtasks**:
- [ ] Parse JSON-LD @context
- [ ] Expand terms to full URIs
- [ ] Handle @vocab
- [ ] Handle @base

**Code Skeleton**:
```python
# jsonld/translator.py
class JSONLDTranslator:
    def expand_context(self, jsonld: dict) -> dict:
        """Expand JSON-LD context"""
        pass
```

**Acceptance Criteria**:
- Context expansion works
- Common vocabularies supported
- Tests pass

---

### Task 4.2: Implement Bidirectional Translation (2 days)
- **Priority**: P0
- **Effort**: 16 hours
- **Dependencies**: Task 4.1

**Subtasks**:
- [ ] JSON-LD → IPLD translation
- [ ] IPLD → JSON-LD translation
- [ ] Preserve semantic meaning
- [ ] Handle blank nodes

**Tests**:
- [ ] Test simple translation (20 tests)
- [ ] Test complex graphs (20 tests)
- [ ] Test round-trip (10 tests)

**Acceptance Criteria**:
- Translation is bidirectional
- Semantics preserved
- All tests pass

---

### Task 4.3: Add Vocabulary Support (2 days)
- **Priority**: P1
- **Effort**: 16 hours
- **Dependencies**: Task 4.2

**Subtasks**:
- [ ] Add Schema.org support
- [ ] Add FOAF support
- [ ] Add Dublin Core support
- [ ] Add custom vocabulary support

**Acceptance Criteria**:
- Common vocabularies work
- Custom vocabularies supported
- Tests pass

---

## Phase 5: Advanced Features (Week 8)

**Goal**: Add indexing, constraints, and optimization

### Task 5.1: Implement B-Tree Indexes (2 days)
- **Priority**: P1
- **Effort**: 16 hours
- **Dependencies**: Phase 4

**Subtasks**:
- [ ] Design B-tree on IPLD
- [ ] Implement index creation
- [ ] Implement index queries
- [ ] Add index maintenance

**Acceptance Criteria**:
- Indexes work correctly
- Performance improves
- Tests pass

---

### Task 5.2: Implement Constraints (2 days)
- **Priority**: P1
- **Effort**: 16 hours
- **Dependencies**: Task 5.1

**Subtasks**:
- [ ] Add unique constraints
- [ ] Add existence constraints
- [ ] Add type constraints
- [ ] Add validation

**Acceptance Criteria**:
- Constraints enforce rules
- Violations detected
- Tests pass

---

### Task 5.3: Query Optimization (1 day)
- **Priority**: P1
- **Effort**: 8 hours
- **Dependencies**: Tasks 5.1-5.2

**Subtasks**:
- [ ] Add cost-based optimizer
- [ ] Add index selection
- [ ] Add query rewriting

**Acceptance Criteria**:
- Queries are faster
- Optimizer makes good choices
- Benchmarks show improvement

---

## Summary

### Total Effort
- **Phase 1**: 96 hours (2 weeks)
- **Phase 2**: 96 hours (2 weeks)
- **Phase 3**: 96 hours (2 weeks)
- **Phase 4**: 48 hours (1 week)
- **Phase 5**: 48 hours (1 week)
- **Total**: 384 hours (8 weeks with 1 FTE)

### Key Milestones
1. **Week 2**: Driver API working with IR queries
2. **Week 4**: Cypher queries working end-to-end
3. **Week 6**: ACID transactions fully implemented
4. **Week 7**: JSON-LD translation working
5. **Week 8**: Indexes and constraints implemented

### Success Metrics
- ✅ 95%+ Cypher compatibility
- ✅ 100% Neo4j driver API compatibility
- ✅ Full ACID transactions
- ✅ <2x performance overhead
- ✅ 90%+ test coverage

---

**Next Steps**:
1. Review and approve roadmap
2. Set up development branch: `feature/neo4j-graph-database`
3. Begin Phase 1, Task 1.1
4. Weekly progress reviews and adjustments
