# End-to-end data and control flows

| Field | Value |
| --- | --- |
| Interface | `DatasetDataFlow@1` |
| Task | `IPFSDOC-011` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `ipfs_datasets_py/core_operations/`; `processors/specialized/pdf/`; `embeddings/`; `vector_stores/`; `search/`; `logic/{ir_core,admissibility,proof_corpus}/`; `analytics/data_provenance.py`; `mcp_server/{server,hierarchical_tool_manager}.py`; MCP tools under `mcp_server/tools/`; [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md); [DOMAIN_MAP.md](DOMAIN_MAP.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related | [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md), [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) |
| Review cadence | semi-annual or after major pipeline / MCP dispatch changes |

## 1. Purpose

This guide answers: **how representative data and control move through the
system**, hop by hop, with ownership, identity/provenance, side effects,
optional dependencies, and failure modes. It is the cross-domain flow language
for later domain leaves. It does **not** idealize unfinished paths or treat
compatibility aliases as preferred design.

Facts prefer the source-authority order: tests and schemas → current
implementation → packaging → operator manifests → accepted ADRs → maintained
guides ([SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md)).

## 2. How to read a hop table

Every hop in the flows below uses this contract:

| Column | Meaning |
| --- | --- |
| **Hop** | Ordered step within the flow |
| **Inputs** | What enters the hop (bytes, IDs, params) |
| **Outputs** | What leaves (artifacts, IDs, results) |
| **Owner** | Domain package that owns the business logic (not the thin wrapper) |
| **Identity / provenance** | How objects are named and lineage is recorded |
| **Side effects** | Persistent or external mutations |
| **Optional deps** | Extras, binaries, submodules, or services that may be absent |
| **Failure / degradation** | What fails, what degrades, fail-closed notes |
| **Entry point** | Actual Python callable, MCP tool path, or console surface |

**Architecture rule:** Core logic lives in domain packages. MCP tools and most
CLI paths are **thin wrappers** over those packages.

---

## 3. System flow map (overview)

```text
  Sources (files, Hub, URLs, PDF, scrape, NL formulas)
           |
           v
  [1] Ingestion-to-artifact ----> managed dataset / IPLD doc / IR artifact
           |                              |
           v                              v
  [2] Artifact-to-index ----> embeddings + vector / graph indexes
           |                              |
           v                              v
  [3] Query-to-result ----> ranked hits, KG answers, hybrid results
           |
           +---- parallel / adjoining ----+
                                          v
  [4] Logic-to-evidence ----> formal IR, proof corpus, admissibility decision
                                          |
  [5] MCP-to-dispatch ----> tools_dispatch -> domain tool -> domain API
           (control plane that can drive 1–4)
```

Cross-cutting provenance appears in three layers (do not conflate them):

| Layer | Path | Role |
| --- | --- | --- |
| **Operational lineage** | `analytics.data_provenance.ProvenanceManager` | SOURCE/TRANSFORM/MERGE/QUERY/RESULT records; optional IPLD chains |
| **IR provenance** | `logic.ir_core.provenance` (`SourceRef`, digests, `ir-provenance/v1`) | Source-body-free identity for semantic IR; digests/CIDs only |
| **Proof / authz evidence** | `logic.proof_corpus`, `logic.admissibility` | Attested envelopes, receipts; **proof ≠ authorization** |

---

## 4. Flow A — Ingestion to artifact

**Representative path:** load a dataset or PDF into a first-class artifact
(managed dataset summary, processed document with IPLD CID, or saved output).

### 4.1 Happy path (dataset load)

```text
Caller (Python / CLI / MCP)
  -> DatasetLoader.load(source, format, options)
  -> HF datasets / local / URL readers
  -> status + dataset_id + metadata + summary
  -> optional ProvenanceManager.record_source(...)
  -> optional DatasetSaver / IPFS pin
```

### 4.2 Happy path (PDF → GraphRAG artifact)

```text
Caller
  -> PDFProcessor.process_pdf(pdf_path, metadata)
  -> stages: validate → decompose → IPLD → OCR → LLM chunk →
             entities → embeddings → GraphRAG → cross-doc → query setup
  -> document_id, ipld_cid, entity/relationship counts
```

### 4.3 Hop table

| Hop | Inputs | Outputs | Owner | Identity / provenance | Side effects | Optional deps | Failure / degradation | Entry point |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1. Invoke surface | source path/id, format, options; or PDF path + metadata | call into loader/processor | `mcp_server` tools or CLI or Python caller | request params only | none yet | MCP transport if remote | invalid JSON / missing fields → MCP validation error | **Python:** `ipfs_datasets_py.core_operations.dataset_loader.DatasetLoader.load`; **MCP:** `dataset_tools/load_dataset.load_dataset`; `pdf_tools/pdf_ingest_to_graphrag.pdf_ingest_to_graphrag`; **CLI:** `ipfs-datasets dataset load …` (`ipfs_datasets_cli.cli_main`); `tools run dataset_tools load_dataset …` |
| A2. Validate source | `source` string, optional format | accepted source or error | `core_operations` (`DatasetLoader`) | reject `.py` / executables as sources | none | Hugging Face `datasets` | empty source, executable extension → `ValueError` / error dict; HF missing → error status | `DatasetLoader.load` / `load_sync` |
| A3. Materialize dataset | Hub id, path, URL | in-memory or on-disk dataset; `dataset_id`, features, record counts | `core_operations` + optional `ipfs_datasets.ipfs_datasets_py` legacy helpers | `dataset_id` / source string; HF revision when applicable | local cache downloads (HF) | network, `datasets` package | network/HF failure → `status: error`; partial metadata when available | `DatasetLoader.load`; legacy `ipfs_datasets.load_dataset` (MCP JSON path) |
| A4. Process / transform (optional) | dataset handle, ops list | transformed dataset | `core_operations.DataProcessor` | transform op ids | may write temp files | domain-specific | op failure → error dict; HF Dataset types optional | MCP `dataset_tools/process_dataset`; `DataProcessor` |
| A5. PDF pipeline (alt path) | PDF bytes/path, OCR flags, chunk strategy | `document_id`, `ipld_cid`, stage stats | `processors` (`PDFProcessor` in `processors/specialized/pdf/`) | document_id + IPLD CID; stage list | IPLD/graph writes when backends present; OCR artifacts | OCR engines, LLM routers, GraphRAG stack | missing `PDFProcessor` → MCP error; stage failures report `stages_completed` + error; non-fatal stage skips possible | **Python:** `PDFProcessor.process_pdf`; **MCP:** `pdf_ingest_to_graphrag` |
| A6. Persist artifact (optional) | dataset/doc, destination, format | saved path / CID | `core_operations` saver / IPFS helpers | CID or destination URI | disk/IPFS write, pin | IPFS kit/daemon (`IPFS_DATASETS_PY_ENABLE_IPFS_KIT`) | pin failure → error; local save may still succeed | MCP `dataset_tools/save_dataset`; CLI `ipfs pin` / dataset save paths |
| A7. Operational provenance (optional) | entity ids, operation params | `ProvenanceRecord` chain | `analytics` (`ProvenanceManager`) | record `id`, `record_type` SOURCE/TRANSFORM/…, timestamps | in-memory or IPLD-backed lineage graph | networkx for viz | provenance off → no lineage; never invents authority | `ProvenanceManager.record_source` / `record_*`; MCP `provenance_tools/*` |

### 4.4 Side-effect and identity notes

- **Default ingest is not authorization.** Loading or OCR does not grant wallet
  rights or admissibility allow.
- **IPLD CIDs** (PDF path) are content addresses for document structure, not
  theorem proofs.
- **HF cache** side effects are outside this package’s control once `datasets`
  is invoked.

---

## 5. Flow B — Artifact to index

**Representative path:** texts or chunks from an artifact become embeddings and
are written into a vector collection and/or knowledge-graph index.

### 5.1 Happy path

```text
Artifact texts / chunks
  -> embeddings.generation_engine.generate_* / embeddings_router
  -> vector_stores.api.add_texts_to_store / store.add_embeddings
  -> collection + vector IDs
  -> optional knowledge_graphs entity/relationship index
  -> optional graph_tools graph_index_create
```

### 5.2 Hop table

| Hop | Inputs | Outputs | Owner | Identity / provenance | Side effects | Optional deps | Failure / degradation | Entry point |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| B1. Select texts | dataset rows, PDF chunks, file | list of texts + metadata | caller + `processors` / dataset layer | chunk_id when present | none | prior Flow A | empty corpus → empty index | Python domain code; PDF pipeline stages inside `process_pdf` |
| B2. Generate embeddings | text(s), `model_name`, normalize/gpu flags | embedding vector(s), dimension, model id | `embeddings` (`generation_engine`) | model name + content hash not always stored; attach metadata yourself for lineage | model download/cache | `vectors` / sentence-transformers; GPU | **degradation:** stub fallback embedding when engine missing (`HAVE_EMBEDDINGS` false) — not production-quality; length limit 10k chars | **Python:** `generate_embedding`, `generate_batch_embeddings`, `generate_embeddings_from_file`; **MCP:** `embedding_tools/embedding_generation`; **CLI:** `ipfs-datasets vector create …` |
| B3. Create / open store | store type (`faiss`, `qdrant`, `elasticsearch`, `ipld`, …), collection name | `BaseVectorStore` instance | `vector_stores` | collection name; backend-specific ids | may create collections/indices on backend | FAISS/Qdrant/ES clients; `vectors` extra | backend down → create/add fails; IPLD path more local | `vector_stores.api.create_vector_store`; `vector_stores.manager` |
| B4. Index vectors | store, texts/embeddings, metadata, batch_size | list of vector IDs | `vector_stores` | vector IDs; optional content CID on IPLD store | persistent index write | embeddings router on store | empty texts → `[]`; missing embedder → error | `add_texts_to_store`; `store.add_embeddings` |
| B5. Graph index (optional) | entities, relationships, ontology | graph nodes/edges/indexes | `knowledge_graphs` | entity keys, lineage types (`cross_document_lineage*`) | Neo4j or decentralized graph write | `knowledge_graphs` extra, Neo4j | graph unavailable → vector-only retrieval remains | MCP `graph_tools/graph_create`, `graph_add_entity`, `graph_index_create`; Python `knowledge_graphs.*` |
| B6. Lineage / provenance | vector ids, source dataset/doc ids | MERGE/TRANSFORM records or graph provenance verify | `analytics` / `knowledge_graphs` / graph provenance tools | links vector/graph ids to source artifact | provenance store / graph edges | optional | skipped if not called | `ProvenanceManager.record_*`; MCP `graph_provenance_verify` |

### 5.3 Failure patterns

| Condition | Behavior |
| --- | --- |
| Embedding deps missing | Fallback numeric stub with warning message (treat as degraded) |
| Vector backend missing | `create_vector_store` / add fails; no silent success |
| Partial PDF pipeline | embeddings stage may be absent if earlier stage failed — check `stages_completed` |
| Sharding / multi-node | optional; coordinators under `vector_stores/sharding/` |

---

## 6. Flow C — Query to result

**Representative path:** natural-language or structured query returns ranked
passages, hybrid graph+vector hits, or Cypher results.

### 6.1 Happy path

```text
Query string / Cypher / filters
  -> embed query (if semantic)
  -> vector_stores.api.search_texts  and/or  embeddings.semantic_search_engine
  -> optional knowledge_graphs / graph_search_hybrid
  -> ranked SearchResult list or graph payload
  -> optional ProvenanceManager.record_query / record_query_result
```

### 6.2 Hop table

| Hop | Inputs | Outputs | Owner | Identity / provenance | Side effects | Optional deps | Failure / degradation | Entry point |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C1. Accept query | query text, top_k, filters, collection | normalized query request | caller / MCP search tools | query id optional | none | — | empty query → validation error | **Python:** `search_texts`, `semantic_search`, `hybrid_search`; **MCP:** embedding `advanced_search`, graph `graph_search_hybrid`, `graph_query_cypher`; **CLI:** `ipfs-datasets vector search`, `graph search`, `graph query`; module CLI `python -m ipfs_datasets_py.search.cli` |
| C2. Query embedding | query text, model | query vector | `embeddings` / store router | model identity | may load model | same as B2 | fallback embedding degrades ranking quality | `generate_embedding` or store router |
| C3. Vector retrieval | query vector, top_k, filters | `List[SearchResult]` (ids, scores, content, metadata) | `vector_stores` | hit ids + scores | read-only against index | FAISS/Qdrant/ES | empty collection → empty list; backend timeout → error | `search_texts`; backend `search` |
| C4. Semantic / hybrid engines | query, multi-modal or filter params | multi-source ranked results | `embeddings.semantic_search_engine`, `search.search_embeddings` | engine-specific result keys | may touch IPFS kit if enabled | `IPFS_DATASETS_PY_ENABLE_IPFS_KIT`; accelerate | kit disabled by default (hermetic); accelerate optional | `semantic_search`, `hybrid_search`, `multi_modal_search`, `search_with_filters`; class `search.search_embeddings.search_embeddings` |
| C5. Graph query (optional) | Cypher / hybrid params | graph rows / hybrid hits | `knowledge_graphs`, MCP graph tools | node/edge ids | read or write depending on query | Neo4j-compatible engine | engine missing → error; hybrid may fall back to vector | `graph_query_cypher`, `graph_search_hybrid`; `knowledge_graphs.query_knowledge_graph` |
| C6. Logic-enhanced RAG (optional) | query + logic context | answers augmented by FOL/deontic/theorem modules | `search.logic_integration` | must not treat model text as proof | may call provers | `logic`, theorem provers | prover missing → degrade to non-logic RAG | `logic_enhanced_rag`, `theorem_augmented_rag` |
| C7. Provenance of query (optional) | query + result ids | QUERY/RESULT records | `analytics` | query record links to result records | provenance store write | — | omission is normal for ad-hoc CLI | `ProvenanceManager.record_query`, `record_query_result` |

### 6.3 Contracts callers may rely on

- Vector search returns **similarity scores**, not policy decisions.
- GraphRAG hybrid search is a **retrieval** product; formal allow/deny is Flow D.
- IPFS kit and accelerate are **opt-in** via environment flags (see SYSTEM_CONTEXT).

---

## 7. Flow D — Logic to evidence

**Representative path:** natural-language or structured claim → formal IR /
proof attempt → attested proof corpus entry → admissibility decision (evidence
for authorization, not automatic remote side effects).

### 7.1 Happy path

```text
Input formula / Intent formal artifact
  -> logic compilers / LogicProcessor (FOL, TDFOL, CEC, …)
  -> external prover or portfolio (optional)
  -> AttestedProofEnvelope / proof corpus store
  -> IntentAdmissibilityGate / IntentAuthorizationAPI.evaluate
  -> AdmissibilityDecision or AuthorizationAPIResult
     (allow | reject | abstain)  — fail closed
```

### 7.2 Hop table

| Hop | Inputs | Outputs | Owner | Identity / provenance | Side effects | Optional deps | Failure / degradation | Entry point |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D1. Capture / formalize | NL text, formula string, Intent IR | formal artifact, formula AST, digests | `logic` (`formalization`, `fol`, `tdfol`, `deontic`, `intent_ir`, …) | `logic.ir_core.provenance.SourceRef` + content digests; schema `ir-provenance/v1` — **no source body in IR** | may write intermediate artifacts | NLP/LLM optional | invalid formula → error; machine-extracted review_status is not proof | **Python:** logic submodules via `logic.submodule_registry`; `core_operations.logic_processor.LogicProcessor`; **MCP:** `logic_tools/*` (e.g. `tdfol_prove`, `tdfol_parse`, `cec_prove`); **CLI:** `python -m ipfs_datasets_py.logic.cli` |
| D2. Prove / check | formula, axioms, strategy, timeout | proved flag, proof steps, method | `logic` + `external_provers` | solver identity in pipeline fields when present | may spawn prover processes | Z3, CVC5, Lean, Coq, ErgoAI, CEC/ShadowProver; extras `logic`, `theorem-provers` | timeout → not proved; missing binary → unavailable error; **simulation ≠ production proof** | `LogicProcessor.prove_tdfol`; MCP `tdfol_prove`, `cec_prove_tool`; `ipfs-datasets-install-provers` for install |
| D3. Attest / store evidence | statement digests, proof artifacts, attestation kind | `AttestedProofEnvelope` / corpus row | `logic.proof_corpus` | interface `AttestedProofEnvelope@1`; CID digests; authority kinds separated | corpus store write | ZKP extras (`provekit`, `groth16`, `profile-f-zk`) optional | **non-authoritative kinds** (`simulation`, `artifact-membership`) never upgrade to theorem authority | `proof_corpus.model`, `attest`, `store`, `query` |
| D4. Admissibility gate | formal Intent artifact + profile | `AdmissibilityDecision` allow/reject/abstain | `logic.admissibility.gate` | profile id; reason codes; integrity checks | read corpus; no remote exec by default | proof corpus populated | incomplete evidence → **abstain**; hard forbid → **reject**; never allow without constraints | `IntentAdmissibilityGate` (`gate.py`); profile resolve fail-closed |
| D5. Authorization API compose | query bundle, portfolio backends | `AuthorizationAPIResult` / decision + receipts | `logic.admissibility` (`api`, `compose`, `portfolio`, `enforcement`) | typed decision/receipt refs; rollout defaults **off/audit** | enforcement may consume receipts if configured | rollout config `config/intent_authorization_rollout.json` | race/store errors; fail closed without validators | `IntentAuthorizationAPI.evaluate`; `evaluate_authorization_api`; MCP logic admissibility tools / `logic_admissibility_*` |
| D6. Audit / hammers (optional) | proof jobs, security IR | audit reports, hammer provenance | `logic` hammers, `audit` | links proof ids to audit events | audit logs | security verification assets | monitoring ≠ proof | `logic/hammers/provenance.py`; audit integrators |

### 7.3 Hard invariants (do not document the opposite)

1. **Proof ≠ authorization.** A proved formula does not by itself execute tools
   or mutate production systems.
2. **Allow requires positive applicable grants** under the profile; abstain does
   not promote to allow.
3. **Simulated ZKP / stub backends are never production-authoritative**
   (`proof_corpus` policy and registry notes).
4. **Discovery of a prover binary ≠ capability** until install and tests say so.

---

## 8. Flow E — MCP to dispatch

**Representative path:** MCP client (VS Code, Claude host, HTTP) lists
categories and executes a domain tool through the hierarchical meta-tools.

### 8.1 Happy path

```text
MCP client
  -> python -m ipfs_datasets_py.mcp_server  (stdio default | --http)
  -> IPFSDatasetsMCPServer.register_tools()
  -> meta-tools: tools_list_categories | tools_list_tools |
                 tools_get_schema | tools_dispatch
  -> HierarchicalToolManager.dispatch(category, tool, params)
  -> import mcp_server.tools.<category>.<tool>
  -> domain package callable
  -> JSON result (+ optional request_id, _trace ExecutionEnvelope)
```

### 8.2 Hop table

| Hop | Inputs | Outputs | Owner | Identity / provenance | Side effects | Optional deps | Failure / degradation | Entry point |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1. Start server | host/port/config flags | running stdio or HTTP process | `mcp_server` | process identity; config from `configs` / YAML | bind port (HTTP); stdio pipes | `mcp`/FastMCP package; Hypercorn+Trio or uvicorn for HTTP | import failure → `ImportError` / fallback `simple_server`; neither ASGI server → stdio fallback | **Console/module:** `python -m ipfs_datasets_py.mcp_server`; **Python:** `start_stdio_server()`, `start_server(host, port)`; **CLI:** `ipfs-datasets mcp start`; `__main__.main` |
| E2. Register meta-tools | server instance | 4 hierarchical tools registered (optional MCP++ policy tools if enabled) | `mcp_server.server.IPFSDatasetsMCPServer` | tool names `tools_*` | in-memory registry | FastMCP real import | without FastMCP, registration raises | `register_tools` → `hierarchical_tool_manager.tools_*` |
| E3. Discover categories | none / include_count | category list | `HierarchicalToolManager` | category directory names under `tools/` | filesystem scan | — | missing tools dir → empty | MCP tool `tools_list_categories` |
| E4. List / schema | category, tool name | tool list or parameter schema | same | module path | import for schema | tool module importable | unknown category/tool → error dict | `tools_list_tools`, `tools_get_schema` |
| E5. Dispatch | category, tool, params | tool result dict (`status`, payload, often `request_id`) | `HierarchicalToolManager.dispatch` | optional Profile B `_trace` via `dispatch_with_trace` (Intent/ExecutionEnvelope CIDs) | **whatever the domain tool does** (disk, network, provers) | per-tool extras | shutdown → reject; circuit breaker OPEN → reject without call; import/exec errors → structured error | MCP `tools_dispatch`; CLI `tools run <category> <tool> --arg …` / `DynamicToolRunner.run_tool` |
| E6. Domain execution | tool kwargs | domain outputs (dataset, embeddings, proof, …) | domain package owning the logic | domain identity rules (Flows A–D) | domain side effects | domain optional deps | tool-level try/except → `status: error` | e.g. `dataset_tools.load_dataset`, `pdf_ingest_to_graphrag`, `embedding_generation.generate_embedding`, `logic_tools.tdfol_prove` |
| E7. Optional peer/P2P | peer method calls | remote tool results | `mcp_server` P2P adapters / MCP++ | peer ids; registry adapter | network | libp2p / accelerate adjacency | start failure logged; tools still local | `P2PMCPRegistryAdapter`; `p2p_libp2p_transport` |
| E8. Shutdown | signal / stop | clean stop | server | — | persist DelegationManager if present; stop P2P | — | save failures logged as warnings | `start_stdio` / `start` finally blocks |

### 8.3 Control-plane notes

- Hierarchical registration deliberately **does not** load ~300+ tools at
  startup; discovery is on demand (reduces context and import cost).
- **Circuit breakers** are per-category: consecutive failures open the breaker;
  recovery timeout probes half-open.
- **Auth token validation** on HTTP paths may use in-memory mock services —
  discovery of a 200 response is not production IAM.
- CLI and MCP share tool modules: the CLI `DynamicToolRunner` imports the same
  `ipfs_datasets_py.mcp_server.tools.<category>.<tool>` paths.

```text
CLI:  ipfs-datasets tools run dataset_tools load_dataset --source squad
MCP:  tools_dispatch(category="dataset_tools", tool="load_dataset",
                     params={"source": "squad"})
Python: await DatasetLoader().load("squad")
```

All three should converge on the same core loader when wrappers stay thin.

---

## 9. Cross-flow composition examples

### 9.1 PDF corpus Q&A (A → B → C)

1. `pdf_ingest_to_graphrag` / `PDFProcessor.process_pdf` (A5) → `document_id`, `ipld_cid`.
2. Pipeline stages generate embeddings and graph edges (B).
3. `pdf_query_corpus` / `graph_search_hybrid` / `search_texts` (C) → ranked answer context.

### 9.2 Dataset semantic search (A → B → C)

1. `load_dataset` → `dataset_id`.
2. `generate_batch_embeddings` + `add_texts_to_store` → vector IDs.
3. `search_texts` / CLI `vector search` → hits.

### 9.3 Policy-gated tool use (D → E)

1. Formalize Intent + evaluate admissibility (D4–D5) → decision/receipt.
2. Only if policy wiring and enforcement are configured, dispatch tools (E5).
3. Without configured enforcement, MCP dispatch may still run — **do not assume
   gate wrapping on every path**. Document call-site wiring explicitly.

### 9.4 Provenance audit trail (A/B/C + analytics)

1. `record_source` at ingest; `record_*` on transforms; `record_query` at search.
2. Audit integrators (`audit.integration.AuditProvenanceIntegrator`) join audit
   events to provenance record ids for compliance views.

---

## 10. Optional dependency matrix (flow-relevant)

| Capability | Extra / flag / submodule | Flows |
| --- | --- | --- |
| HF dataset load | `datasets` (core dynamic deps) | A, C |
| Vector backends | extra `vectors` | B, C |
| Knowledge graphs / Neo4j paths | extra `knowledge_graphs` | B, C |
| PDF/OCR/multimedia | `ocr`, `multimedia`, `file_conversion` | A |
| Logic / provers | `logic`, `theorem-provers`; install script | D |
| ZKP | `provekit`, `groth16`, `profile-f-zk` | D |
| MCP HTTP API | extra `api` | E |
| IPFS kit | env `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` + submodule | A, C |
| LLM stacks | env `IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS` | A, C, D (when used) |

Empty git submodules are **availability** issues, not domain absence
([DOMAIN_MAP.md](DOMAIN_MAP.md)).

---

## 11. Failure and degradation summary

| Class | Pattern | Guidance |
| --- | --- | --- |
| Missing optional import | error dict or ImportError | install extra; do not invent success |
| Stub / fallback embedding | success with placeholder vector | treat as non-production |
| Partial pipeline | `stages_completed` + error | resume or re-run failed stage |
| Circuit open | dispatch rejected | wait recovery_timeout; fix underlying tool |
| Prover timeout / abstain | not proved / abstain | never upgrade to allow |
| Packaging CLI drift | script missing after install | see [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md) |

---

## 12. Non-goals

- Full API reference for every tool (see MCP catalog / API domains).
- Dependency initialization deep dive (planned
  `DEPENDENCY_AND_INITIALIZATION.md`).
- Cross-repository accelerate/agent-supervisor leases (planned
  `INTEGRATION_BOUNDARIES.md` / runtime leaves).
- Claiming every historical dashboard path is wired to these hops.

---

## 13. Related documents

| Document | Role |
| --- | --- |
| [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) | Actors and product surfaces |
| [DOMAIN_MAP.md](DOMAIN_MAP.md) | Domain ownership |
| [RUNTIME_ENTRYPOINTS.md](RUNTIME_ENTRYPOINTS.md) | Callable and console entry map |
| [MCP_TOOLS_ARCHITECTURE.md](MCP_TOOLS_ARCHITECTURE.md) | Historical MCP tooling notes |
| Package ADRs `ipfs_datasets_py/mcp_server/docs/adr/` | MCP design decisions |

---

## 14. Validation

Re-check when pipelines, hierarchical dispatch, or IR/admissibility contracts
change.

```bash
test -s docs/architecture/END_TO_END_DATA_FLOW.md && test -s docs/architecture/RUNTIME_ENTRYPOINTS.md
rg -n 'Python|CLI|MCP|provenance|failure' docs/architecture/END_TO_END_DATA_FLOW.md
```

Evidence for this revision: `DatasetLoader`, `PDFProcessor.process_pdf`,
`embeddings/generation_engine.py`, `vector_stores/api.py`,
`logic/ir_core/provenance.py`, `logic/admissibility/gate.py`,
`logic/proof_corpus/model.py`, `analytics/data_provenance.py`,
`mcp_server/server.py` hierarchical registration, `hierarchical_tool_manager`
`tools_dispatch` / circuit breaker, thin MCP tools under `dataset_tools`,
`pdf_tools`, `embedding_tools`, `logic_tools`, and CLI `cli_main` tool runner.
