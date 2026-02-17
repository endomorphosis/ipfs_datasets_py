# Knowledge Graphs - Migration Guide

**Version:** 2.0.0  
**Last Updated:** 2026-02-17

---

## Table of Contents

1. [Overview](#overview)
2. [Migration from Legacy API](#migration-from-legacy-api)
3. [Known Limitations](#known-limitations)
4. [Feature Support Matrix](#feature-support-matrix)
5. [Breaking Changes](#breaking-changes)
6. [Compatibility Matrix](#compatibility-matrix)
7. [Neo4j to IPFS Migration](#neo4j-to-ipfs-migration)
8. [Migration Checklist](#migration-checklist)
9. [Common Migration Issues](#common-migration-issues)
10. [Deprecation Timeline](#deprecation-timeline)

---

## Overview

This guide covers:
- Migrating from legacy API to new modular structure
- Known limitations and workarounds
- Breaking changes between versions
- Neo4j to IPFS migration path
- Common issues and solutions

---

## Migration from Legacy API

### Old Import Path (Deprecated)

```python
# Old (still works but shows deprecation warning)
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor
)
```

### New Import Path (Recommended)

```python
# New (recommended)
from ipfs_datasets_py.knowledge_graphs.extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor
)
```

**Migration Steps:**
1. Update import statements to use `extraction` package
2. Test that all functionality works as expected
3. Remove old imports once validated

**Backward Compatibility:** Both paths work identically - no code changes needed beyond imports.

---

## Known Limitations

### Migration Format Support

The migration module supports the most common graph formats but has some limitations:

#### ✅ Supported Formats

| Format | Import | Export | Notes |
|--------|--------|--------|-------|
| **CSV** | ✅ Yes | ✅ Yes | Entities and relationships as separate CSVs |
| **JSON** | ✅ Yes | ✅ Yes | Native KnowledgeGraph JSON format |
| **Neo4j Cypher Dump** | ✅ Yes | ✅ Yes | Full Cypher statements |
| **IPLD/IPFS** | ✅ Yes | ✅ Yes | Content-addressed storage |

#### ⚠️ Unsupported Formats

| Format | Status | Workaround |
|--------|--------|------------|
| **GraphML** | Not implemented | Export to CSV or JSON, then convert externally |
| **GEXF** | Not implemented | Use CSV/JSON intermediate format |
| **Pajek** | Not implemented | Convert via NetworkX to CSV/JSON |

**Implementation Status:** These formats are low priority as they are rarely used in production. If you need support for these formats:

**Workaround Option 1 - CSV Export:**
```python
# Export to CSV first
entities_df = pd.DataFrame([e.to_dict() for e in kg.entities.values()])
entities_df.to_csv('entities.csv', index=False)

relationships_df = pd.DataFrame([r.to_dict() for r in kg.relationships.values()])
relationships_df.to_csv('relationships.csv', index=False)

# Then convert CSV to target format using external tools
```

**Workaround Option 2 - JSON Export:**
```python
# Export to JSON
json_data = kg.to_json()

# Use external conversion library (e.g., NetworkX)
import networkx as nx
G = nx.node_link_graph(json.loads(json_data))
nx.write_graphml(G, 'graph.graphml')  # Convert to GraphML
```

### Cypher Language Support

#### ✅ Supported Cypher Features

| Feature | Status | Example |
|---------|--------|---------|
| **MATCH** | ✅ Full | `MATCH (n:Person) RETURN n` |
| **WHERE** | ✅ Full | `WHERE n.name = 'Marie Curie'` |
| **RETURN** | ✅ Full | `RETURN n, r, o` |
| **CREATE (nodes)** | ✅ Full | `CREATE (n:Person {name: 'Alice'})` |
| **ORDER BY** | ✅ Full | `ORDER BY n.name DESC` |
| **LIMIT** | ✅ Full | `LIMIT 10` |
| **Aggregations** | ✅ Full | `COUNT(n)`, `SUM(n.value)`, `AVG()`, `MIN()`, `MAX()` |
| **String Functions** | ✅ Partial | `CONTAINS()`, `STARTS WITH()`, `ENDS WITH()` |

#### ⚠️ Unsupported Cypher Features

| Feature | Status | Workaround |
|---------|--------|------------|
| **NOT operator** | Not implemented | Use positive conditions: `WHERE n.age > 18` instead of `WHERE NOT n.age <= 18` |
| **CREATE (relationships)** | Not implemented | Create relationships via Python API: `kg.add_relationship(rel)` |
| **Complex pattern matching** | Limited | Break into multiple simpler queries |
| **MERGE** | Not implemented | Use CREATE + deduplication logic |
| **DELETE** | Not implemented | Remove via Python API: `kg.entities.pop(entity_id)` |

**Workaround for NOT operator:**
```cypher
# Instead of: WHERE NOT n.age < 18
# Use: WHERE n.age >= 18

# Instead of: WHERE NOT n.name CONTAINS 'test'
# Filter results in Python after query
```

**Workaround for CREATE relationships:**
```python
# Instead of Cypher: CREATE (a)-[r:KNOWS]->(b)
# Use Python API:
from ipfs_datasets_py.knowledge_graphs.extraction import Relationship

rel = Relationship(
    source_entity=entity_a,
    target_entity=entity_b,
    relationship_type="KNOWS"
)
kg.add_relationship(rel)
```

### Extraction Features

#### ✅ Current Extraction Capabilities

| Feature | Status | Notes |
|---------|--------|-------|
| **NER-based extraction** | ✅ Available | Uses spaCy models |
| **Rule-based relationships** | ✅ Available | Pattern matching |
| **Wikipedia enrichment** | ✅ Available | Automatic entity enrichment |
| **Batch processing** | ✅ Available | Process multiple documents |
| **Validation** | ✅ Available | Wikidata cross-checking |

#### ⚠️ Future Extraction Enhancements

| Feature | Status | Planned For |
|---------|--------|-------------|
| **Neural relationship extraction** | Planned | v2.5.0 (Q3 2026) |
| **Dependency parsing extraction** | Planned | v2.5.0 (Q3 2026) |
| **Semantic Role Labeling (SRL)** | Planned | v3.0.0 (Q4 2026) |
| **Multi-hop graph traversal** | Planned | v2.5.0 (Q3 2026) |
| **LLM API integration** | Planned | v3.0.0 (Q4 2026) |

**Note:** Current extraction works well for most use cases. These enhancements are for specialized scenarios.

---

## Feature Support Matrix

### Query Features

| Feature | Version Added | Status | Performance |
|---------|---------------|--------|-------------|
| Cypher queries | 1.0.0 | ✅ Stable | <100ms |
| Hybrid search | 1.0.0 | ✅ Stable | <300ms |
| Budget management | 2.0.0 | ✅ Stable | Minimal overhead |
| GraphRAG queries | 2.0.0 | ✅ Beta | <500ms |
| Federated queries | - | 🔄 Planned | TBD |

### Storage Features

| Feature | Version Added | Status | Notes |
|---------|---------------|--------|-------|
| IPLD storage | 1.0.0 | ✅ Stable | Content-addressed |
| JSON serialization | 1.0.0 | ✅ Stable | Human-readable |
| Transaction support | 2.0.0 | ✅ Stable | ACID compliant |
| Versioning | 2.0.0 | ✅ Beta | Incremental updates |
| Distributed storage | - | 🔄 Planned | Phase 5 |

### Integration Features

| Feature | Version Added | Status | Compatibility |
|---------|---------------|--------|---------------|
| Neo4j API compatibility | 1.0.0 | ✅ Stable | Most operations |
| JSON-LD support | 2.0.0 | ✅ Stable | Full spec |
| Vector store integration | 2.0.0 | ✅ Stable | FAISS, Qdrant |
| SPARQL queries | - | 🔄 Planned | Future |

---

## Breaking Changes

### Version 2.0.0 (2026-02-17)

**Change 1: Consolidated extraction module structure**
- **Impact:** Import paths changed
- **Migration:** Update imports from `knowledge_graph_extraction` to `extraction`
- **Timeline:** Old imports supported until v3.0.0
- **Breaking:** Only import paths; API unchanged

**Change 2: Custom exception hierarchy**
- **Impact:** More specific exception types
- **Migration:** Catch specific exceptions (EntityExtractionError, QueryError, etc.)
- **Timeline:** Generic Exception catching still works but not recommended
- **Breaking:** No (backward compatible)

**Change 3: Budget management added**
- **Impact:** New required parameter for some advanced queries
- **Migration:** Use preset budgets: `budgets=budget_manager.create_preset_budgets('safe')`
- **Timeline:** Optional in 2.0.0, may become required in 3.0.0
- **Breaking:** No (defaults provided)

### Version 1.0.0 (2025-Q4)

**Change: Initial stable release**
- **Impact:** API stabilized
- **Migration:** N/A (first stable version)
- **Breaking:** N/A

---

## Compatibility Matrix

### Python Versions

| Version | Python 3.10 | Python 3.11 | Python 3.12+ | Recommended |
|---------|-------------|-------------|--------------|-------------|
| 2.0.0   | ⚠️ Limited  | ✅ Full     | ✅ Full      | 3.12+       |
| 1.0.0   | ✅ Full     | ✅ Full     | ✅ Full      | 3.11+       |

### Dependencies

| Dependency | Version | Required | Purpose |
|------------|---------|----------|---------|
| **Python** | 3.12+ | Yes | Core runtime |
| **spaCy** | 3.0+ | Recommended | Entity extraction |
| **IPFS** | Any | Optional | Distributed storage |
| **Neo4j** | 4.0+ | Optional | Graph database |
| **transformers** | 4.0+ | Optional | Advanced extraction |

### Environment Compatibility

| Environment | Status | Notes |
|-------------|--------|-------|
| **Linux** | ✅ Full | Primary development platform |
| **macOS** | ✅ Full | Fully supported |
| **Windows** | ⚠️ Limited | Some IPFS features may have issues |
| **Docker** | ✅ Full | Recommended for production |
| **Cloud (AWS/GCP/Azure)** | ✅ Full | Works with all major clouds |

---

## Neo4j to IPFS Migration

### Step-by-Step Migration Guide

**1. Export from Neo4j**

```python
from ipfs_datasets_py.knowledge_graphs.migration import Neo4jExporter

# Connect to Neo4j
exporter = Neo4jExporter(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password"
)

# Export to intermediate format
exporter.export_to_json("neo4j_export.json")
```

**2. Validate Schema Compatibility**

```python
from ipfs_datasets_py.knowledge_graphs.migration import SchemaChecker

checker = SchemaChecker()
is_compatible, issues = checker.check_compatibility("neo4j_export.json")

if not is_compatible:
    print("Schema issues found:")
    for issue in issues:
        print(f"  - {issue}")
```

**3. Import to IPFS**

```python
from ipfs_datasets_py.knowledge_graphs.migration import IPFSImporter

# Import to IPFS
importer = IPFSImporter(ipfs_client=ipfs_client)
cid = importer.import_from_json("neo4j_export.json")

print(f"Graph stored at CID: {cid}")
```

**4. Verify Data Integrity**

```python
from ipfs_datasets_py.knowledge_graphs.migration import IntegrityVerifier

verifier = IntegrityVerifier()
is_valid, errors = verifier.verify(
    source="neo4j_export.json",
    target_cid=cid
)

if is_valid:
    print("Migration successful!")
else:
    print("Integrity issues:")
    for error in errors:
        print(f"  - {error}")
```

### Migration Considerations

**Data Size:**
- Small graphs (<10K entities): Direct migration
- Medium graphs (10K-100K): Batch migration recommended
- Large graphs (>100K): Consider sharding strategy

**Downtime:**
- Zero-downtime migration possible with dual-write approach
- Write to both Neo4j and IPFS during transition
- Switch read traffic to IPFS after validation

**Performance:**
- IPFS reads: 20-100ms (comparable to Neo4j)
- IPFS writes: 50-200ms (slower than Neo4j)
- Consider caching layer for frequently accessed graphs

---

## Migration Checklist

### From 1.x to 2.0

**Phase 1: Preparation (1-2 hours)**
- [ ] Review [ARCHITECTURE.md](ARCHITECTURE.md) for design changes
- [ ] Check [API_REFERENCE.md](API_REFERENCE.md) for API changes
- [ ] Backup existing data and configurations

**Phase 2: Update Code (2-4 hours)**
- [ ] Update import paths to use `extraction` package
- [ ] Update exception handling to use specific exceptions
- [ ] Add budget management to advanced queries (optional)
- [ ] Update tests to reflect new import paths

**Phase 3: Dependency Updates (30 minutes)**
- [ ] Add spaCy to dependencies if not already included
  ```bash
  pip install "ipfs_datasets_py[knowledge_graphs]"
  python -m spacy download en_core_web_sm
  ```
- [ ] Update other dependencies to compatible versions

**Phase 4: Testing (2-4 hours)**
- [ ] Test all extraction workflows
- [ ] Test all query operations
- [ ] Test storage and retrieval
- [ ] Run integration tests
- [ ] Performance testing

**Phase 5: Deployment (1-2 hours)**
- [ ] Deploy to staging environment
- [ ] Validate staging deployment
- [ ] Deploy to production with rollback plan
- [ ] Monitor for errors or issues

**Total Time Estimate:** 6-12 hours

---

## Common Migration Issues

### Issue 1: ImportError after upgrade

**Error:**
```
ImportError: cannot import name 'KnowledgeGraphExtractor' from 'ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction'
```

**Solution:** Install knowledge graphs extras
```bash
pip install "ipfs_datasets_py[knowledge_graphs]"
python -m spacy download en_core_web_sm
```

### Issue 2: Deprecation warnings

**Warning:**
```
DeprecationWarning: Importing from 'knowledge_graph_extraction' is deprecated. Use 'extraction' package instead.
```

**Solution:** Update import paths
```python
# Before
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import Entity

# After
from ipfs_datasets_py.knowledge_graphs.extraction import Entity
```

### Issue 3: Exception handling changes

**Error:**
```
Catching generic Exception doesn't catch specific extraction errors
```

**Solution:** Use specific exception types
```python
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    ExtractionError,
    ValidationError,
    QueryError,
    StorageError
)

try:
    graph = extractor.extract_knowledge_graph(text)
except ExtractionError as e:
    # Handle extraction errors
    logger.error(f"Extraction failed: {e}")
except ValidationError as e:
    # Handle validation errors
    logger.error(f"Validation failed: {e}")
```

### Issue 4: Budget errors in queries

**Error:**
```
BudgetExceededError: Query exceeded timeout budget (1000ms)
```

**Solution:** Use more permissive budget
```python
from ipfs_datasets_py.knowledge_graphs.query import BudgetManager

budget_manager = BudgetManager()

# Try with moderate budget instead of strict
budgets = budget_manager.create_preset_budgets('moderate')
result = engine.execute_cypher(query, budgets=budgets)
```

### Issue 5: spaCy model not found

**Error:**
```
OSError: [E050] Can't find model 'en_core_web_sm'
```

**Solution:** Download spaCy model
```bash
python -m spacy download en_core_web_sm
```

### Issue 6: IPFS connection errors

**Error:**
```
ConnectionError: Failed to connect to IPFS daemon
```

**Solution:** Start IPFS daemon or use fallback storage
```bash
# Start IPFS daemon
ipfs daemon

# Or configure alternative storage
extractor = KnowledgeGraphExtractor(storage_backend='json')
```

---

## Deprecation Timeline

### Version 2.0.0 (2026-02-17) - Current

**Deprecated:**
- Old import paths (`knowledge_graph_extraction`)

**Still Supported:**
- Old imports work with deprecation warnings

### Version 2.5.0 (Planned Q3 2026)

**Changes:**
- Warning level increased for deprecated imports
- New features may not support old import paths

### Version 3.0.0 (Planned Q4 2026)

**Breaking:**
- Old import paths removed
- Must use new `extraction` package

**Migration Required By:** Q4 2026

---

## Getting Help

### Documentation

For migration assistance:
- [USER_GUIDE.md](USER_GUIDE.md) - Updated usage patterns and examples
- [API_REFERENCE.md](API_REFERENCE.md) - Complete API documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design and patterns
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development guidelines

### Support Channels

- **GitHub Issues:** Report bugs or migration problems
- **Documentation:** Check examples in USER_GUIDE.md
- **Tests:** Review test files for usage patterns

### Migration Support

If you encounter issues during migration:
1. Check this guide for known issues
2. Review test files for examples of correct usage
3. Consult USER_GUIDE.md for updated patterns
4. Open a GitHub issue with specific details

---

**Last Updated:** 2026-02-17  
**Version:** 2.0.0  
**Status:** Production-Ready
