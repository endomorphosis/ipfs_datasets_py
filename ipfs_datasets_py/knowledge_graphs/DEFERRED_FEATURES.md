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

### 2f. Cypher FOREACH Clause

**Status:** ✅ Implemented (v2.1.0 — 2026-02-20 session 5)
**Location:** `cypher/lexer.py` (`FOREACH` TokenType), `cypher/ast.py` (`ForeachClause`),
             `cypher/parser.py` (`_parse_foreach`), `cypher/compiler.py` (`_compile_foreach`),
             `core/ir_executor.py` (Foreach op handler)
**Implementation:**
- Lexer: `FOREACH` keyword added to `TokenType` enum and `KEYWORDS` dict
- AST: `ForeachClause(variable, expression, body)` dataclass with `FOREACH` node type
- Parser: `_parse_foreach()` parses `FOREACH (variable IN list_expr | clause*)` grammar
- Compiler: `_compile_foreach()` emits `{"op": "Foreach", "variable", "expression", "body_ops"}` IR
- Executor: iterates list expression, runs `body_ops` sub-program with loop variable bound per element

**Example (now works):**
```cypher
FOREACH (x IN [1, 2, 3] | CREATE (:Counter {value: x}))
FOREACH (n IN relatedNodes | SET n.visited = true)
```

**Tests:** `tests/unit/knowledge_graphs/test_foreach_call_mcp.py` (10 FOREACH tests)

---

### 2g. Cypher CALL Subquery

**Status:** ✅ Implemented (v2.1.0 — 2026-02-20 session 5)
**Location:** `cypher/ast.py` (`CallSubquery`), `cypher/parser.py` (`_parse_call_subquery`),
             `cypher/compiler.py` (`_compile_call_subquery`), `core/ir_executor.py` (CallSubquery handler)
**Implementation:**
- AST: `CallSubquery(body, yield_items)` dataclass with inner `QueryNode` body and optional YIELD declarations
- Parser: `_parse_call_subquery()` collects inner token stream, re-parses via a fresh `CypherParser`, and
  parses an optional `YIELD col [AS alias]` list
- Compiler: `_compile_call_subquery()` compiles inner query into `inner_ops` and emits
  `{"op": "CallSubquery", "inner_ops", "yield_items"}`
- Executor: runs `inner_ops` recursively via `execute_ir_operations`, then merges inner records into
  outer bindings (applying YIELD aliases where declared)

**Example (now works):**
```cypher
CALL { MATCH (n:Person) RETURN n.name AS name }
CALL { MATCH (n) RETURN count(n) AS total } YIELD total
CALL { MATCH (n:Person) RETURN n.name AS nm } YIELD nm AS personName
```

**Tests:** `tests/unit/knowledge_graphs/test_foreach_call_mcp.py` (9 CALL tests)

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

**Status:** ✅ Implemented (v2.5.0 — 2026-02-20); deepened (2026-02-20 session 3); deepened again (2026-02-20 session 4)
**Location:** `extraction/srl.py` — `SRLExtractor`, `SRLFrame`, `RoleArgument`;
             `extraction/extractor.py` — `KnowledgeGraphExtractor`
**Implementation:**
- `SRLExtractor.extract_srl(text)` → list of `SRLFrame` objects (one per predicate)
- Heuristic backend: pure-Python SVO + modifier extraction (no external deps)
- spaCy backend: dependency-parse–based extraction when `nlp=` model is provided
- Semantic roles: Agent, Patient, Theme, Instrument, Location, Time, Cause, Result, Recipient, Source
- `SRLExtractor.to_knowledge_graph(frames)` → event-centric `KnowledgeGraph` (Event nodes + typed role relationships)
- `SRLExtractor.extract_to_triples(text)` → `(subject, predicate, object)` tuples
- Graceful fallback: always works even without spaCy or any ML model
- **Integration** (session 3): `KnowledgeGraphExtractor(use_srl=True)` merges SRL triples into
  every `extract_knowledge_graph()` call via `_merge_srl_into_kg()`
- **Standalone** (session 3): `extractor.extract_srl_knowledge_graph(text)` returns a
  pure event-centric KG without entity/relationship extraction
- **`SRLFrame.from_dict(data)`** (session 4): classmethod to deserialize a frame dict;
  completes the `to_dict` round-trip
