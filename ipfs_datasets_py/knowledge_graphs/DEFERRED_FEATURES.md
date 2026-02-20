# Knowledge Graphs - Deferred Features

**Last Updated:** 2026-02-20  
**Purpose:** Explicitly document features marked for future implementation

---

## Overview

This document clarifies which features in the knowledge_graphs module are **intentionally incomplete** with planned implementation in future versions. These are not bugs or oversights - they are deliberate deferrals based on prioritization and user feedback.

Items marked ✅ have been **implemented** and are tracked here for historical reference.

---

## P1: High Priority (v2.1.0)

### 1. Cypher NOT Operator

**Status:** ✅ Implemented (v2.1.0 — 2026-02-19)  
**Location:** `cypher/parser.py`, `cypher/compiler.py`, `core/expression_evaluator.py`  
**Implementation:**
- Parser: `_parse_not()` handles `NOT expr` AST nodes
- Compiler: emits `UnaryOpNode(operator="NOT")` or negated simple operators (e.g. `>` → `<=`)
- Evaluator: `evaluate_compiled_expression` handles `{"op": "NOT", "operand": ...}` plus short-circuit `AND`/`OR`

**Example (now works):**
```python
executor.execute("MATCH (p:Person) WHERE NOT p.age > 30 RETURN p")
executor.execute("MATCH (p:Person) WHERE NOT (p.age > 30 AND p.city = 'NYC') RETURN p")
```

**Tests:** `tests/unit/knowledge_graphs/test_p1_deferred_features.py`

---

### 2. Cypher CREATE Relationships

**Status:** ✅ Implemented (v2.1.0 — 2026-02-19)  
**Location:** `cypher/compiler.py` — `_compile_create()`  
**Implementation:**
- `CreateNode` + `CreateRelationship` IR operations emitted for `CREATE (a)-[r:TYPE]->(b)` patterns
- Handles left/right/undirected directions and relationship properties

**Example (now works):**
```cypher
MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'})
CREATE (a)-[r:KNOWS]->(b)
RETURN r
```

**Tests:** `tests/unit/knowledge_graphs/test_p1_deferred_features.py`

---

### 2b. Cypher MERGE Clause

**Status:** ✅ Implemented (v2.1.0 — 2026-02-20)  
**Location:** `cypher/ast.py` (`MergeClause`), `cypher/parser.py` (`_parse_merge`), `cypher/compiler.py` (`_compile_merge`), `core/ir_executor.py` (Merge handler)  
**Implementation:**
- Match-or-create: tries to MATCH the pattern first; if found, uses existing node(s); otherwise CREATEs them
- ON CREATE SET: property assignments applied only when the node is newly created
- ON MATCH SET: property assignments applied only when an existing node was matched
- Idempotent: repeated MERGE with the same key never creates duplicates

**Example (now works):**
```cypher
MERGE (n:Person {name: 'Alice'})
MERGE (n:Person {name: 'Alice'})   -- no duplicate created
MERGE (n:Person {name: 'Bob'})     -- creates Bob
```

**Tests:** `tests/unit/knowledge_graphs/test_merge_remove_isnull_xor.py`

---

### 2c. Cypher REMOVE Clause

**Status:** ✅ Implemented (v2.1.0 — 2026-02-20)  
**Location:** `cypher/ast.py` (`RemoveClause`), `cypher/parser.py` (`_parse_remove`), `cypher/compiler.py` (`_compile_remove`), `core/ir_executor.py` (RemoveProperty / RemoveLabel handlers)  
**Implementation:**
- `REMOVE n.property` → emits `RemoveProperty` IR op; deletes the key from the node's `_properties`
- `REMOVE n:Label` → emits `RemoveLabel` IR op; removes the label from the node's `_labels` frozenset

**Example (now works):**
```cypher
MATCH (n:Person) WHERE n.name = 'Alice' REMOVE n.email
MATCH (n:Employee) REMOVE n:Employee
```

**Tests:** `tests/unit/knowledge_graphs/test_merge_remove_isnull_xor.py`

---

### 2d. IS NULL / IS NOT NULL Operators

**Status:** ✅ Implemented (v2.1.0 — 2026-02-20)  
**Location:** `cypher/parser.py` (`_parse_comparison`), `cypher/compiler.py` (`_compile_where_expression`), `core/expression_evaluator.py` (`evaluate_compiled_expression`)  
**Implementation:**
- Parser: `IS NULL` / `IS NOT NULL` produce `UnaryOpNode(operator="IS NULL"/"IS NOT NULL", operand=property_expr)`
- Compiler: emits `Filter` with `{"op": "IS NULL", "operand": ...}`
- Evaluator: `IS NULL` returns `operand is None`; `IS NOT NULL` returns `operand is not None`

