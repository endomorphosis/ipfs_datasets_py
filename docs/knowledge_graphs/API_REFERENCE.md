# Knowledge Graphs - API Reference

**Version:** 2.0.0  
**Last Updated:** 2026-02-17

---

## Table of Contents

1. [Extraction API](#extraction-api)
2. [Query API](#query-api)
3. [Storage API](#storage-api)
4. [Transaction API](#transaction-api)
5. [Cypher Language Reference](#cypher-language-reference)
6. [Utility APIs](#utility-apis)
7. [Compatibility APIs](#compatibility-apis)

---

## Extraction API

### Entity Class

Represents an entity in the knowledge graph.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import Entity

entity = Entity(
    entity_id: str = None,           # Auto-generated if not provided
    entity_type: str = "entity",     # Classification
    name: str = "",                  # Primary identifier
    properties: Dict[str, Any] = {}, # Additional metadata
    confidence: float = 1.0,         # Extraction confidence (0.0-1.0)
    source_text: str = None          # Source text reference
)
```

**Attributes:**
- `entity_id` (str): Unique identifier (auto-generated if not provided)
- `entity_type` (str): Entity classification (person, organization, location, technology, event, concept)
- `name` (str): Primary entity name
- `properties` (Dict[str, Any]): Additional metadata (e.g., birth_year, nationality, field)
- `confidence` (float): Extraction confidence score (0.0-1.0)
- `source_text` (str, optional): Reference to source text

**Methods:**
```python
# Serialization
entity.to_dict() -> Dict[str, Any]

# Deserialization
Entity.from_dict(data: Dict) -> Entity  # classmethod
```

**Example:**
```python
person = Entity(
    entity_type="person",
    name="Marie Curie",
    properties={"birth_year": "1867", "nationality": "Polish"},
    confidence=0.95
)
```

---

### Relationship Class

Represents a relationship between two entities.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import Relationship

relationship = Relationship(
    source_entity: Entity,           # Source entity
    target_entity: Entity,           # Target entity
    relationship_type: str,          # Semantic connection
    properties: Dict[str, Any] = {}, # Additional context
    relationship_id: str = None,     # Auto-generated
    confidence: float = 1.0,         # Relationship confidence
    source_text: str = None,         # Source text reference
    bidirectional: bool = False      # Whether relationship is bidirectional
)
```

**Attributes:**
- `source_entity` (Entity): Source entity
- `target_entity` (Entity): Target entity
- `relationship_type` (str): Type of relationship (WORKS_AT, CREATED, WON, etc.)
- `properties` (Dict[str, Any]): Additional context (e.g., year, shared_with)
- `relationship_id` (str): Unique identifier (auto-generated)
- `confidence` (float): Relationship confidence (0.0-1.0)
- `source_text` (str, optional): Reference to source text
- `bidirectional` (bool): Whether relationship is bidirectional

**Methods:**
```python
# Serialization
relationship.to_dict() -> Dict[str, Any]

# Deserialization
Relationship.from_dict(data: Dict) -> Relationship  # classmethod
```

**Example:**
```python
rel = Relationship(
    source_entity=marie_curie,
    target_entity=nobel_prize,
    relationship_type="WON",
    properties={"year": "1903"},
    confidence=0.92
)
```

---

### KnowledgeGraph Class

Container for entities and relationships.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph

kg = KnowledgeGraph(name: str = "knowledge_graph")
```

**Attributes:**
- `entities` (Dict[str, Entity]): Dictionary of entities (keyed by entity_id)
- `relationships` (Dict[str, Relationship]): Dictionary of relationships (keyed by relationship_id)
- `name` (str): Graph name

**Core Methods:**
```python
# Add entities and relationships
kg.add_entity(entity: Entity) -> Entity
kg.add_relationship(relationship: Relationship) -> Relationship

# Query by ID
kg.get_entity_by_id(entity_id: str) -> Optional[Entity]

# Query by type
kg.get_entities_by_type(entity_type: str) -> List[Entity]

# Query by name
kg.get_entities_by_name(name: str) -> List[Entity]

# Query relationships
kg.get_relationships_by_entity(entity: Entity) -> List[Relationship]

# Graph traversal
kg.find_path(
    source_id: str,
    target_id: str,
    max_depth: int = 5
) -> Optional[List[str]]  # Returns list of entity IDs forming path

# Merge graphs (with deduplication)
kg.merge(other: KnowledgeGraph)
```

**Serialization Methods:**
```python
# Dictionary serialization
kg.to_dict() -> Dict[str, Any]
KnowledgeGraph.from_dict(data: Dict) -> KnowledgeGraph  # classmethod

# JSON serialization
kg.to_json() -> str
KnowledgeGraph.from_json(json_str: str) -> KnowledgeGraph  # classmethod

# RDF export
kg.export_to_rdf() -> str
```

**Example:**
```python
kg = KnowledgeGraph(name="scientists_graph")
kg.add_entity(person)
kg.add_relationship(relationship)

persons = kg.get_entities_by_type("person")
path = kg.find_path(entity1_id, entity2_id, max_depth=5)
```

---

### KnowledgeGraphExtractor Class

Main class for extracting knowledge graphs from text.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor(
    use_spacy: bool = False,             # Use spaCy for NER
    use_transformers: bool = False,      # Use transformer models
    relation_patterns: Optional[List[Dict]] = None,  # Custom relation patterns
    min_confidence: float = 0.5,         # Minimum confidence threshold
    use_tracer: bool = True              # Enable tracing
)
```

**Basic Extraction Methods:**
```python
# Extract entities only
extractor.extract_entities(text: str) -> List[Entity]

# Extract relationships only
extractor.extract_relationships(
    text: str,
    entities: List[Entity]
) -> List[Relationship]

# Extract complete knowledge graph
extractor.extract_knowledge_graph(
    text: str,
    extraction_temperature: float = 0.7,  # 0.1-1.0 (detail level)
    structure_temperature: float = 0.5    # 0.1-1.0 (structure complexity)
) -> KnowledgeGraph
```

**Advanced Extraction Methods:**
```python
# Extract with automatic chunking (for large documents)
extractor.extract_enhanced_knowledge_graph(
    text: str,
    use_chunking: bool = True,
    extraction_temperature: float = 0.7,
    structure_temperature: float = 0.5
) -> KnowledgeGraph

# Extract from multiple documents
extractor.extract_from_documents(
    documents: List[Dict],               # List of document dictionaries
    text_key: str = "text",             # Key containing text
    extraction_temperature: float = 0.7,
    structure_temperature: float = 0.5
) -> KnowledgeGraph

# Extract from Wikipedia
extractor.extract_from_wikipedia(
    page_title: str,
    extraction_temperature: float = 0.7,
    structure_temperature: float = 0.5
) -> KnowledgeGraph
# Raises: ValueError (page not found), RuntimeError (extraction failed)
```

**Validation Methods:**
```python
# Validate against Wikidata
extractor.validate_against_wikidata(
    kg: KnowledgeGraph,
    entity_name: str
) -> Dict[str, Any]
# Returns: {"coverage": float, "matches": List, "mismatches": List}

# Enrich with type information
KnowledgeGraphExtractor.enrich_with_types(
    kg: KnowledgeGraph
) -> KnowledgeGraph  # staticmethod
```

**Temperature Parameters:**

| Temperature | Range | Description | Use Case |
|-------------|-------|-------------|----------|
| Extraction | 0.1-0.3 | Conservative | Legal, factual documents |
| Extraction | 0.4-0.7 | Balanced | General content |
| Extraction | 0.8-1.0 | Detailed | Research, exploratory |
| Structure | 0.1-0.3 | Flat | Simple relationships |
| Structure | 0.4-0.7 | Hierarchical | Standard structures |
| Structure | 0.8-1.0 | Complex | Deep hierarchies |

**Example:**
```python
extractor = KnowledgeGraphExtractor()

# Basic extraction
kg = extractor.extract_knowledge_graph(text)

# Conservative extraction for legal documents
kg = extractor.extract_knowledge_graph(text, extraction_temperature=0.3)

# Detailed extraction for research papers
kg = extractor.extract_knowledge_graph(text, extraction_temperature=0.9)

# Large document with chunking
kg = extractor.extract_enhanced_knowledge_graph(large_text, use_chunking=True)

# Wikipedia extraction
kg = extractor.extract_from_wikipedia("Artificial Intelligence")
```

---

### KnowledgeGraphExtractorWithValidation Class

Enhanced extractor with automatic validation against Wikidata.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractorWithValidation
)

validator = KnowledgeGraphExtractorWithValidation(
    use_spacy: bool = False,
    use_transformers: bool = False,
    relation_patterns: Optional[List[Dict]] = None,
    min_confidence: float = 0.5,
    use_tracer: bool = True,
    sparql_endpoint_url: str = "https://query.wikidata.org/sparql",
    validate_during_extraction: bool = True,    # Validate while extracting
    auto_correct_suggestions: bool = False,      # Auto-apply corrections
    cache_validation_results: bool = True        # Cache validation results
)
```

**Methods:**
```python
# Extract with validation
validator.extract_knowledge_graph(
    text: str,
    extraction_temperature: float = 0.7,
    structure_temperature: float = 0.5,
    validation_depth: int = 1  # 1=entities only, 2=entities+relationships
) -> Dict[str, Any]
# Returns: {
#   "knowledge_graph": KnowledgeGraph,
#   "validation_results": Dict,
#   "validation_metrics": Dict,
#   "corrections": Dict
# }

# Extract from Wikipedia with validation
validator.extract_from_wikipedia(
    page_title: str,
    extraction_temperature: float = 0.7,
    structure_temperature: float = 0.5,
    validation_depth: int = 2,
    focus_validation_on_main_entity: bool = True
) -> Dict[str, Any]

# Extract from documents with validation
validator.extract_from_documents(
    documents: List[Dict],
    text_key: str = "text",
    extraction_temperature: float = 0.7,
    structure_temperature: float = 0.5,
    validation_depth: int = 1
) -> Dict[str, Any]

# Apply corrections
validator.apply_validation_corrections(
    kg: KnowledgeGraph,
    corrections: Dict[str, Any]
) -> KnowledgeGraph
```

**Validation Result Format:**
```python
{
    "knowledge_graph": KnowledgeGraph,
    "validation_results": {
        "entity_name": {
            "matched": bool,
            "wikidata_id": str,
            "properties": Dict,
            "coverage": float
        }
    },
    "validation_metrics": {
        "overall_coverage": float,
        "entities_validated": int,
        "entities_matched": int
    },
    "corrections": {
        "entity_name": {
            "suggested_properties": Dict,
            "confidence": float
        }
    }
}
```

**Example:**
```python
validator = KnowledgeGraphExtractorWithValidation(validate_during_extraction=True)

result = validator.extract_knowledge_graph(text, validation_depth=2)
kg = result["knowledge_graph"]
metrics = result["validation_metrics"]

print(f"Validation coverage: {metrics['overall_coverage']:.2%}")
print(f"Entities matched: {metrics['entities_matched']}/{metrics['entities_validated']}")
```

---

## Query API

### UnifiedQueryEngine Class

Central query execution engine for all GraphRAG operations.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

engine = UnifiedQueryEngine(
    backend: Any,                        # Graph storage backend
    vector_store: Optional[Any] = None,  # Vector store for hybrid search
    llm_processor: Optional[Any] = None, # LLM for GraphRAG
    enable_caching: bool = True,         # Enable query caching
    default_budgets: str = 'safe'        # 'strict', 'moderate', 'permissive', 'safe'
)
```

**Query Execution Methods:**
```python
# Auto-detect query type
engine.execute_query(
    query: str,
    params: Optional[Dict] = None,
    budgets: Optional[ExecutionBudgets] = None,
    query_type: str = 'auto'  # 'auto', 'cypher', 'ir', 'hybrid'
) -> QueryResult

# Execute Cypher query
engine.execute_cypher(
    query: str,
    params: Optional[Dict] = None,
    budgets: Optional[ExecutionBudgets] = None
) -> QueryResult

# Execute hybrid search (vector + graph)
engine.execute_hybrid(
    query: str,
    k: int = 10,                           # Number of results
    budgets: Optional[ExecutionBudgets] = None,
    vector_weight: float = 0.6,            # Vector importance (0-1)
    graph_weight: float = 0.4,             # Graph importance (0-1)
    max_hops: int = 2                      # Max graph traversal depth
) -> QueryResult

# Execute GraphRAG query
engine.execute_graphrag(
    question: str,
    context: Optional[Dict] = None,
    budgets: Optional[ExecutionBudgets] = None
) -> GraphRAGResult

# Batch execution
engine.batch_execute(
    queries: List[str],
    budgets: Optional[ExecutionBudgets] = None
) -> List[QueryResult]
```

**Properties:**
```python
# Lazy-loaded components
engine.cypher_compiler: CypherCompiler
engine.ir_executor: GraphQueryExecutor
engine.graph_engine: GraphEngine
```

**Example:**
```python
engine = UnifiedQueryEngine(backend=backend)

# Cypher query
result = engine.execute_cypher("""
    MATCH (p:Person)-[r:WORKED_AT]->(o:Organization)
    WHERE p.name = 'Marie Curie'
    RETURN p, r, o
""")

# Hybrid search
result = engine.execute_hybrid(
    "Nobel Prize winners in Physics",
    k=10,
    vector_weight=0.7,
    graph_weight=0.3
)

# GraphRAG question answering
result = engine.execute_graphrag(
    "Who won the Nobel Prize in Physics in 1903?"
)
```

---

### QueryResult Class

Container for query results.

**Attributes:**
```python
result.items: List[Any]              # Result items
result.stats: Dict                   # Query statistics
result.counters: Optional[ExecutionCounters]  # Resource usage counters
result.query_type: str               # Type of query executed
result.success: bool                 # Whether query succeeded
result.error: Optional[str]          # Error message if failed
```

**Methods:**
```python
result.to_dict() -> Dict  # Serialize to dictionary
```

---

### GraphRAGResult Class

Extended result for GraphRAG queries.

**Attributes:**
```python
# Inherits from QueryResult
result.reasoning: Optional[Dict]         # Reasoning trace
result.evidence_chains: Optional[List[Dict]]  # Evidence supporting answer
result.confidence: float                 # Answer confidence (0-1)
```

---

### HybridSearchEngine Class

Combines vector similarity with graph traversal.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine

hybrid = HybridSearchEngine(
    backend: Any,                        # Graph storage backend
    vector_store: Optional[Any] = None,  # Vector store
    default_vector_weight: float = 0.6,  # Default vector importance
    default_graph_weight: float = 0.4,   # Default graph importance
    cache_size: int = 1000               # LRU cache size
)
```

**Methods:**
```python
# Hybrid search
hybrid.search(
    query: str,
    k: int = 10,                              # Number of results
    vector_weight: Optional[float] = None,    # Override vector weight
    graph_weight: Optional[float] = None,     # Override graph weight
    max_hops: int = 2,                        # Max graph traversal
    min_score: float = 0.0                    # Minimum result score
) -> List[HybridSearchResult]

# Vector search only
hybrid.vector_search(
    query: str,
    k: int = 10
) -> List[HybridSearchResult]

# Graph expansion from seed nodes
hybrid.graph_expand(
    seed_nodes: List[str],
    max_hops: int = 2,
    max_results: int = 100
) -> List[HybridSearchResult]

# Fuse vector and graph results
hybrid.fuse_results(
    vector_results: List[HybridSearchResult],
    graph_results: List[HybridSearchResult],
    vector_weight: float = 0.6,
    graph_weight: float = 0.4,
    strategy: str = 'weighted'  # 'weighted', 'rrf', 'max'
) -> List[HybridSearchResult]

# Clear cache
hybrid.clear_cache()
```

**Example:**
```python
hybrid = HybridSearchEngine(backend=backend, vector_store=vector_store)

# Search with default weights
results = hybrid.search("Nobel Prize winners", k=10)

# Custom weights
results = hybrid.search(
    "machine learning researchers",
    k=20,
    vector_weight=0.8,  # More emphasis on semantic similarity
    graph_weight=0.2,
    max_hops=3
)

# Process results
for result in results:
    print(f"{result.node_id}: {result.score:.3f}")
```

---

### HybridSearchResult Class

Container for hybrid search results.

**Attributes:**
```python
result.node_id: str              # Node identifier
result.score: float              # Combined score (0-1)
result.vector_score: float       # Vector similarity score (0-1)
result.graph_score: float        # Graph score (0-1)
result.hop_distance: int         # Distance from seed nodes
result.metadata: Optional[Dict]  # Additional metadata
```

---

### BudgetManager Class

Manages resource budgets for query execution.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.query import BudgetManager

budget_manager = BudgetManager()
```

**Methods:**
```python
# Track execution with budget (context manager)
with budget_manager.track(budgets) as tracker:
    # Execute queries
    # tracker.check_timeout()
    # tracker.check_nodes()
    pass

# Create preset budgets
budgets = budget_manager.create_preset_budgets(
    preset: str  # 'strict', 'moderate', 'permissive', 'safe'
) -> ExecutionBudgets

# Check if budget exceeded
exceeded_reason = budget_manager.check_exceeded(
    counters: ExecutionCounters,
    budgets: ExecutionBudgets
) -> Optional[str]  # None if not exceeded, reason string if exceeded
```

**Budget Presets:**

| Budget | Strict | Moderate | Permissive | Safe |
|--------|--------|----------|------------|------|
| Timeout (ms) | 1,000 | 5,000 | 30,000 | 2,000 |
| Max Nodes | 100 | 1,000 | 10,000 | 500 |
| Max Edges | 500 | 5,000 | 50,000 | 2,500 |
| Max Depth | 3 | 5 | 10 | 4 |
| Max Backend Calls | 10 | 50 | 200 | 25 |

**Example:**
```python
budget_manager = BudgetManager()

# Use preset
budgets = budget_manager.create_preset_budgets('safe')

# Execute with budget tracking
with budget_manager.track(budgets) as tracker:
    result = engine.execute_cypher(query, budgets=budgets)
    
    if tracker.exceeded:
        print(f"Budget exceeded: {tracker.exceeded_reason}")
```

---

### ExecutionBudgets Class

Defines resource limits for query execution.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.query import ExecutionBudgets

budgets = ExecutionBudgets(
    timeout_ms: int,          # Maximum execution time (milliseconds)
    max_nodes_visited: int,   # Maximum nodes to visit
    max_edges_scanned: int,   # Maximum edges to scan
    max_traversal_depth: int, # Maximum graph traversal depth
    max_backend_calls: int    # Maximum backend API calls
)
```

---

### ExecutionCounters Class

Tracks resource usage during query execution.

**Attributes:**
```python
counters.nodes_visited: int      # Nodes visited
counters.edges_scanned: int      # Edges scanned
counters.traversal_depth: int    # Maximum depth reached
counters.backend_calls: int      # Backend API calls made
counters.cache_hits: int         # Cache hits
counters.cache_misses: int       # Cache misses
```

---

### BudgetTracker Class

Context manager for budget tracking.

**Attributes:**
```python
tracker.budgets: ExecutionBudgets
tracker.counters: ExecutionCounters
tracker.started: float              # Start time (monotonic)
tracker.exceeded: bool              # Whether budget exceeded
tracker.exceeded_reason: Optional[str]  # Reason if exceeded
```

**Methods:**
```python
tracker.check_timeout()        # Check time budget
tracker.check_nodes()          # Check node budget
tracker.check_edges()          # Check edge budget
tracker.check_depth()          # Check depth budget
tracker.check_backend_calls()  # Check backend call budget
```

---

## Storage API

### IPLDBackend Class

IPFS/IPLD storage backend for knowledge graphs.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

backend = IPLDBackend(ipfs_client: Any)
```

**Methods:**
```python
# Store knowledge graph
cid = backend.store(
    graph: KnowledgeGraph,
    codec: str = "dag-cbor"  # Serialization codec
) -> str  # Returns CID (Content Identifier)

# Retrieve knowledge graph
kg = backend.retrieve(cid: str) -> KnowledgeGraph

# Check if CID exists
exists = backend.exists(cid: str) -> bool

# List all stored graphs
cids = backend.list_graphs() -> List[str]
```

**Supported Codecs:**
- `"dag-cbor"` - DAG-CBOR (recommended, compact binary)
- `"dag-json"` - DAG-JSON (human-readable)
- `"json"` - Standard JSON

**Example:**
```python
backend = IPLDBackend(ipfs_client)

# Store graph
cid = backend.store(kg, codec="dag-cbor")
print(f"Stored at CID: {cid}")

# Retrieve graph
kg_retrieved = backend.retrieve(cid)

# Check existence
if backend.exists(cid):
    print("Graph exists in IPFS")
```

---

## Transaction API

### TransactionManager Class

ACID-compliant transaction management.

**Constructor:**
```python
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager

tx_manager = TransactionManager(backend: Any)
```

**Methods:**
```python
# Begin transaction
tx = tx_manager.begin_transaction() -> Transaction

# Commit transaction
tx_manager.commit(tx: Transaction)

# Rollback transaction
tx_manager.rollback(tx: Transaction)

# Get transaction status
status = tx_manager.get_status(tx: Transaction) -> str
# Returns: 'active', 'committed', 'rolled_back'
```

**Transaction Class:**
```python
# Add operations to transaction
tx.add_entity(entity: Entity)
tx.add_relationship(relationship: Relationship)
tx.remove_entity(entity_id: str)
tx.remove_relationship(relationship_id: str)

# Transaction properties
tx.id: str                       # Transaction ID
tx.started_at: datetime         # Start timestamp
tx.operations: List[Dict]       # List of operations
```

**Example:**
```python
tx_manager = TransactionManager(backend)

# Begin transaction
tx = tx_manager.begin_transaction()

try:
    # Perform operations
    tx.add_entity(entity1)
    tx.add_entity(entity2)
    tx.add_relationship(relationship)
    
    # Commit if successful
    tx_manager.commit(tx)
    print("Transaction committed")
    
except Exception as e:
    # Rollback on error
    tx_manager.rollback(tx)
    print(f"Transaction rolled back: {e}")
```

---

## Cypher Language Reference

### Supported Clauses

#### MATCH
```cypher
MATCH (n:Person)
MATCH (n:Person)-[r:WORKS_AT]->(o:Organization)
MATCH (n) WHERE n.name = 'Marie Curie'
```

#### WHERE
```cypher
WHERE n.name = 'Marie Curie'
WHERE n.age > 30
WHERE n.name CONTAINS 'Curie'
```

#### RETURN
```cypher
RETURN n
RETURN n, r, o
RETURN n.name, n.age
RETURN COUNT(n)
```

#### CREATE
```cypher
CREATE (n:Person {name: 'Albert Einstein', field: 'Physics'})
```

#### ORDER BY
```cypher
ORDER BY n.name
ORDER BY n.age DESC
```

#### LIMIT
```cypher
LIMIT 10
```

### Supported Functions

#### Aggregation
- `COUNT(expr)` - Count items
- `SUM(expr)` - Sum numeric values
- `AVG(expr)` - Average of numeric values
- `MIN(expr)` - Minimum value
- `MAX(expr)` - Maximum value

#### String
- `CONTAINS(str, substr)` - Check if string contains substring
- `STARTS WITH(str, prefix)` - Check if string starts with prefix
- `ENDS WITH(str, suffix)` - Check if string ends with suffix

#### Example Queries

```cypher
-- Find all persons
MATCH (p:Person)
RETURN p

-- Find persons who worked at organizations
MATCH (p:Person)-[r:WORKED_AT]->(o:Organization)
RETURN p.name, o.name

-- Count entities by type
MATCH (n)
RETURN n.entity_type, COUNT(n)

-- Find paths between entities
MATCH path = (a:Person)-[*1..5]-(b:Person)
WHERE a.name = 'Marie Curie' AND b.name = 'Albert Einstein'
RETURN path

-- Top 10 most connected entities
MATCH (n)-[r]-()
RETURN n.name, COUNT(r) AS degree
ORDER BY degree DESC
LIMIT 10
```

### Known Limitations

**Not Yet Supported:**
- `NOT` operator in WHERE clauses - **Workaround:** Use positive conditions
- `CREATE` for relationships - **Workaround:** Create relationships via API
- Complex pattern matching - **Workaround:** Break into multiple queries

---

## Utility APIs

### Constraints API

Define and enforce constraints on knowledge graphs.

```python
from ipfs_datasets_py.knowledge_graphs.constraints import (
    UniqueConstraint,
    ExistenceConstraint,
    PropertyConstraint
)

# Unique constraint
unique = UniqueConstraint(entity_type="person", property="name")

# Existence constraint
exists = ExistenceConstraint(entity_type="person", property="name")

# Property constraint
prop = PropertyConstraint(
    entity_type="person",
    property="age",
    validator=lambda x: isinstance(x, int) and x > 0
)

# Apply constraints
kg.add_constraint(unique)
kg.validate_constraints()  # Raises exception if violated
```

---

### Indexing API

Manage indexes for query performance.

```python
from ipfs_datasets_py.knowledge_graphs.indexing import IndexManager

index_manager = IndexManager(backend)

# Create index
index_manager.create_index(
    index_type="btree",
    entity_type="person",
    property="name"
)

# List indexes
indexes = index_manager.list_indexes()

# Drop index
index_manager.drop_index(index_name)
```

---

### JSON-LD API

JSON-LD serialization and validation.

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import JSONLDTranslator

translator = JSONLDTranslator()

# Convert to JSON-LD
jsonld = translator.to_jsonld(kg)

# Convert from JSON-LD
kg = translator.from_jsonld(jsonld)

# Validate JSON-LD
is_valid = translator.validate(jsonld)
```

---

## Compatibility APIs

### Neo4j Driver Compatibility

Neo4j-compatible driver API.

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

# Create driver
driver = GraphDatabase.driver("ipfs://localhost:5001")

# Create session
with driver.session() as session:
    result = session.run("MATCH (n) RETURN n LIMIT 10")
    
    for record in result:
        print(record["n"])

# Close driver
driver.close()
```

**Compatible Methods:**
- `GraphDatabase.driver(uri)` - Create driver
- `driver.session()` - Create session
- `session.run(query, params)` - Execute query
- `session.close()` - Close session
- `driver.close()` - Close driver

---

## Error Handling

### Common Exceptions

```python
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    ExtractionError,
    ValidationError,
    StorageError,
    QueryError,
    BudgetExceededError
)

try:
    kg = extractor.extract_knowledge_graph(text)
except ExtractionError as e:
    # Extraction failed
    pass
except ValidationError as e:
    # Validation failed
    pass
except StorageError as e:
    # Storage operation failed
    pass
except QueryError as e:
    # Query execution failed
    pass
except BudgetExceededError as e:
    # Resource budget exceeded
    pass
```

---

## Version Information

- **Extraction API:** v0.1.0
- **Query API:** v1.0.0
- **Storage API:** v1.0.0
- **Transaction API:** v1.0.0

All APIs are production-ready with full backward compatibility.

---

**See also:**
- [USER_GUIDE.md](USER_GUIDE.md) - Usage patterns and examples
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
- [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) - Migration paths

---

**Last Updated:** 2026-02-17  
**Version:** 2.0.0  
**Status:** Production-Ready
