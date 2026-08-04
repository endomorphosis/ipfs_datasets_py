# GraphRAG architecture

| Field | Value |
| --- | --- |
| Interface | `GraphRAGArchitecture@1` |
| Task | `IPFSDOC-032` |
| Status | `canonical` |
| Owner | architecture / knowledge-graphs & optimizers (orchestration) |
| Source of truth | `ipfs_datasets_py/search/graphrag_integration/`; `ipfs_datasets_py/processors/specialized/graphrag/`; `ipfs_datasets_py/processors/graphrag_integrator.py`; `ipfs_datasets_py/optimizers/graphrag/`; `ipfs_datasets_py/logic/intent_ir/graphrag/`; [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related ADRs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Review cadence | after hybrid search, processor consolidation, ontology harness, or LLM-integration changes |

> **Sibling guides:** Knowledge-graph data plane (extraction → commit → query) →
> [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md).
> Optimizer generate/critique/optimize/validate contracts →
> [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md).
> Vector/hybrid search attachment →
> [SEARCH_AND_QUERY.md](../retrieval/SEARCH_AND_QUERY.md).
> Embeddings →
> [EMBEDDINGS_AND_INDEXING.md](../retrieval/EMBEDDINGS_AND_INDEXING.md).
> End-to-end product flows →
> [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md).
> Domain ownership → [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.4–4.5.

## 1. Purpose

This guide answers: **how graph-aware retrieval and generation (GraphRAG)
compose vector search, knowledge-graph traversal, optional LLM synthesis, and
optimizer product loops**—and how **provenance, scores, and model outputs
remain candidates and evidence rather than proof or authorization**.

GraphRAG in this repository is a **product orchestration layer**, not a second
fact store and not a formal proof system.

## 2. Audience

- **Primary:** architects and developers wiring hybrid retrieval, PDF/website
  GraphRAG pipelines, ontology optimizers, or MCP graph/PDF tools.
- **Secondary:** agents interpreting evidence chains and quality scores;
  operators diagnosing optional LLM/backend failures.

## 3. Scope and non-goals

### In scope

- Hybrid vector + graph retrieval (`HybridVectorGraphSearch`,
  `GraphRAGQueryEngine`).
- Cross-document reasoning and **evidence chains**.
- LLM enhancement and reasoning-trace surfaces (`GraphRAGIntegration`).
- Document/website processing paths (`UnifiedGraphRAGProcessor`,
  `GraphRAGIntegrator`, PDF/query engine attachment).
- GraphRAG optimizer product tree (`optimizers/graphrag/`: ontology generate →
  critic → mediator → session/harness).
- Provenance and identity of retrieval/generation artifacts.
- Authority of scores, recommendations, and model outputs.
- Lazy LLM dependencies and failure/degradation behavior at the GraphRAG
  boundary.

### Non-goals

- Knowledge-graph engine CRUD, WAL, Neo4j-compat, lineage of **persisted
  facts** → [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md).
- Shared `BaseOptimizer` / `OptimizationContext` session contracts in full →
  [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md).
- Pure vector ANN backend matrices →
  [VECTOR_STORES.md](../retrieval/VECTOR_STORES.md).
- Formal IR proof, admissibility, authorization →
  [logic architecture](../logic/IR_FAMILY_AND_IDENTITY.md) and Flow D in
  [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md).
- Historical multi-processor consolidation timeline as live architecture →
  `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` (migration product note).

## 4. Context

GraphRAG exists because pure vector retrieval misses relational structure, and
pure graph query misses semantic similarity. The product therefore combines:

1. **Dense (and sometimes sparse) retrieval** over embeddings.
2. **Graph expansion** from seed entities/nodes (bounded hops, budgets).
3. **Optional synthesis** (LLM answers, reasoning traces, ontology refinement).
4. **Optional closed-loop optimization** of ontologies, queries, and extraction
   thresholds.

Domain ownership is fixed in [DOMAIN_MAP.md](../DOMAIN_MAP.md):

| Concern | Owner package |
| --- | --- |
| Persisted graph facts, engine, indexes | `knowledge_graphs` |
| Hybrid search / GraphRAG integration glue | `search` (+ adapters) |
| Document/website GraphRAG processing | `processors` |
| Closed-loop GraphRAG product optimizers | `optimizers` (especially `optimizers.graphrag`) |
| Formal proof / Intent IR GraphRAG projectors | `logic` (subordinate projectors only) |

Multiple implementations coexist and **must not be collapsed** into one type:

| Path | Module family | Role |
| --- | --- | --- |
| Hybrid retrieval + evidence chains | `search/graphrag_integration/` | Query-time graph-aware RAG |
| Unified document/website processor | `processors/specialized/graphrag/` | Ingest → entities/relationships → KG artifacts |
| Legacy integrator API | `processors/graphrag_integrator.py` | Compatibility surface for PDF/query tools |
| Ontology optimization product | `optimizers/graphrag/` | Generate/critique/refine ontologies |
| Intent/SkillCenter projectors | `logic/intent_ir/graphrag/` | Source-grounded projection—not fact authority |

## 5. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Hybrid scoring of vector + graph candidates | Durable graph commit semantics (`knowledge_graphs`) |
| Evidence-chain construction and reasoning traces | Formal theorem proof authority (`logic`) |
| Query-time budgets, hop limits, model weights | ANN backend training / store CRUD (`vector_stores`) |
| Ontology candidate generation and critic scores | Policy/authorization decisions |
| Optional LLM synthesis over retrieved context | Silent upgrade of candidates to persisted facts |

**Inbound callers:** Python APIs; MCP PDF/graph/search tools; CLI GraphRAG
entrypoints; optimizers and agentic loops; Intent IR projectors.

**Outbound dependencies:** vector stores and embeddings; knowledge-graph
engines/stores; optional LLM backends (`LazyLLMBackend` / accelerate);
optional provers only via optimizer `LogicValidator` paths (validation
evidence, not product authorization).

**Authority notes:** GraphRAG outputs sit at the **retrieval / model
candidates** layer of
[ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md). Hybrid scores,
critic scores, evidence chains, and synthesized answers are **not** proofs,
policy grants, or authorization.

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| `HybridVectorGraphSearch` | `search/graphrag_integration/graphrag_integration.py` | Weighted vector + multi-hop graph expansion |
| `CrossDocumentReasoner` | same | Entity-mediated evidence chains across documents |
| `GraphRAGQueryEngine` | same | Unified query API (vector, graph, cross-doc, optional LLM) |
| `GraphRAGFactory` | same | Compose dataset, stores, hybrid search, reasoner |
| `GraphRAGIntegration` | same | Optional LLM enhancement, traces, synthesis over evidence |
| `UnifiedGraphRAGProcessor` | `processors/specialized/graphrag/unified_graphrag.py` | Consolidated website/document GraphRAG pipeline |
| `GraphRAGConfiguration` / `GraphRAGResult` | same | Processor config and status/quality result envelope |
| `GraphRAGIntegrator` | `processors/graphrag_integrator.py` | Legacy/compat integrator for PDF & query engine |
| `QueryEngine` (processor) | `processors/query_engine.py` | Query façade over integrator when present |
| `OntologyGenerator` | `optimizers/graphrag/ontology_generator.py` | Produce ontology candidates from source data |
| `OntologyCritic` / `CriticScore` | `optimizers/graphrag/ontology_critic.py` | Multi-dimension quality **evidence** |
| `OntologyMediator` | `optimizers/graphrag/ontology_mediator.py` | Select refinement actions from critic feedback |
| `OntologyOptimizer` | `optimizers/graphrag/ontology_optimizer.py` | History, export, trend/recommendation reports |
| `OntologySession` / `OntologyHarness` | `ontology_session.py`, `ontology_harness.py` | Single-session and batch orchestration |
| `OntologyPipeline` | `optimizers/graphrag/ontology_pipeline.py` | Convenience façade over generator/critic/mediator |
| Query optimizer family | `optimizers/graphrag/query_*.py` | Query planning, rewriting, budgets, learning hooks |
| Intent GraphRAG projectors | `logic/intent_ir/graphrag/` | SkillCenter/corpus projection helpers |

### 6.1 Package diagram (simplified)

```text
                    +------------------+
  documents/URLs -> | processors       | -> entity/relationship candidates
                    | UnifiedGraphRAG  |    GraphRAGResult (quality scores)
                    +--------+---------+
                             |
                             v
  query text -----> +------------------+     +-------------------+
  embeddings -----> | search GraphRAG  |---->| knowledge_graphs  |
                    | QueryEngine      |     | facts / indexes   |
                    | Hybrid + chains  |     +-------------------+
                    +--------+---------+
                             |
              optional LLM   v
                    +------------------+
                    | optimizers.graphrag
                    | ontology session |
                    | generate/critique|
                    +------------------+
                             |
                             v
                    candidates + CriticScore + recommendations
                    (advisory evidence — not proof)
```

## 7. End-to-end flow

### 7.1 Happy path — graph-aware retrieval

1. **Encode** the query (caller-supplied embeddings and/or store-side encoding).
2. **Vector retrieval** seeds top-k nodes/documents by similarity.
3. **Graph expansion** walks relationships up to `max_graph_hops` under visit
   and edge budgets (`HybridVectorGraphSearch`).
4. **Fuse scores** with configured `vector_weight` / `graph_weight` (normalized
   when both are non-zero).
5. **Filter** by `min_score_threshold` / `min_relevance` and optional entity or
   relationship type filters.
6. **Optional cross-document reasoning** builds **evidence chains** connecting
   documents through shared entities (`CrossDocumentReasoner`).
7. **Optional LLM synthesis** produces an answer and reasoning-trace nodes over
   the retrieved context (`GraphRAGIntegration`); synthesis is a **model
   candidate**, not a committed graph fact.
8. **Return** a result envelope with ranked hits, optional
   `evidence_chains`, optional `reasoning_result`, and metrics.

### 7.2 Happy path — document / website GraphRAG processing

1. Configure `GraphRAGConfiguration` (mode, depth, archiving, media flags).
2. `UnifiedGraphRAGProcessor` runs the multi-phase pipeline (extract, entity
   and relationship discovery, optional archive/media steps, analytics).
3. Produce `GraphRAGResult`: entities, relationships, optional
   `knowledge_graph`, quality/completeness scores, status
   (`success` / `partial` / `failed`), errors and warnings.
4. **Promotion to durable facts** requires an explicit write through
   knowledge-graph storage/transaction APIs—not automatic on result return
   ([KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md)).

### 7.3 Happy path — ontology product loop (GraphRAG optimizers)

1. `OntologyGenerator` extracts ontology candidates from source data under an
   extraction config / domain context.
2. `OntologyCritic` evaluates multi-dimensional quality → `CriticScore` +
   recommendations.
3. `OntologyMediator` selects refinement actions; session/harness iterates
   until stop rules.
4. `OntologyOptimizer` may aggregate history into trend reports and
   **recommendations**.
5. Optional `LogicValidator` consistency checks produce **validation evidence**
   (theorem-prover-assisted consistency), still not product authorization.

Full control-loop contracts:
[OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md).

### 7.4 Flow diagram (query)

```text
query_text
   |
   v
+-------------------+     +------------------+
| vector seed hits  |---->| hybrid rescoring |
+-------------------+     | + graph hops     |
                          +--------+---------+
                                   |
                                   v
                        +----------------------+
                        | evidence chains      |
                        | (entity-mediated)    |
                        +----------+-----------+
                                   |
              +--------------------+--------------------+
              |                                         |
              v                                         v
     ranked candidates + chains              optional LLM synthesis
     (retrieval layer)                       (model candidate layer)
              |                                         |
              +--------------------+--------------------+
                                   |
                                   v
                          result envelope
                          (not a proof, not a fact commit)
```

### 7.5 Initialization and lifecycle

- Hybrid/query engines take a dataset, vector store map, and graph store at
  construction; weights are normalized at init.
- LLM modules under `search/graphrag_integration` are **optional**: import
  failures raise or substitute stubs that re-raise on use (`ImportError`),
  consistent with [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md).
- Optimizers defer heavy LLM backends via `LazyLLMBackend`
  (`optimizers/llm_lazy_loader.py`) and circuit breakers.
- Processor results carry `status` / `errors` / `warnings` for partial pipeline
  completion; partial success is feature degradation, not trust upgrade
  ([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

## 8. Contracts

### 8.1 Inputs

| Input | Type / source | Validation |
| --- | --- | --- |
| `query_text` | string | Non-empty for meaningful retrieval; engine may still run with empty embeddings map |
| `query_embeddings` | optional `Dict[model, ndarray]` | Model keys should align with configured vector stores |
| `top_k`, hop/budget limits | ints | Bounded by engine params (`max_nodes_visited`, `max_edges_traversed`, etc.) |
| Source documents / URLs | processor paths | Config thresholds (`content_quality_threshold`, depth) |
| Ontology source data | generator input | Domain + extraction strategy context |

### 8.2 Outputs

| Output | Type / sink | Guarantees |
| --- | --- | --- |
| Ranked hybrid hits | query result structures | Ranking under configured weights—not correctness proof |
| `evidence_chains` | list of chain dicts | Structural connections via shared entities; **advisory evidence** |
| `reasoning_result` / answer | optional LLM payload | Model candidate text; may be absent if LLM disabled |
| `GraphRAGResult` | processor envelope | Status, entity/relationship lists, quality scores |
| `CriticScore` / recommendations | optimizer | Evaluation **evidence** for refinement loops |
| Metrics | counters / timings | Observability only |

### 8.3 Public surfaces

- Python API (retrieval):
  `ipfs_datasets_py.search.graphrag_integration` (`GraphRAGFactory`,
  `GraphRAGQueryEngine`, `HybridVectorGraphSearch`, `CrossDocumentReasoner`).
- Python API (processing):
  `ipfs_datasets_py.processors.specialized.graphrag.unified_graphrag`
  (`UnifiedGraphRAGProcessor`); compat `GraphRAGIntegrator`.
- Python API (optimizers):
  `ipfs_datasets_py.optimizers.graphrag` (`OntologyGenerator`,
  `OntologyCritic`, `OntologySession`, `OntologyHarness`,
  `OntologyPipeline`, query optimizers).
- MCP: PDF ingest / graph tools wrapping integrator and query engine
  (thin adapters—business logic stays in domain packages).
- CLI: GraphRAG-related dataset and history-index commands (see package CLI
  help); optimizers CLI under `optimizers.cli`.

### 8.4 Provenance and identity

GraphRAG attaches several **non-interchangeable** identity kinds:

| Kind | What it identifies | What it does **not** prove |
| --- | --- | --- |
| Source document / URL / archive location | Origin of extracted text | Truth of claims in the text |
| Entity/relationship candidate IDs | Ephemeral or local extraction objects | Persistence in the fact store |
| Graph node / edge IDs after commit | Durable graph identity | Semantic correctness |
| Content CID (when blocks are stored) | Bytes of an artifact ([ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)) | Ranking quality or legal authority |
| Evidence chain IDs / reasoning-trace nodes | Retrieval-time explanatory structure | Formal entailment |
| Session / processing IDs | Run correlation for logs and metrics | Completeness of the real world |

**Provenance discipline:**

1. Keep **source evidence**, **retrieval candidates**, **persisted facts**, and
   **model generations** labeled separately in APIs and docs.
2. Evidence chains document *how* documents were linked (shared entities,
   hops)—they are **not** automatic lineage of committed facts.
3. Reasoning traces and LLM synthesis must cite the retrieval context they
   used when available; absence of a backend must not invent citations.
4. CID or pin presence never upgrades a GraphRAG answer to proof or policy
   ([ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md),
   [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md)).

## 9. Failure modes and fallbacks

| Failure | Detection | Caller-visible behavior | Fallback |
| --- | --- | --- | --- |
| Optional LLM modules missing | ImportError / stub re-raise | Feature unavailable; no silent “full” synthesis | Run hybrid retrieval without LLM |
| `LLM_ENABLED=0` / disabled lazy backend | `LazyLLMBackend.is_enabled()` | Backend returns `None`; no generate path | Critic/generator rule-based or non-LLM paths when implemented |
| Circuit breaker open | `CircuitBreakerOpen` / metrics | Temporary backend unavailability | Fail the LLM call; do not invent scores as success |
| Empty vector store / graph | Empty hit lists | Empty or low-recall results | No fabricated high-confidence hits |
| Graph hop budget exceeded | visit/edge counters | Truncated expansion | Return partial hybrid set under budgets |
| Processor stage failure | `GraphRAGResult.status`, `errors` | `partial` or `failed` | Surface warnings; do not mark durable success |
| Ontology session exception | session catch path | Partial `SessionResult` with `failed: true` metadata | Report failure; do not claim target quality |
| Logic validator unavailable | optional prover path | Consistency check skipped or error | Do not claim proved consistency |

Explicit distinctions:

- **Not installed** (lazy optional) vs **installed but failed** (runtime
  exception, circuit open)—both degrade **features**, never invent trust.
- **Retrieval score** vs **critic quality score** vs **validation boolean** vs
  **authorization**—non-interchangeable.
- **Stub / import-failure path** vs **behaviorally complete hybrid path** must
  not share a generic “ok” without labeling capability.

## 10. Extension points

1. Add hybrid scoring or budget knobs in `HybridVectorGraphSearch` /
   `GraphRAGQueryEngine` with tests for weight normalization and caps.
2. Register new vector models via the `vector_stores` map and model weights;
   keep fusion logic explicit.
3. Extend ontology dimensions in critic modules under
   `optimizers/graphrag/ontology_critic_*.py` with documented weights.
4. Prefer `UnifiedGraphRAGProcessor` for new document/website ingest paths;
   avoid reintroducing deprecated parallel processors.
5. Keep MCP wrappers thin: call domain APIs; do not reimplement fusion.
6. Update this guide and [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) when
   session contracts or evidence envelopes change.

Anti-patterns:

- Treating hybrid or critic scores as proof or authorization.
- Auto-committing extraction candidates from GraphRAG results without
  knowledge-graph write APIs.
- Eager-importing LLM stacks at package import time.
- Collapsing Intent IR projectors with production fact stores.

## 11. Invariants

1. **GraphRAG is retrieval/orchestration**, not the knowledge-graph authority
   of record.
2. **Scores and model recommendations are advisory evidence**, not truth or
   proof.
3. **Evidence chains** explain candidate linkage; they do not replace lineage
   of committed mutations.
4. **Promotion is explicit** — only storage/transaction commits create shared
   persisted facts.
5. **Optional LLM dependencies stay lazy** — missing backends degrade features
   ([ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)).
6. **Fail closed on trust** — incomplete evidence never becomes silent allow
   or silent prove ([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).
7. **CID identifies content bytes**, not ranking quality or policy.
8. **Logic validation under optimizers** is consistency **evidence**, not
   product authorization.
9. **Multiple GraphRAG implementations remain labeled** (search integration,
   processor, optimizer, logic projector)—do not present them as one class.
10. **Budget limits are safety rails** — hop/node/edge caps must remain
    enforceable under adversarial or dense graphs.

## 12. Rationale and decisions

| Topic | Summary | ADR / source |
| --- | --- | --- |
| Hybrid vector + graph | Relational structure complements ANN similarity | `HybridVectorGraphSearch` |
| Evidence chains | Cross-document answers need inspectable linkage, not only top-k | `CrossDocumentReasoner` |
| Split data plane vs loops | Fact durability stays in `knowledge_graphs`; loops in `optimizers` | DOMAIN_MAP §4.4–4.5 |
| Layered authority | Prevent agents equating hits and answers with proof/auth | ADR-003 |
| Lazy LLM | Hermetic import and optional extras | ADR-002, `llm_lazy_loader` |
| Unified processor | Reduce duplicate website/document GraphRAG stacks | `unified_graphrag.py` |
| Critic multi-dimension scores | Structured refinement signals without claiming truth | `OntologyCritic` / `CriticScore` |

Alternatives rejected (brief):

- Pure vector RAG only — rejects relational multi-hop recall.
- Auto-commit every extraction — collapses candidates into facts.
- Single global “confidence” boolean for all layers — violates layered
  authority.

## 13. Security, privacy, and trust boundaries

- Trust boundary: retrieval and model outputs must not authorize side effects.
- Secrets: LLM API keys and backend credentials must not appear in evidence
  chains, logs, or exported ontologies (redaction helpers exist under
  optimizers).
- User content in prompts is potentially sensitive; treat traces as sensitive
  telemetry.
- This layer **must not** claim theorem proof, policy admission, or
  authorization authority.

## 14. Observability and operations

- Engine metrics: queries processed, nodes visited, graph traversals,
  evidence-chain counts, timings.
- Processor metrics: processing time, entity/relationship counts,
  quality/completeness scores, resource usage.
- Optimizer metrics: session scores, iteration counts, Prometheus optional
  recording (best-effort; never fatal).
- Diagnostics: disable LLM (`LLM_ENABLED=0`), lower hop budgets, inspect
  `GraphRAGResult.errors` / session `failed` metadata.
- Product docs: `docs/optimizers/GRAPHRAG_QUICK_START.md`,
  `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` (migration).

## 15. Related documents

| Document | Relationship |
| --- | --- |
| [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Fact store lifecycle GraphRAG consumes/proposes into |
| [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) | BaseOptimizer contracts and control loops |
| [SEARCH_AND_QUERY.md](../retrieval/SEARCH_AND_QUERY.md) | Non-graph retrieval composition |
| [EMBEDDINGS_AND_INDEXING.md](../retrieval/EMBEDDINGS_AND_INDEXING.md) | Encoding side of hybrid |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | PDF → GraphRAG product flow |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Package ownership |
| `docs/api/OPTIMIZERS_API_REFERENCE.md` | Generated API surface |
| `docs/OPTIMIZATION_LOOP_ARCHITECTURE.md` | Short interim loop ASCII (superseded in authority by OPTIMIZATION_LOOPS.md) |

## 16. Verification

```bash
# Declared task validation
test -s docs/architecture/knowledge/GRAPHRAG.md && test -s docs/architecture/knowledge/OPTIMIZATION_LOOPS.md

# Spot-check source of truth still present
test -f ipfs_datasets_py/search/graphrag_integration/graphrag_integration.py
test -f ipfs_datasets_py/processors/specialized/graphrag/unified_graphrag.py
test -d ipfs_datasets_py/optimizers/graphrag
rg -n 'class HybridVectorGraphSearch|class GraphRAGQueryEngine|class OntologyCritic|class UnifiedGraphRAGProcessor' \
  ipfs_datasets_py/search/graphrag_integration ipfs_datasets_py/optimizers/graphrag \
  ipfs_datasets_py/processors/specialized/graphrag --glob '*.py' | head
```
