# Documentation coverage matrix

| Field | Value |
| --- | --- |
| Interface | `DocumentationCoverageMatrix@1` |
| Task | `IPFSDOC-005` |
| Status | `evidence` (coverage snapshot for the documentation program) |
| Owner | documentation-governance |
| Source of truth | `ipfs_datasets_py/` layout (IPFSDOC-001 baseline); target tree in plan §6; task board outputs; package-local map (IPFSDOC-004); authority policy (SOURCE_AUTHORITY.md) |
| Last verified | 2026-08-03 |
| Audience | maintainers, architects, documentation authors, implementation agents |
| Companion | [SOURCE_AUTHORITY.md](SOURCE_AUTHORITY.md) |

## Purpose

This matrix maps **every top-level production domain** under `ipfs_datasets_py/`
and every **target audience** to the state of **canonical documentation
coverage**. It is the reviewed scope input for architecture and audience tasks:
writers use it to find the intended home, avoid inventing competing roots, and
prioritize P0/P1 gaps.

It does **not** rewrite product code or move legacy files. Status labels
describe documentation coverage only.

## How to read this matrix

### Coverage status (exactly one per cell or row concern)

| Status | Meaning |
| --- | --- |
| **current** | Usable body of record exists today for that concern (may still need refresh against code/tests) |
| **planned** | Program board assigns a named canonical deliverable; page not yet landed or not yet authoritative |
| **missing** | No adequate canonical home and no sufficient substitute; must not be cited as covered |
| **n/a** | Non-applicable: domain is empty, non-product, internal-only, or does not need that doc kind |

### Priority gaps

| Priority | Meaning |
| --- | --- |
| **P0** | Blocks truthful product entry, architecture wave, or high-risk surfaces (authz, wallet, MCP, proof boundaries) |
| **P1** | Important for complete domain/API coverage; may ship after P0 architecture spines |
| **P2** | Nice-to-have or thin domains; track but do not block release of core spines |

### Column legend (domain matrix)

| Column | Meaning |
| --- | --- |
| **Arch** | Architecture / ownership / flow guide |
| **User** | End-user or operator journey coverage |
| **Dev** | Contributor / extension guidance |
| **API** | Hand-maintained API/domain reference with provenance |
| **Ops/Sec** | Deployment, runbook, audit, or security boundary docs |

Secondary labels in cells may note **partial** (fragmented or competing hubs)
or **refresh** (body exists but drifted).

---

## 1. Target audiences

Audience IDs match [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) §1.

| Audience ID | Who | Primary canonical homes (target) | Entry coverage today | Status | Gap pri |
| --- | --- | --- | --- | --- | --- |
| `end-user` | Operators and data practitioners (Python API, CLI, MCP tools) | `docs/index.md`, `getting_started.md`, `installation.md`, `configuration.md`, `user_guide.md`, `user_guides/`, `tutorials/`, `examples/` | Root entry pages **present**; many claims flagged in drift matrix; tutorials mixed age | **current** (partial / refresh) | **P0** refresh install/config/user journeys after architecture leaves |
| `developer` | Contributors extending the package | `docs/developer_guide.md`, `developer_guides/*`, `CONTRIBUTING.md` | Developer entry **present**; `DOCUMENTATION_CONTRIBUTING.md` **current**; recipes/testing/FOR_AGENTS **planned** | **planned** + partial current | **P0** `FOR_AGENTS`, extension recipes, testing evidence |
| `architect` | Subsystem boundary designers | `docs/architecture/**`, `architecture/decisions/` | Hub + templates **present**; SYSTEM_CONTEXT / DOMAIN_MAP / domain leaves **planned**; MCP ADRs package-local **current** | **planned** (ADRs current) | **P0** system context, domain map, domain leaves |
| `operator` | Deployers and on-call | `docs/deployment/`, `guides/operations/`, security guides | Deployment guides **current** (partial); MCP runbook **planned**; security corpus large but mixed lifecycle | **partial / planned** | **P0** MCP ops runbook; **P1** unified ops spine |
| `agent` | Implementation agents and automation | `developer_guides/FOR_AGENTS.md` (target), architecture guides, ADRs, this maintenance set | Maintenance IA/authority/coverage **current**; FOR_AGENTS **missing** | **missing** (agent entry) | **P0** |
| `maintainer` | Doc owners and release owners | `docs/maintenance/**` | Baseline, drift, IA, package map, authority, this matrix **current**; legacy disposition / release evidence **planned** | **current** (governance spine) | **P1** legacy disposition + release evidence |

