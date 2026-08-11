# Domain ownership map — IPFS Datasets Python

| Field | Value |
| --- | --- |
| Interface | `DomainOwnershipMap@1` |
| Task | `IPFSDOC-010` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `ipfs_datasets_py/` first-level topology; package-root modules; `pyproject.toml` / `setup.py`; `ipfs_datasets_py/logic/submodule_registry.py`; `tests/`; [CURRENT_STATE_BASELINE.md](../maintenance/CURRENT_STATE_BASELINE.md) §5; [COVERAGE_MATRIX.md](../maintenance/COVERAGE_MATRIX.md) §2 |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent |
| Related | [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md), domain leaves under `docs/architecture/{processing,storage,retrieval,knowledge,logic,mcp,runtime}/` (planned) |
| Review cadence | semi-annual or after domain moves |

## 1. Purpose

This map answers: **which top-level package domains exist, what each owns,
where authority ends, and which surfaces are canonical vs compatibility.**
It is the placement guide for new code, tools, and documentation. System-level
actors and product surfaces are in [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md).

## 2. How to use this map

1. Find the domain that **owns the responsibility** (not where a thin wrapper lives).
2. Put new business logic in that domain; put MCP/CLI exposure as thin wrappers.
3. Prefer **canonical** import paths; mark **compatibility** aliases as such.
4. Treat empty submodule checkouts and missing extras as **availability** issues, not domain absence.
5. When docs disagree with code or tests, apply
   [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md).

### Authority legend

| Tag | Meaning |
| --- | --- |
| **Owns** | May define schemas, algorithms, and public APIs for the concern |
| **Does not own** | Must call or delegate; another domain or external system is authoritative |
| **Canonical** | Preferred path for new work |
| **Compat** | Alias, deprecated, or install-path-dependent surface |
| **Optional** | Requires extras, binaries, or submodules |

---

## 3. Domain clusters (navigation)

| Cluster | Domains | Target architecture home (program) |
| --- | --- | --- |
| **Processing / ingest** | `processors`, `multimedia`, `web_archiving`, `cli` (ingest CLIs) | `docs/architecture/processing/` |
| **Logic / IR / proof** | `logic` (+ registry families), related `optimizers` theorem loops | `docs/architecture/logic/` |
| **Knowledge / GraphRAG** | `knowledge_graphs`, `optimizers`, parts of `search` | `docs/architecture/knowledge/` |
| **Retrieval** | `embeddings`, `vector_stores`, `search`, `ml` | `docs/architecture/retrieval/` |
| **Storage / release** | `storage`, `caching`, `ipfs_cluster`, `p2p_networking`, `huggingface`, `voice` | `docs/architecture/storage/` |
| **Trust / privacy** | `wallet`, `audit`, package `security.py` | `WALLET_TRUST_AND_PRIVACY.md`, security guides |
| **MCP / tools** | `mcp_server` | `docs/architecture/mcp/` |
| **Runtime / platform** | Profile G facades, `accelerate_integration`, `workflow_automation`, `sessions` | `docs/architecture/runtime/` |
| **Cross-cutting ops** | `config`, `dashboards`, `admin`, `alerts`, `analytics`, `error_reporting`, `messaging`, `rate_limiting`, `monitoring*` | ops / MCP observability leaves |
| **Support** | `utils`, `skills`, `scripts`, `static`, `templates`, `install`, in-package `tests` | developer / n/a |

Python counts below are baseline evidence from IPFSDOC-001 (2026-08-03); re-measure after large tree changes.

---

## 4. Core product domains

### 4.1 `processors` (canonical processing)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/processors/` (~974 `*.py`) |
| **Responsibility** | Multimodal and domain processors: PDF, OCR, GraphRAG website processing, legal/medical scrapers, file conversion, investigation, geospatial, finance, Discord, Wikipedia_x, serialization, engines, batch pipelines |
| **Owns** | Processor APIs, scraper CLIs (e.g. Netherlands laws), form-filling / PDF IR, domain adapters under `processors/*` |
| **Does not own** | MCP protocol framing (`mcp_server`); formal IR identity (`logic.ir_core`); vector index backends (`vector_stores`); wallet grants |
| **Inbound** | Python API, MCP `pdf_tools` / `legal_dataset_tools` / media tools, domain CLIs under `cli/` and `processors.cli` |
| **Outbound** | `web_archiving` engines, optional multimedia submodules, storage/IPFS helpers, LLM routers |
| **Canonical** | `ipfs_datasets_py.processors.*` |
| **Compat / optional** | Multimedia git submodules; `common_crawl_search_engine` submodule; heavy scrapers need `scraping` / Playwright extras |
| **Tests / contracts** | `tests/` processor and scraper suites; packaging scripts for Netherlands laws |
| **Docs target** | `architecture/processing/*` |

