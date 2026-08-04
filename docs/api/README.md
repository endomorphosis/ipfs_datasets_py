# API reference index

| Field | Value |
| --- | --- |
| Interface | `APIReferenceIndex@1` |
| Task | `IPFSDOC-082` |
| Status | `canonical` |
| Owner | api-reference |
| Source of truth | Domain pages under `docs/api/domains/`; package exports and ASTs under `ipfs_datasets_py/`; [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md); [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md); generation provenance in [GENERATION_AND_FRESHNESS.md](GENERATION_AND_FRESHNESS.md) |
| Last verified | 2026-08-03 |
| Audience | developer, agent, operator, architect |
| Related | [architecture/README.md](../architecture/README.md), [RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md), [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md) |
| Review cadence | after domain API page refresh, export/`__all__` changes, or generation-script changes |

> **What this page is:** the single **canonical entry** for source-grounded
> callable API maps. It routes conceptual concerns to domain reference pages.
>
> **What this page is not:** a full method dump, a substitute for domain leaves,
> or a promise that every importable symbol is a stable public contract.
> Exhaustive internal AST listings are **not** a public contract.

---

## 1. Purpose

Use this index when you need to:

1. **Find the right domain page** for a callable surface (datasets, processors,
   logic, MCP, ops).
2. **Prefer canonical imports** over compatibility aliases and root re-exports.
3. **Read stability and authority** (public / reviewed / compatibility /
   internal) instead of treating importability as a stability promise.
4. **Distinguish hand-maintained domain maps** from legacy generated dumps
   (optimizers dump, TDFOL Sphinx tree, stub markdown).

Deep contracts live in [domains/](domains/). Generation lifecycle, coverage
limits, and signature-drift checks live in
[GENERATION_AND_FRESHNESS.md](GENERATION_AND_FRESHNESS.md).

Authority order when sources disagree
([SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md)):

1. executable tests and schemas that define a contract;
2. current implementation and packaging/configuration metadata;
3. current operator configuration and deployment manifests;
4. accepted architecture decision records;
5. maintained guides (including this index and domain API pages);
6. historical plans, completion reports, **generated** listings, and archive material.

---

## 2. How to use this index

1. Start from the **conceptual route** table (§3) or the **domain catalog** (§4).
2. Open the domain page and use its **canonical import** and **Source** rows.
3. Respect **Stability** tags: only `public` / `reviewed` rows are intended
   external contracts; `compatibility` means prefer the canonical target;
   `internal` has no stability promise.
4. For optimizers discovery dumps, TDFOL Sphinx HTML, or `*_stubs.md`, see §6
   and [GENERATION_AND_FRESHNESS.md](GENERATION_AND_FRESHNESS.md) — do **not**
   treat them as the product API contract.
5. When a signature in docs disagrees with source, re-check AST/`__all__` and
   tests; follow the drift procedures in GENERATION_AND_FRESHNESS.

### Hard rules

| Rule | Meaning |
| --- | --- |
| Importability ≠ public stability | A symbol may import and still be internal, optional, simulated, or compatibility-only |
| Domain pages outrank dumps | `domains/*.md` + live AST beat auto-generated method lists |
| Result authority is domain-specific | Dict envelopes, proof receipts, policy allow, and MCP health are not interchangeable (see domain legends) |
| No exhaustive AST as public API | Full tree dumps are discovery aids only; public contract is the reviewed export map on each domain page |

---

## 3. Conceptual-to-domain routes

Map the **concern** (not the wrapper layer) to the domain reference page.
Architecture ownership is in [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md);
this table is the **callable API** route only.