### Audience × product-entry surface

| Surface | Path | Audiences | Coverage status | Notes / owner tasks |
| --- | --- | --- | --- | --- |
| Product index | `docs/index.md` | end-user, maintainer | **current** (refresh) | Late nav owner IPFSDOC-095 |
| Getting started | `docs/getting_started.md` | end-user | **current** (refresh) | IPFSDOC-092 |
| Installation | `docs/installation.md` | end-user, operator | **current** (refresh; drift on extras/Python) | IPFSDOC-091 |
| Configuration | `docs/configuration.md` | end-user, operator | **current** (refresh) | IPFSDOC-091 |
| User guide | `docs/user_guide.md` | end-user | **current** (partial; stale imports in drift) | IPFSDOC-092 |
| Developer guide | `docs/developer_guide.md` | developer, agent | **current** (refresh) | IPFSDOC-074 |
| Features / changelog | `docs/FEATURES.md`, `docs/CHANGELOG.md` | end-user, maintainer | **current** (claim repair) | IPFSDOC-064 |
| Glossary | `docs/GLOSSARY.md` | all | **current** (refresh) | IPFSDOC-093 |
| Architecture hub | `docs/architecture/README.md` | architect, developer, agent | **current** (thin; leaves planned) | IPFSDOC-090 |
| MCP ADR bodies | `ipfs_datasets_py/mcp_server/docs/adr/` | architect, agent | **current** | IPFSDOC-016 index/reconcile |
| Agent context | `docs/developer_guides/FOR_AGENTS.md` | agent | **planned** / **missing** | IPFSDOC-073 area |
| Doc contribution | `docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md` | developer, maintainer | **current** | IPFSDOC-003 |
| MkDocs nav | `mkdocs.yml` | end-user (published site) | **current** (narrow: 6 top labels) | Expand only via nav tasks |

---

## 2. Top-level production domains

Inventory: **39** first-level directories under `ipfs_datasets_py/` plus notable
root modules (IPFSDOC-001 §5.1). Python and Markdown counts are baseline
evidence; re-measure after large tree changes.

### 2.1 Core product domains (high code or high risk)