Major subtrees: `core/`, `engines/`, `file_converter/`, `legal_scrapers/`, `legal_data/`, `medical_scrapers/`, `multimedia/`, `web_archiving/`, `ipfs/`, `investigation/`, `domains/`, `finance/`, `discord/`, `wikipedia_x/`, `serialization/`, `groth16_backend/`, `provekit_backend/`.

### 4.2 `logic` (canonical formalization, IR, provers)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/logic/` (~650 `*.py`) |
| **Responsibility** | Logic families, IR core, legal/security/intent IR, admissibility/authorization gates, proof corpus, external provers, ZKP bridges, formalization contracts |
| **Owns** | IR schemas and identity; conversion/compilers; prover routers; proof attestation models; logic API/CLI; **submodule registry** |
| **Does not own** | GraphRAG optimizer loops (`optimizers`); Neo4j engine implementation (`knowledge_graphs` — cross-listed in registry only); MCP transport |
| **Inbound** | Library callers, MCP `logic_tools` / hammers, optimizers, security verification workflows |
| **Outbound** | Optional provers, ErgoAI, CEC assets (submodules), `knowledge_graphs` for frame-logic graphs |
| **Canonical** | `logic.ir_core`, `logic.intent_ir`, `logic.security_ir`, `logic.legal_ir`, `logic.integration`, `logic.admissibility`, `logic.external_provers` |
| **Compat** | `logic.tools` (**deprecated** → `logic.integration`); empty CEC/ErgoAI trees until checkout |
| **Extras** | `logic`, `theorem-provers`, `profile-f-zk`, `provekit`, `groth16` |
| **Tests** | `tests/unit/logic/test_logic_submodule_registry.py`; IR compatibility and authz integration tests |
| **Docs target** | `architecture/logic/*` |

#### Logic submodule registry (machine-readable authority)

Source: `ipfs_datasets_py/logic/submodule_registry.py`.

Public helpers: `logic_submodule_specs()`, `logic_submodule_names()`,
`logic_submodule_spec(name)`, `logic_integration_manifest()`,
`logic_submodule_import_report()`, optimizer scope/file hints.

| Registry name | Roles (summary) | Notes |
| --- | --- | --- |
| `common` | foundation, cache, validation, converter contract | Shared converter primitives |
| `types` | foundation, IR type contracts | Shared aliases |
| `ir_core` | canonicalization, identity, provenance, schema registry, artifacts | Dependency-light IR foundation |
| `formalization` | compiler contract, formal views | Domain-neutral samples/views |
| `legal_ir` | legal formalization adapter | Compatibility adapter |
| `security_ir` | security declarations, adapters, result authority | Immutable Security IR |
| `intent_ir` | intent schema, decode, canonicalize | Source-grounded Intent IR |
| `intent_ir.invocation` | invocation envelopes; SkillCenter/prompt/MCP adapters | **Non-executing** adapters |
| `proof_corpus` | attested proofs, revocation, trust policy | Simulated ZKP never production-authoritative |
| `admissibility` | authorization gate, receipts, rollout | Default legal-strict profile; rollout defaults off/audit |
| `bridge` | legal IR bridge registry for optimizers/provers/KG | Optimizer contract |
| `fol` | first-order conversion | NLP → FOL |
| `deontic` | legal norms, deontic IR | Norm graphs / KB |
| `modal` | modal compiler, autoencoder, frame-logic KG bridge | Crosses into optimizers paths |
| `flogic` | frame-logic types, ErgoAI wrapper | Optional ErgoAI |
| `flogic_optimizer` | semantic optimizer for frame-logic | Loss-aware |
| `TDFOL` | temporal deontic FOL | Prover + strategies |
| `CEC` | cognitive event calculus | Optional SPASS/ShadowProver |
| `external_provers` | Z3, CVC5, Lean, Coq, SymbolicAI router | Lazy install |
| `integration` | high-level bridges, UCAN, symbolic | Preferred over `tools` |
| `integrations` | GraphRAG / UnixFS adapters | Outside core theorem bridge tree |
| `zkp` | ZKP circuits / backends | Optional circom/snarkjs |
| `security` | input validation, rate limit, LLM breaker | Logic-local security controls |
| `security_models` | exchange-style security model IR + provers | Proof reports / MTL monitor |
| `observability` | structured logs, spans | Logic/prover runs |
| `ml_confidence` | optional ML quality scores | Optional deps |
| `batch_processing` | batch conversion | Optional |
| `benchmarks` | conversion/prover benchmarks | Optional |
| `monitoring` | long-running daemon metrics | Optional |
| `knowledge_graphs` | **cross-package** endpoint to `ipfs_datasets_py.knowledge_graphs` | Manifest visibility only |
| `tools` | **deprecated compatibility** | Migrate to `integration` |
| `ErgoAI` | external binary placeholder | `import_check=False` |