**Example (now works):**
```cypher
MATCH (p:Person) WHERE p.email IS NULL RETURN p.name     -- Bob (no email)
MATCH (p:Person) WHERE p.email IS NOT NULL RETURN p.name -- Alice (has email)
```

**Tests:** `tests/unit/knowledge_graphs/test_merge_remove_isnull_xor.py`

---

### 2e. XOR Boolean Operator

**Status:** ✅ Implemented (v2.1.0 — 2026-02-20)  
**Location:** `cypher/parser.py` (`_parse_or` extended for `TokenType.XOR`), `cypher/compiler.py` (`_compile_where_expression` XOR branch), `core/expression_evaluator.py`  
**Implementation:**
- Parser: `_parse_or` now accepts OR **and** XOR tokens, producing `BinaryOpNode(operator="XOR",...)`
- Compiler: XOR gets its own branch in `_compile_where_expression` (cannot use simple property-filter path; both operands need evaluation)
- Evaluator: `apply_operator` and `evaluate_compiled_expression` both handle `XOR` as `bool(left) ^ bool(right)`

**Example (now works):**
```cypher
MATCH (n:Item) WHERE n.a XOR n.b RETURN n  -- True XOR False = True
```

**Tests:** `tests/unit/knowledge_graphs/test_merge_remove_isnull_xor.py`

---

## P2: Medium Priority (v2.2.0)

### 3. GraphML Format Support

**Status:** ✅ Implemented (v2.2.0 — 2026-02-19)  
**Location:** `migration/formats.py` — `_save_to_graphml` / `_load_from_graphml`  
**Implementation:** Full read/write support using `xml.etree.ElementTree`. Preserves node labels, properties, edge types.

**Tests:** `tests/unit/knowledge_graphs/test_p2_format_support.py`

---

### 4. GEXF Format Support

**Status:** ✅ Implemented (v2.2.0 — 2026-02-19)  
**Location:** `migration/formats.py` — `_save_to_gexf` / `_load_from_gexf`  
**Implementation:** Full read/write support for GEXF 1.2draft. Preserves node attributes and edge types.

**Tests:** `tests/unit/knowledge_graphs/test_p2_format_support.py`

---

### 5. Pajek Format Support

**Status:** ✅ Implemented (v2.2.0 — 2026-02-19)  
**Location:** `migration/formats.py` — `_save_to_pajek` / `_load_from_pajek`  
**Implementation:** Read/write support for Pajek `.net` format (`*Vertices`, `*Arcs`, `*Edges` sections).

**Tests:** `tests/unit/knowledge_graphs/test_p2_format_support.py`

---

### 6. CAR Format Support

**Status:** ✅ Implemented (v2.1.0 — 2026-02-19)
**Location:** `migration/formats.py` — `_builtin_save_car` / `_builtin_load_car`
**Library decision:**
- **Option 1 — `libipld` (v3.3.2, Rust-backed):** Fast DAG-CBOR encoding/decoding and
  CAR decoding. No `encode_car` function. Used as primary decoder (faster, Rust extension).
- **Option 2 — `ipld-car` (v0.0.1) + `ipld-dag-pb` (v0.0.1):** Pure-Python CAR
  encode + decode, supports any codec. `ipld-dag-pb` not needed for graph data.
- **Decision:** Use `libipld` for DAG-CBOR encoding + `ipld-car` for CAR file
  creation. Decode prefers `libipld` (fast), falls back to `ipld-car` + `dag-cbor`.

**Install extras:** `pip install -e ".[ipld]"` (adds `libipld`, `ipld-car`, `dag-cbor`)

**Usage:**
```python
from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData, MigrationFormat,
)
graph_data.save_to_file("graph.car", format=MigrationFormat.CAR)
loaded = GraphData.load_from_file("graph.car", format=MigrationFormat.CAR)
```

**Tests:** `tests/unit/knowledge_graphs/test_car_format.py`

---

## P3: Lower Priority (v2.5.0)

### 7. Neural Relationship Extraction

**Status:** ✅ Implemented (v2.5.0 — 2026-02-19)  
**Location:** `extraction/extractor.py` — `_neural_relationship_extraction()`, `_parse_rebel_output()`  
**Implementation:**
- Supports REBEL (text2text generation) and classification-based models (e.g. TACRED)
- Activated with `KnowledgeGraphExtractor(use_transformers=True)`
- Gracefully falls back to rule-based when model not available
- REBEL output parser included (`_parse_rebel_output`)

