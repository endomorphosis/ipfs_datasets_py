# Knowledge Graphs Module

**Version:** 2.0.0  
**Status:** ✅ Production Ready (Comprehensive Review Complete)  
**Last Updated:** 2026-02-18

---

## Overview

The Knowledge Graphs module provides comprehensive tools for building, querying, and reasoning over knowledge graphs in an IPFS-native environment. It combines entity extraction, relationship identification, graph storage, and advanced querying capabilities.

## 🎯 Quick Start

**New to knowledge graphs?** → See **[QUICKSTART.md](./QUICKSTART.md)** for a 5-minute introduction!

```python
# Basic usage - Extract knowledge graph from text
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
text = """
Marie Curie was a physicist who won the Nobel Prize in 1903.
She worked at the University of Paris.
"""

kg = extractor.extract_knowledge_graph(text)
print(f"Extracted {len(kg.entities)} entities and {len(kg.relationships)} relationships")

# Query the graph
persons = kg.get_entities_by_type("person")
for person in persons:
    print(f"Person: {person.name}")
```

**For more examples:** See [QUICKSTART.md](./QUICKSTART.md) and [USER_GUIDE.md](../../docs/knowledge_graphs/USER_GUIDE.md)

## 📋 Current Status & Plans

**📌 Module Status:** [MASTER_STATUS.md](./MASTER_STATUS.md) ⭐ - Single source of truth for features, coverage, roadmap  
**📖 Documentation Guide:** [DOCUMENTATION_GUIDE.md](./DOCUMENTATION_GUIDE.md) ⭐ - How to navigate all documentation  
**🔍 Latest Analysis:** [COMPREHENSIVE_ANALYSIS_2026_02_18.md](./COMPREHENSIVE_ANALYSIS_2026_02_18.md) ⭐ **NEW** - Comprehensive review findings

**Quick Links:**
- **Status & Features:** [MASTER_STATUS.md](./MASTER_STATUS.md) - Feature matrix, test coverage, roadmap
- **Planned Features:** [DEFERRED_FEATURES.md](./DEFERRED_FEATURES.md) - What's coming and when
- **Development Plan:** [ROADMAP.md](./ROADMAP.md) - Long-term development timeline
- **All Documentation:** [INDEX.md](./INDEX.md) - Complete documentation index