### 4.3 `mcp_server` (canonical MCP / HTTP tool host)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/mcp_server/` (~531 `*.py`, large package-local docs) |
| **Responsibility** | Model Context Protocol server, tool registration, FastAPI service, MCP++ peers/workflows, hierarchical tool manager, transports (stdio/HTTP/P2P adapters) |
| **Owns** | Protocol adapters, tool wrappers under `mcp_server/tools/`, server config, FastAPI routes, MCP ADRs in package `docs/adr/` |
| **Does not own** | Domain algorithms (must call `processors`, `logic`, `vector_stores`, …); IPFS kit internals; agent-supervisor leases |
| **Inbound** | MCP clients, CLI dynamic tool runner, operators via Docker/systemd |
| **Outbound** | All domain packages; optional `ipfs_kit` MCP URL; wallet router in FastAPI when enabled |
| **Canonical** | `python -m ipfs_datasets_py.mcp_server`; `start_stdio_server` / `start_server`; tools as thin wrappers |
| **Compat** | `simple_server` fallback; `legacy_mcp_tools`; optional MCP++ |
| **Extras** | `api` for FastAPI stack |
| **Docs target** | `architecture/mcp/*` (ADRs remain package-local until reconcile) |

Representative tool categories: `dataset_tools`, `ipfs_tools`, `embedding_tools`, `graph_tools`, `vector`/`storage` tools, `pdf_tools`, `media_tools`, `logic_tools`, `legal_dataset_tools`, `security_tools`, `audit_tools`, `auth_tools`, `web`/`finance`/`discord`/`email` tools, admin/dashboard/monitoring tools.

### 4.4 `optimizers` (canonical optimization loops)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/optimizers/` (~385 `*.py`) |
| **Responsibility** | GraphRAG, ontology, logic-theorem, agentic, and performance optimizers; lifecycle hooks; REPL and CLI |
| **Owns** | Optimizer pipelines, loss/evaluation loops, agentic optimization modules, optimizer API return types |
| **Does not own** | Core IR schemas (`logic.ir_core`); production admissibility (`logic.admissibility`); MCP transport |
| **Inbound** | Python API, `optimizers.cli`, MCP analysis/workflow tools, benchmarks |
| **Outbound** | `logic` bridges/compilers, `knowledge_graphs`, embeddings/search |
| **Canonical** | `ipfs_datasets_py.optimizers` (GraphRAG / logic theorem / agentic trees) |
| **Docs target** | `architecture/knowledge/OPTIMIZATION_LOOPS.md` (planned); interim `docs/optimizers/*`, `docs/api/OPTIMIZERS_API_REFERENCE.md` |

### 4.5 `knowledge_graphs` (canonical KG / GraphRAG data plane)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/knowledge_graphs/` (~103 `*.py`) |
| **Responsibility** | Extraction, lineage, reasoning helpers, Neo4j-compatible decentralized graph engine, finance GraphRAG, cypher paths |
| **Owns** | Graph engine/database APIs, extraction pipelines, cross-document lineage types |
| **Does not own** | Query optimizer product loops (`optimizers`); formal deontic/modal compilers (`logic`) |
| **Inbound** | Processors GraphRAG paths, logic modal/frame bridges, MCP graph tools |
| **Outbound** | Storage/IPLD, Neo4j optional, vector/search for hybrid retrieval |
| **Canonical** | `ipfs_datasets_py.knowledge_graphs` |
| **Extras** | `knowledge_graphs` |
| **Registry** | Also listed in logic registry as cross-package endpoint |
| **Docs target** | `architecture/knowledge/*` |