- **`SRLExtractor.extract_batch(texts)`** (session 4): convenience method for batch extraction
  across a list of strings; returns one frame list per input, in order
- **`SRLExtractor.build_temporal_graph(text)`** (session 4): extracts events and links them
  with `PRECEDES` / `OVERLAPS` temporal relationships based on connector words (then, meanwhile,
  subsequently, etc.) and sentence ordering

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor
from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor

# Standalone SRL
ext_srl = SRLExtractor()
frames = ext_srl.extract_srl("Alice sent the report to Bob yesterday.")
kg = ext_srl.to_knowledge_graph(frames)

# Integrated SRL enrichment
ext = KnowledgeGraphExtractor(use_srl=True)
kg2 = ext.extract_knowledge_graph("Alice sent Bob a report.")  # SRL triples merged
kg3 = ext.extract_srl_knowledge_graph("Alice taught Bob.")     # event-centric only
```

# Batch extraction (session 4)
ext_srl.extract_batch(["Alice sent a report.", "Bob replied."])

# Temporal graph (session 4)
tg = ext_srl.build_temporal_graph("Alice opened the door. Then Bob walked in.")
```

**Tests:** `tests/unit/knowledge_graphs/test_srl_ontology_distributed.py` (12 tests),
           `tests/unit/knowledge_graphs/test_srl_ontology_distributed_cont.py` (7 tests),
           `tests/unit/knowledge_graphs/test_deferred_session4.py` (13 SRL tests)

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

**Status:** ✅ Implemented (v3.0.0 — 2026-02-20); deepened (session 3); deepened again (session 4)
**Location:** `ontology/reasoning.py` — `OntologySchema`, `OntologyReasoner`, `ConsistencyViolation`, `InferenceTrace`
**Implementation:**
- `OntologySchema` builder: `add_subclass`, `add_subproperty`, `add_transitive`, `add_symmetric`, `add_inverse`, `add_domain`, `add_range`, `add_disjoint`
- **OWL 2 property chains** (session 3): `add_property_chain(chain, result_property)` — declares
  `owl:propertyChainAxiom`; materialized during the fixpoint loop
- **Turtle serialization** (session 3): `to_turtle()` and `from_turtle(text)` — round-trip OWL/RDFS
  declarations in Turtle format without needing `rdflib`
- **`add_equivalent_class(a, b)`** (session 4): declares `owl:equivalentClass`; populates mutual
  `subClassOf` entries so materialisation treats both as the same class; serialised in Turtle
- **`merge(other)`** (session 4): returns a new `OntologySchema` that is the union of both schemas;
  self takes precedence for single-value maps; neither input is modified
- `OntologyReasoner.materialize(kg)` — runs a fixpoint loop applying all declared rules
  - **subClassOf** — nodes gain inferred super-class types (stored in `entity.properties["inferred_types"]`)
  - **subPropertyOf** — new relationships generated for each declared super-property
  - **transitive** — BFS-based transitive closure
  - **symmetric** — reverse relationships for symmetric properties
  - **inverseOf** — inverse-direction relationships generated
  - **domain** — source nodes of a property gain the declared domain class
  - **range** — target nodes of a property gain the declared range class
  - **propertyChainAxiom** (session 3) — multi-step chain inference
- `OntologyReasoner.check_consistency(kg)` — detects disjoint class violations and negative assertion conflicts
- **`OntologyReasoner.explain_inferences(kg)`** (session 4): dry-run materialize on a copy; returns
  a list of `InferenceTrace` objects recording `rule`, `subject_id`, `predicate`, `object_id`,
  `source_ids`, and a human-readable `description`; does **not** modify `kg`

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.ontology import OntologySchema, OntologyReasoner, InferenceTrace

schema = OntologySchema()
schema.add_subclass("Employee", "Person")
schema.add_transitive("isAncestorOf")
schema.add_equivalent_class("Person", "Human")       # session 4

schema2 = OntologySchema()
schema2.add_symmetric("isSiblingOf")
combined = schema.merge(schema2)                       # session 4

reasoner = OntologyReasoner(combined)
kg2 = reasoner.materialize(kg)
violations = reasoner.check_consistency(kg2)

# Inference provenance (session 4)
traces = reasoner.explain_inferences(kg)  # dry-run, kg unchanged
for t in traces:
    print(f"[{t.rule}] {t.description}")
