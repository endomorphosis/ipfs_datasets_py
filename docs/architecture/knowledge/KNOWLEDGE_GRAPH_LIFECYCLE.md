# Knowledge graph lifecycle and authority model

| Field | Value |
| --- | --- |
| Interface | `KnowledgeGraphLifecycle@1` |
| Task | `IPFSDOC-031` |
| Status | `canonical` |
| Owner | architecture / knowledge-graphs domain |
| Source of truth | `ipfs_datasets_py/knowledge_graphs/` (extraction, core, storage, transactions, indexing, lineage, jsonld, cypher, query, reasoning, ontology, neo4j_compat, migration); `ipfs_datasets_py/core_operations/knowledge_graph_manager.py`; [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related ADRs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Review cadence | after graph engine, storage backend, extraction, or Neo4j-compat API changes |

> **Sibling guides:** Content identity and CID profiles →
> [CONTENT_ADDRESSING_AND_IPLD.md](../storage/CONTENT_ADDRESSING_AND_IPLD.md).
> Embeddings and vector indexes →
> [EMBEDDINGS_AND_INDEXING.md](../retrieval/EMBEDDINGS_AND_INDEXING.md).
> Search and hybrid retrieval →
> [SEARCH_AND_QUERY.md](../retrieval/SEARCH_AND_QUERY.md).
> End-to-end product flows →
> [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md).
> GraphRAG orchestration and optimizer control loops → planned
> `GRAPHRAG.md` / `OPTIMIZATION_LOOPS.md` (IPFSDOC-032).
> Domain ownership → [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.5.

## 1. Purpose

This guide answers: **how extraction candidates become (or do not become)
authoritative graph facts**, and which artifact kinds exist at each stage of
the knowledge-graph lifecycle in `ipfs_datasets_py`.

It traces a candidate from source text through model/core representation,
validation, transaction/storage/indexing, lineage/provenance, query surfaces
(JSON-LD, Cypher, SPARQL), reasoning, Neo4j compatibility, and migration—and
labels every major product as one of:

| Artifact kind | Authority |
| --- | --- |
| **Source evidence** | Observed input (text, document bytes, external KB hit); not yet a graph fact |
| **Persisted graph fact** | Committed node/edge (or entity/relationship) with durable identity in storage |
| **Index** | Derived lookup structure; rebuildable; never primary truth |
| **Inferred result** | Materialized or ephemeral reasoning output; subordinate to base facts + ontology |
| **Compatibility view** | Adapter projection (Neo4j driver API, JSON-LD/RDF export, migration payload) over the same facts |

Callers, agents, and docs **must not** promote extraction confidence, index
hits, SPARQL validation reports, ontology inferences, or Cypher result rows to
proof, policy, or authorization authority
([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)).

## 2. Audience

- **Primary:** architects and developers implementing or reviewing graph
  extraction, persistence, query, and Neo4j-compat paths.
- **Secondary:** agents wiring MCP graph tools; operators diagnosing optional
  Neo4j/IPFS/SPARQL dependency failures.

## 3. Scope and non-goals

### In scope

- Lifecycle of candidates from extraction through persistence and query.
- Core model types (`Entity`, `Relationship`, `KnowledgeGraph`, `Node`,
  engine records) and their roles.
- Validation (local thresholds, SPARQL/Wikidata checks, constraints).
- Transactions (WAL), IPLD storage, and index managers.
- Lineage and provenance chains (including CID-linked events).
- Query surfaces: Cypher pipeline, SPARQL templates, JSON-LD/RDF, unified
  and hybrid query engines.
- Reasoning (cross-document helpers, OWL/RDFS ontology materialization).
- Neo4j-compatible driver/session/result surface.
- Migration import/export between Neo4j and IPFS graph formats.
- Authority classification of artifacts at each hop.

### Non-goals

- GraphRAG planner loops, critic scores, and optimizer product contracts →
  IPFSDOC-032 (`GRAPHRAG.md`, `OPTIMIZATION_LOOPS.md`).
- Formal IR proof, admissibility, and authorization gates →
  [logic architecture](../logic/IR_FAMILY_AND_IDENTITY.md) and Flow D in
  [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md).
- Vector ANN backend matrices →
  [VECTOR_STORES.md](../retrieval/VECTOR_STORES.md).
- Content-addressing codec profiles in full →
  [CONTENT_ADDRESSING_AND_IPLD.md](../storage/CONTENT_ADDRESSING_AND_IPLD.md).
- Changing production graph code as part of this documentation task.

## 4. Context

Knowledge graphs in this package serve three product needs:

1. **Structured extraction** from text (and specialized pipelines such as
   finance GraphRAG) into entity/relationship candidates.
2. **Content-addressed persistence** of graph state via IPLD (`CID` blocks),
   with optional Neo4j-compatible access for existing Cypher clients.
3. **Query and light reasoning** for retrieval and analysis—not formal proof.

Domain ownership is fixed in [DOMAIN_MAP.md](../DOMAIN_MAP.md): package
`ipfs_datasets_py.knowledge_graphs` owns the graph data plane; `optimizers`
owns closed-loop GraphRAG product loops; `logic` owns formal compilers and
admissibility. The package is also listed in the logic submodule registry only
as a **cross-package endpoint**, not as ownership of Neo4j itself.

Two representation families coexist and must not be collapsed:

| Family | Types | Typical owners |
| --- | --- | --- |
| **Extraction / analysis model** | `extraction.Entity`, `extraction.Relationship`, `extraction.KnowledgeGraph` | Extractors, validators, ontology reasoner input/output |
| **Engine / Neo4j-compat model** | `neo4j_compat.Node`, `neo4j_compat.Relationship`, `storage.Entity`, `storage.Relationship` | `GraphEngine`, `IPLDBackend`, driver/session, transactions |

`storage.Entity` / `storage.Relationship` bridge IPLD persistence and Neo4j
shapes. Extraction types carry `confidence` and `source_text`; engine nodes
carry labels/properties. Promotion from extraction candidate to engine fact is
an **explicit write** (transaction or manager API), not an automatic upgrade.

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Extraction pipelines and candidate KG containers | Optimizer generate/critique/optimize loops (`optimizers`) |
| Graph engine CRUD, IR query execution, indexes | ANN vector store backends (`vector_stores`) |
| WAL transactions and IPLD graph block storage | Pin lifecycle / cluster consensus (storage routers) |
| Lineage types and provenance event chains for graph mutations | Formal proof envelopes / admissibility (`logic`) |
| Cypher lexer/parser/compiler; SPARQL *templates* and federation hooks | Wikidata/SPARQL remote endpoint operations (external) |
| Neo4j-compatible driver/session/result API over IPFS | Deployed Neo4j server product |
| Migration formats, schema check, integrity verify | Source-document OCR/ingest (`processors`) |

**Inbound callers:** Python domain code; MCP `graph_tools` (via
`KnowledgeGraphManager`); CLI graph commands; processors / file-converter /
PDF tools that extract or query graphs; logic frame/legal projections;
optional optimizers and hybrid search.

**Outbound dependencies:** `ipfs_backend_router` / IPLD block put-get;
optional spaCy / transformers for extraction; optional Neo4j client for
export/import; optional SPARQL endpoints for validation; vector/search for
hybrid retrieval.

**Authority notes:** Graph facts are **structured claims with persistence
identity**, not proofs. A `CID` on a node block or provenance event identifies
bytes, not semantic truth
([ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)).
Extraction confidence and ontology materialization remain at the **retrieval /
model candidates** or **validation** layers of
[ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)—never policy or
authorization.

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| Package surface | `knowledge_graphs/__init__.py` | Stable exceptions; deprecated root re-exports (prefer subpackages) |
| Extraction types | `extraction/entities.py`, `relationships.py`, `types.py` | Candidate entity/relationship model with confidence |
| Extraction graph | `extraction/graph.py` | In-memory `KnowledgeGraph` container + type indexes + events |
| Extractor | `extraction/extractor.py` | Rule / spaCy / transformers extraction from text |
| Validation extractor | `extraction/validator.py` | SPARQL/Wikidata validation wrapper around base extractor |
| Provenance chain | `extraction/provenance.py` | Append-only mutation events linked by CID |
| Advanced / finance / SRL | `extraction/advanced.py`, `finance_graphrag.py`, `srl.py` | Specialized extraction paths |
| Graph engine | `core/graph_engine.py` | Node/relationship CRUD; optional IPLD persist |
| Query / IR executors | `core/query_executor.py`, `ir_executor.py`, `expression_evaluator.py` | Cypher/IR execution against engine |
| Core types | `core/types.py` | `CID`, `NodeRecord`, `RelationshipRecord`, `StorageBackend` protocol |
| IPLD backend | `storage/ipld_backend.py` | Content-addressed store; LRU cache; graph store/retrieve |
| Storage entity model | `storage/types.py` | `Entity` / `Relationship` with optional `cid` field |
| Transactions + WAL | `transactions/manager.py`, `wal.py`, `types.py` | ACID-style begin/commit/rollback; WAL durability |
| Index manager | `indexing/manager.py`, `btree.py`, `specialized.py` | Label/property/composite/full-text/spatial/vector indexes |
| Constraints | `constraints/` | Graph constraint definitions |
| Lineage | `lineage/` | `LineageNode` / `LineageLink`; cross-document lineage |
| JSON-LD | `jsonld/` | Context, translator, RDF serializer, validation |
| Cypher stack | `cypher/` | Lexer, parser, AST, compiler, functions |
| Query engines | `query/` | Unified engine, hybrid search, SPARQL templates, federation, GNN hooks |
| Reasoning | `reasoning/`, `ontology/reasoning.py` | Cross-document reasoning types; OWL/RDFS materialization |
| Neo4j compat | `neo4j_compat/` | `GraphDatabase`, driver, session, result, legal IR projection |
| Migration | `migration/` | Neo4j exporter, IPFS importer, schema checker, integrity verifier |
| Facade manager | `core_operations/knowledge_graph_manager.py` | Async CRUD/query/tx/index API for MCP/CLI |
| Legacy IPLD KG | `ipld.py` | **Deprecated** — use `storage/ipld_backend.py` + neo4j_compat |

```text
Source evidence (text / docs / external KB)
        |
        v
  extraction candidates  ---- validation reports (non-facts)
        |
        v
  extraction.KnowledgeGraph  (analysis model; optional provenance chain)
        |
        +----> ontology/reasoning materialize  -->  inferred results
        |
        v
  explicit commit / manager write
        |
        v
  GraphEngine + TransactionManager + WAL
        |
        +----> IPLDBackend (CID blocks)     = persisted graph facts
        +----> IndexManager                = indexes (derived)
        |
        +----> lineage / provenance links  = evidence about facts
        |
        v
  query: Cypher | SPARQL templates | hybrid | JSON-LD export
        |
        +----> neo4j_compat session/result = compatibility view
        +----> migration payloads          = compatibility view
```

## 7. End-to-end lifecycle

### 7.1 Happy path (candidate to durable fact to query)

1. **Ingest source evidence** — raw text, Wikipedia page body, PDF-derived
   chunks, or finance documents. Identity of the *source* is document/chunk
   IDs and/or content CIDs owned by processors/storage—not yet graph node IDs.
2. **Extract candidates** — `KnowledgeGraphExtractor.extract_knowledge_graph`
   (or advanced/SRL/finance extractors) produces `Entity` / `Relationship`
   objects with `confidence` and optional `source_text`, collected in
   `extraction.KnowledgeGraph`.
3. **Validate (optional)** — local min-confidence filter; optional
   `KnowledgeGraphExtractorWithValidation` SPARQL checks against Wikidata;
   optional constraint checks. Validation reports adjust confidence or
   suggest corrections; they are **not** persisted graph facts by themselves.
4. **Optional analysis lineage** — extraction graph may enable
   `ProvenanceChain` (CID-linked mutation events) and/or
   `lineage` cross-document nodes/links for audit.
5. **Promote to engine** — callers write accepted entities/relationships via
   `GraphEngine.create_node` / `create_relationship`,
   `TransactionManager` operations, `KnowledgeGraphManager.add_entity` /
   `add_relationship`, or Neo4j-compat session Cypher `CREATE`/`MERGE`.
6. **Transaction commit** — WAL records operations; commit materializes
   durable state. Uncommitted ops are not facts for other readers.
7. **Storage** — with `IPLDBackend`, node/edge payloads are stored as
   content-addressed blocks; a **CID** is returned and may be cached against
   engine ids. Without a backend, the engine is **in-memory only**.
8. **Indexing** — `IndexManager` (and MCP `graph_index_create`) maintains
   derived indexes for labels, properties, full-text, spatial, or vector
   sides. Indexes accelerate query; they do not redefine truth.
9. **Query** — Cypher (lexer→parser→compiler→IR→executor), SPARQL templates /
   federation hooks, hybrid graph+vector search, or JSON-LD/RDF export.
10. **Reasoning (optional)** — `OntologyReasoner.materialize` adds inferred
    types/edges to a **copy** of a KG; cross-document reasoning builds
    relation graphs over documents. Inferred results remain labeled inferred.
11. **Compatibility / migration** — Neo4j driver API and migration
    export/import expose the same facts in foreign formats; they do not create
    a second authority store unless explicitly written back.

### 7.2 Lifecycle hop table

| Hop | Inputs | Outputs | Artifact kind | Owner module |
| --- | --- | --- | --- | --- |
| H1 Source | Document bytes, text, URLs | Source text + ids | **Source evidence** | processors / caller |
| H2 Extraction | Text, patterns, optional models | Entity/relationship candidates | **Source evidence → candidate** (not fact) | `extraction/` |
| H3 Local filter | Candidates, `min_confidence` | Filtered candidate set | still candidates | `extraction/extractor.py` |
| H4 External validation | Candidates, SPARQL endpoint | Validation report, adjusted confidence | validation report (ADR-003 validation layer) | `extraction/validator.py` |
| H5 Analysis KG | Candidates | `extraction.KnowledgeGraph` | analysis container (not engine fact) | `extraction/graph.py` |
| H6 Provenance enable | KG mutations | `ProvenanceEvent` chain with **CID** links | evidence / receipts about mutations | `extraction/provenance.py` |
| H7 Lineage record | Entity/doc ids, transforms | `LineageNode` / `LineageLink` | provenance graph (meta) | `lineage/` |
| H8 Tx begin | Engine + storage | `Transaction` | staging | `transactions/` |
| H9 Engine write | Labels, properties, rel types | `Node` / engine `Relationship` | staged fact | `core/graph_engine.py` |
| H10 Commit + WAL | Staged ops | Durable engine state + WAL head **CID** | **Persisted graph facts** | `transactions/`, `storage/` |
| H11 IPLD store | Node/edge JSON | Block **CID** | content identity of payload | `storage/ipld_backend.py` |
| H12 Index update | Facts | Property/label/… indexes | **Index** | `indexing/` |
| H13 Cypher/SPARQL/hybrid query | Query string / params | Rows / hybrid hits | query results (not new facts unless write) | `cypher/`, `query/`, `core/` |
| H14 JSON-LD/RDF | Graph facts | JSON-LD / RDF serialization | **Compatibility view** | `jsonld/` |
| H15 Ontology materialize | Base KG + schema | Augmented KG copy | **Inferred results** | `ontology/reasoning.py` |
| H16 Cross-doc reasoning | Docs + entities | `CrossDocReasoning` graph | **Inferred results** | `reasoning/` |
| H17 Neo4j-compat | Same engine/storage | Driver/session/result | **Compatibility view** | `neo4j_compat/` |
| H18 Migration | Neo4j or file graph | Import/export + integrity report | **Compatibility view** (+ facts if imported) | `migration/` |

### 7.3 Sequence diagram

```text
Caller / MCP graph_tools / CLI
  |  extract / add_entity / session.run(Cypher)
  v
KnowledgeGraphManager  (optional facade)
  |
  +-- extraction.KnowledgeGraphExtractor --> candidates (evidence-derived)
  |         |
  |         +-- optional SPARQLValidator --> validation report
  |         +-- optional ProvenanceChain  --> CID-linked events
  |
  +-- neo4j_compat.GraphDatabase.driver("ipfs://...")
  |         |
  |         v
  |    IPFSSession / IPFSTransaction
  |         |
  |         v
  +-- core.GraphEngine <--> transactions.TransactionManager
  |         |                        |
  |         |                        +--> WAL (CID head)
  |         v
  |    storage.IPLDBackend.store / retrieve  --> CID blocks
  |         |
  |         +--> indexing.IndexManager
  |
  +-- query: cypher compiler | UnifiedQueryEngine | hybrid_search
  |         |
  |         v
  |    Result / hybrid hits / SPARQL template expansion
  |
  +-- optional OntologyReasoner.materialize  --> inferred KG copy
  +-- optional migration export/import       --> foreign format view
```

### 7.4 Initialization and lifecycle

| Mode | Construction | Persistence |
| --- | --- | --- |
| Analysis-only | `KnowledgeGraphExtractor()` / `KnowledgeGraph(name=…)` | In-process dicts; optional provenance JSONL |
| Engine in-memory | `GraphEngine()` without backend | Process memory only |
| Engine + IPLD | `IPLDBackend` + `GraphEngine(storage_backend=…)` + optional `TransactionManager` | Content-addressed blocks via router |
| Neo4j-compat | `GraphDatabase.driver("ipfs://…")` | Session auto-commit or explicit tx |
| MCP/CLI | `KnowledgeGraphManager(driver_url=…).initialize()` | Same as Neo4j-compat path |

Shutdown: close driver/session; WAL recovery reloads from WAL head CID when
configured. Optional IPFS backends follow router/env flags
([DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md)).

## 8. Stage deep dives

### 8.1 Extraction (candidates)

**What it produces:** entities and relationships with types, names, properties,
`confidence` ∈ [0,1], and optional `source_text`.

**What it is not:** a commit to the engine, a proof that the entity exists in
the world, or authorization to act on the entity.

**Surfaces:**

- `extraction.KnowledgeGraphExtractor` — rule-based default; optional spaCy /
  transformers; Wikipedia mixin; temperature-style controls.
- `extraction.KnowledgeGraphExtractorWithValidation` — adds SPARQL validation.
- `extraction.advanced`, `srl`, `finance_graphrag` — domain pipelines.
- Root shims `knowledge_graph_extraction.py`, `advanced_knowledge_extractor.py`
  — prefer subpackage imports.

**Authority:** outputs sit at ADR-003 **retrieval / model candidates** until
an explicit write path promotes them.

### 8.2 Model and core representation

| Model | Module | Fields of note | Role |
| --- | --- | --- | --- |
| Extraction `Entity` | `extraction/entities.py` | type, name, confidence, source_text | Candidate |
| Extraction `Relationship` | `extraction/relationships.py` | type, endpoints, confidence | Candidate edge |
| Extraction `KnowledgeGraph` | `extraction/graph.py` | entities, relationships, type/name indexes | Analysis container; **analysis indexes** are not engine indexes |
| Storage `Entity` / `Relationship` | `storage/types.py` | id, type, properties, confidence, **cid** | Persistence-oriented graph objects |
| Neo4j `Node` / `Relationship` / `Path` | `neo4j_compat/types.py` | labels, properties, element ids | Engine / driver objects |
| Core records | `core/types.py` | `NodeRecord`, `RelationshipRecord`, **`CID`** alias | Export/WAL/API shapes |
| Lineage node/link | `lineage/types.py` | relationship_type, confidence, timestamps | Meta-graph of data flow |

**Invariant:** analysis indexes on `extraction.KnowledgeGraph` (by type/name)
are convenience structures over candidates. Engine `IndexManager` structures
are derived from **persisted** (or engine-resident) facts.

### 8.3 Validation

| Kind | Mechanism | Result kind |
| --- | --- | --- |
| Threshold filter | `min_confidence` on extractor | Dropped candidates remain non-facts |
| SPARQL / Wikidata | `SPARQLValidator` via validation extractor | Validation report; optional confidence rewrite |
| JSON-LD validation | `jsonld/validation.py` | Structural/context validity of exports |
| Graph constraints | `constraints/` | Constraint violations at write/query time |
| Schema (migration) | `migration/schema_checker.py` | Compatibility report between systems |
| Ontology consistency | `OntologyReasoner.check_consistency` | Disjoint / negative-property violations |

Validation success means **schema or external KB constraints hold under the
declared profile**—not theorem proof and not policy admission
([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) validation layer).

### 8.4 Transaction, storage, and indexing

**Transactions** (`transactions/manager.py`):

- Begin with isolation level; stage operations; commit or rollback.
- Write-ahead log (`wal.py`) for durability; WAL stats expose `head_cid`.
- Optimistic concurrency: write-write conflicts abort at commit.
- Uncommitted state is **not** a shared persisted graph fact.

**Storage** (`storage/ipld_backend.py`):

- Implements `StorageBackend` protocol (`store`, `retrieve`, `store_json`, …).
- Returns **CID** strings for stored payloads; optional pin via router.
- `LRUCache` is a **location/performance** cache, not identity
  ([ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)).
- `GraphEngine` may run without storage (memory-only); persistence failures
  log warnings and do not invent success CIDs.

**Indexing** (`indexing/`):

- Default label index; property, composite, full-text, spatial, vector,
  range indexes via `IndexManager`.
- MCP/CLI may create indexes through `KnowledgeGraphManager`.
- **Rebuildable derived artifacts**—if lost, rebuild from facts; never treat
  index presence as proof of a missing node.

### 8.5 Lineage and provenance

| Mechanism | Path | What it records |
| --- | --- | --- |
| Provenance chain | `extraction/provenance.py` | Mutation events (`entity_created`, …) with `previous_cid` / `cid` (SHA-256 content address) |
| Lineage core | `lineage/core.py`, `types.py` | `LineageNode` / `LineageLink` for datasets, transforms, entities |
| Cross-document lineage | `lineage/cross_document*.py` | Links across documents (enhanced variants) |
| Analytics provenance | `analytics` (product Flow B/C) | MERGE/TRANSFORM/QUERY records outside KG package |

**Authority:** lineage and provenance are **evidence about how graph state was
produced or transformed**. They bind history to digests where implemented; they
do not elevate extraction confidence to fact, and a provenance **CID** is not
a proof attestation ([ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)).

### 8.6 Query surfaces: JSON-LD, Cypher, SPARQL, hybrid

| Surface | Path | Input | Output kind |
| --- | --- | --- | --- |
| Cypher | `cypher/*` + `core/query_executor.py` | Cypher string | Result records; write queries may create facts |
| Unified engine | `query/unified_engine.py` | Query + budgets | Engine results under budget |
| Hybrid search | `query/hybrid_search.py` | Text + graph params | Ranked hybrid hits (**scores**, not proofs) |
| Semantic traversal | `query/semantic_traversal.py` | Embedding-guided beams | Path candidates |
| SPARQL templates | `query/sparql_templates.py`, root `sparql_query_templates.py` | Template + bindings | Expanded queries / remote results as **external evidence** when hit Wikidata |
| JSON-LD / RDF | `jsonld/translator.py`, `rdf_serializer.py` | Graph facts | Serialized **compatibility view** |
| GraphQL / GNN / ZKP hooks | `query/graphql.py`, `gnn.py`, `zkp.py`, `groth16_bridge.py` | Advanced adapters | Specialized views; ZKP bridges do not replace logic proof corpus |
| Facade query | `query_knowledge_graph.py`, MCP `query_knowledge_graph` | `query_type` + string | Tool-shaped payload |

**Read vs write:** Cypher `MATCH`/`RETURN` yields **query results**.
`CREATE`/`MERGE`/`DELETE` under a transaction yield **persisted graph facts**
only after successful commit. Hybrid and vector fusion remain ADR-003
**retrieval** products.

### 8.7 Reasoning

| Component | Path | Behavior | Artifact kind |
| --- | --- | --- | --- |
| Ontology reasoner | `ontology/reasoning.py` | RDFS/OWL-style rules (`subClassOf`, transitive, symmetric, inverseOf, domain/range); `materialize` returns augmented **copy** | **Inferred results** |
| Consistency check | same | Disjoint / negative property assertions | validation-style report |
| Cross-document reasoning | `reasoning/`, `cross_document_reasoning.py` | Entity-mediated document relations | **Inferred results** |
| Reasoning helpers | `reasoning/helpers.py`, `_reasoning_helpers.py` | Shared utilities | support only |

**Invariant:** materialization must not silently overwrite the authority of
base facts. Prefer inferred copies or explicitly labeled inferred edges.
Ontology inference is **not** formal prover authority (`logic`).

### 8.8 Neo4j compatibility

**Path:** `neo4j_compat/` — `GraphDatabase`, `IPFSDriver`, `IPFSSession`,
`IPFSTransaction`, `Result`, `Record`, graph types.

**Contract:** drop-in *API shape* for many Neo4j driver call sites, with URI
schemes such as `ipfs://` / `ipfs+embedded://` routing to IPLD-backed storage
instead of a Bolt Neo4j server.

**What it is:**

- A **compatibility view** and control plane over the package graph engine.
- Session auto-commit and explicit transaction APIs aligned with Neo4j habits.
- Optional `legal_ir_projection` helper for legal-IR triple projection.

**What it is not:**

- Ownership of the Neo4j product or guarantee of 100% Cypher parity with a
  given Neo4j server version.
- A second independent fact store with separate authority—facts remain in the
  engine/IPLD plane unless migration explicitly dual-writes.

Root imports of `GraphDatabase` from `knowledge_graphs` are **deprecated**
re-exports; prefer
`from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase`.

### 8.9 Migration

**Path:** `migration/` — `Neo4jExporter`, `IPFSImporter`, `SchemaChecker`,
`IntegrityVerifier`, format registry (`formats.py`).

| Step | Artifact |
| --- | --- |
| Export from Neo4j | File/JSON graph payload (**compatibility view** of external system) |
| Schema check | `CompatibilityReport` |
| Import into IPFS graph | On success, **persisted graph facts** in package storage |
| Integrity verify | `VerificationReport` (evidence about migration completeness) |

Migration never silently promotes incomplete imports to verified facts:
integrity verification is required for trust-bearing handoffs. Legacy
`knowledge_graphs/ipld.py` (`IPLDKnowledgeGraph`) is **deprecated**; new
storage work uses `storage/ipld_backend.py`.

## 9. Authority model (kinds of truth)

### 9.1 Classification matrix

| Artifact | Kind | May be treated as… | Must not be treated as… |
| --- | --- | --- | --- |
| Source document / chunk text | Source evidence | Extraction input | Graph fact |
| Extraction entity/relationship | Candidate | Input to validation/write | Persisted fact; proof |
| Confidence score | Candidate metadata | Ranking/filter signal | Truth probability certificate |
| SPARQL validation report | Validation result | Constraint evidence | Graph fact; authorization |
| `extraction.KnowledgeGraph` | Analysis container | Working set for reasoning/export | Shared durable store |
| Provenance event / lineage link | Evidence / receipt | Audit of mutation history | Semantic proof of content |
| Committed node/edge + CID block | **Persisted graph fact** | Durable structured claim under package storage | Formal theorem; policy allow |
| WAL head CID | Durability pointer | Recovery anchor | Content meaning |
| Label/property/vector index entry | **Index** | Query acceleration | Sole existence proof |
| Cypher/SPARQL read rows | Query results | Observations of current store/external KB | New facts without write |
| Hybrid search hit + score | Retrieval candidate | Ranking evidence | Proof or admission |
| Ontology-materialized edge/type | **Inferred result** | Derived under declared schema | Independent base fact |
| Cross-doc reasoning link | **Inferred result** | Analytical hypothesis | Court/policy finding |
| JSON-LD / RDF export | **Compatibility view** | Interchange serialization | Separate truth store |
| Neo4j driver Result | **Compatibility view** | API projection of engine results | External Neo4j cluster state (unless dual-written) |
| Migration export file | **Compatibility view** | Portable snapshot | Live authority after export drifts |
| Optimizer critic score (later guide) | Advisory | Loop control signal | Graph fact or proof |

### 9.2 Promotion rules

1. **Evidence → candidate** requires extraction (or manual construction).
2. **Candidate → persisted fact** requires an explicit write + successful
   transaction commit (or explicit engine create with defined persistence
   semantics).
3. **Fact → index** is automatic or operator-triggered maintenance; reversible
   by rebuild.
4. **Fact → inferred result** requires a declared reasoner/schema; keep base
   and inferred distinguishable.
5. **Fact → compatibility view** is projection-only unless the foreign system
   is written and then re-imported under migration integrity rules.
6. **No silent layer promotion** to proof, policy, or authorization
   ([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)).

### 9.3 Identity: engine id vs CID vs name

| Identifier | Scope | Notes |
| --- | --- | --- |
| Entity / node id (UUID or engine counter) | Graph element | Local structural identity |
| Relationship id | Graph element | Local structural identity |
| **CID** | Content-addressed block or provenance event | Identity of **bytes** under codec/hash profile |
| Entity `name` / labels | Human / type vocabulary | Not unique identity; collision-prone |
| Vector id / embedding model id | Retrieval | Orthogonal to graph element id |

Never equate “same name string” with “same CID” or “same node id.”

## 10. Contracts

### 10.1 Inputs

| Input | Type / source | Validation |
| --- | --- | --- |
| Source text / documents | str, processor chunks | Non-empty for extraction; encoding owned by caller |
| Extraction config | flags (`use_spacy`, `min_confidence`, …) | Thresholds; optional model availability |
| Cypher / query string | str | Parse errors → `QueryParseError` / tool error |
| Driver URL | e.g. `ipfs://…` | Router/backend availability |
| Migration file / Neo4j URI | path, bolt URI | Schema checker + credentials (ops) |

### 10.2 Outputs

| Output | Type / sink | Guarantees |
| --- | --- | --- |
| Candidate KG | `extraction.KnowledgeGraph` | In-memory structure; confidence metadata |
| Validation report | dict / structured | External KB may be stale or unavailable |
| Committed graph state | engine + optional IPLD | Durable only if backend + commit succeeded |
| Query Result | neo4j_compat `Result` / tool dict | Reflects store at execution time |
| Inferred KG | copy from reasoner | Must not be assumed equal to base store |
| Migration report | export/import/verify objects | Integrity report required for trust |

### 10.3 Public surfaces

- **Python API:** prefer subpackages —
  `knowledge_graphs.extraction`, `.core`, `.storage`, `.transactions`,
  `.indexing`, `.lineage`, `.jsonld`, `.cypher`, `.query`, `.reasoning`,
  `.ontology`, `.neo4j_compat`, `.migration`.
- **Facade:** `ipfs_datasets_py.core_operations.knowledge_graph_manager.KnowledgeGraphManager`.
- **MCP:** `graph_tools` (`graph_create`, `graph_add_entity`,
  `graph_add_relationship`, `graph_query_cypher`, `graph_search_hybrid`,
  `graph_transaction_*`, `graph_index_create`, `query_knowledge_graph`,
  provenance helpers); PDF/file-converter graph tools as thin wrappers.
- **CLI:** `ipfs-datasets graph …` family (create, entities, relationships,
  Cypher, hybrid search, tx, index) per
  [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md).
- **Extras:** packaging extra `knowledge_graphs`; optional NLP/Neo4j/IPFS deps
  per [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md).

### 10.4 Persistence and identity

- Preferred storage backend for new work: `storage/ipld_backend.py`.
- Deprecated: root `ipld.py` (`IPLDKnowledgeGraph`).
- CID construction and codec rules are owned by storage/content-addressing
  guides; this domain **consumes** CIDs as block and provenance identifiers.
- Index files and LRU caches are non-authoritative locations.

## 11. Failure modes and fallbacks

| Failure | Detection | Caller-visible behavior | Fallback |
| --- | --- | --- | --- |
| spaCy / transformers missing | import / flag | Rule-based extraction only | Degraded candidate quality; not silent “model success” |
| SPARQL endpoint down | network / HTTP errors | Validation disabled or partial report | Candidates unvalidated; do not invent “valid” |
| `IPLDBackend` / router missing | import / init | Engine memory-only or storage errors | No fake CIDs; fail or warn per path |
| Persist store fails mid-create | `StorageError` | Warning/error; node may exist only in cache | Caller must not assume durability |
| Tx conflict / abort | `ConflictError` / abort | Commit fails | Retry or surface error; no partial authority |
| Cypher parse error | lexer/parser | `QueryParseError` / Result error summary | No partial execution as success |
| Hybrid vector side down | backend error | Graph-only or error | Documented degradation; scores not proof |
| Neo4j export target down | driver errors | Migration export fails | No empty success export |
| Legacy `ipld` import | DeprecationWarning | Still works until removal | Prefer neo4j_compat + IPLDBackend |
| Ontology inconsistency | `check_consistency` | Violation list | Refuse silent materialization as clean |

Fail closed on durability and validation claims: missing optional capability is
**not** success with empty authority
([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

## 12. Extension points

1. **New extractor** — add under `extraction/`; return `Entity` /
   `Relationship` / `KnowledgeGraph`; wire optional MCP thin wrapper only.
2. **New index type** — implement in `indexing/specialized.py` (or sibling);
   register via `IndexManager`; document rebuild semantics.
3. **New query dialect adapter** — parse to existing IR operations when
   possible (`core/ir_executor.py`) rather than forking storage.
4. **New migration format** — `migration.formats.register_format` +
   schema/integrity hooks.
5. **Ontology rules** — extend `OntologySchema` / reasoner; keep inferred
   outputs labeled.
6. **Tests** — unit tests under `tests/` for extraction, engine, tx, query;
   do not rely on live Wikidata/Neo4j for hermetic CI unless gated.

**Anti-patterns:**

- Business logic inside MCP tool modules (use `KnowledgeGraphManager` /
  domain packages).
- Treating extraction confidence as commit authority.
- Writing optimizer scores into node properties as if they were facts without
  provenance labels.
- Importing deprecated `knowledge_graphs.ipld` in new code.
- Collapsing Neo4j server state and IPFS engine state without migration
  integrity.

## 13. Invariants

1. **Artifact kinds are non-interchangeable** — source evidence, candidates,
   persisted facts, indexes, inferred results, and compatibility views must
   remain distinguishable in APIs, logs, and docs.
2. **Promotion is explicit** — only commit/write paths create shared persisted
   facts from candidates.
3. **CID identifies content bytes** — never semantic correctness, ranking
   quality, or authorization.
4. **Indexes are derived** — loss of an index must not imply loss of facts if
   the fact store remains.
5. **Inferences are subordinate** — ontology and cross-document reasoning
   outputs do not replace base facts without an explicit merge policy.
6. **Neo4j compat is a view** — API compatibility does not invent a second
   authority unless dual-written and verified.
7. **Validation ≠ proof ≠ authorization** — layered authority
   ([ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)) applies end-to-end.
8. **Prefer subpackage imports** — root re-exports are compatibility shims.
9. **Fail closed on durability claims** — memory-only engines and failed
   persists must not report durable CID success.
10. **GraphRAG optimizer loops do not own this data plane** — they consume
    and propose; fact authority stays with storage/commit semantics.

## 14. Rationale and decisions

| Topic | Summary | ADR / source |
| --- | --- | --- |
| Split extraction vs engine models | Analysis pipelines need confidence/source_text; engines need labels/Cypher affinity | Package layout under `knowledge_graphs/` |
| IPLD-backed Neo4j-shaped API | Reuse Cypher skills and driver patterns without requiring Bolt Neo4j for core path | `neo4j_compat/`, DOMAIN_MAP |
| WAL + optimistic concurrency | Durable multi-op updates without silent partial commits | `transactions/` |
| Layered authority | Prevent agents from equating hits, inferences, and facts with proof/auth | ADR-003 |
| Content identity separate from location | CID vs cache vs pin | ADR-001 |
| Optional heavy NLP/graph deps | Rule-based extraction and memory engine remain usable | ADR-002, ADR-004 |
| Deprecate root `ipld.py` | Single storage backend story via `IPLDBackend` | Module deprecation notice |

## 15. Related documents

| Document | Relationship |
| --- | --- |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Owns `knowledge_graphs` boundary |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Flows B/C graph hops |
| [CONTENT_ADDRESSING_AND_IPLD.md](../storage/CONTENT_ADDRESSING_AND_IPLD.md) | CID/IPLD profiles |
| [SEARCH_AND_QUERY.md](../retrieval/SEARCH_AND_QUERY.md) | Hybrid retrieval attachment |
| [EMBEDDINGS_AND_INDEXING.md](../retrieval/EMBEDDINGS_AND_INDEXING.md) | Vector side of hybrid |
| [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](../logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Legal IR → graph projection vocabulary |
| `docs/knowledge_graphs/*` | Package user guides / migration guide (product docs; not architecture authority) |
| Planned `GRAPHRAG.md`, `OPTIMIZATION_LOOPS.md` | Orchestration loops over this lifecycle |
| Planned `docs/architecture/knowledge/README.md` | Index page (IPFSDOC-033) |

## 16. Verification

```bash
# Declared task validation
test -s docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md && rg -n 'extraction|transaction|lineage|query|reasoning|Neo4j|CID' docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md

# Spot-check package layout still matches this guide
test -d ipfs_datasets_py/knowledge_graphs/extraction
test -d ipfs_datasets_py/knowledge_graphs/transactions
test -d ipfs_datasets_py/knowledge_graphs/neo4j_compat
rg -n 'class GraphEngine|class TransactionManager|class KnowledgeGraphExtractor|class OntologyReasoner' ipfs_datasets_py/knowledge_graphs --glob '*.py' | head
```

**Last verified against tree:** 2026-08-03 (worktree sources under
`ipfs_datasets_py/knowledge_graphs/` and architecture ADRs cited above).

## 17. Change history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial canonical guide (`IPFSDOC-031`): full lifecycle trace and authority classification |