### 4.6 `vector_stores` (canonical vector backends)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/vector_stores/` (~19 `*.py`) |
| **Responsibility** | Vector store abstractions and backends (FAISS, Elasticsearch, Qdrant, bridges) |
| **Owns** | Store interfaces, backend configs, local vector persistence APIs |
| **Does not own** | Embedding model training (`embeddings` / `ml`); GraphRAG graph structure (`knowledge_graphs`) |
| **Inbound** | Search, MCP vector/storage tools, optimizers |
| **Outbound** | Optional FAISS/Qdrant/ES clients (`vectors` extra) |
| **Canonical** | `ipfs_datasets_py.vector_stores` |
| **Docs target** | `architecture/retrieval/VECTOR_STORES.md` |

### 4.7 `wallet` (canonical user-controlled trust surface)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/wallet/` (~17 `*.py`) |
| **Responsibility** | User-controlled encrypted data wallet: models, grants, multisig approval gates, privacy policy, proofs, storage health, CLI/service/API |
| **Owns** | Wallet domain models, grant/approval flows, analytics consent policy, proof receipt types for wallet operations |
| **Does not own** | Chain settlement networks; OS keystores; formal Security IR (`logic.security_ir`); MCP auth tools alone without wallet service |
| **Inbound** | FastAPI wallet router (when enabled), `wallet.cli`, security guides |
| **Outbound** | Storage refs, optional external proof backends for location distance |
| **Canonical** | `ipfs_datasets_py.wallet` |
| **Docs target** | `architecture/WALLET_TRUST_AND_PRIVACY.md` |

### 4.8 `voice` (canonical immutable voice-dataset contracts)

| | |
| --- | --- |
| **Path** | `ipfs_datasets_py/voice/` (~13 `*.py`) |
| **Responsibility** | Abby voice dataset schema, normalization, materialize/reconcile, HF release, GraphRAG template ingestion receipts, worksets |
| **Owns** | Voice dataset contracts, normalize/dedupe, release loader contracts, GraphRAG voice template provider types |
| **Does not own** | TTS model training; HF Hub availability; general multimedia conversion (`processors` / multimedia submodules) |
| **Inbound** | `voice_router.py` facade, release/publication workflows |
| **Outbound** | Lazy Arrow/HF integrations; storage/IPFS publication paths |
| **Canonical** | `ipfs_datasets_py.voice` |
| **Docs target** | storage / immutable dataset release leaves |

---

## 5. Retrieval and ML domains

| Domain | Path | Owns | Does not own | Notes |
| --- | --- | --- | --- | --- |
| **embeddings** | `embeddings/` | Embedding/generation engines, sparse embeddings, semantic search engine helpers | Vector DB backends | Works with root `embedding_router` / `embeddings_router` |
| **search** | `search/` | Content discovery, GraphRAG search integration, query optimizer hooks, recommendations, CLI | Core KG storage | Bridges to logic integration |
| **ml** | `ml/` | ML helpers and package-local docs/stubs | Training cluster orchestration | Often optional/heavy |

---

## 6. Storage, network, and publication domains

| Domain | Path | Owns | Does not own | Notes |
| --- | --- | --- | --- | --- |
| **storage** | `storage/` | Storage engine facade | Full IPLD ecosystem | Thin; related IPLD lives with vectors/docs history |
| **caching** | `caching/` | Cache layers for datasets/tools | Distributed cluster policy | |
| **ipfs_cluster** | `ipfs_cluster/` | Cluster helper bindings | Cluster daemon | Sparse |
| **p2p_networking** | `p2p_networking/` | libp2p kit wrappers, peer registry, task queue / workflow engines, CLI | Public DHT governance | MCP P2P tools call here |
| **huggingface** | `huggingface/` | HF dataset integration helpers | Hub hosting SLA | Voice release adjacency |
| **web_archiving** | `web_archiving/` | Unified scraper/archive engines (Wayback, IPWB, search engines, contracts) | Legal corpus policy ownership (processors legal) | Overlaps processors web_archiving subtree — prefer domain module for engines |

---

## 7. Platform, ops, and support domains