| Domain | `*.py` | Package `*.md` | Arch | User | Dev | API | Ops/Sec | Overall | Canonical home (target) | Interim / competing | Gap pri | Board anchors |
| --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **processors** | 974 | 95 | partial | partial | partial | missing | partial | **planned** (refresh) | `docs/architecture/processing/*` | `docs/guides/processors/*` (architecture candidate); package multimedia/legal READMEs; archive refactor plans | **P0** | IPFSDOC-020–022 |
| **logic** | 650 | 20 | partial | partial | partial | partial | partial | **planned** (refresh) | `docs/architecture/logic/*` | Large `docs/logic/` hub (plans + guides mixed); package READMEs | **P0** | IPFSDOC-040–046 |
| **mcp_server** | 531 | 176 | partial | partial | partial | partial | planned | **planned** (ADRs current) | `docs/architecture/mcp/*` + ops runbook | Package `mcp_server/docs/` + ADRs; root MCP_* guides; `docs/architecture/MCP_*` | **P0** | IPFSDOC-050–054 |
| **optimizers** | 385 | 4 | partial | partial | partial | current* | n/a→partial | **partial / planned** | `docs/architecture/knowledge/OPTIMIZATION_LOOPS.md` | `docs/optimizers/*`; `docs/api/OPTIMIZERS_API_REFERENCE.md` (navigated) | **P1** | IPFSDOC-033–034 |
| **knowledge_graphs** | 103 | 15 | partial | partial | partial | missing | n/a | **planned** | `docs/architecture/knowledge/*` | `docs/knowledge_graphs/*` | **P1** | IPFSDOC-032–034 |
| **search** | 34 | 5 | planned | partial | missing | missing | n/a | **planned** | `docs/architecture/retrieval/SEARCH_AND_QUERY.md` | Root/user guide fragments | **P1** | IPFSDOC-030 |
| **vector_stores** | 19 | 12 | partial | partial | missing | missing | n/a | **planned** | `docs/architecture/retrieval/VECTOR_STORES.md` | Root IPLD_VECTOR_* guides (mixed historical) | **P1** | IPFSDOC-030 |
| **embeddings** | 7 | 0 | planned | partial | missing | missing | n/a | **planned** | `docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md` | Routers at package root; ML stubs | **P1** | IPFSDOC-030 |
| **ml** | 33 | 17 | planned | missing | missing | missing | n/a | **planned** / missing | Future retrieval/knowledge API domains | Package stubs/READMEs | **P1** | API domain tasks |
| **wallet** | 17 | 0 | planned | missing | missing | missing | partial | **planned** / **missing** arch | `docs/architecture/WALLET_TRUST_AND_PRIVACY.md` | `docs/security_verification/*` (xaman/wallet evidence & plans—not product arch) | **P0** | IPFSDOC-060 area |
| **voice** | 13 | 0 | planned | missing | missing | missing | n/a | **planned** | `docs/architecture/storage/IMMUTABLE_DATASET_RELEASES.md` (+ storage hub) | No package-local docs | **P0** | IPFSDOC-026 |
| **huggingface** | 6 | 0 | planned | missing | missing | missing | n/a | **planned** | Storage publication / immutable releases + HF paths | No package-local docs | **P0** | IPFSDOC-025–026 |
| **Profile G** (runtime) | facade + `logic/profile_g` | see notes | planned | partial | missing | missing | planned | **planned** | `docs/architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md` | `docs/profile_g_datasets_provider.md` (**current** provider note); `ipfs_datasets_py/profile_g.py` facade | **P0** | IPFSDOC-017 |
| **web_archiving** | 15 | 0 | planned | partial | missing | missing | n/a | **planned** | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | Tutorials; legal scraper guides | **P1** | IPFSDOC-021 |
| **storage** | 2 | 0 | planned | partial | missing | missing | n/a | **planned** | `docs/architecture/storage/*` | IPLD/vector root guides | **P0** | IPFSDOC-023–027 |
| **caching** | 8 | 0 | planned | partial | missing | missing | n/a | **planned** | `docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md` | `docs/guides/DISTRIBUTED_CACHE.md` etc. | **P1** | IPFSDOC-023 |
| **p2p_networking** | 11 | 0 | planned | missing | missing | missing | n/a | **planned** | `docs/architecture/storage/P2P_AND_PUBLICATION.md` | Implementation plans under docs | **P1** | IPFSDOC-025 |
| **audit** | 18 | 26 | planned | n/a | missing | missing | partial | **planned** | `docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md` | Package stubs + security_verification corpus | **P0** | IPFSDOC-060 |
| **cli** | 13 | 0 | n/a→partial | partial | partial | missing | n/a | **partial** | User/CLI guides; align with MCP | `docs/user_guides/CLI_USAGE.md`, CLI_MCP_* root docs | **P1** | User journey tasks |
| **config** | 2 | 3 | n/a | current* | missing | missing | partial | **partial** | `docs/configuration.md` | Package config notes | **P0** | IPFSDOC-091 |
| **core_operations** | 10 | 0 | partial | partial | missing | current* | n/a | **partial** | Architecture domain map + API | `docs/CORE_OPERATIONS_GUIDE.md`, `docs/api/CORE_OPERATIONS_API.md` | **P1** | API / domain map |
| **multimedia** | 0 | 0 | planned | partial | missing | missing | n/a | **planned** (submodule-empty) | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | Empty dir / submodule; MULTIMEDIA_* root docs historical risk | **P1** | IPFSDOC-020; submodule honesty |
| **ipfs_cluster** | 2 | 0 | planned | missing | missing | missing | n/a | **planned** | Storage / IPFS architecture leaves | Sparse code | **P1** | Storage wave |
| **workflow_automation** | 7 | 0 | missing | missing | missing | missing | n/a | **missing** | Future runtime or ops leaf (no exclusive task yet) | Sparse code | **P2** | Track; do not invent status |
| **dashboards** | 19 | 0 | missing | partial | missing | missing | partial | **missing** / partial | Ops/guides if productized | Finance/dashboard guides under `docs/guides/` | **P2** | Review product status first |
| **accelerate_integration** | 4 | 0 | planned | missing | missing | missing | n/a | **planned** | Runtime / supervisor ownership docs | Compat with `ipfs_accelerate` placement | **P1** | IPFSDOC-017 |
| **admin** | 2 | 0 | missing | missing | missing | missing | partial | **missing** | Ops if exposed | Thin | **P2** | |
| **alerts** | 5 | 0 | missing | missing | missing | missing | partial | **missing** | Ops observability | Thin | **P2** | MCP observability leaf |
| **analytics** | 6 | 0 | missing | missing | missing | missing | n/a | **missing** | API domain if public | Thin | **P2** | |
| **error_reporting** | 9 | 2 | missing | partial | missing | missing | partial | **partial** | Developer troubleshooting + ops | `docs/guides/ERROR_REPORTING*.md` | **P1** | FOR_AGENTS / troubleshooting |
| **install** | 0 | 0 | n/a | n/a | n/a | n/a | n/a | **n/a** | — | Empty package dir | — | Do not document as feature |
| **messaging** | 2 | 0 | missing | missing | missing | missing | n/a | **missing** | n/a until productized | Thin | **P2** | |
| **rate_limiting** | 2 | 0 | missing | missing | missing | missing | partial | **missing** | Ops / MCP policy | Thin | **P2** | |
| **scripts** | 7 | 0 | n/a | n/a | partial | n/a | n/a | **n/a** (dev utility) | Developer map | Not a product domain | — | Mention in repository map only |
| **sessions** | 2 | 0 | missing | missing | missing | missing | n/a | **missing** | Runtime if public | Thin | **P2** | |
| **skills** | 1 | 2 | missing | n/a | partial | missing | n/a | **missing** | Agent developer guides | Package skill refs | **P1** | FOR_AGENTS |
| **static** | 0 | 1 | n/a | n/a | n/a | n/a | n/a | **n/a** | — | Assets only | — | |
| **templates** | 0 | 0 | n/a | n/a | n/a | n/a | n/a | **n/a** | — | Empty / non-doc | — | |
| **tests** (in-package) | 17 | 0 | n/a | n/a | partial | n/a | n/a | **n/a** | Testing guides | Not production runtime | — | `TESTING_AND_EVIDENCE` |
| **utils** | 46 | 9 | n/a | n/a | partial | missing | n/a | **partial** | Developer / API as needed | Mixed READMEs | **P2** | |

