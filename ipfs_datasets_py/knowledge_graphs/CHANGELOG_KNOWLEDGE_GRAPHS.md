# Changelog - Knowledge Graphs Module

All notable changes to the knowledge_graphs module will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.22.34] - 2026-02-23

### Added — ROADMAP Research Areas: Knowledge Graph Completion + Explainable AI (Session 80) — 52 tests

**`query/completion.py`** (new module):
- `KnowledgeGraphCompleter(kg)` — suggests missing relationships using 6 structural patterns
- `CompletionReason(str, Enum)` — TRIADIC_CLOSURE / COMMON_NEIGHBOR / SYMMETRIC_RELATION / TRANSITIVE_RELATION / INVERSE_RELATION / TYPE_COMPATIBILITY
- `CompletionSuggestion` dataclass — source_id / target_id / rel_type / score / reason / evidence + `to_dict()`
- `find_missing_relationships(entity_id, rel_type, min_score, max_suggestions)` — sorted by score desc; all 6 patterns
- `find_isolated_entities()` — entities with no incident relationships
- `compute_completion_score(source_id, target_id, rel_type)` — aggregate score for specific triple
- `explain_suggestion(suggestion)` — human-readable explanation string

**`query/explanation.py`** (new module):
- `QueryExplainer(kg)` — main entry point for all explanations
- `ExplanationDepth(str, Enum)` — SURFACE / STANDARD / DEEP verbosity levels
- `EntityExplanation` dataclass — entity_type / name / confidence / in+out degree / top neighbours / narrative + `to_dict()`
- `RelationshipExplanation` dataclass — rel_type / source_name / target_name / symmetry_note / context_chains / narrative + `to_dict()`
- `PathExplanation` dataclass — path_nodes / path_rels / hops / total_confidence / path_labels / narrative / reachable + `to_dict()`
- `explain_entity(entity_id, depth)` — structured entity explanation
- `explain_relationship(relationship_id, depth)` — structured relationship context
- `explain_path(start_id, end_id, max_hops=4)` — BFS shortest-path explanation with confidence chain
- `explain_query_result(entities, depth)` — batch entity explanations
- `why_connected(entity_a_id, entity_b_id)` — natural-language connectivity explanation
- `entity_importance_score(entity_id)` — degree-based centrality × confidence

**`query/__init__.py`**:
- 8 new symbols exported + added to `__all__`: `KnowledgeGraphCompleter` / `CompletionSuggestion` / `CompletionReason` / `QueryExplainer` / `EntityExplanation` / `RelationshipExplanation` / `PathExplanation` / `ExplanationDepth`

**`DEFERRED_FEATURES.md`**:
- P12 §25 Knowledge Graph Completion ✅ Implemented v3.22.34
- P12 §26 Explainable AI over Knowledge Graphs ✅ Implemented v3.22.34

**`ROADMAP.md`**:
- Research Areas "Knowledge graph completion with AI" → ✅ Delivered v3.22.34
- Research Areas "Explainable AI over knowledge graphs" → ✅ Delivered v3.22.34

---

## [3.22.33] - 2026-02-23

### Changed — Comprehensive Documentation Update (Session 79) — 46 doc integrity tests

**`query/README.md`** — version bump 2.1.0→3.22.33:
- Module Contents table: 5 new rows added (graphql.py / federation.py / gnn.py / zkp.py / groth16_bridge.py)
- Overview bullet points expanded with all new capabilities
- Key Features: added privacy-preserving queries, cross-graph federation, neural embeddings
- Stale "Future Enhancements" (listed GraphQL as a future item!) removed and replaced with:
  - "Advanced Query Features" section — code examples for all 5 new query modules
  - "Recent Additions (v3.22.x)" table — module / version / feature cross-reference

**`docs/knowledge_graphs/API_REFERENCE.md`** — version bump 3.22.22→3.22.33:
- New `## Advanced Extraction APIs (v3.22.x)` section with full usage examples for:
  - `KnowledgeGraphDiff` (v3.22.24): diff + apply_diff + summary
  - Graph Event Subscriptions (v3.22.25): subscribe/unsubscribe
  - KG Named Snapshots (v3.22.25): snapshot/restore_snapshot
  - `ProvenanceChain` (v3.22.29): enable_provenance + verify_chain + JSONL
  - `KnowledgeGraphVisualizer` (v3.22.27): to_dot/to_mermaid/to_d3_json/to_ascii
- New `## Advanced Query APIs (v3.22.x)` section with full usage examples + exported symbols for:
  - GraphQL API (v3.22.26): `KnowledgeGraphQLExecutor`
  - Federated Knowledge Graphs (v3.22.28): `FederatedKnowledgeGraph`
  - Graph Neural Networks (v3.22.30): `GraphNeuralNetworkAdapter`
  - Zero-Knowledge Proofs (v3.22.30): `KGZKProver`/`KGZKVerifier`
  - Groth16 Bridge (v3.22.32): `create_groth16_kg_prover`/`KGEntityFormula`
- Table of Contents updated with 2 new entries
- Version Information section updated with all new API version ranges

**`docs/knowledge_graphs/USER_GUIDE.md`** — version bump 2.0.0→3.22.33:
- `§11 Future Roadmap` (which listed features as "planned for Q2-Q1 2027") replaced with `§11 Delivered Features (v3.22.x)`:
  - 15-row delivery table: every planned feature shown as ✅ with delivery version
  - Quick usage examples for all new v3.22.x features
  - Feature Request Process section preserved