| Domain | Path | Owns | Status / notes |
| --- | --- | --- | --- |
| **cli** | `cli/` | Domain CLIs (scraper, finance, discord, docket, workspace, email, …) | Product surface; align with MCP |
| **config** | `config/` | Package config helpers | Complements root `config.py` / examples |
| **core_operations** | `core_operations/` | Core ops helpers | API docs partial |
| **dashboards** | `dashboards/` | Dashboard UIs/services | Productization status review (P2) |
| **admin** | `admin/` | Admin helpers | Thin |
| **alerts** | `alerts/` | Alerting primitives | Ops |
| **analytics** | `analytics/` | Analytics helpers | Thin |
| **audit** | `audit/` | Audit / provenance integration package | Security guides; not proof authority |
| **error_reporting** | `error_reporting/` | CLI/server error handlers | Used by CLI and MCP |
| **messaging** | `messaging/` | SMS bridge (`ipfs-datasets-sms-bridge`) | Console script |
| **rate_limiting** | `rate_limiting/` | Rate limit helpers | Policy/ops |
| **sessions** | `sessions/` | Session helpers | Thin |
| **workflow_automation** | `workflow_automation/` | Workflow automation | Sparse / P2 |
| **accelerate_integration** | `accelerate_integration/` | Compat with accelerate placement | External ownership of accelerate |
| **skills** | `skills/` | Agent skill refs | Agent developer guides |
| **utils** | `utils/` | Shared utilities | Not a product domain |
| **scripts** | `scripts/` | Dev utilities inside package | Not product domain |
| **static** / **templates** | asset dirs | Static assets / templates | n/a as product domains |
| **install** | empty package dir | — | **n/a** — do not document as a feature |
| **tests** (in-package) | `ipfs_datasets_py/tests/` | Package-local test helpers | Primary suite is repo `tests/` |

---

## 8. Package-root modules (cross-cutting)

Not first-level directories; still part of the public/runtime map:

| Module | Role | Authority boundary |
| --- | --- | --- |
| `__init__.py` | Version, hermetic import policy, `initialize()`, lazy exports | Does not import MCP/FastAPI/LLM by default |
| `ipfs_datasets.py` / `dataset_manager.py` | Dataset API used by tools | Dataset ops; not storage backends |
| `router_deps.py`, `*_router.py` | Backend/dependency injection routers | Selection only; backends own behavior |
| `lazy_dependencies.py`, `deps_resolver.py`, `dependency_catalog.py`, `auto_installer.py` | Optional dependency loading | Install surface vs capability honesty |
| `security.py` | Security facade | Defer to logic security / wallet / audit as appropriate |
| `audit.py` | Audit facade | Same |
| `monitoring.py`, `monitoring_engine.py` | Observability | Not proof |
| `profile_g.py` | Profile G facade → `logic.profile_g` | Planning/evidence; fail-closed side effects |
| `voice_router.py` | Voice entry router | Voice package owns contracts |
| `content_discovery.py` | Discovery helper | Search/content adjacency |
| `database_utils.py`, `config.py` | Shared config/DB utils | |

---

## 9. Canonical vs compatibility matrix (cross-domain)

| Concern | Canonical surface | Compatibility / legacy |
| --- | --- | --- |
| Logic integrations | `logic.integration`, family packages (`fol`, `deontic`, …) | `logic.tools` (deprecated) |
| MCP tools | `mcp_server/tools/<category>` thin wrappers | `legacy_mcp_tools`, simple server fallback |
| CLI install names | `pyproject.toml` four scripts | `setup.py` extra names (`ipfs-datasets`, `file-converter`, `fc`) |
| Multimedia converters | Initialized multimedia submodules + `processors.multimedia` | Empty `multimedia/` checkout |
| Profile G | `logic.profile_g` + MCP profile_g service | Root `profile_g.py` facade only |
| Vector search stack | `embeddings` + `vector_stores` + `search` | Historical root IPLD_* guides (mixed age) |
| Knowledge extraction | `knowledge_graphs` + `optimizers.graphrag` | Archived extraction experiments |
| Authorization | `logic.admissibility` + intent IR | UI/MCP discovery alone |

---

## 10. External systems and ownership handoff

