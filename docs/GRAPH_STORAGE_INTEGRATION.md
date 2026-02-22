# Graph Storage Integration Guide

**Version:** 1.0.0  
**Last Updated:** 2025-02-20  
**Status:** Production-Ready  

---

## Overview

This guide covers integrating external graph storage systems with ipfs_datasets_py knowledge graphs. The library provides native support for IPFS-based storage with compatibility layers and export capabilities for popular graph database systems.

**Key Features:**
- Neo4j compatibility layer for familiar driver patterns
- RDF/Turtle export for semantic web integration
- GraphML export for visualization tools (Gephi, yEd)
- IPFS-native storage with content addressing
- Migration tools for Neo4j-to-IPFS workflows

**Target Audience:** Developers integrating knowledge graphs with external databases, graph visualization tools, or semantic web applications.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   Knowledge Graph Core                       │
│          (ipfs_datasets_py.knowledge_graphs.core)           │
└────────────────────┬────────────────────────────────────────┘
                     │
      ┌──────────────┼──────────────┐
      │              │              │
      ▼              ▼              ▼
┌──────────┐  ┌──────────┐  ┌──────────────┐
│   IPFS   │  │  Neo4j   │  │  RDF/GraphML │
│ Storage  │  │  Compat  │  │   Exports    │
│ (native) │  │  Layer   │  │  (portabil.) │
└──────────┘  └──────────┘  └──────────────┘
```

---

## 1. Native IPFS Storage

### Basic Storage Operations

```python
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine, KnowledgeGraph

# Initialize engine with IPFS backend
engine = GraphEngine()

# Create and store nodes
alice = engine.create_node(
    labels=["Person"],
    properties={"name": "Alice", "age": 30}
)
bob = engine.create_node(
    labels=["Person"],
    properties={"name": "Bob", "age": 25}
)

# Create relationship
rel = engine.create_relationship(
    rel_type="KNOWS",
    start_node_id=alice.id,
    end_node_id=bob.id,
    properties={"since": 2020}
)

# Query stored nodes
persons = engine.find_nodes(labels=["Person"])
print(f"Found {len(persons)} person nodes")
```

### Content-Addressed Storage

IPFS provides content-addressed storage - each knowledge graph state has a unique CID:

```python
# Store knowledge graph
cid = engine.store()
print(f"Graph stored at: {cid}")

# Retrieve by CID
retrieved_graph = engine.retrieve(cid)

# Storage is immutable - updates create new CIDs
engine.create_node(labels=["Organization"], properties={"name": "Acme Corp"})
new_cid = engine.store()
print(f"Updated graph: {new_cid}")
```

**Benefits:**
- Immutable versioning (every change creates new CID)
- Deduplication (identical subgraphs share storage)
- Content verification (CID proves data integrity)
- Distributed replication (automatic IPFS network distribution)

---

## 2. Neo4j Compatibility Layer

### Driver Pattern

Familiar Neo4j driver API for easy migration:

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

# Initialize with IPFS URI instead of bolt://
driver = GraphDatabase.driver("ipfs://localhost:5001")

# Use standard Neo4j patterns
with driver.session() as session:
    # Create nodes
    result = session.run(
        "CREATE (p:Person {name: $name, age: $age}) RETURN p",
        name="Alice",
        age=30
    )
    
    # Query
    persons = session.run(
        "MATCH (p:Person) WHERE p.age > $min_age RETURN p",
        min_age=25
    )
    
    for record in persons:
        print(record["p"]["name"])

driver.close()
```

### Migration from Neo4j

For teams transitioning from Neo4j to IPFS:

```python
from ipfs_datasets_py.knowledge_graphs.migration import Neo4jExporter

# Step 1: Export from Neo4j
exporter = Neo4jExporter(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password"
)
exporter.export_to_json("neo4j_export.json")

# Step 2: Import to IPFS
from ipfs_datasets_py.knowledge_graphs.migration import IPFSImporter

importer = IPFSImporter(ipfs_client=ipfs_client)
cid = importer.import_from_json("neo4j_export.json")
print(f"Graph migrated to IPFS: {cid}")

# Step 3: Verify integrity
from ipfs_datasets_py.knowledge_graphs.migration import IntegrityVerifier

verifier = IntegrityVerifier()
is_valid, errors = verifier.verify(
    source="neo4j_export.json",
    target_cid=cid
)
assert is_valid, f"Migration errors: {errors}"
```