```

**Tests:** `tests/unit/knowledge_graphs/test_srl_ontology_distributed.py` (11 tests),
           `tests/unit/knowledge_graphs/test_srl_ontology_distributed_cont.py` (12 tests),
           `tests/unit/knowledge_graphs/test_deferred_session4.py` (14 OWL tests)

---

### 13. Distributed Query Execution

**Status:** ✅ Implemented (v3.0.0 — 2026-02-20); deepened (session 3); deepened again (session 4)
**Location:** `query/distributed.py` — `GraphPartitioner`, `DistributedGraph`, `FederatedQueryExecutor`
**Implementation:**
- `GraphPartitioner(num_partitions, strategy)` — partitions a `KnowledgeGraph` into N shards
  - Strategies: `HASH` (SHA1 of node ID mod N), `RANGE` (sorted ID buckets), `ROUND_ROBIN`
  - Cross-partition edges are copied to both source and target partitions by default
- `DistributedGraph` — holds `N` partition `KnowledgeGraph` objects
  - `get_partition_for_entity(entity_id)` — locate which partition holds an entity
  - `to_merged_graph()` — re-merge all partitions into a single graph
  - `get_partition_stats()` — per-partition node/edge counts
  - **`rebalance(strategy)`** (session 4): returns a new `DistributedGraph` with nodes
    redistributed using *strategy* (default `ROUND_ROBIN` for perfect balance); does not
    mutate the original
- `FederatedQueryExecutor(dist_graph)` — fan-out Cypher query execution
  - `execute_cypher(query)` — serial fan-out, merge + deduplicate
  - `execute_cypher_parallel(query, max_workers)` — thread-pool fan-out
  - **`execute_cypher_async(query)`** (session 3) — asyncio-native wrapper
  - **`lookup_entity(entity_id)`** (session 3) — cross-partition O(partitions) entity lookup
  - **`lookup_entity_partition(entity_id)`** (session 3) — returns partition index or None
  - **`explain_query(query)`** (session 4): returns a `QueryPlan` with per-partition node/edge
    counts and estimated result rows; no actual execution
  - **`execute_cypher_streaming(query)`** (session 4): generator yielding
    `(partition_idx, record_dict)` tuples lazily; deduplication still applied across the stream
  - Each partition gets its own in-memory `GraphEngine` populated from partition nodes/rels
  - Deduplication uses SHA1 fingerprint of serialised record dicts
- New dataclasses: `QueryPlan`, `PartitionQueryPlan` (exported from `query/__init__.py`)

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.query.distributed import (
    GraphPartitioner, FederatedQueryExecutor, PartitionStrategy,
)

dist = GraphPartitioner(num_partitions=4, strategy=PartitionStrategy.HASH).partition(kg)
executor = FederatedQueryExecutor(dist)

# Synchronous fan-out
result = executor.execute_cypher("MATCH (n:Person) WHERE n.age > 30 RETURN n.name, n.age")

# Async fan-out
import asyncio
result = asyncio.run(executor.execute_cypher_async("MATCH (n:Person) RETURN n"))

# Cross-partition entity lookup
entity = executor.lookup_entity(some_entity_id)

# Rebalance partitions (session 4)
balanced = dist.rebalance(PartitionStrategy.ROUND_ROBIN)

# Query plan without execution (session 4)
plan = executor.explain_query("MATCH (n:Person) RETURN n.name")
print(plan.to_dict())

# Streaming (session 4)
for partition_idx, record in executor.execute_cypher_streaming("MATCH (n) RETURN n.name"):
    print(partition_idx, record)
```

**Tests:** `tests/unit/knowledge_graphs/test_srl_ontology_distributed.py` (15 tests),
           `tests/unit/knowledge_graphs/test_srl_ontology_distributed_cont.py` (7 tests),
           `tests/unit/knowledge_graphs/test_deferred_session4.py` (13 distributed tests)

---

## P5: Delivered in v3.22.23 (formerly v4.0+ deferred)

### 14. Confidence Score Aggregation

**Status:** ✅ Implemented (v3.22.23 — 2026-02-22)
**Location:** `extraction/extractor.py` — `KnowledgeGraphExtractor.aggregate_confidence_scores()`,
             `KnowledgeGraphExtractor.compute_extraction_quality_metrics()`