| External / optional | Integration points | Owner of truth |
| --- | --- | --- |
| `ipfs_kit_py` | Submodule; MCP kit tools | External kit repo |
| `ipfs_accelerate_py` | Submodule; dataset manager accelerate path; agent supervisor | External accelerate repo |
| Theorem provers | `logic.external_provers`, install script | Binaries + their vendors |
| CEC / Talos / ShadowProver / DCEC | Submodules under `logic/CEC/` | External repos |
| ErgoAI | `logic/ErgoAI` placeholder | External engine |
| FAISS / Qdrant / Elasticsearch | `vector_stores` | Those projects |
| Neo4j | `knowledge_graphs` | Neo4j / deploy ops |
| Hugging Face | `huggingface`, `voice` release | Hub + local contracts |
| Playwright / Selenium / Scrapy | processors / scraping extra | Those projects |
| Docker / k8s | `docker/`, `deployments/` | Operator manifests (rank 4 authority for ops shape) |

---

## 11. Test and packaging grounding

| Evidence class | Where | Use for domain claims |
| --- | --- | --- |
| Unit / integration tests | `tests/` (primary), package `tests/` | Contracts, registry, IR, tools |
| Logic registry tests | `tests/unit/logic/test_logic_submodule_registry.py` | Registry completeness / import report |
| Packaging | `pyproject.toml`, `setup.py`, `MANIFEST.in` | Extras, scripts, package data (Groth16/Provekit assets, legal IR schemas) |
| MCP ADRs | `mcp_server/docs/adr/` | Why tool/server boundaries exist |
| Benchmarks | `benchmarks/` | Performance evidence (not product API) |

---

## 12. Responsibility summary (quick reference)

| Domain | One-line ownership |
| --- | --- |
| **processors** | Ingest, convert, scrape, and domain-specific document/media processing |
| **logic** | Formal IR, compilers, provers, proof corpus, admissibility; registry is the map |
| **mcp_server** | Expose domain capabilities via MCP/HTTP; never reimplement core logic |
| **optimizers** | Closed-loop GraphRAG / logic / agentic optimization |
| **knowledge_graphs** | Graph extraction, storage, Neo4j-compat engine |
| **vector_stores** | Vector backend abstraction and implementations |
| **wallet** | User-controlled encrypted data, grants, privacy policy |
| **voice** | Immutable voice dataset normalize/release contracts |
| **embeddings** / **search** / **ml** | Embedding generation, query/search, ML helpers |
| **storage** / **caching** / **p2p** / **ipfs_cluster** | Persistence, cache, P2P workflows, cluster helpers |
| **web_archiving** / **huggingface** | Archive/search engines; HF publication helpers |
| **cli** / **config** / **core_operations** | User CLI, configuration, core ops |
| **audit** / **security facades** | Provenance and security entry points (not sole authz) |
| **ops thin domains** | dashboards, admin, alerts, analytics, messaging, rate_limiting, sessions, workflow_automation |
| **support** | utils, skills, scripts, static, templates, empty install |

---

## 13. Non-goals of this map

- Detailed end-to-end sequence diagrams (sibling flow guide).
- Per-tool MCP catalog (package MCP docs / architecture MCP leaves).
- Claiming coverage completeness for documentation (see COVERAGE_MATRIX).
- Resolving packaging CLI drift in code (documented only).
- Treating empty submodules as implemented features.
- Owning external agent-supervisor execution semantics.

## 14. Related and next guides

| Guide | Depends on this map for |
| --- | --- |
| [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) | Actors and surfaces |
| Planned domain leaves under `processing/`, `logic/`, `mcp/`, `knowledge/`, `retrieval/`, `storage/`, `runtime/` | Per-domain flows and invariants |
| [COVERAGE_MATRIX.md](../maintenance/COVERAGE_MATRIX.md) | Doc gap priority per domain |
| [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](../maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | Package-local vs hub docs |

## 15. Validation

```bash
test -s docs/architecture/SYSTEM_CONTEXT.md && test -s docs/architecture/DOMAIN_MAP.md
rg -n 'processors|logic|mcp_server|optimizers|knowledge_graphs|vector_stores|wallet|voice' docs/architecture/DOMAIN_MAP.md
```

Optional re-inventory:

```bash
ls -1d ipfs_datasets_py/*/ | sed 's|ipfs_datasets_py/||;s|/$||' | sort
python3 -c "from ipfs_datasets_py.logic.submodule_registry import logic_submodule_names; print(logic_submodule_names())"
```
