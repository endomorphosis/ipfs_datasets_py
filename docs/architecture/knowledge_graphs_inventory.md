# Knowledge Graphs Inventory (KGP-002)

**Program:** `KGP`  
**Task:** `KGP-002`  
**Inventoried at:** 2026-07-29  
**Machine registry:** `tests/fixtures/knowledge_graphs/corpus_registry.json`  
**Canonical baseline tree:** `6672d69242731f53b49f4f793ed3023b7ba36a0d`

This document is the human-readable inventory of graph producers, artifacts,
schemas, and consumers discovered across `lift_coding`, canonical
`ipfs_datasets_py`, `ipfs_accelerate_py`, and `211-AI`. It does not migrate any
producer. Existing producers remain authoritative until parity evidence passes.

## Authority rules

| Rule | Detail |
| --- | --- |
| Canonical implementation tree | `/home/barberb/ipfs_datasets_py` at `6672d692…` |
| Nested lift checkouts | **Fixture-only.** Never the implementation source of truth. |
| Stale dirty nested lift | `/home/barberb/lift_coding/external/ipfs_datasets` and `…/hallucinate_app/ipfs_datasets_py` at `d144be65…` (dirty) are input fixtures only. |
| CVEfixes producer code | Currently lives under a **non-canonical** nested tree; treat as fixture-only producer snapshot until ported to the canonical tree. |
| Domain owners | 211-AI owns retrieval/browser graphs; accelerate owns supervisor graphs; datasets owns SkillCenter / platform APIs. |

## Repository map

| Repository ID | Path | Commit | Clean | Role | Fixture-only |
| --- | --- | --- | --- | --- | --- |
| `canonical_ipfs_datasets_py` | `/home/barberb/ipfs_datasets_py` | `6672d69242731f53b49f4f793ed3023b7ba36a0d` | no (13 dirty entries) | Canonical KGP implementation | no |
| `lift_coding` | `/home/barberb/lift_coding` | `51dded3b691682791be15d161d01ce94c5944fa1` | no (10) | Artifact host / orchestration | no |
| `ipfs_accelerate_py` | `/home/barberb/ipfs_accelerate_py` | `ff401f83b7e722e58af1696243b3aff9679a7002` | no (10) | Supervisor graph owner | no |
| `two11_ai` | `/home/barberb/211-AI` | `31e2d2f96cad71e00789523cc81c9e16f6d4ce2f` | no (2) | 211 retrieval / browser graphs | no |
| `nested_lift_external_datasets` | `lift_coding/external/ipfs_datasets` | `d144be65ffe4c6423e4e1c30cd692812607343eb` | **dirty** | Stale nested checkout | **yes** |
| `nested_lift_hallucinate_datasets` | `lift_coding/hallucinate_app/ipfs_datasets_py` | `d144be65…` | **dirty** | Stale nested checkout | **yes** |
| `nested_lift_cve_producer_tree` | `lift_coding/data/logic_software_verification_program/repo/ipfs_datasets_py` | `de5697097341f630644977565238dd204ae1f8a1` | clean | Non-canonical CVEfixes producer snapshot | **yes** |
| `nested_unblocking_datasets` | `lift_coding/data/…/unblocking_fix/ipfs_datasets_py` | `66085f6a…` | clean | Nested snapshot | **yes** |
| `nested_accelerate_datasets` | `ipfs_accelerate_py/ipfs_datasets_py` | `6672d692…` | dirty | Vendored mirror | **yes** |
| `nested_211_datasets` | `211-AI/ipfs_datasets_py` | `31e2d2f…` | dirty | Vendored mirror | **yes** |

### Fixture-only nested lift checkouts (mandatory flag)

The following nested `ipfs_datasets_py` trees under `lift_coding` are
**fixture-only**. KGP implementation must not edit them or treat them as the
platform source of truth:

1. **`/home/barberb/lift_coding/external/ipfs_datasets`** — commit `d144be65…`,
   **stale and dirty** (dependency catalog / requirements edits). Input fixture
   only.
2. **`/home/barberb/lift_coding/hallucinate_app/ipfs_datasets_py`** — same
   commit family, **dirty**. Input fixture only.
