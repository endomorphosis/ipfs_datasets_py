# Migration Tools Module

**Version:** 2.0.0  
**Package:** `ipfs_datasets_py.knowledge_graphs.migration`

---

## Overview

The Migration module provides tools for migrating knowledge graphs between different formats and storage systems. It supports importing from Neo4j, exporting to various formats, schema validation, and data integrity verification.

**Key Features:**
- Neo4j to IPFS migration
- Format conversion (CSV, JSON, Cypher dumps)
- Schema compatibility checking
- Data integrity verification
- Automated migration workflows

---

## Core Components

### Neo4j Exporter (`neo4j_exporter.py`)

Export knowledge graphs from Neo4j databases:

```python
from ipfs_datasets_py.knowledge_graphs.migration import Neo4jExporter

# Connect to Neo4j
exporter = Neo4jExporter(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password"
)

# Export to JSON
exporter.export_to_json("neo4j_export.json")

# Export to CSV (entities + relationships)
exporter.export_to_csv("entities.csv", "relationships.csv")

# Export Cypher dump
exporter.export_cypher_dump("neo4j_dump.cypher")
```

**Features:**
- Full graph export
- Filtered export by labels/types
- Incremental export (changed entities only)
- Large graph streaming export

### IPFS Importer (`ipfs_importer.py`)

Import knowledge graphs to IPFS storage:

```python
from ipfs_datasets_py.knowledge_graphs.migration import IPFSImporter

# Initialize with IPFS client
importer = IPFSImporter(ipfs_client=ipfs_client)

# Import from JSON
cid = importer.import_from_json("neo4j_export.json")
print(f"Graph stored at: {cid}")

# Import from CSV
cid = importer.import_from_csv("entities.csv", "relationships.csv")

# Retrieve imported graph
kg = importer.retrieve(cid)
```

**Features:**
- JSON/CSV/Cypher import
- IPLD-native storage
- Content-addressed retrieval
- Incremental imports

### Schema Checker (`schema_checker.py`)

Validate schema compatibility before migration:

```python
from ipfs_datasets_py.knowledge_graphs.migration import SchemaChecker

checker = SchemaChecker()

# Check compatibility
is_compatible, issues = checker.check_compatibility("neo4j_export.json")

if not is_compatible:
    print("Schema issues found:")
    for issue in issues:
        print(f"  - {issue}")
        
# Get schema summary
summary = checker.get_schema_summary("neo4j_export.json")
print(f"Entity types: {summary['entity_types']}")
print(f"Relationship types: {summary['relationship_types']}")
```

**Checks:**
- Entity type compatibility
- Relationship type compatibility
- Property name conflicts
- Type mismatches
- Missing required fields

### Integrity Verifier (`integrity_verifier.py`)

Verify data integrity after migration:

```python
from ipfs_datasets_py.knowledge_graphs.migration import IntegrityVerifier

verifier = IntegrityVerifier()

# Verify migration
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

# Detailed comparison
report = verifier.detailed_verification(
    source="neo4j_export.json",
    target_cid=cid
)
print(f"Entity match: {report['entities_match']:.1%}")
print(f"Relationship match: {report['relationships_match']:.1%}")
```

**Verification:**
- Entity count matching
- Relationship count matching
- Property preservation
- ID consistency
- Relationship connectivity

### Format Converter (`formats.py`)

Convert between different knowledge graph formats:

```python
from ipfs_datasets_py.knowledge_graphs.migration import FormatConverter

converter = FormatConverter()

# Convert JSON to CSV
converter.json_to_csv(
    input_file="graph.json",
    entities_output="entities.csv",
    relationships_output="relationships.csv"
)

# Convert CSV to JSON
converter.csv_to_json(
    entities_file="entities.csv",
    relationships_file="relationships.csv",
    output_file="graph.json"
)

# Convert to Cypher statements
converter.to_cypher(
    input_file="graph.json",
    output_file="graph.cypher"
)
```

**Supported Formats:**
- ✅ JSON (native KnowledgeGraph format)
- ✅ CSV (entities + relationships)
- ✅ Neo4j Cypher dumps
- ✅ IPLD/IPFS
- ⚠️ GraphML (not implemented - use CSV intermediate)
- ⚠️ GEXF (not implemented - use CSV intermediate)

---

## Usage Examples

### Example 1: Complete Neo4j to IPFS Migration

```python
from ipfs_datasets_py.knowledge_graphs.migration import (
    Neo4jExporter,
    SchemaChecker,
    IPFSImporter,
    IntegrityVerifier
)

# Step 1: Export from Neo4j
exporter = Neo4jExporter(
    uri="bolt://localhost:7687",
    user="neo4j",
    password="password"
)
exporter.export_to_json("neo4j_export.json")

# Step 2: Validate schema
checker = SchemaChecker()
is_compatible, issues = checker.check_compatibility("neo4j_export.json")
if not is_compatible:
    print(f"Schema issues: {issues}")
    # Fix issues before continuing

# Step 3: Import to IPFS
importer = IPFSImporter(ipfs_client=ipfs_client)
cid = importer.import_from_json("neo4j_export.json")
print(f"Graph stored at: {cid}")

# Step 4: Verify integrity
verifier = IntegrityVerifier()
is_valid, errors = verifier.verify(
    source="neo4j_export.json",
    target_cid=cid
)

if is_valid:
    print("✅ Migration successful!")
else:
    print(f"❌ Errors: {errors}")
```

### Example 2: Filtered Export