**Implementation:**
- `aggregate_confidence_scores(scores, method='mean', weights=None)` — combines per-source
  confidence scores using one of 6 strategies: `mean`, `min`, `max`, `harmonic_mean`,
  `weighted_mean`, `probabilistic_and`
- `compute_extraction_quality_metrics(kg)` — returns a 10-key metrics dict covering
  entity/relationship counts, density, average/std/low-confidence ratios, type diversity,
  and isolated entity ratio; no external dependencies required

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.extraction.extractor import KnowledgeGraphExtractor

# Aggregate multiple source confidences
scores = [0.9, 0.75, 0.85]
agg = KnowledgeGraphExtractor.aggregate_confidence_scores(scores)  # mean → 0.833
conservative = KnowledgeGraphExtractor.aggregate_confidence_scores(scores, method="probabilistic_and")  # 0.574

# Quality metrics for an extracted graph
metrics = KnowledgeGraphExtractor.compute_extraction_quality_metrics(kg)
print(metrics["relationship_density"])    # rels / entities
print(metrics["low_confidence_ratio"])    # fraction with confidence < 0.5
```

**Tests:** `tests/unit/knowledge_graphs/test_master_status_session69.py`

---

### 15. Migration Progress Tracking

**Status:** ✅ Implemented (v3.22.23 — 2026-02-22)
**Location:** `migration/formats.py` — `GraphData.export_streaming(progress_callback=...)`
**Implementation:**
- New optional `progress_callback: Callable[[int, int, int, int], None]` parameter added to
  `GraphData.export_streaming()`
- Callback signature: `(nodes_written, total_nodes, rels_written, total_rels)`
- Called after each node chunk and each relationship chunk
- Enables progress bars, logging, and resumable-migration checkpoints
- Fully backward-compatible: existing callers without `progress_callback` are unaffected

**Example (now works):**
```python
def on_progress(nw, nt, rw, rt):
    pct = ((nw + rw) / (nt + rt) * 100) if (nt + rt) else 0
    print(f"  {pct:.1f}%  nodes {nw}/{nt}  rels {rw}/{rt}")

nodes_written, rels_written = graph.export_streaming(
    "large_graph.jsonl",
    chunk_size=1000,
    progress_callback=on_progress,
)
```

**Tests:** `tests/unit/knowledge_graphs/test_master_status_session69.py`

---

### 16. Graph Diff/Patch

**Status:** ✅ Implemented (v3.22.24 — 2026-02-22)
**Location:** `extraction/graph.py` — `KnowledgeGraphDiff`, `KnowledgeGraph.diff()`,
             `KnowledgeGraph.apply_diff()`
**Implementation:**
- `KnowledgeGraphDiff` dataclass (`added_entities`, `removed_entity_ids`,
  `added_relationships`, `removed_relationship_ids`, `modified_entities`);
  `is_empty` property; `summary()`, `to_dict()`, `from_dict()` methods
- `KnowledgeGraph.diff(other)` — computes structural diff; entities matched by
  (entity_type, name) fingerprint; relationships matched by
  (relationship_type, source_fingerprint, target_fingerprint)
- `KnowledgeGraph.apply_diff(diff)` — applies diff in-place: cascade-removes
  entities (with their relationships), removes standalone relationships, adds
  new entities, applies property modifications, adds new relationships

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph, KnowledgeGraphDiff

diff = original_kg.diff(updated_kg)
if not diff.is_empty:
    print(diff.summary())          # "+1 entities, -0 entities, +2 rels, ..."
    d = diff.to_dict()             # serialize to JSON-safe dict
    restored = KnowledgeGraphDiff.from_dict(d)  # round-trip
    original_kg.apply_diff(diff)   # transform original into updated in-place
```

**Tests:** `tests/unit/knowledge_graphs/test_master_status_session70.py`

---

## P6: Delivered in v3.22.25 (formerly v4.0+ "Real-time streaming" and "Temporal graph databases")

### 17. Graph Event Subscriptions

**Status:** ✅ Implemented (v3.22.25 — 2026-02-22)
**Location:** `extraction/graph.py` — `GraphEventType`, `GraphEvent`,
             `KnowledgeGraph.subscribe()`, `KnowledgeGraph.unsubscribe()`,
             `KnowledgeGraph._emit_event()`
**Implementation:**
- `GraphEventType(str, Enum)` with 5 event types: `entity_added`, `entity_removed`,
  `entity_modified`, `relationship_added`, `relationship_removed`