| Conceptual concern | Go to domain page | Typical packages / entry modules | Architecture companions |
| --- | --- | --- | --- |
| Dataset load / save / convert | [CORE_AND_DATA.md](domains/CORE_AND_DATA.md) | `core_operations` (`DatasetLoader`, `DatasetSaver`, `DatasetConverter`); `dataset_manager`; package load helpers | [storage/](../architecture/storage/) |
| IPFS pin / get / content address | [CORE_AND_DATA.md](domains/CORE_AND_DATA.md) | `core_operations` (`IPFSPinner`, `IPFSGetter`); `storage`; `ipfs_backend_router` | [CONTENT_ADDRESSING_AND_IPLD.md](../architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md) |
| Storage engines, cache, backends | [CORE_AND_DATA.md](domains/CORE_AND_DATA.md) | `storage`, `caching` | [STORAGE_CACHING_AND_BACKENDS.md](../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md) |
| Web archive / publication / HF push | [CORE_AND_DATA.md](domains/CORE_AND_DATA.md) | `web_archiving`, `huggingface`, `p2p_networking` | [P2P_AND_PUBLICATION.md](../architecture/storage/P2P_AND_PUBLICATION.md) |
| Data / logic **core-ops** processors | [PROCESSING_AND_RETRIEVAL.md](domains/PROCESSING_AND_RETRIEVAL.md) | `core_operations.DataProcessor`, `LogicProcessor` | [PROCESSOR_PIPELINE.md](../architecture/processing/PROCESSOR_PIPELINE.md) |
| Multimodal / file / domain processors | [PROCESSING_AND_RETRIEVAL.md](domains/PROCESSING_AND_RETRIEVAL.md) | `processors` (protocol, universal processor, PDF, OCR, scrapers, conversion) | [FILE_AND_MULTIMEDIA.md](../architecture/processing/FILE_AND_MULTIMEDIA.md) |
| Embeddings and indexing | [PROCESSING_AND_RETRIEVAL.md](domains/PROCESSING_AND_RETRIEVAL.md) | `embeddings`, related `ml` paths | [EMBEDDINGS_AND_INDEXING.md](../architecture/retrieval/EMBEDDINGS_AND_INDEXING.md) |
| Vector stores / ANN backends | [PROCESSING_AND_RETRIEVAL.md](domains/PROCESSING_AND_RETRIEVAL.md) | `vector_stores` | [VECTOR_STORES.md](../architecture/retrieval/VECTOR_STORES.md) |
| Search / hybrid query | [PROCESSING_AND_RETRIEVAL.md](domains/PROCESSING_AND_RETRIEVAL.md) | `search` | [SEARCH_AND_QUERY.md](../architecture/retrieval/SEARCH_AND_QUERY.md) |
| Knowledge graphs / GraphRAG façades | [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | `knowledge_graphs`; core `KnowledgeGraphManager` | [knowledge/](../architecture/knowledge/) |
| Optimizer loops (GraphRAG, agentic, theorem) | [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | `optimizers` (`BaseOptimizer` and product trees) | knowledge + logic leaves |
| IR families / compilers / formalization | [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | `logic.ir_core`, `intent_ir`, `legal_ir`, `security_ir`, `formalization` | [logic/](../architecture/logic/) |
| Provers, hammers, proof corpus | [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | `logic.external_provers`, `proof_corpus`, TDFOL under `logic` | [RESULT_AUTHORITY.md](../architecture/logic/RESULT_AUTHORITY.md) |
| Admissibility / policy / Profile D–G helpers | [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | `logic.admissibility`, `profile_d_policy`, `profile_g` | ADR-003, ADR-004 |
| MCP server / tools / client / transports | [MCP_AND_RUNTIME.md](domains/MCP_AND_RUNTIME.md) | `mcp_server` | [mcp/](../architecture/mcp/), [RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md) |
| Process entrypoints (CLI / stdio / HTTP) | [MCP_AND_RUNTIME.md](domains/MCP_AND_RUNTIME.md) | `mcp_server` start helpers; package scripts | [RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md) |
| Audit, wallet, UCAN, workflow, config | [OPERATIONS_AND_INTEGRATIONS.md](domains/OPERATIONS_AND_INTEGRATIONS.md) | `audit`, `wallet`, `workflow_automation`, `config`, `security`, monitoring | [WALLET_TRUST_AND_PRIVACY.md](../architecture/WALLET_TRUST_AND_PRIVACY.md), security guides |

**Thin wrappers:** MCP tools and CLI commands are expected to call domain
engines, not redefine them. When a tool name and a Python class both exist,
the domain page names the **engine** contract; MCP framing is on
[MCP_AND_RUNTIME.md](domains/MCP_AND_RUNTIME.md).

---

## 4. Domain catalog (canonical API maps)

These five pages are the **hand-maintained, source-grounded** API reference
spine for the product. Each lists reviewed exports, stability, sync/async,
side effects, optional requirements, and canonical imports.

| Domain page | Interface | Covers | Task |
| --- | --- | --- | --- |
| [domains/CORE_AND_DATA.md](domains/CORE_AND_DATA.md) | `CoreDataAPIReference@1` | Eight `core_operations` exports (dataset + IPFS subset fully specified); storage; archive; publication | IPFSDOC-080 |
| [domains/PROCESSING_AND_RETRIEVAL.md](domains/PROCESSING_AND_RETRIEVAL.md) | `ProcessingRetrievalAPIReference@1` | `DataProcessor` / `LogicProcessor`; processors protocol; embeddings; vector stores; search | IPFSDOC-080 |
| [domains/KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) | `KnowledgeLogicAPIReference@1` | Knowledge graphs; optimizers; IR/compilers/provers; policy and proof authority | IPFSDOC-081 |
| [domains/MCP_AND_RUNTIME.md](domains/MCP_AND_RUNTIME.md) | `MCPRuntimeAPIReference@1` | MCP server, tools, interfaces, client, transports, dispatch pipeline | IPFSDOC-081 |
| [domains/OPERATIONS_AND_INTEGRATIONS.md](domains/OPERATIONS_AND_INTEGRATIONS.md) | `OperationsAPIReference@1` | Audit; wallet; workflow; config; monitoring/security; integration attach points | IPFSDOC-081 |

### 4.1 Shared legend (all domain pages)

| Tag | Meaning |
| --- | --- |
| **Stability: public** | Preferred external contract; breaking changes require review |
| **Stability: reviewed** | Exported and exercised by tests/MCP/CLI; module AST is authority for the listed surface |
| **Stability: compatibility** | Alias, lazy re-export, dual path, or migration shim — prefer the canonical target |
| **Stability: internal** | Present in tree; **no** public stability promise |
| **Source** | Module path and symbol that authorize the row |
| **Optional** | Extras, binaries, submodules, network, or env flags |
| **Side effects** | I/O, network, pins, model download, prover binaries, audit writes |

### 4.2 Core-operations export map (quick)

All eight reviewed exports are imported from one canonical package:

```python
from ipfs_datasets_py.core_operations import (
    DatasetLoader,
    DatasetSaver,
    DatasetConverter,
    IPFSPinner,
    IPFSGetter,
    KnowledgeGraphManager,
    DataProcessor,
    LogicProcessor,
)
```

| Export | Primary domain page |
| --- | --- |
| `DatasetLoader`, `DatasetSaver`, `DatasetConverter` | [CORE_AND_DATA.md](domains/CORE_AND_DATA.md) |
| `IPFSPinner`, `IPFSGetter` | [CORE_AND_DATA.md](domains/CORE_AND_DATA.md) |
| `KnowledgeGraphManager` | [CORE_AND_DATA.md](domains/CORE_AND_DATA.md) (core façade); knowledge depth in [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) |
| `DataProcessor`, `LogicProcessor` | [PROCESSING_AND_RETRIEVAL.md](domains/PROCESSING_AND_RETRIEVAL.md) |

**Source:** `ipfs_datasets_py/core_operations/__init__.py` `__all__`.

---

## 5. Audience routes

| Audience | Start here | Then |
| --- | --- | --- |
| **Developer / library caller** | This index → domain page for the concern | Canonical import cheat sheets on the domain page; package tests |
| **Agent / automation** | This index + [GENERATION_AND_FRESHNESS.md](GENERATION_AND_FRESHNESS.md) | Domain pages with stable headings; never invent success from partial envelopes |
| **Operator** | [MCP_AND_RUNTIME.md](domains/MCP_AND_RUNTIME.md) + [OPERATIONS_AND_INTEGRATIONS.md](domains/OPERATIONS_AND_INTEGRATIONS.md) | Ops runbooks under `docs/guides/operations/` (procedures, not API contracts) |
| **Security / policy reviewer** | [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) + [OPERATIONS_AND_INTEGRATIONS.md](domains/OPERATIONS_AND_INTEGRATIONS.md) | [RESULT_AUTHORITY.md](../architecture/logic/RESULT_AUTHORITY.md); wallet/audit inequalities on ops page |
| **Architect** | [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md) first | Domain API pages only for **callable** surface; ownership stays on architecture leaves |

---

## 6. Legacy, generated, and non-canonical API artifacts

These live under or near `docs/api/` (or parallel trees) but are **not** the
canonical product API contract. Classification detail:
[GENERATION_AND_FRESHNESS.md](GENERATION_AND_FRESHNESS.md).

| Artifact | Path | Lifecycle | How to treat |
| --- | --- | --- | --- |
| Optimizers auto-dump | [OPTIMIZERS_API_REFERENCE.md](OPTIMIZERS_API_REFERENCE.md) | `generated` | Discovery of class/method **names** only; regenerate via `scripts/documentation/generate_optimizer_api_reference.py`. Stability and authority: [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) |
| Legacy core-ops note | [CORE_OPERATIONS_API.md](CORE_OPERATIONS_API.md) | `historical` / superseded for method names | Prefer [CORE_AND_DATA.md](domains/CORE_AND_DATA.md); legacy file may retain wrong method names |
| TDFOL Sphinx sources + build | `docs/tdfol/` (`.rst`, `_build/`) | `generated` / domain-local Sphinx | Optional deep reference for TDFOL modules under `logic`; not a product-wide public contract; rebuild from sources when needed |
| Optimizer stub dumps | `docs/optimizers/*_stubs.md` | `generated` | Signature dumps; do not cite for behavior contracts |
| Auto-generated stubs policy | `docs/auto_generated_stubs/` | `generated` policy (tree largely empty of active stubs) | Policy note only unless new stubs are regenerated into the tree |
| Archived processor stubs | `docs/archived_stubs/` | `historical` | Preserved for audit; not current API |
| Marketing-style API guide | `docs/guides/reference/api_reference.md` | `review-needed` / drift risk | Not the domain spine; known stale method examples — do not prefer over `domains/*` |
| Logic package API notes | `docs/logic/API_REFERENCE.md` and related | Mixed | Route formal surfaces through [KNOWLEDGE_LOGIC_AND_PROOF.md](domains/KNOWLEDGE_LOGIC_AND_PROOF.md) |

**MkDocs note:** The site nav may still list Optimizers API and Core Operations
API for continuity. Those pages are **secondary**. This README and the five
domain pages are the maintained API entry.

---

## 7. Related navigation

| Need | Page |
| --- | --- |
| Generation inputs, coverage, limitations, freshness, drift detection | [GENERATION_AND_FRESHNESS.md](GENERATION_AND_FRESHNESS.md) |
| Domain ownership (architecture) | [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md) |
| Architecture hub | [architecture/README.md](../architecture/README.md) |
| How to start processes | [RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md) |
| Doc lifecycle and placement | [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md) |
| Source authority order | [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) |
| Claim / signature drift inventory (program-wide) | [DRIFT_AND_CLAIM_MATRIX.md](../maintenance/DRIFT_AND_CLAIM_MATRIX.md) |

---

## 8. Validation (this index)

```bash
test -s docs/api/README.md
test -s docs/api/GENERATION_AND_FRESHNESS.md
test -s docs/api/domains/CORE_AND_DATA.md
test -s docs/api/domains/PROCESSING_AND_RETRIEVAL.md
test -s docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md
test -s docs/api/domains/MCP_AND_RUNTIME.md
test -s docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md
rg -n 'CORE_AND_DATA|PROCESSING_AND_RETRIEVAL|KNOWLEDGE_LOGIC_AND_PROOF|MCP_AND_RUNTIME' docs/api/README.md
```

Re-verify domain pages after export or signature changes; re-run generation
only for dumps listed in GENERATION_AND_FRESHNESS, never as a replacement for
hand-maintained stability labels.
