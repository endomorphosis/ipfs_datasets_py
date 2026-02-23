# Knowledge Graphs - Quick Start Guide

**Get started with the Knowledge Graphs module in 5 minutes!**

---

## Installation (30 seconds)

```bash
# Install the package
pip install ipfs-datasets-py

# Optional: Install additional features
pip install ipfs-datasets-py[knowledge_graphs]
```

---

## Basic Example (2 minutes)

### Extract Knowledge from Text

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

# Create extractor
extractor = KnowledgeGraphExtractor()

# Extract knowledge graph from text
text = """
Marie Curie was a physicist who won the Nobel Prize in 1903.
She worked at the University of Paris and collaborated with Pierre Curie.
Albert Einstein admired her work on radioactivity.
"""

kg = extractor.extract_knowledge_graph(text)

# See what was extracted
print(f"Found {len(kg.entities)} entities:")
for entity in kg.entities:
    print(f"  - {entity.name} ({entity.entity_type})")

print(f"\nFound {len(kg.relationships)} relationships:")
for rel in kg.relationships.values():
    src = rel.source_entity.name if rel.source_entity else rel.source_id
    tgt = rel.target_entity.name if rel.target_entity else rel.target_id
    print(f"  - {src} --[{rel.relationship_type}]--> {tgt}")
```

**Expected Output:**
```
Found 4 entities:
  - Marie Curie (PERSON)
  - University of Paris (ORGANIZATION)
  - Pierre Curie (PERSON)
  - Albert Einstein (PERSON)

Found 3 relationships:
  - Marie Curie --[WORKED_AT]--> University of Paris
  - Marie Curie --[COLLABORATED_WITH]--> Pierre Curie
  - Albert Einstein --[ADMIRED]--> Marie Curie
```

---

## Query Example (2 minutes)

### Query the Knowledge Graph

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine

# Set up an in-memory store and populate it from the extracted KG
store = GraphEngine()
for entity in kg.entities.values():
    store.create_node(entity.entity_type, entity.name, properties=entity.properties or {})

engine = UnifiedQueryEngine(backend=store)

# Query using Cypher
result = engine.execute_cypher("""
    MATCH (p:Person)-[r:WORKED_AT]->(o:Organization)
    WHERE p.name = 'Marie Curie'
    RETURN p.name, o.name
""")

print("Query results:")
for row in result.items:
    print(f"  {row['p.name']} worked at {row['o.name']}")
```

**Expected Output:**
```
Query results:
  Marie Curie worked at University of Paris
```

---

## Store in IPFS (Optional - 1 minute)

```python
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

# Store knowledge graph in IPFS
backend = IPLDBackend()
cid = backend.store(kg.to_dict())

print(f"Knowledge graph stored with CID: {cid}")

# Retrieve later (returns raw dict)
data = backend.retrieve_json(cid)
print(f"Retrieved graph with {len(data.get('entities', {}))} entities")
```

---

## Where to Go Next

### Learn More
- **[README.md](README.md)** - Full module overview and capabilities
- **[User Guide](../../docs/knowledge_graphs/USER_GUIDE.md)** - 40+ examples covering all features
- **[API Reference](../../docs/knowledge_graphs/API_REFERENCE.md)** - Complete API documentation

### Common Tasks
- **Extract from documents:** See [extraction/README.md](extraction/README.md)
- **Query graphs:** See [query/README.md](query/README.md)  
- **Migrate from Neo4j:** See [MIGRATION_GUIDE.md](../../docs/knowledge_graphs/MIGRATION_GUIDE.md)
- **Store in IPFS:** See [storage/README.md](storage/README.md)

### Advanced Features
- **Cross-document reasoning:** [lineage/README.md](lineage/README.md)
- **Transactions:** [transactions/README.md](transactions/README.md)
- **Neo4j compatibility:** [neo4j_compat/README.md](neo4j_compat/README.md)
- **JSON-LD support:** [jsonld/README.md](jsonld/README.md)

---

## Common Patterns

### Pattern 1: Extract and Validate
```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractorWithValidation
)

validator = KnowledgeGraphExtractorWithValidation(validate_during_extraction=True)
result = validator.extract_knowledge_graph(text, validation_depth=2)

kg = result["knowledge_graph"]
metrics = result["validation_metrics"]
print(f"Validation coverage: {metrics['overall_coverage']:.2%}")
```

### Pattern 2: Neo4j-compatible API
```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

driver = GraphDatabase.driver("ipfs://localhost:5001")
with driver.session() as session:
    result = session.run("""
        MATCH (n:Person)
        WHERE n.age > 30
        RETURN n.name, n.age
        LIMIT 10
    """)
    
    for record in result:
        print(f"{record['n.name']}: {record['n.age']}")

driver.close()
```

### Pattern 3: Hybrid Search
```python
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine

searcher = HybridSearchEngine(backend=backend)
results = searcher.search(
    query="physicist who won Nobel Prize",
    k=5,
    vector_weight=0.4,  # Weight for vector similarity
    graph_weight=0.6,   # Weight for graph relevance
)

for result in results:
    print(f"  - {result.node_id} (score: {result.score:.3f})")
```

---

## Tips

### Performance
- Use caching for frequently-accessed graphs
- Enable indexing for large graphs (>1000 nodes)
- Consider batch operations for bulk inserts

### Best Practices
- Validate extracted graphs with `KnowledgeGraphExtractorWithValidation`
- Use transactions for multi-step operations
- Store graphs in IPFS for immutability and versioning

### Troubleshooting
- **Import errors:** Check that optional dependencies are installed
- **Slow extraction:** Disable Wikipedia enrichment for faster processing
- **Memory issues:** Use streaming for large document processing

---

## Need Help?

- **Documentation:** [INDEX.md](INDEX.md) - Complete documentation index
- **Examples:** [USER_GUIDE.md](../../docs/knowledge_graphs/USER_GUIDE.md) - 40+ examples
- **Issues:** [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Status:** [MASTER_STATUS.md](./MASTER_STATUS.md) - Current capabilities

---

**Ready to build knowledge graphs!** 🚀

Start with the examples above, then explore the [User Guide](../../docs/knowledge_graphs/USER_GUIDE.md) for more advanced features.