**Key Findings from Comprehensive Review (2026-02-18):**
- ✅ **Code is production-ready** - 71 Python files, all complete and functional
- ✅ **All P1-P4 features complete** (PR #1085, 36 new tests, ~1,850 lines)
- ✅ **Strong test coverage** - 75%+ overall, 80-85% on critical modules
- ✅ **Comprehensive documentation** - 54 markdown files (consolidated from duplicates)
- ✅ **Zero incomplete implementations** - All "incomplete" features are intentional deferrals
- ✅ **Previous work IS finished** - User concerns addressed through documentation streamlining

## 📁 Module Structure

```
knowledge_graphs/
├── README.md (this file)
├── MASTER_STATUS.md (⭐ single source of truth)
├── COMPREHENSIVE_ANALYSIS_2026_02_18.md (⭐ latest analysis)
├── IMPROVEMENT_TODO.md (♾️ living “infinite backlog”)
├── INDEX.md (documentation navigation)
│
├── extraction/           # Entity and relationship extraction
│   ├── README.md        # ✅ Complete documentation
│   ├── entities.py      # Entity class
│   ├── relationships.py # Relationship class
│   ├── graph.py         # KnowledgeGraph container
│   ├── extractor.py     # Main extraction engine
│   └── validator.py     # Validation and SPARQL checking
│
├── cypher/              # Cypher query language support
│   ├── lexer.py         # Tokenization
│   ├── parser.py        # Query parsing
│   ├── ast.py           # Abstract syntax tree
│   ├── compiler.py      # Query compilation
│   └── functions.py     # Cypher functions
│
├── query/               # Query execution engines
│   ├── unified_engine.py   # Unified query interface
│   ├── hybrid_search.py    # Hybrid (vector + graph) search
│   └── budget_manager.py   # Resource budgeting
│
├── core/                # Core graph engine
│   └── query_executor.py   # Query execution
│
├── storage/             # IPLD-based storage backend
│   ├── ipld_backend.py  # IPLD storage implementation
│   └── types.py         # Storage data types
│
├── transactions/        # ACID transaction support
│   ├── manager.py       # Transaction manager
│   ├── wal.py          # Write-ahead log
│   └── types.py        # Transaction types
│
├── neo4j_compat/        # Neo4j API compatibility layer
│   ├── driver.py        # Driver interface
│   ├── session.py       # Session management
│   ├── result.py        # Result handling
│   └── types.py         # Type mappings
│
├── constraints/         # Graph constraints
│   └── __init__.py      # Unique, existence, property constraints
│
├── indexing/            # Advanced indexing
│   ├── btree.py         # B-tree implementation
│   ├── manager.py       # Index manager
│   └── specialized.py   # Specialized indexes
│
├── jsonld/              # JSON-LD support
│   ├── context.py       # Context expansion
│   ├── translator.py    # IPLD ↔ JSON-LD translation
│   └── validation.py    # Schema validation
│
├── lineage/             # Cross-document lineage tracking
│   ├── core.py          # Core lineage functionality
│   ├── enhanced.py      # Enhanced tracking
│   └── visualization.py # Lineage visualization
│
└── migration/           # Data migration tools
    ├── neo4j_exporter.py   # Export from Neo4j
    ├── ipfs_importer.py    # Import to IPFS
    ├── schema_checker.py   # Schema compatibility
    └── integrity_verifier.py # Data integrity verification
```

## 📊 Current Status

✅ Production-ready and feature-complete for P1–P4 (see [MASTER_STATUS.md](./MASTER_STATUS.md)).

**Main ongoing improvements:**
- Increase migration module test coverage (target ≥70% in v2.0.1)
- Keep tightening error handling + diagnostics in hot paths

For the comprehensive, continuously-growing improvement plan, see **[IMPROVEMENT_TODO.md](./IMPROVEMENT_TODO.md)**.

## 🚀 Key Features

### Entity & Relationship Extraction
- **NER-based:** Uses spaCy for entity recognition
- **Rule-based:** Pattern matching for relationships
- **Transformers:** Optional transformer models for advanced extraction
- **Wikipedia integration:** Entity enrichment from Wikipedia

### Query Capabilities
- **Cypher support:** Neo4j-compatible Cypher query language
- **SPARQL templates:** Pre-built SPARQL queries
- **Hybrid search:** Combines vector and graph search
- **Cross-document reasoning:** Reason across multiple documents

### Storage & Performance
- **IPLD-native:** Content-addressed, immutable storage
- **Transactions:** ACID-compliant transaction support
- **Indexing:** B-tree and specialized indexes
- **Caching:** LRU caching for frequent queries

### Compatibility
- **Neo4j API:** Compatible with Neo4j driver API
- **JSON-LD:** Standard linked data format support
- **Migration tools:** Import/export between Neo4j and IPFS

## 📖 Documentation

### Quick Reference
- **[QUICKSTART.md](./QUICKSTART.md)** - 5-minute quick start guide ⚡
- **[MASTER_STATUS.md](./MASTER_STATUS.md)** - Feature matrix, test coverage, roadmap ⭐
- **[DEFERRED_FEATURES.md](./DEFERRED_FEATURES.md)** - Planned features with timelines 📅
- **[INDEX.md](./INDEX.md)** - Complete documentation index 📚
- **[IMPROVEMENT_TODO.md](./IMPROVEMENT_TODO.md)** - Living improvement backlog ♾️

### Main Documentation (in /docs)
- **KNOWLEDGE_GRAPHS_INTEGRATION_GUIDE.md** (37KB) - End-to-end workflows
- **KNOWLEDGE_GRAPHS_EXTRACTION_API.md** (21KB) - Extraction API reference
- **KNOWLEDGE_GRAPHS_QUERY_API.md** (22KB) - Query API reference
- **KNOWLEDGE_GRAPHS_USAGE_EXAMPLES.md** (27KB) - Code examples
- **KNOWLEDGE_GRAPHS_PERFORMANCE_OPTIMIZATION.md** (32KB) - Optimization guide

### Module Documentation
- **extraction/README.md** - Extraction package documentation
- ✅ Each subdirectory includes its own `README.md` (see [INDEX.md](./INDEX.md) for navigation)

## 🧪 Testing

**Test Coverage:** 49 test files
```bash
# Run all knowledge graph tests
pytest tests/unit/knowledge_graphs/

# Run specific module tests
pytest tests/unit/knowledge_graphs/test_extraction.py
pytest tests/unit/knowledge_graphs/test_cypher_integration.py
pytest tests/unit/knowledge_graphs/test_transactions.py
```

**Coverage by Module:**
- extraction: ~85%
- cypher: ~80%
- transactions: ~75%
- query: ~80%
- migration: ~40% ⚠️ (needs improvement)

## ⚠️ Known Issues & TODOs

**Critical (P0):**
- ✅ Bare exception handlers (FIXED in Phase 1)
- ✅ Empty constructors (FIXED in Phase 1)
- ✅ Backup files (REMOVED in Phase 1)

**High Priority (P1):**
- Improve migration module test coverage (see [MASTER_STATUS.md](./MASTER_STATUS.md))
- Continue deprecation cleanups (legacy import shims) without breaking compatibility

**See [IMPROVEMENT_TODO.md](./IMPROVEMENT_TODO.md) for the comprehensive list.**

## 🔧 Usage Patterns

### Pattern 1: Simple Extraction
```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph(text)

# Access entities and relationships
for entity in kg.entities:
    print(f"{entity.name} ({entity.entity_type})")
```

### Pattern 2: Extraction with Validation
```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractorWithValidation

validator = KnowledgeGraphExtractorWithValidation(validate_during_extraction=True)
result = validator.extract_knowledge_graph(text, validation_depth=2)

kg = result["knowledge_graph"]
metrics = result["validation_metrics"]
print(f"Validation coverage: {metrics['overall_coverage']:.2%}")
```

### Pattern 3: Graph Querying
```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

engine = UnifiedQueryEngine(backend=your_backend)
results = engine.execute("""
    MATCH (p:Person)-[r:WORKED_AT]->(o:Organization)
    WHERE p.name = 'Marie Curie'
    RETURN p, r, o
""")
```

### Pattern 4: Neo4j Compatibility
```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

driver = GraphDatabase.driver("ipfs://localhost:5001")
with driver.session() as session:
    result = session.run("MATCH (n) RETURN n LIMIT 10")
    for record in result:
        print(record["n"])
driver.close()
```

## 🛠️ Development

### Adding New Features
1. Follow the thin wrapper pattern (business logic in core modules)
2. Add comprehensive docstrings (see `docs/_example_docstring_format.md`)
3. Write tests (see `docs/_example_test_format.md`)
4. Update documentation

### Code Standards
- **Type hints:** All public APIs must have type hints
- **Exceptions:** Use specific exception types, not bare `except:` or generic `Exception`
- **Documentation:** All classes and public methods need docstrings
- **Testing:** >80% coverage required for new code

## 🚦 Migration Guide

### Deprecated API
The `knowledge_graph_extraction.py` module is being deprecated. Use the `extraction/` package instead:

```python
# OLD (still works but deprecated)
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    KnowledgeGraphExtractor
)

# NEW (recommended)
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor
)
```

**Note:** Full deprecation migration is planned for Phase 2 of the refactoring.

## 📈 Performance

- **Extraction:** ~100 words/second (CPU-dependent)
- **Simple queries:** <100ms
- **Complex queries:** <1 second
- **Transaction commit:** <1 second

See **KNOWLEDGE_GRAPHS_PERFORMANCE_OPTIMIZATION.md** for tuning guidance.

## 🤝 Contributing

See:
- [MASTER_STATUS.md](./MASTER_STATUS.md) for current status and gaps
- [IMPROVEMENT_TODO.md](./IMPROVEMENT_TODO.md) for open improvement tasks

## 📝 License

This module is part of the IPFS Datasets Python project. See main project LICENSE for details.

## 🔗 Related Modules

- **ipfs_embeddings_py:** Vector embeddings for semantic search
- **rag:** GraphRAG integration
- **pdf_processing:** PDF to knowledge graph extraction
- **logic_integration:** Formal logic and theorem proving

## 📞 Support

- **Issues:** Include current status + gaps from [MASTER_STATUS.md](./MASTER_STATUS.md)
- **Documentation:** Start with [../../docs/knowledge_graphs/USER_GUIDE.md](../../docs/knowledge_graphs/USER_GUIDE.md) and [../../docs/knowledge_graphs/MIGRATION_GUIDE.md](../../docs/knowledge_graphs/MIGRATION_GUIDE.md)
- **Tests:** See tests/unit/knowledge_graphs/

---

**Last Updated:** 2026-02-18  
**Next Milestone:** v2.0.1 (Q2 2026) - migration test coverage & polish