**See Also:** [migration/README.md](../ipfs_datasets_py/knowledge_graphs/migration/README.md) for comprehensive migration guide.

---

## 3. RDF/Semantic Web Integration

### Export to RDF (Turtle, N-Triples)

Export knowledge graphs to RDF for semantic web applications:

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyOptimizer

# Create optimizer with ontology
optimizer = OntologyOptimizer()
ontology = {
    "entities": [
        {"id": "e1", "text": "Alice Smith", "type": "Person"},
        {"id": "e2", "text": "Acme Corp", "type": "Organization"}
    ],
    "relationships": [
        {"source_id": "e1", "target_id": "e2", "type": "worksAt"}
    ]
}

# Export as Turtle (default)
rdf_turtle = optimizer.export_to_rdf(ontology=ontology, format="turtle")
print(rdf_turtle)
# Output:
# @prefix ont: <urn:optimizers:ontology:> .
# ont:e1 a ont:Entity ;
#     rdfs:label "Alice Smith" ;
#     ont:entityType "Person" .
# ont:e1 ont:worksAt ont:e2 .

# Export as N-Triples
rdf_nt = optimizer.export_to_rdf(ontology=ontology, format="nt")

# Write to file
optimizer.export_to_rdf(
    ontology=ontology,
    filepath="knowledge_graph.ttl",
    format="turtle"
)
```

**Supported RDF Formats:**
- `turtle` - Terse RDF Triple Language (default)
- `nt` - N-Triples (plain triples)
- `n3` - Notation3
- Other formats supported by `rdflib`

**Requirements:** Install `rdflib` with `pip install rdflib`

### SPARQL Query Integration

Use exported RDF with SPARQL endpoints:

```python
from rdflib import Graph
import requests

# Export to Turtle
rdf_data = optimizer.export_to_rdf(ontology, format="turtle")

# Load into rdflib Graph
g = Graph()
g.parse(data=rdf_data, format="turtle")

# Query with SPARQL
query = """
PREFIX ont: <urn:optimizers:ontology:>
SELECT ?entity ?label
WHERE {
    ?entity ont:entityType "Person" ;
            rdfs:label ?label .
}
"""
results = g.query(query)
for row in results:
    print(f"Person: {row.label}")

# Or upload to SPARQL endpoint
# response = requests.post(
#     "http://localhost:3030/dataset/upload",
#     data={"graph": rdf_data}
# )
```

---

## 4. Graph Visualization Integration

### Export to GraphML

Export for visualization tools (Gephi, yEd, Cytoscape):

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyOptimizer

optimizer = OntologyOptimizer()
ontology = {
    "entities": [
        {"id": "e1", "text": "Alice", "type": "Person"},
        {"id": "e2", "text": "Bob", "type": "Person"},
        {"id": "e3", "text": "Acme Corp", "type": "Organization"}
    ],
    "relationships": [
        {"source_id": "e1", "target_id": "e2", "type": "knows"},
        {"source_id": "e1", "target_id": "e3", "type": "worksAt"},
        {"source_id": "e2", "target_id": "e3", "type": "worksAt"}
    ]
}

# Export to GraphML XML
graphml = optimizer.export_to_graphml(ontology=ontology)

# Save for Gephi/yEd
optimizer.export_to_graphml(
    ontology=ontology,
    filepath="knowledge_graph.graphml"
)
```

**GraphML Structure:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="label" for="node" attr.name="label" attr.type="string"/>
  <key id="etype" for="node" attr.name="entityType" attr.type="string"/>
  <key id="rtype" for="edge" attr.name="relationshipType" attr.type="string"/>
  <graph id="G" edgedefault="directed">
    <node id="e1">
      <data key="label">Alice</data>
      <data key="etype">Person</data>
    </node>
    <edge id="e0" source="e1" target="e2">
      <data key="rtype">knows</data>
    </edge>
  </graph>