3. **`…/logic_software_verification_program/repo/ipfs_datasets_py`** — commit
   `de569709…`, hosts CVEfixes Security IR GraphRAG producer modules that are
   **not** present on canonical `6672d692…`. Fixture-only producer snapshot;
   migration target is the canonical tree after KGP control-plane readiness.
4. **`…/unblocking_fix/ipfs_datasets_py`** — nested snapshot, fixture-only.

## Mandatory graph kinds

### 1. `cvefixes_security_ir_graphrag`

| Field | Value |
| --- | --- |
| Display name | CVEfixes Security IR GraphRAG |
| Authoritative owner | `lift_coding` (artifacts) + nested CVE producer tree (code; non-canonical) |
| Fixture-only producer | **yes** (producer modules not on canonical tree) |
| Producers | `…/logic/security_ir/cvefixes/{graph,projector,hf_release,hf_source,retrieval}.py`; `scripts/ops/security_ir/publish_cvefixes_security_ir.py` |
| Consumers | `ipfs_datasets_py.logic.security_ir` adapter path; agent supervisor security gates; HF `Publicus/cvefixes-security-ir-graphrag` |
| Artifact root | `/home/barberb/lift_coding/.cvefixes-build` (5.0G total) |
| Primary release | `release-with-original-v2` (~1.5G) |
| Source Parquet | `source/data` (~1.2G, 12,987 original rows) |
| Schema | release `cvefixes-huggingface-release/v1`; graph `cvefixes-graphrag-graph/v1`; ontology `cvefixes-graphrag-ontology/v1`; primary key `entry_cid` |
| Format | Parquet shards + JSON manifest + bounded adjacency pages |
| Counts | **85,169 nodes / 167,364 edges**; 123,585 corpus/vector rows; 110 graph data shards |
| Provenance | source `hitoshura25/cvefixes@d4f5c4ea…`; graph root CID `bafkreielsquxgqxh6qzb3444bqjlicl34fxqtkyjebwa5h3vqhtaygynee`; license Apache-2.0; program `CVESIR` |
| Migration risk | **high** — non-canonical producer, multi-GB artifacts, original-body release profile |

### 2. `skillcenter_ir_graphrag`

| Field | Value |
| --- | --- |
| Display name | SkillCenter Intent IR GraphRAG |
| Authoritative owner | canonical `ipfs_datasets_py` (`logic/intent_ir/graphrag`) |
| Producers | `skillcenter_hf_release.py`, `skillcenter_graphrag.py`, `skillcenter_cid_graph.py`, corpus/BM25/embedding builders; `scripts/ops/intent_ir/build_skillcenter_*.py` |
| Consumers | Intent IR retrieval/formalizer; HF `Publicus/skillcenter-ir`; unit tests under `tests/unit/logic/intent_ir/graphrag` |
| Artifacts | HF hub + local skillcenter cache (~13M cache dir); reference manifest under `.cvefixes-build/skillcenter-reference` |
| Schema | release `skillcenter-huggingface-release/v3` (v2 compat); adjacency `skillcenter-hf-graph-adjacency/v1`; vector chunk v2; corpus graph `intent-corpus-graph/v1` / ontology `intent-corpus-ontology/v1`; primary key `entry_cid` |
| Format | CID-keyed Parquet, BM25 postings, optional FAISS, JSON manifests |
| Counts | **434,135 nodes / 2,560,637 edges**; 216,972 corpus/vector rows; ~108M BM25 postings |
| Provenance | source `Tommysha/skillcenter-bundles`; derived `Publicus/skillcenter-ir@f9dd4fec…` |
| Migration risk | **medium** — canonical producer; hybrid layout + schema v2/v3 compatibility |

### 3. `two11_retrieval_package`

| Field | Value |
| --- | --- |
| Display name | 211-AI retrieval package knowledge graph |
| Authoritative owner | `211-AI` |
| Producers | `scraper/build_retrieval_package.py` |
| Consumers | browser GraphRAG builder, portal packages, retrieval benchmarks, wallet UI |
| Artifact root | `/home/barberb/211-AI/data/retrieval_package` (**184M**) |
| Schema | `manifest/build_manifest.json` (CID `bafkreifgjbpyynwyebcdfvc2bozwusbhza42xw6w4kutguicfscqovm67a`); embedding model `BAAI/bge-small-en-v1.5` |
| Format | Parquet (documents, BM25, vectors, nodes, edges, communities) + JSON manifest |
| Counts | **48,851 nodes / 648,958 edges**; 22,638 documents/embeddings; 41 communities; 3,191,432 BM25 terms |
| Provenance | DuckDB warehouse `data/live/state/etl_warehouse.duckdb` |
| Migration risk | **medium** — stable package with CIDs; hybrid retrieval coupling |