\*“current*” API cells mark navigated or substantial hand pages that still need
provenance refresh against code.

### 2.2 Profile G (explicit row)

**Profile G** is not a top-level package directory; it is a **production
runtime/planning surface** required by validation and architecture tasks.

| Concern | Code anchors | Doc today | Target canonical | Status | Gap pri |
| --- | --- | --- | --- | --- | --- |
| Datasets Profile G primitives | `ipfs_datasets_py/profile_g.py` → `logic.profile_g` | `docs/profile_g_datasets_provider.md` | Same + architecture runtime leaf | **current** provider note; **planned** architecture | **P0** |
| Planning / risk / evidence / CID | `logic/profile_g`, MCP `profile_g_service` | Partial provider doc; security_verification plans | `docs/architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md` | **planned** | **P0** |
| Agent supervisor taskboards / worktrees | External `ipfs_accelerate` ownership; datasets compat | Missing unified arch | `docs/architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md` | **planned** | **P0** |
| MCP++ / transport boundaries | `mcp_server` Profile G service | Scattered MCP docs | `docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md` | **planned** | **P0** |

**Invariant for all Profile G docs:** placement is advisory; execution, leases,
and side effects remain external and **fail closed** unless validators are
configured (do not document UI visibility as authorization).

### 2.3 Package-root modules (cross-cutting, not directories)