- `GraphEvent` dataclass: `event_type`, `timestamp`, `entity_id`, `relationship_id`, `data`
- `KnowledgeGraph.subscribe(callback) -> int` — registers observer, returns handler ID
- `KnowledgeGraph.unsubscribe(handler_id) -> bool` — removes observer (returns True/False)
- `KnowledgeGraph._emit_event(event)` — fan-out to all subscribers; exceptions in subscribers
  are silently suppressed so a faulty subscriber never disrupts graph operations
- Wired into `add_entity()`, `add_relationship()`, and `apply_diff()` (all five event types)
- Fully backward-compatible: subscribers default to empty dict; no performance overhead
  when no subscribers are registered

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph, GraphEventType

events = []
kg = KnowledgeGraph("example")
hid = kg.subscribe(events.append)

e1 = kg.add_entity("person", "Alice")   # fires ENTITY_ADDED
e2 = kg.add_entity("person", "Bob")    # fires ENTITY_ADDED
kg.add_relationship("knows", e1, e2)   # fires RELATIONSHIP_ADDED

assert events[0].event_type == GraphEventType.ENTITY_ADDED
assert events[0].entity_id == e1.entity_id

kg.unsubscribe(hid)   # clean up
```

**Tests:** `tests/unit/knowledge_graphs/test_master_status_session71.py`

---

### 18. KnowledgeGraph Named Snapshots

**Status:** ✅ Implemented (v3.22.25 — 2026-02-22)
**Location:** `extraction/graph.py` — `KnowledgeGraph.snapshot()`,
             `KnowledgeGraph.get_snapshot()`, `KnowledgeGraph.list_snapshots()`,
             `KnowledgeGraph.restore_snapshot()`
**Implementation:**
- `snapshot(name=None) -> str` — serializes current entities+relationships to a named
  snapshot dict; auto-generates a `snap_<8-char-uuid>` name when none provided; returns name
- `get_snapshot(name) -> Optional[Dict]` — returns a shallow copy of the snapshot payload
  (`{"entities": [...], "relationships": [...]}`); `None` if not found
- `list_snapshots() -> List[str]` — sorted list of all stored snapshot names
- `restore_snapshot(name) -> bool` — fully rebuilds entities, relationships, and all four
  index dicts from the stored snapshot; returns `False` when name is unknown; event
  subscribers are NOT notified during restore (atomic state replacement)

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph

kg = KnowledgeGraph("versioned")
kg.add_entity("person", "Alice")
snap = kg.snapshot("before_merge")   # "before_merge"

kg.add_entity("org", "Acme Corp")
assert len(kg.entities) == 2

kg.restore_snapshot("before_merge")  # reverts addition
assert len(kg.entities) == 1
assert kg.list_snapshots() == ["before_merge"]
```

**Tests:** `tests/unit/knowledge_graphs/test_master_status_session71.py`

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

## P7: Delivered in v3.22.26 (formerly v4.0+ "GraphQL API support")

### 19. GraphQL API Support

**Status:** ✅ Implemented (v3.22.26 — 2026-02-23)
**Location:** `query/graphql.py` — `GraphQLParser`, `KnowledgeGraphQLExecutor`,
             `GraphQLDocument`, `GraphQLField`, `GraphQLParseError`
**Implementation:**
- `GraphQLParser` — recursive-descent parser for a practical GraphQL subset
  (entity queries, argument filters, field projection, nested relationships,
  aliases, float/int/bool/null/string argument values)
- `GraphQLDocument` / `GraphQLField` — lightweight AST nodes
- `GraphQLParseError(ValueError)` — clear error type for parse failures
- `KnowledgeGraphQLExecutor(kg)` — executes GraphQL against a `KnowledgeGraph`;
  response follows the GraphQL-over-HTTP envelope `{"data": {...}}`
  - Entity selection by type (top-level field name = entity type)
  - Argument equality filters: `id`, `name`, `type`, or any property
  - Field projection: `id / entity_id`, `type / entity_type`, `name`,
    `confidence`, arbitrary `entity.properties` keys
  - Relationship traversal: nested field name = outgoing relationship type
  - Aliases: `myAlias: entityType { ... }`
  - Errors captured in `"errors"` key; never throws