- Stale "Experimental Features" block (referencing v2.5.0-alpha imports that don't work) removed
- Header version/date updated

---

## [3.22.32] - 2026-02-23

### Added — Groth16 Bridge Module (Session 78)

**Production code changes.**

- `query/groth16_bridge.py` (new module) — direct bridge from the KG ZKP layer to
  `processors/groth16_backend` via `logic/zkp/backends/groth16.py`:
  - `groth16_binary_available(binary_path=None) → bool` — probes compiled Rust binary
    presence via env overrides (`IPFS_DATASETS_GROTH16_BINARY`, `GROTH16_BINARY`) then
    canonical release-build paths; no subprocess calls.
  - `groth16_enabled() → bool` — checks `IPFS_DATASETS_ENABLE_GROTH16` opt-in env var.
  - `Groth16KGConfig` dataclass — `circuit_version` / `ruleset_id` / `timeout_seconds` /
    `binary_path` / `enable_groth16`; defaults: version=2, ruleset=TDFOL_v1, timeout=30s.
  - `KGEntityFormula` — 6 static methods providing canonical KG↔TDFOL_v1 mapping:
    `entity_exists_theorem` / `entity_exists_axioms` / `path_theorem` / `path_axioms` /
    `property_theorem` / `property_axioms`.  Entity ID stays in private axioms (never in theorem).
  - `create_groth16_kg_prover(kg, config=None) → KGZKProver` — factory backed by
    `ZKPProver(backend="groth16")`; sets `IPFS_DATASETS_ENABLE_GROTH16=1` when `config.enable_groth16`;
    gracefully falls back to simulation mode when binary absent / backend disabled;
    attaches `_groth16_fallback` sentinel attribute.
  - `create_groth16_kg_verifier(seen_nullifiers=None, config=None) → KGZKVerifier` — verifier factory.
  - `describe_groth16_status(binary_path=None) → Dict` — full diagnostic dict:
    `enabled / binary_available / binary_path / backend / production_ready / security_note /
    setup_command / env_var / config_class`.
- `query/__init__.py` — 7 new symbols exported: `groth16_binary_available`, `groth16_enabled`,
  `Groth16KGConfig`, `KGEntityFormula`, `create_groth16_kg_prover`, `create_groth16_kg_verifier`,
  `describe_groth16_status`.
- `DEFERRED_FEATURES.md §24` — "Direct Groth16 Bridge (v3.22.32)" sub-section added with full
  usage examples and production path instructions.

**Test coverage.**

- `tests/unit/knowledge_graphs/test_master_status_session78.py` — 50 tests across 9 classes:
  `TestGroth16AvailabilityHelpers` (7), `TestGroth16KGConfig` (6), `TestKGEntityFormula` (11),
  `TestCreateGroth16KGProver` (4), `TestCreateGroth16KGVerifier` (3), `TestDescribeGroth16Status` (7),
  `TestQueryModuleExports` (3), `TestDocIntegritySession78` (6), `TestVersionAgreement` (3).

---

## [3.22.31] - 2026-02-23

### Added — ZKP Logic Backend Integration (Session 77)

**Production code changes.**

- `query/zkp.py` — `KGZKProver.from_logic_prover(kg, logic_prover, prover_id='default')`:
  factory that wires the KG prover to `ipfs_datasets_py.logic.zkp.ZKPProver`
- `query/zkp.py` — `KGZKProver.uses_logic_backend` property (`True` when logic prover attached)
- `query/zkp.py` — `KGZKProver.get_backend_info()` → `dict` with name/backend/security_level/uses_logic_backend
- `query/zkp.py` — `prove_entity_exists()` + `prove_path_exists()` embed serialised `ZKPProof`
  in `KGProofStatement.public_inputs["logic_proof_data"]` + `"logic_theorem"` when logic prover is present
- `query/zkp.py` — `KGZKVerifier.from_logic_verifier(logic_verifier, seen_nullifiers=None)` factory
- `query/zkp.py` — `KGZKVerifier.verify_statement()` re-verifies embedded `logic_proof_data` via
  `ZKPProof.from_dict()` + `logic_verifier.verify_proof()` when both are present

### Documentation

- `DEFERRED_FEATURES.md §24` — new "Groth16 Backend Integration (v3.22.31)" subsection:
  explains `from_logic_prover`/`from_logic_verifier` factories with usage example;
  documents production path via `processors/groth16_backend` Rust binary
- `MASTER_STATUS.md` — v3.22.30→3.22.31; session 77 log entry

### Tests

- `tests/unit/knowledge_graphs/test_master_status_session77.py` — 28 tests:
  standalone mode (no regression), from_logic_prover factory, logic_proof_data embedding,
  from_logic_verifier factory + enhanced verification, doc-integrity, version agreement

---

## [3.22.30] - 2026-02-23

### Added — Deferred v4.0+ GNN Integration + ZKP Support (Session 76)

**Production code changes.**

- `query/gnn.py` — New module: `GraphNeuralNetworkAdapter` (pure-Python, no PyTorch/TF required)
  - `GNNLayerType(str, Enum)`: GRAPH_CONV / GRAPH_SAGE / GRAPH_ATTENTION
  - `GNNConfig`: embedding_dim / num_layers / layer_type / normalize / activation
  - `NodeEmbedding` dataclass: entity_id / features / layer / dim property
  - `extract_node_features()` — entity-type one-hot + confidence + in/out degree
  - `message_passing()` — neighbour aggregation (3 strategies, configurable iterations)
  - `compute_embeddings()` — full forward pass, cached, with optional L2 normalisation
  - `link_prediction_score(entity_a_id, entity_b_id)` — cosine similarity
  - `find_similar_entities(entity_id, top_k)` — ranked similarity search
  - `to_adjacency_dict()` / `export_node_features_array()` — interop with external GNN frameworks
- `query/zkp.py` — New module: `KGZKProver` + `KGZKVerifier`
  - `KGProofType`: ENTITY_EXISTS / ENTITY_PROPERTY / PATH_EXISTS / QUERY_ANSWER_COUNT
  - `KGProofStatement`: proof_type / parameters / commitment / nullifier / public_inputs
  - `KGZKProver`: prove_entity_exists / prove_entity_property / prove_path_exists / prove_query_answer_count / batch_prove
  - `KGZKVerifier.verify_statement()` + `verify_batch()` — replay-protected verification

**Documentation updates.**

- `query/__init__.py` — 8 new symbols exported; added to `__all__`
- `DEFERRED_FEATURES.md` — P11 §23 GNN + §24 ZKP added (✅ Implemented v3.22.30)
- `ROADMAP.md` — Both remaining v4.0+ items now ✅ Delivered; v3.22.30 row added; Current Version bumped to 3.22.30
- `MASTER_STATUS.md` — v3.22.29→3.22.30; test-files 114+→115+; session 76 log; total 4,169→4,219+

## [3.22.29] - 2026-02-23

### Added — Deferred v4.0+ Blockchain-Style Provenance Chain (Session 75)

**Production code changes.**

- `extraction/provenance.py` (new):
  - `ProvenanceEventType(str, Enum)` with 7 event types: `ENTITY_CREATED`, `ENTITY_MODIFIED`, `ENTITY_REMOVED`, `RELATIONSHIP_CREATED`, `RELATIONSHIP_REMOVED`, `GRAPH_SNAPSHOT`, `GRAPH_RESTORED`
  - `ProvenanceEvent` dataclass — SHA-256 content-addressed CID auto-computed in `__post_init__`; each event links to predecessor via `previous_cid` forming an immutable hash chain; `to_dict()` / `from_dict()`
  - `ProvenanceChain` class — append-only, tamper-evident provenance log with entity/relationship indexes, `verify_chain()`, JSONL serialisation/deserialisation
- `extraction/graph.py`:
  - `KnowledgeGraph.enable_provenance()` — attaches a `ProvenanceChain`; returns chain
  - `KnowledgeGraph.disable_provenance()` — detaches chain
  - `KnowledgeGraph.provenance` property — returns attached chain or `None`
  - `add_entity()` and `add_relationship()` — auto-record provenance events when chain is attached
- `extraction/__init__.py`: `ProvenanceChain`, `ProvenanceEvent`, `ProvenanceEventType` exported in `__all__`
- `DEFERRED_FEATURES.md`: P10 section with §22 Blockchain/Provenance Chain ✅ Implemented v3.22.29
- `ROADMAP.md`: "Blockchain integration for provenance" → ✅ Delivered v3.22.29; v3.22.29 row added

**Test changes (45 new tests):**
- `tests/unit/knowledge_graphs/test_master_status_session75.py`: 45 tests across 8 classes

---

## [3.22.28] - 2026-02-23

### Added — Deferred v4.0+ Federated Knowledge Graphs (Session 74)

**Production code changes.**

- **`query/federation.py`** — New module implementing cross-graph federation:
  - `FederatedKnowledgeGraph` — registry of independent `KnowledgeGraph` instances with full federation operations:
    - `add_graph(kg, name=None) → int` — register a graph, get its index
    - `get_graph(index) → KnowledgeGraph` / `list_graphs() → List[Tuple[int, str]]` / `num_graphs` property
    - `resolve_entities(strategy=TYPE_AND_NAME) → List[EntityMatch]` — cross-graph entity matching
    - `get_entity_cluster(fingerprint, strategy) → List[Tuple[int, str]]` — all occurrences of an entity
    - `query_entity(name=None, entity_type=None) → List[Tuple[int, Entity]]` — search across all graphs
    - `execute_across(query_fn) → FederationQueryResult` — apply callable to all graphs, capture errors
    - `to_merged_graph(strategy, merged_name) → KnowledgeGraph` — deduplicate entities, merge properties, remap relationships
  - `EntityResolutionStrategy(str, Enum)` — three strategies: `EXACT_NAME`, `TYPE_AND_NAME` (default), `PROPERTY_MATCH`
  - `EntityMatch` dataclass — `entity_a_id / entity_b_id / kg_a_index / kg_b_index / score / strategy`
  - `FederationQueryResult` dataclass — `per_graph_results / merged_entities / total_matches / query_errors`
- **`query/__init__.py`** — 4 new symbols exported (`FederatedKnowledgeGraph`, `EntityResolutionStrategy`, `EntityMatch`, `FederationQueryResult`) and added to `__all__`

**Documentation changes.**
- `DEFERRED_FEATURES.md`: P9 §21 Federated Knowledge Graphs ✅ Implemented v3.22.28 with full usage examples
- `ROADMAP.md`: "Federated knowledge graphs" → ✅ Delivered v3.22.28; v3.22.28 row added
- `MASTER_STATUS.md`: v3.22.27→v3.22.28; session 74 entry; test-files 112+→113+; 4,082→4,124 tests

**Tests:** `tests/unit/knowledge_graphs/test_master_status_session74.py` — 42 tests across 9 classes

## [3.22.27] - 2026-02-23

### Added — Deferred v4.0+ Advanced Visualization Tools (Session 73)

**Production code changes.**

- **`extraction/visualization.py`** — New module implementing `KnowledgeGraphVisualizer`:
  - `to_dot(graph_name=None, directed=True) → str` — Graphviz DOT language; entity nodes as ellipses with `name\n(type)` labels; relationship edges with type labels; proper DOT special-char escaping
  - `to_mermaid(direction="LR", max_entities=None) → str` — Mermaid.js `graph LR` notation; compatible with GitHub Markdown, Notion, GitLab, Obsidian, and mermaid.live; optional entity count limit
  - `to_d3_json(max_nodes=None) → dict` — D3.js force-directed graph JSON (`{"nodes": [...], "links": [...]}`) with node fields `id/name/type/confidence/properties` and link fields `source/target/type/confidence/properties`
  - `to_ascii(root_entity_id=None, max_depth=3) → str` — ASCII-art tree; rooted depth-first traversal when `root_entity_id` given; flat entity roster with outgoing relationships otherwise
  - No external dependencies; pure Python 3.12+

- **`extraction/graph.py`**: 4 lazy-import convenience methods added to `KnowledgeGraph`:
  - `to_dot(**kwargs)`, `to_mermaid(**kwargs)`, `to_d3_json(**kwargs)`, `to_ascii(**kwargs)` — each delegates to `KnowledgeGraphVisualizer(self).<method>(**kwargs)`; lazy import avoids circular dependency

- **`extraction/__init__.py`**: `KnowledgeGraphVisualizer` exported in `__all__`

**Documentation changes.**

- `DEFERRED_FEATURES.md`: P8 section added — §20 Advanced Visualization Tools (✅ Implemented v3.22.27) with full usage example for all 4 formats
- `ROADMAP.md`: v4.0+ "Advanced visualization tools" → ✅ Delivered in v3.22.27 (`KnowledgeGraphVisualizer` in `extraction/visualization.py`); v3.22.27 row added to release table; Current Version 3.22.26→3.22.27
- `MASTER_STATUS.md`: version 3.22.26→3.22.27; session 73 entry; test-files 111+→112+; total 4,041→4,082
- `CHANGELOG_KNOWLEDGE_GRAPHS.md`: this section

---

## [3.22.26] - 2026-02-23

### Added — Deferred v4.0+ GraphQL API support (Session 72)

**Production code changes.**

- **`query/graphql.py`** — New module implementing lightweight GraphQL query interface for KnowledgeGraph:
  - `GraphQLParser`: recursive-descent parser for a practical GraphQL subset — entity queries, argument filters (`name`, `id`, `type`, or any property), field projection, nested relationship traversal, aliases, and string/int/float/bool/null argument values
  - `GraphQLDocument` / `GraphQLField`: lightweight AST node dataclasses; `GraphQLField.is_leaf` property
  - `GraphQLParseError(ValueError)`: clean error type for parse failures
  - `KnowledgeGraphQLExecutor(kg)`: executes GraphQL queries against a `KnowledgeGraph`; response envelope follows the GraphQL-over-HTTP specification (`{"data": {...}}`); errors captured without raising; fully backward-compatible

- **`query/__init__.py`**: exports `GraphQLParseError`, `GraphQLField`, `GraphQLDocument`, `GraphQLParser`, `KnowledgeGraphQLExecutor` from `query.__all__`

**Documentation changes.**

- `DEFERRED_FEATURES.md`: P7 section added — §19 GraphQL API Support (✅ Implemented v3.22.26) with full usage example
- `ROADMAP.md`: v4.0+ "GraphQL API support" → ✅ Delivered in v3.22.26; v3.22.26 row added to release table
- `MASTER_STATUS.md`: version 3.22.25→3.22.26; session 72 entry; test-files 110+→111+; total 4,009→4,041
- `CHANGELOG_KNOWLEDGE_GRAPHS.md`: this section

---

## [3.22.25] - 2026-02-22

### Added — Deferred v4.0+ features: graph event subscriptions + KG snapshots (Session 71)

**Production code changes.**

- `extraction/graph.py`: Added `GraphEventType(str, Enum)` with 5 event types: `entity_added`, `entity_removed`, `entity_modified`, `relationship_added`, `relationship_removed`
- `extraction/graph.py`: Added `GraphEvent` dataclass — `event_type`, `timestamp`, `entity_id`, `relationship_id`, `data`
- `extraction/graph.py`: Added `KnowledgeGraph.subscribe(callback) → int` — registers observer callback, returns handler ID; `unsubscribe(handler_id) → bool` — removes observer; `_emit_event(event)` — fan-out to all subscribers; exceptions in subscribers silently suppressed
- `extraction/graph.py`: Wired `_emit_event()` into `add_entity()` (ENTITY_ADDED), `add_relationship()` (RELATIONSHIP_ADDED), and all 5 mutation types in `apply_diff()` (ENTITY_REMOVED, RELATIONSHIP_REMOVED, ENTITY_ADDED, RELATIONSHIP_ADDED, ENTITY_MODIFIED)
- `extraction/graph.py`: Added `KnowledgeGraph.snapshot(name=None) → str` — serializes current entities+relationships; auto-names if omitted
- `extraction/graph.py`: Added `KnowledgeGraph.get_snapshot(name) → Optional[Dict]` — returns copy of stored payload; `None` if not found
- `extraction/graph.py`: Added `KnowledgeGraph.list_snapshots() → List[str]` — sorted snapshot names
- `extraction/graph.py`: Added `KnowledgeGraph.restore_snapshot(name) → bool` — fully rebuilds entities, relationships, and indexes from snapshot; event subscribers not notified during restore
- `extraction/__init__.py`: `GraphEventType` and `GraphEvent` exported from `__all__`

### Fixed — Documentation

- `MASTER_STATUS.md`: version 3.22.24→3.22.25; Documentation row `v3.22.18`→`v3.22.25`; session 71 entry added; total tests 3,971→4,009
- `DEFERRED_FEATURES.md`: §17 Graph Event Subscriptions + §18 KG Snapshots added (both ✅ Implemented v3.22.25)
- `ROADMAP.md`: Current Version 3.22.24→3.22.25; v4.0+ "Real-time graph streaming" + "Temporal graph databases" marked ✅ Delivered; 3.22.25 row added

## [3.22.24] - 2026-02-22

### Added — Graph diff/patch feature (Session 70)

**Production code changes.**

- `extraction/graph.py`: Added `KnowledgeGraphDiff` dataclass — structural diff between two `KnowledgeGraph` instances; fields: `added_entities` (full entity dicts), `removed_entity_ids`, `added_relationships` (full rel dicts), `removed_relationship_ids`, `modified_entities` (per-entity old/new property dicts); `is_empty` property; `summary()`, `to_dict()`, `from_dict()` methods
- `extraction/graph.py`: Added `KnowledgeGraph.diff(other)` — computes structural diff from self to other; entities matched by `(entity_type, name)` fingerprint; relationships matched by `(relationship_type, source_fingerprint, target_fingerprint)` triple
- `extraction/graph.py`: Added `KnowledgeGraph.apply_diff(diff)` — applies diff in-place; cascade-removes entities (including their relationships), removes standalone relationships, adds new entities, applies property modifications, adds new relationships
- `extraction/__init__.py`: `KnowledgeGraphDiff` exported from `__all__`

### Fixed — Documentation / stale snapshot data

- `MASTER_STATUS.md`: version 3.22.23→3.22.24; `Test Files: 103 total` → `110+ total (as of v3.22.24)`; session 70 entry added to session log; total tests 3,939→3,971
- `MASTER_REFACTORING_PLAN_2026.md`: snapshot updated — `session 66`→`session 69`, `3,856+`→`3,939+`, `Document Version: 3.22.21`→`3.22.24`, `Version: 3.22.18`→`3.22.24`
- `DEFERRED_FEATURES.md`: §16 Graph Diff/Patch added (✅ Implemented v3.22.24); Last Updated session 69→70
- `ROADMAP.md`: Current Version 3.22.23→3.22.24; 3.22.24 row added to release table

## [3.22.23] - 2026-02-22

### Added — Deferred v4.0+ features implemented (Session 69)

**Production code changes.**

- `extraction/extractor.py`: Added `KnowledgeGraphExtractor.aggregate_confidence_scores(scores, method='mean', weights=None)` static method — multi-source confidence aggregation supporting 6 strategies: `mean`, `min`, `max`, `harmonic_mean`, `weighted_mean`, `probabilistic_and`
- `extraction/extractor.py`: Added `KnowledgeGraphExtractor.compute_extraction_quality_metrics(kg)` static method — returns 10-key metrics dict: entity/relationship counts + density, avg/std confidence, low-confidence ratio, type diversity, isolated entity ratio; no external deps
- `migration/formats.py`: Added `progress_callback: Optional[Callable[[int, int, int, int], None]] = None` parameter to `GraphData.export_streaming()` — called after each chunk with `(nodes_written, total_nodes, rels_written, total_rels)` for progress tracking and resumable migrations

### Fixed — Documentation

- `extraction/README.md`: Phase 5 "Status: In Progress" → "Status: Complete ✅"; removed duplicate "Security audit and validation" line
- `DEFERRED_FEATURES.md`: P5 section added with entries for Confidence Score Aggregation (✅ v3.22.23) and Migration Progress Tracking (✅ v3.22.23)
- `ROADMAP.md`: Confidence Scoring Improvements `📋 Deferred` → `✅ Delivered in v3.22.23`; Progress Tracking deferred note → `✅ Delivered in v3.22.23`

## [3.22.22] - 2026-02-22

### Fixed — Stale "Not Supported" tables in cypher/README + core/README + docs/ (Session 68)

**Documentation-only changes.**

- `cypher/README.md`: `❌ Not Supported` table replaced with `✅ Implemented in v2.1.0` — NOT/CREATE/MERGE/DELETE all fully implemented; `Last Updated: 2026-02-17` → `2026-02-22`
- `core/README.md`: `Test Coverage: ~80%` → `100%`; `Phase 5: (Planned)` → `📋 Deferred to v4.0+`; `Version: 2.0.0` → `3.22.22`
- `docs/knowledge_graphs/MIGRATION_GUIDE.md`: Cypher `⚠️ Unsupported` table → `✅ All features implemented`; GraphML/GEXF/Pajek `Not implemented` → `✅ Implemented`; stale workaround section replaced with code example; extraction `Planned` table → `✅ Delivered`; version/date updated
- `docs/knowledge_graphs/API_REFERENCE.md`: `Known Limitations` NOT/CREATE bullets removed; `✅ implemented (v2.1.0)` note added; version/date updated

## [3.22.21] - 2026-02-22

### Fixed — Stale TEST_STATUS/TEST_GUIDE metrics + archive/README + MASTER_REFACTORING_PLAN (Session 67)

**Documentation-only changes (test infrastructure docs).**

#### `tests/knowledge_graphs/TEST_STATUS.md`
- `Module Version: 2.0.0` → `3.22.21`; `Last Updated: 2026-02-18` → `2026-02-22`
- `Total Test Files: 47` → `108+`; `Total Test Functions: 647+` → `3,856+`
- `Overall Coverage: ~75%` → `99.99%`; per-module coverage updated (40-85% → 99-100%)
- `Migration Module: ~40%` → `100%`; removed stale v2.0.1 improvement plan
- Fixed broken `IMPLEMENTATION_STATUS.md` link → `MASTER_STATUS.md`

#### `tests/knowledge_graphs/TEST_GUIDE.md`
- Overview: `43 test files / 116+ tests / 75%` → `108+ files / 3,856+ tests / 99.99%`
- Coverage table: all modules updated to current 99-100% (was 40-85%)
- Removed stale "not yet implemented" notes for NOT/CREATE (both implemented in v2.1.0)
- Migration section updated from 40% to 100%
- Coverage Targets table: historical `v2.0.0` targets updated with actual achievements
- Fixed broken links: `IMPLEMENTATION_STATUS.md` → `MASTER_STATUS.md`; removed stale `NEW_COMPREHENSIVE_IMPROVEMENT_PLAN` link
- `Last Updated: 2026-02-18` → `2026-02-22`; Next Review Q2→Q3 2026

#### `archive/README.md`
- Removed `⭐ **NEW**` tag from `COMPREHENSIVE_ANALYSIS_2026_02_18.md` entries (now a historical doc)
- Fixed broken `IMPLEMENTATION_STATUS.md` parent link → `MASTER_STATUS.md`
- `Last Updated: 2026-02-18` → `2026-02-22`

#### `MASTER_REFACTORING_PLAN_2026.md`
- Section 1 heading: `Module Snapshot (session 63)` → `session 66`
- Test counts: `3,782+` → `3,856+`; test files: `95+` → `108+`
- Footer: `Document Version: 1.0` → `3.22.21`
- Section 8: Next review `Q2 2026 (after v2.0.1 release)` → `Q3 2026`

#### `DOCUMENTATION_GUIDE.md`
- Ticked `[ ] Update tests/knowledge_graphs/TEST_GUIDE.md` → `[x]`

## [3.22.20] - 2026-02-22

### Fixed — Historical doc banners + DOCUMENTATION_GUIDE tier classification (Session 66)

**Documentation-only changes.**

#### `COMPREHENSIVE_ANALYSIS_2026_02_18.md`
- Added `⚠️ Historical Document` banner referencing current MASTER_STATUS.md
- Footer "Next Action: Proceed with Phase 1" → "All action items complete as of v3.22.19"
- "Next Review: After Phase 1 & 2 completion (3-4 hours from now)" → "Completed"

#### `EXECUTIVE_SUMMARY_FINAL_2026_02_18.md`
- Added `⚠️ Historical Document` banner
- All stale `[ ]` items ticked `[x]` with completion notes (v3.22.x milestones)
- Status note updated to "All recommended next steps now complete (v3.22.19)"

#### `REFACTORING_COMPLETE_2026_02_18.md`
- Added `⚠️ Historical Document` banner with current metrics link

#### `DOCUMENTATION_GUIDE.md`
- Item 7 (COMPREHENSIVE_ANALYSIS): removed stale `**NEW**` tag; description updated to
  "Historical reference — do not modify"
- Tier 6 section: `EXECUTIVE_SUMMARY_FINAL_2026_02_18.md` and
  `REFACTORING_COMPLETE_2026_02_18.md` now listed explicitly (were missing)

## [3.22.19] - 2026-02-22

### Fixed — Stale docstring + doc reference fixes (Session 65)

**One production code change (docstring only); doc-only otherwise.**

#### `reasoning/cross_document.py` (docstring fix)
- Removed stale "see TODO at line 542" reference from `_determine_document_relationship()`
  docstring. Line 542 is plain implementation code, not a TODO comment. The heuristic
  nature of the current approach is now described directly in the note.

#### `MASTER_STATUS.md`
- `Documentation` row: `Reflects v3.22.15 structure` → `Reflects v3.22.18 structure`
- Test files count: `95 total (as of v3.22.15)` → `102 total (as of v3.22.18)` (sessions 59–64 added 6 new test files)

#### `MASTER_REFACTORING_PLAN_2026.md`
- Version bumped `3.22.17` → `3.22.18`
- Added "API Accuracy (sessions 63–64)" section to §2 Completed Work Summary

#### Tests
- 16 new doc+code integrity tests in `test_master_status_session65.py`

---

## [3.22.18] - 2026-02-22

### Fixed — QUICKSTART.md API inaccuracies + MASTER_STATUS feature coverage matrix (Session 64)

**No production code changes.** Fixed 5 API inaccuracies in QUICKSTART.md (would cause
`AttributeError`/`TypeError` at runtime) and updated the Feature Completeness Matrix in
MASTER_STATUS.md to reflect current 99-100% coverage.

#### `QUICKSTART.md`
- `rel.source` → `rel.source_id`; `rel.target` → `rel.target_id` (`Relationship` attributes are `source_id`/`target_id`, not `source`/`target`)
- Removed non-existent `backend.add_knowledge_graph(kg)` call (no such method on `IPLDBackend`); query example now uses `GraphEngine` directly
- `engine.execute(...)` → `engine.execute_cypher(...)` (no `execute()` method on `UnifiedQueryEngine`)
- `for row in results:` → `for row in result.items:` (`QueryResult` has `.items` list, not `__iter__`)
- `backend.store(kg)` → `backend.store(kg.to_dict())` + `backend.retrieve_json(cid)` (`store()` takes bytes/str/dict; `retrieve()` returns bytes, not a `KnowledgeGraph`)
- `HybridSearch` → `HybridSearchEngine` (correct class name exported from `query/`)
- `top_k=5` → `k=5` (actual kwarg name); removed `combine_strategy="weighted"` (no such argument)
- `result.entity.name` → `result.node_id` (`HybridSearchResult` has `node_id`, not `entity`)

#### `MASTER_STATUS.md`
- Feature Completeness Matrix: all per-feature coverage %s updated from stale 40–85% → current 99–100%
  - Core features: 75–85% → ~97–100%
  - Query/Cypher features: 70–80% → 100%
  - Advanced (P1–P4, SRL, OWL): 75–80% → 99–100%
  - Migration: 40–85% → 100%
- Coverage note updated: "Migration module at 100% coverage as of v3.22.17"

## [3.22.17] - 2026-02-22

### Changed — ROADMAP.md stale items + MASTER_REFACTORING_PLAN_2026.md update (Session 63)

**No production code changes.** Fixed stale "Status: Planned" items inside CANCELLED roadmap
sections and brought the refactoring plan up to date with sessions 59-62 progress.

#### `ROADMAP.md`
- v2.2.0 §4 "Migration Performance": `Status: Planned` → `✅ Delivered in v2.1.0` (streaming export, chunked iteration, parallel query execution, integrity verification all implemented)
- v2.5.0 §2 "spaCy Dependency Parsing Integration": `Status: Planned` → `✅ Delivered in v2.1.0` (via `SRLExtractor` spaCy backend + `_aggressive_entity_extraction()`)
- v2.5.0 §4 "Confidence Scoring Improvements": `Status: Planned` → `📋 Deferred to v4.0+` (basic confidence fields already exist; advanced probabilistic scoring deferred pending user demand)

#### `MASTER_REFACTORING_PLAN_2026.md`
- `**Version:** 1.0` → `3.22.17`
- `**Last Updated:** 2026-02-20` → `2026-02-22`
- §1 Module Snapshot updated: 92→96+ files; 64→95+ test files; 1,075+→3,782 tests; ~78%→**99.99%** coverage; migration coverage 70%+→**100%**
- §2 Completed Work: Coverage Push (sessions 27–58) and Documentation Consistency (sessions 59–62) sections added
- §3.3.2 Extraction Validation Split: `🟡 Deferred` → `📋 Deferred to v4.0+` (explicitly documented rationale: no clean concern separation without substantial refactoring; revisit if class exceeds 1,000 lines)

## [3.22.16] - 2026-02-22

### Changed — DOCUMENTATION_GUIDE.md + DEFERRED_FEATURES.md + IMPROVEMENT_TODO.md stale metadata (Session 62)

**No production code changes.** Fixed stale version numbers, dates, and a wrong path reference
across three documentation files.

#### `DOCUMENTATION_GUIDE.md`
- `**Version:** 1.0` → `3.22.16` (header + footer, 2 places)
- `**Last Updated:** 2026-02-18` → `2026-02-22` (header + footer, 2 places)
- Removed duplicate `MASTER_STATUS.md` entry (item 5 was identical to item 4 — only the ⭐ entry kept)
- Items 6–24 renumbered to 5–23 (sequential after duplicate removal)
- `**Next Review:** Q2 2026` → `After each major release or quarterly`
- Item 5 `DEFERRED_FEATURES.md` description updated: "Intentionally incomplete features (all ✅ implemented as of v3.22.0)"

#### `DEFERRED_FEATURES.md`
- `**Last Updated:** 2026-02-20 (session 4)` → `2026-02-22 (session 62)`
- `**Next Review:** Q3 2026 (before v2.5.0 release)` → `Q3 2026` (removed stale v2.5.0 ref)

#### `IMPROVEMENT_TODO.md`
- Scope path: `ipfs_datasets_py/ipfs_datasets_py/knowledge_graphs/` → `ipfs_datasets_py/knowledge_graphs/`
- Note-on-pathing: removed double `ipfs_datasets_py/` prefix from old wrong path

#### Tests
- Added `test_master_status_session62.py` with 18 doc integrity tests:
  - `TestDocumentationGuideVersion` (5 tests): v3.22.16; stale 1.0 gone; Last Updated 2026-02-22
  - `TestDocumentationGuideDuplicateEntry` (5 tests): no duplicate MASTER_STATUS entries; items number correctly (item 23 present, item 24 absent; old item 5 dup gone)
  - `TestDeferredFeaturesMetadata` (4 tests): session 62 date; stale v2.5.0 ref absent; Last Updated 2026-02-22
  - `TestImprovementTodoPath` (4 tests): double-prefix path absent; correct path present; no old pathing pattern

## [3.22.15] - 2026-02-22

### Changed — Stale version/coverage numbers fixed (Session 61)

**No production code changes.** Updated INDEX.md, README.md, and ROADMAP.md to reflect
the current state (v3.22.15, 99.99% coverage, 3,743+ tests).

#### `INDEX.md`
- `Module Version: 2.0.0` → `3.22.15` (header, stats table, footer)
- `Test Coverage: 75% overall, 116+ tests` → `99.99%, 3,743+ tests`
- `Current State (v2.0.0)` → `Current State (v3.22.15)` in Module Status section
- `11/12 modules production-ready` → `12/12`
- Removed stale `⚠️ Migration Module: Needs test coverage improvement (40% → 70%)`
- `Next Version (v2.0.1 - Q2 2026)` section → `Next Version (v4.0 - 2027+)`
- Added v3.22.0 and v3.22.15 rows to Version History table
- `Last Updated: 2026-02-17` → `2026-02-22` (header + footer)

#### `README.md`
- `**Version:** 2.1.0` → `3.22.15`
- `**Last Updated:** 2026-02-20` → `2026-02-22`

#### `ROADMAP.md`
- `**Current Version:** 3.22.14` → `3.22.15` (header only; 3.22.14 retained in release table)

#### Tests
- Added `test_master_status_session61.py` with 21 doc integrity tests:
  - `TestIndexMdVersionUpdate` (3 tests): Module Version 3.22.15; stale v2.0.0 gone
  - `TestIndexMdCoverageUpdate` (4 tests): 99.99%; 3,743+ tests; stale 75%/116+ gone
  - `TestIndexMdModuleStatusSection` (5 tests): current state v3.22.15; stale warnings absent
  - `TestReadmeMdVersionUpdate` (3 tests): version/last-updated checks
  - `TestRoadmapCurrentVersionUpdate` (3 tests): 3.22.15 present; 3.22.14 in table (backward compat)
  - `TestThreeDocVersionAgreement` (3 tests): INDEX/README/ROADMAP all on v3.22.15

### Changed — MASTER_STATUS stale coverage table + ROADMAP duplicate section (Session 60)

**No production code changes.** Updated docs to reflect sessions 54–59 improvements.

#### `MASTER_STATUS.md`
- Coverage heading: `~89% (measured, session 26)` → `99.99% (1 missed line; measured, session 58)`
- Per-module coverage table: all modules updated to reflect sessions 27–58 results
  (Cypher 100%, Neo4j Compat 100%, Migration 100%, JSON-LD 100%, Core 100%, etc.)
- Removed stale "Largest remaining coverage opportunities" list (extractor 54%, etc.)
- Added one-line summary: `_entity_helpers.py:117` is the only remaining missed line
- Sessions 54–60 added to test session list
- Total test count: `3,614 passing` → `3,725 passing, 26 skipped`
- Test files count: `65 total (as of v2.7.0)` → `95 total (as of v3.22.15)`
- Version: `3.22.14` → `3.22.15`

#### `ROADMAP.md`
- Removed the duplicate unchecked `## Version 2.0.1 (Q2 2026)` section (lines 17–35)
  that was superseded by the checked version immediately below it (lines 37–47)
- Updated `**Last Updated:** 2026-02-20` → `2026-02-22`

#### Tests

**18 new tests** in `test_master_status_session60.py` (4 classes):

- `TestMasterStatusCoverageSection` (6 tests): heading says 99.99% not ~89%; stale entries
  absent; 1-missed-line section present; spaCy stale 108-line ref gone.
- `TestMasterStatusTestCount` (4 tests): 3,725 present; stale 3,614 gone; sessions 54–60 in list.
- `TestRoadmapDuplicateSection` (5 tests): v2.0.1 heading appears exactly once; unchecked
  TODO items gone; Last Updated corrected.
- `TestThreeDocVersionAgreement` (3 tests): MASTER_STATUS/ROADMAP/CHANGELOG all on 3.22.15.

**Result: 3,743 passed, 26 skipped, 0 failed**

---

## [3.22.14] - 2026-02-22

### Changed — Documentation Consistency Fixes (Session 59)

**No production code changes.** Synchronised all three tracking documents to match
the actual release history.

#### `ROADMAP.md`
- Updated `Current Version` header: `3.22.3` → `3.22.14`
- Updated `Status` header: `99%` → `99.99% test coverage`
- Added v3.22.1 through v3.22.14 to the Release Schedule table (was jumping from
  3.22.0 directly to 4.0)

#### `CHANGELOG_KNOWLEDGE_GRAPHS.md`
- Added missing `## [3.22.5]` section (session 50: numpy-via-networkx skip guards)
- Added missing `## [3.22.7]` section (session 52: ImportError except branches)
- Added missing `## [3.22.11]` section (session 56: dead code removal)
- All versions 3.22.0 – 3.22.14 now have their own section headings

#### Tests

**22 new tests** in `test_master_status_session59.py` (4 classes):

- `TestRoadmapHeaderVersion` (5 tests): Current Version header; stale 3.22.3 absent;
  coverage value reflects 99.99%.
- `TestRoadmapReleaseTable` (5 tests): release table has every 3.22.x version 0–14;
  v4.0 future entry preserved.
- `TestChangelogVersionCoverage` (6 tests): all 3.22.x section headings present;
  v3.22.5 / v3.22.7 / v3.22.11 explicitly checked; headings in descending order.
- `TestMasterStatusVersion` (5 tests): version header 3.22.14; not stale 3.22.13;
  all three docs agree on 3.22.14.

**Result: 3,725 passed, 26 skipped, 0 failed**

---

## [3.22.13] - 2026-02-22

### Changed — Dead Code Removal: srl.py + ipld extras (Session 58)

#### `extraction/srl.py` — 2 lines removed

Removed the unreachable `elif dep in ("npadvmod",): role = ROLE_TIME` block (old lines
401-402).  The `npadvmod` dep value is already matched by the preceding
`elif dep in ("prep", "advmod", "npadvmod"):` chain at line 385, so the second elif was
permanently unreachable.  The combined branch routes unrecognised prep-text to ROLE_THEME,
so runtime behaviour is unchanged.

- `extraction/srl.py`: 99% → **100%** ✅

#### `setup.py` — `ipld` extras: `multiformats>=0.3.0` added

The `_builtin_save_car` function imports `from multiformats import CID, multihash` but
`multiformats` was missing from the `ipld` extras in `setup.py`.  Added:

```
'multiformats>=0.3.0',  # CID + multihash (required for CAR save path)
```

#### `pyproject.toml` — `ipld` optional-dependencies section added

`pyproject.toml` had no `ipld` extras section.  Added with all 5 IPLD deps to match
`setup.py`:

```toml
[project.optional-dependencies]
ipld = [
    "libipld>=3.3.2",
    "ipld-car>=0.0.1",
    "ipld-dag-pb>=0.0.1",
    "dag-cbor>=0.3.3",
    "multiformats>=0.3.0",
]
```

#### Test Coverage

**12 new tests** in `test_master_status_session58.py`:

- `TestSrlNpadvmodDeadCodeRemoved` (7 tests): source invariants + runtime proofs
- `TestIpldExtrasMultiformats` (5 tests): setup.py + pyproject.toml ipld consistency

**Result:** 3,757 pass, 2 skip, **0 fail** (full dep env); 1 missed line remaining.
Coverage: 99.99% (only `_entity_helpers.py:117` defensive guard).

---

## [3.22.12] - 2026-02-22

### Added — Visualization Dependencies + plotly ImportError Coverage (Session 57)

**4 optional dependencies added to `knowledge_graphs` extras.**

#### `setup.py` / `pyproject.toml` / `requirements.txt`

Added to `extras_require['knowledge_graphs']` (setup.py) and
`[project.optional-dependencies] knowledge_graphs` (pyproject.toml):

- `scipy>=1.7.0` — enables `nx.kamada_kawai_layout` for hierarchical visualization
- `matplotlib>=3.5.0` — enables `LineageVisualizer.render_networkx()`
- `plotly>=5.9.0` — enables `LineageVisualizer.render_plotly()`
- `rdflib>=6.0.0` — enables `KnowledgeGraph.export_to_rdf()`

Also added to `requirements.txt` for consistent pip installs.

#### Test Coverage

**12 new tests** in `test_master_status_session57.py`:

- `TestVisualizationPlotlyImportError` (7 tests): covers `visualization.py:29-31`
  (plotly ImportError except block) via `_reload_with_absent_dep`; also covers
  render_plotly with real plotly (with `go` restore to guard against session38's
  test which sets `viz_mod.go = MagicMock()` and never restores it).
- `TestSetupPyScipy` (3 tests): verifies scipy/matplotlib/plotly present in
  setup.py knowledge_graphs extras.
- `TestVisualizationHierarchicalLayout` (2 tests): confirms kamada_kawai_layout
  branch (line 116) runs correctly with real scipy.

#### Coverage Results

With all optional deps installed:

- `lineage/visualization.py`: 97% → **100%** ✅ (plotly ImportError except block covered)
- `extraction/graph.py`: 80% → **100%** ✅ (45 rdflib-gated lines covered)
- 15 previously-skipped scipy tests now pass
- TOTAL missed lines: 204 → **120** (99% overall coverage)
- **Test counts: 3,690 passed, 26 skipped, 0 failed**



### Removed — Dead Code in cross_document.py and ir_executor.py (Session 56)

**9 lines of provably unreachable code removed from 2 files.**

#### `reasoning/cross_document.py`

- Removed `if norm_src == 0.0 or norm_tgt == 0.0: return 0.0` guard (2 lines).
  This guard was unreachable: the preceding `if not src_tokens or not tgt_tokens`
  check ensures both token lists are non-empty, so `Counter` values are always ≥ 1
  and both L2 norms are always strictly positive.
- A clarifying comment was added in place of the removed guard.
- **`reasoning/cross_document.py` is now at 100% coverage.**

#### `core/ir_executor.py`

- Removed the `if "." in expr:` / `else:` branching inside `OrderBy make_sort_key`
  (7 lines total):
  - The `var_name, prop_name = expr.split(".", 1)` assignment — those variables were
    never used in the function body.
  - The `try: record.get(expr) / except (AttributeError, KeyError, TypeError): value = None`
    wrapper — `Record.get()` delegates to `dict.get()` and never raises.
  - Both branches performed exactly `value = record.get(expr)`, so they collapsed to
    a single statement.
- **`core/ir_executor.py` is now at 100% coverage.**

### Tests
- Added `tests/unit/knowledge_graphs/test_master_status_session56.py` with **13 invariant
  tests** (2 classes: `TestCrossDocumentZeroNormProof`, `TestIRExecutorOrderByStringExpr`).

**Result: 3,640 pass, 64 skip, 0 fail (base env); 204 missed lines**

---

## [3.22.11] - 2026-02-22

### Removed — Dead Code in cross_document.py and ir_executor.py (Session 56)

*Note: This entry corrects a prior omission — the session 56 content was originally
bundled into the v3.22.12 section of this changelog. The production changes and tests
belong to this version.*

**9 lines of provably unreachable code removed from 2 files. See v3.22.12 for full details.**

- `reasoning/cross_document.py`: removed 2-line zero-norm guard → **100%** ✅
- `core/ir_executor.py`: collapsed 7-line if/else+try/except to 1 line → **100%** ✅
- 13 invariant tests in `test_master_status_session56.py`

**Result: 3,640 pass, 64 skip, 0 fail (base env); 204 missed lines**

---

## [3.22.10] - 2026-02-22

### Changed — numpy as Default Dependency (Session 55)

**numpy promoted from optional to default (always-installed) dependency.**

#### `setup.py`
- `install_requires`: replaced bare `'numpy'` with versioned markers matching
  `requirements.txt`:
  - `"numpy>=1.21.0,<2.0.0; python_version < '3.14'"`
  - `"numpy>=2.0.0; python_version >= '3.14'"`
- `extras_require['knowledge_graphs']`: removed duplicate `'numpy>=1.21.0'` entry
  (numpy is now in base `install_requires`).

#### `pyproject.toml` (new file)
- Created minimal PEP 517/518 build configuration:
  - `[build-system]`: setuptools>=68 + wheel
  - `[project] dependencies`: same numpy version markers as setup.py / requirements.txt
  - `[project.optional-dependencies] knowledge_graphs`: spacy, networkx, transformers
    (numpy omitted since it is in base deps)
  - `[tool.pytest.ini_options]`: asyncio_mode = "auto"

#### `requirements.txt`
- Already had correct versioned numpy entries — no change needed.

#### Tests
- `test_master_status_session55.py`: 13 verification tests in 4 classes
  - `TestSetupPyNumpyDep`: install_requires version bounds + no-dup in extras
  - `TestPyprojectTomlNumpyDep`: file exists, numpy version bounds, build-system
  - `TestRequirementsTxtNumpyDep`: numpy version bounds
  - `TestNumpyVersionConsistency`: all three files share the same lower bound; numpy importable

**Result: 3,627 pass, 64 skip, 0 fail** (env with networkx+numpy; same 207 missed lines).

---

## [3.22.9] - 2026-02-22

### Fixed — Numpy Skip Guards for Sessions 52/53 (Session 54)

**3 test failures fixed by adding `_skip_no_numpy` marks (no production code changed).**

**Root cause:** `ipld.py` imports `ipfs_datasets_py.vector_stores.ipld`, which has a
hard `import numpy as np` at module level. Tests that reloaded `ipld.py` or imported
`IPLDKnowledgeGraph` from it would fail in environments without numpy installed.

#### Tests updated:
- `test_master_status_session52.py::TestIpldCarAvailable::test_have_ipld_car_true_when_mock_available`
- `test_master_status_session52.py::TestIpldCarAvailable::test_ipld_car_attribute_set_when_available`
- `test_master_status_session53.py::TestGetConnectedEntitiesDepthInvariant::test_get_connected_entities_returns_correct_neighbors`

**Pattern used:** `_numpy_available = bool(importlib.util.find_spec("numpy"))` +
`_skip_no_numpy = pytest.mark.skipif(not _numpy_available, reason="numpy not installed")`
— consistent with sessions 40/41/50.

**Result: 3,490 pass, 77 skip, 0 fail** (base env without numpy).

---

## [3.22.8] - 2026-02-22

### Changed — Dead Code Cleanup + Invariant Tests (Session 53)

**Removed 14 lines of confirmed dead code from 3 files; 15 new invariant tests.**

**Coverage improvement: 213→207 missed lines (−6 dead code lines removed from coverage tracking)**

#### Dead code removed:

1. **`cypher/compiler.py:185-186, 212-213`** (4 lines removed)
   - `if not variable: variable = f"_anon{...}"` after `variable = element.variable or f"_n{i}"`
   - `f"_n{i}"` is always truthy → the guard could never fire

2. **`core/ir_executor.py:433-442`** (8 lines removed)
   - `if value is None and hasattr(record, "_values"): obj = record._values.get(var_name) ...`
   - `Record._values` is a `tuple` (not a dict), so `_values.get()` always raised `AttributeError`
   - The entire block was unreachable before the `except (AttributeError, …)` clause caught it

3. **`ipld.py:753-754`** (2 lines removed)
   - `if not source_result: continue` in `vector_augmented_query`
   - `source_result` is found by searching `graph_results` for an entity_id that was derived from
     the same `graph_results` list — it can never be `None`

4. **`ipld.py:1122-1123`** (2 lines removed)
   - `if depth > max_hops: continue` in `_get_connected_entities` BFS
   - Items are only enqueued when `depth < max_hops` → max queue depth = `max_hops` → guard unreachable

**Files changed:**
- `ipfs_datasets_py/knowledge_graphs/cypher/compiler.py` — removed 4 dead lines
- `ipfs_datasets_py/knowledge_graphs/core/ir_executor.py` — removed 8 dead lines
- `ipfs_datasets_py/knowledge_graphs/ipld.py` — removed 4 dead lines
- `tests/unit/knowledge_graphs/test_master_status_session53.py` — new file, 15 tests
- `ipfs_datasets_py/knowledge_graphs/MASTER_STATUS.md` — version 3.22.7→3.22.8
- `ipfs_datasets_py/knowledge_graphs/IMPROVEMENT_TODO.md` — session 53 log
- `ipfs_datasets_py/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` — this entry

**Result: 3,614 pass, 64 skip, 0 fail (base env); 207 missed lines**

---

## [3.22.7] - 2026-02-22

### Tests — ImportError Except Branches (Session 52)

**17 new tests** in `test_master_status_session52.py`. No production code changes.

**Coverage improvement: 229→213 missed lines (16 new lines covered)**

- `reasoning/types.py:24-26` — `numpy` ImportError except: `np=None`, `_NpNdarray=None` (3 lines, now 100%)
- `lineage/core.py:18-20` — `networkx` ImportError except: `NETWORKX_AVAILABLE=False`, `nx=None` (3 lines, now 100%)
- `neo4j_compat/driver.py:35-38` — `router_deps` ImportError except: `HAVE_DEPS=False`, stubs set (4 lines, now 100%)
- `reasoning/cross_document.py:31-32` — numpy ImportError except: `np=None` (2 lines, now 99%)
- `reasoning/cross_document.py:64-66` — optimizer ImportError except: `UnifiedGraphRAGQueryOptimizer=None` (3 lines, now 99%)
- `ipld.py:98` — `HAVE_IPLD_CAR=True` when `ipld_car` mock available via `sys.modules` (1 line, now 99%)

**Key technique**: `_reload_with_absent_dep(module_name, absent_deps)` helper reloads a module
with specified deps blocked in `sys.modules` (set to `None`). Critically, also saves/restores the
**parent package attribute** (e.g., `reasoning.cross_document`) to prevent state leakage into
other tests that import the module via `import pkg.submod as m` pattern.

**Files changed:**
- `tests/unit/knowledge_graphs/test_master_status_session52.py` — new file, 17 tests
- `ipfs_datasets_py/knowledge_graphs/MASTER_STATUS.md` — version 3.22.6→3.22.7
- `ipfs_datasets_py/knowledge_graphs/IMPROVEMENT_TODO.md` — session 52 log
- `ipfs_datasets_py/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` — this entry

**Result: 3,599 pass, 64 skip, 0 fail (base env); 213 missed lines (−16 from session 51)**

---

## [3.22.6] - 2026-02-22

### Tests — BFS Guard + ImportError Exception Coverage (Session 51)

**13 new tests** in `test_master_status_session51.py`. No production code changes.

**Coverage improvement:**
- `query/hybrid_search.py:217` — BFS already-visited guard now covered; `hybrid_search.py` reaches **100%**. The guard fires when diamond-topology graph puts the same node in `current_level` for hop N+1 after it was already visited during hop N (A→B, A→C, B→C topology).
- `migration/formats.py:914, 921-930, 950-951` — `_builtin_save_car` / `_builtin_load_car` ImportError paths now exercised via `sys.modules` injection (simulating absent libipld/ipld-car).
- `extraction/_entity_helpers.py:117` — Filter logic documented; the actual regex patterns cannot produce <2-char groups in normal use (all use `[A-Z][a-z]+`), confirming line 117 is unreachable in standard execution.

**Files changed:**
- `tests/unit/knowledge_graphs/test_master_status_session51.py` — new file, 13 tests
- `ipfs_datasets_py/knowledge_graphs/MASTER_STATUS.md` — version 3.22.5→3.22.6, test count updated
- `ipfs_datasets_py/knowledge_graphs/IMPROVEMENT_TODO.md` — session 51 log entry added
- `ipfs_datasets_py/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` — this entry

**Result: 3,582 pass, 64 skip, 0 fail** (base env); 229 missed lines (down from 230).

---

## [3.22.5] - 2026-02-22

### Tests — numpy-via-networkx Skip Guards (Session 50)

**No new tests, no production code changes.** Fixed 7 test failures that appeared when networkx is installed (networkx imports numpy as a soft dependency that becomes importable) but numpy is not directly available.

**Files changed:**
- `tests/unit/knowledge_graphs/test_master_status_session16.py`
- `tests/unit/knowledge_graphs/test_master_status_session21.py`
- `tests/unit/knowledge_graphs/test_master_status_session33.py`

**Problem 1 (session16, 3 tests):** `TestLineageVisualizerPlotly` tests mock `plotly.graph_objs` (go) but `render_plotly()` also calls `nx.spring_layout()` which requires numpy. The tests called the real `nx.spring_layout` and crashed.

**Fix:** Added `patch("networkx.spring_layout", return_value={node: (x, y)})` to `test_render_plotly_with_mocked_plotly`, `test_render_plotly_with_output_path`, and `test_visualize_lineage_plotly_renderer`.

**Problem 2 (session21, 3 tests):** `TestCrossDocumentReasonerUncoveredPaths` has 3 tests with `import numpy as np` inside the method body. These tests pass when numpy is available but crash with `ModuleNotFoundError` when numpy is absent.

**Fix:** Added `_numpy_available` flag and `_skip_no_numpy` mark at module level; applied `@_skip_no_numpy` to the 3 individual numpy-dependent methods only (9 other tests in the class still run without numpy).

**Problem 3 (session33, 1 test):** `test_numpy_available_flag` in `TestCrossDocumentReasonerMissedPaths` similarly uses `import numpy as np_real` inline.

**Fix:** Added `_numpy_available = bool(importlib.util.find_spec("numpy"))` to the module-level constants (alongside the existing `_rdflib_available`) and applied `@pytest.mark.skipif(not _numpy_available, reason="numpy not installed")` to that one method.

**Verification:**
- Without numpy: 7 previously-failing tests now skip cleanly
- With numpy: all 7 tests continue to pass
- Full suite (base env, networkx installed, numpy absent): **3,448 passed, 74 skipped, 0 failed**

---

## [3.22.4] - 2026-02-22

### Tests — numpy Skip Guards (Session 49)

**No new tests, no production code changes.** Fixed collection errors in two test files.

**Files changed:**
- `tests/unit/knowledge_graphs/test_master_status_session41.py`
- `tests/unit/knowledge_graphs/test_master_status_session42.py`

**Problem:** Both files had `import numpy as np` at module level (before `import pytest`), which caused a `ModuleNotFoundError` collection error — not a graceful skip — in environments without numpy installed.

**Fix:** In both files:
1. Moved `import pytest` before the numpy import
2. Replaced `import numpy as np` with `np = pytest.importorskip("numpy")`

This is consistent with the `pytest.importorskip` pattern used throughout the KG test suite for other optional dependencies (`spacy`, `rdflib`, `matplotlib`, `libipld`).

**Verification:**
- With numpy installed: all 91 tests in sessions 41+42 still pass
- Without numpy: sessions 41+42 are skipped cleanly (no collection error)
- Full suite (base env): **3,569 passed, 64 skipped, 0 failed**
- Full suite (all optional deps): **3,626 passed, 7 skipped, 0 failed**

---

## [3.22.3] - 2026-02-22

### Tests — Final Coverage Push (Session 48)

**16 new tests** in `test_master_status_session48.py`. No production code changes.

**New optional deps installed (unlocks more coverage):** `libipld`, `ipld-car`, `dag-cbor`, `multiformats`
- `migration/formats.py` now **100%** — CAR format save/load paths now exercised by existing property-based tests.

**New test groups:**

1. **`cypher/compiler.py:261`** — `_compile_node_pattern` anonymous variable fallback (`_anon{N}`) when both `node.variable` and `default_var` are `None`/empty string (5 tests):
   - Anon variable is generated and registered in `compiler.variables`
   - `ScanLabel` op emitted with auto-generated variable
   - `ScanAll` op emitted when no labels provided
   - Multiple consecutive anon nodes get unique `_anon0`, `_anon1` variables
   - Empty-string `node.variable` also triggers anon generation

2. **`core/expression_evaluator.py:153-163`** — `reverse` and `size` fallback string handlers (8 tests):
   - These handlers run when the function names are temporarily absent from `FUNCTION_REGISTRY`
   - `reverse`: reverses string / returns `None` for non-string / returns `None` for empty args
   - `size`: returns `len()` for strings / lists / tuples; returns `None` for empty args; returns `None` for non-sequence types

3. **`ontology/reasoning.py:828`** — BFS transitive closure cycle guard `if mid in visited: continue` (3 tests):
   - Triggered by A→B→C→B cycle: B is popped from the BFS queue a second time; line 828 fires and skips it
   - BFS terminates cleanly for longer cycles (A→B→C→D→B)
   - No duplicate inferred relationships added despite cycle

**Coverage impact:** `expression_evaluator.py` 97%→**100%**; `ontology/reasoning.py` 99%→**100%**; `migration/formats.py` 98%→**100%**; `compiler.py` misses reduced from 3→2; overall **99%** (159→141 missed lines).

**Result:** 3,626 passing, 7 skipped, 0 failing (with all optional deps installed).

---

## [3.22.2] - 2026-02-22

### Bug Fix — RDF Boolean Serialization Order (Session 47)

**Production bug fixed in `extraction/graph.py`:**

- **Entity properties** (`export_to_rdf` match block, line ~622): `case bool():` was listed AFTER `case int():`. In Python, `bool` is a subclass of `int`, so `case int():` was matching `True`/`False` first, causing boolean properties to be serialized as `XSD.integer` instead of `XSD.boolean`. Fixed by moving `case bool():` before `case int():`.
  - Before: `True` → `"1"^^xsd:integer` (wrong)
  - After: `True` → `"true"^^xsd:boolean` (correct)

- **Relationship properties** (`export_to_rdf` elif block, line ~654): Same issue with `elif isinstance(value, int):` coming before `elif isinstance(value, bool):`. Fixed by moving `elif isinstance(value, bool):` before `elif isinstance(value, int):`.

**New tests** (`test_master_status_session47.py`, 9 tests):
- `TestExportToRdfEntityNonPrimitiveProperty` (4 tests) — list/None/dict/tuple entity properties hit `case _:` catch-all and use `str(value)` fallback
- `TestExportToRdfRelationshipNonPrimitiveProperty` (5 tests) — same for relationship properties + confirm bool correctly uses XSD.boolean

**Coverage impact:** `extraction/graph.py` 99%→**100%**; overall 98%→**99%** (203→159 missed lines)

**Result:** 3,591 passing, 26 skipped, 0 failing (with matplotlib+scipy+plotly+rdflib); 3,553/55/0 in base environment.

---

## [3.22.1] - 2026-02-22

### Bug Fixes — rdflib Optional Dependency Skip Guards (Session 46)

- **`test_master_status_session33.py`** — Added `_rdflib_available = bool(importlib.util.find_spec("rdflib"))` + `@pytest.mark.skipif(not _rdflib_available, reason="rdflib not installed")` guards to 2 tests that call `export_to_rdf()`: `test_export_to_rdf_entity_boolean_property_uses_xsd_boolean` and `test_export_to_rdf_relationship_boolean_property_uses_xsd_boolean`.
- **`test_master_status_session37.py`** — Added matching class-level `@pytest.mark.skipif` guard to `TestKnowledgeGraphExportBooleanProperty` class.
- **Result:** 3,553 passing, 55 skipped (intentional), 0 failing in base environment (no rdflib).

### Documentation Updates

- **`ROADMAP.md`** — Updated current version from 2.1.0 to v3.22.0; added v3.22.0 section; updated release table; updated community priority list to note 99%+ coverage achieved.
- **`MASTER_STATUS.md`** — Updated "Last Updated" to session 46; corrected test count to 3,553/55/0; added sessions 33-46 to test file list.
- **`IMPROVEMENT_TODO.md`** — Added sessions 33-46 detailed log entries.

---

## [3.22.0] - 2026-02-22

### Bug Fixes — Async Safety + Test Environment Hardening (Session 45)

This release fixes 95 pre-existing test failures across two categories: production async-safety bugs and test skip guards for optional dependencies.

#### Production Bug Fixes

- **`anyio.get_cancelled_exc_class()` outside async context** — Fixed in 4 modules:
  - `query/unified_engine.py`: added `_cancelled_exc_class()` helper that falls back to `asyncio.CancelledError` when no event loop is active; replaced 5 `except anyio.get_cancelled_exc_class():` calls.
  - `transactions/wal.py`: same helper added; replaced 6 calls.
  - `storage/ipld_backend.py`: same helper added; replaced 3 calls.
  - `query/hybrid_search.py`: same helper added; replaced 3 calls.
  - Root cause: newer anyio versions raise `anyio.NoEventLoopError` when `get_cancelled_exc_class()` is called outside an async event loop, breaking synchronous error-handling paths.

- **`ipld.py` missing `ipld_car` module attribute** — Added `ipld_car = None` to the `except ImportError` block so the module-level attribute is always defined (patchable) even when `ipld-car` is not installed. Tests patching `_IPLD.ipld_car` now work correctly.

#### Test Environment Fixes

- **`test_master_status_session43.py`** — Added `pytest.importorskip("spacy")` at module level; all 32 tests are properly skipped when spaCy is absent.
- **`test_master_status_session44.py`** — Added per-class `@_skip_no_spacy` marks for `TestExtractorSpacyModelOSError` and `TestExtractEntitiesLowConfidenceSkip`; non-spaCy tests continue running.
- **`test_master_status_session15.py`** — Added `@_skip_no_matplotlib` decorator to `TestLineageVisualizerRenderNetworkx` class and two methods in `TestVisualizeLinkageFunction`; non-matplotlib tests continue running.
- **`test_master_status_session37.py`** — Added `@pytest.mark.skipif` to `test_render_networkx_ghost_node_gets_lightgray`.
- **`test_master_status_session40.py`** — Added `@_skip_no_libipld` decorator to `TestBuiltinCarSaveLoad` class; non-libipld tests continue running.
- **`test_master_status_session21.py`** — Fixed `test_default_query_optimizer_is_missing_stub` to patch `UnifiedGraphRAGQueryOptimizer` to `None` before constructing `CrossDocumentReasoner`; test now works regardless of whether GraphRAG deps are installed.
- **`test_master_status_session42.py`** — Fixed `TestFromCarEmptyRoots` and `TestExportToCar` to also patch `HAVE_IPLD_CAR = True` alongside `ipld_car`; tests now reach the actual CAR logic instead of the early ImportError guard.

**Result:** 3,567 passing (in full-deps env), 41 skipped (all intentional), 0 failing. Base env without rdflib: 3,553 pass, 55 skip (rdflib skip guards added in v3.22.1).

---

## [2.1.0] - 2026-02-20

### Cypher Feature Completion + Folder Refactoring

This release completes all Cypher clause features, restructures the module folder to permanent canonical subpackage locations, and adds three new MCP tools.

### Added

#### Cypher Clauses (All Clauses Now Complete)
- **FOREACH clause**: `FOREACH (variable IN list | clause*)` — iterate a list and apply mutation clauses (CREATE, SET, MERGE, DELETE, REMOVE) to each element.
- **CALL subquery**: `CALL { inner_query } [YIELD ...]` — execute an inner query and merge its results into the outer query's bindings. Supports YIELD aliasing.
- Lexer: `FOREACH` added to `TokenType` enum and `KEYWORDS` dictionary
- AST: `ForeachClause(variable, expression, body)` and `CallSubquery(body, yield_items)` dataclasses
- Parser: `_parse_foreach()` and `_parse_call_subquery()` methods
- Compiler: `_compile_foreach()` and `_compile_call_subquery()` methods
- IR executor: `Foreach` and `CallSubquery` op handlers

#### New `reasoning/` Subpackage
- `reasoning/__init__.py` — re-exports all public names from sub-modules
- `reasoning/cross_document.py` — canonical home for `CrossDocumentReasoner`
- `reasoning/helpers.py` — canonical home for `ReasoningHelpersMixin`
- `reasoning/types.py` — canonical home for `InformationRelationType`, `DocumentNode`, etc.
- `reasoning/README.md` — subpackage documentation

#### New MCP Graph Tools
- `mcp_server/tools/graph_tools/graph_srl_extract.py` — SRL extraction tool
- `mcp_server/tools/graph_tools/graph_ontology_materialize.py` — OWL/RDFS inference tool
- `mcp_server/tools/graph_tools/graph_distributed_execute.py` — distributed Cypher tool

#### KnowledgeGraphManager Extensions
- `extract_srl(text, return_triples, return_temporal_graph)` — SRL extraction
- `ontology_materialize(graph_name, schema, check_consistency, explain)` — ontology inference
- `distributed_execute(query, num_partitions, partition_strategy, parallel, explain)` — distributed query

#### Folder Restructuring (Permanent Locations)
- `cross_document_reasoning.py` → `reasoning/cross_document.py`
- `_reasoning_helpers.py` → `reasoning/helpers.py`
- `cross_document_types.py` → `reasoning/types.py`
- `cross_document_lineage.py` → `lineage/cross_document.py`
- `cross_document_lineage_enhanced.py` → `lineage/cross_document_enhanced.py`
- `query_knowledge_graph.py` → `query/knowledge_graph.py`
- `sparql_query_templates.py` → `query/sparql_templates.py`
- `finance_graphrag.py` → `extraction/finance_graphrag.py`

### Changed
- All root-level moved files replaced with `DeprecationWarning` shims (100% backward compatible)
- `query/__init__.py` updated with `knowledge_graph` and `sparql_templates` exports
- `extraction/__init__.py` updated with `finance_graphrag` exports
- `lineage/__init__.py` updated with `cross_document` and `cross_document_enhanced` exports
- `graph_tools/__init__.py` updated with 3 new MCP tool exports
- All READMEs (module root, query/, extraction/, lineage/) updated for v2.1.0

### Tests
- 32 new tests in `tests/unit/knowledge_graphs/test_foreach_call_mcp.py`
- 26 pass, 6 skipped (anyio not installed in CI)
- Total: 1075+ passing (up from 1067)

---

## [2.0.0] - 2026-02-17

### Major Refactoring and Documentation Update

This release represents a comprehensive refactoring and documentation effort for the knowledge_graphs module, bringing it to production-ready status with extensive documentation, comprehensive testing, and clear roadmap.

### Added

#### Documentation (222KB Total)
- **USER_GUIDE.md** (30KB) - Comprehensive user guide with 10 sections and 40+ examples
  - Quick start, core concepts, extraction workflows
  - Query patterns, storage options, transaction management
  - Integration patterns, production best practices
  - Troubleshooting guide, examples gallery

- **API_REFERENCE.md** (35KB) - Complete API documentation
  - Extraction API (Entity, Relationship, KnowledgeGraph, Extractor)
  - Query API (UnifiedQueryEngine, QueryResult, GraphRAG, HybridSearch)
  - Storage API (IPLDBackend, IPFS integration)
  - Transaction API (TransactionManager, ACID transactions)
  - Cypher Language Reference with supported features
  - Utility and compatibility APIs
  - Error handling with exception types

- **ARCHITECTURE.md** (24KB) - Comprehensive architecture documentation
  - Module architecture (14 subdirectories, 4-layer design)
  - Design patterns (8 patterns with examples)
  - Component internals (extraction, query, storage, transactions)
  - Data flow diagrams, performance characteristics
  - Scalability patterns, extension points
  - Integration architecture, future enhancements

- **MIGRATION_GUIDE.md** (15KB) - Migration and compatibility guide
  - Known limitations with workarounds
  - Feature support matrix
  - Breaking changes documentation
  - Compatibility matrix (Python, dependencies, environment)
  - Neo4j to IPFS migration guide (4-step workflow)
  - Migration checklist, common issues with solutions
  - Deprecation timeline (v2.0 → v2.5 → v3.0)

- **CONTRIBUTING.md** (23KB) - Development guidelines
  - Advanced development patterns
  - Performance guidelines (temperature tuning, batch processing)
  - Security best practices (input validation, type safety)
  - Common pitfalls with solutions
  - Module-specific conventions
  - Debugging tips, release process
  - Maintenance guidelines

#### Subdirectory Documentation (81KB Total)
- **cypher/README.md** (8.5KB) - Cypher query language implementation
- **migration/README.md** (10.8KB) - Migration tools and workflows
- **core/README.md** (11.5KB) - Core graph database engine
- **neo4j_compat/README.md** (12KB) - Neo4j driver compatibility (~80%)
- **lineage/README.md** (11.9KB) - Cross-document entity tracking
- **indexing/README.md** (12.8KB) - Index management (20-100x speedup)
- **jsonld/README.md** (13.8KB) - W3C JSON-LD 1.1, RDF serialization

#### Code Documentation (14KB)
- **Future Roadmap** - Documented 7 planned features (v2.1 → v3.0)
  - v2.1.0 (Q2 2026): NOT operator, Relationship creation
  - v2.5.0 (Q3-Q4 2026): Neural extraction, spaCy parsing, SRL
  - v3.0.0 (Q1 2027): Multi-hop traversal, LLM integration

- **Enhanced Docstrings** - Comprehensive documentation for 5 complex methods
  - `_determine_relation()` in cross_document_reasoning.py
  - `_generate_traversal_paths()` in cross_document_reasoning.py
  - `_split_child()` in indexing/btree.py
  - `_calculate_score()` in indexing/specialized.py
  - `_detect_conflicts()` in transactions/manager.py

#### Testing (38KB Test Code)
- **Migration Module Tests** - 27 comprehensive tests for 70%+ coverage
  - Neo4j Export: 7 tests (basic, relationships, batching, errors, properties, deduplication)
  - IPFS Import: 7 tests (CID, file, relationships, errors, IPLD, metadata)
  - Format Conversion: 6 tests (JSON, CSV, unsupported formats)
  - Schema Checking: 4 tests (validation, migration detection/execution)
  - Integrity Verification: 3 tests (validation, broken references, repair)

- **Integration Tests** - 9 end-to-end workflow tests
  - Extract → Validate → Query Pipeline: 3 tests
  - Neo4j → IPFS Migration Workflow: 3 tests
  - Multi-document Reasoning Pipeline: 3 tests

### Changed

#### Documentation Improvements
- Documented 2 NotImplementedError instances as known limitations
- Added CSV/JSON workarounds for unsupported formats (GraphML, GEXF, Pajek)
- Enhanced future enhancements section with technical specifications
- Added roadmap section with version timeline and priorities

#### Code Quality
- Enhanced docstrings now include:
  - Algorithm explanations with complexity analysis
  - Usage examples with realistic scenarios
  - Production considerations and best practices
  - Visual aids (ASCII diagrams where applicable)
  
### Fixed
- Clarified Cypher language limitations (NOT operator, CREATE relationships)
- Documented extraction limitations with future solutions
- Added workarounds for all known limitations

### Performance
- Documented performance characteristics:
  - Extraction: 2-100x speedup with parallel processing
  - Query: <100ms hybrid search target
  - Indexing: 20-100x query speedup with proper indexes
  - Parallel Processing: 4-16x gains with multiprocessing

### Security
- Documented security best practices:
  - Input validation patterns
  - Type safety with type hints
  - Exception handling best practices
  - Resource cleanup patterns

### Compatibility
- **Python:** 3.8+ supported, 3.10+ recommended
- **Neo4j API:** ~80% compatibility
- **W3C Standards:** JSON-LD 1.1 compliant
- **RDF Formats:** 5 formats supported (Turtle, N-Triples, RDF/XML, JSON-LD, N-Quads)

## [1.0.0] - Previous Release

### Initial Release
- Basic knowledge graph extraction
- IPLD storage support
- Cross-document reasoning
- Legacy API

---

## Migration Notes

### From v1.x to v2.0

**Breaking Changes:**
- Legacy IPLD API deprecated (use Neo4j-compatible API)
- Some extraction parameters renamed for clarity
- Budget presets modified for better defaults

**Migration Steps:**
1. Update imports to use new API
2. Replace legacy IPLD calls with Neo4j-compatible API
3. Update budget configurations if using custom settings
4. Test extraction and query workflows
5. Update deployment configurations

See MIGRATION_GUIDE.md for detailed migration instructions.

---

## Statistics

### Documentation Coverage
- **Total:** 222KB production-ready documentation
- **Major Docs:** 5 comprehensive guides (127KB)
- **Module Docs:** 7 subdirectory READMEs (81KB)
- **Code Docs:** Enhanced docstrings and roadmap (14KB)

### Test Coverage
- **Migration Module:** 40% → 70%+ (27 new tests)
- **Integration Tests:** 9 end-to-end workflow tests
- **Total New Tests:** 36 comprehensive tests

### Quality Metrics
- **Code Examples:** 150+ working examples
- **Reference Tables:** 60+ comparison and feature tables
- **Standards Compliance:** W3C JSON-LD 1.1, Neo4j API ~80%
- **Breaking Changes:** Documented with migration paths

---

## Roadmap

### v2.1.0 (Q2 2026) - Query Language Enhancement
- NOT operator support in Cypher
- CREATE relationship statement support
- Enhanced query optimization

### v2.5.0 (Q3-Q4 2026) - Advanced Extraction
- Neural relationship extraction
- Aggressive extraction with spaCy dependency parsing
- Complex relationship inference with Semantic Role Labeling (SRL)

### v3.0.0 (Q1 2027) - Advanced Reasoning
- Multi-hop graph traversal for indirect connections
- LLM API integration (OpenAI, Anthropic, local models)
- Advanced temporal reasoning
- Federated query support

---

## Contributors

This refactoring effort involved comprehensive documentation, testing, and code quality improvements across the entire knowledge_graphs module.

**Refactoring Statistics:**
- Duration: 30 hours across 6 sessions
- Files Modified: 20+ documentation and code files
- New Content: 260KB (222KB docs + 38KB tests)
- Commits: 13 comprehensive commits

---

For detailed information about any feature or change, see the corresponding documentation files in the `docs/knowledge_graphs/` directory.