| Module | Role | Coverage | Target | Status | Gap pri |
| --- | --- | --- | --- | --- | --- |
| `ipfs_datasets.py` / dataset manager | Core dataset API | Partial user/API | Domain map + user guide + API domains | **partial** | **P0** |
| `security.py` | Security surface | Partial security guides | Security guides + logic authz | **partial** | **P0** |
| `lazy_dependencies.py` / deps resolvers | Optional capability loading | Partial install docs | Installation + dependency architecture | **partial** | **P0** |
| `*router*.py` | Backend routers | Partial | Integration boundaries + domain leaves | **planned** | **P1** |
| `monitoring*.py` | Observability | Partial ops | MCP audit/observability + ops | **planned** | **P1** |
| `profile_g.py` | Profile G facade | Provider doc current | Runtime architecture | **planned** | **P0** |
| `voice_router.py` | Voice entry | Missing | Voice / immutable releases | **planned** | **P0** |

---

## 3. Architecture subtree coverage (program targets)

Target tree from plan §6. Status as of this worktree:

| Target path | Status | Notes |
| --- | --- | --- |
| `docs/architecture/README.md` | **current** (thin hub) | Expand after leaves (IPFSDOC-090) |
| `docs/architecture/SYSTEM_CONTEXT.md` | **planned** / **missing** | IPFSDOC-010 |
| `docs/architecture/DOMAIN_MAP.md` | **planned** / **missing** | IPFSDOC-010; must list processors, logic, mcp_server, optimizers, knowledge_graphs, vector_stores, wallet, voice |
| `docs/architecture/END_TO_END_DATA_FLOW.md` | **planned** | System architecture wave |
| `docs/architecture/DEPENDENCY_AND_INITIALIZATION.md` | **planned** | |
| `docs/architecture/INTEGRATION_BOUNDARIES.md` | **planned** | |
| `docs/architecture/processing/` | **planned** / **missing** | processors, multimedia, web/legal |
| `docs/architecture/storage/` | **planned** / **missing** | IPLD, cache, P2P, **voice**, **huggingface** releases |
| `docs/architecture/retrieval/` | **planned** / **missing** | embeddings, vector_stores, search |
| `docs/architecture/knowledge/` | **planned** / **missing** | knowledge_graphs, GraphRAG, optimizers |
| `docs/architecture/logic/` | **planned** / **missing** | IR family, provers, authz |
| `docs/architecture/mcp/` | **planned** / **missing** | mcp_server spine; ADRs remain package-local until reconcile |
| `docs/architecture/runtime/` | **planned** / **missing** | Agent supervisor + **Profile G** |
| `docs/architecture/WALLET_TRUST_AND_PRIVACY.md` | **planned** / **missing** | **wallet** trust model |
| `docs/architecture/decisions/` | **partial** | Templates present; MCP ADR bodies still under package; index task IPFSDOC-016 |
| `docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md` | **current** | IPFSDOC-003 |

---

## 4. High-attention domains (detail)

### 4.1 processors

| Aspect | Assessment |
| --- | --- |
| Code | Largest domain (~974 py); pipelines, legal scrapers, file conversion, multimedia paths |
| Docs volume | High package md + `docs/guides/processors/` + archive refactor corpus |
| Canonical today | **None clean** — best interim: `PROCESSORS_ARCHITECTURE.md` (refresh-and-surface) |
| Target | `docs/architecture/processing/{README,PROCESSOR_PIPELINE,FILE_AND_MULTIMEDIA,WEB_ARCHIVING_AND_LEGAL_INGESTION}.md` |
| Risks | Historical “complete” refactor reports; empty multimedia submodule |
| Gap | **P0** architecture spine; **P1** API domain map |

### 4.2 logic