**Example:**
```python
extractor = KnowledgeGraphExtractor(use_transformers=True, re_model=loaded_pipeline)
kg = extractor.extract_knowledge_graph(text)
```

**Tests:** `tests/unit/knowledge_graphs/test_p3_p4_advanced_features.py`

---

### 8. Aggressive Entity Extraction (spaCy Dependency Parsing)

**Status:** ✅ Implemented (v2.5.0 — 2026-02-19)  
**Location:** `extraction/extractor.py` — `_aggressive_entity_extraction()`  
**Implementation:**
- Uses spaCy dependency parser for compound nouns and SVO extraction
- Activated with `KnowledgeGraphExtractor(use_spacy=True, aggressive_extraction=True)`
- Gracefully returns empty list when spaCy model not loaded

**Tests:** `tests/unit/knowledge_graphs/test_p3_p4_advanced_features.py`

---

### 9. Semantic Role Labeling (SRL)

**Status:** ✅ Implemented (v2.5.0 — 2026-02-20)
**Location:** `extraction/srl.py` — `SRLExtractor`, `SRLFrame`, `RoleArgument`
**Implementation:**
- `SRLExtractor.extract_srl(text)` → list of `SRLFrame` objects (one per predicate)
- Heuristic backend: pure-Python SVO + modifier extraction (no external deps)
- spaCy backend: dependency-parse–based extraction when `nlp=` model is provided
- Semantic roles: Agent, Patient, Theme, Instrument, Location, Time, Cause, Result, Recipient, Source
- `SRLExtractor.to_knowledge_graph(frames)` → event-centric `KnowledgeGraph` (Event nodes + typed role relationships)
- `SRLExtractor.extract_to_triples(text)` → `(subject, predicate, object)` tuples
- Graceful fallback: always works even without spaCy or any ML model

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

ext = SRLExtractor()                     # heuristic mode
frames = ext.extract_srl("Alice sent the report to Bob yesterday.")
kg = ext.to_knowledge_graph(frames)      # Event + Agent + Patient + Time entities
triples = ext.extract_to_triples(text)   # (subject, predicate, object) list
```

**Tests:** `tests/unit/knowledge_graphs/test_srl_ontology_distributed.py` (12 tests)

---

## P4: Long-term (v3.0.0)

### 10. Multi-hop Graph Traversal

**Status:** ✅ Implemented (v3.0.0 — 2026-02-19)  
**Location:** `_reasoning_helpers.py` — `ReasoningHelpersMixin._find_multi_hop_connections()`  
**Implementation:**
- BFS-based multi-hop entity path finder
- Integrated into `CrossDocumentReasoner` via mixin inheritance
- Activated when `max_hops > 1` in `find_entity_connections()`
- DFS traversal path generation via `_generate_traversal_paths()`

**Tests:** `tests/unit/knowledge_graphs/test_p3_p4_advanced_features.py`

---

### 11. LLM API Integration

**Status:** ✅ Implemented (v3.0.0 — 2026-02-19)  
**Location:** `_reasoning_helpers.py` — `ReasoningHelpersMixin._generate_llm_answer()`, `_get_llm_router()`  
**Implementation:**
- Supports OpenAI, Anthropic, and local LLM models via `ipfs_datasets_py.ml.llm.LLMRouter`
- Lazy router initialization in `_get_llm_router()`
- Graceful fallback to heuristic answer generation when LLM unavailable
- Used in `CrossDocumentReasoner._synthesize_answer()`

**Example:**
```python
from ipfs_datasets_py.ml.llm.llm_router import LLMRouter
router = LLMRouter(provider="openai", model="gpt-4")
reasoner = CrossDocumentReasoner(llm_service=router)
result = reasoner.reason_across_documents(documents, query="Who collaborated with Alice?")
```

**Tests:** `tests/unit/knowledge_graphs/test_p3_p4_advanced_features.py`

---

### 12. Inference Rules and Ontology Reasoning

**Status:** ✅ Implemented (v3.0.0 — 2026-02-20)
**Location:** `ontology/reasoning.py` — `OntologySchema`, `OntologyReasoner`, `ConsistencyViolation`
**Implementation:**
- `OntologySchema` builder: `add_subclass`, `add_subproperty`, `add_transitive`, `add_symmetric`, `add_inverse`, `add_domain`, `add_range`, `add_disjoint`
- `OntologyReasoner.materialize(kg)` — runs a fixpoint loop applying all declared rules
  - **subClassOf** — nodes gain inferred super-class types (stored in `entity.properties["inferred_types"]`)
  - **subPropertyOf** — new relationships generated for each declared super-property
  - **transitive** — BFS-based transitive closure
  - **symmetric** — reverse relationships for symmetric properties
  - **inverseOf** — inverse-direction relationships generated
  - **domain** — source nodes of a property gain the declared domain class
  - **range** — target nodes of a property gain the declared range class
- `OntologyReasoner.check_consistency(kg)` — detects disjoint class violations and negative assertion conflicts

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema, OntologyReasoner

schema = OntologySchema()
schema.add_subclass("Employee", "Person")
schema.add_transitive("isAncestorOf")
schema.add_symmetric("isSiblingOf")
schema.add_inverse("isManagerOf", "isManagedBy")
schema.add_domain("worksAt", "Person")
schema.add_range("worksAt", "Organization")

reasoner = OntologyReasoner(schema)
kg2 = reasoner.materialize(kg)          # returns augmented copy
violations = reasoner.check_consistency(kg2)
```