</graphml>
```

### Visualization Workflows

**Gephi (Network Analysis):**
```bash
# Open Gephi
gephi &

# File > Open > knowledge_graph.graphml
# Use layout algorithms: ForceAtlas2, Fruchterman-Reingold
# Apply node sizing by degree
# Export publication-ready SVG/PNG
```

**yEd (Diagram Editor):**
```bash
# Open yEd
yed knowledge_graph.graphml

# Layout > Hierarchical / Organic
# Tools > Fit Node to Label
# Export to PDF/PNG
```

**Cytoscape (Biological Networks):**
```bash
cytoscape -N knowledge_graph.graphml
# Apply styles, analyze network properties
```

### NetworkX Integration

Convert to NetworkX for programmatic analysis:

```python
import networkx as nx
import xml.etree.ElementTree as ET

# Load from GraphML string
graphml_data = optimizer.export_to_graphml(ontology)
G = nx.parse_graphml(graphml_data)

# OR load from file
G = nx.read_graphml("knowledge_graph.graphml")

# Analyze
print(f"Nodes: {G.number_of_nodes()}")
print(f"Edges: {G.number_of_edges()}")
print(f"Avg degree: {sum(dict(G.degree()).values()) / G.number_of_nodes():.2f}")

# Community detection
import networkx.algorithms.community as nx_comm
communities = nx_comm.greedy_modularity_communities(G.to_undirected())
print(f"Detected {len(communities)} communities")

# Shortest paths
path = nx.shortest_path(G, source='e1', target='e3')
print(f"Path: {' -> '.join(path)}")
```

---

## 5. Advanced Storage Patterns

### Batch Operations with Transactions

```python
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionContext

engine = GraphEngine()

# Batch create with transaction
with TransactionContext(engine) as tx:
    # Create 1000 nodes in single transaction
    for i in range(1000):
        tx.create_node(
            labels=["DataPoint"],
            properties={"index": i, "value": i * 2}
        )
    # Commit atomically (or rollback on exception)
```

### Cross-Document Lineage Tracking

Track entity provenance across documents:

```python
from ipfs_datasets_py.knowledge_graphs import CrossDocumentLineage

lineage = CrossDocumentLineage()

# Track entity across multiple documents
lineage.track_entity(
    entity_id="e1",
    document_id="doc_2024_q1",
    extraction_metadata={
        "confidence": 0.95,
        "source_span": (45, 67)
    }
)

lineage.track_entity(
    entity_id="e1",
    document_id="doc_2024_q2",
    extraction_metadata={
        "confidence": 0.92,
        "source_span": (102, 125)
    }
)

# Query lineage
history = lineage.get_entity_history("e1")
print(f"Entity appears in {len(history)} documents")
for doc_id, metadata in history.items():
    print(f"  {doc_id}: confidence={metadata['confidence']}")
```

### Sharding Large Graphs

For graphs exceeding memory:

```python
from ipfs_datasets_py.knowledge_graphs.storage import GraphSharder

sharder = GraphSharder(shard_size=10000)  # 10K entities per shard

# Shard large graph
graph = KnowledgeGraph.from_json("large_graph.json")
shards = sharder.shard_graph(graph)

# Store shards independently
cids = []
for shard_id, shard_graph in shards.items():
    cid = engine.store(shard_graph)
    cids.append((shard_id, cid))
    print(f"Shard {shard_id} stored at {cid}")

# Query across shards
results = []
for shard_id, cid in cids:
    shard_graph = engine.retrieve(cid)
    matches = shard_graph.find_entities({"type": "Person"})
    results.extend(matches)
```

---

## 6. Configuration & Best Practices

### Storage Configuration

```python
# Configure IPFS client
import ipfshttpclient

ipfs_client = ipfshttpclient.connect(
    addr='/ip4/127.0.0.1/tcp/5001',
    timeout=300  # 5 min timeout for large graphs
)