### 4. `two11_browser_graphrag`

| Field | Value |
| --- | --- |
| Display name | 211-AI browser GraphRAG export |
| Authoritative owner | `211-AI` |
| Producers | `scraper/browser_graphrag_corpus.py`, `scripts/build_browser_graphrag_corpus.py`, `scripts/shard_browser_corpus_parquets.py` |
| Consumers | wallet UI public corpus path; browser corpus tests; wallet release checks |
| Artifacts | smoke fixtures under `data/browser_graphrag_smoke{,_sharded,_dedup}` (~300K each); full wallet export path `wallet_interface/ui/public/corpus/211-info/current` |
| Schema | `schemaVersion: 1` generated manifest; browser model `Xenova/bge-small-en-v1.5` |
| Format | JSON documents/neighborhoods/communities + f32 embeddings; optional neighborhood shards |
| Counts | smoke: 25 docs / 25 neighborhoods / 11 communities (3 shards in sharded variant); source package counts referenced in smoke manifests (~48,864 / 649,052) |
| Provenance | derived from retrieval package build manifest CID above |
| Migration risk | **low** — small projection; must stay CID-aligned with retrieval package |

### 5. `supervisor_objective_graph`

| Field | Value |
| --- | --- |
| Display name | Agent supervisor objective graph |
| Authoritative owner | `ipfs_accelerate_py` |
| Producers | `agent_supervisor/objective_graph.py` (+ tracker/daemon) |
| Consumers | implementation daemon, bundle planner, program `objective_graph.json` files |
| Primary artifact | `data/agent_supervisor/knowledge_graphs_production_hardening/objective_graph.json` (60,999 bytes) |
| Schema | `ipfs_accelerate_py.agent_supervisor.objective_graph` (+ thought graph schema) |
| Format | JSON |
| Counts (KGP program) | 11 goals (all active); 11 nodes / 10 edges; 19 evidence nodes/edges |
| Migration risk | **low** — supervisor remains authoritative |

### 6. `supervisor_ast_index`

| Field | Value |
| --- | --- |
| Display name | Analysis AST index |
| Authoritative owner | `ipfs_accelerate_py` |
| Producers | `analysis_ast_index.py`; blob schema owned by `conflict_graph.ASTBlobRecord` |
| Consumers | conflict graph, code-evidence graph, scan/impact analysis |
| Schema | `ipfs_accelerate_py/agent-supervisor/analysis-ast-index@1` (version 1); AST blob record schema version 1 |
| Format | JSON records / content-addressed blobs |
| Migration risk | **low** — path projection over immutable blobs |

### 7. `supervisor_code_evidence_graph`

| Field | Value |
| --- | --- |
| Display name | Code evidence graph |
| Authoritative owner | `ipfs_accelerate_py` |
| Producers | `code_evidence_graph.py`, `prover_evidence_store.py` |
| Consumers | merge/completion gates, objective evidence edges |
| Schema | `code-evidence-graph@1`, node/edge/impact-index companion schemas |
| Format | JSON |
| Authority boundary | Projection of trusted supervisor records only; GraphRAG cannot mint proof facts |
| Migration risk | **low** |

### 8. `supervisor_conflict_graph`

| Field | Value |
| --- | --- |
| Display name | Conflict / lane coloring graph |
| Authoritative owner | `ipfs_accelerate_py` |
| Producers | `conflict_graph.py`, `merge_conflict_repair.py` |
| Consumers | parallel lane planner, todo daemon |
| Schema | `conflict_graph@1`; work contracts `@1` |
| Format | JSON |
| Migration risk | **low** |

### 9. `supervisor_semantic_dependency_graph`

| Field | Value |
| --- | --- |
| Display name | Semantic dependency graph |
| Authoritative owner | `ipfs_accelerate_py` |
| Producers | `semantic_dependency_graph.py` |
| Consumers | mandatory closure / authority checks |
| Schema | semantic-dependency graph/node/edge `@1`; mandatory-closure `@1` |
| Bounds | default max 16,384 nodes / 65,536 edges / depth 256 |
| Migration risk | **low** |