```python
# Export only specific entity types
exporter = Neo4jExporter(uri="bolt://localhost:7687", user="neo4j", password="pwd")

# Filter by labels
exporter.export_filtered(
    output_file="persons_and_orgs.json",
    labels=["Person", "Organization"]
)

# Filter by properties
exporter.export_filtered(
    output_file="high_confidence.json",
    property_filter={"confidence": {"$gte": 0.8}}
)
```

### Example 3: Large Graph Migration with Batching

```python
# Stream large graphs in batches
exporter = Neo4jExporter(uri="bolt://localhost:7687", user="neo4j", password="pwd")

batch_size = 1000
for batch_num, batch_data in exporter.stream_export(batch_size=batch_size):
    # Process each batch
    batch_file = f"batch_{batch_num}.json"
    json.dump(batch_data, open(batch_file, 'w'))
    
    # Import batch to IPFS
    cid = importer.import_from_json(batch_file)
    print(f"Batch {batch_num} stored at: {cid}")
```

### Example 4: Format Conversion

```python
from ipfs_datasets_py.knowledge_graphs.migration import FormatConverter

converter = FormatConverter()

# Neo4j dump to JSON
converter.cypher_to_json(
    input_file="neo4j_dump.cypher",
    output_file="graph.json"
)

# JSON to CSV for analysis
converter.json_to_csv(
    input_file="graph.json",
    entities_output="entities.csv",
    relationships_output="relationships.csv"
)

# CSV to IPFS
importer = IPFSImporter(ipfs_client)
cid = importer.import_from_csv("entities.csv", "relationships.csv")
```

### Example 5: Incremental Migration

```python
# Initial migration
exporter = Neo4jExporter(uri="bolt://localhost:7687", user="neo4j", password="pwd")
exporter.export_to_json("initial_export.json")
importer = IPFSImporter(ipfs_client)
initial_cid = importer.import_from_json("initial_export.json")

# Later: Export only changed entities
last_timestamp = "2026-02-17T00:00:00Z"
exporter.export_incremental(
    output_file="incremental_export.json",
    since=last_timestamp
)

# Merge with existing graph
kg_initial = importer.retrieve(initial_cid)
kg_incremental = importer.load_from_json("incremental_export.json")
kg_initial.merge(kg_incremental)

# Store updated graph
updated_cid = importer.store(kg_initial)
```

---

## Migration Considerations

### Data Size Planning

| Graph Size | Strategy | Expected Time |
|------------|----------|---------------|
| <10K entities | Direct migration | Minutes |
| 10K-100K | Batch migration | Hours |
| >100K | Streaming + sharding | Hours to days |

### Downtime Strategies

**Zero-Downtime Migration:**
1. Dual-write to both Neo4j and IPFS during transition
2. Switch read traffic gradually
3. Validate consistency
4. Decommission old system

**Planned Downtime:**
1. Stop writes to Neo4j
2. Export full graph
3. Import to IPFS
4. Validate integrity
5. Switch to IPFS

### Performance Tips

```python
# Use batch processing for large graphs
exporter.export_batched(
    output_dir="batches/",
    batch_size=1000
)

# Parallel import of batches
from concurrent.futures import ProcessPoolExecutor

with ProcessPoolExecutor(max_workers=4) as executor:
    futures = []
    for batch_file in glob.glob("batches/*.json"):
        future = executor.submit(importer.import_from_json, batch_file)
        futures.append(future)
    
    cids = [f.result() for f in futures]
```

---

## Error Handling

### Common Issues

**Issue 1: Neo4j Connection Failed**
```python
try:
    exporter = Neo4jExporter(uri="bolt://localhost:7687", user="neo4j", password="pwd")
except ConnectionError:
    print("Cannot connect to Neo4j. Is the daemon running?")
    # Retry or use fallback
```

**Issue 2: Schema Incompatibility**
```python
checker = SchemaChecker()
is_compatible, issues = checker.check_compatibility("export.json")

if not is_compatible:
    # Option 1: Fix manually
    for issue in issues:
        if issue['type'] == 'property_conflict':
            # Rename conflicting property
            pass
    
    # Option 2: Use migration config
    config = {
        "property_mappings": {
            "old_name": "new_name"
        }
    }
    converter.apply_config(config)
```

**Issue 3: Large File Handling**
```python
# Stream instead of loading entire file
for chunk in exporter.stream_export(chunk_size=1000):
    # Process chunk
    importer.import_chunk(chunk)
```

---

## Testing

Run migration tests:

```bash
# Unit tests
pytest tests/unit/knowledge_graphs/test_migration*.py -v

# Integration tests (requires Neo4j)
pytest tests/integration/test_neo4j_migration.py -v --neo4j-available
```

---

## Known Limitations

### Unsupported Formats

**GraphML, GEXF, Pajek** - Not implemented

**Workaround:**
```python
# Export to CSV first
converter.json_to_csv("graph.json", "entities.csv", "rels.csv")

# Convert to target format using external tools
import networkx as nx
G = nx.read_edgelist("rels.csv")
nx.write_graphml(G, "graph.graphml")
```

See [MIGRATION_GUIDE.md](/docs/knowledge_graphs/MIGRATION_GUIDE.md#migration-format-support) for details.

---

## See Also

- [USER_GUIDE.md](/docs/knowledge_graphs/USER_GUIDE.md) - Usage patterns
- [MIGRATION_GUIDE.md](/docs/knowledge_graphs/MIGRATION_GUIDE.md#neo4j-to-ipfs-migration) - Complete migration guide
- [API_REFERENCE.md](/docs/knowledge_graphs/API_REFERENCE.md) - API documentation

---

**Last Updated:** 2026-02-17  
**Status:** Production-Ready  
**Test Coverage:** ~40% (improvements planned)