# Configure GraphEngine
engine = GraphEngine(
    ipfs_client=ipfs_client,
    cache_size=1000,  # LRU cache for frequent queries
    compression=True  # Compress before IPFS storage
)
```

### Export Format Selection

| Format | Use Case | Tool Compatibility | File Size |
|--------|----------|-------------------|-----------|
| **IPFS (native)** | Production storage, versioning | ipfs_datasets_py | Optimal (deduplicated) |
| **Neo4j Compat** | Migration from Neo4j | Neo4j drivers | N/A (API) |
| **RDF/Turtle** | Semantic web, SPARQL queries | rdflib, Stardog, GraphDB | Medium |
| **GraphML** | Visualization, network analysis | Gephi, yEd, NetworkX | Large (XML) |
| **JSON** | Interchange, debugging | Universal | Medium |
| **CSV** | Data analysis, Excel | Pandas, R, Excel | Small |

### Performance Optimization

**Large Graph Export:**
```python
# Use streaming for graphs >100K entities
from ipfs_datasets_py.knowledge_graphs.migration import Neo4jExporter

exporter = Neo4jExporter(uri="bolt://localhost:7687", user="neo4j", password="pwd")

# Stream in batches
for batch_num, batch_ontology in exporter.stream_export(batch_size=5000):
    # Process each batch
    graphml = optimizer.export_to_graphml(ontology=batch_ontology)
    with open(f"batch_{batch_num}.graphml", "w") as f:
        f.write(graphml)
```

**Parallel Processing:**
```python
from concurrent.futures import ThreadPoolExecutor

def export_shard(shard_data):
    return optimizer.export_to_rdf(ontology=shard_data, format="turtle")

with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(export_shard, shard) for shard in shards]
    rdf_exports = [f.result() for f in futures]
```

---

## 7. Troubleshooting

### Common Issues

**Issue 1: `ImportError: No module named 'rdflib'`**

```bash
# Install RDF dependencies
pip install rdflib
```

**Issue 2: Neo4j Connection Timeout**

```python
# Increase timeout for large exports
exporter = Neo4jExporter(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password",
    connection_timeout=300  # 5 minutes
)
```

**Issue 3: GraphML Rendering Issues in Gephi**

```python
# Ensure all IDs are strings (Gephi requirement)
ontology = {
    "entities": [
        {"id": str(ent["id"]), "text": ent["text"], "type": ent["type"]}
        for ent in raw_entities
    ],
    "relationships": [
        {
            "source_id": str(rel["source_id"]),
            "target_id": str(rel["target_id"]),
            "type": rel["type"]
        }
        for rel in raw_relationships
    ]
}
```

**Issue 4: IPFS Storage Full**

```bash
# Garbage collect unused CIDs
ipfs repo gc

# Or increase storage limit
ipfs config Datastore.StorageMax 100GB
```

---

## 8. Examples

### Example 1: Academic Citation Network

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyOptimizer

# Build citation ontology
ontology = {
    "entities": [
        {"id": "p1", "text": "Graph Neural Networks", "type": "Paper"},
        {"id": "p2", "text": "Semi-Supervised Learning", "type": "Paper"},
        {"id": "a1", "text": "Kipf, T.", "type": "Author"}
    ],
    "relationships": [
        {"source_id": "p1", "target_id": "p2", "type": "cites"},
        {"source_id": "a1", "target_id": "p1", "type": "authored"}
    ]
}

optimizer = OntologyOptimizer()

# Export for visualization
optimizer.export_to_graphml(ontology, filepath="citations.graphml")

# Export for semantic queries
optimizer.export_to_rdf(ontology, filepath="citations.ttl", format="turtle")

# Query with SPARQL
from rdflib import Graph

g = Graph()
g.parse("citations.ttl", format="turtle")

query = """
PREFIX ont: <urn:optimizers:ontology:>
SELECT ?author ?paper
WHERE {
    ?author ont:authored ?paper .
    ?paper ont:entityType "Paper" .
}
"""
for row in g.query(query):
    print(f"{row.author} authored {row.paper}")
```

### Example 2: Legal Knowledge Base