**Tests:** `tests/unit/knowledge_graphs/test_srl_ontology_distributed.py` (11 tests)

---

### 13. Distributed Query Execution

**Status:** ✅ Implemented (v3.0.0 — 2026-02-20)
**Location:** `query/distributed.py` — `GraphPartitioner`, `DistributedGraph`, `FederatedQueryExecutor`
**Implementation:**
- `GraphPartitioner(num_partitions, strategy)` — partitions a `KnowledgeGraph` into N shards
  - Strategies: `HASH` (SHA1 of node ID mod N), `RANGE` (sorted ID buckets), `ROUND_ROBIN`
  - Cross-partition edges are copied to both source and target partitions by default
- `DistributedGraph` — holds `N` partition `KnowledgeGraph` objects
  - `get_partition_for_entity(entity_id)` — locate which partition holds an entity
  - `to_merged_graph()` — re-merge all partitions into a single graph
  - `get_partition_stats()` — per-partition node/edge counts
- `FederatedQueryExecutor(dist_graph)` — fan-out Cypher query execution
  - `execute_cypher(query)` — serial fan-out, merge + deduplicate
  - `execute_cypher_parallel(query, max_workers)` — thread-pool fan-out
  - Each partition gets its own in-memory `GraphEngine` populated from partition nodes/rels
  - Deduplication uses SHA1 fingerprint of serialised record dicts

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.query.distributed import (
    GraphPartitioner, FederatedQueryExecutor, PartitionStrategy,
)

dist = GraphPartitioner(num_partitions=4, strategy=PartitionStrategy.HASH).partition(kg)
result = FederatedQueryExecutor(dist).execute_cypher(
    "MATCH (n:Person) WHERE n.age > 30 RETURN n.name, n.age"
)
for row in result.records:
    print(row)
```

**Tests:** `tests/unit/knowledge_graphs/test_srl_ontology_distributed.py` (15 tests)

---

## How to Use This Document

### For Users

**Encountering a missing feature?**
1. Check this document to see if it's intentionally deferred
2. Check the workaround section for alternatives
3. See the timeline for when it might be implemented
4. Open a GitHub issue if you need it sooner (helps prioritization)

### For Contributors

**Want to implement a deferred feature?**
1. Check the timeline and priority
2. Review the effort estimate
3. See [CONTRIBUTING.md](../../docs/knowledge_graphs/CONTRIBUTING.md) for guidelines
4. Open an issue to discuss before starting work
5. Reference this document in your PR

### For Maintainers

**Adding a new deferred feature:**
1. Add entry to appropriate priority section
2. Include location, status, reason, impact, example, timeline, effort
3. Update ROADMAP.md with the same information
4. Update MASTER_STATUS.md to reflect the updated deferred feature list/status

---

## See Also

- [ROADMAP.md](ROADMAP.md) - Complete development timeline
- [MASTER_STATUS.md](./MASTER_STATUS.md) - Current status (single source of truth)
- [COMPREHENSIVE_ANALYSIS_2026_02_18.md](./COMPREHENSIVE_ANALYSIS_2026_02_18.md) - Comprehensive analysis
- [IMPROVEMENT_TODO.md](./IMPROVEMENT_TODO.md) - Infinite improvement backlog

---

**Last Updated:** 2026-02-20  
**Next Review:** Q3 2026 (before v2.5.0 release)  
**Maintainer:** Knowledge Graphs Team