- All symbols exported from `query/__init__.py` and `query.__all__`

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
from ipfs_datasets_py.knowledge_graphs.query import KnowledgeGraphQLExecutor

kg = KnowledgeGraph("example")
alice = kg.add_entity("person", "Alice", {"age": 30, "city": "NYC"})
bob   = kg.add_entity("person", "Bob",   {"age": 25})
kg.add_relationship("knows", alice, bob)

exe = KnowledgeGraphQLExecutor(kg)
result = exe.execute('''
{
    person(name: "Alice") {
        id
        name
        age
        city
        knows { name age }
    }
}
''')
# {"data": {"person": [{"id": "...", "name": "Alice", "age": 30, "city": "NYC",
#           "knows": [{"name": "Bob", "age": 25}]}]}}

# Parse error → clean response envelope (no exception raised)
err = exe.execute("{ unclosed {")
# {"data": None, "errors": [{"message": "Unexpected EOF inside selection set"}]}
```

**Tests:** `tests/unit/knowledge_graphs/test_master_status_session72.py`

---

## P8: Delivered in v3.22.27 (formerly v4.0+ "Advanced visualization tools")

### 20. Advanced Visualization Tools

**Status:** ✅ Implemented (v3.22.27 — 2026-02-23)
**Location:** `extraction/visualization.py` — `KnowledgeGraphVisualizer`

**Implementation:**
- `KnowledgeGraphVisualizer(kg)` — pure-Python visualization exporter (no external
  dependencies) for :class:`KnowledgeGraph` objects; four output formats:
  - `to_dot(graph_name=None, directed=True) → str` — Graphviz DOT language
    (``digraph`` / ``graph``; entity nodes as ellipses; relationship edges with labels)
  - `to_mermaid(direction="LR", max_entities=None) → str` — Mermaid.js graph
    notation compatible with GitHub Markdown, Notion, GitLab, Obsidian, and mermaid.live
  - `to_d3_json(max_nodes=None) → dict` — D3.js force-directed graph JSON
    (``{"nodes": [...], "links": [...]}``) ready for ``d3-force`` layouts
  - `to_ascii(root_entity_id=None, max_depth=3) → str` — human-readable ASCII
    tree; rooted DFS when *root_entity_id* given; flat entity roster otherwise
- Internal helpers: `_escape_dot_label(text)`, `_escape_mermaid(text)` (not exported)
- **Convenience methods** added to `KnowledgeGraph` (lazy-import, no circular deps):
  `to_dot(**kw)`, `to_mermaid(**kw)`, `to_d3_json(**kw)`, `to_ascii(**kw)`
- `KnowledgeGraphVisualizer` exported from `extraction/__init__.py` and `__all__`

**Example (now works):**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraph,
    KnowledgeGraphVisualizer,
)

kg = KnowledgeGraph("social")
alice = kg.add_entity("person", "Alice", {"age": 30})
bob   = kg.add_entity("person", "Bob",   {"age": 25})
acme  = kg.add_entity("org",    "Acme Corp")
kg.add_relationship("knows",    alice, bob)
kg.add_relationship("works_at", bob,   acme)

vis = KnowledgeGraphVisualizer(kg)

# --- Graphviz DOT (pipe to: dot -Tpng graph.dot -o graph.png) ---
print(vis.to_dot())
# digraph "social" {
#   rankdir=LR;
#   node [shape=ellipse fontname=Helvetica];
#   "..." [label="Alice\n(person)"];
#   "..." [label="Bob\n(person)"];
#   "..." [label="Acme Corp\n(org)"];
#   "..." -> "..." [label="knows"];
#   "..." -> "..." [label="works_at"];
# }

# --- Mermaid.js (embed in ```mermaid ``` fenced code block) ---
print(vis.to_mermaid())
# graph LR
#   e1["Alice\n(person)"]
#   e2["Bob\n(person)"]
#   e3["Acme Corp\n(org)"]
#   e1 -->|"knows"| e2
#   e2 -->|"works_at"| e3

# --- ASCII tree ---
print(vis.to_ascii())
# social (3 entities, 2 relationships)
# ├─ Alice (person)
# │  └─[knows]→ Bob
# ├─ Bob (person)
# │  └─[works_at]→ Acme Corp
# └─ Acme Corp (org)

# --- D3.js JSON ---
import json
d3_data = vis.to_d3_json()
print(json.dumps(d3_data, indent=2))
# {"nodes": [{"id": "...", "name": "Alice", "type": "person", ...}, ...],
#  "links": [{"source": "...", "target": "...", "type": "knows", ...}, ...]}

# --- Convenience methods on KnowledgeGraph ---
dot_src = kg.to_dot(directed=False)   # undirected graph { ... -- ... }
mermaid_tb = kg.to_mermaid(direction="TB")
ascii_rooted = kg.to_ascii(root_entity_id=alice.entity_id, max_depth=2)
d3_limited = kg.to_d3_json(max_nodes=2)
```