| Aspect | Assessment |
| --- | --- |
| Code | ~650 py; IR families, compilers, provers, Profile G logic, legal/security IR |
| Docs volume | Largest docs hub (`docs/logic/` ~267 md) mixed plans + guides + CEC |
| Canonical today | Fragmented; versioned COMPREHENSIVE_LOGIC_REFACTORING plans are **not** authority |
| Target | `docs/architecture/logic/*` (IR, compilers, provers, constraints, authz, result authority) |
| Risks | Plan inflation mistaken for shipped architecture |
| Gap | **P0** IR identity + authorization boundaries |

### 4.3 mcp_server

| Aspect | Assessment |
| --- | --- |
| Code | ~531 py; tools, transports, policy, Profile G service |
| Docs volume | Highest package-local concentration (176 md) including **6 accepted ADRs** |
| Canonical today | **ADRs current**; server architecture still multi-home |
| Target | `docs/architecture/mcp/*` + `docs/guides/operations/MCP_SERVER_RUNBOOK.md` |
| Risks | Tool-count and “complete” claims in root MCP status docs (see drift matrix) |
| Gap | **P0** server/dispatch, tool lifecycle, policy, ops runbook |

### 4.4 wallet

| Aspect | Assessment |
| --- | --- |
| Code | Dedicated `wallet/` package (models, privacy, multisig, proofs, storage) |
| Docs volume | No package-local md; large `docs/security_verification/` xaman/wallet evidence set |
| Canonical today | **missing** product architecture; security_verification is evidence/plan-heavy |
| Target | `docs/architecture/WALLET_TRUST_AND_PRIVACY.md` + security audit guide |
| Gap | **P0** — trust, privacy, simulated vs real effects |

### 4.5 voice

| Aspect | Assessment |
| --- | --- |
| Code | Schema, normalize, materialize, GraphRAG-safe paths, HF release hooks |
| Docs volume | None package-local |
| Canonical today | **missing** |
| Target | Immutable dataset releases architecture (voice + HF) |
| Gap | **P0** for release identity, dry-run boundary, append-only publish |

### 4.6 huggingface

| Aspect | Assessment |
| --- | --- |
| Code | repository, snapshot, publisher, release, bucket helpers |
| Docs volume | None package-local |
| Canonical today | **missing** as domain guide; may appear inside install or publication notes |
| Target | Storage P2P/publication + immutable releases |
| Gap | **P0** with voice release path; **P1** standalone API page |

### 4.7 Profile G

| Aspect | Assessment |
| --- | --- |
| Code | Facade + logic implementation + MCP service |
| Docs volume | Provider page present; full planning/evidence architecture planned |
| Canonical today | **partial** (`profile_g_datasets_provider.md`) |
| Target | Runtime architecture pair (supervisor + Profile G) |
| Gap | **P0** fail-closed execution, CID/canonicalization, risk evidence |

---

## 5. P0 and P1 gap register

### 5.1 P0 gaps (block truthful core documentation)

