# Knowledge and GraphRAG architecture index

| Field | Value |
| --- | --- |
| Interface | `KnowledgeArchitectureIndex@1` |
| Task | `IPFSDOC-033` |
| Status | `canonical` |
| Owner | architecture / knowledge-graphs & optimizers domains |
| Source of truth | Canonical leaves under `docs/architecture/knowledge/`; `ipfs_datasets_py/knowledge_graphs/`; `ipfs_datasets_py/optimizers/`; `ipfs_datasets_py/search/graphrag_integration/`; related processors GraphRAG paths; [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.4–4.5; [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md); [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md); [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, operator |
| Related | [DOMAIN_MAP.md](../DOMAIN_MAP.md), [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md), [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md), [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md), [retrieval/README.md](../retrieval/README.md) |
| Review cadence | after graph engine, GraphRAG orchestration, or optimizer loop contract changes |
| Goal | `IPFSDOC-G050` (shared with retrieval index) |

> **Lifecycle:** This page is the **canonical routing hub** for knowledge
> graphs, GraphRAG orchestration, and optimizer control loops. It does **not**
> replace leaf architecture guides. Prefer the leaves for contracts, authority
> models, failure modes, and extension detail. Package `docs/knowledge_graphs/*`
> status snapshots, `docs/optimizers/*` session reports, and undated coverage
> marketing counts are **not** architecture authority.

## 1. Purpose

Route developers, agents, and operators to the right knowledge documentation
without conflating **extraction candidates**, **persisted graph facts**,
**compatibility views**, **GraphRAG scores**, **optimizer proposals / critic
scores**, or **proof**:

| Need | Go to |
| --- | --- |
| Extraction → commit → index → query → reasoning; Neo4j-compat; lineage | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) |
| Hybrid vector+graph retrieval, evidence chains, processor/optimizer GraphRAG | [GRAPHRAG.md](GRAPHRAG.md) |
| BaseOptimizer generate → critique → optimize → validate loops | [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) |
| Embeddings, ANN backends, pure vector search | [retrieval/README.md](../retrieval/README.md) |
| Domain ownership of `knowledge_graphs` / `optimizers` | [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.4–4.5 |
| Cross-domain hops (Flows A–C with graph index; formal path is Flow D) | [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) |
| Content identity vs graph payload CIDs | [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md), storage identity leaf |
| Layered authority / fail-closed trust | [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| Live package / API / tutorial / historical anchors | §5 Component families + §7 Documentation routes |
| Backend-specific, optional, or historical material only | §5 status legend + §7.4–§7.5 (labeled; not sole architecture) |

**Effects of this index:** one entry point for knowledge and GraphRAG without
rewriting the leaf guides. New code and docs should link here for orientation,
then drop into the owning leaf.

**Core inequalities (all leaves agree):**

- extraction **candidate** **≠** committed **graph fact**
- graph **fact** **≠** Neo4j **compatibility view** **≠** foreign export
- vector / hybrid **score** **≠** fact **≠** proof
- model **proposal** / critic **score** / recommendation **≠** truth or authorization
- optimizer **validate** step **≠** formal theorem proof
- IPLD **CID** of a payload **≠** semantic truth of the payload

## 2. Audience

- **Primary:** developers and agents choosing where to implement or document
  graph lifecycle, hybrid GraphRAG, or optimizer product loops.
- **Secondary:** operators diagnosing optional Neo4j/LLM/IPFS paths; architects
  placing knowledge relative to retrieval, processing, storage, and logic.

## 3. Scope and non-goals

### In scope

- Index of **canonical** knowledge / GraphRAG / optimizer architecture leaves.
- **Ownership** and **current / optional / backend-specific / compatibility /
  historical** status per knowledge family.
- Routes to retained component paths, API and MCP surfaces, tutorials,
  extension seams, and labeled non-authoritative material.
- Explicit honesty: in-memory engines, missing spaCy/transformers, optional
  Neo4j export, lazy LLM loaders, and dry-run optimizer sessions are capability
  or stage gaps—not architecture absence and not production formal authority.

### Non-goals

- Full extraction/transaction/lineage algorithms → [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md).
- Full hybrid search and evidence-chain contracts → [GRAPHRAG.md](GRAPHRAG.md).
- Full BaseOptimizer / critic / lifecycle-hook contracts → [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md).
- ANN backend matrices and pure vector ranking → [retrieval/README.md](../retrieval/README.md).
- Formal IR identity, provers, attestation, authorization → [logic/README.md](../logic/README.md).
- Content-addressed storage backends and pins → [storage/README.md](../storage/README.md).
- MCP transport and tool lifecycle framing → [architecture/mcp/](../mcp/).
- Treating package `MASTER_STATUS` slogans or undated test-count banners as
  current architecture authority.

## 4. Canonical knowledge guides

These three pages are the **architecture authority** for knowledge under
`docs/architecture/knowledge/`. All three have status `canonical` as of last
verification (tasks `IPFSDOC-031`, `IPFSDOC-032`).

| Guide | Interface | Owns | Status |
| --- | --- | --- | --- |
| [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | `KnowledgeGraphLifecycle@1` | Extraction, engine CRUD, IPLD storage, transactions, indexes, lineage, JSON-LD/Cypher/SPARQL, reasoning, Neo4j-compat, migration, **authority model** for facts vs views | **canonical** — data plane for graphs |
| [GRAPHRAG.md](GRAPHRAG.md) | `GraphRAGArchitecture@1` | Hybrid vector+graph retrieval, evidence chains, LLM enhancement, processor GraphRAG paths, GraphRAG optimizer product tree, provenance of retrieval/generation artifacts | **canonical** — orchestration layer; not a second fact store |
| [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) | `OptimizerLoopArchitecture@1` | `BaseOptimizer` / `OptimizationContext` / generate→critique→optimize→validate, critics, lifecycle hooks, lazy LLM, GraphRAG/logic/agentic product loops | **canonical** — control loops; scores are advisory |

```text
                    ┌──────────────────────────────────────┐
                    │  docs/architecture/knowledge/        │
                    │  README.md  (this index)             │
                    └──────────────────┬───────────────────┘
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
   KNOWLEDGE_GRAPH_LIFECYCLE.md   GRAPHRAG.md            OPTIMIZATION_LOOPS.md
   (facts / engine / Neo4j-       (hybrid retrieval /    (generate → critique →
    compat / lineage)              evidence / processors)  optimize → validate)
```

Cross-links among leaves: lifecycle owns **persisted facts** and durability;
GraphRAG **composes** retrieval + graph traversal + optional generation without
redefining fact authority; optimizers close **product loops** around candidates
(ontologies, plans, statements) whose scores remain advisory.

**Reading order for a new knowledge feature:** lifecycle (if facts persist) →
GraphRAG (if hybrid retrieval/generation) → optimization loops (if iterative
generate/critique). For pure ANN, start at
[retrieval/README.md](../retrieval/README.md). For formal proof, go to
[logic/README.md](../logic/README.md)—do not promote GraphRAG or optimizer
outputs into allow/deny.

**Kinds of truth (do not collapse):** source **text**, extraction
**candidate**, engine **node/edge**, committed **fact**, IPLD **CID**, lineage
**record**, Neo4j-compat **view**, hybrid **score**, evidence **chain**,
optimizer **proposal**, critic **score**, recommendation, formal **proof**,
authorization **receipt**. See
[ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) and
[ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md).

## 5. Component families: ownership and status

**Product domains (DOMAIN_MAP):** `knowledge_graphs` (§4.5) and `optimizers`
(§4.4) → this directory. GraphRAG **search integration** also lives under
`search/graphrag_integration/`; processor GraphRAG under
`processors/specialized/graphrag/` and related integrators. MCP graph tools are
**thin wrappers**; algorithms stay in domain packages.

Status legend:

| Status | Meaning |
| --- | --- |
| **canonical** | Preferred import / design for new work |
| **compat** | Supported transitional surface; prefer canonical when writing new code |
| **optional** | Requires extras, host binaries, secrets, models, or initialized services |
| **backend-specific** | Behavior depends on graph storage backend or hybrid vector backend |
| **deprecated** | Still importable with warnings or re-exports; do not extend |
| **historical** | Docs or paths describing past plans/migrations; not live architecture |
| **mock / dry-run** | Explicit non-production or non-committing path; green tests ≠ production truth |

### 5.1 Family matrix

| Family | Canonical path(s) | Optional / backend-specific / compat | Architecture leaf | Notes |
| --- | --- | --- | --- | --- |
| **Extraction** | `knowledge_graphs/extraction/` | spaCy / transformers **optional**; rule-based default | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Candidates ≠ facts |
| **Graph engine** | `knowledge_graphs/core/graph_engine.py` | In-memory without backend; IPLD backend **optional** | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | CRUD over nodes/edges |
| **IPLD graph storage** | `knowledge_graphs/storage/ipld_backend.py` | Router / pin paths **optional** | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Preferred storage for new work |
| **Legacy IPLD KG** | `knowledge_graphs/ipld.py` | **deprecated** — prefer `storage/ipld_backend.py` + neo4j_compat | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Compat until removal |
| **Transactions** | `knowledge_graphs/transactions/` | Durability only with configured backend | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Commit ≠ semantic validation alone |
| **Indexing** | `knowledge_graphs/indexing/` | Index kinds **backend-specific** to engine | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Graph indexes ≠ vector ANN |
| **Lineage / provenance** | `knowledge_graphs/lineage/` | Cross-document lineage types | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Links artifacts; not formal proof |
| **Query / Cypher / SPARQL** | `knowledge_graphs/query/`, `cypher/`, SPARQL helpers | SPARQL endpoints **optional** | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Query results reflect store at execution time |
| **JSON-LD / RDF** | `knowledge_graphs/jsonld/` | Serialization **compatibility views** | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Export ≠ second fact store |
| **Ontology / reasoning** | `knowledge_graphs/ontology/`, `reasoning/` | Inference **optional**; inferred copy labeled | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Materialized inferences are still graph products, not theorems |
| **Neo4j compatibility** | `knowledge_graphs/neo4j_compat/` | Bolt Neo4j product **not** required for core path | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Driver/session/result **compat view** over IPFS engine |
| **Migration import/export** | `knowledge_graphs/migration/` | Foreign Neo4j/file payloads **compat** | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Compatibility payloads only |
| **Manager facade** | `core_operations/knowledge_graph_manager.py` | MCP/CLI convenience over neo4j_compat path | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Not a second engine |
| **Hybrid vector+graph search** | `search/graphrag_integration/` | Vector backends **backend-specific**; graph optional degrade | [GRAPHRAG.md](GRAPHRAG.md), [retrieval/SEARCH_AND_QUERY.md](../retrieval/SEARCH_AND_QUERY.md) | Scores ≠ facts |
| **Processor GraphRAG** | `processors/specialized/graphrag/`, `processors/graphrag_integrator.py` | PDF/website pipelines; optional OCR/LLM | [GRAPHRAG.md](GRAPHRAG.md), [processing/README.md](../processing/README.md) | Processing emits artifacts; KG owns facts |
| **GraphRAG optimizers** | `optimizers/graphrag/` | LLM backends **optional** (lazy loader) | [GRAPHRAG.md](GRAPHRAG.md), [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) | Ontology generate/critic/harness |
| **Base optimizer contracts** | `optimizers/common/` (`base_optimizer`, critics, results, lifecycle) | Shared across product families | [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) | Canonical loop shape |
| **Logic theorem optimizers** | `optimizers/logic_theorem_optimizer/`, `optimizers/logic/` | Prover/LLM stacks **optional** | [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md); formal SoT → logic | Optimizer ≠ proof corpus |
| **Agentic optimizers** | `optimizers/agentic/` | External agents/tools **optional** | [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) | Advisory control loops |
| **Performance optimizers** | `optimizers/performance_optimizer.py`, `advanced_performance_optimizer.py`, `perf/` | Metrics/tracing **optional** | [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) | Performance advice, not facts |
| **Lazy LLM / metrics / alerts** | `optimizers/llm_lazy_loader.py`, learning metrics, alert system | LLM and metrics **optional** | [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) | Circuit breakers; no invented success |
| **MCP / CLI thin surfaces** | `mcp_server/tools/graph_tools/`; optimizers CLI/REPL | Tool availability **optional** by install | §7.3 | No business logic only in tool modules |

### 5.2 Ownership boundaries (summary)

| Owns (knowledge / GraphRAG / optimizers) | Does not own |
| --- | --- |
| Graph extraction, engine CRUD, IPLD graph storage, lineage of graph artifacts | Vector ANN protocol and FAISS/Qdrant/ES matrices (`vector_stores`) |
| Neo4j-compatible driver view over the package engine | Hosting Neo4j Server as a product deliverable |
| Hybrid GraphRAG orchestration and evidence chains | Content CID profiles and pin lifecycle (`storage`) |
| Optimizer generate/critique/optimize/validate product loops | Formal IR identity, provers, attestation, authorization (`logic`) |
| Labeling candidates, scores, dry-runs, and compatibility views | Treating critic scores or hybrid ranks as allow/deny |

**Inbound:** Python API (`knowledge_graphs.*`, `optimizers.*`), MCP graph tools,
processors GraphRAG/PDF paths, logic frame/modal bridges, retrieval hybrid
callers, optimizers CLI/REPL.

**Outbound:** optional spaCy/transformers; optional Neo4j client for
export/import; IPFS/IPLD router for durable graphs; vector/search for hybrid
retrieval; optional LLM stacks via lazy loader; logic bridges for
theorem-oriented optimizer families (formal authority remains in `logic`).

## 6. Extension recipes (where to implement)

Do **not** put new graph or optimizer business logic only in MCP tool modules.
Prefer domain packages, then thin wrappers.

| Extension | Recipe summary | Detail |
| --- | --- | --- |
| New extractor or entity type | Extraction models + confidence/source_text; never auto-promote to fact without commit path | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) |
| New graph index or query surface | Engine/index modules; document durability requirements | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) |
| New lineage relation | Versioned lineage type; link ids without inventing proof | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) |
| New Neo4j-compat Cypher capability | Extend neo4j_compat session/result; label parity gaps | [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) |
| New hybrid retrieval path | Compose vector search + graph traversal; scores stay candidates | [GRAPHRAG.md](GRAPHRAG.md), retrieval leaves for ANN |
| New processor GraphRAG stage | Domain logic under processors + handoff to KG; thin MCP only | [GRAPHRAG.md](GRAPHRAG.md), [processing/README.md](../processing/README.md) |
| New optimizer family or critic | Subclass `BaseOptimizer` / `BaseCritic`; preserve loop authority rules | [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) |
| New lifecycle hook or metric | Hooks + optional metrics; never invent completion | [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) |
| Optional dependency lifecycle | Lazy import; feature degrade OK; inventing facts/proof not OK | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |

**Anti-patterns (all leaves agree):** promoting extraction confidence to
committed fact without store commit; treating Neo4j-compat success as Bolt
Neo4j product parity; collapsing hybrid scores, critic scores, and proofs;
running formal allow/deny from GraphRAG alone; business logic only in MCP
files; citing undated “99.99% coverage / N tests” banners as architecture;
assuming missing LLM or Neo4j extras mean undocumented architecture rather
than unprovisioned capability.

## 7. Documentation routes by authority class

### 7.1 Canonical architecture (preferred)

| Document | Role |
| --- | --- |
| **This index** | Routing, family status, extension map |
| [KNOWLEDGE_GRAPH_LIFECYCLE.md](KNOWLEDGE_GRAPH_LIFECYCLE.md) | Facts, engine, storage, Neo4j-compat, lineage |
| [GRAPHRAG.md](GRAPHRAG.md) | Hybrid retrieval and GraphRAG product composition |
| [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) | Optimizer control loops and critic authority |
| [retrieval/README.md](../retrieval/README.md) | Sibling hub for embeddings / stores / search |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Product domain map (§4.4–4.5) |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Cross-domain hops |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Content identity vs provenance |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional capability lifecycle |
| [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) | Non-interchangeable authority layers |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Trust fail-closed vs feature degrade |

### 7.2 Retained component references (implementation anchors)

Use these live package paths as **component references**. Prefer architecture
leaves when contracts conflict with comments or older READMEs.

| Area | Paths |
| --- | --- |
| Knowledge graphs package | `ipfs_datasets_py/knowledge_graphs/` (`extraction/`, `core/`, `storage/`, `transactions/`, `indexing/`, `lineage/`, `query/`, `cypher/`, `jsonld/`, `ontology/`, `reasoning/`, `neo4j_compat/`, `migration/`) |
| Manager facade | `ipfs_datasets_py/core_operations/knowledge_graph_manager.py` |
| Optimizers package | `ipfs_datasets_py/optimizers/` (`common/`, `graphrag/`, `agentic/`, `logic_theorem_optimizer/`, `llm_lazy_loader.py`, CLI/REPL) |
| GraphRAG search integration | `ipfs_datasets_py/search/graphrag_integration/` |
| Processor GraphRAG | `ipfs_datasets_py/processors/specialized/graphrag/`, `processors/graphrag_integrator.py` |
| Intent-IR GraphRAG helpers | `ipfs_datasets_py/logic/intent_ir/graphrag/` (formal ownership remains logic) |
| Package-local READMEs | `knowledge_graphs` and `optimizers` package READMEs — **component notes**, subordinate to architecture leaves |

### 7.3 API, MCP, tutorials, and product guides

| Surface | Location | Role | Label |
| --- | --- | --- | --- |
| Knowledge graphs API reference | [docs/knowledge_graphs/API_REFERENCE.md](../../knowledge_graphs/API_REFERENCE.md) | Module API exposition | **API reference** — verify against current modules |
| Knowledge graphs component architecture | [docs/knowledge_graphs/ARCHITECTURE.md](../../knowledge_graphs/ARCHITECTURE.md) | Code-aligned layout | **maintained component map** — not a substitute for lifecycle leaf |
| Knowledge graphs quickstart / user guide | [QUICKSTART.md](../../knowledge_graphs/QUICKSTART.md), [USER_GUIDE.md](../../knowledge_graphs/USER_GUIDE.md) | Onboarding | **tutorial / user guide** |
| Knowledge graphs doc index (package) | [docs/knowledge_graphs/INDEX.md](../../knowledge_graphs/INDEX.md) | Package doc router | **component index** — architecture hub is **this page** |
| Optimizers API reference | [docs/api/OPTIMIZERS_API_REFERENCE.md](../../api/OPTIMIZERS_API_REFERENCE.md) | Public optimizer APIs | **API reference** — contracts in [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) |
| Optimizers selection / usage / CLI | [SELECTION_GUIDE.md](../../optimizers/SELECTION_GUIDE.md), [USAGE_GUIDE.md](../../optimizers/USAGE_GUIDE.md), [CLI_GUIDE.md](../../optimizers/CLI_GUIDE.md), [HOW_TO_ADD_NEW_OPTIMIZER.md](../../optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md) | Product how-to | **maintained guide** |
| GraphRAG optimizer quick start | [docs/optimizers/GRAPHRAG_QUICK_START.md](../../optimizers/GRAPHRAG_QUICK_START.md), [docs/OPTIMIZERS_QUICK_START.md](../../OPTIMIZERS_QUICK_START.md) | Short product entry | **tutorial** |
| RAG query optimizer notes | [docs/rag_optimizer/index.md](../../rag_optimizer/index.md) | Learning metrics / integration narrative | **maintained / mixed age** — prefer architecture leaves for authority |
| Tutorials | [docs/tutorials/graphrag_tutorial.md](../../tutorials/graphrag_tutorial.md), [graphrag_website_processing_tutorial.md](../../tutorials/graphrag_website_processing_tutorial.md) | End-to-end walkthroughs | **tutorial** |
| Ontology / extraction ops | [EXTRACTION_CONFIG_GUIDE.md](../../optimizers/EXTRACTION_CONFIG_GUIDE.md), guides under `docs/guides/knowledge_graphs/` | Operator lineage/migration notes | **ops / mixed** — lifecycle leaf wins on contracts |
| MCP graph tools | `mcp_server/tools/graph_tools/` | Thin create/query/hybrid tools | **MCP shim** |
| Optimizers CLI / REPL | `optimizers/cli.py`, `graphrag_repl.py` | Operator entrypoints | **CLI** |
| Dependency / init | [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Extras (`knowledge_graphs`, LLM stacks) | **cross-cutting ops** |
| Integration boundaries | [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Optional Neo4j/LLM/submodule ownership | **cross-cutting ops** |

Package-local completion reports and “PROJECT_COMPLETE” files are **historical
session evidence**, not preferred architecture.

### 7.4 Backend-specific and optional material (labeled)

| Material | Label | Use for |
| --- | --- | --- |
| Packaging extra `knowledge_graphs`; spaCy / transformers | **optional dependencies** | Extraction and NLP paths |
| IPLD/IPFS router vs in-memory engine | **backend-specific** (graph storage) | Durability claims only when backend + commit succeed |
| Live Neo4j Bolt export/import | **optional / external product** | Migration; not required for neo4j_compat core path |
| Hybrid vector side (FAISS/Qdrant/ES) | **backend-specific** (retrieval) | Capability gaps documented in retrieval leaves |
| Lazy LLM loaders, circuit breakers | **optional** | Optimizer generate/critique quality; dry-run remains valid offline |
| SPARQL remote validation endpoints | **optional** | Validation reports only when endpoint provisioned |
| Inferred ontology materialization | **optional reasoning product** | Labeled inferred copy; not formal theorem |

### 7.5 Historical migrations and status dumps (do not treat as current architecture)

Use only to understand **how** the tree got here or to migrate old call sites.
Always re-verify against the **canonical** leaves and live code. **Do not**
copy undated embedded coverage percentages, test counts, or “production ready”
banners into new architecture docs.

| Document / path | Topic | Label |
| --- | --- | --- |
| [docs/knowledge_graphs/MASTER_STATUS.md](../../knowledge_graphs/MASTER_STATUS.md), `EXECUTIVE_SUMMARY_*`, `REFACTORING_COMPLETE_*` | Package status snapshots with fixed counts | **historical status** — architecture leaves are SoT |
| [MASTER_REFACTORING_PLAN_2026.md](../../knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md), `IMPROVEMENT_TODO.md`, `ROADMAP.md` | Plans and backlogs | **historical / plan** |
| [MIGRATION_GUIDE.md](../../knowledge_graphs/MIGRATION_GUIDE.md), `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_*MIGRATION*` | Migration operator notes | **historical / operator migration** — re-check lifecycle leaf |
| `docs/guides/knowledge_graphs/*_2026_02_16*`, feature matrices with snapshot dates | Dated inventories | **historical snapshot** — do not undate counts |
| `docs/archive/knowledge_graphs/**` | Archived API/usage guides | **archive** |
| `docs/optimizers/*_SESSION_*`, `COMPLETE_IMPLEMENTATION_REPORT.md`, `*_STUBS.md`, phase summaries | Session and stub dumps | **historical evidence** |
| `docs/optimizers/COMPREHENSIVE_REFACTOR_PLAN.md`, query optimizer modularization plans | Refactor proposals | **historical plan** — [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) is architecture authority |
| `docs/OPTIMIZATION_LOOP_ARCHITECTURE.md` (if present at root) | Interim short note | **historical interim** — superseded by [OPTIMIZATION_LOOPS.md](OPTIMIZATION_LOOPS.md) |
| `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md`, archive GraphRAG consolidation plans | Multi-processor consolidation timeline | **historical migration** |
| `docs/archive/root_status_reports/GRAPHRAG_*`, `OPTIMIZER_*` | Session completion | **archive** |
| Fixed marketing counts (“99.99% coverage”, “N+ tests”) without current provenance | Inventory marketing | **historical** — do not use as current inventory authority |

## 8. Decision guide (quick chooser)

```text
What are you doing?
│
├─ Extract, commit, index, query, or reason over graph facts?
│    → KNOWLEDGE_GRAPH_LIFECYCLE.md
│    → durability?  need IPLD/backend + commit
│    → Neo4j-shaped API?  neo4j_compat is a view, not Bolt product ownership
│
├─ Hybrid vector + graph retrieval, evidence chains, PDF/website GraphRAG?
│    → GRAPHRAG.md
│    → ANN backend details?  retrieval/README.md leaves
│    → scores/recommendations?  candidates only, not proof
│
├─ Implement or extend generate → critique → optimize → validate?
│    → OPTIMIZATION_LOOPS.md
│    → GraphRAG ontology harness vs logic-theorem vs agentic family
│    → missing LLM?  optional lazy loader; dry-run remains valid
│
├─ Pure embeddings / vector store / semantic search only?
│    → retrieval/README.md
│
├─ Formal proof, attestation, or authorization?
│    → logic/README.md  (do not promote GraphRAG/optimizer output to allow)
│
├─ Add a new knowledge capability?
│    → §6 Extension recipes → owning leaf
│
├─ Only reading MASTER_STATUS, session reports, or old migration plans?
│    → §7.5 historical, then re-check canonical leaf
│
└─ Cross-domain “where does the artifact go next?”
     → END_TO_END_DATA_FLOW.md, then retrieval / storage / logic / MCP
```

## 9. Related architecture and governance

| Document | Relationship |
| --- | --- |
| [architecture/README.md](../README.md) | Architecture documentation hub |
| [ARCHITECTURE_GUIDE_TEMPLATE.md](../ARCHITECTURE_GUIDE_TEMPLATE.md) | Guide contract |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | Product context |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | Hermetic imports and extras |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Optional Neo4j/LLM boundaries |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | CLI/module entry points |
| [retrieval/README.md](../retrieval/README.md) | Retrieval index (embeddings/stores/search) |
| [processing/README.md](../processing/README.md) | Processing index (may emit GraphRAG artifacts) |
| [storage/README.md](../storage/README.md) | Storage index (CIDs/backends; stores graph payload bytes) |
| [logic/README.md](../logic/README.md) | Formal authority (not critic scores) |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Evidence precedence |
| [INFORMATION_ARCHITECTURE.md](../../maintenance/INFORMATION_ARCHITECTURE.md) | Doc IA |

## 10. Validation

Bounded offline checks for this index:

```bash
# Declared output present and keyword coverage (IPFSDOC-033 gate)
test -s docs/architecture/knowledge/README.md
rg -n 'KNOWLEDGE_GRAPH_LIFECYCLE|GRAPHRAG|OPTIMIZATION_LOOPS|optional|compat|canonical' \
  docs/architecture/knowledge/README.md

# Canonical leaves still present
test -s docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md
test -s docs/architecture/knowledge/GRAPHRAG.md
test -s docs/architecture/knowledge/OPTIMIZATION_LOOPS.md

# Package anchors for major families
test -d ipfs_datasets_py/knowledge_graphs
test -d ipfs_datasets_py/knowledge_graphs/neo4j_compat
test -d ipfs_datasets_py/knowledge_graphs/storage
test -d ipfs_datasets_py/optimizers
test -d ipfs_datasets_py/optimizers/graphrag
test -d ipfs_datasets_py/optimizers/common
test -d ipfs_datasets_py/search/graphrag_integration
```

Known limits: live Neo4j Bolt, spaCy/transformers models, LLM backends, and
hybrid vector services are environment- and secret-gated. Optional extras may
be absent. This index only proves **routing, ownership language, and status
labeling**, not full graph durability or optimizer runtime proof. A green
dry-run, critic score, or hybrid hit list is not a committed fact or formal
allow.

## 11. Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Initial **canonical** knowledge and GraphRAG architecture index for `IPFSDOC-033` / `KnowledgeArchitectureIndex@1` |