**Tests:** `tests/unit/knowledge_graphs/test_master_status_session73.py`

---

## P9: Delivered in v3.22.28 (formerly v4.0+ "Federated knowledge graphs")

### 21. Federated Knowledge Graphs

**Status:** ✅ Implemented (v3.22.28 — 2026-02-23)

Multi-graph federation with cross-graph entity resolution, unified query
execution, and property-merging graph consolidation.

**New module:** `query/federation.py`

**New classes:**

| Class | Description |
|-------|-------------|
| `FederatedKnowledgeGraph` | Registry of independent KG instances with federation operations |
| `EntityResolutionStrategy` | Enum: `EXACT_NAME` / `TYPE_AND_NAME` / `PROPERTY_MATCH` |
| `EntityMatch` | Dataclass representing a matched entity pair across two graphs |
| `FederationQueryResult` | Aggregated result from `execute_across()` |

**Usage:**
```python
from ipfs_datasets_py.knowledge_graphs.query.federation import (
    FederatedKnowledgeGraph, EntityResolutionStrategy
)
from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

# Build two independent graphs
kg_hr = KnowledgeGraph(name="hr")
alice_hr = kg_hr.add_entity("person", "Alice", properties={"dept": "eng"})
bob = kg_hr.add_entity("person", "Bob")
kg_hr.add_relationship("manages", alice_hr, bob)

kg_crm = KnowledgeGraph(name="crm")
alice_crm = kg_crm.add_entity("person", "Alice", properties={"region": "west"})
acme = kg_crm.add_entity("company", "Acme")
kg_crm.add_relationship("works_at", alice_crm, acme)

# Register with federation
fed = FederatedKnowledgeGraph()
fed.add_graph(kg_hr, name="hr")
fed.add_graph(kg_crm, name="crm")

# Cross-graph entity resolution
matches = fed.resolve_entities(EntityResolutionStrategy.TYPE_AND_NAME)
# [EntityMatch(entity_a_id=..., entity_b_id=..., kg_a_index=0, kg_b_index=1, score=1.0)]

# Find entity across all graphs
hits = fed.query_entity(name="Alice")
# [(0, <alice_hr Entity>), (1, <alice_crm Entity>)]

# Get all occurrences by fingerprint
cluster = fed.get_entity_cluster("person:alice")
# [(0, <alice_hr entity_id>), (1, <alice_crm entity_id>)]

# Run a query function across all graphs
result = fed.execute_across(lambda kg: kg.get_entities_by_type("person"))
# result.per_graph_results: {0: [<alice_hr>, <bob>], 1: [<alice_crm>]}
# result.total_matches: 3

# Merge all graphs (Alice deduplicated, properties merged)
merged = fed.to_merged_graph()
# merged.entities: 3 (Alice w/ dept+region, Bob, Acme)
# merged.relationships: 2 (manages, works_at)
alice_merged = merged.get_entities_by_name("Alice")[0]
# alice_merged.properties: {'dept': 'eng', 'region': 'west'}  (both merged)
```

**Tests:** `tests/unit/knowledge_graphs/test_master_status_session74.py`

---

## See Also

- [ROADMAP.md](ROADMAP.md) - Complete development timeline
- [MASTER_STATUS.md](./MASTER_STATUS.md) - Current status (single source of truth)
- [COMPREHENSIVE_ANALYSIS_2026_02_18.md](./COMPREHENSIVE_ANALYSIS_2026_02_18.md) - Comprehensive analysis
- [IMPROVEMENT_TODO.md](./IMPROVEMENT_TODO.md) - Infinite improvement backlog

---

**Last Updated:** 2026-02-23 (session 74)
**Next Review:** Q3 2026
**Maintainer:** Knowledge Graphs Team