| ID | Gap | Domains / audiences | Planned remedy |
| --- | --- | --- | --- |
| G-P0-01 | No SYSTEM_CONTEXT / DOMAIN_MAP | all architects; all domains | IPFSDOC-010 |
| G-P0-02 | processors lack canonical architecture spine | processors | processing/* tasks |
| G-P0-03 | logic lacks canonical architecture spine (plans dominate) | logic | logic/* tasks |
| G-P0-04 | mcp_server architecture multi-home; ops runbook missing | mcp_server, operator | mcp/* + MCP_SERVER_RUNBOOK |
| G-P0-05 | wallet trust/privacy architecture missing | wallet, security | WALLET_TRUST_AND_PRIVACY |
| G-P0-06 | voice + huggingface release architecture missing | voice, huggingface, storage | IMMUTABLE_DATASET_RELEASES + publication |
| G-P0-07 | Profile G planning/evidence architecture incomplete | Profile G, agent, mcp | runtime/* IPFSDOC-017 |
| G-P0-08 | Agent-facing FOR_AGENTS missing | agent | developer_guides |
| G-P0-09 | Product entry pages present but drift-heavy | end-user | install/user/features claim repair |
| G-P0-10 | Audit/provenance product guide incomplete vs code | audit, security | security guides wave |

### 5.2 P1 gaps

| ID | Gap | Domains | Planned remedy |
| --- | --- | --- | --- |
| G-P1-01 | Retrieval spine (embeddings, vector_stores, search) | embeddings, vector_stores, search, ml | retrieval/* |
| G-P1-02 | Knowledge / GraphRAG / optimizers architecture | knowledge_graphs, optimizers | knowledge/* |
| G-P1-03 | Storage/IPLD/cache/P2P unified architecture | storage, caching, p2p_networking, ipfs_cluster | storage/* |
| G-P1-04 | Web archiving / legal ingestion architecture | web_archiving, processors legal | processing web/legal |
| G-P1-05 | Hand API domain maps sparse (`docs/api/` thin) | many | API domain tasks |
| G-P1-06 | CLI ↔ MCP alignment docs fragmented | cli, mcp_server | user + MCP leaves |
| G-P1-07 | Extension recipes + testing evidence guides | developer | developer_guides |
| G-P1-08 | Legacy disposition for competing hubs | logic, processors, optimizers, MCP | LEGACY_DISPOSITION |
| G-P1-09 | Multimedia honesty (submodule-empty) | multimedia, processors | processing FILE_AND_MULTIMEDIA |
| G-P1-10 | Error reporting / troubleshooting spine | error_reporting, agent | TROUBLESHOOTING |

### 5.3 Explicit non-goals of this matrix

- Does not mark board todo metadata complete.
- Does not authorize bulk archive moves.
- Does not claim MkDocs site build success.
- Does not treat empty directories (`install/`, `multimedia/`, `templates/`) as features.

---

## 6. Crosswalk: coverage status → writer action

| If status is… | Writer must… |
| --- | --- |
| **current** | Cite as home; refresh against SOURCE_AUTHORITY ranks 1–5; fix drift items |
| **planned** | Write the named target path only; link interim bodies; do not invent a second root |
| **missing** | Do not claim coverage; either implement the planned task or file a board gap |
| **n/a** | Omit from product navigation; optional one-line note in domain map |

---

## 7. Related maintenance artifacts

| Artifact | Role |
| --- | --- |
| [SOURCE_AUTHORITY.md](SOURCE_AUTHORITY.md) | Ranked sources when claims conflict |
| [INFORMATION_ARCHITECTURE.md](INFORMATION_ARCHITECTURE.md) | Audiences, lifecycle, contracts |
| [PACKAGE_LOCAL_DOCUMENTATION_MAP.md](PACKAGE_LOCAL_DOCUMENTATION_MAP.md) | Package vs docs disposition |
| [CURRENT_STATE_BASELINE.md](CURRENT_STATE_BASELINE.md) | Domain counts and inventory |
| [DRIFT_AND_CLAIM_MATRIX.md](DRIFT_AND_CLAIM_MATRIX.md) | Claim-level repair queue |

---

## 8. Validation

```bash
test -s docs/maintenance/SOURCE_AUTHORITY.md && \
  test -s docs/maintenance/COVERAGE_MATRIX.md && \
  rg -n 'processors|logic|mcp_server|wallet|voice|huggingface|Profile G' \
    docs/maintenance/COVERAGE_MATRIX.md
```

### Re-measure domain inventory (optional)

```bash
# Top-level package domains
find ipfs_datasets_py -mindepth 1 -maxdepth 1 -type d | wc -l
for d in ipfs_datasets_py/*/; do
  b=$(basename "$d")
  printf '%s py=%s md=%s\n' "$b" \
    "$(find "$d" -name '*.py' 2>/dev/null | wc -l)" \
    "$(find "$d" -name '*.md' 2>/dev/null | wc -l)"
done | sort
```

---

## 9. Acceptance checklist (IPFSDOC-005 — coverage half)

| Criterion | Evidence |
| --- | --- |
| Every top-level production domain mapped | §2.1 full directory table |
| Target audiences mapped | §1 |
| Status ∈ {current, planned, missing, n/a} | Status columns throughout |
| P0/P1 gaps listed | §5 |
| processors, logic, mcp_server, wallet, voice, huggingface, Profile G appear | §2.1, §2.2, §4 |
| Validation command terms present | §8 and body headings/rows |