```python
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine

# Build legal knowledge graph
engine = GraphEngine()

# Create entities
case1 = engine.create_node(
    labels=["Case"],
    properties={
        "name": "Roe v. Wade",
        "year": 1973,
        "citation": "410 U.S. 113"
    }
)

statute1 = engine.create_node(
    labels=["Statute"],
    properties={
        "name": "14th Amendment",
        "section": "Due Process Clause"
    }
)

# Create citations
engine.create_relationship("CITES", case1.id, statute1.id)

# Store to IPFS
cid = engine.store()
print(f"Legal KB stored at: {cid}")

# Export for external tools
from ipfs_datasets_py.optimizers.graphrag import OntologyOptimizer

# Convert to ontology format
kg_data = engine.to_dict()
ontology = {
    "entities": kg_data["nodes"],
    "relationships": kg_data["edges"]
}

# Export to GraphML for visualization
optimizer = OntologyOptimizer()
optimizer.export_to_graphml(ontology, filepath="legal_kb.graphml")
```

### Example 3: Multi-Format Pipeline

```python
# Unified export pipeline
from ipfs_datasets_py.optimizers.graphrag import OntologyOptimizer
from ipfs_datasets_py.knowledge_graphs.migration import FormatConverter

optimizer = OntologyOptimizer()
converter = FormatConverter()

# 1. Export ontology from optimizer
ontology = {
    "entities": [...],
    "relationships": [...]
}

# 2. Export to all formats
formats = {
    "rdf": optimizer.export_to_rdf(ontology, format="turtle"),
    "graphml": optimizer.export_to_graphml(ontology),
    "json": converter.to_json(ontology)
}

# 3. Save to disk
import json
for fmt, data in formats.items():
    with open(f"knowledge_graph.{fmt}", "w") as f:
        f.write(data)

print("Exported to RDF, GraphML, and JSON")
```

---

## 9. API Reference

### Core Classes

**GraphEngine** - [core.py](../ipfs_datasets_py/knowledge_graphs/core/README.md)
- `create_node(labels, properties) -> Node`
- `create_relationship(type, start_id, end_id, properties) -> Relationship`
- `find_nodes(labels=None, properties=None) -> List[Node]`
- `store() -> CID`
- `retrieve(cid) -> KnowledgeGraph`

**OntologyOptimizer** - [optimizers/graphrag/ontology_optimizer.py](../ipfs_datasets_py/optimizers/graphrag/README.md)
- `export_to_rdf(ontology, filepath=None, format="turtle") -> Optional[str]`
- `export_to_graphml(ontology, filepath=None) -> Optional[str]`

**Neo4jExporter** - [migration/neo4j_exporter.py](../ipfs_datasets_py/knowledge_graphs/migration/README.md)
- `export_to_json(output_file) -> None`
- `export_to_csv(entities_file, relationships_file) -> None`
- `stream_export(batch_size) -> Iterator[Tuple[int, Dict]]`

**IPFSImporter** - [migration/ipfs_importer.py](../ipfs_datasets_py/knowledge_graphs/migration/README.md)
- `import_from_json(filepath) -> CID`
- `import_from_csv(entities_file, relationships_file) -> CID`
- `retrieve(cid) -> KnowledgeGraph`

---

## 10. See Also

- **[migration/README.md](../ipfs_datasets_py/knowledge_graphs/migration/README.md)** - Comprehensive Neo4j migration guide
- **[USER_GUIDE.md](../ipfs_datasets_py/knowledge_graphs/USER_GUIDE.md)** - Knowledge graph usage patterns
- **[QUICKSTART.md](../ipfs_datasets_py/knowledge_graphs/QUICKSTART.md)** - Quick start examples
- **[complaint_phases/README.md](../complaint_phases/README.md)** - Legal knowledge graph workflows
- **[examples/knowledge_graphs/simple_example.py](../ipfs_datasets_py/examples/knowledge_graphs/simple_example.py)** - Complete working example

---

## 11. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-02-20 | Initial release covering IPFS, Neo4j, RDF, GraphML |

---

**Contributors:** Documentation team  
**Feedback:** [GitHub Issues](https://github.com/your-repo/issues) or PRs welcome  
**License:** Same as ipfs_datasets_py project