## Other discovered graph kinds

| Kind | Owner | Producers (summary) | Format | Migration risk | Notes |
| --- | --- | --- | --- | --- | --- |
| `platform_graph_engine` | canonical datasets | `knowledge_graphs/core/graph_engine.py`, extraction, MCP graph tools, CLI | in-memory / partial storage | **critical** | Platform under repair (KGP); non-durable lifecycle |
| `sharded_car_v1` | canonical datasets | `search/graph_query/sharded_car/*` | CAR + IPLD manifest v1 | medium | Starting point for KGP v1/v2 sharding |
| `website_graphrag` | canonical datasets | website GraphRAG processors | processor outputs | medium | No shared multi-GB corpus in this pass |
| `pdf_graphrag_integrator` | canonical datasets | PDF GraphRAGIntegrator + MCP tool | document-scoped | medium | Ephemeral per integration |
| `finance_graphrag` | canonical datasets | `knowledge_graphs/finance_graphrag.py` | extraction records | low | Domain extractor |
| `ipld_legacy_knowledge_graph` | canonical datasets | `knowledge_graphs/ipld.py` | IPLD / DAG-CBOR | **high** | Legacy; prefer modern adapters |
| `logic_aware_knowledge_graph` | canonical datasets | `search/logic_integration/*` | search-coupled | medium | Distinct from Intent IR ontology |
| `intent_corpus_evidence_graph` | canonical datasets | `logic/intent_ir/graphrag/ontology.py` + projectors | digest-bound records | medium | Underpins SkillCenter corpus graph |
| `ipfs_kit_ipld_knowledge_graph` | accelerate / kit | `ipfs_kit_py` IPLD + GraphRAG helpers | IPLD/CAR/VFS | medium | Storage capability surface for KGP-G040 |

## Producer → consumer summary

```text
hitoshura25/cvefixes ──► [nested] security_ir/cvefixes ──► .cvefixes-build ──► HF Publicus/cvefixes-security-ir-graphrag
                                                                              └─► supervisor security gates

Tommysha/skillcenter-bundles ──► intent_ir/graphrag (canonical) ──► Publicus/skillcenter-ir
                                                                  └─► Intent IR retrieval / formalizer

211 warehouse ──► build_retrieval_package ──► data/retrieval_package (parquet graph)
                                           └─► browser_graphrag_corpus ──► wallet UI JSON corpus

objectives.md ──► objective_graph.py ──► objective_graph.json ──► implementation daemon / bundles
repo sources ──► conflict_graph / analysis_ast_index ──► code_evidence / semantic_dependency ──► gates

CLI / MCP / Python ──► knowledge_graphs.* (broken lifecycle today) ──► KGP GraphService (target)
```

## Migration risk ranking

| Risk | Graph kinds |
| --- | --- |
| critical | `platform_graph_engine` |
| high | `cvefixes_security_ir_graphrag`, `ipld_legacy_knowledge_graph` |
| medium | SkillCenter, 211 retrieval, sharded CAR, website/PDF/logic-aware/intent corpus, ipfs_kit helpers |
| low | 211 browser export, all supervisor graphs, finance extractor |

## Inventory gaps / follow-ups

1. Port CVEfixes producer modules from the nested fixture tree onto the
   canonical repository only after control-plane contracts (KGP-003+) exist.
2. Record full-wallet browser corpus counts when the production export under
   `wallet_interface/ui/public/corpus/211-info/current` is rebuilt.
3. Materialize on-disk supervisor AST/conflict/code-evidence samples under a
   durable KGP fixture directory for differential tests (today they are mostly
   program-ephemeral).
4. Do not promote nested dirty lift checkouts; continue to treat them as
   read-only input fixtures.

## Validation

```bash
python -m pytest -q tests/knowledge_graphs/contract/test_corpus_registry.py
```

The contract tests load `tests/fixtures/knowledge_graphs/corpus_registry.json`,
assert every mandatory graph kind is present with owner/schema/format/counts
where available, and assert that stale dirty nested lift checkouts are
classified as fixture-only.
